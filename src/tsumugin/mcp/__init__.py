"""MCP サブパッケージ (M4 / REQ-021〜025/101/106/201)。

**SDK 非依存**: 本サブパッケージの ``tools`` / ``mem`` は MCP SDK を一切 import しない実処理層。
MCP ツール群の実処理関数 (プレーン関数・素の dict 応答) と MEM 委譲境界を公開する
(M4 の 8 ツール + M6 相同定 2 ツール = 10)。

**遅延 import 契約 (D7 / TASK-0045)**: SDK 依存のアダプタ層 ``server`` の公開 API
(``create_mcp_server`` / ``serve_stdio`` / ``serve_local``) も re-export するが、``server``
モジュールはトップレベルで mcp SDK を import しない (関数内で遅延 import) ため、この re-export
自体は optional extra ``mcp`` 未導入でも失敗しない。SDK を要求するのは各関数の呼び出し時点のみで、
未導入なら ``MCPUnavailableError`` へ縮退する (WebUIUnavailableError と対称)。
"""

from __future__ import annotations

from .mem import run_mem_boundary
from .server import create_mcp_server, serve_local, serve_stdio
from .tools import (
    MCP_TOOLS,
    AnalysisSession,
    accept_hypothesis,
    compare_hypotheses,
    export_gpx,
    get_trajectory,
    identify_phase_mixtures,
    identify_phases,
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
    "create_mcp_server",
    "export_gpx",
    "get_trajectory",
    "identify_phase_mixtures",
    "identify_phases",
    "list_hypotheses",
    "revert",
    "run_mem",
    "run_mem_boundary",
    "serve_local",
    "serve_stdio",
    "submit_analysis",
]
