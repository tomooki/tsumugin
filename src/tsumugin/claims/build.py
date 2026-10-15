"""`AutoRietveldResult` → `Claim` の写像 (fit-then-judge P1-1A。proposal §3.1 の表)。

- `base_claims(result)`: 1 回の fit から、値ごとの出自・決定性・scope・相関・`provenance_known` 検査を
  決める。必須検査のうち相集合の完全性と結晶化学は**ここでは走らせない** (未記録 = `unevaluated` =
  出版不可。検査器が後から記録する)。
- `with_convergence(claims, multistart)`: 収束確認 (Phase B) の全開始点で値ごとの一致を見て、
  `determined` の証人を付ける / 割れた値を `initial_value_dependent` に落とす。

出自の典拠は**最終の共分散** (`AutoRietveldResult.final_covariance`) で、値 → GSAS 変数の対応は
engine が作る `claim_variables`。esd の三状態だけでは「未解放・revert・共分散なし」を区別できない。

| 条件 (上から先に当てる) | provenance | determinacy |
|---|---|---|
| 対称性で厳密に決まる (格子・分率の esd が 0.0 / 座標の自由度 0) | symmetry | exact |
| 共分散か変数対応が無い | (空) — `provenance_known` が unevaluated | esd_only |
| 依存変数が剪定で凍結された (`frozen_parameters`) | pruned | undetermined_esd |
| 依存変数が varyList にも従属にも無い (解放しなかった・revert) | input | esd_only (出版はしない) |
| `undetermined_parameters` に名がある / esd ≥ \\|値\\| (Uiso・占有率・分率・微細構造) | refined | undetermined_esd |
| それ以外で精密化した | refined | esd_only (最終段が非収束なら unconverged) |
"""

from __future__ import annotations

import math
from typing import Mapping

from ..autorietveld.agreement import AgreementTolerances, is_agreement, parameter_agreements
from ..autorietveld.model import AutoRietveldResult
from .model import PROVENANCE_VARIED, Check, Claim, Determinacy, Scope, Witness, compose, weaker_determinacy

__all__ = ["CLAIMS_VERSION", "base_claims", "with_convergence", "with_probe"]

#: claims の写像規則の版 (② の出力・sidecar に記録する)。
# 1B/1: 入力値を昇格しない・`locally_stable` (初期値プローブ)・座標の証人は動かした座標だけ・
#   テンプレートの判断要求と `declared:*` の出自 (fit-then-judge P1-1B)。
CLAIMS_VERSION = "fit-then-judge/1B/2"  # /2 (P1.5): 出自の違いだけでは初期値依存にしない

_CELL_AXES = ("a", "b", "c", "alpha", "beta", "gamma")
#: esd ≥ |値| を「決まっていない」とする種類 (格子・座標・プロファイルは値の原点が任意なので除く)。
_WEAK_BY_RATIO = frozenset({"uiso", "occupancy", "weight_fraction", "microstructure"})


