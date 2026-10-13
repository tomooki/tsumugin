"""テンプレートの pass 1 — 判断を決める前処理 fit (proposal §4.3, REQ-FTJ-1B-301〜304)。

pass 1 は pass 2 と同じ段 0–4 を走らせ、次を決めて ``evidence`` に記録する (何を見てどう決めたか):

- **格子を凍結する相**: 段 1 が棄却されたら全体を戻し (engine は毎回 CIF から組み立てるので、やり直しは
  自然に段 1 の前から始まる)、1 相ずつ格子を外した fit を比べて帰属させる。段 0 の強度での事前凍結はしない。
- **対象相**: 段 4 の後の相ごとの積分計算強度 Σ Fc²·Icorr の最大。2 位/1 位が ``target_tie_ratio`` 以上
  (または宣言と食い違う・計測できない) なら「僅差」= 判断要求の印。
- **背景の項数**: 段 4 の後に項数を増やす段を並べ、隣り合う段の Hamilton 検定 (実効自由度で補正) で
  有意でなくなる手前を採る。棄却された段は「有意でない」。
- **Zero** (Bragg-Brentano): 最後に Zero だけを足す段を置き、直前の段と Hamilton 検定。有意なら格子に
  ``{Shift, Zero}`` の相関と非 blocking な判断要求。pass 2 は Zero を装置値のまま (= D の既定)。
- **Uiso のまとめ方**: 対象相の CIF に (元素, 配位数) の規則 (`template.uiso`)。

検定の fit が失敗・発散したら「反証なし」ではなく ``unevaluated`` にして既定側を採る (REQ-FTJ-1B-302)。
runner は注入する (``runner(trial, histograms, phases, stages) -> AutoRietveldResult``)。決定論 (REQ-FTJ-1B-304)。

⚠ Zero の検定は背景の段の後に置く (別の fit を回さないため)。背景の段が「有意でない」と判定されても engine の
revert ガードは受理していることがあるので、Zero の検定の基準は**実際の直前の状態**であって、採用した項数の
状態ではない。位置の項と背景の項数の相関は弱いので、この差は判定に効かないと見込む (P1.5 で確かめる)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

import numpy as np

from ..autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    RefinementStage,
    StageResult,
)
from ..evidence.fitstats import chi2_from_stage, effective_dof_ratio, hamilton_test
from ..errors import TsumuginError
from .compile import TemplateDecisions, pass1_stages
from .declarations import TemplateDeclarations
from .uiso import uiso_groups_from_cif

__all__ = [
    "Pass1Config",
    "Pass1Error",
    "Pass1Outcome",
    "Pass1Runner",
    "run_template_pass1",
]

#: ``runner(trial, histograms, phases, stages)``。``trial`` は成果物の名前 (gpx の label) に使う。
Pass1Runner = Callable[
    [str, Sequence[HistogramSpec], Sequence[PhaseSpec], tuple[RefinementStage, ...]],
    AutoRietveldResult,
]


class Pass1Error(TsumuginError, RuntimeError):
    """pass 1 の基準の fit (段 0–4) が回らなかった — テンプレート候補は立たない。"""


@dataclass(frozen=True)
class Pass1Config:
    """pass 1 の閾値。値は P1.5 で調整する (今の値は「動くこと」のための仮置き)。"""

    alpha: float = 0.01
    background_ladder: tuple[int, ...] = (12, 18, 24)
    target_tie_ratio: float = 0.8

    def to_dict(self) -> dict[str, object]:
        return {
            "alpha": self.alpha,
            "background_ladder": list(self.background_ladder),
            "target_tie_ratio": self.target_tie_ratio,
        }


@dataclass(frozen=True)
class Pass1Outcome:
    """pass 1 の結果。``decisions`` をコンパイルに渡し、``evidence`` を derivation に載せる。

    :param target_phase_ambiguous: 対象相が僅差・宣言と食い違う・計測できない (blocking な判断要求)
    :param zero_offset_significant: Zero が有意 (非 blocking な判断要求)。検定しなかった/できなかったら None
    """

    decisions: TemplateDecisions
    evidence: Mapping[str, object]
    target_phase_ambiguous: bool
    zero_offset_significant: "bool | None"
    results: Mapping[str, "AutoRietveldResult | None"] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 小さな部品 (純関数)
# ---------------------------------------------------------------------------


def _stage(result: AutoRietveldResult, prefix: str) -> "StageResult | None":
    for st in result.stage_results:
        if st.label.split(" ", 1)[0] == prefix:
            return st
    return None


def _chi2(st: StageResult, n_obs: int) -> "float | None":
    return chi2_from_stage(gof=st.gof, n_obs=n_obs, n_params=st.n_params)


def _weighted_residual(result: AutoRietveldResult) -> "np.ndarray | None":
    r = np.asarray(result.residual_intensity, dtype=float)
    s = np.asarray(result.residual_sigma, dtype=float)
    if r.size == 0 or r.shape != s.shape:
        return None
    ok = np.isfinite(r) & np.isfinite(s) & (s > 0)
    return r[ok] / s[ok] if ok.any() else None


def _phase_labels(result: AutoRietveldResult) -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for source in (result.atom_uiso, result.atom_coords):
        for phase, atoms in source.items():
            if atoms and phase not in out:
                out[phase] = tuple(atoms)
    return out


def _decide_target(
    result: AutoRietveldResult,
    phases: Sequence[PhaseSpec],
    declared: "str | None",
    tie_ratio: float,
    *,
    exclude: "str | None" = None,
) -> tuple[str, bool, dict[str, object]]:
    # 内部標準は対象相にしない (強い散乱体であることが多く、強度で選ぶと標準が選ばれてしまう)
    names = [p.phase_name for p in phases if p.phase_name != exclude] or [
        p.phase_name for p in phases
    ]
    if len(names) == 1:
        return names[0], False, {"decision": names[0], "basis": "single_phase", "status": "pass"}
    pii = result.phase_integrated_intensity
    intensity: dict[str, "float | None"] = {}
    for n in names:
        vals = (pii or {}).get(n)
        v = vals[0] if vals else None
        intensity[n] = float(v) if v is not None and math.isfinite(v) and v >= 0 else None
    if pii is None or any(v is None for v in intensity.values()):
        target = declared or names[0]
        return target, True, {
            "decision": target, "basis": "declared" if declared else "first_phase",
            "status": "unevaluated", "reason": "積分計算強度を計測できない",
            "intensity": intensity, "declared": declared,
        }
    ranked = sorted(names, key=lambda n: (-intensity[n], names.index(n)))  # type: ignore[operator]
    top, second = ranked[0], ranked[1]
    ratio = intensity[second] / intensity[top] if intensity[top] else math.inf  # type: ignore[operator]
    target = declared or top
    ambiguous = bool(ratio >= tie_ratio) or (declared is not None and declared != top)
    return target, ambiguous, {
        "decision": target, "basis": "declared" if declared else "integrated_intensity",
        "status": "pass", "intensity": intensity, "ratio": ratio if math.isfinite(ratio) else None,
        "tie_ratio": tie_ratio, "largest": top, "declared": declared, "ambiguous": ambiguous,
    }


def _background_ladder(
    result: AutoRietveldResult,
    start: int,
    ladder: Sequence[int],
    *,
    alpha: float,
    dof_ratio: float,
) -> tuple[int, list[dict[str, object]], str]:
    """隣り合う段で検定し、最初に有意でなくなった手前の項数を返す。"""
    prev = _stage(result, "T4") or _stage(result, "T2")
    tests: list[dict[str, object]] = []
    chosen, prev_n = start, start
    status = "pass"
    for n in ladder:
        st = _stage(result, f"TB{n}")
        if st is None or prev is None:
            status = "unevaluated"
            break
        row: dict[str, object] = {"from": prev_n, "to": n, "reverted": st.reverted}
        if st.reverted:
            row["significant"] = False
            tests.append(row)
            break
        c_small, c_big = _chi2(prev, result.n_obs), _chi2(st, result.n_obs)
        k = st.n_params - prev.n_params
        test = (
            hamilton_test(c_small, c_big, st.gof ** 2, k, alpha=alpha, dof_ratio=dof_ratio)
            if c_small is not None and c_big is not None else None
        )
        if test is None:
            row["significant"] = None
            tests.append(row)
            status = "unevaluated"
            break
        row.update(test.to_dict())
        tests.append(row)
        if not test.significant:
            break
        chosen, prev, prev_n = n, st, n
    return chosen, tests, status


def _zero_test(
    result: AutoRietveldResult, *, alpha: float, dof_ratio: float
) -> tuple["bool | None", dict[str, object]]:
    labels = [st.label.split(" ", 1)[0] for st in result.stage_results]
    if "TZ" not in labels:
        return None, {"status": "unevaluated", "reason": "Zero の段が結果に無い"}
    i = labels.index("TZ")
    st = result.stage_results[i]
    prev = next(
        (s for s in reversed(result.stage_results[:i]) if not s.reverted), None
    )
    if st.reverted:
        return False, {"status": "pass", "significant": False, "reverted": True}
    if prev is None:
        return None, {"status": "unevaluated", "reason": "基準の段が無い"}
    c_small, c_big = _chi2(prev, result.n_obs), _chi2(st, result.n_obs)
    test = (
        hamilton_test(c_small, c_big, st.gof ** 2, st.n_params - prev.n_params,
                      alpha=alpha, dof_ratio=dof_ratio)
        if c_small is not None and c_big is not None else None
    )
    if test is None:
        return None, {"status": "unevaluated", "reason": "検定できない (非有限・母数差 0)"}
    return test.significant, {"status": "pass", **test.to_dict()}


# ---------------------------------------------------------------------------
# 本体
# ---------------------------------------------------------------------------


def _calibrated(histograms: Sequence[HistogramSpec], decl: TemplateDeclarations) -> tuple[bool, str]:
    if decl.instrument_calibrated is not None:
        return bool(decl.instrument_calibrated), "declared(instrument_calibrated)"
    if any(h.instrument_profile is not None for h in histograms):
        return True, "instrument_profile"
    return False, "undeclared"


def run_template_pass1(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    declarations: TemplateDeclarations,
    *,
    runner: Pass1Runner,
    config: "Pass1Config | None" = None,
    background_coeffs: int = 6,
    ledger: "object | None" = None,
) -> Pass1Outcome:
    """pass 1 を回して判断を決める。

    :raises Pass1Error: 基準の fit (段 0–4) が例外で回らなかったとき (候補は立たない)
    """
    cfg = config or Pass1Config()
    declarations.check_phases(phases)
    calibrated, calibrated_basis = _calibrated(histograms, declarations)
    names = [p.phase_name for p in phases]
    results: dict[str, "AutoRietveldResult | None"] = {}

    def trial(label: str, stages: tuple[RefinementStage, ...]) -> "AutoRietveldResult | None":
        try:
            res = runner(label, histograms, phases, stages)
        except Exception as exc:  # noqa: BLE001 — 試行の失敗は判断の unevaluated に畳む
            results[label] = None
            if ledger is not None:
                ledger.append("template_pass1_trial", {"trial": label, "error": repr(exc)[:200]})  # type: ignore[attr-defined]
            return None
        results[label] = res
        if ledger is not None:
            ledger.append(  # type: ignore[attr-defined]
                "template_pass1_trial",
                {"trial": label, "final_rwp": res.final_rwp,
                 "stages": [[s.label, s.rwp, s.n_params, s.reverted] for s in res.stage_results]},
            )
        return res

    def head(cell_phases: "Sequence[str] | None", extra: Sequence[RefinementStage] = ()):
        return pass1_stages(
            histograms, phases, background_coeffs=background_coeffs,
            calibrated=calibrated, cell_phases=cell_phases, extra=extra,
        )

    # --- A: 段 0–4 ----------------------------------------------------------------
    base = trial("A", head(None))
    if base is None:
        raise Pass1Error("pass 1 の基準の fit (段 0–4) が回りませんでした")
    frozen: list[str] = []
    cell_ev: dict[str, object] = {"status": "pass", "trials": []}
    s1 = _stage(base, "T1")
    if s1 is not None and s1.reverted:
        if len(names) == 1:
            frozen = list(names)
            cell_ev["basis"] = "single_phase_stage1_reverted"
        else:
            best: "tuple[float, str] | None" = None
            for p in names:
                others = [n for n in names if n != p]
                res = trial(f"A-cell-without-{p}", head(others))
                st = _stage(res, "T1") if res is not None else None
                accepted = st is not None and not st.reverted
                rwp = res.final_rwp if res is not None else None
                cell_ev["trials"].append(  # type: ignore[union-attr]
                    {"without": p, "stage1_accepted": accepted, "final_rwp": rwp}
                )
                if accepted and rwp is not None and math.isfinite(rwp):
                    if best is None or rwp < best[0]:
                        best = (rwp, p)
            frozen = [best[1]] if best is not None else list(names)
            cell_ev["basis"] = "leave_one_out" if best is not None else "no_single_phase_explains"
        released = [n for n in names if n not in frozen]
        redo = trial("A-refrozen", head(released))
        if redo is None:
            raise Pass1Error("格子を凍結した pass 1 の fit が回りませんでした")
        base = redo
    else:
        cell_ev["basis"] = "stage1_accepted" if s1 is not None else "stage1_missing"
        if s1 is None:
            cell_ev["status"] = "unevaluated"
    cell_ev["decision"] = frozen
    cell_phases = [n for n in names if n not in frozen] if frozen else None

    # --- 対象相・実効自由度 ----------------------------------------------------------
    target, ambiguous, target_ev = _decide_target(
        base, phases, declarations.target_phase, cfg.target_tie_ratio,
        exclude=declarations.internal_standard,
    )
    resid = _weighted_residual(base)
    dof_ratio = effective_dof_ratio(resid) if resid is not None else None
    dof_ev = {"dof_ratio": dof_ratio, "status": "pass" if dof_ratio is not None else "unevaluated"}
    ratio = dof_ratio if dof_ratio is not None else 1.0

    # --- B: 背景の項数 + Zero -------------------------------------------------------
    ladder = tuple(n for n in sorted(set(cfg.background_ladder)) if n > background_coeffs)
    extra = [
        RefinementStage(f"TB{n} background", {"background": {"coeffs": n}}, f"背景 {n} 項の検定")
        for n in ladder
    ]
    bragg = histograms[0].geometry is Geometry.BRAGG_BRENTANO
    if bragg:
        extra.append(RefinementStage("TZ zero", {"zero_offset": True}, "Shift + Zero の検定"))
    tested = trial("B", head(cell_phases, extra)) if extra else None
    if tested is not None:
        bg, bg_tests, bg_status = _background_ladder(
            tested, background_coeffs, ladder, alpha=cfg.alpha, dof_ratio=ratio
        )
    else:
        bg, bg_tests = background_coeffs, []
        bg_status = "unevaluated" if extra else "pass"
    bg_ev = {"decision": bg, "status": bg_status, "start": background_coeffs,
             "ladder": list(ladder), "tests": bg_tests}
    if bragg and tested is not None:
        zero_sig, zero_ev = _zero_test(tested, alpha=cfg.alpha, dof_ratio=ratio)
    elif bragg:
        zero_sig, zero_ev = None, {"status": "unevaluated", "reason": "検定の fit が回らなかった"}
    else:
        zero_sig, zero_ev = None, {"status": "not_applicable", "reason": "Debye-Scherrer は Zero を解放する"}
    zero_ev["decision"] = "instrument_value" if bragg else "refined"
    if declarations.zero_calibrated is not None:
        zero_ev["declared_calibrated"] = declarations.zero_calibrated

    # --- Uiso のまとめ方 -----------------------------------------------------------
    labels = _phase_labels(base)
    target_spec = next(p for p in phases if p.phase_name == target)
    grouping = uiso_groups_from_cif(target_spec.structure_path, labels=labels.get(target))

    decisions = TemplateDecisions(
        target_phase=target,
        phase_labels=labels,
        frozen_cell_phases=tuple(frozen),
        background_coeffs=bg,
        uiso_groups=grouping.groups,
        calibrated=calibrated,
    )
    evidence = {
        "config": cfg.to_dict(),
        "declarations": declarations.to_dict(),
        "calibrated": {"decision": calibrated, "basis": calibrated_basis},
        "cell": cell_ev,
        "target_phase": target_ev,
        "effective_dof": dof_ev,
        "background": bg_ev,
        "zero_offset": zero_ev,
        "uiso": grouping.to_dict(),
    }
    if ledger is not None:
        ledger.append("template_pass1", {"decisions": decisions.to_dict(), "evidence": evidence})  # type: ignore[attr-defined]
    return Pass1Outcome(
        decisions=decisions, evidence=evidence, target_phase_ambiguous=ambiguous,
        zero_offset_significant=zero_sig, results=results,
    )
