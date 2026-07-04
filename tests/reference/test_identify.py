"""M6 TASK-0101 identify_phases オーケストレーションの失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/engine.py`` (未実装)。
`identify_phases(two_theta, intensity, provider, *, elements, hull_cutoff_ev, ...)` を検証する。
Fake provider で決定論・元素系フィルタ・hull フィルタ (FR-103)・未知相レポート (FR-117) を検証。

土台は既存 `find_peaks` / `match_score` / `unmatched_peaks` (numpy-only, GSAS-II 非依存)。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from tsumugin.reference.engine import identify_phases
from tsumugin.reference.model import PhaseIdentification, ReferencePhase
from tsumugin.search.peaks import Peak


class FakeProvider:
    """`ReferenceProvider` を満たす in-memory テストダブル。fetch 引数を記録する。"""

    def __init__(self, phases: Sequence[ReferencePhase]) -> None:
        self._phases = tuple(phases)
        self.calls: list[tuple[str, ...]] = []

    def fetch(self, elements: Sequence[str]) -> Sequence[ReferencePhase]:
        self.calls.append(tuple(elements))
        return self._phases


def _ref(
    phase_id: str,
    *,
    peaks: Sequence[tuple[float, float]],
    elements: Sequence[str],
    formula: str = "X",
    ehull: float | None = 0.0,
) -> ReferencePhase:
    return ReferencePhase(
        phase_id=phase_id,
        formula=formula,
        element_system=tuple(sorted(elements)),
        peaks=tuple(Peak(position=p, height=h) for p, h in peaks),
        energy_above_hull=ehull,
    )


def _gaussian_pattern(centers: Sequence[float], *, heights: Sequence[float] | None = None,
                      fwhm: float = 0.2) -> tuple[np.ndarray, np.ndarray]:
    """指定 2θ 中心に Gaussian ピークを立てた合成パターンを返す (決定論)。"""
    two_theta = np.arange(15.0, 60.0, 0.02)
    intensity = np.zeros_like(two_theta)
    hs = heights if heights is not None else [1.0] * len(centers)
    sigma = fwhm / 2.3548
    for c, h in zip(centers, hs):
        intensity += h * np.exp(-0.5 * ((two_theta - c) / sigma) ** 2)
    return two_theta, intensity


# --- 基本ランキング --------------------------------------------------------


def test_returns_phase_identification():
    tt, inten = _gaussian_pattern([20.0, 30.0])
    prov = FakeProvider([_ref("mp-1", peaks=[(20.0, 1.0), (30.0, 0.8)], elements=["Fe", "O"])])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    assert isinstance(result, PhaseIdentification)


def test_best_match_ranked_first():
    tt, inten = _gaussian_pattern([20.0, 30.0, 40.0])
    good = _ref("mp-good", peaks=[(20.0, 1.0), (30.0, 1.0), (40.0, 1.0)], elements=["Fe", "O"])
    poor = _ref("mp-poor", peaks=[(25.0, 1.0), (55.0, 1.0)], elements=["Fe", "O"])
    prov = FakeProvider([poor, good])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    assert result.matches[0].reference.phase_id == "mp-good"
    assert result.matches[0].score > result.matches[1].score


def test_ranking_is_deterministic_tie_break_phase_id():
    tt, inten = _gaussian_pattern([20.0, 30.0])
    peaks = [(20.0, 1.0), (30.0, 1.0)]
    a = _ref("mp-b", peaks=peaks, elements=["Fe", "O"])
    b = _ref("mp-a", peaks=peaks, elements=["Fe", "O"])
    prov = FakeProvider([a, b])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    # 同点スコアは phase_id 昇順で安定
    assert [m.reference.phase_id for m in result.matches] == ["mp-a", "mp-b"]


def test_provider_queried_with_elements():
    tt, inten = _gaussian_pattern([20.0])
    prov = FakeProvider([_ref("mp-1", peaks=[(20.0, 1.0)], elements=["Fe", "O"])])
    identify_phases(tt, inten, prov, elements=["O", "Fe"])
    assert prov.calls == [("O", "Fe")]


# --- 元素系フィルタ --------------------------------------------------------


def test_phase_with_foreign_element_is_filtered_out():
    tt, inten = _gaussian_pattern([20.0, 30.0])
    allowed = _ref("mp-allowed", peaks=[(20.0, 1.0), (30.0, 1.0)], elements=["Fe", "O"])
    foreign = _ref("mp-foreign", peaks=[(20.0, 1.0), (30.0, 1.0)], elements=["Fe", "O", "Ni"])
    prov = FakeProvider([allowed, foreign])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    ids = [m.reference.phase_id for m in result.matches]
    assert "mp-foreign" not in ids
    assert "mp-allowed" in ids


def test_subset_phase_is_kept():
    # 元素系の部分集合 (例: Fe2O3 は Li-Fe-P-O 系の探索でも候補になり得る)
    tt, inten = _gaussian_pattern([20.0])
    subset = _ref("mp-sub", peaks=[(20.0, 1.0)], elements=["Fe", "O"])
    prov = FakeProvider([subset])
    result = identify_phases(tt, inten, prov, elements=["Li", "Fe", "P", "O"])
    assert [m.reference.phase_id for m in result.matches] == ["mp-sub"]


# --- hull フィルタ (FR-103) ------------------------------------------------


def test_hull_filter_drops_high_energy_phase():
    tt, inten = _gaussian_pattern([20.0, 30.0])
    stable = _ref("mp-stable", peaks=[(20.0, 1.0), (30.0, 1.0)], elements=["Fe", "O"], ehull=0.0)
    unstable = _ref("mp-unstable", peaks=[(20.0, 1.0), (30.0, 1.0)], elements=["Fe", "O"], ehull=0.25)
    prov = FakeProvider([stable, unstable])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"], hull_cutoff_ev=0.1)
    ids = [m.reference.phase_id for m in result.matches]
    assert ids == ["mp-stable"]


def test_hull_filter_keeps_unregistered_none_energy():
    # FR-103: MP未登録 (energy_above_hull=None) は hull フィルタで除外せず保持する
    tt, inten = _gaussian_pattern([20.0])
    unreg = _ref("user-cif", peaks=[(20.0, 1.0)], elements=["Fe", "O"], ehull=None)
    prov = FakeProvider([unreg])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"], hull_cutoff_ev=0.1)
    assert [m.reference.phase_id for m in result.matches] == ["user-cif"]


def test_hull_cutoff_none_disables_filter():
    tt, inten = _gaussian_pattern([20.0])
    unstable = _ref("mp-hi", peaks=[(20.0, 1.0)], elements=["Fe", "O"], ehull=1.0)
    prov = FakeProvider([unstable])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"], hull_cutoff_ev=None)
    assert [m.reference.phase_id for m in result.matches] == ["mp-hi"]


def test_hull_boundary_is_inclusive():
    # 閾値ちょうどは保持 (<= 採用)
    tt, inten = _gaussian_pattern([20.0])
    edge = _ref("mp-edge", peaks=[(20.0, 1.0)], elements=["Fe", "O"], ehull=0.1)
    prov = FakeProvider([edge])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"], hull_cutoff_ev=0.1)
    assert [m.reference.phase_id for m in result.matches] == ["mp-edge"]


# --- 未知相レポート (FR-117) -----------------------------------------------


def test_unmatched_observed_peak_flags_unknown_phase():
    # 観測に候補で説明できないピーク (50°) がある → unknown_phase_flag=True
    tt, inten = _gaussian_pattern([20.0, 50.0])
    partial = _ref("mp-partial", peaks=[(20.0, 1.0)], elements=["Fe", "O"])
    prov = FakeProvider([partial])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    assert result.unmatched.unknown_phase_flag is True
    unmatched_positions = [round(p.position) for p in result.unmatched.unmatched_observed]
    assert 50 in unmatched_positions


def test_complete_explanation_no_unknown_flag():
    tt, inten = _gaussian_pattern([20.0, 30.0])
    full = _ref("mp-full", peaks=[(20.0, 1.0), (30.0, 1.0)], elements=["Fe", "O"])
    prov = FakeProvider([full])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    assert result.unmatched.unknown_phase_flag is False


# --- max_results / エッジ ---------------------------------------------------


def test_max_results_truncates_matches():
    tt, inten = _gaussian_pattern([20.0, 30.0])
    peaks = [(20.0, 1.0), (30.0, 1.0)]
    prov = FakeProvider([
        _ref("mp-1", peaks=peaks, elements=["Fe", "O"]),
        _ref("mp-2", peaks=peaks, elements=["Fe", "O"]),
        _ref("mp-3", peaks=peaks, elements=["Fe", "O"]),
    ])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"], max_results=2)
    assert len(result.matches) == 2


def test_max_results_does_not_hide_unknown_peaks():
    # max_results で表示を絞っても、未知相判定は全生存候補の説明力で行う
    tt, inten = _gaussian_pattern([20.0, 30.0, 50.0])
    prov = FakeProvider([
        _ref("mp-a", peaks=[(20.0, 1.0)], elements=["Fe", "O"]),
        _ref("mp-b", peaks=[(30.0, 1.0)], elements=["Fe", "O"]),
        _ref("mp-c", peaks=[(50.0, 1.0)], elements=["Fe", "O"]),
    ])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"], max_results=1)
    # 3 相合わせれば 20/30/50 全て説明でき unknown_phase_flag=False であるべき
    assert result.unmatched.unknown_phase_flag is False


def test_empty_pattern_returns_empty_matches():
    two_theta = np.arange(15.0, 60.0, 0.02)
    intensity = np.zeros_like(two_theta)
    prov = FakeProvider([_ref("mp-1", peaks=[(20.0, 1.0)], elements=["Fe", "O"])])
    result = identify_phases(two_theta, intensity, prov, elements=["Fe", "O"])
    assert result.observed_peaks == ()
    # 観測ピークゼロでも例外化しない
    assert isinstance(result, PhaseIdentification)


def test_no_candidates_after_filter_returns_empty():
    tt, inten = _gaussian_pattern([20.0])
    prov = FakeProvider([_ref("mp-1", peaks=[(20.0, 1.0)], elements=["Ni"])])
    result = identify_phases(tt, inten, prov, elements=["Fe", "O"])
    assert result.matches == ()


def test_empty_elements_raises():
    tt, inten = _gaussian_pattern([20.0])
    prov = FakeProvider([])
    with pytest.raises(ValueError):
        identify_phases(tt, inten, prov, elements=[])
