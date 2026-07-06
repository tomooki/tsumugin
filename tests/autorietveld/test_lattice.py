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
    refine_cell_robust,
    solve_cell_from_dspacings,
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
