"""結晶化学検査器 — 精密化後の構造の粗大誤差を三値で返す (fit-then-judge P1-1A, REQ-FTJ-1A-403)。

相ごとに 3 つの検査を `pass` / `fail` / `unevaluated` で返し、`crystal_chemistry` はその最悪
(出版の必須検査。`claims.model.required_checks_for`):

| 検査 | 何を見るか | fail |
|---|---|---|
| ``short_contact`` | 別サイトの原子間距離 / 原子半径の和 (pymatgen ``Element.atomic_radius``) | 0.7 未満がある (分割サイトの対は除く) |
| ``bvs_gii`` | 結合原子価和の global instability index ``sqrt(mean((\\|BVS\\| − \\|V\\|)²))`` | 0.3 v.u. を超える |
| ``charge_neutrality`` | 推定した酸化数 × 精密化後の組成の総和 / 総電荷の大きさ | 0.05 を超える |

- 構造は**入力 CIF の非対称単位に精密化後の格子・座標・占有率を差し込んで**組む (対称操作は CIF の
  ものを使う)。どれかの原子が結果に無い・CIF を読めない・pymatgen が無い → 3 検査とも ``unevaluated``。
- 結合原子価は pymatgen 同梱の O'Keeffe–Brese 元素パラメータ (``bond_valence.BV_PARAMS``) で
  占有率を重み付けて計算し (`_bv_sum`)、リポジトリに表を複製しない。酸化数は**入力構造**に ``BVAnalyzer`` を掛けて元素ごとに決める
  (精密化後の占有率がずれて電荷が合わなくなったことを、入力の酸化数で検出するため)。決められなければ
  ``bvs_gii``・``charge_neutrality`` は ``unevaluated``。
- 閾値は経験則 (GII は Salinas-Sanchez らの目安) で P1.5 で調整する (`CHEMISTRY_VERSION`)。
- 既存の ``autorietveld.validity.check_bond_validity`` (bool・M10 が依存) は変えない。
"""

from __future__ import annotations

import math
import tempfile
import warnings
from dataclasses import replace
from pathlib import Path
from typing import Mapping

from .model import Check, Witness, worse_check

__all__ = ["CHEMISTRY_CHECKS", "CHEMISTRY_VERSION", "crystal_chemistry", "short_bonds"]

CHEMISTRY_VERSION = "crystal-chemistry/1"
CHEMISTRY_CHECKS = ("short_contact", "bvs_gii", "charge_neutrality")

_SHORT_CONTACT_RATIO = 0.7
_GII_FAIL = 0.3
_CHARGE_FAIL = 0.05
_NEIGHBOR_CUTOFF = 3.5  # Å — 結合原子価は距離で指数的に減るのでこれより先は無視できる


def _all(outcome: Check, reason: str) -> dict[str, tuple[Check, Witness]]:
    w = Witness("crystal_chemistry", {"version": CHEMISTRY_VERSION, "reason": reason})
    return {name: (outcome, w) for name in CHEMISTRY_CHECKS}


def _refined_structure(structure_path: str, phase: str, result: object):
    """入力 CIF の非対称単位に精密化後の値を差し込む (`cif_normalize.Structure`)。"""
    from ..autorietveld.cif_normalize import read_structure_cif

    base = read_structure_cif(structure_path)
    cells = getattr(result, "refined_cells", {})
    coords = getattr(result, "atom_coords", {}).get(phase)
    occ = getattr(result, "atom_occupancy", {}).get(phase)
    if phase not in cells or coords is None or occ is None:
        raise LookupError(f"相 {phase!r} の精密化後の値が結果に無い")
    missing = [at.label for at in base.atoms if at.label not in coords or at.label not in occ]
    if missing:
        raise LookupError(f"相 {phase!r} の原子 {missing} の精密化後の値が結果に無い")
    a, b, c, al, be, ga = (float(v) for v in cells[phase])
    atoms = tuple(
        replace(at, x=float(coords[at.label][0]), y=float(coords[at.label][1]),
                z=float(coords[at.label][2]), occ=float(occ[at.label]))
        for at in base.atoms
    )
    return base, replace(base, a=a, b=b, c=c, alpha=al, beta=be, gamma=ga, atoms=atoms)


