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
        "run_mem",
        "propose_structure_revision",
        "propose_review_resolution",
        "propose_phase_change",
        "propose_settings_change",
        "list_pending_approvals",
    }
)

_EXPECTED_BYPASS_ONLY_TOOL_NAMES = frozenset(
    {"open_project", "close_project", "create_project", "demo_project"}
)


# ---------------------------------------------------------------------------
# 権限境界 (単一情報源)
# ---------------------------------------------------------------------------


def test_allowed_tool_names_match_permission_boundary():
    assert agent_mcp.ALLOWED_TOOL_NAMES == _EXPECTED_TOOL_NAMES


def test_tool_specs_names_match_allowed_tool_names_plus_bypass_only():
    """_TOOL_SPECS (実装) は ALLOWED_TOOL_NAMES ∪ BYPASS_ONLY_TOOL_NAMES (契約) とちょうど一致する。"""
    spec_names = {spec[0] for spec in agent_mcp._TOOL_SPECS}
    assert spec_names == agent_mcp.ALLOWED_TOOL_NAMES | agent_mcp.BYPASS_ONLY_TOOL_NAMES


def test_no_forbidden_tool_categories():
    """直接実行/自己承認/project ライフサイクルを指す語幹を含む名前が無いこと。

    ``propose_structure_revision``/``propose_review_resolution``/``list_pending_approvals`` は
    意図的に "structure"/"review"/"approval" を名前に含むが、これらは「起票/読み取り」であり
    直接実行ではないため、`_FORBIDDEN_MARKERS` は broad な名詞でなく具体的な動詞トークン
    (``apply_structure``/``resolve_review``/``approve`` 等) を使う (2026-07-26 改訂)。
    """
    for name in agent_mcp.ALLOWED_TOOL_NAMES:
        assert not any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS), name


def test_propose_and_list_tools_are_allowed_despite_topic_words():
    """`propose_*`/`list_pending_approvals` は起票/読み取りであり、直接実行の弊害が無いことを明示する。"""
    for name in (
        "propose_structure_revision",
        "propose_review_resolution",
        "propose_phase_change",
        "propose_settings_change",
        "list_pending_approvals",
    ):
        assert name in agent_mcp.ALLOWED_TOOL_NAMES
        assert not any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS), name


def test_forbidden_marker_check_flags_a_mutated_tool_name():
    """変異実証: 直接実行系のツール名が紛れ込んだ場合、境界チェックが検知することを確認する。"""
    mutated = frozenset(agent_mcp.ALLOWED_TOOL_NAMES | {"resolve_approval", "apply_structure"})
    violations = sorted(
        name for name in mutated if any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS)
    )
    assert violations == ["apply_structure", "resolve_approval"]


def test_forbidden_marker_check_flags_self_approval_and_project_lifecycle_mutations():
    """変異実証: 自己承認 (approve/reject) と project ライフサイクル系ツールが紛れ込んだ場合を検知する。"""
    mutated = frozenset(
        agent_mcp.ALLOWED_TOOL_NAMES
        | {
            "approve_action",
            "reject_action",
            "open_project",
            "close_project",
            "create_project",
            "demo_project",
        }
    )
    violations = sorted(
        name for name in mutated if any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS)
    )
    assert violations == [
        "approve_action",
        "close_project",
        "create_project",
        "demo_project",
        "open_project",
        "reject_action",
    ]


def test_allowed_tool_ids_use_mcp_prefix_and_cover_all_names():
    ids = agent_mcp.allowed_tool_ids()
    assert len(ids) == len(agent_mcp.ALLOWED_TOOL_NAMES)
    for tool_id in ids:
        assert tool_id.startswith(f"mcp__{agent_mcp.SERVER_NAME}__")
        assert tool_id[len(f"mcp__{agent_mcp.SERVER_NAME}__") :] in agent_mcp.ALLOWED_TOOL_NAMES


# ---------------------------------------------------------------------------
# エージェント権限モード (agent_policy, 2026-07-26 権限境界改訂): ツール表の policy 別切替
# ---------------------------------------------------------------------------


