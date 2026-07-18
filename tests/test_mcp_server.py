"""TASK-0045 mcp/server (SDK 依存の薄いアダプタ層・遅延 import) の TDD テスト。

対象実装 (本タスクで新設):
- ``src/tsumugin/mcp/server.py``: ``create_mcp_server`` / ``serve_stdio`` / ``serve_local``
  (mcp SDK を遅延 import し、未導入なら ``MCPUnavailableError`` へ縮退する)

完了条件 5 項目 (TASK-0045) に 1:1 対応する:
  (1) ``import tsumugin.mcp.server`` が mcp SDK 未導入でも成功する      [REQ-102/EDGE-009]
  (2) SDK 未導入で create_mcp_server/serve_stdio が MCPUnavailableError へ縮退し
      ツール実処理関数 (tools.py) は SDK 非依存で動作する                [TC-407-08/EDGE-009]
  (3) @pytest.mark.mcp: SDK 導入時に create_mcp_server が 8 ツールを配線   [REQ-021]
  (4) serve_stdio/serve_local が既定ローカル (stdio / host=127.0.0.1) で
      無認証ネットワーク公開しない (シグネチャ/既定値の検証)             [REQ-303/405]
  (5) コア import が numpy のみ (mcp なしで tsumugin が import 可能)      [TC-408-04/REQ-403]

WebUIUnavailableError パターン (tests/test_webui.py) の縮退テストの書き方を踏襲する。
SDK 配線の実テスト (3) のみ ``@pytest.mark.mcp`` で分離し、SDK 未導入環境では
conftest.py が自動 skip する (既存 gsas マーカと同型)。
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect

import pytest

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.errors import MCPUnavailableError, TsumuginError
from tsumugin.evidence.ic import BICBackend
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance, Project
from tsumugin.search.matcher import UnmatchedPeakReport
from tsumugin.search.tree import SearchResult
from tsumugin.selection import FinalSelectionEngine
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# 【遅延 import 契約の核】: SDK 未導入でも import 自体は成功しなければならない (下の (1) で検証) 🔵
from tsumugin.mcp import server as server_module
from tsumugin.mcp.server import create_mcp_server, serve_local, serve_stdio

_MCP_PRESENT = importlib.util.find_spec("mcp") is not None


# ---------------------------------------------------------------------------
# テストデータヘルパ (tests/test_mcp_tools.py の慣習を踏襲)
# ---------------------------------------------------------------------------


def _phase(a: float = 4.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=1.0)


def _search_result() -> SearchResult:
    led = Ledger()
    hyp = Hypothesis(id="hyp-0001", phases=(_phase(),), metrics=None, status="candidate")
    return SearchResult(
        ranked=(),
        hypotheses={hyp.id: hyp},
        good_cluster_ids=(),
        alternatives={},
        unmatched=UnmatchedPeakReport(
            unmatched_observed=(), extra_calculated=(), unknown_phase_flag=False
        ),
        final_reports={},
        ledger=led,
        snapshots=SnapshotStore(ledger=led),
        warnings=(),
    )


def _session() -> "server_module.AnalysisSession":
    from tsumugin.mcp.tools import AnalysisSession

    ledger = Ledger()
    return AnalysisSession(
        project=Project(id="proj-0"),
        backend=SimulatedBackend(),
        selection=FinalSelectionEngine(mode="agent", ledger=ledger),
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        evidence=BICBackend(),
        search_result=_search_result(),
    )


# ===========================================================================
# (1) import tsumugin.mcp.server が mcp SDK 未導入でも成功する [REQ-102/EDGE-009]
# ===========================================================================


def test_import_server_module_succeeds_without_sdk():
    # 【テスト目的】: 遅延 import 契約 — SDK 未導入でもモジュール import が成功する 🔵
    # 【テスト内容】: reimport して create_mcp_server/serve_stdio/serve_local が引ける
    # 【期待される動作】: WebUIUnavailableError パターンと対称。トップレベルで mcp を引かない
    reimported = importlib.import_module("tsumugin.mcp.server")
    assert reimported is server_module  # 【検証項目】: import 成功 (キャッシュ同一体) 🔵
    for name in ("create_mcp_server", "serve_stdio", "serve_local"):
        assert callable(getattr(reimported, name))  # 【検証項目】: 公開 API が引ける 🔵


def test_server_module_does_not_import_mcp_sdk_at_module_top():
    # 【テスト目的】: モジュールトップレベルで mcp SDK を import していないことを構造検証 🔵
    # 【テスト内容】: server.py のソースに素の `import mcp` / `from mcp` がトップレベルに無い
    # 【期待される動作】: mcp 参照は関数内 (遅延) のみ。未導入環境で import が壊れない
    source = inspect.getsource(server_module)
    # モジュール**トップレベル** (インデント無し = 関数本体でない行) に mcp SDK import が無いことを
    # 確認する。関数内の遅延 import (インデント有り) は契約上許容される。
    for line in source.splitlines():
        if line[:1].isspace() or not line.strip():
            continue  # インデント行 (関数本体) と空行は対象外 — 遅延 import は許容
        stripped = line.strip()
        assert not stripped.startswith("import mcp")  # 【検証項目】: top-level `import mcp` 不在 🔵
        assert not stripped.startswith("from mcp ")  # 【検証項目】: top-level `from mcp` 不在 🔵
        assert not stripped.startswith("from mcp.")  # 【検証項目】: top-level `from mcp.` 不在 🔵


# ===========================================================================
# (2) SDK 未導入で create_mcp_server/serve_stdio が MCPUnavailableError へ縮退 [TC-407-08/EDGE-009]
# ===========================================================================


@pytest.mark.skipif(_MCP_PRESENT, reason="mcp SDK 導入済み環境では縮退経路をテストしない")
def test_create_mcp_server_without_sdk_raises_mcp_unavailable():
    # 【テスト目的】: SDK 未導入時に MCPUnavailableError (extra mcp 案内) を送出する 🔵 REQ-102
    # 【テスト内容】: create_mcp_server 呼び出しで誘導エラーが上がることを検証
    # 【期待される動作】: 遅延 import 契約 — import は成功し呼び出し時点でのみ失敗する
    with pytest.raises(MCPUnavailableError) as exc:
        create_mcp_server(_session())

    assert issubclass(MCPUnavailableError, TsumuginError)  # 【検証項目】: 例外階層 🔵
    message = str(exc.value)
    assert ("tsumugin[mcp]" in message) or ("uv sync --extra mcp" in message)
    # 【検証項目】: extra mcp の導入手順を案内するメッセージ 🔵


@pytest.mark.skipif(_MCP_PRESENT, reason="mcp SDK 導入済み環境では縮退経路をテストしない")
def test_serve_stdio_without_sdk_raises_mcp_unavailable():
    # 【テスト目的】: serve_stdio も SDK 未導入時は MCPUnavailableError へ縮退する 🔵 REQ-102
    with pytest.raises(MCPUnavailableError):
        serve_stdio(_session())


@pytest.mark.skipif(_MCP_PRESENT, reason="mcp SDK 導入済み環境では縮退経路をテストしない")
def test_serve_local_without_sdk_raises_mcp_unavailable():
    # 【テスト目的】: serve_local も SDK 未導入時は MCPUnavailableError へ縮退する 🔵 REQ-102/303
    with pytest.raises(MCPUnavailableError):
        serve_local(_session())


def test_tools_work_without_sdk_when_server_degrades():
    # 【テスト目的】: server が SDK 未導入で縮退しても、ツール実処理関数は SDK 非依存で動作する 🔵 EDGE-009
    # 【テスト内容】: create_mcp_server が縮退する一方で list_hypotheses が実データを返す
    # 【期待される動作】: 2 層分離 (D7) — tools.py は SDK に一切依存しない
    from tsumugin.mcp.tools import list_hypotheses

    session = _session()
    out = list_hypotheses(session)  # SDK 不要で動く
    assert isinstance(out, dict)  # 【検証項目】: 素の型 dict 応答 🔵
    assert "n_hypotheses" in out or "ranked" in out  # 【検証項目】: to_summary スキーマ 🔵


# ===========================================================================
# (4) serve_stdio/serve_local が既定ローカルで無認証公開しない (シグネチャ検証) [REQ-303/405]
# ===========================================================================


def test_serve_local_defaults_to_localhost_bind():
    # 【テスト目的】: serve_local の host 既定が 127.0.0.1 (無認証ネットワーク公開しない) 🔵 REQ-303/405
    # 【テスト内容】: シグネチャの既定値と kw-only 属性を検証 (SDK 不要で確認可能)
    # 【期待される動作】: 外部公開の口を作らない — 既定 localhost バインド
    sig = inspect.signature(serve_local)
    host_param = sig.parameters["host"]
    port_param = sig.parameters["port"]

    assert host_param.default == "127.0.0.1"  # 【検証項目】: localhost 既定 🔵
    assert host_param.kind is inspect.Parameter.KEYWORD_ONLY  # 【検証項目】: kw-only 🔵
    assert port_param.default == 0  # 【検証項目】: 任意ポート既定 0 🔵
    assert port_param.kind is inspect.Parameter.KEYWORD_ONLY  # 【検証項目】: kw-only 🔵


def test_serve_stdio_signature_is_local_default():
    # 【テスト目的】: serve_stdio が session のみを取る既定・ローカル起動口であることを確認 🔵 REQ-405
    # 【テスト内容】: シグネチャに host/port 等のネットワーク公開パラメータが無いことを検証
    # 【期待される動作】: stdio は本質的にローカル (ネットワーク露出の口が無い)
    sig = inspect.signature(serve_stdio)
    assert list(sig.parameters) == ["session"]  # 【検証項目】: session のみ 🔵


# ===========================================================================
# (5) コア import が numpy のみ (mcp なしで tsumugin が import 可能) [TC-408-04/REQ-403]
# ===========================================================================


def test_core_imports_without_mcp_sdk():
    # 【テスト目的】: mcp SDK 無しでも tsumugin コア/主要サブパッケージが import 可能 🔵 REQ-403
    # 【テスト内容】: import tsumugin と主要サブパッケージを reimport して例外なしを確認
    # 【期待される動作】: コア依存は numpy のみ。mcp/server は遅延 import で汚染しない
    for name in (
        "tsumugin",
        "tsumugin.mcp",
        "tsumugin.mcp.tools",
        "tsumugin.mcp.server",
        "tsumugin.errors",
    ):
        assert importlib.import_module(name) is not None  # 【検証項目】: import 成功 🔵


# ===========================================================================
# (3) @pytest.mark.mcp: SDK 導入時に create_mcp_server が 8 ツールを配線 [REQ-021]
#     — 未導入環境では conftest.py が自動 skip する
# ===========================================================================


@pytest.mark.mcp
def test_create_mcp_server_returns_server_object():
    # 【テスト目的】: SDK 導入時 create_mcp_server が MCP Server オブジェクトを返す 🔵 REQ-021
    # 【テスト内容】: 返り値が None でなく、例外なく構築されることを確認
    # 【期待される動作】: mcp SDK の Server を構築して返す
    server = create_mcp_server(_session())
    assert server is not None  # 【検証項目】: Server オブジェクトを返す 🔵


@pytest.mark.mcp
def test_create_mcp_server_wires_all_eight_tools():
    # 【テスト目的】: create_mcp_server が MCP_TOOLS の全ツールを配線する 🔵 REQ-021
    # 【テスト内容】: SDK の list_tools 相当を通じ全ツール名が登録されていることを確認
    # 【期待される動作】: MCP_TOOLS の全名が漏れなく Server へ配線される
    from tsumugin.mcp.tools import MCP_TOOLS

    server = create_mcp_server(_session())
    # 低レベル SDK: list_tools ハンドラを request_handlers 経由で駆動し登録ツール名を収集する。
    tools = _collect_tool_names(server)
    assert set(tools) == set(MCP_TOOLS)  # 【検証項目】: 全ツール配線 🔵
    # 【検証項目】: ツール総数 24 (M4 8 + M6 2 + M8 実構造 3 + M9 in situ 逐次 3 + M8-③ MEM 3
    #   + operando 診断 4 + M10 anchor 1 [anchored_sequential, Issue #97]) 🔵
    assert len(MCP_TOOLS) == 24


def _collect_tool_names(server: object) -> list[str]:
    """SDK 導入環境で Server から登録ツール名を収集する (バージョン差を吸収)。"""
    import anyio
    import mcp.types as mcp_types

    # 低レベル Server は list_tools ハンドラを request_handlers[ListToolsRequest] に保持する。
    handler = server.request_handlers[mcp_types.ListToolsRequest]

    async def _run() -> object:
        request = mcp_types.ListToolsRequest(method="tools/list")
        return await handler(request)

    result = anyio.run(_run)
    tools = result.root.tools
    return [t.name for t in tools]
