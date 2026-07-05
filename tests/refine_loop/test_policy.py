"""TASK-0803: refine_loop.policy — AnalysisPolicy Protocol + RuleBasedPolicy。

RuleBasedPolicy は SafeAction のみを優先度順に選び、ModelAction は無視 (③ に委ねる)。
目標到達/停滞(新規 safe 手なし)/反復上限で Stop。決定論・終了保証 (architecture.md §3.2)。
"""

from __future__ import annotations

from tsumugin.autorietveld import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.refine_loop.action import AddPhase, AdjustBackground, ReleaseParams, Stop
from tsumugin.refine_loop.diagnostics import ActionProposal
from tsumugin.refine_loop.policy import (
    AnalysisPolicy,
    AnalysisState,
    AnalysisStep,
    PolicyBudget,
    RuleBasedPolicy,
)


def _result(rwp: float, *, passed: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=rwp, gof=1.0, n_params=8, converged=True),),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=passed),
    )


def _state(result, proposals=(), history=(), iteration=0, budget=None) -> AnalysisState:
    return AnalysisState(
        result=result,
        proposals=tuple(proposals),
        history=tuple(history),
        iteration=iteration,
        budget=budget or PolicyBudget(),
    )


def _safe(action, priority=0.5) -> ActionProposal:
    return ActionProposal(action=action, rationale="", priority=priority, safe=True)


def _unsafe(action, priority=1.0) -> ActionProposal:
    return ActionProposal(action=action, rationale="", priority=priority, safe=False)


def test_rulebased_is_analysispolicy():
    assert isinstance(RuleBasedPolicy(), AnalysisPolicy)


def test_picks_highest_priority_safe_action():
    props = (_safe(AdjustBackground(9), 0.3), _safe(ReleaseParams("s", {"size_strain": True}), 0.8))
    # propose_next_actions は safe 優先・優先度降順で渡す想定 → 先頭を選ぶ
    action = RuleBasedPolicy().decide(_state(_result(20.0), props))
    assert isinstance(action, ReleaseParams)


def test_ignores_model_actions_even_if_higher_priority():
    props = (_unsafe(AddPhase(element_hint=("Ca",)), 0.9), _safe(AdjustBackground(9), 0.2))
    action = RuleBasedPolicy().decide(_state(_result(20.0), props))
    assert isinstance(action, AdjustBackground)  # ModelAction は無視


def test_stops_when_only_model_actions_available():
    props = (_unsafe(AddPhase(element_hint=("Ca",))),)
    action = RuleBasedPolicy().decide(_state(_result(20.0), props))
    assert isinstance(action, Stop)
    assert "safe" in action.reason.lower() or "③" in action.reason or action.reason


def test_stops_when_target_rwp_reached():
    budget = PolicyBudget(target_rwp=10.0)
    props = (_safe(AdjustBackground(9)),)
    action = RuleBasedPolicy().decide(_state(_result(9.5), props, budget=budget))
    assert isinstance(action, Stop) and "target" in action.reason.lower()


def test_stops_at_max_iterations():
    budget = PolicyBudget(max_iterations=3)
    props = (_safe(AdjustBackground(9)),)
    action = RuleBasedPolicy().decide(_state(_result(20.0), props, iteration=3, budget=budget))
    assert isinstance(action, Stop)


def test_does_not_repeat_already_tried_action():
    # 一度試した (履歴にある) safe 手は再選択しない → 終了保証
    tried = AdjustBackground(9)
    history = (AnalysisStep(iteration=0, action=tried, result_rwp=19.0, accepted=False),)
    props = (_safe(tried),)
    action = RuleBasedPolicy().decide(_state(_result(20.0), props, history=history, iteration=1))
    assert isinstance(action, Stop)  # 唯一の safe 手が既試行 → Stop


def test_progressive_background_is_not_blocked():
    # 既試行が bg=9 でも、新規に提案された bg=12 は別 Action なので選ぶ
    history = (
        AnalysisStep(iteration=0, action=AdjustBackground(9), result_rwp=15.0, accepted=True),
    )
    props = (_safe(AdjustBackground(12)),)
    action = RuleBasedPolicy().decide(_state(_result(15.0), props, history=history, iteration=1))
    assert action == AdjustBackground(12)


def test_deterministic_same_state_same_action():
    props = (_safe(AdjustBackground(9), 0.3), _safe(ReleaseParams("s", {"size_strain": True}), 0.8))
    s = _state(_result(20.0), props)
    assert RuleBasedPolicy().decide(s) == RuleBasedPolicy().decide(s)
