"""同一データ上の 2 つの fit を比べる判定量 (fit-then-judge proposal §5)。

| 比較 | 判定量 |
|---|---|
| 入れ子のモデル (k 個の母数を足す) | **Hamilton の R 比検定 ≒ 尤度比**: ``Δχ²/GOF²_big`` を自由度 k の χ² 分位点と比べる |
| 母数の数が同じ 2 解 | 計算値の差 ``S = Σ((m₁−m₂)/σ)²``。``S/GOF²`` が χ²₁ の分位点未満なら区別できない。大きければ ``z = Δχ²/(2·GOF·√S)`` |
| 「同じ解か」 | パラメータ差がそれぞれ kσ 以内 (``autorietveld.agreement.parameter_agreements`` が唯一の実装) |

**σ(χ²)=√(2·dof) は使わない** — それはデータを取り直したときのばらつきで、同じデータ上の 2 つの fit の差の
雑音ではない (点数が増えるほど甘くなる)。``tests/evidence/test_fitstats.py`` が ``src/`` 全体を走査して縛る。

**実効自由度**: 残差に系列相関があると χ² は独立な点の数を過大に数え、検定が甘くなる。Durbin–Watson 統計から
一次の相関 ρ を推定し、AR(1) の近似 ``n_eff/n = (1−ρ)/(1+ρ)`` で判定量を縮める (Bérar–Lelann 型の補正と同じ ρ)。
esd には掛けない (GSAS の esd は既に GOF² を含む — 掛け直すと二重になる)。

numpy のみを import する。χ² 分位点だけ scipy を**遅延 import** する (コア import は numpy のみの規約)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

__all__ = [
    "HamiltonResult",
    "SameDofComparison",
    "chi2_from_stage",
    "effective_dof_ratio",
    "hamilton_test",
    "same_dof_comparison",
]


def _chi2_quantile(p: float, k: int) -> float:
    from scipy.stats import chi2

    return float(chi2.ppf(p, k))


def _finite(*xs: float) -> bool:
    return all(isinstance(x, (int, float)) and math.isfinite(x) for x in xs)


@dataclass(frozen=True)
class HamiltonResult:
    """入れ子のモデルの比較の結果。derivation にそのまま載せる (何と比べてどう判定したか)。"""

    significant: bool
    lr: float
    critical: float
    k: int
    alpha: float
    dof_ratio: float

    def to_dict(self) -> dict[str, object]:
        return {
            "significant": self.significant, "lr": self.lr, "critical": self.critical,
            "k": self.k, "alpha": self.alpha, "dof_ratio": self.dof_ratio,
        }


def hamilton_test(
    chi2_small: float,
    chi2_big: float,
    gof2_big: float,
    k: int,
    *,
    alpha: float,
    dof_ratio: float = 1.0,
) -> "HamiltonResult | None":
    """母数を k 個足したモデル (big) が有意に良いか (Hamilton の R 比検定 ≒ 尤度比)。

    判定量 ``LR = (χ²_small − χ²_big) / GOF²_big · dof_ratio`` を χ²_k の ``1−α`` 分位点と比べる。
    GOF² で割るのは、χ² が「重みが正しい」前提の量だから (GSAS の重みはしばしば過小で GOF > 1)。

    :param dof_ratio: 実効自由度の比 ``n_eff/n`` (`effective_dof_ratio`)。基準モデル (小さい方) の残差から
        1 回計算して渡す。(0, 1] の外は判定しない
    :returns: 判定できない入力 (非有限・k<1・GOF²≤0・不正な比) では ``None`` — 「有意でない」と区別する
    """
    if not _finite(chi2_small, chi2_big, gof2_big, dof_ratio, alpha):
        return None
    if k < 1 or gof2_big <= 0.0 or not (0.0 < dof_ratio <= 1.0) or not (0.0 < alpha < 1.0):
        return None
    lr = (chi2_small - chi2_big) / gof2_big * dof_ratio
    critical = _chi2_quantile(1.0 - alpha, k)
    return HamiltonResult(
        significant=bool(lr > critical), lr=float(lr), critical=critical,
        k=int(k), alpha=float(alpha), dof_ratio=float(dof_ratio),
    )


def chi2_from_stage(*, gof: float, n_obs: int, n_params: int) -> "float | None":
    """GSAS の段の値から χ² を戻す (``GOF = sqrt(χ²/(N−P))`` なので ``χ² = GOF²·(N−P)``)。

    ⚠ 拘束 (restraint) を張った fit では GOF が拘束項を含むので使わない (テンプレートは拘束を張らない)。
    """
    if not _finite(gof) or n_obs - n_params <= 0:
        return None
    return float(gof) ** 2 * (n_obs - n_params)


@dataclass(frozen=True)
class SameDofComparison:
    """母数の数が同じ 2 解の比較。``z`` は区別できるときだけ持つ。"""

    distinguishable: bool
    s: float
    critical: float
    z: "float | None"

    def to_dict(self) -> dict[str, object]:
        return {"distinguishable": self.distinguishable, "s": self.s,
                "critical": self.critical, "z": self.z}


def same_dof_comparison(
    m1: np.ndarray,
    m2: np.ndarray,
    sigma: np.ndarray,
    chi2_1: float,
    chi2_2: float,
    gof2: float,
    *,
    alpha: float,
) -> "SameDofComparison | None":
    """母数の数が同じ 2 解 (ベイスン・±δ) を計算値の差で比べる。

    ``S = Σ((m₁−m₂)/σ)²`` は「2 つの計算パターンがどれだけ違うか」を観測の誤差の単位で測る量。
    ``S/GOF²`` が χ²₁ の分位点未満ならデータは 2 解を区別できない。区別できるなら
    ``z = Δχ²/(2·GOF·√S)`` (Δχ² = χ²₁ − χ²₂ — 正なら 2 が良い)。
    """
    a = np.asarray(m1, dtype=float)
    b = np.asarray(m2, dtype=float)
    s_ = np.asarray(sigma, dtype=float)
    if a.shape != b.shape or a.shape != s_.shape or a.size == 0:
        return None
    if not (np.all(np.isfinite(a)) and np.all(np.isfinite(b)) and np.all(np.isfinite(s_))):
        return None
    if np.any(s_ <= 0.0) or not _finite(chi2_1, chi2_2, gof2) or gof2 <= 0.0:
        return None
    s = float(np.sum(((a - b) / s_) ** 2))
    critical = _chi2_quantile(1.0 - alpha, 1)
    if s / gof2 < critical:
        return SameDofComparison(False, s, critical, None)
    z = (chi2_1 - chi2_2) / (2.0 * math.sqrt(gof2) * math.sqrt(s))
    return SameDofComparison(True, s, critical, float(z))


def effective_dof_ratio(residual: np.ndarray) -> "float | None":
    """残差の系列相関から実効自由度の比 ``n_eff/n`` を推定する。

    Durbin–Watson ``d = Σ(eᵢ−eᵢ₋₁)²/Σeᵢ²`` → ``ρ = 1 − d/2`` → ``(1−ρ)/(1+ρ)``。
    負の相関 (ρ<0) で 1 を超えた分は使わない (情報量を水増ししない)。下限は 1/n (独立な点が 1 つは残る —
    0 で割る検定を作らない)。

    :param residual: 重み付き残差 ``(Yobs−Ycalc)/σ`` を測定順に
    :returns: 点数が 3 未満・非有限を含む・全ゼロなら ``None`` (= 補正しない、と呼び手が記録する)
    """
    e = np.asarray(residual, dtype=float).ravel()
    if e.size < 3 or not np.all(np.isfinite(e)):
        return None
    denom = float(np.sum(e * e))
    if denom <= 0.0:
        return None
    d = float(np.sum(np.diff(e) ** 2)) / denom
    rho = 1.0 - d / 2.0
    if rho <= 0.0:
        return 1.0
    ratio = (1.0 - rho) / (1.0 + rho)
    return float(min(1.0, max(ratio, 1.0 / e.size)))
