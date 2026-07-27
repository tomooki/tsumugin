"""``tsumugin.workbench.session.WorkbenchSession`` の TDD テスト。

対象: モード切替 (FR-402) / hypotheses accept・revert / review queue resolve /
structure apply / approval / stages / refine / transcript message / ledger view /
解析ループ完成 (V2a' A1-A6): stages_on フィルタ (A1)・occ revisions 再精密化配線 (A3)・
相同定ジョブ (A4)・マルチスタート ジョブ (A5)・gpx エクスポート (A6)。
"""

from __future__ import annotations

import dataclasses
import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.multistart import MultistartStart, RietveldMultistartResult
from tsumugin.workbench import lifecycle
from tsumugin.workbench.project import WorkbenchProject
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
# V3a レビュー指摘 #2: 実行中エージェントと mode 切替の衝突
# ---------------------------------------------------------------------------


def test_set_mode_rejects_switch_while_agent_running():
    from tsumugin.errors import ConflictError

    session = WorkbenchSession.create_demo()
    session.set_mode("auto")
    before = len(session.ledger.entries)
    session._agent_bridge = _StubBridge(available=True, running=True)

    with pytest.raises(ConflictError):
        session.set_mode("manual")

    # 拒否された切替は ledger にも engine.mode にも副作用を残さない。
    assert session.mode == "auto"
    assert len(session.ledger.entries) == before


def test_agent_running_reflects_bridge_status():
    session = WorkbenchSession.create_demo()
    assert session.agent_running() is False
    session._agent_bridge = _StubBridge(available=True, running=True)
    assert session.agent_running() is True


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
# ModelAction 起票 (create_proposal / 一般化 resolve_approval, 2026-07-26 権限境界改訂)
# ---------------------------------------------------------------------------


def test_create_proposal_structure_revision_creates_pending_card_and_ledger():
    session = WorkbenchSession.create_demo()
    before_ledger = len(session.ledger.entries)

    result = session.create_proposal(
        "structure_revision", {"sites": [{"id": "s1", "label": "O1", "occ": 0.71}]},
        rationale="occupancy drift observed",
    )

    assert result == {"action_id": "sr-1", "state": "pending"}
    assert len(session.ledger.entries) == before_ledger + 1
    assert session.ledger.entries[-1].kind == "agent_proposal"
    card = next(m for m in session.viewmodel()["transcript"] if m.get("action_id") == "sr-1")
    assert card["kind"] == "approval"
    assert card["state"] == "pending"
    assert card["rationale"] == "occupancy drift observed"
    assert json.loads(card["action_json"]) == {"sites": [{"id": "s1", "label": "O1", "occ": 0.71}]}


def test_create_proposal_unknown_kind_returns_422_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.create_proposal("bogus_kind", {}, rationale="x")
    assert result["error_type"] == "ValueError"


def test_create_proposal_non_dict_payload_returns_422_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.create_proposal("structure_revision", "not-a-dict", rationale="x")
    assert result["error_type"] == "ValueError"


def test_create_proposal_structure_revision_empty_sites_returns_422():
    session = WorkbenchSession.create_demo()
    result = session.create_proposal("structure_revision", {"sites": []}, rationale="x")
    assert result["error_type"] == "ValueError"


def test_create_proposal_review_resolution_unknown_item_id_returns_404_at_propose_time():
    session = WorkbenchSession.create_demo()
    before_ledger = len(session.ledger.entries)

    result = session.create_proposal(
        "review_resolution", {"item_id": "no-such-item", "action": "accept"}, rationale="x"
    )

    assert result["error_type"] == "NotFoundError"
    # 起票時に弾かれる = ledger に agent_proposal は残らない (承認時まで持ち越さない)
    assert len(session.ledger.entries) == before_ledger


def test_create_proposal_review_resolution_invalid_action_returns_422():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    result = session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "bogus"}, rationale="x"
    )
    assert result["error_type"] == "ValueError"


def test_create_proposal_phase_change_without_project_returns_422():
    session = WorkbenchSession.create_demo()
    result = session.create_proposal(
        "phase_change", {"op": "add", "phase_name": "p1", "structure_path": "p1.cif"}, rationale="x"
    )
    assert result["error_type"] == "ValueError"


def test_create_proposal_phase_change_add_requires_structure_path(project_session: WorkbenchSession):
    result = project_session.create_proposal(
        "phase_change", {"op": "add", "phase_name": "p1"}, rationale="x"
    )
    assert result["error_type"] == "ValueError"


def test_create_proposal_phase_change_remove_unknown_phase_returns_404(
    project_session: WorkbenchSession,
):
    result = project_session.create_proposal(
        "phase_change", {"op": "remove", "phase_name": "no-such-phase"}, rationale="x"
    )
    assert result["error_type"] == "NotFoundError"


def test_create_proposal_settings_change_without_project_returns_422():
    session = WorkbenchSession.create_demo()
    result = session.create_proposal("settings_change", {"max_cyc": 10}, rationale="x")
    assert result["error_type"] == "ValueError"


def test_create_proposal_settings_change_requires_at_least_one_field(
    project_session: WorkbenchSession,
):
    result = project_session.create_proposal("settings_change", {}, rationale="x")
    assert result["error_type"] == "ValueError"


def test_create_proposal_settings_change_invalid_two_theta_limits_returns_422(
    project_session: WorkbenchSession,
):
    result = project_session.create_proposal(
        "settings_change", {"two_theta_limits": ["not", "numbers"]}, rationale="x"
    )
    assert result["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# エージェント権限モード (agent_policy, 2026-07-26 権限境界改訂)
# ---------------------------------------------------------------------------


def test_agent_policy_defaults_to_approve():
    session = WorkbenchSession.create_demo()
    assert session.agent_policy == "approve"
    assert session.state()["agent"]["policy"] == "approve"


def test_set_agent_policy_switches_and_appends_single_ledger_entry():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    changed = session.set_agent_policy("auto")

    assert changed is True
    assert session.agent_policy == "auto"
    assert session.state()["agent"]["policy"] == "auto"
    assert len(session.ledger.entries) == before + 1
    assert session.ledger.entries[-1].kind == "agent_policy_change"
    assert session.ledger.entries[-1].payload["policy"] == "auto"


def test_set_agent_policy_same_value_is_noop_and_does_not_append_ledger():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    changed = session.set_agent_policy("approve")

    assert changed is False
    assert session.agent_policy == "approve"
    assert len(session.ledger.entries) == before


def test_set_agent_policy_rejects_unknown_value():
    session = WorkbenchSession.create_demo()
    with pytest.raises(ValueError):
        session.set_agent_policy("bogus")


def test_set_agent_policy_round_trip_appends_three_entries():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    session.set_agent_policy("auto")
    session.set_agent_policy("bypass")
    session.set_agent_policy("approve")

    assert len(session.ledger.entries) == before + 3
    assert session.agent_policy == "approve"


def test_set_agent_policy_rejects_switch_while_agent_running():
    from tsumugin.errors import ConflictError

    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)
    session._agent_bridge = _StubBridge(available=True, running=True)

    with pytest.raises(ConflictError):
        session.set_agent_policy("auto")

    assert session.agent_policy == "approve"
    assert len(session.ledger.entries) == before


# ---------------------------------------------------------------------------
# create_proposal の agent_policy 分岐 (auto/bypass 即時自動適用)
# ---------------------------------------------------------------------------


def test_create_proposal_auto_policy_immediately_executes_review_resolution():
    session = WorkbenchSession.create_demo()
    session.set_agent_policy("auto")
    item_id = session.review_queue.items[0].item_id
    before_ledger = len(session.ledger.entries)

    result = session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )

    assert result["action_id"] == "rv-1"
    assert result["state"] == "auto_applied"
    assert "result" in result
    resolved_item = next(it for it in session.review_queue.items if it.item_id == item_id)
    assert resolved_item.resolved is True
    card = next(m for m in session.viewmodel()["transcript"] if m.get("action_id") == "rv-1")
    assert card["state"] == "auto_applied"
    # agent_proposal + review_resolve (実操作) + approval_decision(auto) の 3 件が追記される。
    kinds = [e.kind for e in session.ledger.entries[before_ledger:]]
    assert kinds == ["agent_proposal", "review_resolve", "approval_decision"]
    assert session.ledger.entries[-1].payload["decision"] == "auto"


def test_create_proposal_bypass_policy_immediately_executes_structure_revision():
    session = WorkbenchSession.create_demo()
    session.set_agent_policy("bypass")
    before_snaps = len(session.snapshots.snapshots)

    result = session.create_proposal(
        "structure_revision", {"sites": [{"id": "s1", "label": "O1", "occ": 0.9}]}, rationale="x"
    )

    assert result["state"] == "auto_applied"
    assert len(session.snapshots.snapshots) == before_snaps + 1
    card = next(m for m in session.viewmodel()["transcript"] if m.get("action_id") == "sr-1")
    assert card["state"] == "auto_applied"


def test_create_proposal_auto_policy_execution_failure_leaves_card_pending():
    """auto 適用の実操作が失敗すれば error dict + カードは pending 相当に残る (再試行可能)。"""
    session = WorkbenchSession.create_demo()
    session.set_agent_policy("auto")
    item_id = session.review_queue.items[0].item_id
    # 【失敗を決定論的に再現】: _execute_proposal 呼び出しの直前に、別経路 (人間の GUI 操作を
    #   模擬) で同じ項目を先に解決してしまう競合を注入する (resolve_review_item は「既に
    #   解決済み」を ConflictError error dict で返す — session.py L705 付近)。
    original_execute = session._execute_proposal

    def _fail_once(kind, payload):
        session.resolve_review_item(item_id, action="send_back")
        return original_execute(kind, payload)

    session._execute_proposal = _fail_once

    result = session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )

    assert "error" in result
    assert result["action_id"] == "rv-1"
    assert result["state"] == "pending"
    assert "rv-1" not in session._approvals
    card = next(m for m in session.viewmodel()["transcript"] if m.get("action_id") == "rv-1")
    assert card["state"] == "pending"
    # approve 経路で人間が承認/却下できるよう、起票 (create_proposal 側の validation) は
    # 通っていたことを確認する — pending_approvals にも引き続き現れる。
    assert any(row["action_id"] == "rv-1" for row in session.pending_approvals())


def test_create_proposal_approve_policy_default_still_creates_pending_only():
    """既定 (approve) の回帰: create_proposal は実操作を起こさずカードのみを作る。"""
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id

    result = session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )

    assert result == {"action_id": "rv-1", "state": "pending"}
    resolved_item = next(it for it in session.review_queue.items if it.item_id == item_id)
    assert resolved_item.resolved is False
    kinds = [e.kind for e in session.ledger.entries]
    assert "approval_decision" not in kinds


# ---------------------------------------------------------------------------
# 並行 create_proposal(auto) の lost update (レビュー指摘 #2: self._lock を RLock 化)
# ---------------------------------------------------------------------------


def test_create_proposal_auto_concurrent_phase_change_add_no_lost_update(
    project_session: WorkbenchSession, monkeypatch
):
    """指摘2: auto ポリシーで 2 件の propose_phase_change(op=add) が同一ターンで並走しても、
    ``self._project`` の read-modify-write (``add_phase``) が ``self._lock`` (RLock) 下で直列化
    され、どちらの変更も消えないことを実証する。

    ``dataclasses.replace(project, phases=...)`` 呼び出し (``add_phase``/``remove_phase`` の
    書込み直前) へ ``threading.Barrier(2)`` を仕込み、2 スレッドが「``self._project.phases`` の
    読取直後・``self._project`` への書込み直前」に同時到達できてしまう場合を deterministic に
    再現する。

    - **ロックが効いていれば**: 片方のスレッドは ``add_phase`` 冒頭の ``with self._lock:`` の
      外で足止めされ、barrier の相手が来ないため待機は timeout する (``BrokenBarrierError`` を
      握りつぶしてそのまま処理を続ける — 直列実行なので待つ意味がない)。ロックを保持したまま
      読取→書込みが完結するため、後続スレッドは前者が反映した相を含む最新の ``self._project``
      から読み直し、**両方の相が最終的に残る**。
    - **ロックを外す変異では**: 両スレッドが無防備に「読取直後」へほぼ同時到達でき、barrier が
      高確率で解消する。両者とも同一の (まだ相手の追加を含まない) 古い ``self._project`` から
      新タプルを計算し、後勝ちの代入がもう片方の相追加を丸ごと消す — このテストは phaseA/phaseB
      のどちらかが最終的に欠落することで検知する (手動で ``add_phase``/``create_proposal`` の
      ``with self._lock:`` を外して本テストを実行し fail することを確認済み)。
    """
    session = project_session
    session.set_agent_policy("auto")

    barrier = threading.Barrier(2)
    original_replace = dataclasses.replace

    def hooked_replace(obj, **changes):
        if "phases" in changes:
            try:
                barrier.wait(timeout=0.3)
            except threading.BrokenBarrierError:
                pass
        return original_replace(obj, **changes)

    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module.dataclasses, "replace", hooked_replace)

    results: dict[str, Any] = {}
    errors: list[BaseException] = []
    out_lock = threading.Lock()

    def _propose(name: str, path: str) -> None:
        try:
            r = session.create_proposal(
                "phase_change",
                {"op": "add", "phase_name": name, "structure_path": path},
                rationale="x",
            )
            with out_lock:
                results[name] = r
        except BaseException as exc:  # noqa: BLE001 — 収集して assert で可視化する
            with out_lock:
                errors.append(exc)

    t1 = threading.Thread(target=_propose, args=("phaseA", "a.cif"))
    t2 = threading.Thread(target=_propose, args=("phaseB", "b.cif"))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert not errors, f"unexpected exceptions: {errors}"
    assert results["phaseA"]["state"] == "auto_applied", results["phaseA"]
    assert results["phaseB"]["state"] == "auto_applied", results["phaseB"]

    names = {p.phase_name for p in session._project.phases}
    assert "phaseA" in names, "phaseA lost — read-modify-write race (指摘2, lost update)"
    assert "phaseB" in names, "phaseB lost — read-modify-write race (指摘2, lost update)"

    project_edits = [e for e in session.ledger.entries if e.kind == "project_edit"]
    assert len(project_edits) == 2
    assert session.ledger.verify() is True


def test_resolve_generic_proposal_structure_revision_approve_creates_snapshot():
    session = WorkbenchSession.create_demo()
    session.create_proposal(
        "structure_revision", {"sites": [{"id": "s1", "label": "O1", "occ": 0.9}]}, rationale="x"
    )
    before_snaps = len(session.snapshots.snapshots)

    result = session.resolve_approval("sr-1", decision="approve")

    assert result["state"] == "approved"
    assert result["snapshot_id"] is not None
    assert len(session.snapshots.snapshots) == before_snaps + 1
    card = next(m for m in session.viewmodel()["transcript"] if m.get("action_id") == "sr-1")
    assert card["state"] == "approved"


def test_resolve_generic_proposal_review_resolution_approve_resolves_item():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )

    result = session.resolve_approval("rv-1", decision="approve")

    assert result["state"] == "approved"
    resolved_item = next(it for it in session.review_queue.items if it.item_id == item_id)
    assert resolved_item.resolved is True
    row = next(r for r in session.review_view() if r["id"] == item_id)
    assert row["state"] == "accepted"


def test_resolve_generic_proposal_phase_change_add_approve_adds_phase(
    project_session: WorkbenchSession,
):
    project_session.create_proposal(
        "phase_change",
        {"op": "add", "phase_name": "phaseX", "structure_path": "data/phaseX.cif"},
        rationale="x",
    )
    before = len(project_session._project.phases)

    result = project_session.resolve_approval("pc-1", decision="approve")

    assert result["state"] == "approved"
    assert len(project_session._project.phases) == before + 1
    assert any(p.phase_name == "phaseX" for p in project_session._project.phases)


def test_resolve_generic_proposal_phase_change_remove_approve_removes_phase(
    project_session: WorkbenchSession,
):
    project_session.add_phase(structure_path="p.cif", phase_name="phaseY")
    project_session.create_proposal(
        "phase_change", {"op": "remove", "phase_name": "phaseY"}, rationale="x"
    )

    result = project_session.resolve_approval("pc-1", decision="approve")

    assert result["state"] == "approved"
    assert not any(p.phase_name == "phaseY" for p in project_session._project.phases)


def test_resolve_generic_proposal_settings_change_approve_applies_settings(
    project_session: WorkbenchSession,
):
    project_session.create_proposal("settings_change", {"max_cyc": 42}, rationale="x")

    result = project_session.resolve_approval("st-1", decision="approve")

    assert result["state"] == "approved"
    assert project_session._project.max_cyc == 42


def test_resolve_generic_proposal_reject_appends_ledger_only():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )

    result = session.resolve_approval("rv-1", decision="reject")

    assert result["state"] == "rejected"
    assert result["snapshot_id"] is None
    resolved_item = next(it for it in session.review_queue.items if it.item_id == item_id)
    assert resolved_item.resolved is False  # reject では実操作は起きない


def test_resolve_generic_proposal_double_approve_returns_409():
    session = WorkbenchSession.create_demo()
    session.create_proposal(
        "structure_revision", {"sites": [{"id": "s1", "label": "O1", "occ": 0.5}]}, rationale="x"
    )
    session.resolve_approval("sr-1", decision="approve")

    result = session.resolve_approval("sr-1", decision="approve")

    assert result["error_type"] == "ConflictError"


def test_resolve_generic_proposal_unknown_action_id_returns_404():
    session = WorkbenchSession.create_demo()
    result = session.resolve_approval("sr-999", decision="approve")
    assert result["error_type"] == "NotFoundError"


def test_resolve_generic_proposal_execution_failure_reverts_card_to_pending():
    """approve 時の実操作 (resolve_review_item) が失敗すれば error dict + カードは pending 復帰。"""
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )
    # 承認カード起票後、人間が GUI から直接同じ項目を解決してしまう競合を模擬する。
    session.resolve_review_item(item_id, action="send_back")

    result = session.resolve_approval("rv-1", decision="approve")

    assert "error" in result
    assert result["error_type"] == "ConflictError"
    assert "rv-1" not in session._approvals  # pending のまま (再試行可能)
    card = next(m for m in session.viewmodel()["transcript"] if m.get("action_id") == "rv-1")
    assert card["state"] == "pending"


