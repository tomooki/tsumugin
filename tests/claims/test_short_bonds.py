"""P0 §1.4: 短結合の外れ b = 第一配位圏の結合のうち d_fit + 3σ_d < d_min のもの (検査器の表で)。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pymatgen")

from tsumugin.claims.chemistry import short_bonds  # noqa: E402

_CIF = """data_x
_cell_length_a 10.0
_cell_length_b 10.0
_cell_length_c 10.0
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_symmetry_equiv_pos_as_xyz
'x, y, z'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Na1 Na 0.0 0.0 0.0 1
Cl1 Cl 0.5 0.5 0.5 1
"""


def _result(cl_x, esd, *, occ=1.0):
    return SimpleNamespace(
        refined_cells={"P": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        atom_coords={"P": {"Na1": (0.0, 0.0, 0.0), "Cl1": (cl_x, 0.0, 0.0)}},
        atom_occupancy={"P": {"Na1": occ, "Cl1": occ}},
        atom_coord_esd={"P": {"Na1": (esd, esd, esd), "Cl1": (esd, esd, esd)}},
    )


@pytest.fixture
def cif(tmp_path):
    p = tmp_path / "p1.cif"
    p.write_text(_CIF, encoding="utf-8")
    return str(p)


def test_a_short_bond_is_counted_once(cif):
    # Na–Cl 1.5 Å、d_min = 0.7 × (1.8 + 1.0) = 1.96 Å
    n, detail = short_bonds("P", cif, _result(0.15, 0.0))
    assert n == 1 and detail["bonds"][0]["labels"] == ["Cl1", "Na1"]


def test_normal_distances_are_not_short(cif):
    assert short_bonds("P", cif, _result(0.30, 0.0))[0] == 0


def test_the_esd_widens_the_margin(cif):
    # σ 0.01 (0.1 Å/軸): σ_d ≈ 0.14 → 1.5 + 0.42 < 1.96 で短い。σ 0.02 → 1.5 + 0.85 > 1.96 で外れでない
    assert short_bonds("P", cif, _result(0.15, 0.01))[0] == 1
    assert short_bonds("P", cif, _result(0.15, 0.02))[0] == 0


def test_unrefined_axes_count_as_zero_esd(cif):
    r = _result(0.15, 0.0)
    r.atom_coord_esd = {"P": {"Na1": (None, None, None), "Cl1": (None, None, None)}}
    assert short_bonds("P", cif, r)[0] == 1


def test_split_site_pairs_are_not_contacts(cif):
    assert short_bonds("P", cif, _result(0.15, 0.0, occ=0.5))[0] == 0


def test_missing_values_are_unevaluated_not_zero(cif):
    r = _result(0.15, 0.0)
    r.atom_coords = {"P": {"Na1": (0.0, 0.0, 0.0)}}
    n, detail = short_bonds("P", cif, r)
    assert n is None and "reason" in detail


def test_symmetry_equivalent_bonds_count_once(tmp_path):
    # P-1: Na が対称中心にあり、Cl1 の像が 2 つ → 同じ結合が 2 本見えるが 1 本に数える
    p = tmp_path / "pm1.cif"
    centric = _CIF.replace("'P 1'", "'P -1'").replace("'x, y, z'", "'x, y, z'\n'-x, -y, -z'")
    p.write_text(centric, encoding="utf-8")
    assert short_bonds("P", str(p), _result(0.15, 0.0))[0] == 1


def test_non_finite_esd_is_treated_as_zero(cif):
    nan = float("nan")
    assert short_bonds("P", cif, _result(0.15, nan))[0] == 1
