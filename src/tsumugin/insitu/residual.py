"""残差 S/N による「2相目を追加すべきか」の判定 (operando 逐次解析)。

既存相で fit した後の残差 (Yobs−Ycalc) に、ノイズを超える**未説明ピーク**があれば、未同定の相が
残っている証拠になる。恣意的な Rwp 比閾値でなく、計数統計ノイズ σ に対する残差ピークの S/N で
判定することで、「本物の未説明反射」と「ノイズ/過剰適合」を原理的に区別する (F 検定/Hamilton R 比
検定と同型)。

- **トリガ**: 残差に S/N > 閾値 の未説明ピークがある → 2相目を探す。
- **受理補助**: 候補追加で残差 S/N が有意に下がる → その候補が未説明ピークを説明した証拠。

構造化ピーク (数点に跨る反射) は移動平均で S/N が √窓 倍に上がり、単点ノイズは平均で消える。numpy のみ。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = ["ResidualSignificance", "residual_significance"]


@dataclass(frozen=True)
class ResidualSignificance:
    """残差の未説明ピークの有意性。🔵"""

    max_snr: float  # 最大の未説明ピークの S/N 🔵
    n_3sigma: int  # S/N ≥ 3 の未説明ピーク数 🔵
    n_5sigma: int  # S/N ≥ 5 の未説明ピーク数 🔵

    def warrants_new_phase(self, snr_threshold: float) -> bool:
        """残差 S/N が閾値を超える未説明ピークを持つか (2相目追加の是非)。"""
        return self.max_snr >= snr_threshold


def residual_significance(
    two_theta: np.ndarray,
    residual: np.ndarray,
    sigma: np.ndarray,
    *,
    smooth_window: int = 5,
    min_frac: float = 0.0,
) -> ResidualSignificance:
    """残差の**正の未説明ピーク**の S/N を推定する (計数統計ノイズ σ 比)。

    :param two_theta: 2θ (未使用だが対称性のため受ける)
    :param residual: Yobs−Ycalc (レンジ内)
    :param sigma: 各点の標準偏差 (計数統計)。0/非有限は無視
    :param smooth_window: 移動平均窓 (点数)。反射幅 ~数点を想定。ノイズを √窓 倍抑制
    :param min_frac: 検出する残差ピークの最小高 (最大残差比)。ノイズ床の切り上げ
    :returns: ResidualSignificance (max_snr, n_3sigma, n_5sigma)。データ不足は全 0
    """
    r = np.asarray(residual, dtype=float)
    s = np.asarray(sigma, dtype=float)
    k = max(1, int(smooth_window))
    if r.size < k + 2 or r.size != s.size:
        return ResidualSignificance(0.0, 0, 0)

    # 移動平均で単点ノイズを緩和 (構造化ピークは残す)
    kernel = np.ones(k) / k
    r_sm = np.convolve(r, kernel, mode="same")
    # 平滑化後のノイズ: σ_local / √k。σ 無効点は inf (S/N=0 相当) にする
    with np.errstate(divide="ignore", invalid="ignore"):
        s_sm = np.where((s > 0) & np.isfinite(s), s / np.sqrt(k), np.inf)
        snr = np.where(np.isfinite(s_sm) & (s_sm > 0), r_sm / s_sm, 0.0)

    # 正の局所極大 (未説明ピーク) のみ
    thresh = min_frac * float(np.nanmax(r_sm)) if r_sm.size else 0.0
    interior = np.zeros(r_sm.size, dtype=bool)
    interior[1:-1] = (
        (r_sm[1:-1] > r_sm[:-2]) & (r_sm[1:-1] > r_sm[2:]) & (r_sm[1:-1] > max(thresh, 0.0))
    )
    peak_snr = snr[interior]
    if peak_snr.size == 0:
        return ResidualSignificance(0.0, 0, 0)
    return ResidualSignificance(
        max_snr=float(peak_snr.max()),
        n_3sigma=int(np.count_nonzero(peak_snr >= 3.0)),
        n_5sigma=int(np.count_nonzero(peak_snr >= 5.0)),
    )