def test_pending_approvals_lists_only_pending_cards_across_kinds():
    session = WorkbenchSession.create_demo()
    item_id = session.review_queue.items[0].item_id
    sr_result = session.create_proposal(
        "structure_revision", {"sites": [{"id": "s1", "label": "O1", "occ": 0.5}]}, rationale="x"
    )
    rv_result = session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="y"
    )
    session.resolve_approval(sr_result["action_id"], decision="approve")  # これはもう pending でない

    pending = session.pending_approvals()

    pending_ids = {row["action_id"] for row in pending}
    assert sr_result["action_id"] not in pending_ids
    assert rv_result["action_id"] in pending_ids
    # demo シードの一般承認カード "a1" も pending として一覧に含まれる (機構問わず)。
    assert "a1" in pending_ids


# ---------------------------------------------------------------------------
# abandon_pending_approvals (レビュー指摘 #1: セッション差し替え時の pending カード記録)
# ---------------------------------------------------------------------------


def test_abandon_pending_approvals_records_one_entry_per_pending_card():
    session = WorkbenchSession.create_demo()
    session.resolve_approval("a1", decision="reject")  # demo 既定の pending カードを解消
    item_id = session.review_queue.items[0].item_id
    session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )
    session.create_proposal(
        "structure_revision", {"sites": [{"id": "s1", "label": "O1", "occ": 0.5}]}, rationale="y"
    )
    before = len(session.ledger.entries)

    count = session.abandon_pending_approvals()

    # action_id の連番 (``_proposal_seq``) は kind を跨いで共有される (`create_proposal` 参照) —
    # review_resolution が先なので "rv-1"、structure_revision は "sr-2"。
    assert count == 2
    new_entries = session.ledger.entries[before:]
    assert [e.kind for e in new_entries] == ["approval_abandoned", "approval_abandoned"]
    action_ids = {e.payload["action_id"] for e in new_entries}
    assert action_ids == {"rv-1", "sr-2"}
    kinds = {e.payload["action_id"]: e.payload["kind"] for e in new_entries}
    assert kinds == {"rv-1": "review_resolution", "sr-2": "structure_revision"}
    assert all(e.payload["reason"] == "session swap" for e in new_entries)
    assert session.ledger.verify() is True
    assert session._approvals["rv-1"]["state"] == "abandoned"
    assert session._approvals["sr-2"]["state"] == "abandoned"
    # 以後 pending 一覧・resolve_approval の対象から外れる。
    assert session.pending_approvals() == []
    result = session.resolve_approval("rv-1", decision="approve")
    assert result["error_type"] == "ConflictError"


def test_abandon_pending_approvals_custom_reason():
    session = WorkbenchSession.create_demo()
    session.resolve_approval("a1", decision="reject")
    item_id = session.review_queue.items[0].item_id
    session.create_proposal(
        "review_resolution", {"item_id": item_id, "action": "accept"}, rationale="x"
    )

    session.abandon_pending_approvals(reason="custom reason")

    assert session.ledger.entries[-1].payload["reason"] == "custom reason"


def test_abandon_pending_approvals_noop_when_none_pending():
    session = WorkbenchSession.create_demo()
    session.resolve_approval("a1", decision="reject")
    before = len(session.ledger.entries)

    count = session.abandon_pending_approvals()

    assert count == 0
    assert len(session.ledger.entries) == before


def test_abandon_pending_approvals_skips_already_resolved_card():
    """既に approve/reject 済みのカード ("a1", demo 既定) は対象外 — 二重記録しない。"""
    session = WorkbenchSession.create_demo()
    session.resolve_approval("a1", decision="approve")
    before = len(session.ledger.entries)

    count = session.abandon_pending_approvals()

    assert count == 0
    assert len(session.ledger.entries) == before
    assert session._approvals["a1"]["state"] == "approved"


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
# V3a AUTO 実 LLM ブリッジ: post_message の分岐配線
# ---------------------------------------------------------------------------


class _StubBridge:
    """``AgentBridge`` の代わりに差し込む最小スタブ (session.py が使う面のみ実装)。"""

    def __init__(self, *, available: bool, accept: bool = True, running: bool = False) -> None:
        self._available = available
        self._accept = accept
        self._running = running
        self.sent: list[str] = []

    @property
    def available(self) -> bool:
        return self._available

    def send(self, text: str) -> bool:
        if not self._accept:
            return False
        self.sent.append(text)
        return True

    def status(self) -> dict:
        is_running = self._running or bool(self.sent)
        return {"status": "running" if is_running else "idle", "available": self._available,
                "tokens": 0, "wall_time_s": 0.0, "error": None}


def test_post_message_auto_mode_with_available_bridge_starts_agent():
    session = WorkbenchSession.create_demo()
    session.set_mode("auto")
    stub = _StubBridge(available=True)
    session._agent_bridge = stub

    result = session.post_message("hello agent")

    assert result == {"status": "agent_started"}
    assert stub.sent == ["hello agent"]
    # ユーザーメッセージ自体は従来どおり transcript/ledger に記録される。
    assert any(m.get("text") == "hello agent" for m in session.viewmodel()["transcript"])


def test_post_message_auto_mode_with_unavailable_bridge_falls_back():
    session = WorkbenchSession.create_demo()
    session.set_mode("auto")
    stub = _StubBridge(available=False)
    session._agent_bridge = stub

    result = session.post_message("hello agent")

    assert result["message"]["text"] == "hello agent"
    assert stub.sent == []  # bridge には送られていない (フォールバック)


def test_post_message_manual_mode_never_invokes_bridge_even_if_available():
    session = WorkbenchSession.create_demo()  # 既定 manual
    stub = _StubBridge(available=True)
    session._agent_bridge = stub

    result = session.post_message("hello")

    assert result["message"]["text"] == "hello"
    assert stub.sent == []


def test_post_message_source_none_never_invokes_bridge():
    session = WorkbenchSession.create_empty()
    session.set_mode("auto")
    stub = _StubBridge(available=True)
    session._agent_bridge = stub

    result = session.post_message("hello")

    assert result["message"]["text"] == "hello"
    assert stub.sent == []


def test_post_message_agent_already_running_returns_conflict():
    session = WorkbenchSession.create_demo()
    session.set_mode("auto")
    stub = _StubBridge(available=True, accept=False)
    session._agent_bridge = stub

    result = session.post_message("hello")

    assert result["error_type"] == "ConflictError"


def test_post_message_transcript_append_is_serialized_by_lock():
    """V3a レビュー指摘 #3: ``post_message`` の ``msg = {"id": f"t{len(self._transcript)+1}", ...}``
    採番 + append が ``self._lock`` 下で直列化されることを、複数スレッドが
    ``len(self._transcript)`` の呼び出し (フック付き ``list`` サブクラス) に**同時に**到達できない
    ことで確認する。

    ``threading.Barrier(n_threads)`` を ``list.__len__`` にフックする: ロックが効いていれば
    高々 1 スレッドずつしか ``len()`` 呼び出しに到達できないため、``n_threads`` 全員が揃うことは
    なく barrier は必ずタイムアウトし ``post_message`` は例外で終わる (transcript には 1 行も
    追加されない)。ロックを外す変異 (このテストが検出対象とする欠陥) を入れると、複数スレッドが
    無防備に ``len()`` へ同時到達でき barrier が解消し、**同一の "before" 件数を読んだまま**
    全員が append する — id が重複した行が transcript に残る。
    """
    session = WorkbenchSession.create_demo()
    before = len(session._transcript)
    n_threads = 5

    class _BarrierHookedList(list):
        """``__len__`` 呼び出しごとに barrier で待ち合わせるテスト専用の list サブクラス。"""

        def __init__(self, *args: Any, on_len: Any) -> None:
            super().__init__(*args)
            self._on_len = on_len

        def __len__(self) -> int:
            n = super().__len__()
            self._on_len()
            return n

    barrier = threading.Barrier(n_threads, timeout=1.0)
    session._transcript = _BarrierHookedList(session._transcript, on_len=barrier.wait)

    errors: list[BaseException] = []
    lock = threading.Lock()

    def _post(i: int) -> None:
        try:
            session.post_message(f"msg-{i}")
        except BaseException as exc:  # noqa: BLE001 — barrier タイムアウト/破損を収集する
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_post, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    new_rows = session._transcript[before:]
    ids = [row["id"] for row in new_rows]

    # ロックで直列化されていれば barrier (n_threads 人待ち) は誰も揃わずタイムアウトし、
    # 全スレッドが例外で終わって transcript には何も追加されない。
    assert len(errors) == n_threads, f"expected all {n_threads} calls to fail via barrier timeout"
    assert new_rows == []
    assert len(set(ids)) == len(ids)  # (mutation 時の対照: 重複が出れば直ちに分かる)


def test_agent_status_delegates_to_bridge():
    session = WorkbenchSession.create_demo()
    stub = _StubBridge(available=True)
    session._agent_bridge = stub
    assert session.agent_status() == stub.status()


def test_state_agent_reflects_bridge_tokens_and_available():
    session = WorkbenchSession.create_demo()

    class _Bridge:
        available = True

        def status(self):
            return {"status": "idle", "available": True, "tokens": 42, "wall_time_s": 3.5, "error": None}

    session._agent_bridge = _Bridge()
    agent = session.state()["agent"]
    assert agent["available"] is True
    assert agent["tokens"] == 42
    assert agent["wall_time_s"] == 3.5


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


def test_state_agent_idle_reflects_turn_not_mode():
    # V3a: idle は「エージェントのターンが走っていないこと」。旧仕様の「mode==manual」は
    # AUTO でターン完了後も idle=false に固着する欠陥だった (TestAgentIdleReflectsTurnStatus)。
    session = WorkbenchSession.create_demo()
    assert session.state()["agent"]["idle"] is True  # manual, ターンなし
    session.set_mode("auto")
    assert session.state()["agent"]["idle"] is True  # auto でもターンが無ければ idle


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


# ---------------------------------------------------------------------------
# プロジェクト spec 編集 (V2a P2: add/remove histogram・phase・settings・upload)
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_session(tmp_path) -> WorkbenchSession:
    project = lifecycle.create_project("proj", str(tmp_path))
    return WorkbenchSession.from_project(project)


def _block_refine(session: WorkbenchSession) -> "tuple[threading.Event, threading.Event]":
    """session._job を実行中状態に固定する (refine 実行中 409 ガードのテスト用)。"""
    started = threading.Event()
    release = threading.Event()

    def runner():
        started.set()
        release.wait(timeout=5)
        raise RuntimeError("test runner (unused result)")

    session._job.start(runner, on_success=lambda r: None, on_failure=lambda e: None)
    started.wait(timeout=5)
    return started, release


def test_viewmodel_project_config_echo_present_only_in_project_mode(tmp_path):
    # 【契約 (frontend PROJECT タブ, api-contract.md viewmodel.project)】: demo/none は省略、
    #   project モードのみ histograms/phases/settings を 1:1 で echo する。
    demo = WorkbenchSession.create_demo()
    assert "project" not in demo.viewmodel()

    empty = WorkbenchSession.create_empty()
    assert "project" not in empty.viewmodel()

    project = lifecycle.create_project("proj", str(tmp_path))
    session = WorkbenchSession.from_project(project)
    session.add_histogram(
        data_path="d.xy", instrument_path="d.instprm", radiation="xray_lab",
        geometry="bragg_brentano", data_format="xy", two_theta_limits=[10.0, 70.0],
    )
    session.add_phase(structure_path="p.cif", phase_name="phaseA")

    vm = session.viewmodel()
    assert vm["project"]["histograms"] == [
        {
            "id": "h0", "data_path": "d.xy", "instrument_path": "d.instprm",
            "radiation": "xray_lab", "geometry": "bragg_brentano", "data_format": "XY",
            "two_theta_limits": [10.0, 70.0], "bank": None,
        }
    ]
    assert vm["project"]["phases"] == [{"name": "phaseA", "structure_path": "p.cif"}]
    assert vm["project"]["settings"] == {
        "two_theta_limits": [10.0, 70.0], "background_coeffs": 6, "max_cyc": 12,
    }


def test_add_histogram_appends_spec_persists_and_refreshes_viewmodel(
    project_session: WorkbenchSession, tmp_path
):
    before_ledger = len(project_session.ledger.entries)

    result = project_session.add_histogram(
        data_path="data/hist.xy",
        instrument_path="data/hist.instprm",
        radiation="xray_lab",
        geometry="bragg_brentano",
        data_format="xy",
        two_theta_limits=[10.0, 70.0],
    )

    assert "error" not in result
    assert len(project_session._project.histograms) == 1
    assert project_session._project.histograms[0].data_format == "XY"
    assert len(project_session.ledger.entries) == before_ledger + 1

    # project.json に自動保存されている
    spec_path = tmp_path / "proj" / "project.json"
    saved = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(saved["histograms"]) == 1

    # PARAMETERS/FIT viewmodel が再構築されている
    vm = project_session.viewmodel()
    assert "h0" in vm["parameters"]
    assert vm["fit"]["histograms"][0]["id"] == "h0"


def test_add_histogram_invalid_radiation_returns_422_error_dict(project_session: WorkbenchSession):
    result = project_session.add_histogram(
        data_path="d", instrument_path="i", radiation="bogus", geometry="bragg_brentano"
    )
    assert result["error_type"] == "ValueError"


def test_add_histogram_invalid_data_format_returns_422_error_dict(project_session: WorkbenchSession):
    result = project_session.add_histogram(
        data_path="d", instrument_path="i", radiation="xray_lab",
        geometry="bragg_brentano", data_format="bogus",
    )
    assert result["error_type"] == "ValueError"


def test_add_histogram_without_project_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.add_histogram(
        data_path="d", instrument_path="i", radiation="xray_lab", geometry="bragg_brentano"
    )
    assert result["error_type"] == "ValueError"


def test_remove_histogram_removes_from_spec_and_persists(
    project_session: WorkbenchSession, tmp_path
):
    project_session.add_histogram(
        data_path="d", instrument_path="i", radiation="xray_lab", geometry="bragg_brentano"
    )
    assert len(project_session._project.histograms) == 1

    result = project_session.remove_histogram("h0")

    assert "error" not in result
    assert len(project_session._project.histograms) == 0
    saved = json.loads((tmp_path / "proj" / "project.json").read_text(encoding="utf-8"))
    assert saved["histograms"] == []


def test_remove_histogram_unknown_id_returns_404(project_session: WorkbenchSession):
    result = project_session.remove_histogram("h99")
    assert result["error_type"] == "NotFoundError"


def test_add_phase_and_remove_phase_roundtrip(project_session: WorkbenchSession, tmp_path):
    result = project_session.add_phase(structure_path="p.cif", phase_name="phaseA")
    assert "error" not in result
    assert len(project_session._project.phases) == 1

    dup = project_session.add_phase(structure_path="p2.cif", phase_name="phaseA")
    assert dup["error_type"] == "ValueError"

    removed = project_session.remove_phase("phaseA")
    assert "error" not in removed
    assert len(project_session._project.phases) == 0

    missing = project_session.remove_phase("phaseA")
    assert missing["error_type"] == "NotFoundError"


def test_update_settings_changes_background_and_two_theta_limits(
    project_session: WorkbenchSession, tmp_path
):
    project_session.add_histogram(
        data_path="d", instrument_path="i", radiation="xray_lab", geometry="bragg_brentano"
    )

    result = project_session.update_settings(
        two_theta_limits=[5.0, 60.0], background_coeffs=12, max_cyc=8
    )

    assert "error" not in result
    assert project_session._project.background_coeffs == 12
    assert project_session._project.max_cyc == 8
    assert project_session._project.histograms[0].two_theta_limits == (5.0, 60.0)


def test_update_settings_invalid_two_theta_limits_returns_422(project_session: WorkbenchSession):
    result = project_session.update_settings(two_theta_limits=["not", "numbers"])
    assert result["error_type"] == "ValueError"


def test_store_upload_writes_file_into_data_dir_and_sanitizes_name(
    project_session: WorkbenchSession, tmp_path
):
    result = project_session.store_upload("../evil/../hist.xy", b"1 2 3\n")

    assert "error" not in result
    stored = tmp_path / "proj" / "data" / "hist.xy"
    assert stored.exists()
    assert result["stored_path"] == str(stored)


def test_store_upload_dedups_same_filename(project_session: WorkbenchSession, tmp_path):
    first = project_session.store_upload("hist.xy", b"a")
    second = project_session.store_upload("hist.xy", b"b")

    assert first["stored_path"] != second["stored_path"]
    assert (tmp_path / "proj" / "data" / "hist.xy").read_bytes() == b"a"
    assert (tmp_path / "proj" / "data" / "hist_1.xy").read_bytes() == b"b"