def _finite(value: object) -> float | None:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class _Origins:
    """1 回の fit の出自判定に要る集合をまとめたもの。"""

    def __init__(self, result: AutoRietveldResult) -> None:
        cov = result.final_covariance
        self.known = cov is not None and result.claim_variables is not None
        self.variables: Mapping[str, tuple[str, ...]] = result.claim_variables or {}
        self.refined = frozenset(cov.vary_list) | frozenset(cov.dependent) if cov else frozenset()
        self.frozen = frozenset(result.frozen_parameters)
        self.undetermined = frozenset(w.name for w in result.undetermined_parameters)
        stages = result.stage_results
        self.converged = bool(stages[-1].converged) if stages else False
        self.correlations = cov.correlations if cov else ()

    def classify(
        self, key: str, param_class: str, value: float | None, esd: float | None,
        symmetric: bool,
    ) -> tuple[frozenset[str], Determinacy]:
        if symmetric:
            return frozenset({"symmetry"}), Determinacy.EXACT
        if not self.known:
            return frozenset(), Determinacy.ESD_ONLY
        names = frozenset(self.variables.get(key, ()))
        if names & self.frozen:
            return frozenset({"pruned"}), Determinacy.UNDETERMINED_ESD
        if not names & self.refined:
            return frozenset({"input"}), Determinacy.ESD_ONLY
        det = Determinacy.ESD_ONLY
        weak_ratio = (
            param_class in _WEAK_BY_RATIO and value is not None and esd is not None
            and esd >= abs(value)
        )
        if names & self.undetermined or weak_ratio:
            det = Determinacy.UNDETERMINED_ESD
        if not self.converged:
            det = weaker_determinacy(det, Determinacy.UNCONVERGED)
        return frozenset({"refined"}), det

    def correlated_keys(self) -> dict[str, frozenset[str]]:
        """|ρ| が閾値を超える**直接の**相手を値のキーで返す (推移閉包はとらない — proposal §3.3)。"""
        by_var: dict[str, set[str]] = {}
        for key, names in self.variables.items():
            for name in names:
                by_var.setdefault(name, set()).add(key)
        out: dict[str, set[str]] = {}
        for pair in self.correlations:
            for ka in by_var.get(pair.a, ()):
                for kb in by_var.get(pair.b, ()):
                    if ka != kb:
                        out.setdefault(ka, set()).add(kb)
                        out.setdefault(kb, set()).add(ka)
        return {k: frozenset(v) for k, v in out.items()}


def _entries(result: AutoRietveldResult):
    """(key, class, phase, label, axis, value, esd, unit, symmetric, scope) を値ごとに列挙する。"""
    for phase, cell in result.refined_cells.items():
        esds = result.cell_esd.get(phase, (None,) * 6)
        for i, axis in enumerate(_CELL_AXES):
            esd = _finite(esds[i]) if i < len(esds) else None
            yield (
                f"cell:{phase}.{axis}", "cell", phase, None, axis, _finite(cell[i]), esd,
                "angstrom" if i < 3 else "degree", esd == 0.0, Scope.RELATIVE_WITHIN_SAMPLE,
            )
    for phase, atoms in result.atom_coords.items():
        esd_map = result.atom_coord_esd.get(phase, {})
        free_map = result.atom_coord_free_index.get(phase, {})
        for label, xyz in atoms.items():
            esds = esd_map.get(label, (None, None, None))
            free = free_map.get(label)
            for i, axis in enumerate("xyz"):
                symmetric = free is not None and int(free[i]) == 0
                yield (
                    f"coord:{phase}.{label}.{axis}", "coord", phase, label, axis,
                    _finite(xyz[i]), _finite(esds[i]) if i < len(esds) else None,
                    "fractional", symmetric, Scope.ABSOLUTE,
                )
    for cls, values, esds, unit in (
        ("uiso", result.atom_uiso, result.atom_uiso_esd, "angstrom^2"),
        ("occupancy", result.atom_occupancy, result.atom_occupancy_esd, "fraction"),
    ):
        for phase, per_label in values.items():
            for label, value in per_label.items():
                yield (
                    f"{cls}:{phase}.{label}", cls, phase, label, None, _finite(value),
                    _finite(esds.get(phase, {}).get(label)), unit, False, Scope.ABSOLUTE,
                )
    for phase, value in result.phase_weight_fractions.items():
        esd = _finite(result.phase_weight_fraction_esd.get(phase))
        yield (
            f"weight_fraction:{phase}.wt", "weight_fraction", phase, None, None, _finite(value),
            esd, "mass_fraction", esd == 0.0, Scope.ABSOLUTE,
        )
    for name, values, esds, unit in (
        ("size", result.hap_size, result.hap_size_esd, "micrometer"),
        ("mustrain", result.hap_mustrain, result.hap_mustrain_esd, "microstrain"),
    ):
        for phase, per_hist in values.items():
            for hkey, value in per_hist.items():
                yield (
                    f"microstructure:{phase}.{hkey}.{name}", "microstructure", phase, None, name,
                    _finite(value), _finite(esds.get(phase, {}).get(hkey)), unit, False,
                    Scope.ABSOLUTE,
                )
    for h, profile in enumerate(result.hist_profile):
        esds = result.hist_profile_esd[h] if h < len(result.hist_profile_esd) else {}
        for key, value in profile.items():
            yield (
                f"profile:hist{h}.{key}", "profile", None, None, key, _finite(value),
                _finite(esds.get(key)), "gsas_instrument", False, Scope.ABSOLUTE,
            )


