"""M6 TASK-0113 Phase A: 格子ズレ吸収 (Pawley-lite: 等方歪み+ゼロシフト) の失敗テスト (Red)。

対象実装: ``src/tsumugin/reference/rietveld.py`` (未実装)。
`align_peaks(calc, observed)`: 参照計算ピークを観測へ整合させる等方格子歪み ε と 2θ ゼロシフト z を
最小二乗で求め、整合後ピーク列を返す。DFT 緩和格子のピーク位置ずれを吸収する。numpy のみ・決定論。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.search.peaks import Peak


def _peaks(*specs):
    return tuple(Peak(position=p, height=h) for p, h in specs)


def _apply_strain(peaks, eps):
    """d -> d(1+eps) の等方歪みでピーク 2θ を移す (テスト用オラクル)。"""
    out = []
    for p in peaks:
        s = math.sin(math.radians(p.position / 2.0)) / (1.0 + eps)
        if s < 1.0:
            out.append(Peak(2.0 * math.degrees(math.asin(s)), p.height))
    return tuple(out)


def test_no_offset_returns_zero_params():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0), (35.0, 80.0), (50.0, 60.0))
    r = align_peaks(calc, calc)
    assert r.strain == pytest.approx(0.0, abs=1e-4)
    assert r.zero_shift == pytest.approx(0.0, abs=1e-3)


def test_recovers_pure_zero_shift():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0), (35.0, 80.0), (50.0, 60.0), (65.0, 40.0))
    obs = tuple(Peak(p.position + 0.2, p.height) for p in calc)  # +0.2° ずれ
    r = align_peaks(calc, obs)
    assert r.zero_shift == pytest.approx(0.2, abs=0.02)
    # 整合後ピークは観測に近い
    aligned = sorted(p.position for p in r.aligned_peaks)
    assert aligned[0] == pytest.approx(20.2, abs=0.03)


def test_recovers_pure_strain():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0), (35.0, 80.0), (50.0, 60.0), (65.0, 40.0))
    obs = _apply_strain(calc, 0.005)  # 0.5% 格子膨張
    r = align_peaks(calc, obs)
    assert r.strain == pytest.approx(0.005, abs=5e-4)
    # 整合後は観測位置にほぼ一致
    obs_pos = sorted(p.position for p in obs)
    aligned = sorted(p.position for p in r.aligned_peaks)
    for a, o in zip(aligned, obs_pos):
        assert a == pytest.approx(o, abs=0.03)


def test_recovers_combined_strain_and_zero():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((18.0, 100.0), (30.0, 90.0), (44.0, 70.0), (58.0, 50.0), (72.0, 40.0))
    obs = tuple(Peak(p.position + 0.15, p.height) for p in _apply_strain(calc, 0.004))
    r = align_peaks(calc, obs)
    assert r.strain == pytest.approx(0.004, abs=8e-4)
    assert r.zero_shift == pytest.approx(0.15, abs=0.03)
    assert r.rms_residual < 0.02


def test_strain_is_bounded():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0), (40.0, 80.0), (60.0, 60.0))
    obs = _apply_strain(calc, 0.05)  # 5% (上限 1% を超える)
    r = align_peaks(calc, obs, max_strain=0.01)
    assert abs(r.strain) <= 0.01 + 1e-9


def test_too_few_matches_returns_identity():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0))
    obs = _peaks((80.0, 100.0))  # 全く一致しない
    r = align_peaks(calc, obs)
    assert r.strain == pytest.approx(0.0)
    assert r.zero_shift == pytest.approx(0.0)
    assert r.n_matched < 2


def test_deterministic():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0), (35.0, 80.0), (50.0, 60.0))
    obs = _apply_strain(calc, 0.003)
    a = align_peaks(calc, obs)
    b = align_peaks(calc, obs)
    assert a.strain == b.strain
    assert a.zero_shift == b.zero_shift


def test_aligned_preserves_heights_and_count_for_in_range():
    from tsumugin.reference.rietveld import align_peaks

    calc = _peaks((20.0, 100.0), (35.0, 80.0), (50.0, 60.0))
    obs = _apply_strain(calc, 0.002)
    r = align_peaks(calc, obs)
    assert len(r.aligned_peaks) == len(calc)
    assert sorted(p.height for p in r.aligned_peaks) == sorted(p.height for p in calc)
