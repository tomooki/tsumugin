"""P0 §6.3: 出発モデルに入れる欠陥 (構造への純関数)。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.autorietveld.cif_normalize import Atom, Structure
from tsumugin.prereg_eval.defects import (
    displace_atom,
    drop_atom,
    lattice_matrix,
    scale_cell,
    shift_mixed_ratio,
    swap_site_elements,
    translate_along,
)


def _s(a=10.0, b=10.0, c=10.0, gamma=90.0):
    atoms = (
        Atom("Mg1", "Mg", 0.0, 0.0, 0.0, 0.9, 0.01),
        Atom("Fe1", "Fe", 0.0, 0.0, 0.0, 0.1, 0.01),
        Atom("O1", "O", 0.21, 0.33, 0.17, 1.0, 0.01),
        Atom("Si1", "Si", 0.4, 0.1, 0.25, 1.0, 0.01),
    )
    return Structure(a=a, b=b, c=c, alpha=90.0, beta=90.0, gamma=gamma, spacegroup_hm="P 1", it_number=1, atoms=atoms)


def test_swap_exchanges_the_elements_of_two_sites():
    out = swap_site_elements(_s(), "O1", "Si1")
    by = {a.label: a for a in out.atoms}
    assert by["O1"].type_symbol == "Si" and by["Si1"].type_symbol == "O"
    assert (by["O1"].x, by["O1"].y) == (0.21, 0.33)  # 位置は変えない


def test_drop_removes_one_atom():
    out = drop_atom(_s(), "Si1")
    assert [a.label for a in out.atoms] == ["Mg1", "Fe1", "O1"]
    assert [a.label for a in drop_atom(_s(), "Fe1").atoms] == ["Mg1", "O1", "Si1"]
    with pytest.raises(KeyError):
        drop_atom(_s(), "Nope")


def test_mixed_ratio_shift_keeps_the_sum():
    out = {a.label: a for a in shift_mixed_ratio(_s(), "Mg1", "Fe1", -0.2).atoms}
    assert out["Mg1"].occ == pytest.approx(0.7) and out["Fe1"].occ == pytest.approx(0.3)
    with pytest.raises(ValueError):
        shift_mixed_ratio(_s(), "Mg1", "Fe1", 0.2)  # Fe が負になる


def test_displacement_has_the_requested_cartesian_length():
    s = _s(a=8.0, b=9.0, c=10.0)
    out = displace_atom(s, "O1", 0.3, np.random.default_rng(1))
    before = next(a for a in s.atoms if a.label == "O1")
    after = next(a for a in out.atoms if a.label == "O1")
    d = (np.array([after.x, after.y, after.z]) - np.array([before.x, before.y, before.z])) @ lattice_matrix(s)
    assert float(np.linalg.norm(d)) == pytest.approx(0.3, rel=1e-9)


def test_lattice_matrix_of_hexagonal_cell():
    m = lattice_matrix(_s(a=3.0, b=3.0, c=5.0, gamma=120.0))
    assert np.linalg.norm(m[0]) == pytest.approx(3.0) and np.linalg.norm(m[1]) == pytest.approx(3.0)
    cosg = float(m[0] @ m[1]) / 9.0
    assert math.degrees(math.acos(cosg)) == pytest.approx(120.0)


def test_cell_scaling_respects_symmetry_equalities():
    out = scale_cell(_s(a=8.0, b=9.0, c=10.0), (1.01, 1.02, 1.03))
    assert (out.a, out.b, out.c) == pytest.approx((8.08, 9.18, 10.3))
    with pytest.raises(ValueError):
        scale_cell(_s(), (1.01, 1.02, 1.03))  # a = b = c の格子を別々に伸ばすと結晶系が変わる
    eq = scale_cell(_s(), (1.02, 1.02, 1.02))
    assert eq.a == eq.b == eq.c


def test_translation_moves_every_atom_along_the_axis():
    out = translate_along(_s(), "z", 0.05)
    for before, after in zip(_s().atoms, out.atoms):
        assert after.z == pytest.approx((before.z + 0.05) % 1.0) and after.x == before.x
