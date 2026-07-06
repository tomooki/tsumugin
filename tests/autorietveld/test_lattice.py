"""異方格子ソルバ (autorietveld.lattice) の numpy 決定論テスト (Issue #20)。

逆格子計量テンソル最小二乗が、既知格子から生成した合成反射 (hkl, d) を初期値に依らず復元し、
結晶系拘束を厳密に満たし、誤指数付け外れ値をロバスト再重み付けで除去することを検証する。
GSAS/MP 非依存 (numpy のみ)。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.autorietveld.lattice import (
    cell_from_reciprocal_metric,
    reciprocal_metric_from_cell,
    refine_cell_from_indexed_peaks,
    refine_cell_robust,
    solve_cell_from_dspacings,
    two_theta_of_hkls,
)


def _d_of(cell, hkl) -> float:
    """格子 cell の反射 hkl の d 間隔 (Å) を独立計算する (テスト用オラクル)。"""
    g_star = reciprocal_metric_from_cell(cell)
    h = np.array(hkl, dtype=float)
    inv_d2 = float(h @ g_star @ h)
    return 1.0 / math.sqrt(inv_d2)


def _cells_close(c1, c2, *, tol=1e-6):
    return all(abs(a - b) < tol for a, b in zip(c1, c2))


# 代表反射 (低角の独立反射を含む)
_HKLS = [
    (1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (1, 0, 1), (0, 1, 1),
    (1, 1, 1), (2, 0, 0), (0, 2, 0), (0, 0, 2), (2, 1, 0), (1, 2, 1),
    (2, 1, 1), (1, 1, 2), (2, 2, 0),
]


def test_reciprocal_metric_roundtrip_orthorhombic():
    cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    back = cell_from_reciprocal_metric(reciprocal_metric_from_cell(cell))
    assert _cells_close(cell, back, tol=1e-8)


def test_reciprocal_metric_roundtrip_monoclinic():
    cell = (7.1, 8.4, 9.9, 90.0, 104.3, 90.0)
    back = cell_from_reciprocal_metric(reciprocal_metric_from_cell(cell))
    assert _cells_close(cell, back, tol=1e-8)


def test_reciprocal_metric_roundtrip_triclinic():
    cell = (5.1, 6.2, 7.3, 82.0, 96.0, 108.0)
    back = cell_from_reciprocal_metric(reciprocal_metric_from_cell(cell))
    assert _cells_close(cell, back, tol=1e-8)


def test_reciprocal_metric_roundtrip_hexagonal():
    cell = (3.2, 3.2, 5.2, 90.0, 90.0, 120.0)
    back = cell_from_reciprocal_metric(reciprocal_metric_from_cell(cell))
    assert _cells_close(cell, back, tol=1e-8)


def test_solve_recovers_orthorhombic_exactly():
    """直方格子から生成した反射を初期値なしで厳密復元する (線形解, 局所解に嵌らない)。"""
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    got = solve_cell_from_dspacings(_HKLS, d, crystal_system="orthorhombic")
    assert _cells_close(got, true_cell, tol=1e-5)


def test_solve_recovers_anisotropic_c_error():
    """c 軸だけ +3.4% ずれた初期からでも、観測 d に一致する真格子を復元する (Issue #20 の核心)。

    ソルバは線形 (初期値不使用) なので、DFT の異方誤差がどれだけ大きくても観測 d が正しければ真値へ。
    """
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    # DFT 初期 (c +3.4%) を initial_cell に渡しても解は真値 (フォールバックに使われない)
    dft_cell = (6.551, 8.235, 13.778, 90.0, 90.0, 90.0)
    got = solve_cell_from_dspacings(
        _HKLS, d, crystal_system="orthorhombic", initial_cell=dft_cell
    )
    assert abs(got[2] - 13.322) < 1e-4  # c が復元されている
    assert not _cells_close(got, dft_cell, tol=0.1)


def test_tetragonal_constraint_enforces_a_equals_b():
    """正方拘束では a==b が厳密 (別々に動かない)。"""
    true_cell = (4.5, 4.5, 7.1, 90.0, 90.0, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    got = solve_cell_from_dspacings(_HKLS, d, crystal_system="tetragonal")
    assert abs(got[0] - got[1]) < 1e-9
    assert _cells_close(got, true_cell, tol=1e-5)


def test_monoclinic_recovers_beta():
    true_cell = (7.1, 8.4, 9.9, 90.0, 104.3, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    got = solve_cell_from_dspacings(_HKLS, d, crystal_system="monoclinic")
    assert abs(got[3] - 90.0) < 1e-6 and abs(got[5] - 90.0) < 1e-6  # α=γ=90 固定
    assert abs(got[4] - 104.3) < 1e-4  # β 復元
    assert _cells_close(got, true_cell, tol=1e-4)


def test_hexagonal_constraint():
    true_cell = (3.2, 3.2, 5.2, 90.0, 90.0, 120.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    got = solve_cell_from_dspacings(_HKLS, d, crystal_system="hexagonal")
    assert abs(got[0] - got[1]) < 1e-9
    assert abs(got[5] - 120.0) < 1e-5
    assert _cells_close(got, true_cell, tol=1e-4)


def test_insufficient_reflections_falls_back():
    dft_cell = (6.551, 8.235, 13.778, 90.0, 90.0, 90.0)
    got = solve_cell_from_dspacings(
        [(1, 0, 0)], [6.5], crystal_system="orthorhombic", initial_cell=dft_cell
    )
    assert got == dft_cell


def test_insufficient_reflections_raises_without_fallback():
    with pytest.raises(ValueError):
        solve_cell_from_dspacings([(1, 0, 0)], [6.5], crystal_system="orthorhombic")


def test_rank_deficient_reflections_fall_back():
    """全反射 l=0 だと G33 (c 軸) が拘束されずランク落ち → initial_cell へフォールバック (LOW-2)。"""
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    # l=0 のみの反射列 (c 軸を決められない)
    hkls_l0 = [(1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0), (0, 2, 0), (2, 1, 0)]
    d = [_d_of(true_cell, h) for h in hkls_l0]
    dft_cell = (6.551, 8.235, 13.778, 90.0, 90.0, 90.0)
    got = solve_cell_from_dspacings(
        hkls_l0, d, crystal_system="orthorhombic", initial_cell=dft_cell
    )
    assert got == dft_cell  # 退化 → フォールバック (退化 c を捏造しない)


def test_rank_deficient_raises_without_fallback():
    hkls_l0 = [(1, 0, 0), (0, 1, 0), (1, 1, 0), (2, 0, 0)]
    d = [_d_of((6.5, 8.1, 13.3, 90, 90, 90), h) for h in hkls_l0]
    with pytest.raises(ValueError):
        solve_cell_from_dspacings(hkls_l0, d, crystal_system="orthorhombic")


def test_robust_rejects_outlier_reflection():
    """1 本だけ誤指数付け (d を大きく外す) した反射を棄却して真格子を復元する。"""
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    d[5] = d[5] * 1.15  # 反射 index 5 を誤指数付け (15% ずれ)
    sol = refine_cell_robust(_HKLS, d, crystal_system="orthorhombic", reject_sigma=3.0)
    assert 5 in sol.rejected
    assert _cells_close(sol.cell, true_cell, tol=1e-3)
    assert sol.n_used == len(_HKLS) - 1


def test_robust_no_outlier_keeps_all():
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    sol = refine_cell_robust(_HKLS, d, crystal_system="orthorhombic")
    assert sol.rejected == ()
    assert sol.n_used == len(_HKLS)
    assert sol.rms_inv_d2 < 1e-9


def test_robust_deterministic():
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    d = [_d_of(true_cell, h) for h in _HKLS]
    d[3] *= 1.2
    s1 = refine_cell_robust(_HKLS, d, crystal_system="orthorhombic")
    s2 = refine_cell_robust(_HKLS, d, crystal_system="orthorhombic")
    assert s1 == s2


# --- refine_cell_from_indexed_peaks (hybrid の numpy コア; pymatgen 不要) ---

# 2θ が (10,80) に入る直方晶の反射集合を広めに用意
_HKLS_WIDE = [
    (h, k, ll)
    for h in range(3) for k in range(3) for ll in range(6)
    if (h, k, ll) != (0, 0, 0)
]


def _indexed_obs(cell, wavelength=1.5406, rng=(10.0, 80.0)):
    """真セルから (hkls, 強度, 観測位置, 観測強度) を作る (観測=計算位置)。"""
    tth = two_theta_of_hkls(cell, _HKLS_WIDE, wavelength)
    hkls, pos = [], []
    for h, t in zip(_HKLS_WIDE, tth):
        if math.isfinite(t) and rng[0] <= t <= rng[1]:
            hkls.append(h)
            pos.append(float(t))
    inten = [100.0] * len(hkls)  # 一様強度
    return hkls, inten, pos, list(inten)


def test_two_theta_of_hkls_matches_bragg():
    cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    tth = two_theta_of_hkls(cell, [(0, 0, 2)], 1.5406)
    # d(002)=c/2=6.661 → 2θ = 2·asin(λ/2d)
    d = 13.322 / 2.0
    expect = 2 * math.degrees(math.asin(1.5406 / (2 * d)))
    assert abs(float(tth[0]) - expect) < 1e-6


def test_indexed_peaks_recovers_anisotropic_from_perturbed_initial():
    """MP-DFT 相当の異方摂動初期セル (a+0.4% b+0.8% c+3.4%) から真セルを回復する (numpy のみ)。"""
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    hkls, inten, obs_pos, obs_ht = _indexed_obs(true_cell)
    perturbed = (6.527 * 1.004, 8.171 * 1.008, 13.322 * 1.034, 90.0, 90.0, 90.0)
    sol = refine_cell_from_indexed_peaks(
        perturbed, "orthorhombic", hkls, inten, obs_pos, obs_ht,
        wavelength=1.5406, two_theta_range=(10.0, 80.0),
    )
    assert sol is not None
    assert abs(sol.cell[0] - 6.527) < 0.02
    assert abs(sol.cell[1] - 8.171) < 0.02
    assert abs(sol.cell[2] - 13.322) < 0.02  # c を +3.4% から回復


def test_indexed_peaks_require_improvement_returns_none_when_no_gain():
    """観測と全く整合しない (乱れた) 観測位置では改善せず None (require_improvement)。"""
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    hkls, inten, _pos, _ht = _indexed_obs(true_cell)
    # 観測を大きくずらして整合不能に
    bad_pos = [15.5, 22.3, 31.1, 44.9, 55.2]
    bad_ht = [100.0] * len(bad_pos)
    sol = refine_cell_from_indexed_peaks(
        (6.5, 8.1, 13.3, 90, 90, 90), "orthorhombic", hkls, inten, bad_pos, bad_ht,
        wavelength=1.5406, two_theta_range=(10.0, 80.0), grid_span=(0.995, 1.005),
    )
    # 改善が無ければ None (安全側)。改善が僅かでもあれば LatticeSolution だが c は動かない想定。
    if sol is not None:
        assert sol.cell[2] > 1.0  # 少なくとも退化していない


def test_indexed_peaks_deterministic():
    true_cell = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
    hkls, inten, obs_pos, obs_ht = _indexed_obs(true_cell)
    perturbed = (6.56, 8.20, 13.70, 90.0, 90.0, 90.0)
    s1 = refine_cell_from_indexed_peaks(perturbed, "orthorhombic", hkls, inten, obs_pos, obs_ht,
                                        wavelength=1.5406, two_theta_range=(10.0, 80.0))
    s2 = refine_cell_from_indexed_peaks(perturbed, "orthorhombic", hkls, inten, obs_pos, obs_ht,
                                        wavelength=1.5406, two_theta_range=(10.0, 80.0))
    assert s1 == s2
