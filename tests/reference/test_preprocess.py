"""M6 TASK-0110 背景減算 (SNIP) + Kα2 サテライトモデルの失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/background.py`` + ``src/tsumugin/reference/kalpha.py`` (未実装)。
- estimate_snip_background / subtract_background: 遅変化背景の推定・除去 (numpy のみ・決定論)。
- KAlpha2 / add_kalpha2_satellites: 参照ピークへ Kα2 二重線サテライトを付加。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.search.peaks import Peak


def _peak_on_background(centers, *, bg_slope=0.5, bg_intercept=100.0, height=1000.0, fwhm=0.3):
    tt = np.arange(10.0, 90.0, 0.02)
    background = bg_intercept + bg_slope * (tt - tt[0])
    sigma = fwhm / 2.3548
    y = background.copy()
    for c in centers:
        y += height * np.exp(-0.5 * ((tt - c) / sigma) ** 2)
    return tt, y, background


# --- 背景推定 (SNIP) -------------------------------------------------------


def test_snip_background_follows_baseline_not_peaks():
    from tsumugin.reference.background import estimate_snip_background

    tt, y, true_bg = _peak_on_background([40.0, 60.0])
    bg = estimate_snip_background(y, max_window=60)
    assert bg.shape == y.shape
    # 背景推定はピーク下でも真の背景に近く、ピーク強度を拾わない
    peak_i = int(np.argmin(np.abs(tt - 40.0)))
    assert bg[peak_i] < 0.3 * y[peak_i]  # ピーク位置で信号の大半を背景と誤認しない
    # ピークから離れた点では真の背景に近い
    flat_i = int(np.argmin(np.abs(tt - 25.0)))
    assert abs(bg[flat_i] - true_bg[flat_i]) < 0.2 * true_bg[flat_i]


def test_subtract_background_removes_baseline():
    from tsumugin.reference.background import subtract_background

    tt, y, _ = _peak_on_background([40.0])
    corrected = subtract_background(y, max_window=60)
    assert corrected.shape == y.shape
    assert np.all(corrected >= 0.0)  # 非負へフロア
    # ピークから離れた背景領域はほぼゼロ
    flat_i = int(np.argmin(np.abs(tt - 25.0)))
    assert corrected[flat_i] < 50.0
    # ピークは概ね保持 (背景ぶん減るが大きく残る)
    peak_i = int(np.argmin(np.abs(tt - 40.0)))
    assert corrected[peak_i] > 700.0


def test_snip_background_deterministic():
    from tsumugin.reference.background import estimate_snip_background

    _, y, _ = _peak_on_background([40.0])
    assert np.array_equal(estimate_snip_background(y), estimate_snip_background(y))


def test_subtract_background_flat_input():
    from tsumugin.reference.background import subtract_background

    y = np.full(200, 250.0)
    corrected = subtract_background(y, max_window=40)
    assert np.all(corrected < 5.0)  # 一定背景はほぼ完全に除去


# --- Kα2 サテライト --------------------------------------------------------


def test_add_kalpha2_doubles_and_places_satellite_higher():
    from tsumugin.reference.kalpha import KAlpha2, add_kalpha2_satellites

    peaks = (Peak(30.0, 100.0),)
    out = add_kalpha2_satellites(peaks, KAlpha2())
    assert len(out) == 2
    positions = sorted(p.position for p in out)
    # Kα2 は高角側 (λ2 > λ1)
    assert positions[0] == pytest.approx(30.0)
    assert positions[1] > 30.0
    # 半強度サテライト
    sat = [p for p in out if p.position > 30.0][0]
    assert sat.height == pytest.approx(50.0)


def test_kalpha2_splitting_increases_with_angle():
    from tsumugin.reference.kalpha import KAlpha2, add_kalpha2_satellites

    cfg = KAlpha2()
    low = add_kalpha2_satellites((Peak(20.0, 100.0),), cfg)
    high = add_kalpha2_satellites((Peak(80.0, 100.0),), cfg)
    split_low = max(p.position for p in low) - 20.0
    split_high = max(p.position for p in high) - 80.0
    assert split_high > split_low > 0.0


def test_kalpha2_custom_intensity_ratio():
    from tsumugin.reference.kalpha import KAlpha2, add_kalpha2_satellites

    out = add_kalpha2_satellites((Peak(30.0, 100.0),), KAlpha2(intensity_ratio=0.3))
    sat = max(out, key=lambda p: p.position)
    assert sat.height == pytest.approx(30.0)


def test_kalpha2_skips_unphysical_high_angle():
    from tsumugin.reference.kalpha import KAlpha2, add_kalpha2_satellites

    # sinθ2 > 1 になる極端角では サテライトを付けない (元ピークのみ)
    out = add_kalpha2_satellites((Peak(179.5, 100.0),), KAlpha2())
    assert all(p.position <= 180.0 for p in out)


def test_kalpha2_empty_peaks():
    from tsumugin.reference.kalpha import KAlpha2, add_kalpha2_satellites

    assert add_kalpha2_satellites((), KAlpha2()) == ()
