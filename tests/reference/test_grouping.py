"""M6 TASK-0114 Phase E: 組成グルーピングの失敗テスト (Red)。

対象実装: ``src/tsumugin/reference/grouping.py`` (未実装)。
`group_by_composition(matches)`: 同一組成 (reduced formula) の候補相をまとめ、各グループの
最良スコア相を代表に、グループを代表スコア降順で返す (Dara の compositional grouping)。
"""

from __future__ import annotations

from tsumugin.reference.grouping import PhaseMatchGroup, group_by_composition
from tsumugin.reference.model import PhaseMatch, ReferencePhase
from tsumugin.search.peaks import Peak


def _match(phase_id, formula, score, *, sg=None):
    ref = ReferencePhase(
        phase_id=phase_id,
        formula=formula,
        element_system=("C", "Ca", "O"),
        peaks=(Peak(20.0, 1.0),),
        spacegroup=sg,
    )
    return PhaseMatch(reference=ref, score=score, matched_observed=(0,), extra_calculated=())


def test_groups_same_formula_together():
    matches = (
        _match("mp-1", "CaCO3", 0.5, sg="R-3c"),      # calcite
        _match("mp-2", "CaCO3", 0.3, sg="Pnma"),      # aragonite
        _match("mp-3", "CaO", 0.2, sg="Fm-3m"),
    )
    groups = group_by_composition(matches)
    assert all(isinstance(g, PhaseMatchGroup) for g in groups)
    caco3 = next(g for g in groups if g.formula == "CaCO3")
    assert len(caco3.members) == 2
    # 代表はグループ内最良スコア (calcite 0.5)
    assert caco3.representative.reference.phase_id == "mp-1"


def test_groups_sorted_by_representative_score():
    matches = (
        _match("mp-cao", "CaO", 0.2),
        _match("mp-caco3", "CaCO3", 0.6),
    )
    groups = group_by_composition(matches)
    assert [g.formula for g in groups] == ["CaCO3", "CaO"]  # 代表スコア降順


def test_members_sorted_by_score_desc():
    matches = (
        _match("mp-a", "CaCO3", 0.2, sg="Pnma"),
        _match("mp-b", "CaCO3", 0.5, sg="R-3c"),
        _match("mp-c", "CaCO3", 0.4, sg="P-1"),
    )
    groups = group_by_composition(matches)
    scores = [m.score for m in groups[0].members]
    assert scores == sorted(scores, reverse=True)


def test_empty_matches():
    assert group_by_composition(()) == ()


def test_single_phase_group():
    groups = group_by_composition((_match("mp-1", "PbSO4", 0.7),))
    assert len(groups) == 1
    assert groups[0].representative.reference.formula == "PbSO4"
    assert len(groups[0].members) == 1
