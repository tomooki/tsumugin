"""``tsumugin.workbench.session.WorkbenchSession`` の TDD テスト。

対象: モード切替 (FR-402) / hypotheses accept・revert / review queue resolve /
structure apply / approval / stages / refine / transcript message / ledger view。
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from tsumugin.workbench import lifecycle
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
