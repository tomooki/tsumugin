"""P0 §5: 反証プローブの登録 (効果量 Δ) と、報告の 1 行の判定。

既定 (凍結・固定・まとめ) を、それを外した大きい模型と比べる。判定量は Hamilton の R 比 ``Δχ²/GOF²`` (入れ子)。
登録する効果量 Δ は「出版する値を一致判定の床の外へ動かす最小のずれ」(P0 §5.2 の原則)。床は
`autorietveld.agreement.AgreementTolerances` の値 (座標 0.02 Å・格子 相対 1e-4・Uiso 0.002 Å²) で、P0 で登録済みの 2 つ
(ゼロ点 0.01°・副相の格子 0.5%) はそのまま写す。

| id | 外す既定 | 足す母数 k | Δ |
|---|---|---|---|
| ``zero_fixed`` | ゼロ点の固定 (``Shift`` のみ) | 1 | 0.01° (P0 §5.2) |
| ``minor_cell_frozen`` | 副相の格子の凍結 | 独立な格子定数 | 各 0.5% (P0 §5.2) |
| ``minor_coords_frozen`` | 副相の座標の凍結 (テンプレートの非対象相) | 自由座標 | 各軸で原子が 0.02 Å 動く分率 |
| ``minor_uiso_frozen`` | 副相の Uiso の凍結 (同上) | Uiso の組 | 各 0.002 Å² |
| ``uiso_grouping`` | 対象相の Uiso のまとめ | 組を分けて増える母数 | 各 0.002 Å² |

検出力は非心度 ``λ = Δᵀ Σ₂₂⁻¹ Δ`` (Σ₂₂ は大きい模型の共分散のうち足した母数の部分。GSAS の共分散は GOF² を含むので
割り直さない) で ``P(χ²_k(λ) > critical)``。符号の組み合わせは λ が最小のものを採る (見分けにくい向きで報告する)。
判定 (P0 §5.1): 統計量 > 臨界値 → ``refuted`` / 検出力 ≥ 0.8 → ``not_refuted`` / それ以外 → ``not_refuted_low_power``。
fit の失敗・非有限は ``unevaluated(<理由>)``。scipy (χ² 分位点・非心 χ²) は遅延 import。
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "MIN_POWER",
    "PROBES",
    "ProbeSpec",
    "classify",
    "delta_cell",
    "delta_coords",
    "delta_uiso",
    "delta_zero",
    "noncentrality",
    "power",
]

MIN_POWER = 0.8
_ZERO_DEG = 0.01
_CELL_FRAC = 0.005
_COORD_ANG = 0.02
_UISO = 0.002
_MAX_SIGN_SEARCH = 12  # 2^12 通りまでは全符号を調べる。超えたら全て正の向きで報告する


@dataclass(frozen=True)
class ProbeSpec:
    probe_id: str
    test: str
    phase_role: str
    rationale: str


PROBES: dict[str, ProbeSpec] = {
    "zero_fixed": ProbeSpec("zero_fixed", "hamilton", "main",
                            "P0 §5.2: 2θ=60° で格子に 1.5e-4 の相対誤差 = 格子の一致判定の床を超える最小級"),
    "minor_cell_frozen": ProbeSpec("minor_cell_frozen", "hamilton", "minor",
                                   "P0 §5.2: Phase B の格子摂動より小さく収束半径内 = 凍結で隠れる誤差の規模"),
    "minor_coords_frozen": ProbeSpec("minor_coords_frozen", "hamilton", "minor",
                                     "座標の一致の床 0.02 Å (AgreementTolerances.coord_dist_floor_ang)"),
    "minor_uiso_frozen": ProbeSpec("minor_uiso_frozen", "hamilton", "minor",
                                   "Uiso の一致の床 0.002 Å² (AgreementTolerances.uiso_abs_floor)"),
    "uiso_grouping": ProbeSpec("uiso_grouping", "hamilton", "main",
                               "Uiso の一致の床 0.002 Å² — まとめた組の中で値が床を超えて違うなら、まとめは誤り"),
}


def delta_zero() -> list[float]:
    return [_ZERO_DEG]


def delta_cell(independent_cell: Sequence[float]) -> list[float]:
    return [_CELL_FRAC * float(v) for v in independent_cell]


def delta_coords(axes: Sequence[tuple[str, float]]) -> list[float]:
    """自由軸 (軸名, その軸の長さ Å) ごとに、原子が 0.02 Å 動く分率。"""
    return [_COORD_ANG / float(length) for _, length in axes]


def delta_uiso(n: int) -> list[float]:
    return [_UISO] * int(n)


def noncentrality(delta: Sequence[float], cov: np.ndarray) -> float:
    """``λ = Δᵀ Σ⁻¹ Δ`` の符号の組み合わせについての最小。"""
    d = np.asarray(delta, dtype=float)
    c = np.asarray(cov, dtype=float)
    if d.size > _MAX_SIGN_SEARCH:
        return float(d @ np.linalg.solve(c, d))
    best = math.inf
    for signs in itertools.product((1.0, -1.0), repeat=max(d.size - 1, 0)):
        v = d * np.array((1.0, *signs))  # 先頭の符号は固定 (全体の符号反転で λ は変わらない)
        best = min(best, float(v @ np.linalg.solve(c, v)))
    return best


def power(lam: float, *, k: int, alpha: float) -> float:
    from scipy.stats import chi2, ncx2

    crit = chi2.ppf(1.0 - alpha, k)
    if lam <= 0.0:
        return float(chi2.sf(crit, k))
    return float(ncx2.sf(crit, k, lam))


def classify(
    *, statistic: float | None, lam: float | None, k: int, alpha: float, failure: str = ""
) -> str:
    """P0 §5.1 の ``outcome``。"""
    from scipy.stats import chi2

    if failure:
        return f"unevaluated({failure})"
    if statistic is None or lam is None or not math.isfinite(statistic) or not math.isfinite(lam):
        return "unevaluated(non-finite statistic)"
    if statistic > chi2.ppf(1.0 - alpha, k):
        return "refuted"
    return "not_refuted" if power(lam, k=k, alpha=alpha) >= MIN_POWER else "not_refuted_low_power"
