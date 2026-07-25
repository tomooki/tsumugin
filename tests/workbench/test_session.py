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
from pathlib import Path

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
