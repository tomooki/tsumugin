"""autorietveld.cif_edit (原子レベル CIF 編集) の TDD テスト (M8-③ MEM model-fix Phase A)。

決定論・純テキスト (GSAS 非依存)。add/move/set_occupancy/set_uiso/remove を Structure 変換で
適用し、元 CIF 不変 (P2) + fail-loud + ビット同一を検証する。
"""
from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError

import pytest

from tsumugin.autorietveld.cif_edit import (
    AtomEdit,
    apply_atom_edits,
    apply_edits_to_structure,
)
from tsumugin.autorietveld.cif_normalize import read_structure_cif

_CIF = """data_test
_cell_length_a 6.95000
_cell_length_b 7.29000
_cell_length_c 12.84000
_cell_angle_alpha 90.0
_cell_angle_beta 119.66
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M "P 1"
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 _atom_site_U_iso_or_equiv
Cu1 Cu 0.00000 0.50000 0.50000 1.0000 0.01800
Fe1 Fe 0.50000 0.00000 0.50000 1.0000 0.00400
"""


def _cif(tmp_path):
    p = tmp_path / "start.cif"
    p.write_text(_CIF, encoding="utf-8")
    return p


def _labels(struct):
    return [a.label for a in struct.atoms]


# ---------------------------------------------------------------------------
# (A) AtomEdit dataclass
# ---------------------------------------------------------------------------


def test_atom_edit_frozen():
    assert dataclasses.is_dataclass(AtomEdit)
    e = AtomEdit(op="add", label="O1", element="O", frac=(0.1, 0.2, 0.3), occ=0.3)
    with pytest.raises(FrozenInstanceError):
        e.occ = 0.5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (B) add
# ---------------------------------------------------------------------------


def test_add_atom(tmp_path):
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [
        AtomEdit(op="add", label="Ow", element="O", frac=(0.25, 0.25, 0.25),
                 occ=0.3, uiso=0.05)
    ], str(out))
    s = read_structure_cif(out)
    assert "Ow" in _labels(s)
    ow = next(a for a in s.atoms if a.label == "Ow")
    assert ow.type_symbol == "O"
    assert (round(ow.x, 3), round(ow.y, 3), round(ow.z, 3)) == (0.25, 0.25, 0.25)
    assert ow.occ == pytest.approx(0.3)
    assert ow.uiso == pytest.approx(0.05)


def test_add_defaults_occ_uiso(tmp_path):
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [
        AtomEdit(op="add", label="X1", element="Na", frac=(0.1, 0.1, 0.1))
    ], str(out))
    s = read_structure_cif(out)
    x = next(a for a in s.atoms if a.label == "X1")
    assert x.occ == pytest.approx(1.0)
    assert x.uiso == pytest.approx(0.025)


def test_add_duplicate_label_raises(tmp_path):
    with pytest.raises(ValueError):
        apply_atom_edits(str(_cif(tmp_path)), [
            AtomEdit(op="add", label="Cu1", element="Cu", frac=(0.0, 0.0, 0.0))
        ], str(tmp_path / "o.cif"))


def test_add_missing_element_or_frac_raises(tmp_path):
    with pytest.raises(ValueError):
        apply_atom_edits(str(_cif(tmp_path)), [
            AtomEdit(op="add", label="Q", frac=(0.1, 0.1, 0.1))
        ], str(tmp_path / "o.cif"))
    with pytest.raises(ValueError):
        apply_atom_edits(str(_cif(tmp_path)), [
            AtomEdit(op="add", label="Q", element="O")
        ], str(tmp_path / "o2.cif"))


# ---------------------------------------------------------------------------
# (C) move / set_occupancy / set_uiso / remove
# ---------------------------------------------------------------------------


