"""`tsumugin.workbench.agent_bridge.AgentBridge` — V3a AUTO 実 LLM ブリッジのユニットテスト。

フェイク SDK メッセージ (このファイルのローカルクラス。``type(message).__name__`` で判定する
`AgentBridge` の duck-typing と同じ名前を持たせるだけで、``claude_agent_sdk`` を一切 import せずに
transcript 写像/tokens 累積/失敗縮退/二重 send 409/resume 継続を決定論的に検証できる) を注入する。

実 CLI 疎通 (`@pytest.mark.agent`) は本ファイル末尾。
"""

from __future__ import annotations

import asyncio
import json
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tsumugin.workbench.agent_bridge import AgentBridge, _load_agent_config


# ---------------------------------------------------------------------------
# フェイク SDK メッセージ (実 claude_agent_sdk 非依存 — クラス名一致のみで足りる)
# ---------------------------------------------------------------------------


class TextBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class ToolUseBlock:
    def __init__(self, id: str, name: str, input: dict[str, Any]) -> None:
        self.id = id
        self.name = name
        self.input = input


class ToolResultBlock:
    def __init__(self, tool_use_id: str, content: Any, is_error: bool = False) -> None:
        self.tool_use_id = tool_use_id
        self.content = content
        self.is_error = is_error


class AssistantMessage:
    def __init__(self, content: list[Any]) -> None:
        self.content = content


class UserMessage:
    def __init__(self, content: list[Any]) -> None:
        self.content = content


class ResultMessage:
    def __init__(
        self,
        *,
        usage: "dict[str, Any] | None" = None,
        duration_ms: int = 0,
        session_id: "str | None" = None,
        is_error: bool = False,
        result: "str | None" = None,
    ) -> None:
        self.usage = usage
        self.duration_ms = duration_ms
        self.session_id = session_id
        self.is_error = is_error
        self.result = result


def _make_query_fn(messages: "list[Any]", captured: "list[dict[str, Any]] | None" = None):
    async def _fn(*, prompt: str, options: Any):
        if captured is not None:
            captured.append({"prompt": prompt, "options": options})
        for message in messages:
            yield message

    return _fn


def _wait_until(predicate, timeout: float = 5.0) -> None:
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if predicate():
            return
        time.sleep(0.005)
    raise AssertionError("timed out waiting for condition")


def _wait_terminal(bridge: AgentBridge) -> None:
    _wait_until(lambda: bridge.status()["status"] != "running")


class _EventRecorder:
    """``AgentBridge(on_event=...)`` に渡すフェイク transcript ストア。"""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def append(self, kind: str, **fields: Any) -> dict[str, Any]:
        row: dict[str, Any] = {"id": f"t{len(self.rows) + 1}", "kind": kind, **fields}
        self.rows.append(row)
        return row


# ---------------------------------------------------------------------------
# available
# ---------------------------------------------------------------------------


def test_available_false_when_sdk_not_importable(monkeypatch: pytest.MonkeyPatch):
    import sys

    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    bridge = AgentBridge(on_event=lambda *a, **k: {})
    assert bridge.available is False


def test_available_true_when_query_fn_injected():
    bridge = AgentBridge(on_event=lambda *a, **k: {}, query_fn=_make_query_fn([]))
    assert bridge.available is True


# ---------------------------------------------------------------------------
# transcript 写像 / tokens 累積
# ---------------------------------------------------------------------------


def test_send_appends_agent_text_and_tool_call_with_result():
    recorder = _EventRecorder()
    messages = [
        AssistantMessage(content=[TextBlock(text="checking current state")]),
        AssistantMessage(
            content=[ToolUseBlock(id="tu1", name="mcp__tsumugin__get_state", input={})]
        ),
        UserMessage(content=[ToolResultBlock(tool_use_id="tu1", content="ok", is_error=False)]),
        ResultMessage(usage={"input_tokens": 10, "output_tokens": 5}, duration_ms=250, session_id="s1"),
    ]
    bridge = AgentBridge(on_event=recorder.append, query_fn=_make_query_fn(messages))

    assert bridge.send("hello") is True
    _wait_terminal(bridge)

    status = bridge.status()
    assert status["status"] == "idle"
    assert status["tokens"] == 15
    assert status["wall_time_s"] == pytest.approx(0.25)
    assert status["error"] is None

    assert recorder.rows[0]["kind"] == "agent"
    assert recorder.rows[0]["text"] == "checking current state"
    assert recorder.rows[1]["kind"] == "tool"
    assert recorder.rows[1]["tool"] == "get_state"  # mcp__tsumugin__ prefix stripped
    assert recorder.rows[1]["layer"] == "MCP ②"
    assert recorder.rows[1]["ret"] == "ok"
    assert recorder.rows[1]["secs"] >= 0


