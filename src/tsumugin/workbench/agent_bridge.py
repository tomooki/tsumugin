"""AUTO 実 LLM ブリッジ (V3a) — `docs/design/gui-workbench/api-contract.md` §AUTO 実 LLM ブリッジ。

ローカル `claude` CLI (claude-agent-sdk 経由, optional extra ``agent``) を駆動する ``AgentBridge``。
エージェントは `agent_mcp` shim (専用 MCP server) 越しにのみ workbench HTTP API へ到達できる —
人間と同じ custody ガード (ledger/409/422) が全て適用される (§権限境界, 変更禁止)。

**SDK 非依存 import**: 本モジュールのトップレベルは ``claude_agent_sdk`` を import しない。
``AgentBridge.available`` は遅延 import の可否で判定し、未導入環境では常に ``False`` へ縮退する
(`GET /api/agent/status` の ``available`` フィールド)。

**会話継続方式**: ターンごとに ``claude_agent_sdk.query()`` (stateless one-shot) を呼び、直前ターンの
``ResultMessage.session_id`` を次ターンの ``ClaudeAgentOptions.resume`` に渡すことで会話を継続する
(``ClaudeSDKClient`` を保持し続ける常駐イベントループより単純で、``send()`` ごとに独立した
バックグラウンドスレッド + ``asyncio.run`` で完結させられる)。
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import agent_mcp

#: SDK 既定 (ClaudeAgentOptions.max_turns=None) はドキュメント上「無制限」なので、暴走を避け
#: 明示的な既定値を持つ (`~/.tsumugin/agent.json` で上書き可)。
_DEFAULT_MAX_TURNS = 25


def _default_config_path() -> Path:
    """``~/.tsumugin/agent.json`` — 呼び出し時に都度 ``Path.home()`` を解決する。

    モジュール import 時に 1 度だけ評価する定数にすると、テストの ``Path.home()`` monkeypatch
    (`tests/workbench/conftest.py` の autouse ``_isolated_home``) より先に固定されてしまい、
    テスト間で実ホームの状態に依存する恐れがある — 呼び出し時解決にして隔離を効かせる。
    """
    return Path.home() / ".tsumugin" / "agent.json"

_SYSTEM_PROMPT_HEADER = (
    "あなたは Tsumugin workbench の ③ 層 (自律実行エージェント) です。"
    "利用できる手段は MCP サーバ \"tsumugin\" が公開するツールのみで、読み取り系 "
    "(get_state/get_viewmodel/get_ledger/job_status) とジョブ起動系 "
    "(run_refine/run_sequential/run_phaseid/run_multistart/run_echem) に限られます。"
    "承認 (approval) の解決・レビュー (review) の解決・構造 (structure) の適用・"
    "プロジェクト設定の変更を行うツールは存在しません — それらは人間専用です。"
    "必要と考える場合は、実行するのではなく提案としてテキストで述べてください (提案 ≠ 適用)。"
)

#: tokens 集計に使う usage キー ($ は保持しない、FR-404)。
#: 【実測で確定】: ``ResultMessage.usage``/``AssistantMessage.usage`` は Anthropic Messages API の
#: 生 usage オブジェクトそのもの (snake_case: ``input_tokens``/``output_tokens``/...) であり、
#: ``claude_agent_sdk.ModelUsage`` (camelCase, ``model_usage`` per-model 内訳用の別スキーマ) とは
#: 異なる。実 CLI 疎通 (`tests/workbench/test_agent_bridge.py::test_real_cli_single_turn_reports_state`,
#: `@pytest.mark.agent`) で camelCase 版が常に 0 token を集計してしまう欠陥として発覚し、ここへ
#: 修正した — gated テストが無ければ気付けなかった実害。
_TOKEN_USAGE_KEYS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


def _load_agent_config(path: Path) -> dict[str, Any]:
    """``~/.tsumugin/agent.json`` (任意) を読む。無い/壊れている場合は空 dict (既定値を使う)。"""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _sdk_available() -> bool:
    try:
        import claude_agent_sdk  # noqa: F401
    except ImportError:
        return False
    return True


def _content_to_text(content: Any) -> str:
    """``ToolResultBlock.content`` (str または content block のリスト) を表示用テキストへ畳む。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text", item)))
            else:
                parts.append(str(getattr(item, "text", item)))
        return "\n".join(parts)
    return str(content)


def _strip_server_prefix(name: str) -> str:
    prefix = f"mcp__{agent_mcp.SERVER_NAME}__"
    return name[len(prefix) :] if name.startswith(prefix) else name