def test_store_upload_rejects_oversized_file(project_session: WorkbenchSession, monkeypatch):
    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "_MAX_UPLOAD_BYTES", 4)
    result = project_session.store_upload("hist.xy", b"12345")
    assert result["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# refine 実行中の spec 変更系ガード (api-contract.md 「refine 実行中は 409」)
# ---------------------------------------------------------------------------


def test_add_histogram_returns_409_while_refine_running(project_session: WorkbenchSession):
    started, release = _block_refine(project_session)
    try:
        result = project_session.add_histogram(
            data_path="d", instrument_path="i", radiation="xray_lab", geometry="bragg_brentano"
        )
        assert result["error_type"] == "ConflictError"
    finally:
        release.set()
        project_session._job.join(timeout=5)


def test_store_upload_returns_409_while_refine_running(project_session: WorkbenchSession):
    started, release = _block_refine(project_session)
    try:
        result = project_session.store_upload("hist.xy", b"1")
        assert result["error_type"] == "ConflictError"
    finally:
        release.set()
        project_session._job.join(timeout=5)


# ---------------------------------------------------------------------------
# ガード変異実証: _guard_project_editable を無効化すると 409 が消えることを確認する
# (変異させて fail することの実証 — 恒久ガードのテスト自体が意味を持つことの確認)
# ---------------------------------------------------------------------------


def test_guard_mutation_without_running_check_would_not_conflict(
    project_session: WorkbenchSession, monkeypatch
):
    """ガードから running チェックを外すと 409 が返らなくなることを示し、ガードの意味を実証する。"""
    import tsumugin.workbench.session as session_module

    def _no_guard(self):  # refine 実行中チェックを外した変異版
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        return None

    started, release = _block_refine(project_session)
    try:
        monkeypatch.setattr(
            session_module.WorkbenchSession, "_guard_project_editable", _no_guard
        )
        result = project_session.add_histogram(
            data_path="d", instrument_path="i", radiation="xray_lab", geometry="bragg_brentano"
        )
        # 【変異で意図的に破壊】: ガードを無効化すると refine 実行中でも受理されてしまう
        #   (= 元のガードが実際に 409 を作り出していたことの証明)。
        assert "error" not in result
    finally:
        release.set()
        project_session._job.join(timeout=5)


class TestAddHistogramXrdmlConversion:
    """add_histogram も load_project_spec と同じ XRDML→XYE 自己変換を通ること (回帰)。

    【背景】: WorkbenchProject の不変条件は「histograms はそのまま run_auto_rietveld に
    渡せる (XRDML は変換済み)」だが、実行時 add_histogram が未変換のまま追記し、GUI 通し
    実証で refine が 'Could not read file' で failed になった。
    """

    def test_add_histogram_converts_xrdml_to_xye(self, tmp_path) -> None:
        project = lifecycle.create_project("conv", str(tmp_path))
        session = WorkbenchSession.open_persistent(project)
        src = (
            Path(__file__).resolve().parents[2]
            / "docs" / "benchmark" / "testdata" / "m9" / "cateo3" / "NB-LM01MO_030.XRDML"
        )
        instprm = src.parent / "cateo3_CuKa.instprm"
        result = session.add_histogram(
            data_path=str(src),
            instrument_path=str(instprm),
            radiation="xray_lab",
            geometry="bragg_brentano",
            data_format="XRDML",
            two_theta_limits=[12.0, 70.0],
        )
        assert "error" not in result
        hist = session.viewmodel()["project"]["histograms"][0]
        # runner-ready 不変条件: XRDML のままではなく XYE へ自己変換済み
        assert hist["data_format"] != "XRDML"
        assert Path(hist["data_path"]).exists()


# ---------------------------------------------------------------------------
# 解析ループ完成 (V2a' A1-A6) — stages_on / occ revisions / phaseid / multistart / export
# ---------------------------------------------------------------------------

_NACL_CIF = """data_NaCl
_cell_length_a 5.64
_cell_length_b 5.64
_cell_length_c 5.64
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
Na Na 0.0 0.0 0.0
Cl Cl 0.5 0.5 0.5
"""


def _phaseid_project(tmp_path: Path) -> WorkbenchProject:
    """元素導出 (pymatgen) 可能な CIF を持つ project フィクスチャ (A4 テスト用)。"""
    cif_path = tmp_path / "nacl.cif"
    cif_path.write_text(_NACL_CIF, encoding="utf-8")
    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"),
        instrument_path=str(tmp_path / "d.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(cif_path), phase_name="nacl")
    return WorkbenchProject(
        name="phaseid fixture", histograms=(hist,), phases=(phase,),
        gpx_path=str(tmp_path / "refined.gpx"), spec_dir=str(tmp_path),
    )


class _FakeReferenceProvider:
    """A4 の provider 注入テスト用フェイク (`tests/reference/test_iterative.py` と同じ流儀)。"""

    def __init__(self, phases):
        self._phases = tuple(phases)

    def fetch(self, elements):
        return self._phases


def _synthetic_pattern(positions, *, scale: float = 2.0):
    """フェイク供給元の 1 相ピーク列から合成観測パターンを作る (numpy 決定論, ノイズなし)。"""
    import numpy as np

    tt = np.linspace(10.0, 80.0, 2000)
    fwhm = 0.15
    y = np.zeros_like(tt)
    sigma = fwhm / 2.3548
    for pos in positions:
        y += scale * 100.0 * np.exp(-0.5 * ((tt - pos) / sigma) ** 2)
    return tt, y


def _fake_autorietveld_result(*, rwp: float, a: float, phase_name: str = "nacl") -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="s", rwp=rwp, gof=1.1, n_params=3, converged=True),),
        final_rwp=rwp,
        final_gof=1.1,
        refined_cells={phase_name: (a, a, a, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        gpx_path="",
        n_obs=100,
    )


# ---------------------------------------------------------------------------
# A1: stages_on
# ---------------------------------------------------------------------------


def test_request_refine_unknown_stages_on_key_returns_422_error_dict(
    project_session: WorkbenchSession,
):
    result = project_session.request_refine(stages_on={"99": False})
    assert result["error_type"] == "ValueError"
    assert "99" in result["error"]


def test_stages_on_unknown_key_guard_mutation_would_not_reject(tmp_path, monkeypatch):
    """``_validate_stages_on`` を無効化すると、存在しない nn ("99") でもジョブが受理されて
    しまうことを示す (= 元の 422 がこの検証から来ていたことの証明)。
    """
    project = _phaseid_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    import tsumugin.workbench.session as session_module

    def fake_build(project, ledger=None, stages_on=None, initial_occupancies=None):
        return lambda: _fake_autorietveld_result(rwp=5.0, a=5.0, phase_name="nacl")

    monkeypatch.setattr(session_module, "build_default_runner", fake_build)
    monkeypatch.setattr(
        session_module.WorkbenchSession, "_validate_stages_on", lambda self, stages_on: None
    )

    result = session.request_refine(stages_on={"99": False})  # "99" は実在しない段
    # 【変異で意図的に破壊】: 検証を外すと存在しない nn でも受理され、ジョブが起動してしまう。
    assert result == {"status": "started"}
    session._job.join(timeout=5)


def test_request_refine_demo_records_stages_on_in_ledger_payload_and_still_recorded():
    session = WorkbenchSession.create_demo()
    result = session.request_refine(stages_on={"01": False})
    assert result == {"status": "recorded"}
    assert session.ledger.entries[-1].payload["stages_on"] == {"01": False}


def test_request_refine_passes_stages_on_and_clears_pending_occupancies_on_start(
    tmp_path, monkeypatch
):
    # 【nn を持つ project が必要】: 空の project (project_session fixture) は build_recipe が
    #   ValueError で stages=[] になり、stages_on の nn 検証が空集合になってしまう。
    project = _phaseid_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    captured: dict[str, object] = {}

    def fake_build(project, ledger=None, stages_on=None, initial_occupancies=None):
        captured["stages_on"] = stages_on
        captured["initial_occupancies"] = initial_occupancies
        return lambda: _fake_autorietveld_result(rwp=5.0, a=5.0, phase_name="nacl")

    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "build_default_runner", fake_build)
    session._pending_occupancies = {"nacl": {"O1": 0.5}}

    result = session.request_refine(stages_on={"01": False})
    assert result == {"status": "started"}
    session._job.join(timeout=5)

    assert captured["stages_on"] == {"01": False}
    assert captured["initial_occupancies"] == {"nacl": {"O1": 0.5}}
    # A3: 起動確定後は消費済みになる (次回 refine には持ち越さない)
    assert session._pending_occupancies == {}


def test_apply_structure_during_refine_snapshot_does_not_lose_revision(tmp_path, monkeypatch):
    """セルフレビュー指摘 #2 (ロック外競合): ``request_refine`` の「pending_occupancies
    スナップショット読取 → job 起動 → 起動確定後のみ clear」と ``apply_structure`` の書込みを
    同一 ``self._lock`` に揃えたことを、決定論的な並行性テストで実証する。

    ``build_default_runner`` (snapshot 読取の**直後**に呼ばれる, `session.py` 参照) をブロックする
    フェイクへ差し替え、その間に別スレッドから ``apply_structure`` を割り込ませる。ロックが効いて
    いれば apply はブロックされ (① で実証)、request_refine 再開後の clear が apply の新しい
    revision を巻き込まずに済む (② で実証)。``apply_structure``/``request_refine`` いずれか片方でも
    ``with self._lock:`` を外す変異を入れると、① (即完了してしまう) または ② (0.9 が {} に消える)
    のいずれかで fail することを手動確認済み。
    """
    project = _phaseid_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    session._site_phase_map = {"s1": "nacl"}  # id→相名 (セルフレビュー指摘 #3, label ではない)
    session._pending_occupancies = {"nacl": {"O1": 0.5}}

    entered_build = threading.Event()
    proceed_build = threading.Event()

    def fake_build(project, ledger=None, stages_on=None, initial_occupancies=None):
        # request_refine のスナップショット読取 (self._pending_occupancies のコピー) は本関数
        # 呼び出しより前に完了している (session.py の request_refine 参照) — ここで一時停止する
        # ことで、別スレッドの apply_structure が「読取後・clear 前」の隙間に割り込む機会を作る。
        entered_build.set()
        proceed_build.wait(timeout=5)
        return lambda: _fake_autorietveld_result(rwp=5.0, a=5.0, phase_name="nacl")

    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "build_default_runner", fake_build)

    refine_result: dict[str, object] = {}

    def do_refine():
        refine_result["value"] = session.request_refine()

    refine_thread = threading.Thread(target=do_refine)
    refine_thread.start()
    assert entered_build.wait(timeout=5)

    apply_done = threading.Event()

    def do_apply():
        session.apply_structure([{"id": "s1", "label": "O1", "occ": "0.9"}])
        apply_done.set()

    apply_thread = threading.Thread(target=do_apply)
    apply_thread.start()

    # ①【ロックによる直列化の実証】: request_refine がクリティカルセクションを保持中は
    #   apply_structure が完了できないはず (ロックを外す変異ではここが即完了し fail する)。
    assert not apply_done.wait(timeout=0.3), (
        "apply_structure が refine のクリティカルセクション中に完了した = ロックが効いていない"
    )

    proceed_build.set()
    refine_thread.join(timeout=5)
    apply_thread.join(timeout=5)
    session._job.join(timeout=5)

    assert refine_result["value"] == {"status": "started"}
    assert apply_done.is_set()
    # ②【revision 非消失の実証】: apply の新しい revision (0.9) は、snapshot 済みの古い値 (0.5) の
    #   clear に巻き込まれず残っている (次回 refine の initial_occupancies として使われる)。
    assert session._pending_occupancies == {"nacl": {"O1": 0.9}}


# ---------------------------------------------------------------------------
# A3: apply_structure → pending occ revisions
# ---------------------------------------------------------------------------


def test_apply_structure_records_pending_occupancies_via_site_phase_map(
    project_session: WorkbenchSession,
):
    # id→相名 (セルフレビュー指摘 #3): _site_phase_map は site の一意 id をキーにする。
    project_session._site_phase_map = {"s1": "phaseA", "s2": "phaseA"}

    project_session.apply_structure(
        [
            {"id": "s1", "label": "O1", "occ": "0.55"},
            {"id": "s2", "label": "Ca1", "occ": "1.0"},
            {"id": "s99", "label": "Unknown1", "occ": "0.9"},  # 直近抽出に無い id は無視
        ]
    )

    assert project_session._pending_occupancies == {
        "phaseA": {"O1": 0.55, "Ca1": 1.0}
    }


def test_apply_structure_routes_colliding_labels_across_phases_by_unique_id(
    project_session: WorkbenchSession,
):
    """セルフレビュー指摘 #3: 多相で同じ label ("O1") を持つ 2 サイトが別々の相にあっても、
    id ルーティングにより両方の occ 編集が正しい相へ配信されること (label キーの中間辞書だと
    後勝ちで一方が消える回帰の恒久ガード)。
    """
    project_session._site_phase_map = {"s1": "phaseA", "s7": "phaseB"}

    result = project_session.apply_structure(
        [
            {"id": "s1", "label": "O1", "occ": "0.40"},  # phaseA の O1
            {"id": "s7", "label": "O1", "occ": "0.80"},  # phaseB の (別サイトの) O1 — label 衝突
        ]
    )

    assert "error" not in result
    assert project_session._pending_occupancies == {
        "phaseA": {"O1": 0.40},
        "phaseB": {"O1": 0.80},
    }


def test_apply_structure_demo_does_not_touch_pending_occupancies():
    session = WorkbenchSession.create_demo()
    session.apply_structure([{"label": "K1", "occ": "0.5"}])
    assert session._pending_occupancies == {}


# ---------------------------------------------------------------------------
# A4: 相同定ジョブ (POST /api/phaseid 相当)
# ---------------------------------------------------------------------------


def test_request_phaseid_invalid_mode_returns_422_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.request_phaseid(mode="bogus")  # type: ignore[arg-type]
    assert result["error_type"] == "ValueError"


def test_request_phaseid_without_project_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.request_phaseid(mode="pattern")
    assert result["error_type"] == "ValueError"


def test_request_phaseid_residual_mode_without_prior_refine_returns_409(
    project_session: WorkbenchSession,
):
    result = project_session.request_phaseid(mode="residual")
    assert result["error_type"] == "ConflictError"


def test_request_phaseid_missing_mp_key_returns_422_error_dict(
    project_session: WorkbenchSession, monkeypatch
):
    project_session._fit["plot"] = {"h0": {"x": [1.0], "yobs": [2.0], "residual": None}}

    import tsumugin.mp.client as mp_client_module

    def _raise(*a, **kw):
        raise ValueError("no MATERIALS_PROJECT_API key")

    monkeypatch.setattr(mp_client_module, "MPRestClient", _raise)

    result = project_session.request_phaseid(mode="pattern")
    assert result["error_type"] == "ValueError"


class TestRequestPhaseidWithInjectedProvider:
    """provider 注入ユニットテスト (§4.5: 実運用は MPReferenceProvider のみ, ここはテスト専用)。"""

    def test_pattern_mode_populates_candidates_with_mp_id(self, tmp_path):
        pytest.importorskip("pymatgen")
        project = _phaseid_project(tmp_path)
        session = WorkbenchSession.from_project(project)

        from tsumugin.reference.model import ReferencePhase
        from tsumugin.search.peaks import Peak

        positions = [20.0, 35.0, 52.0]
        target = ReferencePhase(
            phase_id="mp-1", formula="NaCl", element_system=("Cl", "Na"),
            peaks=tuple(Peak(position=p, height=100.0) for p in positions),
            energy_above_hull=0.0,
        )
        tt, obs = _synthetic_pattern(positions)
        session._fit["plot"] = {
            "h0": {"x": tt.tolist(), "yobs": obs.tolist(), "residual": None}
        }

        result = session.request_phaseid(
            mode="pattern", top_k=3, _provider=_FakeReferenceProvider([target])
        )
        assert result == {"status": "started"}
        session._job.join(timeout=5)

        vm = session.viewmodel()
        candidates = vm["phase_id"]["candidates"]
        assert len(candidates) == 1
        assert candidates[0]["formula"] == "NaCl"
        assert candidates[0]["mp_id"] == "mp-1"
        assert candidates[0]["rank"] == 1
        assert candidates[0]["guard_fail"] is False

        assert any(e.kind == "phaseid_finished" for e in session.ledger.entries)

    def test_no_matching_phase_yields_empty_candidates(self, tmp_path):
        pytest.importorskip("pymatgen")
        project = _phaseid_project(tmp_path)
        session = WorkbenchSession.from_project(project)
        import numpy as np

        tt = np.linspace(10.0, 80.0, 500)
        noise = 5.0 + 0.01 * tt
        session._fit["plot"] = {
            "h0": {"x": tt.tolist(), "yobs": noise.tolist(), "residual": None}
        }

        result = session.request_phaseid(
            mode="pattern", _provider=_FakeReferenceProvider([])
        )
        assert result == {"status": "started"}
        session._job.join(timeout=5)

        assert session.viewmodel()["phase_id"]["candidates"] == []


def test_phaseid_running_reports_kind_phaseid_in_shared_job_status(tmp_path):
    """セルフレビュー指摘 #1: phaseid 実行中は共有ジョブ status の kind が "phaseid" になる。

    ``refine_status()`` は GET /api/refine/status・/api/phaseid/status・/api/multistart/status の
    3 ルート共通の実装 (`app.py` がそのまま返す) なので、ここでの検証はそのままエンドポイント
    契約の検証になる。
    """
    pytest.importorskip("pymatgen")
    project = _phaseid_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    # 【mode="pattern" の前提】: `TestRequestPhaseidWithInjectedProvider` と同じ合成パターン —
    # 平坦なダミー配列だと残差 S/N が閾値に届かず provider.fetch まで到達しない (started_evt が
    # 立たない = ブロックする前にジョブが即完了する)。
    tt, obs = _synthetic_pattern([20.0, 35.0, 52.0])
    session._fit["plot"] = {"h0": {"x": tt.tolist(), "yobs": obs.tolist(), "residual": None}}

    started_evt = threading.Event()
    release_evt = threading.Event()

    class _BlockingProvider:
        def fetch(self, elements):
            started_evt.set()
            release_evt.wait(timeout=5)
            return []

    result = session.request_phaseid(mode="pattern", _provider=_BlockingProvider())
    assert result == {"status": "started"}
    assert started_evt.wait(timeout=5)
    try:
        status = session.refine_status()
        assert status["status"] == "running"
        assert status["kind"] == "phaseid"
    finally:
        release_evt.set()
        session._job.join(timeout=5)

    assert session.refine_status()["kind"] == "phaseid"  # 完了後も直近種別を保持


