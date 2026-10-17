"""P0 §1.3 / §3.1: 出発構造と参照構造の原子の対応・参照値の写し・独立性の照合 (合成の構造だけ)。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.cif_normalize import Atom, Structure
from tsumugin.prereg_eval.mapping import esd_of, map_atoms, reference_values, same_to_printed_precision

# P 2/m 相当の小さな対称操作 (恒等・反転) — 対称像を通した対応を試す
_OPS = ("x,y,z", "-x,-y,-z")


def _s(atoms, ops=_OPS, cell=(5.0, 6.0, 7.0)):
    return Structure(a=cell[0], b=cell[1], c=cell[2], alpha=90.0, beta=90.0, gamma=90.0,
                     spacegroup_hm="P -1", it_number=2, atoms=tuple(atoms), symops=ops)


START = _s([Atom("Ca1", "Ca", 0.10, 0.20, 0.30, 1.0, 0.01), Atom("O1", "O", 0.40, 0.10, 0.25, 1.0, 0.01)])


def test_atoms_map_through_symmetry_images_and_different_labels():
    # 参照は別のラベルで、O は反転の像 (-x,-y,-z) の位置に書かれている
    ref = _s([Atom("Ca", "Ca", 0.101, 0.199, 0.302, 1.0, 0.01), Atom("Ox", "O", -0.401, -0.098, -0.251, 1.0, 0.01)])
    m = map_atoms(START, ref)
    assert m.ok and m.pairs == {"Ca1": "Ca", "O1": "Ox"}


def test_mapping_fails_when_an_atom_has_no_partner_nearby():
    ref = _s([Atom("Ca", "Ca", 0.10, 0.20, 0.30, 1.0, 0.01), Atom("Ox", "O", 0.70, 0.60, 0.75, 1.0, 0.01)])
    m = map_atoms(START, ref)
    assert not m.ok and "O1" in m.unmatched


def test_mapping_is_one_to_one():
    start = _s([Atom("O1", "O", 0.40, 0.10, 0.25, 1.0, 0.01), Atom("O2", "O", 0.41, 0.11, 0.26, 1.0, 0.01)])
    ref = _s([Atom("Ox", "O", 0.405, 0.105, 0.255, 1.0, 0.01)])
    assert not map_atoms(start, ref).ok


def test_elements_must_match():
    ref = _s([Atom("Ca", "Ca", 0.10, 0.20, 0.30, 1.0, 0.01), Atom("F1", "F", 0.40, 0.10, 0.25, 1.0, 0.01)])
    assert not map_atoms(START, ref).ok


def test_reference_values_are_written_at_the_start_atoms_positions_with_their_esds():
    ref = _s([Atom("Ca", "Ca", 0.101, 0.199, 0.302, 1.0, 0.01), Atom("Ox", "O", -0.401, -0.098, -0.251, 1.0, 0.01)])
    esd = {"Ca": (0.001, 0.002, 0.003), "Ox": (0.004, 0.005, 0.006)}
    vals = {v.key: v for v in reference_values(START, ref, map_atoms(START, ref), esd, phase="P")}
    o = vals["coord:P.O1"]
    assert o.value == pytest.approx((0.401, 0.098, 0.251))  # 反転の像を出発の非対称単位に写した
    assert o.sigma == pytest.approx((0.004, 0.005, 0.006))  # 反転は軸の esd を変えない
    assert vals["coord:P.Ca1"].value == pytest.approx((0.101, 0.199, 0.302))


def test_axis_permuting_operations_permute_the_esds():
    ops = ("x,y,z", "y,x,z")
    start = _s([Atom("O1", "O", 0.40, 0.10, 0.25, 1.0, 0.01)], ops=ops, cell=(5.0, 5.0, 7.0))
    ref = _s([Atom("Ox", "O", 0.10, 0.40, 0.25, 1.0, 0.01)], ops=ops, cell=(5.0, 5.0, 7.0))
    vals = reference_values(start, ref, map_atoms(start, ref), {"Ox": (0.001, 0.009, 0.003)}, phase="P")
    assert vals[0].sigma == pytest.approx((0.009, 0.001, 0.003))


def test_independence_is_lost_when_every_value_matches_to_printed_precision():
    start_raw = {"coord:P.O1": ("0.4000", "0.1000", "0.2500")}
    assert same_to_printed_precision(start_raw, {"coord:P.O1": (0.40004, 0.09996, 0.25001)})
    assert not same_to_printed_precision(start_raw, {"coord:P.O1": (0.4003, 0.1000, 0.2500)})


def test_nothing_to_compare_is_not_evidence_of_copying():
    assert not same_to_printed_precision({}, {"coord:P.O1": (0.4, 0.1, 0.25)})


@pytest.mark.parametrize("token, esd", [("0.1234(5)", 0.0005), ("0.12(12)", 0.12), ("1.5(3)", 0.3),
                                        ("0.25", None), ("0.1234(0)", None), ("12(2)", 2.0), ("?", None)])
def test_esd_is_read_from_the_parenthesised_digits(token, esd):
    assert esd_of(token) == (None if esd is None else pytest.approx(esd))


def test_charged_type_symbols_match_their_element():
    ref = _s([Atom("Ca", "Ca2+", 0.10, 0.20, 0.30, 1.0, 0.01), Atom("Ox", "O2-", 0.40, 0.10, 0.25, 1.0, 0.01)])
    assert map_atoms(START, ref).ok
