"""残差 S/N 判定 (insitu.residual) の numpy 決定論テスト。

構造化した未説明ピークは高 S/N、単点ノイズは移動平均で抑制、ノイズのみは低 S/N を検証する。
"""

from __future__ import annotations

import numpy as np

from tsumugin.insitu.residual import residual_significance


def _grid(n=2000, lo=12.0, hi=70.0):
    return np.linspace(lo, hi, n)


def test_noise_only_low_snr():
    """ノイズのみの残差は有意ピークを持たない (rng 固定で決定論)。"""
    rng = np.random.default_rng(0)
    tt = _grid()
    sigma = np.full(tt.size, 10.0)
    resid = rng.normal(0, 10.0, tt.size)  # σ=10 のノイズ
    sig = residual_significance(tt, resid, sigma)
    # ノイズは多数の局所極大の最大で ~3-4σ に達し得るが 5σ は超えない (だからトリガ閾値は ~8)。
    assert sig.max_snr < 5.0
    assert sig.n_5sigma == 0


def test_structured_peak_high_snr():
    """ノイズ上に構造化ピーク (数点に跨る反射) を置くと高 S/N で検出。"""
    rng = np.random.default_rng(1)
    tt = _grid()
    sigma = np.full(tt.size, 10.0)
    resid = rng.normal(0, 10.0, tt.size)
    # 2θ=40° 付近に FWHM ~0.3° の未説明ピーク (高さ 200 = 20σ級)
    resid += 200.0 * np.exp(-0.5 * ((tt - 40.0) / 0.15) ** 2)
    sig = residual_significance(tt, resid, sigma)
    assert sig.max_snr > 8.0
    assert sig.n_5sigma >= 1
    assert sig.warrants_new_phase(8.0)


def test_single_point_spike_suppressed():
    """単点スパイク (ノイズ) は移動平均で平坦化し未説明ピークとして検出されない (構造化と区別)。"""
    tt = _grid()
    sigma = np.full(tt.size, 10.0)
    spike = np.zeros(tt.size)
    spike[1000] = 200.0  # 単点だけ 200 のスパイク
    sig_spike = residual_significance(tt, spike, sigma)
    # 同じ高さの構造化ピーク (数点に跨る反射)
    struct = 200.0 * np.exp(-0.5 * ((tt - 40.0) / 0.15) ** 2)
    sig_struct = residual_significance(tt, struct, sigma)
    # 単点は平滑化で平坦化し S/N 低 (or 0)、構造化ピークは高 S/N。両者が明確に区別される。
    assert sig_spike.max_snr < sig_struct.max_snr
    assert sig_struct.max_snr > 8.0
    assert not sig_spike.warrants_new_phase(8.0)


def test_negative_residual_not_a_peak():
    """負の残差 (calc>obs の過剰) は未説明ピークとしない (正の未説明のみ)。"""
    tt = _grid()
    sigma = np.full(tt.size, 10.0)
    resid = -150.0 * np.exp(-0.5 * ((tt - 40.0) / 0.15) ** 2)  # 負のディップ
    sig = residual_significance(tt, resid, sigma)
    assert sig.max_snr <= 0.0 or sig.n_5sigma == 0


def test_short_or_mismatched_returns_zero():
    assert residual_significance(np.array([1.0]), np.array([1.0]), np.array([1.0])).max_snr == 0.0
    # 長さ不一致
    assert residual_significance(_grid(), np.zeros(10), np.ones(5)).n_3sigma == 0


def test_deterministic():
    tt = _grid()
    sigma = np.full(tt.size, 10.0)
    resid = 200.0 * np.exp(-0.5 * ((tt - 40.0) / 0.15) ** 2)
    a = residual_significance(tt, resid, sigma)
    b = residual_significance(tt, resid, sigma)
    assert a == b
