"""M8 Agentic 閉ループ解析 — 決定論コアの判断ループ (規則部)。

M7 の実構造自動 Rietveld (`tsumugin.autorietveld`) の上に、「フィット結果を観測し次手を
判断して再実行する」閉ループを載せる。判断者は 3 層に分離する (architecture.md §0):
① 決定論コア (本パッケージ: 規則が安全部分集合を実行) / ② 薄い MCP (計器+アクチュエータ) /
③ ハーネス (Claude Code plugin — 開放的判断・構造改訂・事前知識)。

"agentic" は capability であり ③ に置く。本パッケージは AgentPolicy→LLM の外呼びを持たず、
規則ポリシー + 種固定でビット同一な決定論ループとして振る舞う (NFR-102)。コア import は numpy のみ。
"""

from __future__ import annotations

from .action import (
    AddPhase,
    AdjustBackground,
    AnalysisAction,
    AnalysisInput,
    ModelAction,
    ReleaseParams,
    RemovePhase,
    RestrictUiso,
    ReviseStructure,
    SafeAction,
    SetAbsorption,
    SetLimits,
    SetMixedOccupancy,
    Stop,
)
from .diagnose_residual import diagnose_residual
from .diagnostics import (
    ActionProposal,
    ResidualFeatures,
    propose_initial_limits,
    propose_next_actions,
)
from .model_compare import ModelCompareResult, run_model_comparison
from .orchestrator import RefinementLoopResult, run_refinement_loop
from .policy import (
    AnalysisPolicy,
    AnalysisState,
    AnalysisStep,
    PolicyBudget,
    RuleBasedPolicy,
)

__all__ = [
    "ActionProposal",
    "AddPhase",
    "AdjustBackground",
    "AnalysisAction",
    "AnalysisInput",
    "AnalysisPolicy",
    "AnalysisState",
    "AnalysisStep",
    "ModelAction",
    "ModelCompareResult",
    "PolicyBudget",
    "RefinementLoopResult",
    "ReleaseParams",
    "RemovePhase",
    "ResidualFeatures",
    "RestrictUiso",
    "ReviseStructure",
    "RuleBasedPolicy",
    "SafeAction",
    "SetAbsorption",
    "SetLimits",
    "SetMixedOccupancy",
    "Stop",
    "diagnose_residual",
    "propose_initial_limits",
    "propose_next_actions",
    "run_model_comparison",
    "run_refinement_loop",
]