def test_allowed_tool_names_for_approve_is_unchanged_base_set():
    assert agent_mcp.allowed_tool_names("approve") == _EXPECTED_TOOL_NAMES
    assert agent_mcp.allowed_tool_names() == _EXPECTED_TOOL_NAMES  # 既定引数も approve


def test_allowed_tool_names_for_auto_is_unchanged_base_set():
    """auto は即時適用こそするが、ツール表自体 (何を呼べるか) は approve と同一。"""
    assert agent_mcp.allowed_tool_names("auto") == _EXPECTED_TOOL_NAMES


def test_allowed_tool_names_for_bypass_adds_exactly_the_four_project_lifecycle_tools():
    assert (
        agent_mcp.allowed_tool_names("bypass")
        == _EXPECTED_TOOL_NAMES | _EXPECTED_BYPASS_ONLY_TOOL_NAMES
    )
    added = agent_mcp.allowed_tool_names("bypass") - agent_mcp.allowed_tool_names("approve")
    assert added == _EXPECTED_BYPASS_ONLY_TOOL_NAMES


def test_allowed_tool_ids_bypass_covers_all_nineteen_names():
    ids = agent_mcp.allowed_tool_ids("bypass")
    assert len(ids) == 19
    names = {tid[len(f"mcp__{agent_mcp.SERVER_NAME}__") :] for tid in ids}
    assert names == agent_mcp.allowed_tool_names("bypass")


def test_build_tools_bypass_smoke_includes_project_lifecycle_tools():
    pytest.importorskip("claude_agent_sdk")
    tools = agent_mcp.build_tools("bypass")
    assert {t.name for t in tools} == agent_mcp.allowed_tool_names("bypass")


def test_build_tools_approve_smoke_excludes_project_lifecycle_tools():
    pytest.importorskip("claude_agent_sdk")
    tools = agent_mcp.build_tools("approve")
    assert {t.name for t in tools} == _EXPECTED_TOOL_NAMES


# ---------------------------------------------------------------------------
# 絶対境界 (全 policy 共通, 変更禁止): 自己承認・自己昇格ツールは bypass でも現れない
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("policy", ["approve", "auto", "bypass"])
def test_no_self_escalation_markers_for_any_policy(policy: str):
    """(a) 承認解決ツールが存在しない・(b) agent_policy 自己変更ツールが存在しない絶対境界。

    ``bypass`` は project ライフサイクル語幹 (open_project 等) を意図的に含むため
    `_FORBIDDEN_MARKERS` はここでは使わず、承認自己解決 + policy 自己変更のみを見る
    `_SELF_ESCALATION_MARKERS` を使う (全 policy で不変)。
    """
    names = agent_mcp.allowed_tool_names(policy)
    for name in names:
        assert not any(marker in name for marker in agent_mcp._SELF_ESCALATION_MARKERS), name


def test_self_escalation_markers_mutation_flags_injected_approval_resolution_tool():
    """変異実証 (a): bypass のツール表に承認解決ツールが紛れ込んだ場合を検知する。"""
    mutated = agent_mcp.allowed_tool_names("bypass") | {"resolve_approval", "reject_approval"}
    violations = sorted(
        name for name in mutated if any(m in name for m in agent_mcp._SELF_ESCALATION_MARKERS)
    )
    assert violations == ["reject_approval", "resolve_approval"]


def test_self_escalation_markers_mutation_flags_injected_set_agent_policy_tool():
    """変異実証 (b): どの policy のツール表にも agent_policy 自己変更ツールが紛れ込んだ場合を検知する。"""
    for policy in ("approve", "auto", "bypass"):
        mutated = agent_mcp.allowed_tool_names(policy) | {"set_agent_policy"}
        violations = sorted(
            name for name in mutated if any(m in name for m in agent_mcp._SELF_ESCALATION_MARKERS)
        )
        assert violations == ["set_agent_policy"], policy


def test_forbidden_markers_still_apply_only_to_base_allowed_tool_names():
    """`_FORBIDDEN_MARKERS` (project ライフサイクル語幹込み) は base 15 (全 policy 共通部分) にのみ
    適用する不変条件 — bypass の +4 本自体にこの集合を適用すると自己矛盾で必ず fail するため、
    誤って `allowed_tool_names("bypass")` へ適用していないことを回帰ガードする。
    """
    for name in agent_mcp.ALLOWED_TOOL_NAMES:
        assert not any(marker in name for marker in agent_mcp._FORBIDDEN_MARKERS), name


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