def test_multistart_running_reports_kind_multistart_in_shared_job_status(tmp_path, monkeypatch):
    """セルフレビュー指摘 #1: multistart 実行中は共有ジョブ status の kind が "multistart" になる。"""
    hist = HistogramSpec(
        data_path=str(tmp_path / "hist.xy"),
        instrument_path=str(tmp_path / "hist.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / "phase.cif"), phase_name="phaseA")
    project = WorkbenchProject(name="ms-kind", histograms=(hist,), phases=(phase,))
    session = WorkbenchSession.from_project(project)

    started_evt = threading.Event()
    release_evt = threading.Event()

    def blocking_run_multistart_rietveld(*args, **kwargs):
        started_evt.set()
        release_evt.wait(timeout=5)
        raise RuntimeError("unused")

    import tsumugin.autorietveld.multistart as multistart_module

    monkeypatch.setattr(
        multistart_module, "run_multistart_rietveld", blocking_run_multistart_rietveld
    )

    result = session.request_multistart()
    assert result == {"status": "started"}
    assert started_evt.wait(timeout=5)
    try:
        status = session.refine_status()
        assert status["status"] == "running"
        assert status["kind"] == "multistart"
    finally:
        release_evt.set()
        session._job.join(timeout=5)


# ---------------------------------------------------------------------------
# A4/A5: refine/phaseid/multistart の共有ジョブ枠 (409) + 変異実証
# ---------------------------------------------------------------------------


def test_phaseid_returns_409_while_refine_running(project_session: WorkbenchSession):
    started, release = _block_refine(project_session)
    try:
        result = project_session.request_phaseid(mode="pattern")
        assert result["error_type"] == "ConflictError"
    finally:
        release.set()
        project_session._job.join(timeout=5)


def test_multistart_returns_409_while_refine_running(project_session: WorkbenchSession):
    started, release = _block_refine(project_session)
    try:
        result = project_session.request_multistart()
        assert result["error_type"] == "ConflictError"
    finally:
        release.set()
        project_session._job.join(timeout=5)


def test_refine_returns_409_while_multistart_running(project_session: WorkbenchSession):
    started_evt = threading.Event()
    release_evt = threading.Event()

    def blocking_runner():
        started_evt.set()
        release_evt.wait(timeout=5)
        raise RuntimeError("unused")

    project_session._job.start(blocking_runner, on_success=lambda r: None, on_failure=lambda e: None)
    started_evt.wait(timeout=5)
    try:
        result = project_session.request_refine()
        assert result["error_type"] == "ConflictError"
    finally:
        release_evt.set()
        project_session._job.join(timeout=5)


def test_shared_job_guard_mutation_would_not_conflict(
    project_session: WorkbenchSession, monkeypatch
):
    """RefinementJobManager.start を常に True へ変異させると、実行中でも 409 が消えることを示す
    (= 元の 409 が refine/phaseid/multistart 共有ジョブ枠の「実行中」チェックから来ていたことの証明)。
    """
    started, release = _block_refine(project_session)
    try:
        import tsumugin.workbench.jobs as jobs_module

        monkeypatch.setattr(jobs_module.RefinementJobManager, "start", lambda self, *a, **kw: True)
        result = project_session.request_multistart()
        # 【変異で意図的に破壊】: start が常に True を返すと refine 実行中でも受理されてしまう。
        assert "error" not in result
    finally:
        release.set()


# ---------------------------------------------------------------------------
# A4: ADD AS PHASE (phaseid_add)
# ---------------------------------------------------------------------------


def test_phaseid_add_without_project_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.phaseid_add(formula="NaCl", mp_id="mp-1")
    assert result["error_type"] == "ValueError"


def test_phaseid_add_missing_fields_returns_422(project_session: WorkbenchSession):
    result = project_session.phaseid_add(formula="", mp_id="mp-1")
    assert result["error_type"] == "ValueError"


def test_phaseid_add_materialization_failure_returns_error_dict(tmp_path, monkeypatch):
    pytest.importorskip("pymatgen")
    project = _phaseid_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    class _FailingMaterializer:
        def __init__(self, client):
            pass

        def materialize(self, *a, **kw):
            raise RuntimeError("mp lookup failed")

    import tsumugin.insitu.phaseid as phaseid_module
    import tsumugin.mp.client as mp_client_module

    monkeypatch.setattr(phaseid_module, "MPMaterializer", _FailingMaterializer)
    monkeypatch.setattr(mp_client_module, "MPRestClient", lambda *a, **kw: object())

    result = session.phaseid_add(formula="KCl", mp_id="mp-99")
    assert result["error_type"] == "ValueError"
    assert "mp lookup failed" in result["error"]


def test_phaseid_add_success_materializes_cif_and_adds_phase(tmp_path, monkeypatch):
    pytest.importorskip("pymatgen")
    project = _phaseid_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    class _FakeMaterializer:
        def __init__(self, client):
            pass

        def materialize(self, phase_id, elements, out_path, strain=0.0, cell=None):
            Path(out_path).write_text(_NACL_CIF, encoding="utf-8")
            return out_path

    import tsumugin.insitu.phaseid as phaseid_module
    import tsumugin.mp.client as mp_client_module

    monkeypatch.setattr(phaseid_module, "MPMaterializer", _FakeMaterializer)
    monkeypatch.setattr(mp_client_module, "MPRestClient", lambda *a, **kw: object())

    result = session.phaseid_add(formula="KCl", mp_id="mp-99")
    assert "error" not in result
    assert any(p.phase_name == "KCl" for p in session._project.phases)


# ---------------------------------------------------------------------------
# A5: マルチスタート (POST /api/multistart 相当)
# ---------------------------------------------------------------------------


def test_request_multistart_without_project_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.request_multistart()
    assert result["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# Tier1 sidecar (C1): status.gsas_available + GSAS 必須ジョブの 422 縮退
# ---------------------------------------------------------------------------


def test_state_status_includes_gsas_available(project_session: WorkbenchSession):
    # 【契約】: api-contract.md GET /api/state `status.gsas_available` は毎回動的評価 (この開発機は
    #   GSAS-II 導入済みなので True)。
    state = project_session.state()
    assert state["status"]["gsas_available"] is True


def test_request_refine_returns_422_gsas_unavailable_error_when_gsas_missing(
    project_session: WorkbenchSession, monkeypatch
):
    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "gsasii_available", lambda: False)
    result = project_session.request_refine()
    assert result["error_type"] == "GSASUnavailableError"


def test_request_multistart_returns_422_gsas_unavailable_error_when_gsas_missing(
    project_session: WorkbenchSession, monkeypatch
):
    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "gsasii_available", lambda: False)
    result = project_session.request_multistart()
    assert result["error_type"] == "GSASUnavailableError"


def test_request_sequential_returns_422_gsas_unavailable_error_when_gsas_missing(
    project_session: WorkbenchSession, monkeypatch
):
    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "gsasii_available", lambda: False)
    # frames 未設定でも gsas ガードが先に効くことを確認 (guard の順序: gsas → frames)。
    result = project_session.request_sequential(mode="forward")
    assert result["error_type"] == "GSASUnavailableError"


def test_request_refine_demo_mode_does_not_require_gsas(monkeypatch):
    # 【後方互換】: demo モードは実 GSAS を呼ばない従来経路 (ledger 追記のみ) なので、
    #   GSAS 不在でもブロックされない。
    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "gsasii_available", lambda: False)
    session = WorkbenchSession.create_demo()
    result = session.request_refine()
    assert result == {"status": "recorded"}


def test_on_multistart_success_populates_basin_points_and_corroborated_evidence(tmp_path):
    project = lifecycle.create_project("ms", str(tmp_path))
    project = dataclasses.replace(
        project, phases=(PhaseSpec(structure_path="p.cif", phase_name="phaseA"),)
    )
    session = WorkbenchSession.from_project(project)

    starts = (
        MultistartStart(
            index=0, cell_scale={"phaseA": (0.98, 0.98, 0.98)},
            result=_fake_autorietveld_result(rwp=6.5, a=9.30, phase_name="phaseA"),
        ),
        MultistartStart(
            index=1, cell_scale={"phaseA": (1.02, 1.02, 1.02)},
            result=_fake_autorietveld_result(rwp=6.6, a=9.31, phase_name="phaseA"),
        ),
    )
    result = RietveldMultistartResult(
        best=starts[0].result, best_index=0, starts=starts, n_starts=2, n_diverged=0,
        n_basins=1, is_global_corroborated=True,
    )

    session._on_multistart_success(result)

    hyp = session.hypotheses_view()
    assert hyp["basin"]["points"] == [
        {"x": 9.30, "y": 6.5, "label": "start 1"},
        {"x": 9.31, "y": 6.6, "label": "start 2"},
    ]
    assert any(row[0] == "corroborated" for row in hyp["evidence"])
    assert session.ledger.entries[-1].kind == "multistart_finished"
    assert session.ledger.entries[-1].payload["corroborated"] is True


def test_on_multistart_failure_appends_ledger_without_raising(project_session: WorkbenchSession):
    before = len(project_session.ledger.entries)
    project_session._on_multistart_failure(RuntimeError("boom"))
    assert len(project_session.ledger.entries) == before + 1
    assert project_session.ledger.entries[-1].kind == "multistart_failed"


# ---------------------------------------------------------------------------
# A6: gpx エクスポート
# ---------------------------------------------------------------------------


def test_export_gpx_info_without_project_returns_404_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.export_gpx_info()
    assert result["error_type"] == "NotFoundError"


def test_export_gpx_info_before_refine_returns_404(project_session: WorkbenchSession):
    result = project_session.export_gpx_info()
    assert result["error_type"] == "NotFoundError"


def test_export_gpx_info_after_gpx_written_returns_path_and_filename(
    project_session: WorkbenchSession,
):
    gpx_path = Path(project_session._project.gpx_path)
    gpx_path.parent.mkdir(parents=True, exist_ok=True)
    gpx_path.write_bytes(b"fake gpx contents")

    result = project_session.export_gpx_info()

    assert result["path"] == str(gpx_path)
    assert result["filename"] == f"{project_session._project.name}.gpx"


