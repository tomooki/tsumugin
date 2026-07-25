"""``tsumugin.workbench.session.WorkbenchSession`` の TDD テスト。

対象: モード切替 (FR-402) / hypotheses accept・revert / review queue resolve /
structure apply / approval / stages / refine / transcript message / ledger view。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.workbench.session import WorkbenchSession


# ---------------------------------------------------------------------------
# モード切替 (FR-402)
# ---------------------------------------------------------------------------


def test_set_mode_switches_engine_and_appends_single_ledger_entry():
    # 【目的】: manual→auto で engine.mode が human→agent になり ledger が 1 件だけ増える
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    changed = session.set_mode("auto")

    assert changed is True
    assert session.mode == "auto"
    assert session.engine.mode == "agent"
    assert len(session.ledger.entries) == before + 1
    assert session.ledger.entries[-1].kind == "selection_set_mode"


def test_set_mode_same_mode_is_noop_and_does_not_append_ledger():
    # 【目的】: 同一モードへの切替は no-op で False を返し ledger は増えない
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    changed = session.set_mode("manual")

    assert changed is False
    assert session.mode == "manual"
    assert len(session.ledger.entries) == before


def test_set_mode_rejects_unknown_mode():
    session = WorkbenchSession.create_demo()
    with pytest.raises(ValueError):
        session.set_mode("bogus")


def test_set_mode_round_trip_appends_two_entries():
    # 【目的】: manual→auto→manual は 2 件の ledger 追記 (それぞれ 1 件ずつ)
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    session.set_mode("auto")
    session.set_mode("manual")

    assert len(session.ledger.entries) == before + 2
    assert session.mode == "manual"


# ---------------------------------------------------------------------------
# review queue resolve
# ---------------------------------------------------------------------------


def test_create_demo_seeds_four_review_items():
    session = WorkbenchSession.create_demo()
    rows = session.review_view()
    assert len(rows) == 4
    titles = {r["title"] for r in rows}
    assert titles == {
        "close competitor", "unindexed peaks", "guard fired 3×",
        "coulometric feasibility infeasible",
    }
    assert all(r["state"] == "pending" for r in rows)


def test_resolve_review_item_accept_sets_resolved_and_appends_ledger():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    before = len(session.ledger.entries)

    result = session.resolve_review_item(item_id, action="accept", note="looks fine")

    assert "error" not in result
    assert result["item"]["state"] == "accepted"
    assert session.review_queue.items[0].resolved is True
    assert len(session.ledger.entries) == before + 1


def test_resolve_review_item_send_back_sets_resolved_and_appends_ledger():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[1].item_id
    before = len(session.ledger.entries)

    result = session.resolve_review_item(item_id, action="send_back", note="needs more data")

    assert result["item"]["state"] == "sent_back"
    assert session.review_queue.items[1].resolved is True
    assert len(session.ledger.entries) == before + 1


def test_resolve_review_item_unknown_id_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.resolve_review_item("nope", action="accept", note="")
    assert result["error_type"] == "NotFoundError"
    assert "error" in result


def test_resolve_review_item_double_resolve_returns_error_dict():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    session.resolve_review_item(item_id, action="accept", note="")

    result = session.resolve_review_item(item_id, action="accept", note="again")

    assert result["error_type"] == "ConflictError"


# ---------------------------------------------------------------------------
# structure apply
# ---------------------------------------------------------------------------


def test_apply_structure_creates_snapshot_and_appends_ledger():
    session = WorkbenchSession.create_demo()
    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)
    sites = session.viewmodel()["structure"]["sites"]
    sites[0]["occ"] = "0.55"

    result = session.apply_structure(sites, note="lower K1 occupancy")

    assert "snapshot_id" in result
    assert "ledger_index" in result
    assert len(session.snapshots.snapshots) == before_snaps + 1
    assert len(session.ledger.entries) == before_ledger + 1
    assert session._structure_phases[0].occupancies["K1"] == pytest.approx(0.55)


def test_apply_structure_ignores_malformed_occ_without_raising():
    session = WorkbenchSession.create_demo()
    sites = session.viewmodel()["structure"]["sites"]
    sites[0]["occ"] = "not-a-number"

    result = session.apply_structure(sites, note="bad value")

    assert "snapshot_id" in result  # 例外化せず縮退する


# ---------------------------------------------------------------------------
# approval
# ---------------------------------------------------------------------------


def test_resolve_approval_approve_creates_snapshot_and_ledger():
    session = WorkbenchSession.create_demo()
    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)

    result = session.resolve_approval("a1", decision="approve")

    assert result["state"] == "approved"
    assert result["snapshot_id"] is not None
    assert len(session.snapshots.snapshots) == before_snaps + 1
    assert len(session.ledger.entries) == before_ledger + 1
    # 提案 (transcript の approval カード) は消えない
    transcript_ids = [m["id"] for m in session.viewmodel()["transcript"]]
    assert "t7" in transcript_ids


def test_resolve_approval_reject_appends_ledger_only():
    session = WorkbenchSession.create_demo()
    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)

    result = session.resolve_approval("a1", decision="reject")

    assert result["state"] == "rejected"
    assert result["snapshot_id"] is None
    assert len(session.snapshots.snapshots) == before_snaps  # snapshot は増えない
    assert len(session.ledger.entries) == before_ledger + 1
    transcript_ids = [m["id"] for m in session.viewmodel()["transcript"]]
    assert "t7" in transcript_ids  # 提案は ledger に残ったまま消えない


def test_resolve_approval_double_resolve_returns_error_dict():
    session = WorkbenchSession.create_demo()
    session.resolve_approval("a1", decision="approve")

    result = session.resolve_approval("a1", decision="reject")

    assert result["error_type"] == "ConflictError"


def test_resolve_approval_unknown_action_id_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.resolve_approval("nope", decision="approve")
    assert result["error_type"] == "NotFoundError"


def test_viewmodel_transcript_approval_state_reflects_resolution():
    session = WorkbenchSession.create_demo()
    session.resolve_approval("a1", decision="approve")

    approval_msg = next(m for m in session.viewmodel()["transcript"] if m.get("kind") == "approval")
    assert approval_msg["state"] == "approved"


# ---------------------------------------------------------------------------
# refine
# ---------------------------------------------------------------------------


def test_request_refine_appends_ledger_only():
    session = WorkbenchSession.create_demo()
    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)

    result = session.request_refine()

    assert result == {"status": "recorded"}
    assert len(session.ledger.entries) == before_ledger + 1
    assert len(session.snapshots.snapshots) == before_snaps


# ---------------------------------------------------------------------------
# transcript message
# ---------------------------------------------------------------------------


def test_post_message_appends_transcript_and_ledger():
    session = WorkbenchSession.create_demo()
    before_ledger = len(session.ledger.entries)

    result = session.post_message("what about fr092?")

    assert result["message"]["kind"] == "user"
    assert result["message"]["text"] == "what about fr092?"
    assert len(session.ledger.entries) == before_ledger + 1
    assert any(
        m.get("text") == "what about fr092?" for m in session.viewmodel()["transcript"]
    )


# ---------------------------------------------------------------------------
# hypotheses accept / revert
# ---------------------------------------------------------------------------


def test_accept_hypothesis_registers_in_engine_and_appends_ledger():
    session = WorkbenchSession.create_demo()
    before_ledger = len(session.ledger.entries)

    result = session.accept_hypothesis("H-014", by="human")

    assert result["status"] == "accepted"
    assert "H-014" in session.engine.accepted
    assert len(session.ledger.entries) > before_ledger


def test_accept_hypothesis_unknown_id_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.accept_hypothesis("nope", by="human")
    assert result["error_type"] == "NotFoundError"


def test_accept_hypothesis_human_mode_agent_by_is_recommend_only():
    # 【目的】: MANUAL (human) で agent 発の accept は書き込まず recommend_only に留まる
    session = WorkbenchSession.create_demo()
    assert session.mode == "manual"
    before_ledger = len(session.ledger.entries)

    result = session.accept_hypothesis("H-014", by="agent")

    assert result["status"] == "recommend_only"
    assert "H-014" not in session.engine.accepted
    assert len(session.ledger.entries) == before_ledger


def test_revert_hypothesis_after_accept_marks_superseded():
    session = WorkbenchSession.create_demo()
    session.accept_hypothesis("H-014", by="human")

    result = session.revert_hypothesis("H-014", note="second look")

    assert result == {"status": "reverted"}
    assert session.engine.accepted["H-014"].status == "superseded"


def test_revert_hypothesis_not_accepted_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.revert_hypothesis("H-011", note="")
    assert result["error_type"] == "NotFoundError"


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------


def test_stage_action_release_and_revert_append_ledger():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    result = session.stage_action("07", action="release")

    assert result["stage"]["released"] is True
    assert len(session.ledger.entries) == before + 1


def test_stage_action_unknown_nn_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.stage_action("99", action="release")
    assert result["error_type"] == "NotFoundError"


# ---------------------------------------------------------------------------
# state / viewmodel
# ---------------------------------------------------------------------------


def test_state_ledger_verified_is_true():
    session = WorkbenchSession.create_demo()
    state = session.state()
    assert state["ledger"]["verified"] is True
    assert state["ledger"]["count"] == len(session.ledger.entries)


def test_state_agent_idle_reflects_mode():
    session = WorkbenchSession.create_demo()
    assert session.state()["agent"]["idle"] is True  # manual
    session.set_mode("auto")
    assert session.state()["agent"]["idle"] is False  # auto


def test_viewmodel_top_level_keys_present_and_json_serializable():
    session = WorkbenchSession.create_demo()
    vm = session.viewmodel()

    required = {
        "datasets", "phases", "channels", "snapshots", "fit", "parameters",
        "hypotheses", "phase_id", "sequence", "structure", "stages", "review", "transcript",
    }
    assert required <= set(vm)
    text = json.dumps(vm, allow_nan=False)  # NaN/inf があれば ValueError
    assert text


def test_ledger_view_entries_have_required_keys_and_are_verified():
    session = WorkbenchSession.create_demo()
    session.set_mode("auto")
    view = session.ledger_view()

    assert view["verified"] is True
    assert len(view["entries"]) == len(session.ledger.entries)
    for row in view["entries"]:
        assert {"index", "time", "actor", "text", "hash", "revert_to"} <= set(row)
    mode_row = next(r for r in view["entries"] if "mode switch" in r["text"])
    assert "manual" in mode_row["text"] and "auto" in mode_row["text"]
