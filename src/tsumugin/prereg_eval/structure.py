"""P0 §1.3: 独立参照がある事例の構造の悪化 — 規格化偏差 u・D (RMS)・n_out。

- ``u = |Δ| / max(σ_c, f/3)``、``σ_c = √(σ_ref² + σ_fit²)`` (GOF を掛けない)。精密化しなかった値は σ_fit = 0。
- 座標は**原子ごとの変位の Å 距離** |Δr|。σ は軸ごとの esd を対角近似で伝播する (``∂|Δr|/∂x_i`` で重みを付けた和)。
- 床 f: 座標 0.02 Å・占有率 0.02・格子 相対 1e-4 (既存の一致判定 ``AgreementTolerances`` と同じ値と単位)。
- アーム間の比較 (P0 §2.1 (c)) は ``other`` を渡し、σ_fit を両アームの大きい方に揃える (悪いアームが得をしない)。
- σ_ref の無い参照値・アーム側に値の無いものは ``unevaluated`` (``pass`` に数えない)。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "FLOOR_CELL_REL",
    "FLOOR_COORD_ANG",
    "FLOOR_OCCUPANCY",
    "OUTLIER_U",
    "Deviations",
    "FitValue",
    "RefValue",
    "StructureMetrics",
    "deviations",
    "metrics",
]

FLOOR_COORD_ANG = 0.02
FLOOR_OCCUPANCY = 0.02
FLOOR_CELL_REL = 1e-4
#: 外れ = u > 3 (既存の一致判定の k_esd)
OUTLIER_U = 3.0

_KINDS = ("coord", "occupancy", "cell")

Scalar = float
Triple = tuple[float, float, float]
OptTriple = tuple["float | None", "float | None", "float | None"]


@dataclass(frozen=True)
class RefValue:
    """参照構造の 1 値。座標は ``value`` が分率 3 成分、``sigma`` が 3 つの esd (どれか None なら unevaluated)。"""

    kind: str
    key: str
    value: "Scalar | Triple"
    sigma: "Scalar | OptTriple | None"


@dataclass(frozen=True)
class FitValue:
    """アームの 1 値。``refined=False`` なら σ_fit = 0 として扱う。"""

    kind: str
    key: str
    value: "Scalar | Triple"
    sigma: "Scalar | Triple | None"
    refined: bool


@dataclass(frozen=True)
class Deviations:
    values: dict[str, float]
    unevaluated: tuple[str, ...]


@dataclass(frozen=True)
class StructureMetrics:
    d: float | None
    n_out: int | None
    n_evaluated: int
    n_unevaluated: int


def _fit_sigma(v: FitValue | None) -> "float | Triple":
    if v is None or not v.refined or v.sigma is None:
        return (0.0, 0.0, 0.0) if (v is not None and v.kind == "coord") else 0.0
    return v.sigma


def _larger(a: "float | Triple", b: "float | Triple") -> "float | Triple":
    if isinstance(a, tuple):
        return tuple(max(float(x), float(y)) for x, y in zip(a, b))  # type: ignore[arg-type]
    return max(float(a), float(b))  # type: ignore[arg-type]


def _scalar_u(ref: RefValue, fit_value: float, sig_fit: float) -> float:
    delta = abs(float(fit_value) - float(ref.value))  # type: ignore[arg-type]
    sigma_c = math.hypot(float(ref.sigma), sig_fit)  # type: ignore[arg-type]
    floor = FLOOR_OCCUPANCY if ref.kind == "occupancy" else FLOOR_CELL_REL * abs(float(ref.value))  # type: ignore[arg-type]
    return delta / max(sigma_c, floor / 3.0)


def _coord_u(ref: RefValue, fit_value: Triple, sig_fit: Triple, lattice: np.ndarray) -> float:
    dfrac = np.asarray(fit_value, dtype=float) - np.asarray(ref.value, dtype=float)
    dr = dfrac @ lattice
    dist = float(np.linalg.norm(dr))
    if dist == 0.0:
        return 0.0
    n = dr / dist
    weights = lattice @ n  # ∂|Δr|/∂x_i = n · a_i
    var = math.fsum(
        float(w) ** 2 * (float(sr) ** 2 + float(sf) ** 2)
        for w, sr, sf in zip(weights, ref.sigma, sig_fit)  # type: ignore[arg-type]
    )
    return dist / max(math.sqrt(var), FLOOR_COORD_ANG / 3.0)


def _has_ref_sigma(ref: RefValue) -> bool:
    if ref.sigma is None:
        return False
    if isinstance(ref.sigma, tuple):
        return all(s is not None for s in ref.sigma)
    return True


def deviations(
    reference: Iterable[RefValue],
    fit: Iterable[FitValue],
    *,
    lattice: "np.ndarray | Sequence[Sequence[float]]",
    other: Iterable[FitValue] | None = None,
) -> Deviations:
    """比較集合の各値の u。``lattice`` は行が格子ベクトル (Å) の 3×3 (分率 → デカルト)。"""
    mat = np.asarray(lattice, dtype=float)
    by_key = {v.key: v for v in fit}
    other_by_key: Mapping[str, FitValue] | None = None if other is None else {v.key: v for v in other}
    values: dict[str, float] = {}
    unevaluated: list[str] = []
    for ref in reference:
        if ref.kind not in _KINDS:
            raise ValueError(f"未知の kind: {ref.kind!r}")
        mine = by_key.get(ref.key)
        if mine is None or not _has_ref_sigma(ref) or mine.kind != ref.kind:
            unevaluated.append(ref.key)
            continue
        sig = _fit_sigma(mine)
        if other_by_key is not None:
            sig = _larger(sig, _fit_sigma(other_by_key.get(ref.key)))
        if ref.kind == "coord":
            values[ref.key] = _coord_u(ref, mine.value, sig, mat)  # type: ignore[arg-type]
        else:
            values[ref.key] = _scalar_u(ref, mine.value, sig)  # type: ignore[arg-type]
    return Deviations(values=values, unevaluated=tuple(unevaluated))


def metrics(values: Mapping[str, float], *, unevaluated: Sequence[str] = ()) -> StructureMetrics:
    """D = u の RMS、n_out = u > 3 の件数。評価した値が無ければ D・n_out は None。"""
    us = [float(u) for u in values.values()]
    if not us:
        return StructureMetrics(None, None, 0, len(unevaluated))
    d = math.sqrt(math.fsum(u * u for u in us) / len(us))
    return StructureMetrics(d, sum(1 for u in us if u > OUTLIER_U), len(us), len(unevaluated))
