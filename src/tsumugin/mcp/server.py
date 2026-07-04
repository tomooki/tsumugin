"""MCP サーバ (SDK 依存の薄いアダプタ層 / M4 / REQ-021/102/303/405 / interfaces.py mcp/server 節)。

**2 層分離 (D7)**: MCP ツール群の実処理は SDK 非依存の ``mcp.tools`` が担い、本モジュールは MCP
プロトコル (JSON-RPC) との配線のみを担う薄いアダプタ層である。``MCP_TOOLS`` を単一情報源として
低レベル MCP ``Server`` の ``list_tools`` / ``call_tool`` ハンドラへ MCP ツール群を配線する。

**SDK 遅延 import 契約 (WebUIUnavailableError と対称)**: コア依存は numpy のみ (CLAUDE.md /
REQ-403)。``mcp`` SDK は optional extra ``mcp``。**トップレベルで mcp を import しない**ことで、
``import tsumugin.mcp.server`` 自体は SDK 未導入でも成功させる。SDK を要求するのは
``create_mcp_server`` / ``serve_stdio`` / ``serve_local`` の呼び出し時点のみで、未導入なら
``MCPUnavailableError`` (extra 導入案内) へ変換する (REQ-102/EDGE-009)。実処理関数 ``mcp.tools``
は本例外・SDK に一切依存せず動作する。

**無認証ネットワーク公開しない (REQ-303/405)**: 既定は stdio トランスポート (``serve_stdio``、
本質的にローカル)。``serve_local`` はローカルバインド (``host="127.0.0.1"`` 既定) の任意
トランスポートに限り、外部公開の口を構造的に作らない。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..errors import MCPUnavailableError
from .tools import MCP_TOOLS, AnalysisSession

if TYPE_CHECKING:  # 【型のみ参照】: 実行時 import を避けコア依存 (numpy のみ) を汚染しない 🔵 REQ-403
    pass

__all__ = ["AnalysisSession", "create_mcp_server", "serve_local", "serve_stdio"]

# 【未導入誘導メッセージ】: extra mcp の導入手順 (pip / uv 両方) を明示する (WebUI と対称) 🟡
_MCP_EXTRA_HINT = (
    "MCP サーバには optional extra 'mcp' (公式 Model Context Protocol Python SDK) が必要です。"
    "`pip install 'tsumugin[mcp]'` または `uv sync --extra mcp` で導入してください。"
)


def _require_mcp() -> Any:
    """mcp SDK を遅延 import し、未導入なら誘導エラーへ変換する (WebUI ``_require_fastapi`` と対称)。

    【機能概要】: ``import mcp`` を関数内で行い、未導入 (ImportError/ModuleNotFoundError) を
      ``MCPUnavailableError`` (extra mcp 案内) へ変換する遅延 import ゲート。
    【実装方針】: モジュール読込時ではなく呼び出し時に評価することで、SDK 未導入環境でも
      ``import tsumugin.mcp.server`` を成功させる (遅延 import 契約, WebUIUnavailableError 対称)。
    🔵 信頼性レベル: 遅延 import 契約は interfaces.py mcp/server 節 / CLAUDE.md 由来。
    """
    try:
        # 【遅延 import】: 呼び出し時にのみ mcp SDK を要求する 🔵 REQ-102
        import mcp  # noqa: F401
    except ImportError as exc:  # 【未導入捕捉】: extra mcp 案内へ変換 (ModuleNotFoundError も含む) 🔵
        raise MCPUnavailableError(_MCP_EXTRA_HINT) from exc
    return mcp


def create_mcp_server(session: AnalysisSession) -> object:
    """MCP ``Server`` を構築し ``MCP_TOOLS`` の MCP ツール群を実処理関数へ配線して返す。🔵 REQ-021/102

    【SDK 遅延 import】: 本関数呼び出し時にのみ mcp SDK を import。未導入なら
      ``MCPUnavailableError`` を送出する (実処理関数 ``mcp.tools`` は SDK 非依存で動作,
      REQ-102/EDGE-009)。
    【配線】: ``MCP_TOOLS`` を単一情報源に、低レベル ``mcp.server.Server`` の ``list_tools`` /
      ``call_tool`` ハンドラへ MCP ツール群を登録する。各ツールは第 1 引数 ``session`` を束縛して
      呼び出され、素の型 dict 応答を JSON テキストコンテンツとして返す。
    【非破壊】: session を書き換えず、ツール実処理へ委譲するのみ (2 層分離, D7)。
    🔵 信頼性レベル: シグネチャ・MCP ツール群配線は interfaces.py mcp/server 節 / REQ-021 に確定。

    Args:
        session: MCP ツール群が委譲先へアクセスするための不変 facade (``AnalysisSession``)。

    Returns:
        構築済みの MCP ``Server`` インスタンス (呼び出し側が任意トランスポートで駆動する)。

    Raises:
        MCPUnavailableError: optional extra ``mcp`` (mcp SDK) 未導入のとき。
    """
    # 【遅延 import ゲート】: 未導入なら extra mcp 案内で早期に送出する 🔵 REQ-102
    _require_mcp()
    import json

    import mcp.types as mcp_types
    from mcp.server import Server

    server: Any = Server("tsumugin")

    # 【ツール記述子】: MCP_TOOLS の 8 名を list_tools で公開する。入力スキーマは緩い object
    #   (追加プロパティ許容) とし、実処理関数側の引数検証・既定値へ委ねる (D7 2 層分離) 🔵
    _tool_descriptors = [
        mcp_types.Tool(
            name=name,
            description=(getattr(fn, "__doc__", None) or name).strip().splitlines()[0],
            inputSchema={"type": "object", "additionalProperties": True},
        )
        for name, fn in MCP_TOOLS.items()
    ]

    @server.list_tools()
    async def _list_tools() -> list[Any]:
        # 【ツール公開】: MCP_TOOLS の 8 記述子をそのまま返す (単一情報源) 🔵 REQ-021
        return _tool_descriptors

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any] | None) -> list[Any]:
        # 【配線】: 名前から実処理関数を引き当て、session を束縛して委譲する 🔵 REQ-021
        fn = MCP_TOOLS.get(name)
        if fn is None:
            raise ValueError(f"unknown tool: {name}")
        kwargs = dict(arguments or {})
        # 【第 1 引数束縛】: 全ツールは (session, **kwargs) 形。素の型 dict 応答を得る 🔵
        result = fn(session, **kwargs)  # type: ignore[operator]
        # 【応答整形】: 素の型 dict を JSON テキストコンテンツで返す (SDK が転送) 🔵
        return [mcp_types.TextContent(type="text", text=json.dumps(result, allow_nan=False))]

    return server


def serve_stdio(session: AnalysisSession) -> None:
    """既定・ローカルの stdio トランスポートで MCP サーバを起動する (ブロッキング)。🔵 REQ-405

    【機能概要】: ``create_mcp_server(session)`` を構築し、stdio トランスポート
      (標準入出力・本質的にローカル) で駆動する。ネットワーク露出の口を持たない。
    【SDK 遅延 import】: 未導入なら ``create_mcp_server`` 内で ``MCPUnavailableError`` を送出する。
    🔵 信頼性レベル: シグネチャ・stdio 既定は interfaces.py mcp/server 節 / REQ-405 に依拠。

    Args:
        session: 配信対象の ``AnalysisSession``。

    Raises:
        MCPUnavailableError: optional extra ``mcp`` (mcp SDK) 未導入のとき。
    """
    # 【遅延 import ゲート】: 未導入なら create_mcp_server 内で extra mcp 案内が上がる 🔵 REQ-102
    server = create_mcp_server(session)
    import anyio
    from mcp.server.stdio import stdio_server

    async def _run() -> None:
        # 【stdio 駆動】: 標準入出力ストリームで Server を走らせる (ローカル・無公開) 🔵 REQ-405
        async with stdio_server() as (read_stream, write_stream):
            await server.run(  # type: ignore[attr-defined]
                read_stream, write_stream, server.create_initialization_options()
            )

    # 【ブロッキング配信】: stdio でローカルサーバを起動する 🔵 REQ-405
    anyio.run(_run)


def serve_local(session: AnalysisSession, *, host: str = "127.0.0.1", port: int = 0) -> None:
    """ローカルバインド (既定 ``127.0.0.1``) の任意トランスポートで起動する。🟡 REQ-303/405

    【機能概要】: ローカルホストへバインドした MCP サーバを起動する。既定 ``host="127.0.0.1"`` /
      ``port=0`` (任意ポート)。
    【SDK 遅延 import】: 未導入なら ``create_mcp_server`` 内で ``MCPUnavailableError`` を送出する。

    .. warning::
        本サーバに認証は無い。``host`` を ``127.0.0.1`` 以外 (例 ``0.0.0.0``) に変更すると、
        解析データ全量が同一ネットワークへ無認証で公開される。M4 はローカル利用専用であり、
        外部公開はサポートしない (REQ-303/405)。既定は localhost バインドで外部公開の口を作らない。
    🟡 信頼性レベル: シグネチャ・既定値は interfaces.py mcp/server 節 / REQ-303/405 に依拠、
      トランスポート駆動は SDK バージョン差があり実装時確定。

    Args:
        session: 配信対象の ``AnalysisSession``。
        host: バインドホスト (kw-only)。既定 ``127.0.0.1`` (localhost・外部非公開)。
        port: バインドポート (kw-only)。既定 ``0`` (OS 任意ポート)。

    Raises:
        MCPUnavailableError: optional extra ``mcp`` (mcp SDK) 未導入のとき。
    """
    # 【遅延 import ゲート】: 未導入なら create_mcp_server 内で extra mcp 案内が上がる 🔵 REQ-102
    server = create_mcp_server(session)
    import anyio
    from mcp.server.streamable_http import StreamableHTTPServerTransport

    # 【ローカルバインド担保】: 127.0.0.1 以外への公開口を構造的に作らない。SSE/HTTP トランスポートは
    #   ASGI アプリとして host/port にバインドして駆動する (無認証ゆえ既定 localhost 固定) 🟡 REQ-303
    async def _run() -> None:
        transport = StreamableHTTPServerTransport(mcp_session_id=None)
        import uvicorn
        from starlette.applications import Starlette
        from starlette.routing import Mount

        async def _handle_streamable_http(scope: Any, receive: Any, send: Any) -> None:
            await transport.handle_request(scope, receive, send)

        app = Starlette(routes=[Mount("/mcp", app=_handle_streamable_http)])

        async def _serve_connection() -> None:
            async with transport.connect() as (read_stream, write_stream):
                await server.run(  # type: ignore[attr-defined]
                    read_stream, write_stream, server.create_initialization_options()
                )

        config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        async with anyio.create_task_group() as tg:
            tg.start_soon(_serve_connection)
            await uvicorn.Server(config).serve()

    anyio.run(_run)
