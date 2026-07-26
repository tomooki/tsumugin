"""AUTO 実 LLM ブリッジ (V3a) の MCP shim — `docs/design/gui-workbench/api-contract.md`
§AUTO 実 LLM ブリッジ。

エージェント (ローカル `claude` CLI, claude-agent-sdk 経由) が唯一到達できる MCP サーバ。
公開するのは読み取り (state/viewmodel/ledger/status 系) と SafeAction 級のジョブ起動
(refine/sequential/phaseid/multistart/echem) に加え、ModelAction を「起票」するだけの
`propose_*` ツール (構造改訂/レビュー解決/相変更/設定変更 — 承認カードを作るのみで実行しない) —
**これが権限境界の単一情報源**である (2026-07-26 権限境界改訂)。承認の解決 (自己承認) と
project ライフサイクル (create/open/close/demo) だけは絶対に公開しない (人間専用, 提案≠適用)。

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

#: 【権限境界の単一情報源, FR-402, 変更禁止 (2026-07-26 権限境界改訂)】: shim が公開するツール名の
#: 全体集合。SafeAction (読み取り + ジョブ起動) に加え、ModelAction を「起票」するだけの
#: `propose_*` ツール (承認カードを作るのみ・実行しない) を公開する。承認解決 (自己承認) と
#: project ライフサイクルはここに追加しない — 追加すると `tests/workbench/test_agent_mcp.py` の
#: ガードが fail する (変異実証済み)。
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
        "propose_structure_revision",
        "propose_review_resolution",
        "propose_phase_change",
        "propose_settings_change",
        "list_pending_approvals",
    }
)

#: 【エージェント権限モード, 2026-07-26 権限境界改訂】: ``agent_policy="bypass"`` のときのみ
#: ``ALLOWED_TOOL_NAMES`` に追加公開する project ライフサイクル 4 本 (api-contract.md
#: §エージェント権限モード「bypass: project ライフサイクルもエージェントに開放」)。``approve``/
#: ``auto`` では従来どおり ``ALLOWED_TOOL_NAMES`` のみ (このツール表は増えない) — `allowed_tool_names`
#: が policy に応じてどちらを合成するかを一元管理する (単一情報源)。
BYPASS_ONLY_TOOL_NAMES: frozenset[str] = frozenset(
    {"open_project", "close_project", "create_project", "demo_project"}
)

#: 到達不能な (=人間専用の) 直接実行操作を表す語幹。**``ALLOWED_TOOL_NAMES`` (常設 14 本, 全 policy
#: 共通の基底集合) にのみ適用する** — `test_agent_mcp.py::test_no_forbidden_tool_categories` が
#: ガードする。**broad な名詞 ("structure"/"review"/"approval" 等) ではなく直接実行を指す具体的な
#: 動詞トークンを列挙する** (2026-07-26 改訂): `propose_structure_revision`/
#: `propose_review_resolution`/`list_pending_approvals` は「起票/読み取り」であり実行そのものでは
#: ないため、意図的にこの集合の対象外 — 一方で `apply_structure`/`resolve_review`/
#: `resolve_approval`/`add_phase`/`remove_phase`/`update_settings` (直接実行) や
#: `open_project`/`close_project`/`create_project`/`demo_project` (セッション/ledger のすり替え) が
#: 紛れ込めば検知する。**``BYPASS_ONLY_TOOL_NAMES`` は意図的にこれらの語幹そのものを名前に持つ**
#: (bypass 限定で project ライフサイクルを開放する設計) ため、この集合を ``allowed_tool_names(
#: "bypass")`` の結果へ適用してはならない — bypass の絶対境界チェックは ``_SELF_ESCALATION_MARKERS``
#: (自己承認 + 自己昇格のみ、project ライフサイクルは含まない) を使う。
_FORBIDDEN_MARKERS: tuple[str, ...] = (
    "approve",
    "reject",
    "resolve_approval",
    "resolve_review",
    "apply_structure",
    "add_phase",
    "remove_phase",
    "update_settings",
    "open_project",
    "close_project",
    "create_project",
    "demo_project",
    "revert",
    "accept",
)

#: 【絶対境界, 全 policy 共通 (2026-07-26 権限境界改訂)】: ``bypass`` を含む**どの policy でも**
#: 現れてはならない語幹 — 承認の自己解決 (自己承認の禁止) と ``agent_policy`` 自体の自己変更
#: (自己昇格の禁止) のみを指す。`_FORBIDDEN_MARKERS` と異なり project ライフサイクル語幹は含めない
#: (bypass ではそれ自体が意図的に許可される)。`test_agent_mcp.py` の policy 別テストがこれを
#: ``allowed_tool_names("approve"|"auto"|"bypass")`` それぞれへ適用する。
_SELF_ESCALATION_MARKERS: tuple[str, ...] = (
    "approve",
    "reject",
    "resolve_approval",
    "resolve_review",
    "agent_policy",
    "set_policy",
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


async def _h_propose_structure_revision(args: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "kind": "structure_revision",
        "payload": {"sites": args.get("sites")},
        "rationale": args.get("rationale", ""),
    }
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/proposals", payload))


async def _h_propose_review_resolution(args: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "kind": "review_resolution",
        "payload": {"item_id": args.get("item_id"), "action": args.get("action")},
        "rationale": args.get("rationale", ""),
    }
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/proposals", payload))


async def _h_propose_phase_change(args: dict[str, Any]) -> dict[str, Any]:
    inner = _strip_none(
        {
            "op": args.get("op"),
            "phase_name": args.get("phase_name"),
            "structure_path": args.get("structure_path"),
        }
    )
    payload = {"kind": "phase_change", "payload": inner, "rationale": args.get("rationale", "")}
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/proposals", payload))


async def _h_propose_settings_change(args: dict[str, Any]) -> dict[str, Any]:
    inner = _strip_none(
        {
            "two_theta_limits": args.get("two_theta_limits"),
            "background_coeffs": args.get("background_coeffs"),
            "max_cyc": args.get("max_cyc"),
        }
    )
    payload = {"kind": "settings_change", "payload": inner, "rationale": args.get("rationale", "")}
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/proposals", payload))


async def _h_list_pending_approvals(_args: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(await asyncio.to_thread(_request, "GET", "/api/proposals"))


# ---------------------------------------------------------------------------
# bypass 限定: project ライフサイクル (2026-07-26 権限境界改訂)
# ---------------------------------------------------------------------------


async def _h_open_project(args: dict[str, Any]) -> dict[str, Any]:
    payload = {"path": args.get("path")}
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/project/open", payload))


async def _h_close_project(_args: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/project/close", {}))


async def _h_create_project(args: dict[str, Any]) -> dict[str, Any]:
    payload = {"name": args.get("name"), "directory": args.get("directory")}
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/project", payload))


async def _h_demo_project(_args: dict[str, Any]) -> dict[str, Any]:
    return _tool_result(await asyncio.to_thread(_request, "POST", "/api/project/demo", {}))


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
    (
        "propose_structure_revision",
        "構造改訂 (ReviseStructure) を起票する — 承認カードを作るだけで、適用は人間の承認後に "
        "実行される (POST /api/proposals, kind=structure_revision)。sites は "
        "get_viewmodel().structure.sites から作ること。",
        {
            "type": "object",
            "properties": {
                "sites": {
                    "type": "array",
                    "description": "get_viewmodel().structure.sites 形の改訂後サイト列。",
                    "items": {"type": "object"},
                },
                "rationale": {"type": "string", "description": "起票理由 (承認カードに表示)。"},
            },
            "required": ["sites", "rationale"],
        },
        _h_propose_structure_revision,
    ),
    (
        "propose_review_resolution",
        "レビューキュー項目の解決を起票する (POST /api/proposals, kind=review_resolution)。"
        "item_id は get_viewmodel().review[].id から作ること。",
        {
            "type": "object",
            "properties": {
                "item_id": {"type": "string"},
                "action": {"type": "string", "enum": ["accept", "send_back"]},
                "rationale": {"type": "string"},
            },
            "required": ["item_id", "action", "rationale"],
        },
        _h_propose_review_resolution,
    ),
    (
        "propose_phase_change",
        "相の追加/除去を起票する (POST /api/proposals, kind=phase_change)。phase_name は "
        "op=remove のとき get_viewmodel().project.phases[].name から作ること。",
        {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": ["add", "remove"]},
                "phase_name": {"type": "string"},
                "structure_path": {
                    "type": "string",
                    "description": "op=add で必須 (CIF/EXP パス)。",
                },
                "rationale": {"type": "string"},
            },
            "required": ["op", "phase_name", "rationale"],
        },
        _h_propose_phase_change,
    ),
    (
        "propose_settings_change",
        "精密化設定 (2θ範囲/背景項数/max_cyc) の変更を起票する "
        "(POST /api/proposals, kind=settings_change)。",
        {
            "type": "object",
            "properties": {
                "two_theta_limits": {
                    "type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2,
                },
                "background_coeffs": {"type": "integer"},
                "max_cyc": {"type": "integer"},
                "rationale": {"type": "string"},
            },
            "required": ["rationale"],
        },
        _h_propose_settings_change,
    ),
    (
        "list_pending_approvals",
        "自分 (または他の起票元) が作った承認待ちカードの一覧を取得する (read-only, "
        "GET /api/proposals)。承認自体はこのツールではできない。",
        _EMPTY_SCHEMA,
        _h_list_pending_approvals,
    ),
    # 【bypass 限定, BYPASS_ONLY_TOOL_NAMES】: build_tools(policy="bypass") のときのみ公開される。
    (
        "open_project",
        "既存プロジェクトを開く (POST /api/project/open)。agent_policy=bypass 限定。",
        {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
        _h_open_project,
    ),
    (
        "close_project",
        "現在のプロジェクトを閉じる (POST /api/project/close, source=none へ)。"
        "agent_policy=bypass 限定。",
        _EMPTY_SCHEMA,
        _h_close_project,
    ),
    (
        "create_project",
        "新規プロジェクトを作成する (POST /api/project)。agent_policy=bypass 限定。",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "directory": {"type": "string"}},
            "required": ["name", "directory"],
        },
        _h_create_project,
    ),
    (
        "demo_project",
        "シードのデモセッションへ切り替える (POST /api/project/demo)。agent_policy=bypass 限定。",
        _EMPTY_SCHEMA,
        _h_demo_project,
    ),
)


def allowed_tool_names(policy: str = "approve") -> "frozenset[str]":
    """``agent_policy`` (``"approve"|"auto"|"bypass"``) に応じたツール名集合の単一情報源。

    ``bypass`` のときのみ ``BYPASS_ONLY_TOOL_NAMES`` (project ライフサイクル 4 本) を追加する
    (api-contract.md §エージェント権限モード)。``approve``/``auto`` は ``ALLOWED_TOOL_NAMES`` の
    まま変わらない — ModelAction の即時適用の有無 (`WorkbenchSession.create_proposal` が分岐) は
    ツール表とは独立した挙動であり、ここでは扱わない。
    """
    if policy == "bypass":
        return ALLOWED_TOOL_NAMES | BYPASS_ONLY_TOOL_NAMES
    return ALLOWED_TOOL_NAMES


def build_tools(policy: str = "approve") -> "list[Any]":
    """``claude_agent_sdk.tool`` で装飾した ``SdkMcpTool`` のリストを構築する (遅延 import)。

    ``policy`` に応じて ``allowed_tool_names(policy)`` に含まれる分だけを ``_TOOL_SPECS`` から
    抽出する (bypass だけ project ライフサイクル 4 本が加わる)。
    """
    from claude_agent_sdk import tool

    names = allowed_tool_names(policy)
    return [
        tool(name, description, schema)(handler)
        for name, description, schema, handler in _TOOL_SPECS
        if name in names
    ]


def build_server(policy: str = "approve") -> Any:
    """``ClaudeAgentOptions.mcp_servers`` に渡す in-process SDK MCP server を構築する (遅延 import)。"""
    from claude_agent_sdk import create_sdk_mcp_server

    return create_sdk_mcp_server(name=SERVER_NAME, tools=build_tools(policy))


def allowed_tool_ids(policy: str = "approve") -> "list[str]":
    """``ClaudeAgentOptions.allowed_tools`` 用の完全修飾ツール名 (``mcp__<server>__<tool>``)。"""
    return [f"mcp__{SERVER_NAME}__{name}" for name in sorted(allowed_tool_names(policy))]