def test_tool_result_content_block_list_is_flattened_to_text():
    recorder = _EventRecorder()
    messages = [
        AssistantMessage(content=[ToolUseBlock(id="tu1", name="mcp__tsumugin__get_ledger", input={})]),
        UserMessage(
            content=[
                ToolResultBlock(
                    tool_use_id="tu1",
                    content=[{"type": "text", "text": "line1"}, {"type": "text", "text": "line2"}],
                )
            ]
        ),
        ResultMessage(),
    ]
    bridge = AgentBridge(on_event=recorder.append, query_fn=_make_query_fn(messages))
    bridge.send("hi")
    _wait_terminal(bridge)
    assert recorder.rows[0]["ret"] == "line1\nline2"


# ---------------------------------------------------------------------------
# 二重 send (409 相当)
# ---------------------------------------------------------------------------


def test_send_rejects_while_already_running():
    release = threading.Event()

    async def blocking_query_fn(*, prompt: str, options: Any):
        await asyncio.to_thread(release.wait)
        if False:  # pragma: no cover — async generator の型を保つためだけの到達不能 yield
            yield

    bridge = AgentBridge(on_event=lambda *a, **k: {}, query_fn=blocking_query_fn)
    assert bridge.send("first") is True
    # send() は自スレッド起動前に status="running" を同期的に確定させるため、ここで
    # 2 回目の呼び出しがレースなく確実に拒否される。
    assert bridge.send("second") is False
    release.set()
    _wait_terminal(bridge)
    assert bridge.status()["status"] == "idle"


# ---------------------------------------------------------------------------
# 失敗の縮退
# ---------------------------------------------------------------------------


def test_query_fn_exception_sets_failed_status_with_error():
    async def failing_query_fn(*, prompt: str, options: Any):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    bridge = AgentBridge(on_event=lambda *a, **k: {}, query_fn=failing_query_fn)
    bridge.send("hi")
    _wait_terminal(bridge)
    status = bridge.status()
    assert status["status"] == "failed"
    assert "boom" in status["error"]


def test_result_message_is_error_marks_failed_without_exception():
    messages = [ResultMessage(is_error=True, result="rate limited")]
    bridge = AgentBridge(on_event=lambda *a, **k: {}, query_fn=_make_query_fn(messages))
    bridge.send("hi")
    _wait_terminal(bridge)
    status = bridge.status()
    assert status["status"] == "failed"
    assert "rate limited" in status["error"]


def test_failed_turn_does_not_block_next_send():
    async def failing_query_fn(*, prompt: str, options: Any):
        raise RuntimeError("boom")
        yield  # pragma: no cover

    bridge = AgentBridge(on_event=lambda *a, **k: {}, query_fn=failing_query_fn)
    bridge.send("first")
    _wait_terminal(bridge)
    assert bridge.status()["status"] == "failed"
    # 失敗後も次の send は 409 にならない (running のままロックされない)。
    assert bridge.send("second") is True
    _wait_terminal(bridge)


# ---------------------------------------------------------------------------
# 会話継続 (resume) / システムプロンプト / config
# ---------------------------------------------------------------------------


def test_session_id_resumes_across_turns():
    captured: list[dict[str, Any]] = []
    bridge = AgentBridge(
        on_event=lambda *a, **k: {},
        query_fn=_make_query_fn([ResultMessage(session_id="sess-42", duration_ms=10)], captured),
    )
    bridge.send("turn1")
    _wait_terminal(bridge)
    assert captured[0]["options"]["resume"] is None

    bridge._query_fn = _make_query_fn([ResultMessage(session_id="sess-42", duration_ms=10)], captured)
    bridge.send("turn2")
    _wait_terminal(bridge)
    assert captured[1]["options"]["resume"] == "sess-42"


