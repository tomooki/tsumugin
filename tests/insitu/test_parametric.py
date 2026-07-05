"""M9 insitu.parametric の純テスト (numpy-only)。sequential.thermal 上の抽出層を検証。"""

from __future__ import annotations

import pytest

from tsumugin.insitu.model import FrameRietveldResult, SequentialRietveldResult
from tsumugin.insitu.parametric import (
    analyze_phase,
    lattice_baseline,
    pseudo_variable_series,
    transition_from_fractions,
)


def _frame(i, axis, cells, fracs, names):
    return FrameRietveldResult(
        frame_index=i, axis_value=axis, data_path=f"f{i}", rwp=9.0, gof=1.0,
        refined_cells=cells, phase_fractions=fracs, phase_names=names,
    )


def _linear_expansion_result():
    """alpha 相の a が温度で線形膨張 (a = 14.8 + 0.001*(T-300))。"""
    frames = []
    for k, T in enumerate([300.0, 320.0, 340.0, 360.0, 380.0]):
        a = 14.8 + 0.001 * (T - 300.0)
        frames.append(_frame(k, T, {"alpha": (a, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0}, ("alpha",)))
    return SequentialRietveldResult(frames=tuple(frames))


def test_lattice_baseline_linear_slope():
    r = _linear_expansion_result()
    bl = lattice_baseline(r, "alpha", component="a", degree=1)
    # coefficients 低次から: [intercept, slope]。slope ≈ 0.001
    assert bl.parameter == "alpha.a"
    assert bl.coefficients[1] == pytest.approx(0.001, abs=1e-6)
    assert bl.outlier_frames == ()  # 完全線形なら逸脱なし


def test_transition_appearing_midpoint():
    # delta の相分率が 0→1 に遷移 (midpoint ~ 340K で 50%)
    fracs_by_T = [(300.0, 0.0), (320.0, 0.0), (340.0, 0.5), (360.0, 1.0), (380.0, 1.0)]
    frames = []
    for k, (T, fd) in enumerate(fracs_by_T):
        cells = {"delta": (13.3, 6.5, 8.1, 90, 90, 90)} if fd > 0 else {}
        names = ("delta",) if fd > 0 else ()
        frames.append(_frame(k, T, cells, {"delta": fd}, names))
    r = SequentialRietveldResult(frames=tuple(frames))
    tr = transition_from_fractions(r, "delta")
    assert tr is not None
    assert tr.midpoint == pytest.approx(340.0, abs=1.0)
    assert tr.direction == "appearing"


def test_transition_none_when_constant():
    frames = tuple(
        _frame(k, 300.0 + 20 * k, {"a": (5, 5, 5, 90, 90, 90)}, {"a": 1.0}, ("a",))
        for k in range(4)
    )
    r = SequentialRietveldResult(frames=frames)
    assert transition_from_fractions(r, "a") is None


def test_pseudo_variable_bc_ratio():
    # b/c 比が 1.0 に収束していく (2 次転移の擬変数)
    frames = [
        _frame(0, 100.0, {"p": (5.0, 6.0, 8.0, 90, 90, 90)}, {"p": 1.0}, ("p",)),
        _frame(1, 120.0, {"p": (5.0, 7.0, 8.0, 90, 90, 90)}, {"p": 1.0}, ("p",)),
        _frame(2, 140.0, {"p": (5.0, 8.0, 8.0, 90, 90, 90)}, {"p": 1.0}, ("p",)),
    ]
    r = SequentialRietveldResult(frames=tuple(frames))
    axes, ratios = pseudo_variable_series(r, "p", lambda c: c[1] / c[2])
    assert axes == (100.0, 120.0, 140.0)
    assert ratios == pytest.approx((0.75, 0.875, 1.0))


def test_analyze_phase_bundles():
    r = _linear_expansion_result()
    pa = analyze_phase(r, "alpha", component="a")
    assert pa.phase == "alpha"
    assert pa.baseline.coefficients[1] == pytest.approx(0.001, abs=1e-6)
    assert pa.transition is None  # 定数分率 (単相)