class AgentBridge:
    """1 workbench セッションに束縛された AUTO 実 LLM ブリッジ (可変・スレッドセーフ)。

    ``send(text)`` はバックグラウンドスレッドでエージェントの 1 ターンを実行し、即座に戻る
    (非同期実行, api-contract.md)。実行中の重複 ``send`` は ``False`` を返す (呼び出し側が 409 へ縮退)。
    イベント (テキスト/ツール呼び出し) は ``on_event`` コールバック経由で呼び出し側の transcript
    ストアへ逐次 append される。
    """

    def __init__(
        self,
        *,
        on_event: "Callable[..., dict[str, Any]]",
        get_state_summary: "Callable[[], dict[str, Any]] | None" = None,
        query_fn: "Callable[..., Any] | None" = None,
        config_path: "Path | None" = None,
    ) -> None:
        """
        :param on_event: ``(kind: str, **fields) -> dict`` — transcript へ 1 行 append し、
            append 済みの (可変) row dict を返す callable。呼び出し側 (`WorkbenchSession`) が
            スレッドセーフに実装する。
        :param get_state_summary: システムプロンプトに埋め込む現在の state 要約を返す callable
            (``WorkbenchSession.state`` を渡す想定)。``None`` なら要約なし。
        :param query_fn: **テスト専用**の SDK ``query`` 差し替えシーム。``None`` (既定) は実行時に
            ``claude_agent_sdk.query`` を遅延 import する。注入時は SDK 型 (``ClaudeAgentOptions``)
            を一切構築せず、プレーンな dict を ``options`` として渡す (フェイク側は中身を見ない)。
        :param config_path: ``~/.tsumugin/agent.json`` の代わりに読む設定ファイル (テスト用)。
        """
        self._on_event = on_event
        self._get_state_summary = get_state_summary
        self._query_fn = query_fn
        self._config = _load_agent_config(config_path if config_path is not None else _default_config_path())
        self._injected = query_fn is not None

        self._lock = threading.Lock()
        self._status = "idle"
        self._error: "str | None" = None
        self._tokens = 0
        self._wall_time_s = 0.0
        self._session_id: "str | None" = None

    # ------------------------------------------------------------------
    # GET /api/agent/status
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """CLI/SDK が利用可能か (テスト注入時は常に True)。"""
        return True if self._injected else _sdk_available()

    def status(self) -> dict[str, Any]:
        """``{"status", "available", "tokens", "wall_time_s", "error"}`` (api-contract.md)。"""
        with self._lock:
            return {
                "status": self._status,
                "available": self.available,
                "tokens": self._tokens,
                "wall_time_s": self._wall_time_s,
                "error": self._error,
            }

    # ------------------------------------------------------------------
    # POST /api/transcript/message (mode=auto かつ available 時)
    # ------------------------------------------------------------------

    def send(self, text: str) -> bool:
        """エージェントの 1 ターンをバックグラウンドスレッドで開始する。

        実行中 (``status == "running"``) なら何もせず ``False`` (呼び出し側が 409 へ縮退)。
        """
        with self._lock:
            if self._status == "running":
                return False
            self._status = "running"
            self._error = None
        thread = threading.Thread(target=self._run_thread, args=(text,), daemon=True)
        thread.start()
        return True

    # ------------------------------------------------------------------
    # 内部実装
    # ------------------------------------------------------------------

    def _run_thread(self, text: str) -> None:
        try:
            asyncio.run(self._run_turn(text))
        except Exception as exc:  # ③ は LLM 境界外 — 例外は貫通させず failed へ縮退する
            with self._lock:
                self._status = "failed"
                self._error = str(exc)
            return
        with self._lock:
            self._status = "idle"

    async def _run_turn(self, text: str) -> None:
        query_fn = self._query_fn
        if query_fn is None:
            from claude_agent_sdk import query as _real_query

            query_fn = _real_query
        options = self._build_options()
        pending_tools: "dict[str, dict[str, Any]]" = {}
        tool_started_at: "dict[str, float]" = {}
        turn_error: "str | None" = None
        async for message in query_fn(prompt=text, options=options):
            error = self._handle_message(message, pending_tools, tool_started_at)
            if error is not None:
                turn_error = error
        if turn_error is not None:
            raise RuntimeError(turn_error)

    def _build_system_prompt(self) -> str:
        prompt = _SYSTEM_PROMPT_HEADER
        if self._get_state_summary is not None:
            try:
                summary = self._get_state_summary()
            except Exception:
                summary = None
            if summary is not None:
                prompt = f"{prompt}\n\n現在の state 要約:\n{json.dumps(summary, ensure_ascii=False, default=str)}"
        return prompt

    def _build_options(self) -> Any:
        """``ClaudeAgentOptions`` (実行時) または注入テスト用のプレーン dict を構築する。"""
        if self._injected:
            # 【テスト注入経路】: フェイク query_fn は options の中身を実際には解釈しないため、
            #   実 SDK 型 (claude_agent_sdk/mcp 依存) を組み立てない。resume/system_prompt は
            #   テストが検証できるようそのまま入れておく。
            return {
                "system_prompt": self._build_system_prompt(),
                "resume": self._session_id,
                "max_turns": int(self._config.get("max_turns", _DEFAULT_MAX_TURNS)),
            }
        from claude_agent_sdk import ClaudeAgentOptions

        kwargs: dict[str, Any] = {
            "system_prompt": self._build_system_prompt(),
            "mcp_servers": {agent_mcp.SERVER_NAME: agent_mcp.build_server()},
            "allowed_tools": agent_mcp.allowed_tool_ids(),
            # 【bypassPermissions】: shim のツール表自体が権限境界 (承認/レビュー/構造/project は
            #   非公開) なので、CLI 側の対話的許可プロンプトは不要かつ非対話実行では単にハング
            #   する。既に安全なツール集合に絞られている前提で許可を素通しする。
            "permission_mode": "bypassPermissions",
            "max_turns": int(self._config.get("max_turns", _DEFAULT_MAX_TURNS)),
        }
        model = self._config.get("model")
        if model:
            kwargs["model"] = model
        if self._session_id:
            kwargs["resume"] = self._session_id
        return ClaudeAgentOptions(**kwargs)

    def _handle_message(
        self,
        message: Any,
        pending_tools: "dict[str, dict[str, Any]]",
        tool_started_at: "dict[str, float]",
    ) -> "str | None":
        """1 メッセージを transcript へ写像する。エラーがあれば理由文字列を返す (それ以外 None)。"""
        cls_name = type(message).__name__
        if cls_name == "AssistantMessage":
            self._handle_assistant_message(message, pending_tools, tool_started_at)
            return None
        if cls_name == "UserMessage":
            self._handle_user_message(message, pending_tools, tool_started_at)
            return None
        if cls_name == "ResultMessage":
            return self._handle_result_message(message)
        return None

    def _handle_assistant_message(
        self,
        message: Any,
        pending_tools: "dict[str, dict[str, Any]]",
        tool_started_at: "dict[str, float]",
    ) -> None:
        for block in getattr(message, "content", None) or []:
            block_name = type(block).__name__
            if block_name == "TextBlock":
                text = getattr(block, "text", "")
                if text:
                    self._on_event("agent", text=text)
            elif block_name == "ToolUseBlock":
                tool_id = getattr(block, "id", "")
                tool_name = _strip_server_prefix(getattr(block, "name", ""))
                args_json = json.dumps(getattr(block, "input", {}) or {}, ensure_ascii=False, default=str)
                row = self._on_event("tool", tool=tool_name, layer="MCP ②", args=args_json)
                pending_tools[tool_id] = row
                tool_started_at[tool_id] = time.monotonic()

    def _handle_user_message(
        self,
        message: Any,
        pending_tools: "dict[str, dict[str, Any]]",
        tool_started_at: "dict[str, float]",
    ) -> None:
        for block in getattr(message, "content", None) or []:
            if type(block).__name__ != "ToolResultBlock":
                continue
            tool_id = getattr(block, "tool_use_id", "")
            row = pending_tools.pop(tool_id, None)
            if row is None:
                continue
            row["ret"] = _content_to_text(getattr(block, "content", None))
            started = tool_started_at.pop(tool_id, None)
            if started is not None:
                row["secs"] = round(time.monotonic() - started, 3)

    def _handle_result_message(self, message: Any) -> "str | None":
        usage = getattr(message, "usage", None) or {}
        delta = 0
        if isinstance(usage, dict):
            delta = sum(int(usage.get(k) or 0) for k in _TOKEN_USAGE_KEYS)
        duration_ms = getattr(message, "duration_ms", 0) or 0
        session_id = getattr(message, "session_id", None)
        with self._lock:
            self._tokens += delta
            self._wall_time_s += float(duration_ms) / 1000.0
        if session_id:
            self._session_id = session_id
        if getattr(message, "is_error", False):
            return str(getattr(message, "result", None) or "agent turn failed")
        return None