def base_claims(result: AutoRietveldResult) -> dict[str, Claim]:
    """1 回の fit の結果から値ごとの `Claim` を作る (証人・検査器はまだ掛けない)。"""
    origins = _Origins(result)
    correlated = origins.correlated_keys()
    known = Check.PASS if origins.known else Check.UNEVALUATED
    out: dict[str, Claim] = {}
    for key, cls, phase, label, axis, value, esd, unit, symmetric, scope in _entries(result):
        provenance, determinacy = origins.classify(key, cls, value, esd, symmetric)
        out[key] = Claim(
            key=key, param_class=cls, value=value, esd=esd, unit=unit,
            phase=phase, label=label, axis=axis,
            determinacy=determinacy, provenance=provenance,
            correlations=correlated.get(key, frozenset()), scope=scope,
            checks={"provenance_known": known},
        )
    return out


def _usable(result: AutoRietveldResult | None) -> bool:
    return (
        result is not None
        and _finite(result.final_rwp) is not None
        and bool(result.validity.passed)
    )


def with_convergence(
    claims: Mapping[str, Claim], multistart: object | None
) -> dict[str, Claim]:
    """収束確認 (`RietveldMultistartResult`) の全開始点で値ごとの一致を見る (REQ-FTJ-1A-401)。

    - 各開始点の出自と合成する (開始点で出自が違えば `initial_value_dependent`)
    - valid な開始点のどれかの対で割れた値 (DISAGREE) は `initial_value_dependent`
    - **全開始点が実行・valid**・摂動が実際に効いた・全対で一致 → `determined` (証人付き)。
      `esd_only` の値だけを昇格する (`undetermined_esd` 等は一致しても決まっていない)
    """
    out = dict(claims)
    if multistart is None:
        return out
    starts = tuple(getattr(multistart, "starts", ()))
    results = [s.result for s in starts]

    # 出自の合成も値の一致と同じ開始点 (使える = 有限・validity を通った) に限る。validity に落ちた開始点
    #   (別ベイスンに落ちた等) は比較から外しているのに、出自の違いで値を初期値依存にしていた (P1.5)。
    for r in results:
        if not _usable(r):
            continue
        for key, other in base_claims(r).items():
            if key in out:
                out[key] = compose(out[key], other)

    valid = [r for r in results if _usable(r)]
    all_valid = len(starts) >= 2 and len(valid) == len(starts)
    witness_ok = all_valid and bool(getattr(multistart, "perturbation_applied", False))
    # 座標の摂動を頼んだのに 1 軸も動かなかった (高対称・全原子凍結) なら座標は試験していない
    #   (multistart の傍証条件 `perturbation_had_no_effect` と同じ)。格子だけ振った一致は座標の証人にしない。
    jitter_requested = any(
        float(getattr(s.perturbation, "coord_jitter_ang", 0.0)) > 0.0 for s in starts
    )
    coords_tested = not jitter_requested or any(
        int(getattr(s, "n_axes_jittered", 0)) > 0 for s in starts
    )
    # どの座標を振ったか (engine が記録)。記録があれば座標の証人はそれに限る — 件数だけだと、極性原点の
    #   hold や凍結で振っていない座標まで「試験した」と数える (fit-then-judge P1-1B)
    #   記録が 1 つも無い (TOPAS 等の engine は記録しない) ときだけ件数の規則へ戻る。使える開始点だけを数える (N9)
    moved_coords = {
        f"coord:{k}" for r in results if _usable(r)
        for k in getattr(r, "coord_jitter_moved", ())
    }
    tolerances = AgreementTolerances()

    verdicts: dict[str, list[tuple[str, float | None, int, int]]] = {}
    pairs = 0
    for i in range(len(valid)):
        for j in range(i + 1, len(valid)):
            pairs += 1
            for cls, items in parameter_agreements(valid[i], valid[j], tolerances).items():
                for it in items:
                    verdicts.setdefault(f"{cls}:{it.key}", []).append((it.verdict, it.z, i, j))

    for key, claim in list(out.items()):
        found = verdicts.get(key, [])
        split = [v for v in found if v[0] == "DISAGREE"]
        if split:
            worst = max(split, key=lambda v: v[1] if v[1] is not None else math.inf)
            out[key] = claim.weakened_to(
                Determinacy.INITIAL_VALUE_DEPENDENT,
                Witness("multistart_disagreement", {
                    "pair": [worst[2], worst[3]], "z": worst[1], "n_split_pairs": len(split),
                }),
            )
            continue
        if (
            witness_ok and pairs > 0 and len(found) == pairs
            and all(is_agreement(v[0]) for v in found)
            and claim.determinacy is Determinacy.ESD_ONLY
            and "refined" in claim.provenance  # 解放しなかった入力値は「決まった」のではない
            # 開始点で出自が違った (ある開始点では精密化しなかった) 値は試験したとは言えない
            and not any(w.kind == PROVENANCE_VARIED for w in claim.witnesses)
            and (
                claim.param_class != "coord"
                or (coords_tested and (not moved_coords or key in moved_coords))
            )
        ):
            zs = [v[1] for v in found if v[1] is not None]
            out[key] = claim.strengthened_to(
                Determinacy.DETERMINED,
                Witness("multistart_agreement", {
                    "n_starts": len(starts), "n_pairs": pairs, "k_esd": tolerances.k_esd,
                    "max_z": max(zs) if zs else None,
                }),
            )
    return out


