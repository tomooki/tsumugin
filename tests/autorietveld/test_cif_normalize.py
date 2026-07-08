"""autorietveld.cif_normalize (CIF 正規化) の決定論テスト。"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.cif_normalize import (
    normalize_cif_for_gsas,
    read_structure_cif,
    write_gsas_cif,
)

# Z-Rietveld 風: 複数 data ブロック + esd 付き値 + B_iso 列。
_CHECKCIF = """data_global
_journal_name_full 'Some Journal'

data_single_phase
_cell_length_a 6.95976(2)
_cell_length_b 7.29213(3)
_cell_length_c 12.85438(3)
_cell_angle_alpha 90
_cell_angle_beta 119.6716(2)
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 21/c'
_symmetry_Int_Tables_number 14

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_occupancy
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_B_iso_or_equiv
Cu Cu2+ 1 0 0.5 -0.5 0.562(12)
Na1 Na 0.9999902 -0.80567(10) 0.5179(2) -0.75859(6) 2.90(2)
O2A O 0.25 0(3) 1(3) -0.2(19) 2.50137
"""


def test_read_structure_strips_esd_and_multiblock():
    st = read_structure_cif_from_text(_CHECKCIF)
    assert st.a == pytest.approx(6.95976)
    assert st.beta == pytest.approx(119.6716)
    assert st.spacegroup_hm == "P 21/c"
    assert st.it_number == 14
    assert len(st.atoms) == 3
    na = next(a for a in st.atoms if a.label == "Na1")
    # B_iso 2.90 → U = B/(8π²)
    assert na.uiso == pytest.approx(2.90 / (8 * math.pi**2), rel=1e-4)
    assert na.occ == pytest.approx(0.9999902)


def test_write_gsas_cif_single_block_and_uiso(tmp_path):
    st = read_structure_cif_from_text(_CHECKCIF)
    out = write_gsas_cif(st, tmp_path / "clean.cif", phase_name="NaCuHCF")
    text = out.read_text(encoding="utf-8")
    assert text.count("data_") == 1  # 単一ブロック
    assert 'data_NaCuHCF' in text
    assert "_atom_site_U_iso_or_equiv" in text
    assert "(" not in text  # esd 除去済
    # 往復で原子数保存。
    st2 = read_structure_cif(out)
    assert len(st2.atoms) == 3


def test_read_structure_keeps_atoms_across_blank_rows():
    # 一部 CIF ライタはサイト行の間に空行を挿む。空行で loop を打ち切って原子を落とさないこと。
    cif = (
        "_cell_length_a 5\n_cell_length_b 5\n_cell_length_c 5\n"
        "_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 90\n"
        "_symmetry_space_group_name_H-M 'P 1'\n"
        "loop_\n_atom_site_label\n_atom_site_type_symbol\n"
        "_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\n"
        "O1 O 0.0 0.0 0.0\n\nO2 O 0.5 0.5 0.5\n"
    )
    st = read_structure_cif_from_text(cif)
    assert {a.label for a in st.atoms} == {"O1", "O2"}  # 空行後の O2 も保持


def test_normalize_roundtrip(tmp_path):
    src = tmp_path / "src.cif"
    src.write_text(_CHECKCIF, encoding="utf-8")
    out = normalize_cif_for_gsas(src, tmp_path / "out.cif", phase_name="p")
    st = read_structure_cif(out)
    assert st.spacegroup_hm == "P 21/c"


def read_structure_cif_from_text(text):
    import tempfile
    from pathlib import Path

    p = Path(tempfile.mktemp(suffix=".cif"))
    p.write_text(text, encoding="utf-8")
    return read_structure_cif(p)