class TestStagesDefaultOnAndEmptyRecipeGuard:
    """A1 統合修正: recipe 由来ステージは「実行予定 = released True」既定、全段 OFF は 422。

    【背景】: GUI 通し実証で released=False 既定 → stageOn 同期 → stages_on 全 false →
    空 recipe の縮退 run (履歴空・Rwp なし・"done") が実際に発生した。縮退 run は
    「成功に見える無意味な実行」で最悪の失敗形。
    """

    def _project_session(self, tmp_path):
        from tsumugin.workbench import lifecycle

        project = lifecycle.create_project("stg", str(tmp_path))
        session = WorkbenchSession.open_persistent(project)
        src = (
            Path(__file__).resolve().parents[2]
            / "docs" / "benchmark" / "testdata" / "m9" / "cateo3"
        )
        session.add_histogram(
            data_path=str(src / "NB-LM01MO_030.XRDML"),
            instrument_path=str(src / "cateo3_CuKa.instprm"),
            radiation="xray_lab",
            geometry="bragg_brentano",
            data_format="XRDML",
            two_theta_limits=[12.0, 70.0],
        )
        session.add_phase(structure_path=str(src / "alpha_CaTeO3_H2O.cif"), phase_name="alpha")
        return session

    def test_recipe_stages_default_released_true(self, tmp_path) -> None:
        session = self._project_session(tmp_path)
        stages = session.viewmodel()["stages"]
        assert len(stages) > 0
        assert all(st["released"] is True for st in stages)

    def test_all_stages_off_is_rejected_not_degenerate_run(self, tmp_path) -> None:
        session = self._project_session(tmp_path)
        stages = session.viewmodel()["stages"]
        all_off = {st["nn"]: False for st in stages}
        result = session.request_refine(stages_on=all_off)
        assert "error" in result
        assert result["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# V2b 逐次/operando 接続 (B1-B5)
# ---------------------------------------------------------------------------

from tsumugin.insitu.model import FrameSpec  # noqa: E402


def _write_xy_v2b(path: Path, n: int = 10) -> None:
    lines = [f"{10.0 + i * 0.01:.4f} {100.0 + 5.0 * (i % 7):.2f}" for i in range(n)]
    path.write_text("\n".join(lines), encoding="utf-8")


def _sequential_project(tmp_path: Path, *, n_frames: int = 2, with_frames: bool = True) -> WorkbenchProject:
    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"),
        instrument_path=str(tmp_path / "d.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / "phase.cif"), phase_name="alpha")
    frames: tuple[FrameSpec, ...] = ()
    if with_frames:
        frames = tuple(
            FrameSpec(data_path=str(tmp_path / f"frame{i}.xy"), axis_value=float(i), data_format="XY")
            for i in range(n_frames)
        )
    return WorkbenchProject(
        name="seq fixture", histograms=(hist,), phases=(phase,), frames=frames,
        gpx_path=str(tmp_path / "refined.gpx"), spec_dir=str(tmp_path),
    )


def _fake_frame(
    idx: int, *, rwp: float = 8.0, changepoint: bool = False,
    alkali_feasibility: str = "", x_echem=None, residual_report=None,
    cells=None, wt=None,
) -> dict:
    return {
        "frame_index": idx, "axis_value": float(idx), "data_path": f"frame{idx}.xy",
        "rwp": rwp, "gof": 1.2, "phase_names": ["alpha"],
        "refined_cells": cells or {"alpha": [5.0, 5.0, 5.0, 90.0, 90.0, 90.0]},
        "phase_fractions": {"alpha": 1.0}, "changepoint": changepoint,
        "changepoint_reasons": ["rwp_jump"] if changepoint else [],
        "validity_passed": True, "refine_failed": False,
        "residual_report": residual_report,
        "phase_weight_fractions": wt if wt is not None else {"alpha": 1.0},
        "phase_weight_fraction_esd": {}, "cell_esd": {},
        "alkali_x_echem": x_echem, "alkali_x_xrd": None, "alkali_x_xrd_esd": None,
        "alkali_per_phase": {}, "alkali_residual": None,
        "alkali_constraint_applied": "", "alkali_feasibility": alkali_feasibility,
    }


def _fake_seq_result(frames: list, *, phase_names=("alpha",), anchors=None, crossovers=None, warnings=()) -> dict:
    out = {
        "phase_names": list(phase_names), "frames": frames, "appearances": [],
        "warnings": list(warnings),
    }
    if anchors is not None:
        out["anchors"] = anchors
    if crossovers is not None:
        out["crossovers"] = crossovers
    out["ledger_verified"] = True
    out["reason"] = ""
    return out


# --- B1: POST /api/project/frames (set_frames) --------------------------------------


def test_set_frames_without_project_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.set_frames([{"data_path": "x.xy"}])
    assert result["error_type"] == "ValueError"


def test_set_frames_rejects_non_list(project_session: WorkbenchSession):
    result = project_session.set_frames({"data_path": "x.xy"})
    assert result["error_type"] == "ValueError"


def test_set_frames_rejects_missing_data_file(project_session: WorkbenchSession):
    result = project_session.set_frames([{"data_path": "missing.xy", "data_format": "XY"}])
    assert result["error_type"] == "ValueError"
    assert project_session._project.frames == ()


def test_set_frames_stores_specs_and_appends_ledger(project_session: WorkbenchSession, tmp_path):
    _write_xy_v2b(tmp_path / "proj" / "frame0.xy")
    before = len(project_session.ledger.entries)

    result = project_session.set_frames(
        [{"data_path": "frame0.xy", "axis_value": 30.0, "data_format": "XY"}],
        frame_axis="temperature",
    )

    assert "error" not in result
    assert len(project_session._project.frames) == 1
    assert project_session._project.frame_axis == "temperature"
    assert len(project_session.ledger.entries) == before + 1
    assert project_session.ledger.entries[-1].kind == "project_edit"


def test_set_frames_full_replace_is_idempotent(project_session: WorkbenchSession, tmp_path):
    proj_dir = Path(project_session._project.spec_dir)
    _write_xy_v2b(proj_dir / "frame0.xy")
    _write_xy_v2b(proj_dir / "frame1.xy")

    project_session.set_frames([{"data_path": "frame0.xy", "data_format": "XY"}])
    assert len(project_session._project.frames) == 1

    project_session.set_frames(
        [{"data_path": "frame0.xy", "data_format": "XY"}, {"data_path": "frame1.xy", "data_format": "XY"}]
    )
    assert len(project_session._project.frames) == 2


def test_set_frames_guard_refining_returns_409(project_session: WorkbenchSession):
    started, release = _block_refine(project_session)
    try:
        result = project_session.set_frames([{"data_path": "x.xy"}])
        assert result["error_type"] == "ConflictError"
    finally:
        release.set()
        project_session._job.join(timeout=5)


def test_set_frames_reflects_frame_count_in_state_dataset(project_session: WorkbenchSession):
    proj_dir = Path(project_session._project.spec_dir)
    _write_xy_v2b(proj_dir / "frame0.xy")

    project_session.set_frames([{"data_path": "frame0.xy", "data_format": "XY"}])

    assert "1 frame(s)" in project_session.state()["project"]["dataset"]


# --- B2/B3: POST /api/sequential ------------------------------------------------------


def test_request_sequential_without_frames_returns_422(tmp_path):
    project = _sequential_project(tmp_path, with_frames=False)
    session = WorkbenchSession.from_project(project)
    result = session.request_sequential(mode="forward")
    assert result["error_type"] == "ValueError"


def test_request_sequential_frames_guard_mutation_would_not_reject(tmp_path, monkeypatch):
    """変異実証: frames 未設定 422 ガード (`_guard_frames_configured`) を無効化すると通ってしまう。"""
    project = _sequential_project(tmp_path, with_frames=False)
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(
        insitu_tools_module, "sequential_rietveld",
        lambda *a, **kw: _fake_seq_result([]),
    )
    monkeypatch.setattr(session, "_guard_frames_configured", lambda project: None)

    result = session.request_sequential(mode="forward")
    # 【変異で意図的に破壊】: ガードを無効化すると frames=() でもジョブが受理されてしまう。
    assert result == {"status": "started"}
    session._job.join(timeout=5)


def test_request_sequential_invalid_mode_returns_422(tmp_path):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    result = session.request_sequential(mode="bogus")
    assert result["error_type"] == "ValueError"


def test_request_sequential_anchored_without_anchor_table_returns_422(tmp_path):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    result = session.request_sequential(mode="anchored")
    assert result["error_type"] == "ValueError"


def test_request_sequential_forward_builds_instrument_spec_from_histograms0(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    captured = {}

    def fake_sequential_rietveld(frames, phases, *, instrument=None, charge_constraint=None):
        captured["frames"] = frames
        captured["phases"] = phases
        captured["instrument"] = instrument
        captured["charge_constraint"] = charge_constraint
        return _fake_seq_result([_fake_frame(0), _fake_frame(1)])

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", fake_sequential_rietveld)

    result = session.request_sequential(mode="forward")
    assert result == {"status": "started"}
    session._job.join(timeout=5)

    assert len(captured["frames"]) == 2
    assert captured["instrument"]["path"] == project.histograms[0].instrument_path
    assert captured["instrument"]["radiation"] == "xray_lab"
    assert captured["charge_constraint"] is None
    assert session.refine_status()["status"] == "done"
    assert session.refine_status()["kind"] == "sequential"


def test_request_sequential_emits_heartbeat_progress_ledger_entries_while_running(tmp_path, monkeypatch):
    """進捗可視化ハートビート: 長時間 runner の間、``sequential_progress`` が ledger に載る。

    api-contract.md は「進捗 = ledger (frame k/N)」を約束するが、実走で確認すると
    sequential_request → (無音) → sequential_finished/failed の間は ledger が一切動かず、
    数十分規模の実 GSAS 実行中に GUI が「動いているのか固まっているのか」を判別できない欠陥が
    あった (14 フレーム実データ検証で発見)。`request_sequential` の runner はハートビートスレッドで
    ``_SEQUENTIAL_HEARTBEAT_INTERVAL_S`` 間隔で ``sequential_progress`` を追記する — 本テストは
    その間隔を monkeypatch で短縮し、runner 実行中に 1 件以上現れ、runner 完了後は増え続けない
    (スレッドが確実に停止する) ことを確認する。
    """
    import tsumugin.workbench.session as session_module

    monkeypatch.setattr(session_module, "_SEQUENTIAL_HEARTBEAT_INTERVAL_S", 0.05)

    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def slow_fake_sequential_rietveld(frames, phases, **kw):
        time.sleep(0.3)  # ハートビート間隔 (0.05s) の複数倍だけ runner を「実行中」に保つ
        return _fake_seq_result([_fake_frame(0), _fake_frame(1)])

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", slow_fake_sequential_rietveld)

    result = session.request_sequential(mode="forward")
    assert result == {"status": "started"}
    session._job.join(timeout=5)

    assert session.refine_status()["status"] == "done"
    progress_entries = [e for e in session.ledger.entries if e.kind == "sequential_progress"]
    assert len(progress_entries) >= 1, "expected at least one heartbeat entry during a slow run"
    assert progress_entries[0].payload["mode"] == "forward"
    assert progress_entries[0].payload["n_frames"] == 2
    assert progress_entries[0].payload["elapsed_s"] >= 0.0

    n_after_done = len(progress_entries)
    time.sleep(0.3)  # スレッドが停止していれば、完了後に ledger エントリが増えないはず
    progress_entries_later = [e for e in session.ledger.entries if e.kind == "sequential_progress"]
    assert len(progress_entries_later) == n_after_done, (
        "heartbeat thread kept appending after runner completed (not stopped/joined correctly)"
    )

    ledger_view = session.ledger_view()
    hb_texts = [e["text"] for e in ledger_view["entries"] if e["text"].startswith("sequential running")]
    assert hb_texts and hb_texts[0].startswith("sequential running (mode=forward")


def test_request_sequential_anchored_calls_anchored_sequential_with_anchor_table(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    captured = {}

    def fake_anchored_sequential(frames, phases, *, anchor_table=None, instrument=None, charge_constraint=None, **kw):
        captured["anchor_table"] = anchor_table
        return _fake_seq_result(
            [_fake_frame(0), _fake_frame(1)],
            anchors=[{"frame": 0, "phases": ["alpha"], "rwp": 8.0, "confidence": 1.0, "fallback": False, "alkali": {}}],
            crossovers=[],
        )

    import tsumugin.mcp.anchor_tools as anchor_tools_module

    monkeypatch.setattr(anchor_tools_module, "anchored_sequential", fake_anchored_sequential)

    result = session.request_sequential(mode="anchored", anchor_table={"0": ["alpha"]})
    assert result == {"status": "started"}
    session._job.join(timeout=5)

    assert captured["anchor_table"] == {"0": ["alpha"]}
    vm = session.viewmodel()
    assert vm["sequence"]["anchors"] == [{"id": "fr000", "crossover": False}]


def test_on_sequential_success_populates_charts_and_frames_table(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def fake_sequential_rietveld(frames, phases, **kw):
        return _fake_seq_result(
            [_fake_frame(0, rwp=9.0), _fake_frame(1, rwp=8.0)]
        )

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", fake_sequential_rietveld)

    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    vm = session.viewmodel()
    seq = vm["sequence"]
    chart_ids = {c["id"] for c in seq["charts"]}
    assert chart_ids == {"rwp", "lattice", "phase_fraction"}
    rwp_chart = next(c for c in seq["charts"] if c["id"] == "rwp")
    assert rwp_chart["series"]["x"] == [0, 1]
    assert rwp_chart["series"]["ys"] == [[9.0, 8.0]]
    assert len(seq["frames"]) == 2
    assert seq["frames"][0]["frame"] == 0
    assert seq["frames"][0]["rwp"] == 9.0
    assert seq["frames"][0]["fractions"] == {"alpha": 1.0}


def test_on_sequential_success_infeasible_frame_adds_review_item_severity_echem(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def fake_sequential_rietveld(frames, phases, **kw):
        return _fake_seq_result(
            [_fake_frame(0, alkali_feasibility="infeasible", x_echem=0.5)]
        )

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", fake_sequential_rietveld)

    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    rows = session.review_view()
    echem_rows = [r for r in rows if r["severity"] == "echem"]
    assert len(echem_rows) == 1
    assert echem_rows[0]["ref"] == "FR-403"
    assert echem_rows[0]["state"] == "pending"


def test_on_sequential_success_changepoint_frame_creates_approval_card(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def fake_sequential_rietveld(frames, phases, **kw):
        return _fake_seq_result([_fake_frame(0, changepoint=True)])

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", fake_sequential_rietveld)

    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    vm = session.viewmodel()
    approvals = [t for t in vm["transcript"] if t["kind"] == "approval"]
    assert len(approvals) == 1
    assert approvals[0]["action_id"] == "np-0"
    assert approvals[0]["state"] == "pending"


def test_request_sequential_returns_409_while_job_running(tmp_path):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    started, release = _block_refine(session)
    try:
        result = session.request_sequential(mode="forward")
        assert result["error_type"] == "ConflictError"
    finally:
        release.set()
        session._job.join(timeout=5)


def test_sequential_failure_appends_ledger_and_status_failed(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def failing_sequential_rietveld(frames, phases, **kw):
        return {"error": "boom", "error_type": "RuntimeError"}

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", failing_sequential_rietveld)

    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    assert session.refine_status()["status"] == "failed"
    assert any(e.kind == "sequential_failed" for e in session.ledger.entries)


# --- B4: POST /api/echem --------------------------------------------------------------


def test_request_echem_without_project_returns_error_dict():
    session = WorkbenchSession.create_demo()
    result = session.request_echem(mpr_path="x.mpr")
    assert result["error_type"] == "ValueError"


def test_request_echem_align_error_returns_422(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.echem_tools as echem_tools_module

    monkeypatch.setattr(
        echem_tools_module, "align_echem",
        lambda *a, **kw: {"error": "galvani missing", "error_type": "EchemUnavailableError"},
    )

    result = session.request_echem(mpr_path="x.mpr", offset_s=0.0, interval_s=1.0)
    assert result["error_type"] == "ValueError"
    assert any(e.kind == "echem_failed" for e in session.ledger.entries)


def test_request_echem_populates_channels_and_state_echem(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def fake_align_echem(mpr_path, *, clamp=False, **kw):
        return {
            "curve": {"start_timestamp": 0.0, "n_points": 2, "duration_s": 100.0,
                      "voltage_min": 1.0, "voltage_max": 2.0, "source_path": mpr_path},
            "frames": [
                {"frame": 0, "time_s": 0.0, "time_h": 0.0, "voltage_v": 1.5,
                 "charge_mah": 10.0, "state": "charge", "in_span": True},
                {"frame": 1, "time_s": 283.0, "time_h": 0.08, "voltage_v": 1.8,
                 "charge_mah": 20.0, "state": "charge", "in_span": True},
            ],
            "n_in_span": 2, "reason": "",
        }

    import tsumugin.mcp.echem_tools as echem_tools_module

    monkeypatch.setattr(echem_tools_module, "align_echem", fake_align_echem)

    result = session.request_echem(mpr_path="x.mpr", offset_s=0.0, interval_s=283.0)
    assert "error" not in result
    assert result["targets"] is None

    channels = session.viewmodel()["channels"]
    echem_channel = next(c for c in channels if c["id"] == "echem")
    assert "1.8" in echem_channel["value"]
    assert session.state()["project"]["echem"]["v"] == 1.8


def test_request_echem_x0_without_mass_returns_422(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.echem_tools as echem_tools_module

    monkeypatch.setattr(
        echem_tools_module, "align_echem",
        lambda *a, **kw: {"curve": {}, "frames": [], "n_in_span": 0, "reason": ""},
    )

    result = session.request_echem(mpr_path="x.mpr", offset_s=0.0, interval_s=1.0, x0=1.9)
    assert result["error_type"] == "ValueError"


def test_request_echem_with_x0_calls_alkali_budget_and_supplies_targets(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.echem_tools as echem_tools_module

    monkeypatch.setattr(
        echem_tools_module, "align_echem",
        lambda *a, **kw: {"curve": {}, "frames": [
            {"frame": 0, "time_s": 0.0, "time_h": 0.0, "voltage_v": 1.5,
             "charge_mah": 0.0, "state": "rest", "in_span": True},
        ], "n_in_span": 1, "reason": ""},
    )
    captured = {}

    def fake_alkali_budget(mpr_path, active_mass_mg, formula_weight, *, x0, **kw):
        captured["active_mass_mg"] = active_mass_mg
        captured["formula_weight"] = formula_weight
        captured["x0"] = x0
        return {
            "targets": [{"frame": 0, "x_total": 1.9, "n_e": 0.0, "state": "rest", "in_span": True,
                         "time_h": 0.0, "voltage_v": 1.5, "charge_mah": 0.0}],
            "x0": x0, "x0_source": "given", "sign": 1, "warnings": [], "n_with_target": 1, "reason": "",
        }

    monkeypatch.setattr(echem_tools_module, "alkali_budget", fake_alkali_budget)

    result = session.request_echem(
        mpr_path="x.mpr", offset_s=0.0, interval_s=283.0, x0=1.944,
        active_mass_mg=19.628, formula_weight=678.8,
    )
    assert "error" not in result
    assert result["targets"][0]["x_total"] == 1.9
    assert captured["active_mass_mg"] == 19.628
    assert captured["x0"] == 1.944


# --- B5: 新相承認カード (approve/reject) -----------------------------------------------


def test_resolve_new_phase_approval_reject_records_ledger_no_add_phase(tmp_path, monkeypatch):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    def fake_sequential_rietveld(frames, phases, **kw):
        return _fake_seq_result([_fake_frame(0, changepoint=True)])

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", fake_sequential_rietveld)
    session.request_sequential(mode="forward")
    session._job.join(timeout=5)
    n_phases_before = len(session._project.phases)

    result = session.resolve_approval("np-0", decision="reject")
    assert result["state"] == "rejected"
    assert len(session._project.phases) == n_phases_before
    assert any(e.kind == "approval_decision" for e in session.ledger.entries)


def test_resolve_new_phase_approval_unknown_action_id_not_found(tmp_path):
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    result = session.resolve_approval("np-999", decision="reject")
    assert result["error_type"] == "NotFoundError"


def test_resolve_new_phase_approval_approve_reaches_add_phase(tmp_path, monkeypatch):
    """変異実証: approve → identify_and_add_phase → add_phase まで実際に到達することを検証する。

    ``WorkbenchSession.add_phase`` をスパイに差し替え、approve 経路がそれを呼ぶことを直接示す
    (呼ばれなければ ``called`` が空のまま残り、下のアサーションで検出される)。
    """
    pytest.importorskip("pymatgen")
    cif_path = tmp_path / "nacl.cif"
    cif_path.write_text(_NACL_CIF, encoding="utf-8")
    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"), instrument_path=str(tmp_path / "d.instprm"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(cif_path), phase_name="nacl")
    frame_path = tmp_path / "frame0.xy"
    tt, obs = _synthetic_pattern([20.0, 35.0, 52.0])
    frame_path.write_text(
        "\n".join(f"{x:.4f} {y:.4f}" for x, y in zip(tt.tolist(), obs.tolist())), encoding="utf-8"
    )
    frame = FrameSpec(data_path=str(frame_path), axis_value=0.0, data_format="XY")
    project = WorkbenchProject(
        name="approve fixture", histograms=(hist,), phases=(phase,), frames=(frame,),
        gpx_path=str(tmp_path / "refined.gpx"), spec_dir=str(tmp_path),
    )
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(
        insitu_tools_module, "sequential_rietveld",
        lambda frames, phases, **kw: _fake_seq_result([_fake_frame(0, changepoint=True)]),
    )
    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    called = {}
    original_add_phase = session.add_phase

    def spy_add_phase(*, structure_path, phase_name):
        called["structure_path"] = structure_path
        called["phase_name"] = phase_name
        return original_add_phase(structure_path=structure_path, phase_name=phase_name)

    monkeypatch.setattr(session, "add_phase", spy_add_phase)

    from tsumugin.reference.model import ReferencePhase
    from tsumugin.search.peaks import Peak

    class _FakeMaterializer:
        def __init__(self, client=None):
            pass

        def materialize(self, phase_id, elements, out_path, strain=0.0, cell=None):
            Path(out_path).write_text(_NACL_CIF, encoding="utf-8")
            return out_path

    class _FakeProvider:
        def fetch(self, elements):
            return [
                ReferencePhase(
                    phase_id="mp-1", formula="NaCl", element_system=("Cl", "Na"),
                    peaks=(Peak(position=20.0, height=100.0),), energy_above_hull=0.0,
                )
            ]

    import tsumugin.insitu.phaseid as phaseid_module
    import tsumugin.mp.provider as mp_provider_module

    monkeypatch.setattr(phaseid_module, "MPMaterializer", _FakeMaterializer)
    monkeypatch.setattr(mp_provider_module, "MPReferenceProvider", lambda *a, **kw: _FakeProvider())

    result = session.resolve_approval("np-0", decision="approve")

    assert "error" not in result
    assert result["state"] == "approved"
    assert called.get("phase_name") is not None
    assert any(p.phase_name == called["phase_name"] for p in session._project.phases)


# ---------------------------------------------------------------------------
# B5 / Issue #20: GUI 承認経路にも異方セル補正を通す
# ---------------------------------------------------------------------------


def _instprm_text(*lines: str) -> str:
    head = ["#GSAS-II instrument parameter file; do not add/delete items!", "Type:PXC", "Bank:1.0"]
    tail = ["Zero:0.0", "Polariz.:0.95", "Azimuth:0.0", "U:3.0", "V:-3.0", "W:30.0",
            "X:0.0", "Y:3.0", "Z:0.0", "SH/L:0.002"]
    return "\n".join(head + list(lines) + tail) + "\n"


#: 放射光 (SPring-8 BL02B2 相当) の単一波長 instprm。既定 Cu Kα1 (1.5406) と遠いので、
#: 「実波長を渡しているか」が既知相ピーク位置で明確に判別できる。
_SYNCHROTRON_INSTPRM = _instprm_text("Lam:0.799580")
#: Kα1/Kα2 の実験室 X 線 instprm (``Lam1``/``Lam2``)。ピーク位置の指標は Kα1 (``Lam1``)。
_KA12_INSTPRM = _instprm_text("Lam1:1.540500", "Lam2:1.544300")
#: TOF 中性子 instprm — 単一波長が無い (``difC`` 系)。2θ/λ 前提の補正は成立しない。
_TOF_INSTPRM = "\n".join(
    ["#GSAS-II instrument parameter file; do not add/delete items!",
     "Type:PNT", "Bank:1.0", "difC:5000.0", "difA:0.0", "difB:0.0", "Zero:0.0",
     "alpha:1.0", "beta-0:0.03", "beta-1:0.008", "beta-q:0.0", "sig-0:0.0", "sig-1:20.0"]
) + "\n"


def _np_prealign_session(
    tmp_path, monkeypatch, *, instprm_text: "str | None" = _SYNCHROTRON_INSTPRM,
    cells=None, phase_names=("alpha",),
):
    """np-0 が pending の実プロジェクトセッションを作る (Issue #20 承認経路テストの共通土台)。

    ``instprm_text`` が None なら instprm ファイルを**書かない** (波長が読めない系)。
    """
    prm = tmp_path / "d.instprm"
    if instprm_text is not None:
        prm.write_text(instprm_text, encoding="utf-8")
    cif = tmp_path / "alpha.cif"
    cif.write_text(_NACL_CIF, encoding="utf-8")
    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"), instrument_path=str(prm),
        radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER, data_format="XY",
    )
    phases = tuple(PhaseSpec(structure_path=str(cif), phase_name=n) for n in phase_names)
    frame_path = tmp_path / "frame0.xy"
    tt, obs = _synthetic_pattern([20.0, 35.0, 52.0])
    frame_path.write_text(
        "\n".join(f"{x:.4f} {y:.4f}" for x, y in zip(tt.tolist(), obs.tolist())), encoding="utf-8"
    )
    project = WorkbenchProject(
        name="prealign fixture", histograms=(hist,), phases=phases,
        frames=(FrameSpec(data_path=str(frame_path), axis_value=0.0, data_format="XY"),),
        gpx_path=str(tmp_path / "refined.gpx"), spec_dir=str(tmp_path),
    )
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(
        insitu_tools_module, "sequential_rietveld",
        lambda frames, phases_payload, **kw: _fake_seq_result(
            [_fake_frame(0, changepoint=True, cells=cells)], phase_names=list(phase_names)
        ),
    )
    session.request_sequential(mode="forward")
    session._job.join(timeout=5)
    return session


def _spy_identify(monkeypatch, captured: dict, *, found: "dict | None" = None):
    """② ``identify_and_add_phase`` を、渡された kwargs を記録するスパイに差し替える。"""
    import tsumugin.mcp.insitu_tools as insitu_tools_module

    def spy(two_theta, intensity, elements, workdir, **kw):
        captured.update(kw)
        captured["_called"] = True
        return found if found is not None else {
            "candidates": [], "n_candidates": 0,
            "prealign_basis": "residual" if kw.get("known_phases") else "skipped",
            "n_known_phases_used": len(kw.get("known_phases") or ()),
        }

    monkeypatch.setattr(insitu_tools_module, "identify_and_add_phase", spy)


class TestNewPhaseApprovalPrealign:
    """Issue #20: GUI から承認した相にも異方セル補正 (残差整合プリアライン) を通す。

    ② ``identify_and_add_phase`` は ``known_phases`` を渡されて初めて補正を行う
    (``prealign_basis="residual"``)。渡さないと MP(DFT) 素の格子のまま CIF が返り
    (実測 CaTeO3 delta: c 軸 +3.42%)、Rietveld の収束半径 ~2% を超えて Rwp が高止まりする。
    ③ (MCP) 経路だけ補正が入り GUI 承認だけ入らない**非対称**を塞ぐ。
    """

    def test_known_phases_carry_project_spec_and_refined_cell(self, tmp_path, monkeypatch):
        """承認経路は「そのフレームに既に居る相」を spec + 精密化格子として ② に渡す。

        変異実証: ``known_phases=`` を渡さない実装に戻すと ``known_phases`` が空になり fail。
        ``refined_cell`` の添付を落とすと DFT 格子のまま = 補正の意味が消えるので、こちらも fail。
        """
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(
            tmp_path, monkeypatch, cells={"alpha": [4.9, 5.1, 17.3, 90.0, 90.0, 90.0]}
        )
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        result = session.resolve_approval("np-0", decision="approve")

        assert "error" not in result
        known = captured.get("known_phases")
        assert known, "known_phases が ② に渡っていない (補正が skipped に落ちる)"
        assert [k["phase_name"] for k in known] == ["alpha"]
        assert known[0]["structure_path"] == str(tmp_path / "alpha.cif")
        assert known[0]["refined_cell"] == [4.9, 5.1, 17.3, 90.0, 90.0, 90.0]

    def test_wavelength_comes_from_instprm_not_cu_default(self, tmp_path, monkeypatch):
        """放射光プロジェクトでは instprm の実波長を渡す (既定 Cu Kα1 では既知相ピークが狂う)。

        変異実証: ``wavelength=`` を渡さない / 1.5406 を固定で渡す実装では fail。
        """
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch)
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        session.resolve_approval("np-0", decision="approve")

        assert captured.get("wavelength") == pytest.approx(0.799580)

    def test_wavelength_uses_lam1_for_ka12_instprm(self, tmp_path, monkeypatch):
        """Kα1/Kα2 instprm (``Lam1``/``Lam2``) では Kα1 を採る (ピーク位置の指標)。"""
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch, instprm_text=_KA12_INSTPRM)
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        session.resolve_approval("np-0", decision="approve")

        assert captured.get("wavelength") == pytest.approx(1.540500)

    @pytest.mark.parametrize(
        "instprm_text,label",
        [(None, "instprm 不在"), (_TOF_INSTPRM, "TOF (単一波長なし)")],
    )
    def test_unknown_wavelength_skips_correction_rather_than_guessing(
        self, tmp_path, monkeypatch, instprm_text, label
    ):
        """波長が決まらないなら ``known_phases`` を**渡さない** (誤波長で残差を壊さない)。

        既知相ピークを誤った波長で立てて引くと残差そのものが壊れ、プリアラインは壊れた残差へ
        整合してしまう — 補正なし (DFT 格子のまま) より悪い。補正を諦める方が安全側。

        変異実証: 波長不明でも Cu Kα1 既定のまま ``known_phases`` を渡す実装では fail。
        """
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch, instprm_text=instprm_text)
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        result = session.resolve_approval("np-0", decision="approve")

        assert captured.get("_called"), f"{label}: ② が呼ばれていない"
        assert not captured.get("known_phases"), f"{label}: 誤波長で既知相を渡している"
        assert "error" not in result  # 同定自体は続行する (補正なしに縮退するだけ)

    def test_nonfinite_refined_cell_degrades_to_dft_cell_not_error(self, tmp_path, monkeypatch):
        """発散フレームの非有限セルは ``refined_cell`` を落として渡す (② の形検証で全体を失敗させない)。

        ② ``_parse_known_phases`` は非有限 ``refined_cell`` を ValueError にする (呼び手の意図を
        ②からは判別できないため正しい)。③ 側では「その相の精密化が発散した」と判っているので、
        主張しない (None) へ縮退させ、他の相の補正は生かす。

        変異実証: 非有限セルをそのまま渡す実装だと ② が error dict を返し承認が失敗する。
        """
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(
            tmp_path, monkeypatch,
            cells={"alpha": [float("nan"), 5.1, 17.3, 90.0, 90.0, 90.0],
                   "beta": [3.0, 3.0, 3.0, 90.0, 90.0, 90.0]},
            phase_names=("alpha", "beta"),
        )
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        result = session.resolve_approval("np-0", decision="approve")

        assert "error" not in result
        known = {k["phase_name"]: k for k in captured.get("known_phases") or ()}
        assert known["alpha"]["refined_cell"] is None  # 発散した相は格子を主張しない
        assert known["beta"]["refined_cell"] == [3.0, 3.0, 3.0, 90.0, 90.0, 90.0]

    def test_ledger_records_prealign_basis_so_gui_can_see_it(self, tmp_path, monkeypatch):
        """LEDGER タブに「補正が入ったのか」を残す (Rwp が下がらない時の第一容疑を可視化)。

        変異実証: ledger payload から ``prealign_basis`` を落とすと fail。
        """
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch)
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        session.resolve_approval("np-0", decision="approve")

        decisions = [e for e in session.ledger.entries if e.kind == "approval_decision"]
        assert decisions
        payload = decisions[-1].payload
        assert payload["prealign_basis"] == "residual"
        assert payload["n_known_phases_used"] == 1
        assert payload["wavelength"] == pytest.approx(0.799580)

    def test_ledger_records_skipped_basis_when_wavelength_unknown(self, tmp_path, monkeypatch):
        """補正を諦めたときも黙らない — ``prealign_basis="skipped"`` を ledger に残す。"""
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch, instprm_text=None)
        captured: dict = {}
        _spy_identify(monkeypatch, captured)

        session.resolve_approval("np-0", decision="approve")

        payload = [e for e in session.ledger.entries if e.kind == "approval_decision"][-1].payload
        assert payload["prealign_basis"] == "skipped"
        assert payload["wavelength"] is None

    def test_ledger_view_text_exposes_prealign_to_the_gui(self, tmp_path, monkeypatch):
        """③ 露出: LEDGER タブ (``ledger_view``) の文面にも補正の有無を出す。

        ``ledger_view`` は payload を返さず ``text`` だけを返すので、payload に足しただけでは
        GUI に届かない (足したのに見えない = 実質未露出)。

        変異実証: ``_text_for_kind`` の approval_decision を元の 1 行に戻すと fail。
        """
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch)
        _spy_identify(monkeypatch, {})

        session.resolve_approval("np-0", decision="approve")

        texts = [e["text"] for e in session.ledger_view()["entries"] if "approval np-0" in e["text"]]
        assert texts, "approval エントリが LEDGER タブに出ていない"
        assert "cell prealign: residual" in texts[-1]
        assert "0.79958" in texts[-1]  # 実波長も見える (Cu Kα1 で走っていないことが判る)

    def test_ledger_view_text_says_dft_cell_kept_when_skipped(self, tmp_path, monkeypatch):
        """補正なしのときは「DFT 格子のまま」と明示する (沈黙は偽の正常応答になる)。"""
        pytest.importorskip("pymatgen")
        session = _np_prealign_session(tmp_path, monkeypatch, instprm_text=None)
        _spy_identify(monkeypatch, {})

        session.resolve_approval("np-0", decision="approve")

        text = [e["text"] for e in session.ledger_view()["entries"] if "approval np-0" in e["text"]][-1]
        assert "cell prealign: skipped" in text
        assert "DFT cell kept" in text

    def test_payload_round_trips_through_the_real_second_layer_parser(self, tmp_path, monkeypatch):
        """③→② 到達可能性: 組んだ ``known_phases`` を ② の**実**パーサが受理する。

        他のテストは ② をスパイに差し替えるので、形が ② の契約とずれていても気づけない
        (`_parse_known_phases` は形の誤りを error dict にするだけで、承認は「候補 0 で成功」に
        見えてしまう)。ここだけは実物を通して spec/格子が復元されることを確かめる。

        変異実証: ``refined_cell`` を ``[a,b,c]`` 3 要素や dict で渡す実装にすると ② が
        ValueError を投げて fail。
        """
        from tsumugin.mcp.insitu_tools import _parse_known_phases
        from tsumugin.workbench.session import _known_phases_payload

        project = _sequential_project(tmp_path)
        seq = _fake_seq_result(
            [_fake_frame(0, cells={"alpha": [4.9, 5.1, 17.3, 90.0, 90.0, 90.0]}),
             _fake_frame(1, cells={"alpha": [4.8, 5.0, 17.0, 90.0, 90.0, 90.0]})]
        )

        parsed = _parse_known_phases(_known_phases_payload(project, seq, 1))

        assert len(parsed) == 1
        spec, cell = parsed[0]
        assert spec.phase_name == "alpha"
        assert spec.structure_path == str(tmp_path / "phase.cif")
        # 位置ではなく frame_index で引く — frame 1 の格子が復元されること
        assert cell == (4.8, 5.0, 17.0, 90.0, 90.0, 90.0)

    def test_payload_frame_lookup_is_by_index_not_position(self, tmp_path):
        """``frames`` が全フレームを含まない (max_frames 等) 系列でも取り違えない。"""
        from tsumugin.workbench.session import _known_phases_payload

        project = _sequential_project(tmp_path)
        seq = _fake_seq_result([_fake_frame(7, cells={"alpha": [7.0, 7.0, 7.0, 90.0, 90.0, 90.0]})])

        assert _known_phases_payload(project, seq, 7)[0]["refined_cell"] == [7.0, 7.0, 7.0, 90.0, 90.0, 90.0]
        assert _known_phases_payload(project, seq, 0)[0]["refined_cell"] is None

    def test_payload_without_sequential_result_still_lists_known_phases(self, tmp_path):
        """逐次結果が無くても既知相そのものは渡す (DFT 格子でも残差減算の相手にはなる)。"""
        from tsumugin.workbench.session import _known_phases_payload

        project = _sequential_project(tmp_path)
        payload = _known_phases_payload(project, None, 0)

        assert [p["phase_name"] for p in payload] == ["alpha"]
        assert payload[0]["refined_cell"] is None

    def test_ledger_view_text_unchanged_for_non_prealign_approvals(self, tmp_path, monkeypatch):
        """prealign 情報を持たない承認 (reject / 他機構の sr-/pc- 等) の文面は変えない。"""
        session = _np_prealign_session(tmp_path, monkeypatch)

        session.resolve_approval("np-0", decision="reject")

        text = [e["text"] for e in session.ledger_view()["entries"] if "approval np-0" in e["text"]][-1]
        assert text == "approval np-0 reject"


class TestInstprmWavelength:
    """``_instprm_wavelength``: GSAS ``.instprm`` から単一波長 (Å) を読む (Issue #20)。"""

    def test_reads_lam(self, tmp_path):
        from tsumugin.workbench.session import _instprm_wavelength

        p = tmp_path / "a.instprm"
        p.write_text(_SYNCHROTRON_INSTPRM, encoding="utf-8")
        assert _instprm_wavelength(str(p)) == pytest.approx(0.799580)

    def test_prefers_lam1_over_lam2(self, tmp_path):
        from tsumugin.workbench.session import _instprm_wavelength

        p = tmp_path / "a.instprm"
        p.write_text(_KA12_INSTPRM, encoding="utf-8")
        assert _instprm_wavelength(str(p)) == pytest.approx(1.540500)

    @pytest.mark.parametrize("text", [_TOF_INSTPRM, "Type:PXC\nLam:not-a-number\n", "", "Lam:0.0\n"])
    def test_returns_none_when_no_usable_wavelength(self, tmp_path, text):
        """TOF/壊れた値/空/非正値は None (呼び手はこれを見て補正を諦める)。"""
        from tsumugin.workbench.session import _instprm_wavelength

        p = tmp_path / "a.instprm"
        p.write_text(text, encoding="utf-8")
        assert _instprm_wavelength(str(p)) is None

    def test_returns_none_when_file_missing(self, tmp_path):
        from tsumugin.workbench.session import _instprm_wavelength

        assert _instprm_wavelength(str(tmp_path / "nope.instprm")) is None


class TestNewPhaseApprovalErrorPaths:
    """B5 実走で発見の 2 欠陥の回帰ガード。

    (1) ② identify_and_add_phase の既定 provider が client 無し構築で TypeError 即死
        (DOA, §4.5) — 例外は境界で error dict に縮退し、承認カードは pending のまま。
    (2) ② が error dict を返したとき「承認済み・候補 0」と誤読しない (失敗を正常と
        答えるのは最悪の失敗形)。
    """

    def _session_with_pending(self, tmp_path, monkeypatch):
        from tsumugin.workbench import lifecycle

        project = lifecycle.create_project("np", str(tmp_path))
        session = WorkbenchSession.open_persistent(project)
        src = (
            Path(__file__).resolve().parents[2]
            / "docs" / "benchmark" / "testdata" / "m9" / "cateo3"
        )
        session.add_histogram(
            data_path=str(src / "NB-LM01MO_030.XRDML"),
            instrument_path=str(src / "cateo3_CuKa.instprm"),
            radiation="xray_lab", geometry="bragg_brentano", data_format="XRDML",
            two_theta_limits=[12.0, 70.0],
        )
        session.add_phase(structure_path=str(src / "alpha_CaTeO3_H2O.cif"), phase_name="alpha")
        # 承認カードを直接シード (逐次実行を経ずに B5 経路のみ検証)。
        # pending = transcript にあり _approvals に無い、が実装の状態機械。
        hist = session.viewmodel()["project"]["histograms"][0]
        session._np_approval_info["np-0"] = {
            "frame_index": 0, "data_path": hist["data_path"],
            "data_format": hist["data_format"],
        }
        session._transcript.append({
            "id": "t1", "kind": "approval", "action_id": "np-0",
            "title": "frame 0: 新相の可能性", "rationale": "", "action_json": "{}",
            "state": "pending",
        })
        return session

    def test_identify_exception_degrades_to_error_dict_and_stays_pending(
        self, tmp_path, monkeypatch
    ) -> None:
        session = self._session_with_pending(tmp_path, monkeypatch)
        import tsumugin.mcp.insitu_tools as it

        def boom(*a, **k):
            raise TypeError("missing 1 required positional argument: 'client'")

        monkeypatch.setattr(it, "identify_and_add_phase", boom)
        result = session.resolve_approval("np-0", decision="approve")
        assert "error" in result
        assert "np-0" not in session._approvals  # pending のまま (再試行可能)

    def test_identify_error_dict_is_not_treated_as_success(self, tmp_path, monkeypatch) -> None:
        session = self._session_with_pending(tmp_path, monkeypatch)
        import tsumugin.mcp.insitu_tools as it

        monkeypatch.setattr(
            it, "identify_and_add_phase",
            lambda *a, **k: {"error": "MP key missing", "error_type": "ValueError"},
        )
        result = session.resolve_approval("np-0", decision="approve")
        assert "error" in result and "MP key missing" in result["error"]
        assert "np-0" not in session._approvals  # pending のまま (再試行可能)


# --- B1 レビュー指摘: frames 全置換で旧逐次結果/np カードを整理する ------------------------


def test_set_frames_clears_stale_sequence_and_np_approvals(tmp_path, monkeypatch):
    """フレーム全置換後は sequence が空状態に戻り、旧フレームの np- 承認カードが消える。

    同じ frame_index (0) が次回逐次実行で再び changepoint と判定されれば、新しい np-0
    カードが再生成されることも併せて検証する — 置換前の解決状態 (``_np_approval_info``/
    ``_approvals``/transcript の pending カード) が残って再提案をブロックしないことの確認。
    """
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(
        insitu_tools_module, "sequential_rietveld",
        lambda frames, phases, **kw: _fake_seq_result([_fake_frame(0, changepoint=True)]),
    )
    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    vm = session.viewmodel()
    assert vm["sequence"]["frames"]
    approvals_before = [t for t in vm["transcript"] if t["kind"] == "approval"]
    assert any(a["action_id"] == "np-0" for a in approvals_before)
    assert session._sequential_result is not None
    assert session._sequence is not None
    assert session._np_approval_info

    proj_dir = Path(session._project.spec_dir)
    _write_xy_v2b(proj_dir / "newframe0.xy")

    result = session.set_frames([{"data_path": "newframe0.xy", "data_format": "XY"}])
    assert "error" not in result

    assert session._sequential_result is None
    assert session._sequence is None
    assert session._np_approval_info == {}
    assert "np-0" not in session._approvals

    vm2 = session.viewmodel()
    from tsumugin.workbench.session import _EMPTY_SEQUENCE

    assert vm2["sequence"] == _EMPTY_SEQUENCE
    approvals_after = [t for t in vm2["transcript"] if t["kind"] == "approval"]
    assert not any(a["action_id"] == "np-0" for a in approvals_after)

    # 同じ frame_index (0) が再び changepoint と判定されれば、新しい np-0 カードが再生成される
    # (旧カードが _np_approval_info/_approvals/transcript のいずれかに残っていると
    # `_create_new_phase_approvals` の重複防止チェックに引っかかり再生成されない)。
    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    vm3 = session.viewmodel()
    approvals_regenerated = [t for t in vm3["transcript"] if t["kind"] == "approval"]
    assert any(
        a["action_id"] == "np-0" and a["state"] == "pending" for a in approvals_regenerated
    )


def test_set_frames_preserves_unrelated_approvals(tmp_path, monkeypatch):
    """np- 以外の承認カード (例: 構造編集提案) は frames 置換で消えない。"""
    project = _sequential_project(tmp_path)
    session = WorkbenchSession.from_project(project)
    session._transcript.append(
        {
            "id": "t-other", "kind": "approval", "action_id": "a1",
            "title": "unrelated", "rationale": "", "action_json": "{}", "state": "pending",
        }
    )

    proj_dir = Path(session._project.spec_dir)
    _write_xy_v2b(proj_dir / "newframe0.xy")
    result = session.set_frames([{"data_path": "newframe0.xy", "data_format": "XY"}])
    assert "error" not in result

    ids = [m["action_id"] for m in session._transcript if m.get("kind") == "approval"]
    assert "a1" in ids


def test_resolve_new_phase_approval_double_approve_returns_409_while_in_progress(tmp_path, monkeypatch):
    """変異実証: check-and-set マーカーを外すと、実行中の 2 回目呼び出しが 409 でなく通って
    ``identify_and_add_phase`` を二重実行してしまう (`resolve_approval` の np- 分岐参照)。

    ``_elements_from_project`` が空 (元素導出不能) だと ``identify_and_add_phase`` を呼ぶ前に
    早期 return してしまう (`test_resolve_new_phase_approval_approve_reaches_add_phase` と同じ
    落とし穴) ため、実在する CIF を持つ相集合を組み立てる。
    """
    pytest.importorskip("pymatgen")
    cif_path = tmp_path / "nacl.cif"
    cif_path.write_text(_NACL_CIF, encoding="utf-8")
    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"), instrument_path=str(tmp_path / "d.instprm"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(cif_path), phase_name="nacl")
    frame_path = tmp_path / "frame0.xy"
    tt, obs = _synthetic_pattern([20.0, 35.0, 52.0])
    frame_path.write_text(
        "\n".join(f"{x:.4f} {y:.4f}" for x, y in zip(tt.tolist(), obs.tolist())), encoding="utf-8"
    )
    frame = FrameSpec(data_path=str(frame_path), axis_value=0.0, data_format="XY")
    project = WorkbenchProject(
        name="double approve fixture", histograms=(hist,), phases=(phase,), frames=(frame,),
        gpx_path=str(tmp_path / "refined.gpx"), spec_dir=str(tmp_path),
    )
    session = WorkbenchSession.from_project(project)

    import tsumugin.mcp.insitu_tools as insitu_tools_module

    monkeypatch.setattr(
        insitu_tools_module, "sequential_rietveld",
        lambda frames, phases, **kw: _fake_seq_result([_fake_frame(0, changepoint=True)]),
    )
    session.request_sequential(mode="forward")
    session._job.join(timeout=5)

    started = threading.Event()
    release = threading.Event()
    call_count = {"n": 0}

    def blocking_identify(*a, **k):
        call_count["n"] += 1
        started.set()
        release.wait(timeout=5)
        return {"error": "still identifying (test canary)", "error_type": "ValueError"}

    monkeypatch.setattr(insitu_tools_module, "identify_and_add_phase", blocking_identify)

    results: dict[str, dict] = {}

    def run_first():
        results["first"] = session.resolve_approval("np-0", decision="approve")

    t = threading.Thread(target=run_first)
    t.start()
    assert started.wait(timeout=5)

    second = session.resolve_approval("np-0", decision="approve")

    release.set()
    t.join(timeout=5)

    assert second["error_type"] == "ConflictError"
    assert "error" in results["first"]
    assert call_count["n"] == 1  # 二重実行していない (変異させると 2 になる)
    # エラー経路なのでマーカーは pop され、pending に戻って再試行できる。
    assert "np-0" not in session._approvals


class TestAgentIdleReflectsTurnStatus:
    """state.agent.idle は「ターンが走っていないこと」(実走スモークで発見の回帰)。

    旧実装は ``mode == "manual"`` を idle としていたため、AUTO でターンが完了しても
    idle=false のまま固着し、UI からはエージェントが動き続けているように見えた。
    """

    def test_idle_true_in_auto_when_no_turn_running(self) -> None:
        session = WorkbenchSession.create_demo()
        session.set_mode("auto")
        assert session.state()["agent"]["idle"] is True

    def test_idle_false_while_turn_running(self, monkeypatch) -> None:
        session = WorkbenchSession.create_demo()
        session.set_mode("auto")
        monkeypatch.setattr(
            session._agent_bridge,
            "status",
            lambda: {
                "status": "running", "available": True, "tokens": 5, "wall_time_s": 1.0,
                "error": None,
            },
        )
        assert session.state()["agent"]["idle"] is False


# ---------------------------------------------------------------------------
# V3b: MEM 密度マップ (FR-601, POST /api/mem, GET /api/mem/status)
# ---------------------------------------------------------------------------


def _mem_project(tmp_path: Path, *, write_gpx: bool = True) -> WorkbenchProject:
    """MEM ジョブ用の project フィクスチャ (gpx_path を実在ファイルにする)。"""
    gpx_path = tmp_path / "refined.gpx"
    if write_gpx:
        gpx_path.write_bytes(b"")  # 存在だけを見る (実 mem_density はテストで monkeypatch する)
    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"), instrument_path=str(tmp_path / "d.instprm"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / "p.cif"), phase_name="p1")
    return WorkbenchProject(
        name="mem fixture", histograms=(hist,), phases=(phase,),
        gpx_path=str(gpx_path), spec_dir=str(tmp_path),
    )


def _fake_mem_result(grd_path: str, *, n_peaks: int = 1) -> dict[str, Any]:
    """``mcp.mem_tools.mem_density`` の戻り値の代役 (成功系)。"""
    peaks = [{"frac": [0.5, 0.25, 0.0], "magnitude": 0.82, "nearest_atom": "Ow1", "distance": 1.5}]
    return {
        "density_kind": "electron",
        "density_min": -0.5,
        "density_max": 3.2,
        "pre_min": -0.1,
        "pre_max": 2.0,
        "n_reflections": 42,
        "converged": True,
        "mem_r_factor": 0.03,
        "grd_path": grd_path,
        "peaks": peaks[:n_peaks],
    }


class TestRequestMem:
    """``request_mem`` (POST /api/mem) の起動ガード + 成功/失敗経路。"""

    def test_without_project_returns_error_dict(self):
        session = WorkbenchSession.create_demo()
        result = session.request_mem()
        assert result["error_type"] == "ValueError"

    def test_without_refined_gpx_returns_422_value_error(self, project_session: WorkbenchSession):
        # project_session (lifecycle.create_project) は gpx_path を持つが未生成 (refine 前)。
        result = project_session.request_mem()
        assert result["error_type"] == "ValueError"
        assert "gpx" in result["error"]

    def test_invalid_map_type_returns_422(self, tmp_path):
        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        result = session.request_mem(map_type="bogus")
        assert result["error_type"] == "ValueError"

    def test_dysnomia_unavailable_returns_422_mem_unavailable_error(self, tmp_path, monkeypatch):
        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        import tsumugin.mem.gsas as mem_gsas_module

        monkeypatch.setattr(mem_gsas_module, "resolve_dysnomia_binary", lambda **kw: None)
        result = session.request_mem(map_type="Fobs")
        assert result["error_type"] == "MEMUnavailableError"

    def test_delt_f_does_not_require_dysnomia_binary(self, tmp_path, monkeypatch):
        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        import tsumugin.mcp.mem_tools as mem_tools_module
        import tsumugin.mem.gsas as mem_gsas_module

        monkeypatch.setattr(mem_gsas_module, "resolve_dysnomia_binary", lambda **kw: None)
        monkeypatch.setattr(
            mem_tools_module, "mem_density", lambda gpx_path, **kw: _fake_mem_result("")
        )
        result = session.request_mem(map_type="delt-F")
        assert result == {"status": "started"}
        session._job.join(timeout=5)

    def test_job_already_running_returns_409(self, tmp_path):
        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        started, release = _block_refine(session)
        try:
            result = session.request_mem()
            assert result["error_type"] == "ConflictError"
        finally:
            release.set()
            session._job.join(timeout=5)

    def test_success_builds_structure_mem_viewmodel_contract_shape(self, tmp_path, monkeypatch):
        import numpy as np

        from tsumugin.mem.output import save_density_grid

        grd_path = tmp_path / "d.grd"
        save_density_grid(
            str(grd_path), np.arange(4, dtype=float).reshape(2, 2, 1),
            (10.0, 10.0, 10.0, 90.0, 90.0, 90.0),
        )

        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        import tsumugin.mcp.mem_tools as mem_tools_module
        import tsumugin.mem.gsas as mem_gsas_module

        monkeypatch.setattr(mem_gsas_module, "resolve_dysnomia_binary", lambda **kw: "fake-binary")
        monkeypatch.setattr(
            mem_tools_module, "mem_density",
            lambda gpx_path, **kw: _fake_mem_result(str(grd_path)),
        )
        before = len(session.ledger.entries)

        result = session.request_mem()
        assert result == {"status": "started"}
        session._job.join(timeout=5)

        assert len(session.ledger.entries) == before + 2  # mem_request + mem_finished
        assert session.ledger.entries[-1].kind == "mem_finished"

        vm = session.viewmodel()
        mem = vm["structure"]["mem"]
        assert mem is not None
        assert mem["map"]["axis"] == "c"
        assert mem["map"]["nx"] == 2
        assert mem["map"]["ny"] == 2
        assert mem["map"]["vmin"] == -0.5
        assert mem["map"]["vmax"] == 3.2
        assert mem["map"]["unit"] == "e·Å⁻³"
        assert len(mem["peaks"]) == 1
        assert mem["peaks"][0]["assign"] == "Ow1?"  # distance 1.5 >= 1.0 → 未モデル候補マーク
        # 既存キー structure.mem_peaks も同じ実ピークへ差し替わる (契約)。
        assert vm["structure"]["mem_peaks"] == mem["peaks"]

    def test_failure_records_mem_failed_ledger_entry(self, tmp_path, monkeypatch):
        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        import tsumugin.mcp.mem_tools as mem_tools_module
        import tsumugin.mem.gsas as mem_gsas_module

        monkeypatch.setattr(mem_gsas_module, "resolve_dysnomia_binary", lambda **kw: "fake-binary")
        monkeypatch.setattr(
            mem_tools_module, "mem_density",
            lambda gpx_path, **kw: {"error": "boom", "error_type": "MEMUnavailableError"},
        )
        session.request_mem()
        session._job.join(timeout=5)
        assert session.ledger.entries[-1].kind == "mem_failed"
        assert session.viewmodel()["structure"]["mem"] is None

    def test_refine_status_reports_mem_kind_after_run(self, tmp_path, monkeypatch):
        session = WorkbenchSession.from_project(_mem_project(tmp_path))
        import tsumugin.mcp.mem_tools as mem_tools_module
        import tsumugin.mem.gsas as mem_gsas_module

        monkeypatch.setattr(mem_gsas_module, "resolve_dysnomia_binary", lambda **kw: "fake-binary")
        monkeypatch.setattr(
            mem_tools_module, "mem_density", lambda gpx_path, **kw: _fake_mem_result("")
        )
        session.request_mem()
        session._job.join(timeout=5)
        assert session.refine_status()["kind"] == "mem"


# ---------------------------------------------------------------------------
# アプリ設定 (資格情報) — Materials Project トークン (api-contract.md §アプリ設定)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_mp_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """MP API キー環境変数をテストごとに未設定へ揃える (実行環境の実キーに左右されないため)。"""
    monkeypatch.delenv("MATERIALS_PROJECT_API", raising=False)


def test_get_settings_reports_unset_by_default():
    session = WorkbenchSession.create_demo()

    result = session.get_settings()

    assert result == {
        "mp_api_key_set": False, "mp_api_key_hint": None, "mp_api_key_source": None,
    }


def test_save_settings_persists_masks_and_appends_ledger_without_value():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    result = session.save_settings(mp_api_key="sk-super-secret-abcd")

    assert result["mp_api_key_set"] is True
    assert result["mp_api_key_source"] == "settings"
    assert result["mp_api_key_hint"] == "…abcd"
    assert len(session.ledger.entries) == before + 1
    entry = session.ledger.entries[-1]
    assert entry.kind == "settings_change"
    assert entry.payload == {"key": "mp_api_key", "action": "set"}


def test_save_settings_rejects_empty_string():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    result = session.save_settings(mp_api_key="")

    assert result["error_type"] == "ValueError"
    assert len(session.ledger.entries) == before  # ガードで弾いた分は ledger を汚さない


def test_save_settings_rejects_non_string():
    session = WorkbenchSession.create_demo()

    result = session.save_settings(mp_api_key=12345)

    assert result["error_type"] == "ValueError"


def test_save_settings_applies_to_process_env_for_mp_client():
    # 【① 非変更の確認】: 保存したキーが既存の MPRestClient() 遅延構築経路 (env → .env) から
    #   そのまま拾えることを確認する (設定 > env の優先順位を実プロセス env で実証)。
    import os

    session = WorkbenchSession.create_demo()

    session.save_settings(mp_api_key="sk-process-env-check")

    assert os.environ.get("MATERIALS_PROJECT_API") == "sk-process-env-check"


def test_clear_settings_removes_value_and_appends_ledger_without_value():
    session = WorkbenchSession.create_demo()
    session.save_settings(mp_api_key="sk-to-be-cleared")
    before = len(session.ledger.entries)

    result = session.clear_settings("mp_api_key")

    assert result == {
        "mp_api_key_set": False, "mp_api_key_hint": None, "mp_api_key_source": None,
    }
    assert len(session.ledger.entries) == before + 1
    entry = session.ledger.entries[-1]
    assert entry.kind == "settings_change"
    assert entry.payload == {"key": "mp_api_key", "action": "clear"}


def test_clear_settings_unknown_key_returns_422_error_dict():
    session = WorkbenchSession.create_demo()
    before = len(session.ledger.entries)

    result = session.clear_settings("not_a_real_key")

    assert result["error_type"] == "ValueError"
    assert len(session.ledger.entries) == before


def test_state_status_reflects_mp_available_from_settings():
    session = WorkbenchSession.create_demo()
    assert session.state()["status"]["mp_available"] is False

    session.save_settings(mp_api_key="sk-abcd1234")

    assert session.state()["status"]["mp_available"] is True

    session.clear_settings("mp_api_key")

    assert session.state()["status"]["mp_available"] is False


def test_state_status_mp_available_true_from_env_without_settings(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MATERIALS_PROJECT_API", "env-only-key")
    session = WorkbenchSession.create_demo()

    assert session.state()["status"]["mp_available"] is True


def test_ledger_never_contains_saved_mp_api_key_value():
    # 【契約の絶対規則: ledger にキーを書かない】: 保存/削除を経ても ledger の payload/text
    #   いずれにも原文キーが現れないことを、全エントリを走査して確認する。
    secret = "sk-must-never-appear-in-ledger-zzz9"
    session = WorkbenchSession.create_demo()

    session.save_settings(mp_api_key=secret)
    session.clear_settings("mp_api_key")

    for entry in session.ledger.entries:
        assert secret not in json.dumps(entry.payload, default=str)
    for row in session.ledger_view()["entries"]:
        assert secret not in row["text"]


def test_ledger_leak_guard_fails_if_payload_carried_the_value_mutation_proof():
    # 【変異実証】: 上のガードテストが「ledger に値を書いてしまう」実装バグを本当に検出できることを
    #   独立に示す — payload に値を積む版を模擬し、上と同じ走査アサーションが fail することを確認する
    #   (「落ちないガードは無いより悪い」CLAUDE.md の教訓に従う)。
    secret = "sk-mutation-proof-leak-value"
    session = WorkbenchSession.create_demo()
    # 実装のガードをすり抜けて「値入りペイロード」を直接 ledger に積む変異を模擬する。
    session.ledger.append("settings_change", {"key": "mp_api_key", "action": "set", "value": secret})

    leaked = any(
        secret in json.dumps(entry.payload, default=str) for entry in session.ledger.entries
    )
    assert leaked, "mutation-proof: 値入り payload を積んだのにガードのロジックが検出できていない"


# ---------------------------------------------------------------------------
# エージェント境界: settings は agent_mcp shim に露出しない
# ---------------------------------------------------------------------------


def test_agent_mcp_does_not_expose_any_credential_tools():
    # 【契約: エージェントに読ませない】: shim (agent_mcp) の許可ツール名に MP キー資格情報
    # (get/save/clear settings, api_key, credential) 関連が一切含まれないことを確認する。
    # `propose_settings_change` (精密化設定の ModelAction 起票) は別物なので意図的に除外しない —
    # 資格情報固有の語幹だけを見る (名前に "setting" を含む既存ツールとの衝突を避けるため)。
    from tsumugin.workbench import agent_mcp

    all_names = agent_mcp.ALLOWED_TOOL_NAMES | agent_mcp.BYPASS_ONLY_TOOL_NAMES
    forbidden_stems = ("api_key", "credential", "get_settings", "save_settings", "clear_settings")
    for name in all_names:
        lowered = name.lower()
        for stem in forbidden_stems:
            assert stem not in lowered, f"{name!r} exposes credential-shaped tool ({stem!r})"


# ---------------------------------------------------------------------------
# phaseid の MP キー不在ガード非回帰 (実 settings/env 経路)
# ---------------------------------------------------------------------------


def test_request_phaseid_returns_422_when_no_mp_key_anywhere(
    project_session: WorkbenchSession, monkeypatch
):
    # 【非回帰】: settings/env のどちらにもキーが無いとき、request_phaseid は既存の
    #   MPRestClient() 事前検証 (① 非変更) 経由で 422 ValueError へ縮退する。リポジトリ実 .env の
    #   混入を避けるため cwd を tmp へ退避する (mp.client._find_dotenv は cwd から親方向探索)。
    monkeypatch.chdir(project_session._project.spec_dir)  # type: ignore[union-attr]
    project_session._fit["plot"] = {"h0": {"x": [1.0], "yobs": [2.0], "residual": None}}

    result = project_session.request_phaseid(mode="pattern")

    assert result["error_type"] == "ValueError"


def test_phaseid_add_returns_error_dict_when_no_mp_key_anywhere(
    project_session: WorkbenchSession, monkeypatch
):
    monkeypatch.chdir(project_session._project.spec_dir)  # type: ignore[union-attr]

    result = project_session.phaseid_add(formula="NaCl", mp_id="mp-1")

    assert result["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# LEDGER の適合度 (Rwp / BIC) 表示 — api-contract.md GET /api/ledger
# ---------------------------------------------------------------------------


def test_ledger_view_exposes_rwp_and_bic_for_stage_entries():
    # 【目的】: 精密化段階の ledger エントリは rwp と bic を持つ。bic は payload の生の事実
    #   (gof/n_params/n_obs) から χ² + n_params·ln(n_obs) として導出される。
    import math

    session = WorkbenchSession.create_demo()
    session.ledger.append(
        "m7_stage",
        {"stage": "01 background", "rwp": 24.5, "gof": 2.4, "n_params": 12, "n_obs": 4200},
    )

    entry = session.ledger_view()["entries"][-1]

    assert entry["rwp"] == pytest.approx(24.5)
    expected = 2.4 * 2.4 * (4200 - 12) + 12 * math.log(4200)
    assert entry["bic"] == pytest.approx(expected)


def test_ledger_view_bic_matches_anchor_frame_bic_definition():
    # 【目的】: GUI の bic は ① `insitu.anchor.select.frame_bic` と**同一式**である
    #   (相数を Rwp でなく bic で抑制する CLAUDE.md の規律と同じ物差しを GUI にも出す)。
    #   片方だけ式が変わったらこのテストが落ちる。
    from tsumugin.insitu.anchor.model import AnchorConfig
    from tsumugin.insitu.anchor.select import frame_bic
    from tsumugin.insitu.model import FrameRietveldResult

    gof, n_params, n_obs = 1.44, 25, 3800
    session = WorkbenchSession.create_demo()
    session.ledger.append(
        "refine_finished", {"rwp": 13.4, "gof": gof, "n_params": n_params, "n_obs": n_obs}
    )

    fr = FrameRietveldResult(
        frame_index=0, axis_value=0.0, data_path="d.xy", rwp=13.4, gof=gof, n_obs=n_obs,
        refined_cells={}, phase_names=("a",), phase_fractions={"a": 1.0},
    )
    cfg = AnchorConfig(base_params=n_params - 1, per_phase_params=1)

    assert session.ledger_view()["entries"][-1]["bic"] == pytest.approx(frame_bic(fr, cfg))


def test_ledger_view_rwp_and_bic_are_null_for_non_refinement_entries():
    # 【目的】: 適合度を持たない操作 (モード切替など) は rwp/bic とも null。
    #   「値が無い」を 0 や前段の値で埋めない (empty-state 規律)。
    session = WorkbenchSession.create_demo()
    session.set_mode("auto")

    entry = session.ledger_view()["entries"][-1]

    assert entry["rwp"] is None
    assert entry["bic"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"rwp": 9.0, "gof": 1.2, "n_params": 10},                      # n_obs 欠落
        {"rwp": 9.0, "gof": float("inf"), "n_params": 10, "n_obs": 40},  # gof 非有限
        {"rwp": 9.0, "gof": 1.2, "n_params": 40, "n_obs": 40},          # dof ≤ 0
        {"rwp": 9.0, "gof": None, "n_params": 10, "n_obs": 4000},       # gof なし
    ],
)
def test_ledger_view_bic_is_null_when_not_derivable(payload):
    # 【目的】: 導出できない入力で bic を捏造しない (0 や inf を返さない)。rwp は残る。
    session = WorkbenchSession.create_demo()
    session.ledger.append("m7_stage", {"stage": "s", **payload})

    entry = session.ledger_view()["entries"][-1]

    assert entry["bic"] is None
    assert entry["rwp"] == pytest.approx(9.0)


def test_refine_finished_ledger_payload_carries_gof_n_params_n_obs(tmp_path):
    # 【目的】: refine 完了エントリが bic 導出に必要な生の事実を payload に持つ
    #   (LEDGER の bic 列がここから作れる = ② 到達可能性と同じ「出力から作れるか」の規律)。
    project = lifecycle.create_project("proj", str(tmp_path))
    session = WorkbenchSession.from_project(project)
    result = AutoRietveldResult(
        stage_results=(StageResult(label="s", rwp=8.1, gof=1.3, n_params=17, converged=True),),
        final_rwp=8.1, final_gof=1.3, refined_cells={}, validity=ValidityReport(passed=True),
        gpx_path="", n_obs=3300,
    )

    session._on_refine_success(result)

    payload = [e for e in session.ledger.entries if e.kind == "refine_finished"][-1].payload
    assert payload["gof"] == pytest.approx(1.3)
    assert payload["n_params"] == 17
    assert payload["n_obs"] == 3300


# ---------------------------------------------------------------------------
# PHASE ID の元素系 — 固定表記ではなく現相集合の CIF から導出する
# ---------------------------------------------------------------------------


def test_viewmodel_phase_id_elements_derived_from_project_cifs(tmp_path):
    # 【目的】: 相同定タブの元素表記は固定文字列ではなく、実際に `identify_pattern` へ渡る
    #   元素系 (`_elements_from_project` と同一導出) である。
    pytest.importorskip("pymatgen")
    session = WorkbenchSession.from_project(_phaseid_project(tmp_path))

    elements = session.viewmodel()["phase_id"]["elements"]

    assert elements == ["Cl", "Na"]


def test_viewmodel_phase_id_elements_empty_when_no_phases(tmp_path):
    # 【目的】: 相 0 件の新規プロジェクトは空リスト (存在しない元素系をでっち上げない)。
    project = lifecycle.create_project("proj", str(tmp_path))
    session = WorkbenchSession.from_project(project)

    assert session.viewmodel()["phase_id"]["elements"] == []


def test_viewmodel_phase_id_elements_empty_when_pymatgen_missing(tmp_path, monkeypatch):
    # 【目的】: pymatgen 未導入環境でも viewmodel は落ちず空リストへ縮退する
    #   (相同定タブが使えないだけで GUI 全体は動く)。
    from tsumugin.workbench import session as session_mod

    def _boom(_project):
        raise ImportError("pymatgen is not installed")

    monkeypatch.setattr(session_mod, "_elements_from_project", _boom)
    session = WorkbenchSession.from_project(_phaseid_project(tmp_path))

    assert session.viewmodel()["phase_id"]["elements"] == []


def test_ledger_text_formats_rwp_to_two_decimals():
    # 【目的】: ledger のテキストに 15 桁の生 float を出さない (Rwp 列と併記されるため
    #   `rwp=12.568386255970948` は読みづらいだけ)。`last_event` (ステータスバー/コンソール
    #   表示) も同じテキストを使うので、値自体は残す。
    session = WorkbenchSession.create_demo()
    session.ledger.append("m7_stage", {"stage": "S6", "rwp": 12.568386255970948, "gof": 1.4})
    session.ledger.append("refine_finished", {"rwp": 12.568386255970948, "gof": 1.4})

    texts = [e["text"] for e in session.ledger_view()["entries"][-2:]]

    assert texts[0] == "stage S6 rwp=12.57"
    assert texts[1] == "refine finished (rwp=12.57)"


def test_ledger_text_keeps_dash_when_rwp_is_missing():
    # 【目的】: 値なしを 0.00 に化けさせない。
    session = WorkbenchSession.create_demo()
    session.ledger.append("refine_finished", {"rwp": None, "gof": None})

    assert session.ledger_view()["entries"][-1]["text"] == "refine finished (rwp=―)"


# ---------------------------------------------------------------------------
# 相同定の元素系を GUI から直接指定する (CIF 先読み不要の動線)
# ---------------------------------------------------------------------------


def _pattern_only_project(tmp_path: Path) -> WorkbenchProject:
    """**相 0 件**の project (未知試料の単一パターン解析: 相は同定の結果であって前提でない)。"""
    return WorkbenchProject(
        name="pattern only",
        histograms=(
            HistogramSpec(
                data_path=str(tmp_path / "d.xy"),
                instrument_path=str(tmp_path / "d.instprm"),
                radiation=Radiation.XRAY_LAB,
                geometry=Geometry.BRAGG_BRENTANO,
                data_format="XY",
            ),
        ),
        phases=(),
        gpx_path=str(tmp_path / "refined.gpx"),
        spec_dir=str(tmp_path),
    )


class _RecordingProvider:
    """`fetch` に渡された元素系を記録するテスト供給元 (§4.5: 注入はテスト専用)。"""

    def __init__(self):
        self.seen: "list[list[str]]" = []

    def fetch(self, elements):
        self.seen.append(list(elements))
        return []


def _seed_pattern(session: WorkbenchSession) -> None:
    tt, obs = _synthetic_pattern([20.0, 35.0, 52.0])
    session._fit["plot"] = {"h0": {"x": tt.tolist(), "yobs": obs.tolist(), "residual": None}}


def test_request_phaseid_uses_explicitly_given_elements(tmp_path):
    # 【目的】: elements を渡すと**その元素系がそのまま** identify_pattern へ渡る。
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)
    provider = _RecordingProvider()

    result = session.request_phaseid(
        mode="pattern", elements=["Te", "Ca", "O"], _provider=provider
    )

    assert result == {"status": "started"}
    session._job.join(timeout=5)
    # 重複排除 + 昇順ソートで正規化 (NFR-102 決定性)
    assert provider.seen == [["Ca", "O", "Te"]]


def test_request_phaseid_works_without_any_phase_in_the_model(tmp_path):
    # 【目的 (この改良の要点)】: 相 0 件 = CIF 未読込でも相同定できる。
    #   「CIF を読み込んでから相同定」は未知試料では成り立たない動線。
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)

    assert session.request_phaseid(
        mode="pattern", elements=["Na", "Cl"], _provider=_RecordingProvider()
    ) == {"status": "started"}
    session._job.join(timeout=5)


def test_request_phaseid_normalises_duplicates_and_case_of_given_elements(tmp_path):
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)
    provider = _RecordingProvider()

    session.request_phaseid(mode="pattern", elements=["na", "CL", "Na"], _provider=provider)
    session._job.join(timeout=5)

    assert provider.seen == [["Cl", "Na"]]


@pytest.mark.parametrize("bad", [["Ca", "Xx"], ["Ca", ""], ["Ca", 7], "CaO"])
def test_request_phaseid_rejects_invalid_elements_without_starting_a_job(tmp_path, bad):
    # 【目的】: 不正な元素指定は 422 へ縮退し、**ジョブは起動しない** (MP 側の失敗に化けさせない)。
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)

    result = session.request_phaseid(mode="pattern", elements=bad, _provider=_RecordingProvider())

    assert result["error_type"] == "ValueError"
    assert session._job.status()["status"] == "idle"


def test_request_phaseid_rejects_empty_element_list(tmp_path):
    # 【目的】: 明示的な空配列は「省略」と区別して 422 (黙って CIF 由来へ落とさない)。
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)

    result = session.request_phaseid(mode="pattern", elements=[], _provider=_RecordingProvider())

    assert result["error_type"] == "ValueError"