def with_probe(
    claims: Mapping[str, Claim], base: AutoRietveldResult, outcome: object | None
) -> dict[str, Claim]:
    """初期値プローブ (±δ の 2 開始点) で値ごとに「戻ったか」を見る (REQ-FTJ-1B-602)。

    - どちらかの開始点で割れた値 (DISAGREE) は `initial_value_dependent`
    - 両方で戻った `esd_only` の値は `locally_stable` (証人付き)。`determined` 等は変えない
      (合成は最小 — 割れたときだけ落ちる)
    - 2 開始点とも回り、**収束し**、使える結果でなければ何もしない (回らなかった・省いた値は基底状態のまま)
    - **振った値にだけ** `locally_stable` を付ける: 格子は ``cell_frac`` が一致の許容幅を超えるとき、座標は
      両方の開始点で実際に動かした座標 (`coord_jitter_moved`) で、かつ**その軸の実際の変位**
      (`coord_jitter_shift`, 2 開始点の小さい方) が一致の床と kσ 帯を超えるとき。
      Uiso・占有率・プロファイル・分率・微細構造は振っていないので、戻っても証人にしない
      (割れたら `initial_value_dependent` には落とす — 割れたこと自体は情報)
    """
    out = dict(claims)
    if outcome is None or not getattr(outcome, "complete", False):
        return out
    probes = tuple(getattr(outcome, "probes", ()))
    # 収束した使える開始点だけで判定する。**割れ**はそこから落とす (収束した開始点がはっきり割れたことは情報)。
    #   **昇格**は両開始点とも収束したときだけ (収束していない開始点の「戻った」は証人にならない。N7)
    converged_idx = {
        i for i, p in enumerate(probes)
        if _usable(p) and all(st.converged for st in p.stage_results)
    }
    all_converged = len(converged_idx) == len(probes)
    if not converged_idx:
        return out
    config = getattr(outcome, "config", None)
    tolerances = AgreementTolerances()
    jitter = float(getattr(config, "coord_jitter_ang", 0.0) or 0.0)
    cell_frac = float(getattr(config, "cell_frac", 0.0) or 0.0)
    cell_tested = cell_frac > tolerances.cell_rel_floor
    moved_coords: set[str] = set()
    if jitter > tolerances.coord_dist_floor_ang:
        moved_sets = [set(p.coord_jitter_moved) for p in probes]
        moved_coords = {f"coord:{k}" for k in set.intersection(*moved_sets)} if moved_sets else set()
    # 軸ごとの実際の変位 (分率)。結束の組の従属軸は係数比ぶんしか動かない ((x,2x,z) の x は amp の半分) —
    #   全軸が jitter Å 動いた前提で数えると、許容幅の内側しか動いていない軸に空虚な証人を付ける。
    #   2 開始点の小さい方で判定する。**記録が無ければ証人にしない** (fail closed): 動かした座標を記録する
    #   engine (GSAS のプローブ) は変位も必ず記録する — 片方だけ欠けるのは配線漏れで、そのとき軸長から推すと
    #   従属軸に空虚な証人を付ける規則へ黙って戻る
    shift_maps = [getattr(p, "coord_jitter_shift", None) or {} for p in probes]

    def axis_shift(claim: Claim) -> "float | None":
        key = claim.key.removeprefix("coord:")
        vals = [m.get(key) for m in shift_maps]
        if any(v is None for v in vals):
            return None
        return min(abs(float(v)) for v in vals)

    def coord_displacement_resolvable(claim: Claim) -> bool:
        """実際の変位が一致の床 (Å) と kσ 帯を超えるか (N3: σ の大きい座標は 0.05 Å 振っても「戻った」と
        区別できない)。"""
        cell = (base.refined_cells or {}).get(claim.phase or "")
        if claim.esd is None or cell is None or claim.axis not in ("x", "y", "z"):
            return False
        length = float(cell["xyz".index(claim.axis)])
        if not (length > 0.0):
            return False
        shift = axis_shift(claim)  # 分率
        if shift is None or not (shift * length > tolerances.coord_dist_floor_ang):
            return False
        band = tolerances.k_esd * math.sqrt(2.0) * float(claim.esd)  # 分率
        return shift > band

    def tested(claim: Claim) -> bool:
        if claim.param_class == "cell":
            return cell_tested
        if claim.param_class == "coord":
            return claim.key in moved_coords and coord_displacement_resolvable(claim)
        return False
    found: dict[str, list[tuple[str, float | None, int]]] = {}
    for i, probe in enumerate(probes):  # 元の添字で記録する (L-a)
        if i not in converged_idx:
            continue
        for cls, items in parameter_agreements(base, probe, tolerances).items():
            for it in items:
                found.setdefault(f"{cls}:{it.key}", []).append((it.verdict, it.z, i))
    detail_base = {
        "n_probes": len(probes),
        "cell_frac": getattr(config, "cell_frac", None),
        "coord_jitter_ang": jitter,
        "k_esd": tolerances.k_esd,
    }
    for key, claim in list(out.items()):
        verdicts = found.get(key, [])
        split = [v for v in verdicts if v[0] == "DISAGREE"]
        if split:
            worst = max(split, key=lambda v: v[1] if v[1] is not None else math.inf)
            out[key] = claim.weakened_to(
                Determinacy.INITIAL_VALUE_DEPENDENT,
                Witness("initial_value_probe_split", {
                    **detail_base, "probe": worst[2], "z": worst[1],
                }),
            )
            continue
        if (
            all_converged
            and len(verdicts) == len(probes)
            and all(is_agreement(v[0]) for v in verdicts)
            and claim.determinacy is Determinacy.ESD_ONLY
            and "refined" in claim.provenance  # 解放しなかった入力値は戻って当然 (証人にならない)
            and tested(claim)
        ):
            zs = [v[1] for v in verdicts if v[1] is not None]
            out[key] = claim.strengthened_to(
                Determinacy.LOCALLY_STABLE,
                Witness("initial_value_probe", {**detail_base, "max_z": max(zs) if zs else None}),
            )
    return out