def _to_pymatgen(structure, phase: str):
    from pymatgen.io.cif import CifParser

    from ..autorietveld.cif_normalize import write_gsas_cif

    with tempfile.TemporaryDirectory() as tmp:
        path = write_gsas_cif(structure, Path(tmp) / "phase.cif", phase_name=phase)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            return CifParser(str(path)).parse_structures(primitive=False)[0]


def _element_valences(pmg_input) -> dict[str, float]:
    """入力構造の元素ごとの酸化数 (占有率で重み付けした平均)。決められなければ ValueError。"""
    from pymatgen.analysis.bond_valence import BVAnalyzer

    decorated = BVAnalyzer().get_oxi_state_decorated_structure(pmg_input)
    totals: dict[str, list[float]] = {}
    for site in decorated:
        for sp, amount in site.species.items():
            acc = totals.setdefault(sp.symbol, [0.0, 0.0])
            acc[0] += float(sp.oxi_state) * float(amount)
            acc[1] += float(amount)
    return {el: s / n for el, (s, n) in totals.items() if n > 0}


def _short_contact(pmg) -> tuple[Check, dict]:
    from pymatgen.core.periodic_table import Element

    worst = math.inf
    worst_pair: list[str] = []
    for i, site in enumerate(pmg):
        for nb in pmg.get_neighbors(site, _NEIGHBOR_CUTOFF):
            if nb.index <= i:
                continue
            occ_i = sum(site.species.values())
            occ_j = sum(nb.species.values())
            if occ_i < 1.0 - 1e-6 and occ_j < 1.0 - 1e-6 and occ_i + occ_j <= 1.0 + 1e-2:
                continue  # 分割サイト (どちらか一方しか居ない) の対は接触ではない
            for el_i in site.species:
                for el_j in nb.species:
                    ri = Element(el_i.symbol).atomic_radius
                    rj = Element(el_j.symbol).atomic_radius
                    if ri is None or rj is None:
                        continue
                    ratio = float(nb.nn_distance) / (float(ri) + float(rj))
                    if ratio < worst:
                        worst = ratio
                        worst_pair = [el_i.symbol, el_j.symbol, round(float(nb.nn_distance), 4)]
    if not math.isfinite(worst):
        return Check.UNEVALUATED, {"reason": "no_neighbors"}
    outcome = Check.FAIL if worst < _SHORT_CONTACT_RATIO else Check.PASS
    return outcome, {"min_ratio": worst, "pair": worst_pair, "limit": _SHORT_CONTACT_RATIO}


def _bv_sum(site, neighbors) -> float:
    """結合原子価和 (O'Keeffe–Brese の元素パラメータ)。占有率で重み付けするので混合占有にも効く。

    順序サイトでは pymatgen ``calculate_bv_sum`` と同じ値 (テストで固定)。pymatgen の
    ``calculate_bv_sum_unordered`` は近接原子が ``PeriodicNeighbor`` のとき ``.specie`` を引いて
    AttributeError になる (実データ T2 garnet の Fe/Al 混合サイトで踏んだ) ので使わない。
    """
    from pymatgen.analysis.bond_valence import BV_PARAMS, ELECTRONEG

    occ = sum(site.species.values())
    total = 0.0
    for sp_i, amt_i in site.species.items():
        el_i = sp_i.element if hasattr(sp_i, "element") else sp_i
        for nb in neighbors:
            for sp_j, amt_j in nb.species.items():
                el_j = sp_j.element if hasattr(sp_j, "element") else sp_j
                if el_i == el_j or (el_i not in ELECTRONEG and el_j not in ELECTRONEG):
                    continue
                r1, c1 = BV_PARAMS[el_i]["r"], BV_PARAMS[el_i]["c"]
                r2, c2 = BV_PARAMS[el_j]["r"], BV_PARAMS[el_j]["c"]
                r0 = r1 + r2 - r1 * r2 * (math.sqrt(c1) - math.sqrt(c2)) ** 2 / (c1 * r1 + c2 * r2)
                v = math.exp((r0 - float(nb.nn_distance)) / 0.31)
                total += (amt_i / occ) * float(amt_j) * v * (1 if el_i.X < el_j.X else -1)
    return total


