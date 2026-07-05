"""M6 TASK-0100 相ライブラリ data model の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/model.py`` (未実装)。
`ReferencePhase` / `PhaseMatch` / `PhaseIdentification` の契約・不変性・値等価を検証する。
書式は `tests/test_matcher.py` を範とする (frozen dataclass の値等価 / モジュールヘルパ)。

本タスクは numpy 非依存で完結する (data model のみ)。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.search.peaks import Peak

# 未実装のため collection 時に import が失敗し全テストがエラー(=Red)になる想定。
from tsumugin.reference.model import (
    PhaseIdentification,
    PhaseMatch,
    ReferencePhase,
)
from tsumugin.search.matcher import UnmatchedPeakReport


def _ref(phase_id: str = "mp-1", *, formula: str = "LiFePO4", ehull: float | None = 0.0) -> ReferencePhase:
    return ReferencePhase(
        phase_id=phase_id,
        formula=formula,
        element_system=("Fe", "Li", "O", "P"),
        peaks=(Peak(position=20.0, height=1.0), Peak(position=30.0, height=0.5)),
        spacegroup="Pnma",
        energy_above_hull=ehull,
    )


def test_reference_phase_is_frozen():
    ref = _ref()
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.formula = "X"  # type: ignore[misc]


def test_reference_phase_value_equality():
    assert _ref() == _ref()
    assert _ref("mp-1") != _ref("mp-2")


def test_reference_phase_optional_fields_default_none():
    ref = ReferencePhase(
        phase_id="mp-9",
        formula="Fe2O3",
        element_system=("Fe", "O"),
        peaks=(),
    )
    assert ref.spacegroup is None
    assert ref.energy_above_hull is None  # MP未登録/不明 → hull フィルタで保持される契約


def test_phase_match_holds_reference_and_score():
    ref = _ref()
    m = PhaseMatch(
        reference=ref,
        score=0.75,
        matched_observed=(0, 2),
        extra_calculated=(45.0,),
    )
    assert m.reference is ref
    assert m.score == pytest.approx(0.75)
    assert m.matched_observed == (0, 2)


def test_phase_identification_holds_matches_and_report():
    ref = _ref()
    m = PhaseMatch(reference=ref, score=0.9, matched_observed=(0,), extra_calculated=())
    report = UnmatchedPeakReport(unmatched_observed=(), extra_calculated=(), unknown_phase_flag=False)
    ident = PhaseIdentification(
        matches=(m,),
        unmatched=report,
        observed_peaks=(Peak(position=20.0, height=1.0),),
    )
    assert ident.matches == (m,)
    assert ident.unmatched is report
    assert len(ident.observed_peaks) == 1


def test_phase_identification_is_frozen():
    ident = PhaseIdentification(
        matches=(),
        unmatched=UnmatchedPeakReport(unmatched_observed=(), extra_calculated=(), unknown_phase_flag=False),
        observed_peaks=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        ident.matches = ()  # type: ignore[misc]
