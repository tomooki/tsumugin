"""AUTO 実 LLM ブリッジ (V3a) の MCP shim — `docs/design/gui-workbench/api-contract.md`
§AUTO 実 LLM ブリッジ。

エージェント (ローカル `claude` CLI, claude-agent-sdk 経由) が唯一到達できる MCP サーバ。
公開するのは読み取り (state/viewmodel/ledger/status 系) と SafeAction 級のジョブ起動
(refine/sequential/phaseid/multistart/echem) のみ — **これが権限境界の単一情報源**であり、
approval/review/structure/project 変更系は一切公開しない (人間専用, 提案≠適用)。

実装は workbench 自身の HTTP API (``http://127.0.0.1:{TSUMUGIN_WORKBENCH_PORT}``) を叩くだけの
薄いアダプタ: エージェントは人間の GUI と全く同じ custody ガード (ledger/409/422) を通る。

**SDK 非依存 import**: 本モジュールのトップレベルは ``claude_agent_sdk``/``mcp`` を import しない
(未導入環境でも ``import tsumugin.workbench.agent_mcp`` 自体は成功する)。実際に SDK 型が要る
``build_tools``/``build_server`` の呼び出し時点でのみ遅延 import する。
"""

from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable

#: サーバ名 (ClaudeAgentOptions.mcp_servers のキー / allowed_tools の `mcp__<name>__<tool>` 接頭辞)。
SERVER_NAME = "tsumugin"

#: 【権限境界の単一情報源, FR-402, 変更禁止】: shim が公開するツール名の全体集合。
#: approval/review/structure/project 変更系をここに追加しない — 追加すると
#: `tests/workbench/test_agent_mcp.py` のガードが fail する (変異実証済み)。
ALLOWED_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "get_state",
        "get_viewmodel",
        "get_ledger",
        "job_status",
        "run_refine",
        "run_sequential",
        "run_phaseid",
        "run_multistart",
        "run_echem",
    }
)

#: 到達不能な (=人間専用の) カテゴリを表す語幹。ツール名にこれらが部分文字列として現れないことを
#: `test_agent_mcp.py::test_no_forbidden_tool_categories` がガードする。
_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "approval",
    "review",
    "structure",
    "project",
    "revert",
    "accept",
    "resolve",
)

_HTTP_TIMEOUT_S = 60.0


def _base_url() -> str:
    """workbench HTTP API のベース URL。ポートは env ``TSUMUGIN_WORKBENCH_PORT`` から解決する。"""
    port = os.environ.get("TSUMUGIN_WORKBENCH_PORT", "8770")
    return f"http://127.0.0.1:{port}"


def _request(method: str, path: str, payload: "dict[str, Any] | None" = None) -> dict[str, Any]:
    """workbench HTTP API を 1 回呼び出す (同期・stdlib のみ)。

    例外を送出しない — ネットワーク/HTTP エラーは ``{"status": None|code, "body": ..., "error": ...}``
    へ縮退する (② は例外を送出しない、`app.py` `_unhandled_exception_handler` docstring と同じ流儀)。
    """
    url = _base_url() + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:
            raw = resp.read().decode("utf-8")
            body = json.loads(raw) if raw else None
            return {"status": resp.status, "body": body}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8") if exc.fp is not None else ""
        try:
            body = json.loads(raw) if raw else None
        except json.JSONDecodeError:
            body = raw
        return {"status": exc.code, "body": body}
    except urllib.error.URLError as exc:
        return {"status": None, "body": None, "error": str(exc.reason)}


def _tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    """MCP ``CallToolResult`` 形 (content: [{"type": "text", "text": ...}]) へ変換する。"""
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, default=str)}]}


def _strip_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# ツールハンドラ (プレーンな async 関数。@tool 装飾は build_tools() で遅延適用する)
# ---------------------------------------------------------------------------