def test_request_phaseid_names_deuterium_explicitly(tmp_path):
    # 【目的】: D は元素表 (GSAS 由来 99 択) にあるが MP の chemsys には無い。
    #   "unknown element symbol" で放り出さず H を案内する。
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)

    result = session.request_phaseid(mode="pattern", elements=["D", "O"], _provider=_RecordingProvider())

    assert result["error_type"] == "ValueError"
    assert "H" in result["error"]


def test_request_phaseid_without_elements_still_derives_from_cifs(tmp_path):
    # 【非回帰】: 省略時は従来どおり現相集合の CIF から導出する (operando 経路の互換)。
    pytest.importorskip("pymatgen")
    session = WorkbenchSession.from_project(_phaseid_project(tmp_path))
    _seed_pattern(session)
    provider = _RecordingProvider()

    session.request_phaseid(mode="pattern", _provider=provider)
    session._job.join(timeout=5)

    assert provider.seen == [["Cl", "Na"]]


def test_viewmodel_phase_id_elements_reflect_the_last_identification(tmp_path):
    # 【目的】: 表示は「直近の同定が実際に使った元素系」。CIF 由来の導出値で上書きしない。
    pytest.importorskip("pymatgen")
    session = WorkbenchSession.from_project(_phaseid_project(tmp_path))
    _seed_pattern(session)
    assert session.viewmodel()["phase_id"]["elements"] == ["Cl", "Na"]

    session.request_phaseid(mode="pattern", elements=["Ca", "Te", "O"], _provider=_RecordingProvider())
    session._job.join(timeout=5)

    assert session.viewmodel()["phase_id"]["elements"] == ["Ca", "O", "Te"]


