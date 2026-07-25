"""`tsumugin.workbench.agent_mcp` — V3a MCP shim の権限境界ガード + HTTP 委譲テスト。

権限境界 (api-contract.md §AUTO 実 LLM ブリッジ, FR-402, 変更禁止) はこのモジュールが公開する
ツール名の集合が単一情報源。approval/review/structure/project 変更系を足す変異で fail することを
実証する (`test_forbidden_marker_check_flags_a_mutated_tool_name` / `test_no_forbidden_tool_categories`)。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from tsumugin.workbench import agent_mcp

_EXPECTED_TOOL_NAMES = frozenset(
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


# ---------------------------------------------------------------------------
# 権限境界 (単一情報源)
# ---------------------------------------------------------------------------


def test_allowed_tool_names_match_permission_boundary():
    assert agent_mcp.ALLOWED_TOOL_NAMES == _EXPECTED_TOOL_NAMES


def test_tool_specs_names_match_allowed_tool_names():
    """_TOOL_SPECS (実装) と ALLOWED_TOOL_NAMES (契約) がずれていないこと。"""
    spec_names = {spec[0] for spec in agent_mcp._TOOL_SPECS}
    assert spec_names == agent_mcp.ALLOWED_TOOL_NAMES


def test_no_forbidden_tool_categories():
    """approval/review/structure/project/revert/accept/resolve を含む名前が無いこと。"""
    for name in agent_mcp.ALLOWED_TOOL_NAMES:
        assert not any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS), name


def test_forbidden_marker_check_flags_a_mutated_tool_name():
    """変異実証: 禁止カテゴリのツール名が紛れ込んだ場合、境界チェックが検知することを確認する。"""
    mutated = frozenset(agent_mcp.ALLOWED_TOOL_NAMES | {"resolve_approval", "apply_structure"})
    violations = sorted(
        name for name in mutated if any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS)
    )
    assert violations == ["apply_structure", "resolve_approval"]


def test_allowed_tool_ids_use_mcp_prefix_and_cover_all_names():
    ids = agent_mcp.allowed_tool_ids()
    assert len(ids) == len(agent_mcp.ALLOWED_TOOL_NAMES)
    for tool_id in ids:
        assert tool_id.startswith(f"mcp__{agent_mcp.SERVER_NAME}__")
        assert tool_id[len(f"mcp__{agent_mcp.SERVER_NAME}__") :] in agent_mcp.ALLOWED_TOOL_NAMES


# ---------------------------------------------------------------------------
# HTTP 委譲 (workbench 自身の API を叩くだけの薄いアダプタ)
# ---------------------------------------------------------------------------


def test_get_state_handler_calls_expected_path(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"status": 200, "body": {"mode": "manual"}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    result = asyncio.run(agent_mcp._h_get_state({}))
    assert calls == [("GET", "/api/state", None)]
    payload = json.loads(result["content"][0]["text"])
    assert payload == {"status": 200, "body": {"mode": "manual"}}


def test_run_refine_handler_passes_stages_on(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"status": 202, "body": {"status": "started"}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_run_refine({"stages_on": {"01": False}}))
    assert captured == {
        "method": "POST",
        "path": "/api/refine",
        "payload": {"stages_on": {"01": False}},
    }


def test_run_refine_handler_omits_absent_stages_on(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["payload"] = payload
        return {"status": 202, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_run_refine({}))
    assert captured["payload"] == {}


def test_run_echem_handler_requires_mpr_path_pass_through(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["payload"] = payload
        return {"status": 200, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_run_echem({"mpr_path": "x.mpr", "sign": -1}))
    assert captured["payload"] == {"mpr_path": "x.mpr", "sign": -1}


def test_base_url_uses_env_port(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TSUMUGIN_WORKBENCH_PORT", "9999")
    assert agent_mcp._base_url() == "http://127.0.0.1:9999"
    monkeypatch.delenv("TSUMUGIN_WORKBENCH_PORT", raising=False)
    assert agent_mcp._base_url() == "http://127.0.0.1:8770"


# ---------------------------------------------------------------------------
# SDK 型構築 (claude_agent_sdk 導入時のみ)
# ---------------------------------------------------------------------------


def test_build_tools_and_server_smoke():
    pytest.importorskip("claude_agent_sdk")
    tools = agent_mcp.build_tools()
    assert {t.name for t in tools} == agent_mcp.ALLOWED_TOOL_NAMES
    server = agent_mcp.build_server()
    assert server["name"] == agent_mcp.SERVER_NAME
    assert server["type"] == "sdk"
