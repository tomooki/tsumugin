"""``tsumugin.workbench.app`` の FastAPI ルート層テスト (`tests/test_webui.py` の流儀を踏襲)。

read-only 保証 (webui) と対称に、ワークベンチは「削除系ルートが存在しない」ことを構造的に
担保する (P2 / NFR-GUI-001)。DELETE/PUT ルート不在はガードテストとして扱い、実装を一時的に
壊して fail することを確認したうえで元に戻した (レポート参照)。
"""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

import tsumugin.workbench.session as workbench_session_module  # noqa: E402
from tsumugin.autorietveld.model import (  # noqa: E402
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.workbench.app import create_workbench_app  # noqa: E402
from tsumugin.workbench.project import WorkbenchProject  # noqa: E402
from tsumugin.workbench.session import WorkbenchSession  # noqa: E402


@pytest.fixture()
def session() -> WorkbenchSession:
    return WorkbenchSession.create_demo()


@pytest.fixture()
def client(session: WorkbenchSession) -> TestClient:
    return TestClient(create_workbench_app(session))


def _fake_project(tmp_path) -> WorkbenchProject:
    hist = HistogramSpec(
        data_path=str(tmp_path / "hist.xy"),
        instrument_path=str(tmp_path / "hist.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / "phase.cif"), phase_name="phaseA")
    return WorkbenchProject(
        name="project fixture",
        histograms=(hist,),
        phases=(phase,),
        background_coeffs=6,
        max_cyc=5,
        gpx_path=str(tmp_path / "workbench_out" / "refined.gpx"),
    )


def _fake_result() -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="background", rwp=12.0, gof=1.2, n_params=6, converged=True),),
        final_rwp=12.0,
        final_gof=1.2,
        refined_cells={"phaseA": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True, checks=(("occupancy bounds", True, "ok"),)),
        gpx_path="",
        n_obs=500,
        phase_weight_fractions={"phaseA": 1.0},
        phase_weight_fraction_esd={"phaseA": 0.0},
    )


# ---------------------------------------------------------------------------
# P2: DELETE/PUT ルート不在 (構造的ガード)
# ---------------------------------------------------------------------------


def test_no_delete_or_put_routes_are_defined(client: TestClient):
    # 【目的】: ルート表を構造的に走査し DELETE/PUT を持つルートが 1 つも無いことを確認する (P2)
    app = client.app
    offending = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        if not methods:
            continue
        if "DELETE" in methods or "PUT" in methods:
            offending.append((getattr(route, "path", "?"), methods))
    assert offending == []


def test_delete_and_put_requests_return_404_or_405(client: TestClient):
    assert client.delete("/api/ledger").status_code in (404, 405)
    assert client.put("/api/state").status_code in (404, 405)
    assert client.delete("/api/review-queue/rq-0000").status_code in (404, 405)


# ---------------------------------------------------------------------------
# GET /api/state
# ---------------------------------------------------------------------------


def test_get_state_returns_shell_state(client: TestClient):
    resp = client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "manual"
    assert data["final_selection_mode"] == "human"
    assert data["ledger"]["verified"] is True


def test_get_state_demo_source_and_refine_idle(client: TestClient):
    # 【契約】: demo モードは source="demo"・refine.status="idle" 固定 (互換)。last_event は
    #   session ledger の最新エントリを素直に反映する (demo でも ledger は実在するため None 固定ではない)。
    resp = client.get("/api/state")
    data = resp.json()
    assert data["source"] == "demo"
    assert data["refine"]["status"] == "idle"
    assert data["refine"]["elapsed_s"] is None
    assert data["refine"]["error"] is None


# ---------------------------------------------------------------------------
# POST /api/mode
# ---------------------------------------------------------------------------