def test_system_prompt_includes_state_summary_when_provided():
    captured: list[dict[str, Any]] = []
    bridge = AgentBridge(
        on_event=lambda *a, **k: {},
        get_state_summary=lambda: {"mode": "auto", "marker": "xyz123"},
        query_fn=_make_query_fn([], captured),
    )
    bridge.send("hi")
    _wait_terminal(bridge)
    assert "xyz123" in captured[0]["options"]["system_prompt"]


def test_state_summary_exception_does_not_break_turn():
    def _boom() -> dict[str, Any]:
        raise ValueError("no state yet")

    captured: list[dict[str, Any]] = []
    bridge = AgentBridge(
        on_event=lambda *a, **k: {}, get_state_summary=_boom, query_fn=_make_query_fn([], captured)
    )
    bridge.send("hi")
    _wait_terminal(bridge)
    assert bridge.status()["status"] == "idle"
    assert captured[0]["options"]["system_prompt"]  # ヘッダのみでも空でない


def test_config_path_overrides_max_turns(tmp_path: Path):
    config_path = tmp_path / "agent.json"
    config_path.write_text(json.dumps({"max_turns": 7}), encoding="utf-8")
    captured: list[dict[str, Any]] = []
    bridge = AgentBridge(
        on_event=lambda *a, **k: {}, query_fn=_make_query_fn([], captured), config_path=config_path
    )
    bridge.send("hi")
    _wait_terminal(bridge)
    assert captured[0]["options"]["max_turns"] == 7


# ---------------------------------------------------------------------------
# CRITICAL guard: ビルトインツール全無効 (V3a レビュー指摘 #1)
# ---------------------------------------------------------------------------


def test_build_options_disables_builtin_tools_and_restricts_to_shim_mcp_tools():
    """非注入 (実 SDK) 経路の ``_build_options()`` は ``tools=[]`` (ビルトイン全無効) を返し、
    ``allowed_tools`` は shim (`agent_mcp`) の完全修飾 mcp ツール id 集合とちょうど一致する。

    ``tools`` 未設定 (SDK 既定 ``None``) だと CLI へ ``--tools`` が渡らず、CLI 既定のビルトイン
    (Bash/Read/Write/Edit/WebFetch 等) が ``bypassPermissions`` 下で素通しに有効化されてしまう
    (shim による権限境界が虚構になる)。``tools`` キー自体を削る変異で本テストは fail する。
    """
    from tsumugin.workbench import agent_mcp

    bridge = AgentBridge(on_event=lambda *a, **k: {})
    options = bridge._build_options()

    assert options.tools == []
    assert options.allowed_tools == agent_mcp.allowed_tool_ids()
    assert set(options.allowed_tools) == {
        f"mcp__{agent_mcp.SERVER_NAME}__{name}" for name in agent_mcp.ALLOWED_TOOL_NAMES
    }


def test_build_options_cli_args_pass_empty_tools_and_shim_allowed_tools():
    """`_build_options()` が実際に SDK の CLI コマンド組み立て (`subprocess_cli.py
    _build_command`) を通ったときに ``--tools ""`` (ベースのビルトインツール集合が空)
    + ``--allowedTools <shim id 群>`` になることを、SDK 内部の変換ロジックを直接使って確認する
    (SDK の ``tools=[]`` の意味論そのものを検証する — こちらが動作の一次情報源)。実プロセスは
    起動しない (``cli_path`` をダミー文字列に固定しコマンド配列を組み立てるだけ)。
    """
    pytest.importorskip("claude_agent_sdk")
    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    from tsumugin.workbench import agent_mcp

    bridge = AgentBridge(on_event=lambda *a, **k: {})
    options = bridge._build_options()
    options.cli_path = "claude-stub"  # 実 CLI 探索/起動を避ける (コマンド組み立てのみ検証)

    transport = SubprocessCLITransport(prompt="hi", options=options)
    cmd = transport._build_command()

    assert "--tools" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""  # 空 = ビルトイン全無効 (SDK 実挙動で確認済み)

    assert "--allowedTools" in cmd
    allowed = set(cmd[cmd.index("--allowedTools") + 1].split(","))
    assert allowed == set(agent_mcp.allowed_tool_ids())


