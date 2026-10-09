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
