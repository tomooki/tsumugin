"""autorietveld.deuterium (D₂O 幾何配置) の決定論テスト。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.autorietveld.deuterium import frac_to_cart_matrix, place_d2o

# 立方 a=10 → cart = 10·frac の単純セル。水 O は部分占有 (共有サイト水を模す)。
_CIF = """_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'

loop_
_atom_site_label
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_type_symbol
_atom_site_U_iso_or_equiv
Cu 0.0 0.0 0.0 1.0 Cu 0.01
Ow 0.5 0.5 0.5 0.30 O 0.04
"""


def test_frac_to_cart_orthogonal_cell_is_diagonal():
    m = frac_to_cart_matrix(10.0, 12.0, 14.0, 90.0, 90.0, 90.0)
    assert np.allclose(m, np.diag([10.0, 12.0, 14.0]), atol=1e-9)


def test_place_d2o_adds_two_deuteriums_per_water(tmp_path):
    src = tmp_path / "m.cif"
    src.write_text(_CIF, encoding="utf-8")
    out, sites = place_d2o(src, ["Ow"], tmp_path / "m_d.cif")
    assert len(sites) == 2
    assert {s.label for s in sites} == {"DOw1", "DOw2"}
    assert all(s.parent_label == "Ow" for s in sites)
    # 占有率は親 O (0.30) に等値。
    assert all(s.occupancy == pytest.approx(0.30) for s in sites)


def test_place_d2o_geometry_distance_and_angle(tmp_path):
    src = tmp_path / "m.cif"
    src.write_text(_CIF, encoding="utf-8")
    _out, sites = place_d2o(
        src, ["Ow"], tmp_path / "m_d.cif", od_distance=0.96, dod_angle=104.5
    )
    mat = frac_to_cart_matrix(10, 10, 10, 90, 90, 90)
    o_cart = mat @ np.array([0.5, 0.5, 0.5])
    d_carts = [mat @ np.array(s.frac) for s in sites]
    # O–D 距離 ≈ 0.96 Å。
    for dc in d_carts:
        assert np.linalg.norm(dc - o_cart) == pytest.approx(0.96, abs=1e-4)
    # D–O–D 角 ≈ 104.5°。
    v1 = d_carts[0] - o_cart
    v2 = d_carts[1] - o_cart
    cos_ang = float(v1 @ v2 / (np.linalg.norm(v1) * np.linalg.norm(v2)))
    assert math.degrees(math.acos(cos_ang)) == pytest.approx(104.5, abs=1e-2)


def test_place_d2o_writes_type_D_and_preserves_atoms(tmp_path):
    src = tmp_path / "m.cif"
    src.write_text(_CIF, encoding="utf-8")
    out, _sites = place_d2o(src, ["Ow"], tmp_path / "m_d.cif")
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    struct = read_structure_cif(out)  # 出力は GSAS 向け正規化 CIF (再読込可)
    labels = {a.label for a in struct.atoms}
    assert {"Cu", "Ow", "DOw1", "DOw2"} <= labels  # 既存原子 + D を保持
    d_atoms = [a for a in struct.atoms if a.label.startswith("DOw")]
    assert len(d_atoms) == 2
    for a in d_atoms:
        assert a.type_symbol == "D"
        assert a.occ == pytest.approx(0.30)


def test_place_d2o_element_and_occupancy_scale(tmp_path):
    src = tmp_path / "m.cif"
    src.write_text(_CIF, encoding="utf-8")
    # H 同位体 + 占有率 0.5 倍 (H/D 混合の H 側)。
    out, sites = place_d2o(src, ["Ow"], tmp_path / "m_h.cif", element="H", occupancy_scale=0.4)
    assert {s.label for s in sites} == {"HOw1", "HOw2"}
    assert all(s.occupancy == pytest.approx(0.30 * 0.4) for s in sites)
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    st = read_structure_cif(out)
    h = [a for a in st.atoms if a.label.startswith("HOw")]
    assert all(a.type_symbol == "H" for a in h)


def test_place_d2o_unknown_label_raises(tmp_path):
    src = tmp_path / "m.cif"
    src.write_text(_CIF, encoding="utf-8")
    with pytest.raises(ValueError, match="見つかりません"):
        place_d2o(src, ["NoSuch"], tmp_path / "out.cif")