def _gii(pmg, valences: Mapping[str, float]) -> tuple[Check, dict]:
    devs: list[float] = []
    for site in pmg:
        bvs = _bv_sum(site, pmg.get_neighbors(site, _NEIGHBOR_CUTOFF))
        occ = sum(site.species.values())
        expected = sum(abs(valences[el.symbol]) * amt for el, amt in site.species.items()) / occ
        devs.append((abs(bvs) - expected) ** 2)
    if not devs:
        return Check.UNEVALUATED, {"reason": "no_sites"}
    gii = math.sqrt(sum(devs) / len(devs))
    return (Check.FAIL if gii > _GII_FAIL else Check.PASS), {"gii": gii, "limit": _GII_FAIL}


def _charge(pmg, valences: Mapping[str, float]) -> tuple[Check, dict]:
    comp = pmg.composition
    total = sum(valences[el.symbol] * amt for el, amt in comp.items())
    scale = sum(abs(valences[el.symbol]) * amt for el, amt in comp.items())
    if scale <= 0.0:
        return Check.UNEVALUATED, {"reason": "no_charge"}
    imbalance = abs(total) / scale
    outcome = Check.FAIL if imbalance > _CHARGE_FAIL else Check.PASS
    return outcome, {"imbalance": imbalance, "limit": _CHARGE_FAIL}


def crystal_chemistry(
    phase: str, structure_path: str, result: object
) -> dict[str, tuple[Check, Witness]]:
    """相 1 つの結晶化学検査。検査名 → (結果, 証人)。``"crystal_chemistry"`` に最悪を足して返す。

    例外は送出しない — 何かが組めなければ ``unevaluated`` とその理由を返す。
    """
    try:
        import pymatgen  # noqa: F401
    except ImportError:
        out = _all(Check.UNEVALUATED, "pymatgen_unavailable")
    else:
        out = _evaluate(phase, structure_path, result)
    worst = Check.PASS
    for outcome, _ in out.values():
        worst = worse_check(worst, outcome)
    summary = Witness("crystal_chemistry", {
        "version": CHEMISTRY_VERSION,
        "checks": {name: {"outcome": o.value, **dict(w.detail)} for name, (o, w) in out.items()},
    })
    return {**out, "crystal_chemistry": (worst, summary)}


def _evaluate(phase: str, structure_path: str, result: object) -> dict[str, tuple[Check, Witness]]:
    try:
        base, refined = _refined_structure(structure_path, phase, result)
        pmg_input = _to_pymatgen(base, phase)
        pmg = _to_pymatgen(refined, phase)
    except Exception as exc:  # noqa: BLE001 — 組めなければ検査していない (pass にしない)
        return _all(Check.UNEVALUATED, f"structure_unavailable: {type(exc).__name__}: {exc}")

    def witness(detail: Mapping[str, object]) -> Witness:
        return Witness("crystal_chemistry", {"version": CHEMISTRY_VERSION, **detail})

    out: dict[str, tuple[Check, Witness]] = {}
    try:
        outcome, detail = _short_contact(pmg)
    except Exception as exc:  # noqa: BLE001
        outcome, detail = Check.UNEVALUATED, {"reason": f"{type(exc).__name__}: {exc}"}
    out["short_contact"] = (outcome, witness(detail))

    try:
        valences = _element_valences(pmg_input)
    except Exception as exc:  # noqa: BLE001 — 酸化数を決められない
        reason = {"reason": f"valences_unavailable: {type(exc).__name__}: {exc}"}
        out["bvs_gii"] = (Check.UNEVALUATED, witness(reason))
        out["charge_neutrality"] = (Check.UNEVALUATED, witness(reason))
        return out
    for name, fn in (("bvs_gii", _gii), ("charge_neutrality", _charge)):
        try:
            outcome, detail = fn(pmg, valences)
        except Exception as exc:  # noqa: BLE001 — パラメータの無い元素など
            outcome, detail = Check.UNEVALUATED, {"reason": f"{type(exc).__name__}: {exc}"}
        out[name] = (outcome, witness({**detail, "valences": dict(valences)}))
    return out


