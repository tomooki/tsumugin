"""MCP サブパッケージ (M4 / REQ-021〜025/101/106/201)。

**SDK 非依存**: 本サブパッケージの ``tools`` / ``mem`` は MCP SDK を一切 import しない実処理層。
8 ツール実処理関数 (プレーン関数・素の dict 応答) と MEM 委譲境界のみを公開する。MCP プロトコル
(JSON-RPC) との配線を担う SDK 依存の薄いアダプタ層 (``mcp.server``) は TASK-0045 スコープであり、
本 ``__init__`` からは re-export しない (遅延 import 契約・2 層分離, D7)。
"""

from __future__ import annotations

from .mem import run_mem_boundary
from .tools import (
    MCP_TOOLS,
    AnalysisSession,
    accept_hypothesis,
    compare_hypotheses,
    export_gpx,
    get_trajectory,
    list_hypotheses,
    revert,
    run_mem,
    submit_analysis,
)

__all__ = [
    "MCP_TOOLS",
    "AnalysisSession",
    "accept_hypothesis",
    "compare_hypotheses",
    "export_gpx",
    "get_trajectory",
    "list_hypotheses",
    "revert",
    "run_mem",
    "run_mem_boundary",
    "submit_analysis",
]
