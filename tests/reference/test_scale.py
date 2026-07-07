"""M11 reference/scale.py — 非負スケール joint フィット + プロファイル合成の numpy 決定論テスト。"""

from __future__ import annotations

import numpy as np

from tsumugin.reference.scale import (
    build_design_matrix,
    fit_nonneg_scales,
    nnls,
    render_phase,
)

_TT = np.linspace(10.0, 80.0, 3500)
_FWHM = 0.15


def test_render_phase_peak_height():
    """単ピーク相はガウスで、ピーク位置で高さに達する。"""
    y = render_phase(_TT, [(40.0, 100.0)], _FWHM)
    i = int(np.argmin(np.abs(_TT - 40.0)))
    assert y[i] == max(y) or abs(y[i] - 100.0) < 2.0
    assert abs(max(y) - 100.0) < 2.0


def test_nnls_recovers_positive_solution():
    A = np.array([[1.0, 0.0], [0.0, 1.0], [1.0, 1.0]])
    b = np.array([2.0, 3.0, 5.0])
    x = nnls(A, b)
    assert np.allclose(x, [2.0, 3.0], atol=1e-6)


def test_nnls_clips_negative():
    """真の最小二乗解が負になる列は 0 にクリップされる。"""
    A = np.array([[1.0, 1.0], [1.0, 1.0001]])
    b = np.array([1.0, -1.0])  # 不整合 → 片方が負になりがち
    x = nnls(A, b)
    assert np.all(x >= 0.0)


def test_fit_recovers_known_scales():
    """観測 = 2·A + 3·B (非重複ピーク) を fit すると scales ≈ [2,3]。"""
    a = [(20.0, 100.0), (35.0, 60.0)]
    b = [(50.0, 80.0), (65.0, 40.0)]
    obs = 2.0 * render_phase(_TT, a, _FWHM) + 3.0 * render_phase(_TT, b, _FWHM)
    s, model, resid, unexplained = fit_nonneg_scales(_TT, obs, [a, b], _FWHM)
    assert np.allclose(s, [2.0, 3.0], atol=0.05)
    assert unexplained < 1e-3 * float(np.sum(obs**2))


def test_fit_absent_phase_gets_zero_scale():
    """観測に存在しない相 (既説明ピークのみ) はスケール≈0 (decoy 棄却の核)。"""
    a = [(20.0, 100.0), (35.0, 60.0)]
    decoy = [(20.0, 50.0)]  # A の 1 本と同位置 (残差に固有ピークを持たない)
    obs = 2.0 * render_phase(_TT, a, _FWHM)
    s, *_ = fit_nonneg_scales(_TT, obs, [a, decoy], _FWHM)
    assert s[0] > 1.0
    assert s[1] < 0.05  # decoy は自前の説明対象が無く 0 付近


def test_fit_unexplained_ss_for_extra_peak():
    """どの相にも無いピークが観測にあると unexplained_ss > 0 (正残差)。"""
    a = [(20.0, 100.0)]
    obs = render_phase(_TT, a, _FWHM) + render_phase(_TT, [(60.0, 80.0)], _FWHM)  # 60° は未説明
    _, _, _, unexplained = fit_nonneg_scales(_TT, obs, [a], _FWHM)
    assert unexplained > 0.1 * float(np.sum(render_phase(_TT, [(60.0, 80.0)], _FWHM) ** 2))


def test_fit_empty_phases():
    obs = render_phase(_TT, [(30.0, 100.0)], _FWHM)
    s, model, resid, unexplained = fit_nonneg_scales(_TT, obs, [], _FWHM)
    assert s.size == 0
    assert np.allclose(model, 0.0)
    assert np.allclose(resid, obs)
    assert unexplained > 0.0


def test_design_matrix_shape():
    A = build_design_matrix(_TT, [[(20.0, 1.0)], [(40.0, 1.0)], [(60.0, 1.0)]], _FWHM)
    assert A.shape == (_TT.size, 3)


def test_deterministic():
    a = [(20.0, 100.0), (35.0, 60.0)]
    b = [(50.0, 80.0)]
    obs = 2.0 * render_phase(_TT, a, _FWHM) + render_phase(_TT, b, _FWHM)
    r1 = fit_nonneg_scales(_TT, obs, [a, b], _FWHM)
    r2 = fit_nonneg_scales(_TT, obs, [a, b], _FWHM)
    assert np.array_equal(r1[0], r2[0])
    assert r1[3] == r2[3]
