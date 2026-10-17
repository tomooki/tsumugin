"""engine の結果 (`AutoRietveldResult`) を評価の入力 `ArmOutcome` に写す (P0 §1.2–§1.5)。

結果に直接は無いものをここで作る:

- **χ²**: 最後に受理された段の GOF・母数と ``n_obs`` から ``GOF²·(N−P)`` (`evidence.fitstats.chi2_from_stage`)。
  テンプレートも基準経路も拘束を張らないので GOF は拘束項を含まない。
- **観測集合のハッシュ** (§1.5): ヒストグラムごとのデータファイルの中身の sha256 と、使用域 (``two_theta_limits``)・除外区間・
  形式。これが一致するアーム同士でだけ χ² を比べる。読めなければ None (比べない)。
- **f** (§1.4): `check_validity` の違反と、結晶化学検査器の ``fail`` を (検査, 相) 単位で数える (まとめの
  ``crystal_chemistry`` は二重に数えない)。
- **b** (§1.4): `claims.chemistry.short_bonds` の相ごとの和。どれかの相で数えられなければ None (0 にしない)。

**失敗** (§1.2): 結果が無い・例外/エラー・χ² が非有限・収束しなかった (`autorietveld.search.convergence_verdict`)・
評価スクリプトの事後の収束検査に外れた。

比較集合のキー: 座標 ``coord:<相>.<ラベル>``・占有率 ``occ:<相>.<ラベル>``・格子 ``cell:<相>.<a|b|c|alpha|beta|gamma>``。
参照側 (`RefValue`) は事例表の原子の対応でこのキーに写して作る。
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Sequence
from pathlib import Path

from .case import ArmOutcome
from .structure import FitValue

__all__ = ["POSTHOC_MAX_SHIFT_ESD", "fail_count", "posthoc_converged", "fit_values", "observation_set_hash", "outcome_from_result", "result_chi2", "short_bond_total"]

_CELL_AXES = ("a", "b", "c", "alpha", "beta", "gamma")

Checker = Callable[[str, str, object], dict]
BondCounter = Callable[[str, str, object], tuple]


#: P0 §1.2 の事後の収束検査の閾値 (P1.5 で凍結)。engine の収束判定 (`StabilityOptions.max_shift_esd`) と同じ値 —
#   評価だけ別の物差しにしない。S-dev の全アームの実測は 0.0–0.72 (2026-10-15)。
POSTHOC_MAX_SHIFT_ESD = 1.0


def posthoc_converged(max_shift_esd: float | None) -> bool | None:
    """事後の追加サイクルの max |shift|/esd が閾値以下か。値が無ければ None (判定できない)。"""
    if max_shift_esd is None or not math.isfinite(max_shift_esd):
        return None
    return max_shift_esd <= POSTHOC_MAX_SHIFT_ESD


def result_chi2(result: object) -> float | None:
    """最後に受理された段の χ²。受理段・観測点数が無ければ None。"""
    from ..autorietveld.search import accepted_stage
    from ..evidence.fitstats import chi2_from_stage

    stage = accepted_stage(result)  # type: ignore[arg-type]
    n_obs = int(getattr(result, "n_obs", 0) or 0)
    gof = None if stage is None else getattr(stage, "gof", None)
    if gof is None or n_obs <= 0:
        return None
    try:
        gof = float(gof)
    except (TypeError, ValueError):
        return None
    return chi2_from_stage(gof=gof, n_obs=n_obs, n_params=int(stage.n_params))


def observation_set_hash(histograms: Sequence[object]) -> str | None:
    """観測集合の内容ハッシュ (§1.5)。データファイルが読めなければ None。"""
    h = hashlib.sha256()
    for hist in histograms:
        try:
            data = Path(str(getattr(hist, "data_path"))).read_bytes()
        except OSError:
            return None
        limits = getattr(hist, "two_theta_limits", None)
        excluded = sorted(tuple(map(float, r)) for r in (getattr(hist, "excluded_regions", ()) or ()))
        meta = {
            "data_sha256": hashlib.sha256(data).hexdigest(),
            "format": str(getattr(hist, "data_format", "")),
            "limits": None if limits is None else [float(x) for x in limits],
            "excluded": excluded,
        }
        h.update(json.dumps(meta, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def _refined_esd(esd: object) -> bool:
    return esd is not None and math.isfinite(float(esd)) and float(esd) > 0.0  # type: ignore[arg-type]


def fit_values(result: object, *, include_cell: bool) -> tuple[FitValue, ...]:
    """比較集合に入りうる値 (座標・占有率・必要なら格子) を `FitValue` に写す。"""
    out: list[FitValue] = []
    coord_esd = getattr(result, "atom_coord_esd", {}) or {}
    for phase, atoms in (getattr(result, "atom_coords", {}) or {}).items():
        esd_ph = coord_esd.get(phase, {})
        for label, xyz in atoms.items():
            raw = esd_ph.get(label) or (None, None, None)
            sig = tuple(float(s) if _refined_esd(s) else 0.0 for s in raw)
            out.append(FitValue("coord", f"coord:{phase}.{label}", tuple(map(float, xyz)), sig,  # type: ignore[arg-type]
                                any(_refined_esd(s) for s in raw)))
    occ_esd = getattr(result, "atom_occupancy_esd", {}) or {}
    for phase, atoms in (getattr(result, "atom_occupancy", {}) or {}).items():
        for label, occ in atoms.items():
            e = occ_esd.get(phase, {}).get(label)
            ok = _refined_esd(e)
            out.append(FitValue("occupancy", f"occ:{phase}.{label}", float(occ), float(e) if ok else 0.0, ok))
    if include_cell:
        cell_esd = getattr(result, "cell_esd", {}) or {}
        for phase, cell in (getattr(result, "refined_cells", {}) or {}).items():
            esds = cell_esd.get(phase) or (None,) * 6
            for axis, value, e in zip(_CELL_AXES, cell, esds):
                ok = _refined_esd(e)
                out.append(FitValue("cell", f"cell:{phase}.{axis}", float(value), float(e) if ok else 0.0, ok))
    return tuple(out)


def _default_checker(phase: str, path: str, result: object) -> dict:
    from ..claims.chemistry import crystal_chemistry

    return crystal_chemistry(phase, path, result)


def _default_bonds(phase: str, path: str, result: object) -> tuple:
    from ..claims.chemistry import short_bonds

    return short_bonds(phase, path, result)


def fail_count(result: object, phases: Sequence[object], *, checker: Checker = _default_checker) -> int:
    """`check_validity` の違反 + 結晶化学の ``fail`` ((検査, 相) 単位)。"""
    from ..claims.chemistry import CHEMISTRY_CHECKS
    from ..claims.model import Check

    validity = getattr(result, "validity", None)
    n = sum(1 for _name, ok, _detail in (getattr(validity, "checks", ()) or ()) if not ok)
    for spec in phases:
        checks = checker(str(getattr(spec, "phase_name")), str(getattr(spec, "structure_path")), result)
        n += sum(1 for name in CHEMISTRY_CHECKS if name in checks and checks[name][0] == Check.FAIL)
    return n


def short_bond_total(result: object, phases: Sequence[object], *, bond_counter: BondCounter = _default_bonds) -> int | None:
    total = 0
    for spec in phases:
        n, _ = bond_counter(str(getattr(spec, "phase_name")), str(getattr(spec, "structure_path")), result)
        if n is None:
            return None
        total += int(n)
    return total


def outcome_from_result(
    result: object | None = None,
    *,
    histograms: Sequence[object],
    phases: Sequence[object],
    error: str = "",
    include_cell: bool = False,
    posthoc_converged: bool | None = None,
    checker: Checker = _default_checker,
    bond_counter: BondCounter = _default_bonds,
) -> ArmOutcome:
    """1 (事例, アーム) の結果を `ArmOutcome` にする。失敗なら理由付きで ``failed=True``。"""
    from ..autorietveld.search import convergence_verdict

    if result is None or error:
        return ArmOutcome(failed=True, failure_reason=error or "no result")
    chi2 = result_chi2(result)
    if chi2 is None:  # chi2_from_stage は非有限の GOF で None を返す
        return ArmOutcome(failed=True, failure_reason="chi2 not finite or unavailable")
    converged, why = convergence_verdict(result)  # type: ignore[arg-type]
    if converged is False:
        return ArmOutcome(failed=True, chi2=chi2, failure_reason=f"did not converge: {why}")
    if posthoc_converged is False:
        return ArmOutcome(failed=True, chi2=chi2, failure_reason="post-hoc convergence check failed")
    return ArmOutcome(
        failed=False,
        chi2=chi2,
        obs_hash=observation_set_hash(histograms),
        values=fit_values(result, include_cell=include_cell),
        fail_count=fail_count(result, phases, checker=checker),
        short_bonds=short_bond_total(result, phases, bond_counter=bond_counter),
    )
