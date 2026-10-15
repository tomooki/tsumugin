"""結合原子価の対ごとの表 (Brown の bvparm) — P1.5 の検査器の調整 (crystal-chemistry/2)。

表そのものはリポジトリに置かない。ここでは同じ書式の小さな表を書いて使う。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("pymatgen")

from tsumugin.claims import chemistry as ch  # noqa: E402
from tsumugin.claims.model import Check  # noqa: E402

_TABLE = """data_BOND_VALENCE_PARAMETERS_test
loop_
   _valence_param_atom_1
   _valence_param_atom_1_valence
   _valence_param_atom_2
   _valence_param_atom_2_valence
   _valence_param_Ro
   _valence_param_B
   _valence_param_ref_id
   _valence_param_details

Zn 2   O  -2    1.704    0.37     a   ?
Zn 2   O  -2    1.684    0.383    bs  ?
Ag 9   O  -2    1.805    0.37     b   ?
#### EOF ####
"""

_ZNO = """data_x
_cell_length_a 3.2498
_cell_length_b 3.2498
_cell_length_c 5.2066
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_symmetry_space_group_name_H-M 'P 63 m c'
loop_
_symmetry_equiv_pos_as_xyz
'x,y,z'
'-y,x-y,z'
'-x+y,-x,z'
'-x,-y,z+1/2'
'y,-x+y,z+1/2'
'x-y,x,z+1/2'
'-y,-x,z'
'-x+y,y,z'
'x,x-y,z'
'y,x,z+1/2'
'x-y,-y,z+1/2'
'-x,-x+y,z+1/2'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Zn1 Zn 0.333333333 0.666666667 0 1 0.01
O1 O 0.333333333 0.666666667 0.382 1 0.01
"""


@pytest.fixture
def table(tmp_path, monkeypatch):
    p = tmp_path / "bvparm.cif"
    p.write_text(_TABLE, encoding="utf-8")
    monkeypatch.setenv("TSUMUGIN_BVPARM", str(p))
    monkeypatch.setattr(ch, "BVPARM_SHA256", None)  # 小さな試験用の表は版の照合を外す
    return p


def _zno(tmp_path):
    p = tmp_path / "zno.cif"
    p.write_text(_ZNO, encoding="utf-8")
    return str(p), SimpleNamespace(
        refined_cells={"P": (3.2498, 3.2498, 5.2066, 90.0, 90.0, 120.0)},
        atom_coords={"P": {"Zn1": (1 / 3, 2 / 3, 0.0), "O1": (1 / 3, 2 / 3, 0.382)}},
        atom_occupancy={"P": {"Zn1": 1.0, "O1": 1.0}},
    )


def test_table_rows_are_read_first_match_wins(table):
    t = ch.load_bv_pair_table(table)
    assert t[("Zn", 2, "O", -2)] == (1.704, 0.37)  # 同じ対の 2 行目 (bs) ではなく最初の行
    assert t[("Ag", 9, "O", -2)] == (1.805, 0.37)


def test_wurtzite_passes_with_pair_parameters(table, tmp_path):
    path, result = _zno(tmp_path)
    out = ch.crystal_chemistry("P", path, result)
    outcome, witness = out["bvs_gii"]
    assert outcome == Check.PASS and witness.detail["gii"] < 0.1
    assert witness.detail["method"].startswith("pair-table")


def test_without_the_table_the_element_estimate_is_used_and_said(monkeypatch, tmp_path):
    monkeypatch.setenv("TSUMUGIN_BVPARM", str(tmp_path / "missing.cif"))
    path, result = _zno(tmp_path)
    _, witness = ch.crystal_chemistry("P", path, result)["bvs_gii"]
    assert witness.detail["method"] == "element-estimate"


def test_a_pair_missing_from_the_table_is_unevaluated_not_estimated(tmp_path, monkeypatch):
    p = tmp_path / "t.cif"
    p.write_text(_TABLE.replace("Zn 2   O  -2    1.704    0.37     a   ?\n", "").replace(
        "Zn 2   O  -2    1.684    0.383    bs  ?\n", ""), encoding="utf-8")
    monkeypatch.setenv("TSUMUGIN_BVPARM", str(p))
    monkeypatch.setattr(ch, "BVPARM_SHA256", None)
    path, result = _zno(tmp_path)
    outcome, witness = ch.crystal_chemistry("P", path, result)["bvs_gii"]
    assert outcome == Check.UNEVALUATED and "Zn" in witness.detail["reason"]


def test_a_table_with_the_wrong_hash_is_refused(table, monkeypatch, tmp_path):
    monkeypatch.setattr(ch, "BVPARM_SHA256", "0" * 64)
    path, result = _zno(tmp_path)
    outcome, witness = ch.crystal_chemistry("P", path, result)["bvs_gii"]
    assert outcome == Check.UNEVALUATED and "sha256" in witness.detail["reason"]


def test_version_was_bumped():
    assert ch.CHEMISTRY_VERSION == "crystal-chemistry/2"


def test_any_valence_rows_are_the_fallback(tmp_path, monkeypatch):
    p = tmp_path / "t9.cif"
    p.write_text(_TABLE.replace("Zn 2   O  -2    1.704", "Zn 9   O  -2    1.704").replace(
        "Zn 2   O  -2    1.684    0.383    bs  ?\n", ""), encoding="utf-8")
    monkeypatch.setenv("TSUMUGIN_BVPARM", str(p))
    monkeypatch.setattr(ch, "BVPARM_SHA256", None)
    path, result = _zno(tmp_path)
    outcome, witness = ch.crystal_chemistry("P", path, result)["bvs_gii"]
    assert outcome == Check.PASS and witness.detail["gii"] < 0.1