def test_phaseid_add_uses_the_elements_of_the_last_identification(tmp_path, monkeypatch):
    # 【目的】: 相 0 件のプロジェクトでも同定 → ADD AS PHASE まで通る
    #   (従来は物質化のために CIF 由来の元素系を要求し、相が無いと必ず失敗した)。
    session = WorkbenchSession.from_project(_pattern_only_project(tmp_path))
    _seed_pattern(session)
    session.request_phaseid(mode="pattern", elements=["Na", "Cl"], _provider=_RecordingProvider())
    session._job.join(timeout=5)

    seen: dict[str, Any] = {}

    class _FakeMaterializer:
        def __init__(self, *a, **kw):
            pass

        def materialize(self, mp_id, elements, cif_path, strain=0.0):
            seen["elements"] = list(elements)
            Path(cif_path).write_text("data_x\n", encoding="utf-8")

    import tsumugin.insitu.phaseid as phaseid_mod
    import tsumugin.mp.client as mp_client_mod

    monkeypatch.setattr(phaseid_mod, "MPMaterializer", _FakeMaterializer)
    monkeypatch.setattr(mp_client_mod, "MPRestClient", lambda *a, **kw: object())

    result = session.phaseid_add(formula="NaCl", mp_id="mp-22862")

    assert "error" not in result, result
    assert seen["elements"] == ["Cl", "Na"]


