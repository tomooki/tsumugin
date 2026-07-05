"""M8: 判断ポリシー — AnalysisPolicy Protocol + 決定論の RuleBasedPolicy。

`RuleBasedPolicy` は **SafeAction のみ**を (診断が並べた) 優先度順に選び、ModelAction は無視する
(③ に委ねる)。目標 Rwp 到達 / 新規 safe 手なし (停滞) / 反復上限で `Stop`。既試行 Action を再選択
しないことで**終了を保証**し、種・入力が同一ならビット同一に振る舞う (NFR-102, architecture.md §3.2)。

AI 判断者 (③) も同じ `AnalysisPolicy` 契約を満たすが、その実体は Claude Code (ライブラリ外)。
本ライブラリは AgentPolicy→LLM の外呼びを持たない (§0 二重反転回避)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from tsumugin.autorietveld import AutoRietveldResult
from .action import AnalysisAction, Stop
from .diagnostics import ActionProposal


@dataclass(frozen=True)
class PolicyBudget:
    """ポリシーの停止条件。

    :param max_iterations: 反復上限
    :param target_rwp: 目標 Rwp (到達で Stop)。None なら停滞/上限のみで停止
    """

    max_iterations: int = 8
    target_rwp: float | None = None


@dataclass(frozen=True)
class AnalysisStep:
    """ループ 1 反復の記録 (履歴)。

    :param iteration: 反復番号
    :param action: 実行した Action
    :param result_rwp: 適用後 (候補) の Rwp
    :param accepted: 受理基準を満たし採用されたか (False=棄却/revert)
    """

    iteration: int
    action: AnalysisAction
    result_rwp: float
    accepted: bool


@dataclass(frozen=True)
class AnalysisState:
    """ポリシーが観測する状態。

    :param result: 直近のフィット結果
    :param proposals: 診断が出した次手候補 (safe 優先・優先度降順)
    :param history: これまでの反復記録
    :param iteration: 現在の反復番号
    :param budget: 停止条件
    """

    result: AutoRietveldResult
    proposals: tuple[ActionProposal, ...]
    history: tuple[AnalysisStep, ...]
    iteration: int
    budget: PolicyBudget = field(default_factory=PolicyBudget)


@runtime_checkable
class AnalysisPolicy(Protocol):
    """観測状態から次の 1 アクションを決める判断者。Stop で終了。"""

    def decide(self, state: AnalysisState) -> AnalysisAction:
        ...


@dataclass(frozen=True)
class RuleBasedPolicy:
    """安全部分集合 (SafeAction) のみを実行する決定論ポリシー (§3.2, §4)。"""

    def decide(self, state: AnalysisState) -> AnalysisAction:
        budget = state.budget
        # 目標 Rwp 到達で停止
        if budget.target_rwp is not None and state.result.final_rwp <= budget.target_rwp:
            return Stop(f"target Rwp {budget.target_rwp} reached (={state.result.final_rwp:.3f})")
        # 反復上限で停止
        if state.iteration >= budget.max_iterations:
            return Stop(f"max iterations {budget.max_iterations} reached")

        # Action は flags 等の dict フィールドを持ちうる (unhashable) ため list で等価判定する。
        tried = [step.action for step in state.history]
        # SafeAction のみを優先度降順で選ぶ (診断のソートに依存せず防御的に整列; 決定論)。
        safe = [p for p in state.proposals if p.safe]
        safe.sort(key=lambda p: (-p.priority, type(p.action).__name__))
        for proposal in safe:
            if proposal.action in tried:
                continue  # 既試行は再選択しない (終了保証)
            return proposal.action

        # 新規の safe 手がない = 停滞。ModelAction 提案は open_proposals として ③ へ。
        return Stop("no new SafeAction; remaining proposals are ModelAction (③ へ)")
