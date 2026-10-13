"""fit-then-judge P1-1B タスク 5: Uiso のまとめ方の規則 ((元素, 配位数) でまとめる)。"""

from __future__ import annotations

import pytest

from tsumugin.template.uiso import uiso_groups_from_cif

pytest.importorskip("pymatgen")


def _rocksalt_p1(tmp_path, *, drop: "str | None" = None) -> str:
    """岩塩 NaCl を P1 の慣用胞で (ラベル Na1..Na4 / Cl1..Cl4)。"""
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    na = [(0, 0, 0), (0, 0.5, 0.5), (0.5, 0, 0.5), (0.5, 0.5, 0)]
    cl = [(0.5, 0, 0), (0, 0.5, 0), (0, 0, 0.5), (0.5, 0.5, 0.5)]
    species, coords, labels = [], [], []
    for i, c in enumerate(na, 1):
        species.append("Na"), coords.append(c), labels.append(f"Na{i}")
    for i, c in enumerate(cl, 1):
        if f"Cl{i}" == drop:
            continue
        species.append("Cl"), coords.append(c), labels.append(f"Cl{i}")
    s = Structure(Lattice.cubic(5.64), species, coords, labels=labels)
    path = tmp_path / "nacl.cif"
    CifWriter(s).write_file(str(path))
    return str(path)


def test_atoms_of_one_element_with_the_same_coordination_share_a_uiso(tmp_path):
    g = uiso_groups_from_cif(_rocksalt_p1(tmp_path))
    assert g.status == "pass"
    assert set(map(tuple, g.groups)) == {("Na1", "Na2", "Na3", "Na4"), ("Cl1", "Cl2", "Cl3", "Cl4")}
    assert g.coordination["Na1"] == 6


def test_a_different_coordination_splits_the_group(tmp_path):
    g = uiso_groups_from_cif(_rocksalt_p1(tmp_path, drop="Cl4"))
    cn = g.coordination
    assert cn["Na1"] == 6 and cn["Na2"] == cn["Na3"] == cn["Na4"] == 4  # Cl4 の像 2 つが抜ける
    assert ("Na2", "Na3", "Na4") in g.groups
    assert not any("Na1" in grp for grp in g.groups)


def test_a_restriction_to_refined_labels_is_honoured(tmp_path):
    g = uiso_groups_from_cif(_rocksalt_p1(tmp_path), labels=("Na1", "Na2", "Cl1"))
    assert set(map(tuple, g.groups)) == {("Na1", "Na2")}


def test_an_unreadable_structure_is_unevaluated_not_individual_by_accident(tmp_path):
    bad = tmp_path / "bad.cif"
    bad.write_text("not a cif", encoding="utf-8")
    g = uiso_groups_from_cif(str(bad))
    assert g.status == "unevaluated" and g.groups == () and g.reason


def test_mixed_occupancy_sites_are_left_to_the_engine(tmp_path):
    """混合占有のサイトはまとめない (同じ位置の Uiso 等価は engine が混合占有の組として張る)。"""
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    mixed = {"Fe": 0.5, "Al": 0.5}
    s = Structure(
        Lattice.cubic(5.64),
        [mixed, mixed, "O", "O"],
        [(0, 0, 0), (0.5, 0.5, 0.5), (0.5, 0, 0), (0, 0.5, 0)],
        labels=["M1", "M2", "O1", "O2"],
    )
    path = tmp_path / "mixed.cif"
    CifWriter(s).write_file(str(path))
    g = uiso_groups_from_cif(str(path))
    assert g.status == "pass"
    assert not any(lab in ("M1", "M2") for grp in g.groups for lab in grp)


def test_labels_missing_from_the_cif_are_unevaluated(tmp_path):
    """GSAS のラベルが CIF に無い = 規則を適用できなかった (「組が無かった」と混同しない。M6)。"""
    g = uiso_groups_from_cif(_rocksalt_p1(tmp_path), labels=("Na1", "Q9"))
    assert g.status == "unevaluated" and "Q9" in g.reason


def test_co_located_rows_merged_by_pymatgen_still_count_as_present(tmp_path):
    """同じ位置の 2 行 (Fe1/Al1) は pymatgen が 1 サイトにまとめる — ラベルが「無い」とは言わない (N2)。"""
    lines = [
        "data_mix", "_cell_length_a 5.0", "_cell_length_b 5.0", "_cell_length_c 5.0",
        "_cell_angle_alpha 90", "_cell_angle_beta 90", "_cell_angle_gamma 90",
        "_symmetry_space_group_name_H-M 'P 1'", "loop_", "_symmetry_equiv_pos_as_xyz", "x,y,z",
        "loop_", "_atom_site_label", "_atom_site_type_symbol", "_atom_site_fract_x",
        "_atom_site_fract_y", "_atom_site_fract_z", "_atom_site_occupancy",
        "Fe1 Fe 0 0 0 0.5", "Al1 Al 0 0 0 0.5", "O1 O 0.5 0 0 1", "O2 O 0 0.5 0 1",
        "O3 O 0 0 0.5 1",
    ]
    cif = tmp_path / "mix.cif"
    cif.write_text(chr(10).join(lines) + chr(10), encoding="utf-8")
    g = uiso_groups_from_cif(str(cif), labels=("Fe1", "Al1", "O1", "O2", "O3"))
    assert g.status == "pass", g.reason
    assert ("O1", "O2", "O3") in g.groups


def test_an_atom_without_neighbours_makes_the_rule_unevaluated(tmp_path):
    """配位数を決められない原子があれば「組が無かった」と言わない (/code-review #243)。"""
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    s = Structure(Lattice.cubic(30.0), ["Na", "Cl"], [(0, 0, 0), (0.5, 0.5, 0.5)],
                  labels=["Na1", "Cl1"])
    path = tmp_path / "sparse.cif"
    CifWriter(s).write_file(str(path))
    g = uiso_groups_from_cif(str(path))
    assert g.status == "unevaluated" and "Na1" in g.reason
