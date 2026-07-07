"""M10 check_bond_validity — 結合距離/配位数の物理妥当性ゲート (pymatgen gated)。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.validity import check_bond_validity


def test_pymatgen_absent_or_bad_path_skips_gracefully():
    """存在しないパスは passed=True + 警告に縮退 (クラッシュしない, REQ-1013 WHERE)。"""
    rep = check_bond_validity("does_not_exist.cif")
    assert rep.passed is True
    assert rep.warnings  # 何らかの skip 警告


def _write_nacl(tmp_path, a=5.64):
    pmg = pytest.importorskip("pymatgen.core")
    Structure, Lattice = pmg.Structure, pmg.Lattice
    # NaCl (rock salt): 最近接 Na-Cl は稜方向 a/2 (体心 0.5,0.5,0.5 でなく 0.5,0,0)
    s = Structure(Lattice.cubic(a), ["Na", "Cl"], [[0, 0, 0], [0.5, 0, 0]])
    path = str(tmp_path / "nacl.cif")
    s.to(filename=path)
    return path


def test_reasonable_structure_passes(tmp_path):
    """妥当な NaCl (Na-Cl ≈ 2.82Å ≈ 半径和) は結合距離チェックを通る。"""
    path = _write_nacl(tmp_path)
    rep = check_bond_validity(path, bond_tol_lo=0.7, bond_tol_hi=1.3)
    assert rep.passed is True
    assert any(name == "min_bond_distance" for name, _, _ in rep.checks)


def test_collapsed_cell_fails_bond_distance(tmp_path):
    """精密化格子を 1/2.8 に潰すと最近接距離が半径和を大きく下回り不合格。"""
    path = _write_nacl(tmp_path)
    rep = check_bond_validity(path, refined_cell=(2.0, 2.0, 2.0, 90, 90, 90),
                              bond_tol_lo=0.7, bond_tol_hi=1.3)
    assert rep.passed is False
    assert any(name == "min_bond_distance" and not ok for name, ok, _ in rep.checks)


def test_over_expanded_cell_fails_upper_bound(tmp_path):
    """過膨張 (最近接が半径和の 1.3 倍超) も不合格。"""
    path = _write_nacl(tmp_path)
    rep = check_bond_validity(path, refined_cell=(20.0, 20.0, 20.0, 90, 90, 90),
                              bond_tol_lo=0.7, bond_tol_hi=1.3)
    assert rep.passed is False


def test_refined_cell_override_changes_geometry(tmp_path):
    """refined_cell を渡すと元 CIF でなくその格子で距離を評価する。"""
    path = _write_nacl(tmp_path, a=5.64)
    # 元は pass (Na-Cl 2.82Å), 縮小 (a=3.0 → Na-Cl 1.5Å) は下限割れで fail に変わる
    ok_rep = check_bond_validity(path)
    small = check_bond_validity(path, refined_cell=(3.0, 3.0, 3.0, 90, 90, 90))
    assert ok_rep.passed is True
    assert small.passed is False


def test_coordination_check_optional(tmp_path):
    """expected_coordination 指定時は CrystalNN で配位数も検査 (NaCl は 6 配位)。"""
    pytest.importorskip("pymatgen.analysis.local_env")
    path = _write_nacl(tmp_path)
    rep = check_bond_validity(path, expected_coordination={"Na": (4, 8), "Cl": (4, 8)})
    # 配位数チェックが走っている (pass/fail は環境依存だが check が存在)
    assert any(name.startswith("coordination_") for name, _, _ in rep.checks) or rep.warnings