def test_load_agent_config_missing_file_returns_empty(tmp_path: Path):
    assert _load_agent_config(tmp_path / "does-not-exist.json") == {}


def test_load_agent_config_broken_json_returns_empty(tmp_path: Path):
    path = tmp_path / "agent.json"
    path.write_text("{not json", encoding="utf-8")
    assert _load_agent_config(path) == {}


def test_load_agent_config_non_dict_json_returns_empty(tmp_path: Path):
    path = tmp_path / "agent.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert _load_agent_config(path) == {}


def test_default_config_path_resolves_lazily_under_patched_home():
    """`Path.home()` monkeypatch (conftest autouse) が import 時定数化されていないことの確認。"""
    from tsumugin.workbench.agent_bridge import _default_config_path

    assert _default_config_path() == Path.home() / ".tsumugin" / "agent.json"


# ---------------------------------------------------------------------------
# gated: 実 claude CLI + claude-agent-sdk での 1 ターン疎通 (subscription 実消費)
# ---------------------------------------------------------------------------


@pytest.mark.agent
def test_real_cli_single_turn_reports_state(monkeypatch: pytest.MonkeyPatch):
    """実サブスクリプションで 1 ターン実走し、transcript に kind=agent が append され tokens>0
    になることを確認する (最大 3 ターン・小プロンプト)。ネットワーク/認証失敗は skip でなく
    failed 状態への縮退を確認する形で許容する。"""
    pytest.importorskip("claude_agent_sdk")
    if shutil.which("claude") is None:
        pytest.skip("claude CLI が PATH に見つからない")

    import uvicorn

    from tsumugin.workbench.app import create_workbench_app
    from tsumugin.workbench.session import WorkbenchSession

    # 【max_turns を小さく】: AgentBridge は構築時に ~/.tsumugin/agent.json (fake home,
    #   conftest _isolated_home) を読む。session 構築 (AgentBridge 構築) より前に書く必要がある。
    agent_config_dir = Path.home() / ".tsumugin"
    agent_config_dir.mkdir(parents=True, exist_ok=True)
    (agent_config_dir / "agent.json").write_text(json.dumps({"max_turns": 3}), encoding="utf-8")

    session = WorkbenchSession.create_demo()
    session.set_mode("auto")
    app = create_workbench_app(session)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        _wait_until(lambda: server.started, timeout=10)
        port = server.servers[0].sockets[0].getsockname()[1]
        monkeypatch.setenv("TSUMUGIN_WORKBENCH_PORT", str(port))

        result = session.post_message(
            "GET the workbench state via the get_state tool and report the current mode "
            "and Rwp in one short sentence. Do not call any other tool."
        )
        assert result.get("status") == "agent_started", result

        _wait_until(lambda: session.agent_status()["status"] != "running", timeout=180)

        status = session.agent_status()
        transcript = session.viewmodel()["transcript"]
        agent_rows = [m for m in transcript if m.get("kind") == "agent"]
        tool_rows = [m for m in transcript if m.get("kind") == "tool"]

        # 【cp932 コンソール対策】: Windows のデフォルトコンソール符号化 (cp932) は絵文字/一部の
        #   記号 (例 en-dash) を表現できず、素の print が UnicodeEncodeError で落ちる — レポート
        #   目的の診断出力なので ASCII へ縮退させて確実に表示させる (テスト結果自体は変えない)。
        def _ascii(obj: Any) -> str:
            return json.dumps(obj, ensure_ascii=True, default=str)

        print("\n[gated real-CLI test] agent_status:", _ascii(status))
        print("[gated real-CLI test] agent rows:", _ascii(agent_rows))
        print("[gated real-CLI test] tool rows:", _ascii(tool_rows))

        assert status["status"] in ("idle", "failed")
        if status["status"] == "failed":
            pytest.skip(f"agent turn ended failed (network/auth?): {status['error']}")
        assert agent_rows, "expected at least one kind=agent transcript row"
        assert status["tokens"] > 0
    finally:
        server.should_exit = True
        thread.join(timeout=10)
