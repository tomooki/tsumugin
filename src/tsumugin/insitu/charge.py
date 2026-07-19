"""FR-318 電気化学制約のモード分岐・診断レポート (numpy-only 純関数層)。🔵

`FrameSpec.target_composition` (per-frame 目標) と `ChargeConstraintConfig` (系列定数) から、
`run_auto_rietveld` へ渡す拘束 kwargs を組み立てる (`plan_frame_constraint`) と、精密化結果から
XRD 由来アルカリ量 vs echem 目標の診断 (`frame_alkali_report`) を作る。GSAS 非依存・決定論。

設計 (docs/design/charge-constrained-rietveld/architecture.md):
- **実行可能性/縮退のゲートはこの層の責務** (engine `_apply_content_constraint` は機械的に登録
  するだけ)。infeasible は拘束せず診断へ縮退 + 警告 (= 多相域の不可逆容量検出器)。
- 2 相 lock_fractions は相分率を完全決定する — 警告を必ず付す (既定にしない理由)。
- 単位規約: `TargetComposition.total`/`per_phase` は**式単位あたり** x。ChemComp へは x×Z
  (セルあたり) に換算して渡す (engine は GSAS ネイティブ単位)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..operando.coulometry import (
    MobileSiteSpec,
    feasibility,
    occupancies_for_content,
    x_xrd_from_weight_fractions,
)
from .model import ChargeConstraintConfig, TargetComposition

__all__ = [
    "AlkaliFrameReport",
    "FrameConstraintPlan",
    "alkali_fields",
    "frame_alkali_report",
    "multiplicity_mismatch_warnings",
    "plan_frame_constraint",
]


@dataclass(frozen=True)
class FrameConstraintPlan:
    """1 フレームの拘束計画 (`run_auto_rietveld` への追加 kwargs + 適用記録)。

    :param kwargs: `run_auto_rietveld` へ渡す追加キーワード
        (`initial_occupancies`/`chem_comp_restraints`/`content_constraint` の部分集合)
    :param applied: 実際に**拘束として**効くモード ("" = 拘束なし/診断のみ,
        "soft"/"fix"/"lock_fractions")。多相 diagnose の xᵢ 凍結シードは拘束に数えない
    :param feasibility: 多相での実行可能性 ("" = 未評価/単相, "feasible"/"infeasible"/"degenerate")
    :param warnings: 縮退・不整合の警告
    """

    kwargs: Mapping[str, object] = field(default_factory=dict)
    applied: str = ""
    feasibility: str = ""
    warnings: tuple[str, ...] = ()


def _sites_by_phase(cfg: ChargeConstraintConfig) -> dict[str, MobileSiteSpec]:
    return {s.phase_name: s for s in cfg.mobile_sites}


def _occupancy_targets(
    per_phase: Mapping[str, float],
    cfg: ChargeConstraintConfig,
    warnings: list[str],
) -> dict[str, dict[str, float]]:
    """相ごとの目標 x → 占有率 (等比配分; base は cfg.base_occupancies, 無ければ均等)。"""
    sites = _sites_by_phase(cfg)
    out: dict[str, dict[str, float]] = {}
    for p, x in per_phase.items():
        spec = sites.get(p)
        z = cfg.z_formula.get(p)
        if spec is None or z is None:
            warnings.append(
                f"相 {p}: mobile_sites/z_formula が未定義のため占有率目標を作れません"
            )
            continue
        base = dict(cfg.base_occupancies.get(p) or {lb: 0.0 for lb in spec.site_labels})
        try:
            out[p] = occupancies_for_content(
                float(x), spec, z_formula=float(z), base_occupancies=base
            )
        except ValueError as exc:
            warnings.append(f"相 {p}: 目標 x={x} を占有率へ配分できません ({exc})")
    return out


def plan_frame_constraint(
    tc: TargetComposition | None,
    cfg: ChargeConstraintConfig | None,
    phase_names: Sequence[str],
) -> FrameConstraintPlan:
    """per-frame 目標 + 系列設定 → 拘束計画 (REQ-318-002/003/004)。🔵

    - tc なし (echem 範囲外) / cfg 無効 → 空計画 (従来動作)。
    - 単相: fix = 占有率を x₀ に凍結 / soft = ChemComp (x×Z) / lock = 適用不能→診断。
    - 多相: xᵢ (アンカー値) の凍結シードは全モード共通。lock_fractions のみ
      係数 Zᵢ(xᵢ−x_total) の相間線形拘束を追加 (feasible の場合に限る)。
    """
    if tc is None or cfg is None or not cfg.enabled:
        return FrameConstraintPlan()
    warnings: list[str] = []
    sites = _sites_by_phase(cfg)
    present = [p for p in phase_names if p in sites]
    if not present:
        return FrameConstraintPlan(
            warnings=(
                "可動イオンサイト定義のある相がこのフレームに存在しません "
                f"(相集合: {list(phase_names)})",
            )
        )
    mode = tc.mode
    multi = len(phase_names) >= 2

    if not multi:
        p = present[0]
        if mode == "fix":
            occ = _occupancy_targets({p: tc.total}, cfg, warnings)
            return FrameConstraintPlan(
                kwargs={"initial_occupancies": occ} if occ else {},
                applied="fix" if occ else "",
                warnings=tuple(warnings),
            )
        if mode == "soft":
            # ⚠ 実測: 本バージョンの GSAS-II は headless 最小二乗で restraint penalty が
            # 機能しない (engine `_apply_chem_comp_restraints` docstring の 3 経路)。注入しても
            # 黙って効かないのは「呼べるが黙って間違う」なので、**縮退を明示して診断で続行**する。
            # カナリア (test_canary_headless_penalty_is_inert) が fail したら再有効化。
            warnings.append(
                "soft (ChemComp restraint) は現行 GSAS-II の headless 精密化では機能しません"
                " (penalty が最小二乗に取り込まれない実測バグ) → 診断モードへ縮退。"
                "拘束が必要なら fix (占有率凍結) を使ってください"
            )
            return FrameConstraintPlan(warnings=tuple(warnings))
        if mode == "lock_fractions":
            warnings.append(
                "単相フレームに lock_fractions は適用できません (相分率が存在しない) → 診断のみ"
            )
            return FrameConstraintPlan(warnings=tuple(warnings))
        return FrameConstraintPlan(warnings=tuple(warnings))  # diagnose

    # --- 多相 ---
    per = {p: float(tc.per_phase[p]) for p in phase_names if p in tc.per_phase}
    if len(per) < len(phase_names):
        missing = [p for p in phase_names if p not in per]
        warnings.append(
            f"per_phase x が無い相 {missing} があるため多相拘束を適用できません → 診断のみ"
        )
        return FrameConstraintPlan(warnings=tuple(warnings))
    feas = feasibility(tc.total, per)
    occ = _occupancy_targets(per, cfg, warnings)
    fix_kwargs: dict[str, object] = {"initial_occupancies": occ} if occ else {}

    if mode in ("diagnose", "fix", "soft"):
        if mode == "soft":
            warnings.append(
                "相間 soft 拘束は GSAS 非ネイティブのため適用できません "
                "(xᵢ 凍結 + 診断で続行; lock_fractions は明示 opt-in)"
            )
        return FrameConstraintPlan(
            kwargs=fix_kwargs,
            applied="fix" if (mode == "fix" and occ) else "",
            feasibility=feas,
            warnings=tuple(warnings),
        )

    # lock_fractions
    if feas != "feasible":
        warnings.append(
            f"lock_fractions を適用できません (feasibility={feas}): "
            f"x_total={tc.total} が相の x 範囲 {sorted(per.values())} に対し"
            + ("縮退 (xᵢ 等値 — 拘束が情報を持たない)" if feas == "degenerate"
               else "範囲外 (非負分率で実現不能 = 不可逆容量/副反応の疑い)")
            + " → 拘束せず診断で続行"
        )
        return FrameConstraintPlan(
            kwargs=fix_kwargs, applied="", feasibility=feas, warnings=tuple(warnings)
        )
    coeffs = {p: float(cfg.z_formula[p]) * (per[p] - float(tc.total)) for p in per
              if p in cfg.z_formula}
    if len(coeffs) < len(per):
        missing = [p for p in per if p not in coeffs]
        warnings.append(f"z_formula が無い相 {missing} のため lock_fractions を適用できません")
        return FrameConstraintPlan(
            kwargs=fix_kwargs, applied="", feasibility=feas, warnings=tuple(warnings)
        )
    if len(phase_names) == 2:
        warnings.append(
            "2 相 lock_fractions: 相分率和=1 と合わせ相分率が完全決定されます — "
            "XRD は相分率に寄与せず、Rwp が echem との一致度の検定量になります"
        )
    return FrameConstraintPlan(
        kwargs={**fix_kwargs, "content_constraint": coeffs},
        applied="lock_fractions",
        feasibility=feas,
        warnings=tuple(warnings),
    )


def multiplicity_mismatch_warnings(
    cfg: ChargeConstraintConfig,
    atom_multiplicity: Mapping[str, Mapping[str, float]],
) -> tuple[str, ...]:
    """MobileSiteSpec の multiplicity と GSAS 実値 (原子行 cs+1) の照合 (REQ-318-008, T11)。🔵

    不一致は**静かに誤った x** を作る (x = Σ occ·mult/Z の mult が違えば全数値が系統的にずれる)
    ため必ず警告する。GSAS 側にラベルが無い場合も警告 (spec の書き間違い検出)。
    """
    warnings: list[str] = []
    for spec in cfg.mobile_sites:
        gsas = atom_multiplicity.get(spec.phase_name)
        if gsas is None:
            continue  # この結果に当該相が無い (相集合外) — 呼び出し側の文脈次第なので黙認
        for lb, m in zip(spec.site_labels, spec.multiplicities):
            actual = gsas.get(lb)
            if actual is None:
                warnings.append(
                    f"{spec.phase_name}/{lb}: GSAS 構造に該当ラベルがありません "
                    "(MobileSiteSpec のラベル誤り?)"
                )
            elif abs(float(actual) - float(m)) > 1e-6:
                warnings.append(
                    f"{spec.phase_name}/{lb}: multiplicity 不一致 — spec {m} vs GSAS {actual}。"
                    "GSAS 実値を優先しますが spec を修正してください (x の系統誤差源)"
                )
    return tuple(warnings)


@dataclass(frozen=True)
class AlkaliFrameReport:
    """1 フレームの XRD vs echem アルカリ量診断 (REQ-318-007)。

    :param x_echem: クーロメトリー目標 (tc.total)。tc なしなら None
    :param x_xrd: XRD 由来のモル平均アルカリ量。算出不能なら None
    :param x_xrd_esd: その esd。伝播できなければ None (0.0 を捏造しない)
    :param per_phase: 相名→精密化占有率由来の xᵢ (GSAS mult 優先)
    :param residual: x_xrd − x_echem (不可逆容量/副反応の診断量)。どちらか欠けたら None
    :param warnings: mult 照合・算出不能の警告
    """

    x_echem: float | None = None
    x_xrd: float | None = None
    x_xrd_esd: float | None = None
    per_phase: Mapping[str, float] = field(default_factory=dict)
    residual: float | None = None
    warnings: tuple[str, ...] = ()


def frame_alkali_report(
    *,
    tc: TargetComposition | None,
    cfg: ChargeConstraintConfig | None,
    phase_names: Sequence[str],
    atom_occupancy: Mapping[str, Mapping[str, float]],
    atom_multiplicity: Mapping[str, Mapping[str, float]],
    atom_occupancy_esd: Mapping[str, Mapping[str, float | None]] | None = None,
    phase_weight_fractions: Mapping[str, float] | None = None,
    phase_weight_fraction_esd: Mapping[str, float | None] | None = None,
) -> AlkaliFrameReport:
    """精密化結果 → XRD 由来アルカリ量の診断レポート (diagnose の出力, REQ-318-007)。🔵

    xᵢ は**精密化された占有率** (`atom_occupancy`) と **GSAS 実 multiplicity** から計算する
    (spec 値でなく実値 — mult 照合警告は別途 `multiplicity_mismatch_warnings`)。
    多相のモル平均は `x_xrd_from_weight_fractions` (**FW 除算**)。esd は重量分率 esd +
    占有率 esd の一次伝播。伝播できない場合は None (0.0 を捏造しない)。
    """
    if cfg is None or not cfg.enabled:
        return AlkaliFrameReport()
    warnings = list(multiplicity_mismatch_warnings(cfg, atom_multiplicity))
    sites = _sites_by_phase(cfg)
    per_phase: dict[str, float] = {}
    per_phase_esd: dict[str, float] = {}
    for p in phase_names:
        spec = sites.get(p)
        z = cfg.z_formula.get(p)
        occ = atom_occupancy.get(p)
        mult = atom_multiplicity.get(p) or {}
        if spec is None:
            # 【可動イオンを含まない相の規約】: mobile_sites にサイトが無く、かつ z_formula と
            # formula_weights の**両方に登録**されている相は x_i ≡ 0 (可動イオンなし) と扱う。
            # 例: 深充電相 tetra は K サイト自体が無い — この相をモル平均から**抜くと** x_XRD が
            # 過大評価になる (K₂Mn[Fe(CN)₆] 実測: cubic+tetra 域で tetra 50wt% を無視すると
            # x_XRD が ~2 倍化ける)。CIF にラベルが無いので MobileSiteSpec では表現できない。
            if p in cfg.z_formula and p in cfg.formula_weights:
                per_phase[p] = 0.0
            continue
        if z is None or occ is None:
            continue
        total = 0.0
        var = 0.0
        ok = True
        for lb, spec_m in zip(spec.site_labels, spec.multiplicities):
            if lb not in occ:
                warnings.append(f"{p}/{lb}: 占有率が結果にありません — xᵢ を算出できません")
                ok = False
                break
            m = float(mult.get(lb, spec_m))  # GSAS 実値優先、無ければ spec
            total += float(occ[lb]) * m
            e = (atom_occupancy_esd or {}).get(p, {}).get(lb)
            if e is not None:
                var += (float(e) * m) ** 2
        if not ok:
            continue
        per_phase[p] = total / float(z)
        if var > 0.0:
            per_phase_esd[p] = math.sqrt(var) / float(z)

    x_echem = float(tc.total) if tc is not None else None
    if not per_phase:
        return AlkaliFrameReport(x_echem=x_echem, warnings=tuple(warnings))

    if len(per_phase) == 1 and len(phase_names) == 1:
        p = next(iter(per_phase))
        x = per_phase[p]
        esd = per_phase_esd.get(p)
    else:
        w = dict(phase_weight_fractions or {})
        fw = {p: cfg.formula_weights.get(p) for p in per_phase}
        if any(v is None for v in fw.values()) or not w:
            missing = [p for p, v in fw.items() if v is None]
            if missing:
                warnings.append(
                    f"formula_weights が無い相 {missing} のためモル平均 x_XRD を算出できません"
                )
            else:
                warnings.append("重量分率が無いためモル平均 x_XRD を算出できません")
            return AlkaliFrameReport(
                x_echem=x_echem, per_phase=per_phase, warnings=tuple(warnings)
            )
        use = {p: float(w.get(p, 0.0)) for p in per_phase}
        w_esd = {
            p: float(v)
            for p, v in (phase_weight_fraction_esd or {}).items()
            if p in per_phase and v is not None
        }
        try:
            x, esd = x_xrd_from_weight_fractions(
                use,
                {p: float(v) for p, v in fw.items()},  # type: ignore[arg-type]
                per_phase,
                weight_esd=w_esd or None,
                x_esd=per_phase_esd or None,
            )
        except ValueError as exc:
            warnings.append(f"x_XRD 算出不能: {exc}")
            return AlkaliFrameReport(
                x_echem=x_echem, per_phase=per_phase, warnings=tuple(warnings)
            )

    residual = (x - x_echem) if (x_echem is not None) else None
    return AlkaliFrameReport(
        x_echem=x_echem,
        x_xrd=float(x),
        x_xrd_esd=esd,
        per_phase=per_phase,
        residual=residual,
        warnings=tuple(warnings),
    )


def alkali_fields(
    tc: TargetComposition | None,
    cfg: ChargeConstraintConfig | None,
    phase_names: Sequence[str],
    result: object,
) -> tuple[dict[str, object], tuple[str, ...]]:
    """FrameRietveldResult へ流し込む alkali_* フィールド辞書 + 警告を作る (エンジン統合点)。🔵

    :param result: `AutoRietveldResult` 相当 (atom_occupancy / atom_multiplicity /
        atom_occupancy_esd / phase_weight_fractions(+esd) を duck-type で読む — テストスタブ可)
    :returns: (フィールド辞書, 警告)。機能無効なら ({}, ()) — 既定値のまま (後方互換)。
    """
    if cfg is None or not cfg.enabled:
        return {}, ()
    plan = plan_frame_constraint(tc, cfg, phase_names)
    rep = frame_alkali_report(
        tc=tc,
        cfg=cfg,
        phase_names=phase_names,
        atom_occupancy=getattr(result, "atom_occupancy", {}) or {},
        atom_multiplicity=getattr(result, "atom_multiplicity", {}) or {},
        atom_occupancy_esd=getattr(result, "atom_occupancy_esd", {}) or {},
        phase_weight_fractions=getattr(result, "phase_weight_fractions", {}) or {},
        phase_weight_fraction_esd=getattr(result, "phase_weight_fraction_esd", {}) or {},
    )
    fields: dict[str, object] = {
        "alkali_x_echem": rep.x_echem,
        "alkali_x_xrd": rep.x_xrd,
        "alkali_x_xrd_esd": rep.x_xrd_esd,
        "alkali_per_phase": dict(rep.per_phase),
        "alkali_residual": rep.residual,
        "alkali_constraint_applied": plan.applied,
        "alkali_feasibility": plan.feasibility,
    }
    return fields, tuple(plan.warnings) + tuple(rep.warnings)
