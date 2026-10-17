"""P0 §3.2.1-2 の CIF の検査 (合成の CIF だけ)。"""

from __future__ import annotations

from tsumugin.prereg_eval.hpub import atom_site_rows, cif_tags, cod_revision, free_coordinate_count, has_all_free_esds

_OPS = "\n".join(f"'{op}'" for op in (
    "x,y,z", "-y,x-y,z", "-x+y,-x,z", "-x,-y,z+1/2", "y,-x+y,z+1/2", "x-y,x,z+1/2",
    "-y,-x,z", "-x+y,y,z", "x,x-y,z", "y,x,z+1/2", "x-y,-y,z+1/2", "-x,-x+y,z+1/2"))


def _cif(o_row="O1 O 0.3333 0.6667 0.3820(3) 1", zn_row="Zn1 Zn 0.3333 0.6667 0 1", extra=""):
    return f"""#$Date: 2017-10-13 $
#$Revision: 201954 $
data_x
_cell_length_a 3.2498(1)
_cell_length_b 3.2498(1)
_cell_length_c 5.2066(2)
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_diffrn_ambient_temperature 295(2)
{extra}
_symmetry_space_group_name_H-M 'P 63 m c'
loop_
_symmetry_equiv_pos_as_xyz
{_OPS}
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
{zn_row}
{o_row}
"""


def test_raw_rows_keep_the_esd_brackets():
    rows = atom_site_rows(_cif())
    assert rows[1]["_atom_site_fract_z"] == "0.3820(3)" and rows[0]["_atom_site_label"] == "Zn1"


def test_tags_and_revision():
    assert cif_tags(_cif())["_diffrn_ambient_temperature"] == "295(2)"
    assert cod_revision(_cif()) == "201954"


def test_free_coordinates_exclude_symmetry_fixed_axes():
    # 2b (1/3, 2/3, z): 自由なのは z だけ。Zn の z は原点の選び方で決まる自由軸だが座標としては数える
    assert free_coordinate_count(_cif()) == 2


def test_esd_required_on_every_free_non_h_coordinate():
    assert not has_all_free_esds(_cif())  # Zn の z に esd が無い
    ok = _cif(zn_row="Zn1 Zn 0.3333 0.6667 0.0000(1) 1")
    assert has_all_free_esds(ok)
    zero = _cif(zn_row="Zn1 Zn 0.3333 0.6667 0.0000(0) 1")
    assert not has_all_free_esds(zero)  # 0 の esd は esd ではない


def test_hydrogen_is_ignored():
    h = _cif(extra="", o_row="O1 O 0.3333 0.6667 0.3820(3) 1\nH1 H 0.3333 0.6667 0.55 1",
             zn_row="Zn1 Zn 0.3333 0.6667 0.0000(1) 1")
    assert has_all_free_esds(h)


def test_without_symmetry_operators_nothing_can_be_decided():
    no_ops = _cif().replace(_OPS, "")
    assert free_coordinate_count(no_ops) is None and has_all_free_esds(no_ops) is False
