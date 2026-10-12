"""fit-then-judge P1a タスク 2: 等値拘束の組の合併と検査 (`autorietveld.constraint_groups`) — 純関数。

GSAS-II の等値拘束 (`add_EquivConstr`) は**同じ変数を 2 つの組に入れると**一般拘束へ変換し直す
(GSASIImapvars)。混合占有の Uiso 等価と新設の `uiso_equiv_groups` が同じ原子を含むと二重に張る
ことになるので、推移的に合併して 1 回だけ張る。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.constraint_groups import (
    merge_equiv_groups,
    partially_released_groups,
    unknown_labels,
)


def test_singletons_are_dropped_and_order_is_first_appearance():
    assert merge_equiv_groups((("A",), ("B", "C"))) == (("B", "C"),)


def test_overlapping_groups_are_merged_transitively():
    mixed = (("Fe1", "Al1"), ("Al2", "Fe2"))
    uiso = (("Fe1", "Al2"),)
    assert merge_equiv_groups(mixed, uiso) == (("Fe1", "Al1", "Al2", "Fe2"),)


def test_chain_merges_into_one_group():
    assert merge_equiv_groups((("A", "B"),), (("B", "C"),), (("D", "C"),)) == (
        ("A", "B", "C", "D"),
    )


def test_disjoint_groups_stay_separate_in_order():
    assert merge_equiv_groups((("O1", "O2"),), (("Y1", "Y2"),)) == (
        ("O1", "O2"),
        ("Y1", "Y2"),
    )


def test_duplicate_labels_inside_a_group_are_collapsed():
    assert merge_equiv_groups((("A", "A", "B"),)) == (("A", "B"),)


def test_unknown_labels_are_reported_in_order():
    assert unknown_labels((("O1", "Ox"), ("Y9",)), {"O1", "Y1"}) == ["Ox", "Y9"]


def test_partially_released_group_is_reported():
    groups = (("Fe1", "Al1", "Al2"), ("O1", "O2"))
    assert partially_released_groups(groups, {"Fe1", "O1", "O2"}) == [("Fe1", "Al1", "Al2")]


@pytest.mark.parametrize("released", [set(), {"Fe1", "Al1", "Al2", "O1", "O2"}])
def test_uniform_groups_pass(released):
    groups = (("Fe1", "Al1", "Al2"), ("O1", "O2"))
    assert partially_released_groups(groups, released) == []


# ---------------- 極性方向の原点固定 (P1a タスク 3) ----------------
#
# 極性空間群では、極性方向へ全原子を一斉に並進しても強度が変わらない (原点が決まらない)。
# GSAS-II は警告するだけで固定しない (GSASIIspc の SGPolax)。その方向の座標が自由な**すべての**
# 原子を精密化するときだけ、最も散乱の強い原子でその方向の座標の一次結合を 1 本固定する。
# 1 原子でも凍結されていれば原点はそれで決まっているので、固定を足すと実在の自由度を消す。

from tsumugin.autorietveld.constraint_groups import AtomSite, polar_origin_constraints  # noqa: E402

_GENERAL = ((1, 2, 3), (1.0, 1.0, 1.0))
_ZONLY = ((0, 0, 1), (0.0, 0.0, 1.0))
_XXX = ((1, 1, 1), (1.0, 1.0, 1.0))


def _site(label, z, sym, refined=True):
    return AtomSite(label=label, z=z, xid=sym[0], xcoef=sym[1], refined=refined)


def test_centrosymmetric_or_nonpolar_needs_no_origin_fix():
    assert polar_origin_constraints("", [_site("Zn1", 30, _ZONLY)]) == []


def test_single_polar_axis_holds_the_heaviest_atom():
    sites = [_site("O1", 8, _ZONLY), _site("Zn1", 30, _ZONLY)]
    assert polar_origin_constraints("z", sites) == [("Zn1", (("z", 1.0),))]


def test_origin_already_pinned_by_a_frozen_atom_adds_nothing():
    sites = [_site("O1", 8, _ZONLY, refined=False), _site("Zn1", 30, _ZONLY)]
    assert polar_origin_constraints("z", sites) == []


def test_atoms_without_freedom_along_the_axis_are_ignored():
    fixed = ((0, 0, 0), (0.0, 0.0, 0.0))
    sites = [_site("Ba1", 56, fixed, refined=False), _site("O1", 8, _ZONLY)]
    assert polar_origin_constraints("z", sites) == [("O1", (("z", 1.0),))]


def test_111_on_a_threefold_axis_holds_the_independent_x():
    """(x,x,x) は GSAS が y,z を x に従属させているので、独立変数 x の hold になる。"""
    sites = [_site("Bi1", 83, _XXX), _site("O1", 8, _GENERAL)]
    assert polar_origin_constraints("111", sites) == [("Bi1", (("x", 3.0),))]


def test_111_on_a_general_atom_fixes_the_sum_of_the_three_shifts():
    sites = [_site("Bi1", 83, _GENERAL)]
    assert polar_origin_constraints("111", sites) == [
        ("Bi1", (("x", 1.0), ("y", 1.0), ("z", 1.0)))
    ]


def test_p1_fixes_three_axes():
    sites = [_site("O1", 8, _GENERAL), _site("Fe1", 26, _GENERAL)]
    assert polar_origin_constraints("xyz", sites) == [
        ("Fe1", (("x", 1.0),)),
        ("Fe1", (("y", 1.0),)),
        ("Fe1", (("z", 1.0),)),
    ]


def test_two_polar_axes_coupled_on_one_variable_are_refused():
    """x と y が同じ独立変数に結ばれた原子しか無いと、2 本の固定が 1 変数に重なる (特異)。"""
    xx0 = ((1, 1, 0), (1.0, 1.0, 0.0))
    with pytest.raises(ValueError):
        polar_origin_constraints("x y", [_site("A1", 20, xx0)])


def test_unknown_polar_axis_code_is_refused():
    with pytest.raises(ValueError):
        polar_origin_constraints("q", [_site("A1", 20, _GENERAL)])
