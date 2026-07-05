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
    ReviseStructure,
    SafeAction,
    SetLimits,
    SetMixedOccupancy,
    Stop,
)
from .diagnostics import (
    ActionProposal,
    ResidualFeatures,
    propose_initial_limits,
    propose_next_actions,
)

__all__ = [
    "ActionProposal",
    "AddPhase",
    "AdjustBackground",
    "AnalysisAction",
    "AnalysisInput",
    "ModelAction",
    "ReleaseParams",
    "RemovePhase",
    "ResidualFeatures",
    "ReviseStructure",
    "SafeAction",
    "SetLimits",
    "SetMixedOccupancy",
    "Stop",
    "propose_initial_limits",
    "propose_next_actions",
]