def test_propose_structure_revision_handler_posts_proposals_with_kind(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"status": 200, "body": {"action_id": "sr-1", "state": "pending"}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(
        agent_mcp._h_propose_structure_revision(
            {"sites": [{"id": "s1", "occ": 0.5}], "rationale": "occupancy drift"}
        )
    )
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/proposals"
    assert captured["payload"] == {
        "kind": "structure_revision",
        "payload": {"sites": [{"id": "s1", "occ": 0.5}]},
        "rationale": "occupancy drift",
    }


def test_propose_review_resolution_handler_builds_payload(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["payload"] = payload
        return {"status": 200, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(
        agent_mcp._h_propose_review_resolution(
            {"item_id": "rv1", "action": "accept", "rationale": "close competitor resolved"}
        )
    )
    assert captured["payload"] == {
        "kind": "review_resolution",
        "payload": {"item_id": "rv1", "action": "accept"},
        "rationale": "close competitor resolved",
    }


def test_propose_phase_change_handler_omits_absent_structure_path(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["payload"] = payload
        return {"status": 200, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(
        agent_mcp._h_propose_phase_change(
            {"op": "remove", "phase_name": "phaseA", "rationale": "no longer supported"}
        )
    )
    assert captured["payload"] == {
        "kind": "phase_change",
        "payload": {"op": "remove", "phase_name": "phaseA"},
        "rationale": "no longer supported",
    }


def test_propose_phase_change_handler_includes_structure_path_when_present(
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["payload"] = payload
        return {"status": 200, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(
        agent_mcp._h_propose_phase_change(
            {
                "op": "add",
                "phase_name": "phaseB",
                "structure_path": "data/phaseB.cif",
                "rationale": "changepoint fr090",
            }
        )
    )
    assert captured["payload"] == {
        "kind": "phase_change",
        "payload": {"op": "add", "phase_name": "phaseB", "structure_path": "data/phaseB.cif"},
        "rationale": "changepoint fr090",
    }


def test_propose_settings_change_handler_strips_absent_fields(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured["payload"] = payload
        return {"status": 200, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(
        agent_mcp._h_propose_settings_change(
            {"background_coeffs": 24, "rationale": "residual not flat past 60deg"}
        )
    )
    assert captured["payload"] == {
        "kind": "settings_change",
        "payload": {"background_coeffs": 24},
        "rationale": "residual not flat past 60deg",
    }


def test_list_pending_approvals_handler_calls_get_proposals(monkeypatch: pytest.MonkeyPatch):
    calls = []

    def fake_request(method, path, payload=None):
        calls.append((method, path, payload))
        return {"status": 200, "body": {"pending": []}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    result = asyncio.run(agent_mcp._h_list_pending_approvals({}))
    assert calls == [("GET", "/api/proposals", None)]
    payload = json.loads(result["content"][0]["text"])
    assert payload == {"status": 200, "body": {"pending": []}}


def test_open_project_handler_posts_path(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"status": 200, "body": {"source": "project"}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_open_project({"path": "/tmp/proj"}))
    assert captured == {
        "method": "POST", "path": "/api/project/open", "payload": {"path": "/tmp/proj"},
    }


def test_close_project_handler_posts_empty_body(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"status": 200, "body": {"source": "none"}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_close_project({}))
    assert captured == {"method": "POST", "path": "/api/project/close", "payload": {}}


def test_create_project_handler_posts_name_and_directory(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"status": 200, "body": {}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_create_project({"name": "proj1", "directory": "/tmp"}))
    assert captured == {
        "method": "POST", "path": "/api/project",
        "payload": {"name": "proj1", "directory": "/tmp"},
    }


def test_demo_project_handler_posts_empty_body(monkeypatch: pytest.MonkeyPatch):
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"status": 200, "body": {"source": "demo"}}

    monkeypatch.setattr(agent_mcp, "_request", fake_request)
    asyncio.run(agent_mcp._h_demo_project({}))
    assert captured == {"method": "POST", "path": "/api/project/demo", "payload": {}}


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