def test_move_atom(tmp_path):
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [
        AtomEdit(op="move", label="Fe1", frac=(0.4, 0.1, 0.4))
    ], str(out))
    s = read_structure_cif(out)
    fe = next(a for a in s.atoms if a.label == "Fe1")
    assert (round(fe.x, 3), round(fe.y, 3), round(fe.z, 3)) == (0.4, 0.1, 0.4)
    # Cu1 は不変
    cu = next(a for a in s.atoms if a.label == "Cu1")
    assert cu.x == pytest.approx(0.0) and cu.z == pytest.approx(0.5)


def test_set_occupancy(tmp_path):
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [
        AtomEdit(op="set_occupancy", label="Cu1", occ=0.75)
    ], str(out))
    s = read_structure_cif(out)
    assert next(a for a in s.atoms if a.label == "Cu1").occ == pytest.approx(0.75)


def test_set_uiso(tmp_path):
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [
        AtomEdit(op="set_uiso", label="Fe1", uiso=0.02)
    ], str(out))
    s = read_structure_cif(out)
    assert next(a for a in s.atoms if a.label == "Fe1").uiso == pytest.approx(0.02)


def test_remove_atom(tmp_path):
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [AtomEdit(op="remove", label="Fe1")], str(out))
    s = read_structure_cif(out)
    assert "Fe1" not in _labels(s)
    assert "Cu1" in _labels(s)


@pytest.mark.parametrize("op,kw", [
    ("move", {"frac": (0.1, 0.1, 0.1)}),
    ("set_occupancy", {"occ": 0.5}),
    ("set_uiso", {"uiso": 0.02}),
    ("remove", {}),
])
def test_edit_missing_label_raises(tmp_path, op, kw):
    with pytest.raises(KeyError):
        apply_atom_edits(str(_cif(tmp_path)), [AtomEdit(op=op, label="ZZ", **kw)],
                         str(tmp_path / "o.cif"))


def test_unknown_op_raises(tmp_path):
    with pytest.raises(ValueError):
        apply_atom_edits(str(_cif(tmp_path)), [AtomEdit(op="frobnicate", label="Cu1")],
                         str(tmp_path / "o.cif"))


# ---------------------------------------------------------------------------
# (D) order / P2 non-destructive / determinism
# ---------------------------------------------------------------------------


def test_edits_applied_in_order(tmp_path):
    """add してから同じ原子を move できる (順次適用)。"""
    out = tmp_path / "out.cif"
    apply_atom_edits(str(_cif(tmp_path)), [
        AtomEdit(op="add", label="Ow", element="O", frac=(0.1, 0.1, 0.1)),
        AtomEdit(op="move", label="Ow", frac=(0.2, 0.2, 0.2)),
    ], str(out))
    s = read_structure_cif(out)
    ow = next(a for a in s.atoms if a.label == "Ow")
    assert (round(ow.x, 3), round(ow.y, 3), round(ow.z, 3)) == (0.2, 0.2, 0.2)


def test_original_cif_unchanged(tmp_path):
    src = _cif(tmp_path)
    before = src.read_text(encoding="utf-8")
    apply_atom_edits(str(src), [AtomEdit(op="remove", label="Fe1")], str(tmp_path / "o.cif"))
    assert src.read_text(encoding="utf-8") == before


def test_deterministic(tmp_path):
    edits = [AtomEdit(op="add", label="Ow", element="O", frac=(0.25, 0.25, 0.25), occ=0.3)]
    a = tmp_path / "a.cif"
    b = tmp_path / "b.cif"
    apply_atom_edits(str(_cif(tmp_path)), edits, str(a))
    apply_atom_edits(str(_cif(tmp_path)), edits, str(b))
    assert a.read_text(encoding="utf-8") == b.read_text(encoding="utf-8")


def test_apply_edits_to_structure_pure(tmp_path):
    """Structure 変換は純関数 (元 Structure を破壊しない)。"""
    s0 = read_structure_cif(_cif(tmp_path))
    s1 = apply_edits_to_structure(s0, [AtomEdit(op="remove", label="Fe1")])
    assert len(s0.atoms) == 2 and len(s1.atoms) == 1