# ---------------------------------------------------------------------------
# PHASES タブ — 相スコープの精密化制御
# ---------------------------------------------------------------------------


def test_phases_view_exposes_phase_scoped_fields(tmp_path):
    # 【目的】: PHASES タブが必要とする相スコープの実データが viewmodel.phases に出る。
    project = lifecycle.create_project("proj", str(tmp_path))
    cif = Path(project.spec_dir) / "data" / "a.cif"
    cif.parent.mkdir(parents=True, exist_ok=True)
    cif.write_text("data_a\n", encoding="utf-8")
    session = WorkbenchSession.from_project(project)
    session.add_phase(structure_path=str(cif), phase_name="alpha")

    row = session.viewmodel()["phases"][0]

    assert row["name"] == "alpha"
    assert row["structure_path"].endswith("a.cif")
    assert row["refine_cell"] is True
    assert row["temperature"] is None
    assert row["cell"] is None  # 未精密化は捏造しない (empty-state)


def test_set_phase_settings_toggles_refine_cell_and_appends_ledger(tmp_path):
    # 【目的】: REFINE CELL のチェックは実 PhaseSpec.refine_cell (engine が読む値) を変える。
    project = lifecycle.create_project("proj", str(tmp_path))
    cif = Path(project.spec_dir) / "data" / "a.cif"
    cif.parent.mkdir(parents=True, exist_ok=True)
    cif.write_text("data_a\n", encoding="utf-8")
    session = WorkbenchSession.from_project(project)
    session.add_phase(structure_path=str(cif), phase_name="alpha")
    before = len(session.ledger.entries)

    result = session.set_phase_settings("alpha", refine_cell=False)

    assert "error" not in result, result
    assert session._project.phases[0].refine_cell is False
    assert session.viewmodel()["phases"][0]["refine_cell"] is False
    assert len(session.ledger.entries) == before + 1


def test_set_phase_settings_persists_to_project_spec(tmp_path):
    # 【目的】: 再起動を跨いで効く (spec 自動保存)。GUI の設定が次回 run に届かないと意味がない。
    project = lifecycle.create_project("proj", str(tmp_path))
    cif = Path(project.spec_dir) / "data" / "a.cif"
    cif.parent.mkdir(parents=True, exist_ok=True)
    cif.write_text("data_a\n", encoding="utf-8")
    session = WorkbenchSession.from_project(project)
    session.add_phase(structure_path=str(cif), phase_name="alpha")

    session.set_phase_settings("alpha", refine_cell=False)

    spec_path = Path(session._project.spec_dir) / lifecycle.PROJECT_JSON_NAME
    saved = json.loads(spec_path.read_text(encoding="utf-8"))
    assert saved["phases"][0]["refine_cell"] is False


def test_set_phase_settings_unknown_phase_returns_not_found(tmp_path):
    project = lifecycle.create_project("proj", str(tmp_path))
    session = WorkbenchSession.from_project(project)

    result = session.set_phase_settings("nope", refine_cell=False)

    assert result["error_type"] == "NotFoundError"


def test_set_phase_settings_rejects_non_boolean(tmp_path):
    # 【目的】: 型不正を「正常」と答えない (② 不変条件)。
    project = lifecycle.create_project("proj", str(tmp_path))
    cif = Path(project.spec_dir) / "data" / "a.cif"
    cif.parent.mkdir(parents=True, exist_ok=True)
    cif.write_text("data_a\n", encoding="utf-8")
    session = WorkbenchSession.from_project(project)
    session.add_phase(structure_path=str(cif), phase_name="alpha")

    result = session.set_phase_settings("alpha", refine_cell="yes")

    assert result["error_type"] == "ValueError"
    assert session._project.phases[0].refine_cell is True


def test_phases_view_lists_the_recipe_stages_touching_each_phase(tmp_path):
    # 【目的】: 「この相に何が起きるか」を読み取り専用で示す。相単位に制御できないフラグ
    #   (size_strain 等) はここで見えるだけ — 触れると嘘になるので編集させない。
    project = lifecycle.create_project("proj", str(tmp_path))
    cif = Path(project.spec_dir) / "data" / "a.cif"
    cif.parent.mkdir(parents=True, exist_ok=True)
    cif.write_text("data_a\n", encoding="utf-8")
    hist_data = Path(project.spec_dir) / "data" / "d.xy"
    hist_data.write_text("1 1\n", encoding="utf-8")
    instr = Path(project.spec_dir) / "data" / "d.instprm"
    instr.write_text("#\n", encoding="utf-8")
    session = WorkbenchSession.from_project(project)
    session.add_histogram(
        data_path=str(hist_data), instrument_path=str(instr),
        radiation="xray_lab", geometry="bragg_brentano", data_format="XY",
    )
    session.add_phase(structure_path=str(cif), phase_name="alpha")

    stages = session.viewmodel()["phases"][0]["stages"]

    # 相スコープのフラグ (cell/size_strain/coords/uiso) を持つ段だけが並ぶ。
    assert any("cell" in s for s in stages)
    assert any("size_strain" in s for s in stages)
    # ヒストグラム専用の段 (背景のみ) は相に触れないので出ない
    assert not any("scale+background" in s for s in stages)


def test_phases_view_shows_refined_cell_after_a_refinement(tmp_path):
    project = lifecycle.create_project("proj", str(tmp_path))
    cif = Path(project.spec_dir) / "data" / "a.cif"
    cif.parent.mkdir(parents=True, exist_ok=True)
    cif.write_text("data_a\n", encoding="utf-8")
    session = WorkbenchSession.from_project(project)
    session.add_phase(structure_path=str(cif), phase_name="alpha")
    result = AutoRietveldResult(
        stage_results=(StageResult(label="s", rwp=8.0, gof=1.2, n_params=5, converged=True),),
        final_rwp=8.0, final_gof=1.2,
        refined_cells={"alpha": (9.3721, 9.3721, 6.8861, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=True), gpx_path="", n_obs=1000,
    )

    session._on_refine_success(result)

    cell = session.viewmodel()["phases"][0]["cell"]
    assert cell["a"].startswith("9.372")
    assert cell["gamma"].startswith("120")


def test_ledger_text_for_stage_error_includes_the_reason():
    # 【目的】: 「stage S1 error」だけでは LEDGER から原因が追えない (実際に追えず詰まった)。
    session = WorkbenchSession.create_demo()
    session.ledger.append(
        "m7_stage_error", {"stage": "S1 cell+displacement", "error": "ValueError('boom')"}
    )

    text = session.ledger_view()["entries"][-1]["text"]

    assert "S1 cell+displacement" in text
    assert "boom" in text