def _cartesian_sigma(esd: object, lattice_lengths: tuple[float, float, float]) -> float:
    """原子 1 つの位置の esd を、方向によらない 1 次元の σ (Å) に畳む (対角近似)。

    軸ごとの σ_x·|a| を二乗平均して √3 で割る (等方とみなしたときの 1 方向あたりの σ)。精密化しなかった軸は 0。
    """
    if not isinstance(esd, (tuple, list)) or len(esd) != 3:
        return 0.0
    total = 0.0
    for s, length in zip(esd, lattice_lengths):
        if s is not None and math.isfinite(float(s)):
            total += (float(s) * length) ** 2
    return math.sqrt(total / 3.0)


def short_bonds(phase: str, structure_path: str, result: object) -> tuple[int | None, dict]:
    """P0 §1.4 の短結合の外れ ``b``: 第一配位圏 (``_NEIGHBOR_CUTOFF`` 以内) の結合のうち
    ``d + 3σ_d < d_min`` のものの数。``d_min`` は ``short_contact`` と同じ表 (原子半径の和 × 0.7)。

    - σ_d は両端の原子の位置の esd を対角近似で合成する (`_cartesian_sigma`)。格子の esd は入れない。
    - 対称で等価な結合は 1 本に数える (非対称単位のラベルの対と距離で同一視)。分割サイトの対は除く。
    - 例外は送出しない。組めなければ ``(None, {"reason": ...})`` (0 にしない)。
    """
    try:
        import pymatgen  # noqa: F401
        from pymatgen.core.periodic_table import Element

        _, refined = _refined_structure(structure_path, phase, result)
        pmg = _to_pymatgen(refined, phase)
    except Exception as exc:  # noqa: BLE001 — 組めなければ数えていない
        return None, {"reason": f"structure_unavailable: {type(exc).__name__}: {exc}"}
    esd = getattr(result, "atom_coord_esd", {}).get(phase) or {}
    lengths = (float(refined.a), float(refined.b), float(refined.c))
    seen: set[tuple[str, str, float]] = set()
    bonds: list[dict] = []
    for i, site in enumerate(pmg):
        for nb in pmg.get_neighbors(site, _NEIGHBOR_CUTOFF):
            if nb.index <= i:
                continue
            occ_i = sum(site.species.values())
            occ_j = sum(nb.species.values())
            if occ_i < 1.0 - 1e-6 and occ_j < 1.0 - 1e-6 and occ_i + occ_j <= 1.0 + 1e-2:
                continue
            d = float(nb.nn_distance)
            li, lj = str(site.label), str(nb.label)
            sigma_d = math.hypot(_cartesian_sigma(esd.get(li), lengths), _cartesian_sigma(esd.get(lj), lengths))
            for el_i in site.species:
                for el_j in nb.species:
                    ri = Element(el_i.symbol).atomic_radius
                    rj = Element(el_j.symbol).atomic_radius
                    if ri is None or rj is None:
                        continue
                    d_min = _SHORT_CONTACT_RATIO * (float(ri) + float(rj))
                    if d + 3.0 * sigma_d < d_min:
                        labels = sorted((li, lj))
                        key = (labels[0], labels[1], round(d, 3))
                        if key not in seen:
                            seen.add(key)
                            bonds.append({"labels": labels, "distance": d, "sigma": sigma_d, "d_min": d_min})
    return len(bonds), {"bonds": bonds, "ratio": _SHORT_CONTACT_RATIO, "version": CHEMISTRY_VERSION}
