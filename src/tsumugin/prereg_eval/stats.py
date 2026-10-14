"""P0 §3.3 / 付録 B: 劣化率の Clopper–Pearson 片側 95% 上限と、許容件数 c(N)。

scipy を使わず、二項分布の累積 ``P(X ≤ c | n, p) = 0.05`` を p について二分法で解く
(``scipy.stats.beta.ppf(0.95, c+1, n−c)`` と同じ値)。
"""

from __future__ import annotations

import math

__all__ = ["M_NONINFERIORITY", "allowed_failures", "binomial_cdf", "upper_bound"]

#: P0 U2: 非劣性の上限 (劣化率)
M_NONINFERIORITY = 0.25
_CONFIDENCE = 0.95


def binomial_cdf(c: int, n: int, p: float) -> float:
    """``P(X ≤ c)``、X ~ Binomial(n, p)。"""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if c >= n else 0.0
    return math.fsum(math.comb(n, k) * p**k * (1.0 - p) ** (n - k) for k in range(c + 1))


def upper_bound(c: int, n: int, *, confidence: float = _CONFIDENCE) -> float:
    """n 件中 c 件の劣化から求めた劣化率の片側 ``confidence`` 上限 (Clopper–Pearson)。"""
    if n < 0 or c < 0 or c > n:
        raise ValueError(f"c={c}, n={n} は 0 ≤ c ≤ n でない")
    if c == n:
        return 1.0
    alpha = 1.0 - confidence
    lo, hi = 0.0, 1.0
    for _ in range(200):  # 区間は 2^-200 未満まで縮む (倍精度の限界で止まる)
        mid = 0.5 * (lo + hi)
        if binomial_cdf(c, n, mid) > alpha:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-15:
            break
    return 0.5 * (lo + hi)


def allowed_failures(n: int, *, margin: float = M_NONINFERIORITY) -> int | None:
    """上限 < ``margin`` を満たす最大の劣化件数 c(N)。0 件でも満たさなければ None (何も示せない)。"""
    if n < 0:
        raise ValueError(f"n={n} は負")
    best: int | None = None
    for c in range(n + 1):
        if upper_bound(c, n) < margin:
            best = c
        else:
            break  # 上限は c について単調増加
    return best