def test_post_mode_switches_and_returns_state(client: TestClient, session: WorkbenchSession):
    resp = client.post("/api/mode", json={"mode": "auto"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "auto"
    assert data["final_selection_mode"] == "agent"
    assert data["ledger"]["count"] == len(session.ledger.entries)


def test_post_mode_same_mode_does_not_grow_ledger(client: TestClient, session: WorkbenchSession):
    before = len(session.ledger.entries)
    resp = client.post("/api/mode", json={"mode": "manual"})
    assert resp.status_code == 200
    assert len(session.ledger.entries) == before


def test_post_mode_invalid_value_returns_422_error_dict(client: TestClient):
    resp = client.post("/api/mode", json={"mode": "bogus"})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_type"] == "ValueError"
    assert "error" in body


# ---------------------------------------------------------------------------
# GET /api/viewmodel
# ---------------------------------------------------------------------------


def test_get_viewmodel_returns_full_shape(client: TestClient):
    resp = client.get("/api/viewmodel")
    assert resp.status_code == 200
    data = resp.json()
    required = {
        "datasets", "phases", "channels", "snapshots", "fit", "parameters",
        "hypotheses", "phase_id", "sequence", "structure", "stages", "review", "transcript",
    }
    assert required <= set(data)


# ---------------------------------------------------------------------------
# review queue
# ---------------------------------------------------------------------------


def test_get_review_queue_lists_four_seeded_items(client: TestClient):
    resp = client.get("/api/review-queue")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 4


def test_review_resolve_accept_then_send_back_and_errors(client: TestClient):
    items = client.get("/api/review-queue").json()["items"]
    item_id = items[0]["id"]

    resp = client.post(f"/api/review-queue/{item_id}/resolve", json={"action": "accept", "note": ""})
    assert resp.status_code == 200
    assert resp.json()["item"]["state"] == "accepted"

    resp2 = client.post(f"/api/review-queue/{item_id}/resolve", json={"action": "send_back", "note": ""})
    assert resp2.status_code == 409
    assert resp2.json()["error_type"] == "ConflictError"

    resp3 = client.post("/api/review-queue/nope/resolve", json={"action": "accept", "note": ""})
    assert resp3.status_code == 404

    resp4 = client.post(f"/api/review-queue/{item_id}/resolve", json={"action": "bogus", "note": ""})
    assert resp4.status_code == 422


# ---------------------------------------------------------------------------
# structure apply
# ---------------------------------------------------------------------------


def test_structure_apply_returns_snapshot_id_and_grows_snapshots(
    client: TestClient, session: WorkbenchSession
):
    sites = client.get("/api/viewmodel").json()["structure"]["sites"]
    sites[0]["occ"] = "0.42"
    before = len(session.snapshots.snapshots)

    resp = client.post("/api/structure/apply", json={"sites": sites, "note": "lower K1"})

    assert resp.status_code == 200
    data = resp.json()
    assert "snapshot_id" in data
    assert "ledger_index" in data
    assert len(session.snapshots.snapshots) == before + 1


def test_structure_apply_rejects_non_list_sites(client: TestClient):
    resp = client.post("/api/structure/apply", json={"sites": "not-a-list"})
    assert resp.status_code == 422


def test_structure_apply_rejects_non_dict_site_elements(client: TestClient):
    # 【Red→Green】: 修正前は sites の各要素を dict と仮定して素通しするため
    #   ``session.apply_structure`` 内の ``site.get(...)`` が str に対して AttributeError を送出し、
    #   ハンドラの外へ貫通していた (raise_server_exceptions=True の TestClient は Python 例外として
    #   再送出する = 422 どころか応答すら返らない)。修正後は各要素が dict であることを検証し、
    #   ハンドラ内で 422 error dict へ縮退させる。
    resp = client.post("/api/structure/apply", json={"sites": ["x"]})
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_type"] == "ValueError"
    assert "error" in body


# ---------------------------------------------------------------------------
# approval
# ---------------------------------------------------------------------------


def test_approval_approve_creates_snapshot_and_ledger(client: TestClient, session: WorkbenchSession):
    before_snaps = len(session.snapshots.snapshots)
    resp = client.post("/api/approval/a1", json={"decision": "approve"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "approved"
    assert data["snapshot_id"] is not None
    assert len(session.snapshots.snapshots) == before_snaps + 1


def test_approval_reject_does_not_create_snapshot(client: TestClient, session: WorkbenchSession):
    before_snaps = len(session.snapshots.snapshots)
    resp = client.post("/api/approval/a1", json={"decision": "reject"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "rejected"
    assert data["snapshot_id"] is None
    assert len(session.snapshots.snapshots) == before_snaps


def test_approval_double_resolve_is_4xx(client: TestClient):
    client.post("/api/approval/a1", json={"decision": "approve"})
    resp = client.post("/api/approval/a1", json={"decision": "reject"})
    assert 400 <= resp.status_code < 500


def test_approval_invalid_decision_returns_422(client: TestClient):
    resp = client.post("/api/approval/a1", json={"decision": "bogus"})
    assert resp.status_code == 422


def test_approval_keeps_transcript_proposal_both_paths(client: TestClient):
    client.post("/api/approval/a1", json={"decision": "reject"})
    transcript = client.get("/api/viewmodel").json()["transcript"]
    approval = next(m for m in transcript if m.get("kind") == "approval")
    assert approval["action_id"] == "a1"
    assert approval["state"] == "rejected"


# ---------------------------------------------------------------------------
# stages
# ---------------------------------------------------------------------------


def test_stage_release_and_revert(client: TestClient):
    resp = client.post("/api/stages/07", json={"action": "release"})
    assert resp.status_code == 200
    assert resp.json()["stage"]["released"] is True

    resp2 = client.post("/api/stages/07", json={"action": "revert"})
    assert resp2.status_code == 200
    assert resp2.json()["stage"]["released"] is False


def test_stage_unknown_nn_returns_404(client: TestClient):
    resp = client.post("/api/stages/99", json={"action": "release"})
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# refine
# ---------------------------------------------------------------------------


def test_refine_returns_202_and_appends_ledger_only(client: TestClient, session: WorkbenchSession):
    before_snaps = len(session.snapshots.snapshots)
    before_ledger = len(session.ledger.entries)

    resp = client.post("/api/refine", json={})

    assert resp.status_code == 202
    assert resp.json() == {"status": "recorded"}
    assert len(session.ledger.entries) == before_ledger + 1
    assert len(session.snapshots.snapshots) == before_snaps


def test_refine_status_route_returns_contract_shape_for_demo(client: TestClient):
    resp = client.get("/api/refine/status")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"status", "elapsed_s", "last_event", "error"}
    assert data["status"] == "idle"
    assert data["elapsed_s"] is None
    assert data["error"] is None


# ---------------------------------------------------------------------------
# refine (project モード, REQ-GUI-013)
# ---------------------------------------------------------------------------


@pytest.fixture()
def project_session(tmp_path) -> WorkbenchSession:
    return WorkbenchSession.from_project(_fake_project(tmp_path))


@pytest.fixture()
def project_client(project_session: WorkbenchSession) -> TestClient:
    return TestClient(create_workbench_app(project_session))


def test_get_state_project_source(project_client: TestClient):
    resp = project_client.get("/api/state")
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "project"
    assert data["refine"]["status"] == "idle"


def test_project_refine_202_then_status_done_after_fake_runner_completes(
    project_client: TestClient, project_session: WorkbenchSession, monkeypatch
):
    monkeypatch.setattr(
        workbench_session_module, "build_default_runner",
        lambda project, ledger=None: _fake_result,
    )

    resp = project_client.post("/api/refine", json={})
    assert resp.status_code == 202
    assert resp.json() == {"status": "started"}

    project_session._job.join(timeout=5)

    status_resp = project_client.get("/api/refine/status")
    assert status_resp.status_code == 200
    status = status_resp.json()
    assert status["status"] == "done"
    assert status["error"] is None

    state_resp = project_client.get("/api/state")
    assert state_resp.json()["refine"]["status"] == "done"

    vm = project_client.get("/api/viewmodel").json()
    rwp_row = next(m for m in vm["fit"]["metrics"] if m["key"] == "rwp")
    assert rwp_row["value"] == "12.00%"


def test_project_refine_returns_409_when_already_running(
    project_client: TestClient, project_session: WorkbenchSession, monkeypatch
):
    started_evt = threading.Event()
    release_evt = threading.Event()

    def fake_runner() -> AutoRietveldResult:
        started_evt.set()
        release_evt.wait(timeout=5)
        return _fake_result()

    monkeypatch.setattr(
        workbench_session_module, "build_default_runner",
        lambda project, ledger=None: fake_runner,
    )

    resp1 = project_client.post("/api/refine", json={})
    assert resp1.status_code == 202
    assert started_evt.wait(timeout=5)

    resp2 = project_client.post("/api/refine", json={})
    assert resp2.status_code == 409
    body = resp2.json()
    assert body["error_type"] == "ConflictError"

    release_evt.set()
    project_session._job.join(timeout=5)


def test_project_refine_failure_sets_status_failed_with_error(
    project_client: TestClient, project_session: WorkbenchSession, monkeypatch
):
    def bad_runner() -> AutoRietveldResult:
        raise RuntimeError("gsas exploded")

    monkeypatch.setattr(
        workbench_session_module, "build_default_runner",
        lambda project, ledger=None: bad_runner,
    )

    resp = project_client.post("/api/refine", json={})
    assert resp.status_code == 202

    project_session._job.join(timeout=5)

    status = project_client.get("/api/refine/status").json()
    assert status["status"] == "failed"
    assert "gsas exploded" in status["error"]

    ledger = project_client.get("/api/ledger").json()
    assert ledger["entries"][-1]["text"].startswith("refine failed")
    assert ledger["verified"] is True


# ---------------------------------------------------------------------------
# transcript message
# ---------------------------------------------------------------------------


def test_transcript_message_is_recorded(client: TestClient):
    resp = client.post("/api/transcript/message", json={"text": "hello"})
    assert resp.status_code == 200
    assert resp.json()["message"]["text"] == "hello"

    transcript = client.get("/api/viewmodel").json()["transcript"]
    assert any(m.get("text") == "hello" for m in transcript)


# ---------------------------------------------------------------------------
# ledger
# ---------------------------------------------------------------------------


def test_get_ledger_matches_state_count(client: TestClient):
    resp = client.get("/api/ledger")
    assert resp.status_code == 200
    data = resp.json()
    assert data["verified"] is True
    state = client.get("/api/state").json()
    assert len(data["entries"]) == state["ledger"]["count"]


# ---------------------------------------------------------------------------
# hypotheses
# ---------------------------------------------------------------------------


def test_get_hypotheses_matches_viewmodel_shape(client: TestClient):
    resp = client.get("/api/hypotheses")
    assert resp.status_code == 200
    data = resp.json()
    assert {"rows", "diff", "evidence"} <= set(data)


def test_accept_hypothesis_then_revert(client: TestClient):
    resp = client.post("/api/hypotheses/H-014/accept", json={"by": "human"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "accepted"

    resp2 = client.post("/api/revert", json={"hypothesis_id": "H-014", "note": "second look"})
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "reverted"


def test_accept_hypothesis_unknown_id_returns_404(client: TestClient):
    resp = client.post("/api/hypotheses/nope/accept", json={"by": "human"})
    assert resp.status_code == 404


def test_revert_hypothesis_not_accepted_returns_404(client: TestClient):
    resp = client.post("/api/revert", json={"hypothesis_id": "H-011", "note": ""})
    assert resp.status_code == 404


def test_revert_without_hypothesis_id_returns_422(client: TestClient):
    resp = client.post("/api/revert", json={"note": "x"})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# fastapi 未導入経路
# ---------------------------------------------------------------------------


def test_create_workbench_app_without_fastapi_raises_web_unavailable(
    session: WorkbenchSession, monkeypatch
):
    from tsumugin.errors import TsumuginError, WebUIUnavailableError

    monkeypatch.setitem(sys.modules, "fastapi", None)

    with pytest.raises(WebUIUnavailableError) as exc:
        create_workbench_app(session)

    assert issubclass(WebUIUnavailableError, TsumuginError)
    message = str(exc.value)
    assert ("tsumugin[web]" in message) or ("uv sync --extra web" in message)


# ---------------------------------------------------------------------------
# static 配信フォールバック
# ---------------------------------------------------------------------------


def test_root_without_static_dir_returns_json_hint(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "app" in data


def test_root_with_static_dir_serves_index_html(session: WorkbenchSession, tmp_path):
    (tmp_path / "index.html").write_text("<html><body>workbench</body></html>", encoding="utf-8")
    app = create_workbench_app(session, static_dir=tmp_path)
    static_client = TestClient(app)

    resp = static_client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "workbench" in resp.text


# ---------------------------------------------------------------------------
# 未定義ルート
# ---------------------------------------------------------------------------


def test_unknown_route_returns_404(client: TestClient):
    assert client.get("/api/does-not-exist").status_code == 404


# ---------------------------------------------------------------------------
# 汎用例外ハンドラ (PR #120 系統欠陥の再発防止)
# ---------------------------------------------------------------------------


def test_unhandled_exception_degrades_to_500_error_dict(
    session: WorkbenchSession, monkeypatch: pytest.MonkeyPatch
):
    """個別ハンドラが捕捉していない例外 (実装漏れ) でも、生の traceback ではなく

    ``{"error", "error_type"}`` 形状の 500 で返ることを担保する。session.state を
    monkeypatch して ValueError/KeyError/ConflictError のどれでもない例外 (RuntimeError) を
    誘発する — 本番アプリにテスト専用ルートは足さない。
    """
    monkeypatch.setattr(
        session, "state", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    app = create_workbench_app(session)
    no_raise_client = TestClient(app, raise_server_exceptions=False)

    resp = no_raise_client.get("/api/state")

    assert resp.status_code == 500
    body = resp.json()
    assert body == {"error": "internal server error", "error_type": "internal_error"}


# ---------------------------------------------------------------------------
# プロジェクトライフサイクル (V2a P1/P2, api-contract.md §プロジェクトライフサイクル)
# ---------------------------------------------------------------------------


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """recent 一覧の保存先をテスト用ホームへ隔離する。"""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def test_project_create_open_close_demo_round_trip(
    client: TestClient, tmp_path: Path, fake_home: Path
):
    directory = tmp_path / "projects"
    directory.mkdir()

    resp = client.post("/api/project", json={"name": "proj1", "directory": str(directory)})
    assert resp.status_code == 200
    data = resp.json()
    assert data["source"] == "project"
    assert data["project"]["name"] == "proj1"
    assert data["project_path"] is not None

    resp2 = client.post("/api/project/close", json={})
    assert resp2.status_code == 200
    assert resp2.json()["source"] == "none"
    assert resp2.json()["project_path"] is None

    resp3 = client.post(
        "/api/project/open", json={"path": str(directory / "proj1")}
    )
    assert resp3.status_code == 200
    assert resp3.json()["source"] == "project"
    assert resp3.json()["project"]["name"] == "proj1"

    resp4 = client.post("/api/project/demo", json={})
    assert resp4.status_code == 200
    assert resp4.json()["source"] == "demo"


def test_project_create_existing_directory_returns_409(
    client: TestClient, tmp_path: Path, fake_home: Path
):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    assert resp.status_code == 409
    assert resp.json()["error_type"] == "ConflictError"


def test_project_create_missing_name_or_directory_returns_422(client: TestClient, tmp_path: Path):
    resp = client.post("/api/project", json={"name": "", "directory": str(tmp_path)})
    assert resp.status_code == 422

    resp2 = client.post("/api/project", json={"name": "x"})
    assert resp2.status_code == 422


def test_project_open_missing_path_returns_404(client: TestClient, tmp_path: Path):
    resp = client.post("/api/project/open", json={"path": str(tmp_path / "does-not-exist")})
    assert resp.status_code == 404
    assert resp.json()["error_type"] == "NotFoundError"


def test_project_recent_lists_after_create(client: TestClient, tmp_path: Path, fake_home: Path):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.get("/api/project/recent")

    assert resp.status_code == 200
    projects = resp.json()["projects"]
    assert len(projects) == 1
    assert projects[0]["name"] == "proj1"
    assert "last_opened" in projects[0]


def test_project_upload_stores_file_and_returns_stored_path(
    client: TestClient, tmp_path: Path, fake_home: Path
):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.post(
        "/api/project/upload",
        data={"kind": "data"},
        files={"file": ("hist.xy", io.BytesIO(b"10.0 100\n10.1 105\n"), "text/plain")},
    )

    assert resp.status_code == 200
    stored_path = resp.json()["stored_path"]
    assert Path(stored_path).exists()
    assert Path(stored_path).parent.name == "data"


def test_project_upload_invalid_kind_returns_422(client: TestClient, tmp_path: Path, fake_home: Path):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.post(
        "/api/project/upload",
        data={"kind": "bogus"},
        files={"file": ("hist.xy", io.BytesIO(b"x"), "text/plain")},
    )

    assert resp.status_code == 422


def test_project_upload_without_project_returns_422(client: TestClient):
    # 【demo セッション (source != "project")】: upload はプロジェクト未読込では拒否される
    resp = client.post(
        "/api/project/upload",
        data={"kind": "data"},
        files={"file": ("hist.xy", io.BytesIO(b"x"), "text/plain")},
    )
    assert resp.status_code == 422


def test_project_histograms_add_and_remove(client: TestClient, tmp_path: Path, fake_home: Path):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": "data/hist.xy",
            "instrument_path": "data/hist.instprm",
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XY",
        },
    )
    assert resp.status_code == 200
    vm = client.get("/api/viewmodel").json()
    assert len(vm["datasets"]) == 1
    hist_id = vm["datasets"][0]["id"]

    resp_bad_radiation = client.post(
        "/api/project/histograms",
        json={
            "data_path": "data/hist2.xy",
            "instrument_path": "data/hist2.instprm",
            "radiation": "not-a-radiation",
            "geometry": "bragg_brentano",
        },
    )
    assert resp_bad_radiation.status_code == 422

    resp_remove = client.post(f"/api/project/histograms/{hist_id}/remove", json={})
    assert resp_remove.status_code == 200
    vm2 = client.get("/api/viewmodel").json()
    assert vm2["datasets"] == []


def test_project_phases_add_and_remove(client: TestClient, tmp_path: Path, fake_home: Path):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.post(
        "/api/project/phases", json={"structure_path": "data/p.cif", "phase_name": "phaseA"}
    )
    assert resp.status_code == 200
    vm = client.get("/api/viewmodel").json()
    assert len(vm["phases"]) == 1

    resp_remove = client.post("/api/project/phases/phaseA/remove", json={})
    assert resp_remove.status_code == 200

    resp_remove_again = client.post("/api/project/phases/phaseA/remove", json={})
    assert resp_remove_again.status_code == 404


def test_project_settings_update(client: TestClient, tmp_path: Path, fake_home: Path):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})
    client.post(
        "/api/project/histograms",
        json={
            "data_path": "data/hist.xy",
            "instrument_path": "data/hist.instprm",
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XY",
        },
    )

    resp = client.post(
        "/api/project/settings",
        json={"two_theta_limits": [8.0, 65.0], "background_coeffs": 10, "max_cyc": 15},
    )

    assert resp.status_code == 200
    vm = client.get("/api/viewmodel").json()
    assert vm["fit"]["two_theta"] == {"min": 8.0, "max": 65.0}


# ---------------------------------------------------------------------------
# refine 実行中のプロジェクト変更系ガード (409, api-contract.md)
# ---------------------------------------------------------------------------


def test_project_lifecycle_routes_return_409_while_refine_running(
    client: TestClient, tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})
    client.post(
        "/api/project/histograms",
        json={
            "data_path": "data/hist.xy",
            "instrument_path": "data/hist.instprm",
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XY",
        },
    )
    client.post(
        "/api/project/phases", json={"structure_path": "data/p.cif", "phase_name": "phaseA"}
    )

    started_evt = threading.Event()
    release_evt = threading.Event()

    def fake_runner() -> AutoRietveldResult:
        started_evt.set()
        release_evt.wait(timeout=5)
        return _fake_result()

    monkeypatch.setattr(
        workbench_session_module, "build_default_runner",
        lambda project, ledger=None: fake_runner,
    )

    resp = client.post("/api/refine", json={})
    assert resp.status_code == 202
    assert started_evt.wait(timeout=5)

    try:
        for method, path, body in [
            ("post", "/api/project/close", {}),
            ("post", "/api/project/demo", {}),
            ("post", "/api/project/histograms/h0/remove", {}),
            (
                "post",
                "/api/project/phases",
                {"structure_path": "x.cif", "phase_name": "phaseB"},
            ),
            ("post", "/api/project/settings", {"max_cyc": 3}),
        ]:
            resp = getattr(client, method)(path, json=body)
            assert resp.status_code == 409, f"{path} did not 409 while refine running"
            assert resp.json()["error_type"] == "ConflictError"
    finally:
        release_evt.set()


# ---------------------------------------------------------------------------
# ガード変異実証 (b): DELETE ルート不在ガードが project ルート追加後も落ちること
# ---------------------------------------------------------------------------


def test_no_delete_or_put_routes_guard_detects_injected_delete_route(client: TestClient):
    """DELETE ルートを一時的に注入すると `test_no_delete_or_put_routes_are_defined` 相当の

    走査ガードが検知することを、本テスト内で実証する (恒久ガード自体は上の
    ``test_no_delete_or_put_routes_are_defined`` — ここでは新設した project ルート追加後も
    ガードの検知力が損なわれていないことを変異実証する)。
    """
    app = client.app

    @app.delete("/api/project/__mutation_test__")
    def _injected_delete() -> dict:
        return {}

    offending = [
        (getattr(route, "path", "?"), route.methods)
        for route in app.routes
        if getattr(route, "methods", None) and "DELETE" in route.methods
    ]
    assert offending, "注入した DELETE ルートが検知されなかった (ガードが機能していない)"

    # 【復元】: 注入したルートを取り除き、恒久ガードへの影響を残さない
    app.router.routes = [
        r for r in app.router.routes if getattr(r, "path", None) != "/api/project/__mutation_test__"
    ]
    offending_after = [
        (getattr(route, "path", "?"), route.methods)
        for route in app.routes
        if getattr(route, "methods", None) and "DELETE" in route.methods
    ]
    assert offending_after == []