async def _h_get_state(_args: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(await asyncio.to_thread(_request, "GET", "/api/state"))


async def _h_get_viewmodel(_args: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(await asyncio.to_thread(_request, "GET", "/api/viewmodel"))


async def _h_get_ledger(_args: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(await asyncio.to_thread(_request, "GET", "/api/ledger"))


async def _h_job_status(_args: dict[str, Any]) -> dict[str, Any]:
    """共有ジョブ枠 (refine/phaseid/multistart) の状態 (`GET /api/refine/status` と同形)。"""
    return _tool_result(await asyncio.to_thread(_request, "GET", "/api/refine/status"))


async def _h_run_refine(args: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_none({"stages_on": args.get("stages_on")})
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/refine", payload))


async def _h_run_sequential(args: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_none(
        {
            "mode": args.get("mode", "forward"),
            "anchor_table": args.get("anchor_table"),
            "use_charge_constraint": args.get("use_charge_constraint"),
        }
    )
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/sequential", payload))


async def _h_run_phaseid(args: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_none({"mode": args.get("mode", "pattern"), "top_k": args.get("top_k")})
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/phaseid", payload))


async def _h_run_multistart(args: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_none({"n_starts": args.get("n_starts"), "scale": args.get("scale")})
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/multistart", payload))


async def _h_run_echem(args: dict[str, Any]) -> dict[str, Any]:
    payload = _strip_none(
        {
            "mpr_path": args.get("mpr_path"),
            "offset_s": args.get("offset_s"),
            "interval_s": args.get("interval_s"),
            "n_frames": args.get("n_frames"),
            "frame_epoch_s": args.get("frame_epoch_s"),
            "sign": args.get("sign"),
            "x0": args.get("x0"),
            "active_mass_mg": args.get("active_mass_mg"),
            "formula_weight": args.get("formula_weight"),
            "z": args.get("z"),
            "x0_source": args.get("x0_source"),
            "clamp": args.get("clamp"),
        }
    )
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/echem", payload))


_EMPTY_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

#: (name, description, JSON Schema, handler) — §4.5 到達可能性: 各引数はすべて JSON リテラル
#: (workbench API の JSON body フィールドそのもの) であり、他ツール出力から機械的に組み立てられる
#: か、エージェントが直接指定できるプリミティブのみ。callable 引数は無い。
_TOOL_SPECS: "tuple[tuple[str, str, dict[str, Any], Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]], ...]" = (
    ("get_state", "workbench GET /api/state を取得する (read-only)。", _EMPTY_SCHEMA, _h_get_state),
    (
        "get_viewmodel",
        "workbench GET /api/viewmodel を取得する (read-only)。",
        _EMPTY_SCHEMA,
        _h_get_viewmodel,
    ),
    (
        "get_ledger",
        "workbench GET /api/ledger (追記専用の監査ログ) を取得する (read-only)。",
        _EMPTY_SCHEMA,
        _h_get_ledger,
    ),
    (
        "job_status",
        "共有ジョブ枠 (refine/phaseid/multistart のうち直近に動いたもの) の状態を取得する "
        "(read-only, GET /api/refine/status と同形)。",
        _EMPTY_SCHEMA,
        _h_job_status,
    ),
    (
        "run_refine",
        "実 Rietveld 精密化ジョブを起動する (POST /api/refine)。実行中は 409 で拒否される。",
        {
            "type": "object",
            "properties": {
                "stages_on": {
                    "type": "object",
                    "description": "段階 nn (\"01\".. ) → 解放するか。省略時は全段既定。",
                }
            },
            "required": [],
        },
        _h_run_refine,
    ),
    (
        "run_sequential",
        "逐次/operando 精密化ジョブを起動する (POST /api/sequential)。frames 未設定は 422。",
        {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["forward", "anchored"]},
                "anchor_table": {
                    "type": "object",
                    "description": "{frame_index: [phase_name, ...]} (mode=anchored 用)。",
                },
                "use_charge_constraint": {"type": "boolean"},
            },
            "required": [],
        },
        _h_run_sequential,
    ),
    (
        "run_phaseid",
        "相同定ジョブを起動する (POST /api/phaseid)。MATERIALS_PROJECT_API 未設定は 422。",
        {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["pattern", "residual"]},
                "top_k": {"type": "integer"},
            },
            "required": [],
        },
        _h_run_phaseid,
    ),
    (
        "run_multistart",
        "マルチスタート大域最適確認ジョブを起動する (POST /api/multistart)。",
        {
            "type": "object",
            "properties": {
                "n_starts": {"type": "integer"},
                "scale": {"type": "number"},
            },
            "required": [],
        },
        _h_run_multistart,
    ),
    (
        "run_echem",
        "電気化学同期 (align_echem + alkali_budget) を実行する (POST /api/echem, 同期実行)。",
        {
            "type": "object",
            "properties": {
                "mpr_path": {"type": "string"},
                "offset_s": {"type": "number"},
                "interval_s": {"type": "number"},
                "n_frames": {"type": "integer"},
                "frame_epoch_s": {"type": "number"},
                "sign": {"type": "integer", "enum": [1, -1]},
                "x0": {"type": "number"},
                "active_mass_mg": {"type": "number"},
                "formula_weight": {"type": "number"},
                "z": {"type": "integer"},
                "x0_source": {"type": "string"},
                "clamp": {"type": "boolean"},
            },
            "required": ["mpr_path"],
        },
        _h_run_echem,
    ),
)


def build_tools() -> "list[Any]":
    """``claude_agent_sdk.tool`` で装飾した ``SdkMcpTool`` のリストを構築する (遅延 import)。"""
    from claude_agent_sdk import tool

    return [tool(name, description, schema)(handler) for name, description, schema, handler in _TOOL_SPECS]


def build_server() -> Any:
    """``ClaudeAgentOptions.mcp_servers`` に渡す in-process SDK MCP server を構築する (遅延 import)。"""
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(name=SERVER_NAME, tools=build_tools())


def allowed_tool_ids() -> "list[str]":
    """``ClaudeAgentOptions.allowed_tools`` 用の完全修飾ツール名 (``mcp__<server>__<tool>``)。"""
    return [f"mcp__{SERVER_NAME}__{name}" for name in sorted(ALLOWED_TOOL_NAMES)]
