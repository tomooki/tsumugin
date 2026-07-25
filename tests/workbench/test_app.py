"""``tsumugin.workbench.app`` の FastAPI ルート層テスト (`tests/test_webui.py` の流儀を踏襲)。

read-only 保証 (webui) と対称に、ワークベンチは「削除系ルートが存在しない」ことを構造的に
担保する (P2 / NFR-GUI-001)。DELETE/PUT ルート不在はガードテストとして扱い、実装を一時的に
壊して fail することを確認したうえで元に戻した (レポート参照)。
"""

from __future__ import annotations

import io
import json
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

import tsumugin.workbench.app as workbench_app_module  # noqa: E402
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
    assert set(data) == {"status", "elapsed_s", "last_event", "error", "kind"}
    assert data["status"] == "idle"
    assert data["elapsed_s"] is None
    assert data["error"] is None
    assert data["kind"] is None


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
        lambda project, ledger=None, stages_on=None, initial_occupancies=None: _fake_result,
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
        lambda project, ledger=None, stages_on=None, initial_occupancies=None: fake_runner,
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
        lambda project, ledger=None, stages_on=None, initial_occupancies=None: bad_runner,
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


def test_project_open_malformed_json_returns_422_not_404(
    client: TestClient, tmp_path: Path, fake_home: Path
):
    """セルフレビュー指摘 #3: パスは実在するが spec の内容が不正 (JSON 壊れ) なときは 422。

    修正前は ``post_project_open`` が ValueError を一律 404 NotFoundError に丸めていたため、
    「パスが見つからない」と「spec が壊れている」の区別が付かなかった。
    """
    directory = tmp_path / "projects" / "proj1"
    directory.mkdir(parents=True)
    (directory / "project.json").write_text("{not valid json", encoding="utf-8")

    resp = client.post("/api/project/open", json={"path": str(directory)})

    assert resp.status_code == 422
    body = resp.json()
    assert body["error_type"] == "ValueError"


def test_project_open_missing_referenced_data_file_returns_4xx_not_500(
    client: TestClient, tmp_path: Path, fake_home: Path
):
    """セルフレビュー指摘 #1: project.json が参照する XRDML データファイルが実在しないとき、

    生の 500 (OSError 貫通) ではなく既知の 4xx error dict になることを確認する
    (`load_project_spec` が OSError を「どのファイルが読めないか」を含む ValueError へ正規化 →
    `post_project_open` が 422 へ縮退)。
    """
    directory = tmp_path / "projects" / "proj1"
    directory.mkdir(parents=True)
    (directory / "data").mkdir()
    spec = {
        "name": "proj1",
        "histograms": [
            {
                "data_path": "data/missing.xrdml",
                "instrument_path": "data/missing.instprm",
                "radiation": "xray_lab",
                "geometry": "bragg_brentano",
                "data_format": "XRDML",
            }
        ],
        "phases": [{"structure_path": "data/p.cif", "phase_name": "phaseA"}],
    }
    (directory / "project.json").write_text(json.dumps(spec), encoding="utf-8")

    resp = client.post("/api/project/open", json={"path": str(directory)})

    assert resp.status_code != 500
    assert 400 <= resp.status_code < 500
    body = resp.json()
    assert "error" in body and "error_type" in body
    assert "missing.xrdml" in body["error"]


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
        lambda project, ledger=None, stages_on=None, initial_occupancies=None: fake_runner,
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
            ("post", "/api/project/frames", {"frames": []}),
        ]:
            resp = getattr(client, method)(path, json=body)
            assert resp.status_code == 409, f"{path} did not 409 while refine running"
            assert resp.json()["error_type"] == "ConflictError"
    finally:
        release_evt.set()


# ---------------------------------------------------------------------------
# open/create⇄refine TOCTOU レース (セルフレビュー指摘 #2, NFR-105)
# ---------------------------------------------------------------------------


def test_project_create_and_refine_are_serialized_by_the_same_lock(
    client: TestClient, tmp_path: Path, fake_home: Path, monkeypatch: pytest.MonkeyPatch
):
    """POST /api/project (create) の「ガード再確認 + I/O + swap」と POST /api/refine の起動が

    ``_SessionHolder.lock`` で直列化されることを実証する。``lifecycle.create_project`` を
    threading.Event で遅延させ、その最中に別スレッドから refine を起動しても、create 側の
    ロック保持が終わるまで refine 側が完了しないことを確認する。

    ロックを外す変異 (`_guarded_swap` から ``with holder.lock:`` を外す、または
    ``post_refine`` から ``with holder.lock:`` を外す) で本テストが fail することを実証済み
    (レポート参照)。
    """
    directory = tmp_path / "projects"
    directory.mkdir()

    entered_evt = threading.Event()
    release_evt = threading.Event()
    refine_done_evt = threading.Event()

    real_create_project = workbench_app_module.lifecycle.create_project

    def slow_create_project(name: str, dir_arg: str):
        entered_evt.set()
        release_evt.wait(timeout=5)
        return real_create_project(name, dir_arg)

    monkeypatch.setattr(workbench_app_module.lifecycle, "create_project", slow_create_project)

    create_result: list = []

    def _do_create() -> None:
        create_result.append(
            client.post("/api/project", json={"name": "proj1", "directory": str(directory)})
        )

    create_thread = threading.Thread(target=_do_create)
    create_thread.start()
    assert entered_evt.wait(timeout=5), "create_project が呼ばれなかった"

    def _do_refine() -> None:
        client.post("/api/refine", json={})
        refine_done_evt.set()

    refine_thread = threading.Thread(target=_do_refine)
    refine_thread.start()

    # 【直列化の核心】: create_project が holder.lock を保持したままブロックしている間、
    #   refine の起動 (post_refine の holder.lock 取得) は完了できないはず。
    assert not refine_done_evt.wait(timeout=0.5), (
        "refine がロック保持中に完了した = create/open⇄refine が直列化されていない (TOCTOU 再発)"
    )

    release_evt.set()
    create_thread.join(timeout=5)
    assert refine_done_evt.wait(timeout=5), "create_project 完了後も refine が完了しなかった"

    assert create_result[0].status_code == 200
    assert create_result[0].json()["source"] == "project"


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


# ---------------------------------------------------------------------------
# 解析ループ完成 (V2a' A1-A6) ルート層
# ---------------------------------------------------------------------------


def test_refine_route_stages_on_invalid_shape_returns_422(project_client: TestClient):
    resp = project_client.post("/api/refine", json={"stages_on": {"01": "not-a-bool"}})
    assert resp.status_code == 422


def test_refine_route_stages_on_unknown_key_returns_422(project_client: TestClient):
    # 【viewmodel.stages に無い nn】: _fake_project は 1 hist/1 phase を持ち実レシピの段数は
    #   高々一桁なので "99" はどの構成でも存在しない不明キーになる。
    resp = project_client.post("/api/refine", json={"stages_on": {"99": False}})
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "ValueError"


def test_refine_route_stages_on_passes_through_to_session(
    project_client: TestClient, project_session: WorkbenchSession, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_build(project, ledger=None, stages_on=None, initial_occupancies=None):
        captured["stages_on"] = stages_on
        return lambda: _fake_result()

    monkeypatch.setattr(workbench_session_module, "build_default_runner", fake_build)
    # stages_on の nn 検証を通すため viewmodel.stages に 2 段を用意する
    # (1 段のみ+OFF だと「全段 OFF は 422」の縮退 run ガードに当たるため)。
    project_session._stages = [
        {"nn": "01", "name": "s", "flags": "", "delta_rwp": "", "released": True, "gate": None},
        {"nn": "02", "name": "t", "flags": "", "delta_rwp": "", "released": True, "gate": None},
    ]

    resp = project_client.post("/api/refine", json={"stages_on": {"01": False, "02": True}})
    assert resp.status_code == 202
    project_session._job.join(timeout=5)
    assert captured["stages_on"] == {"01": False, "02": True}


# --- Tier1 sidecar (C1): GSAS 不在時の 422 縮退 (HTTP 境界) --------------


def test_refine_route_returns_422_when_gsas_unavailable(
    project_client: TestClient, monkeypatch
):
    monkeypatch.setattr(workbench_session_module, "gsasii_available", lambda: False)
    resp = project_client.post("/api/refine", json={})
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "GSASUnavailableError"


def test_get_state_route_reflects_gsas_available_false(
    project_client: TestClient, monkeypatch
):
    monkeypatch.setattr(workbench_session_module, "gsasii_available", lambda: False)
    resp = project_client.get("/api/state")
    assert resp.status_code == 200
    assert resp.json()["status"]["gsas_available"] is False


# --- A4: 相同定ジョブ ------------------------------------------------------


def test_phaseid_route_invalid_mode_returns_422(project_client: TestClient):
    resp = project_client.post("/api/phaseid", json={"mode": "bogus"})
    assert resp.status_code == 422


def test_phaseid_route_without_project_returns_422(client: TestClient):
    resp = client.post("/api/phaseid", json={"mode": "pattern"})
    assert resp.status_code == 422


def test_phaseid_status_route_matches_refine_status_shape(project_client: TestClient):
    resp = project_client.get("/api/phaseid/status")
    assert resp.status_code == 200
    assert set(resp.json()) == {"status", "elapsed_s", "last_event", "error", "kind"}


def test_phaseid_add_route_missing_fields_returns_422(project_client: TestClient):
    resp = project_client.post("/api/phaseid/add", json={"formula": ""})
    assert resp.status_code == 422


def test_phaseid_route_returns_409_while_refine_running(
    project_client: TestClient, project_session: WorkbenchSession
):
    started_evt = threading.Event()
    release_evt = threading.Event()

    def fake_runner() -> AutoRietveldResult:
        started_evt.set()
        release_evt.wait(timeout=5)
        return _fake_result()

    project_session._job.start(fake_runner, on_success=lambda r: None, on_failure=lambda e: None)
    started_evt.wait(timeout=5)
    try:
        resp = project_client.post("/api/phaseid", json={"mode": "pattern"})
        assert resp.status_code == 409
        assert resp.json()["error_type"] == "ConflictError"
    finally:
        release_evt.set()
        project_session._job.join(timeout=5)


# --- A5: マルチスタート -----------------------------------------------------


def test_multistart_route_invalid_types_returns_422(project_client: TestClient):
    resp = project_client.post("/api/multistart", json={"n_starts": "not-an-int"})
    assert resp.status_code == 422


def test_multistart_route_without_project_returns_422(client: TestClient):
    resp = client.post("/api/multistart", json={})
    assert resp.status_code == 422


def test_multistart_status_route_matches_refine_status_shape(project_client: TestClient):
    resp = project_client.get("/api/multistart/status")
    assert resp.status_code == 200
    assert set(resp.json()) == {"status", "elapsed_s", "last_event", "error", "kind"}


def test_multistart_route_returns_409_while_refine_running(
    project_client: TestClient, project_session: WorkbenchSession
):
    started_evt = threading.Event()
    release_evt = threading.Event()

    def fake_runner() -> AutoRietveldResult:
        started_evt.set()
        release_evt.wait(timeout=5)
        return _fake_result()

    project_session._job.start(fake_runner, on_success=lambda r: None, on_failure=lambda e: None)
    started_evt.wait(timeout=5)
    try:
        resp = project_client.post("/api/multistart", json={"n_starts": 3, "scale": 0.007})
        assert resp.status_code == 409
        assert resp.json()["error_type"] == "ConflictError"
    finally:
        release_evt.set()
        project_session._job.join(timeout=5)


# --- A6: gpx エクスポート ----------------------------------------------------


def test_export_gpx_route_returns_404_before_refine(project_client: TestClient):
    resp = project_client.get("/api/export/gpx")
    assert resp.status_code == 404
    assert resp.json()["error_type"] == "NotFoundError"


def test_export_gpx_route_returns_404_without_project(client: TestClient):
    resp = client.get("/api/export/gpx")
    assert resp.status_code == 404


def test_export_gpx_route_downloads_file_with_project_name(
    project_client: TestClient, project_session: WorkbenchSession
):
    gpx_path = Path(project_session._project.gpx_path)
    gpx_path.parent.mkdir(parents=True, exist_ok=True)
    gpx_path.write_bytes(b"fake gpx contents")

    resp = project_client.get("/api/export/gpx")

    assert resp.status_code == 200
    assert resp.content == b"fake gpx contents"
    from urllib.parse import unquote

    disposition = unquote(resp.headers.get("content-disposition", ""))
    assert f"{project_session._project.name}.gpx" in disposition


# ---------------------------------------------------------------------------
# V2b B1-B4: フレーム/逐次/echem ルート
# ---------------------------------------------------------------------------


def _seq_route_project(tmp_path: Path) -> "WorkbenchProject":
    from tsumugin.insitu.model import FrameSpec

    hist = HistogramSpec(
        data_path=str(tmp_path / "d.xy"), instrument_path=str(tmp_path / "d.instprm"),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XY",
    )
    phase = PhaseSpec(structure_path=str(tmp_path / "phase.cif"), phase_name="alpha")
    (tmp_path / "frame0.xy").write_text("10.0 100.0\n10.1 110.0\n", encoding="utf-8")
    frame = FrameSpec(data_path=str(tmp_path / "frame0.xy"), axis_value=30.0, data_format="XY")
    return WorkbenchProject(
        name="seq route fixture", histograms=(hist,), phases=(phase,), frames=(frame,),
        gpx_path=str(tmp_path / "refined.gpx"), spec_dir=str(tmp_path),
    )


@pytest.fixture()
def seq_session(tmp_path) -> WorkbenchSession:
    return WorkbenchSession.from_project(_seq_route_project(tmp_path))


@pytest.fixture()
def seq_client(seq_session: WorkbenchSession) -> TestClient:
    return TestClient(create_workbench_app(seq_session))


def test_post_project_frames_replaces_and_reflects_in_viewmodel(tmp_path: Path):
    # 【spec_dir を明示 (project_client/project_session は使わない)】: `_fake_project` は
    #   spec_dir 既定 "." のため、frames 設定 (自動保存が伴う) にそれを使うとリポジトリ直下の
    #   カレントディレクトリへ project.json を書き出してしまう (実害: 初版実装で発生・report 参照)。
    seq_session = WorkbenchSession.from_project(_seq_route_project(tmp_path))
    seq_client_local = TestClient(create_workbench_app(seq_session))

    data_path = tmp_path / "frame_extra.xy"
    data_path.write_text("10.0 100.0\n10.1 110.0\n", encoding="utf-8")
    resp = seq_client_local.post(
        "/api/project/frames",
        json={"frames": [{"data_path": str(data_path), "axis_value": 30.0, "data_format": "XY"}]},
    )
    assert resp.status_code == 200, resp.text

    vm = seq_client_local.get("/api/viewmodel").json()
    assert len(vm["project"]["frames"]) == 1
    assert vm["project"]["frames"][0]["axis_value"] == 30.0
    assert Path(seq_session._project.spec_dir).resolve() == tmp_path.resolve()


def test_post_project_frames_non_list_returns_422(project_client: TestClient):
    resp = project_client.post("/api/project/frames", json={"frames": "nope"})
    assert resp.status_code == 422


def test_post_sequential_without_frames_returns_422(project_client: TestClient):
    resp = project_client.post("/api/sequential", json={"mode": "forward"})
    assert resp.status_code == 422
    assert resp.json()["error_type"] == "ValueError"


def test_post_sequential_invalid_mode_returns_422(seq_client: TestClient):
    resp = seq_client.post("/api/sequential", json={"mode": "bogus"})
    assert resp.status_code == 422


def test_post_sequential_anchored_without_anchor_table_returns_422(seq_client: TestClient):
    resp = seq_client.post("/api/sequential", json={"mode": "anchored"})
    assert resp.status_code == 422


def test_post_sequential_starts_job_and_status_route_matches_refine_status_shape(
    seq_client: TestClient, seq_session: WorkbenchSession, monkeypatch: pytest.MonkeyPatch
):
    import tsumugin.mcp.insitu_tools as insitu_tools_module

    def fake_sequential_rietveld(frames, phases, **kw):
        return {
            "phase_names": ["alpha"],
            "frames": [
                {
                    "frame_index": 0, "axis_value": 30.0, "data_path": "frame0.xy",
                    "rwp": 9.0, "gof": 1.2, "phase_names": ["alpha"],
                    "refined_cells": {"alpha": [5.0, 5.0, 5.0, 90.0, 90.0, 90.0]},
                    "phase_fractions": {"alpha": 1.0}, "changepoint": False,
                    "changepoint_reasons": [], "validity_passed": True, "refine_failed": False,
                    "residual_report": None, "phase_weight_fractions": {"alpha": 1.0},
                    "phase_weight_fraction_esd": {}, "cell_esd": {},
                    "alkali_x_echem": None, "alkali_x_xrd": None, "alkali_x_xrd_esd": None,
                    "alkali_per_phase": {}, "alkali_residual": None,
                    "alkali_constraint_applied": "", "alkali_feasibility": "",
                }
            ],
            "appearances": [], "warnings": [], "reason": "",
        }

    monkeypatch.setattr(insitu_tools_module, "sequential_rietveld", fake_sequential_rietveld)

    resp = seq_client.post("/api/sequential", json={"mode": "forward"})
    assert resp.status_code == 202

    seq_session._job.join(timeout=5)

    status = seq_client.get("/api/sequential/status").json()
    assert status["status"] == "done"
    assert status["kind"] == "sequential"
    assert set(status.keys()) == {"status", "elapsed_s", "last_event", "error", "kind"}

    vm = seq_client.get("/api/viewmodel").json()
    assert len(vm["sequence"]["frames"]) == 1
    assert vm["sequence"]["frames"][0]["rwp"] == 9.0


def test_post_sequential_returns_409_while_refine_running(
    seq_client: TestClient, seq_session: WorkbenchSession, monkeypatch: pytest.MonkeyPatch
):
    started_evt = threading.Event()
    release_evt = threading.Event()

    def blocking_runner() -> AutoRietveldResult:
        started_evt.set()
        release_evt.wait(timeout=5)
        return _fake_result()

    monkeypatch.setattr(
        workbench_session_module, "build_default_runner",
        lambda project, ledger=None, stages_on=None, initial_occupancies=None: blocking_runner,
    )
    resp = seq_client.post("/api/refine", json={})
    assert resp.status_code == 202
    assert started_evt.wait(timeout=5)
    try:
        resp = seq_client.post("/api/sequential", json={"mode": "forward"})
        assert resp.status_code == 409
        assert resp.json()["error_type"] == "ConflictError"
    finally:
        release_evt.set()
        seq_session._job.join(timeout=5)


def test_post_echem_missing_mpr_path_returns_422(seq_client: TestClient):
    resp = seq_client.post("/api/echem", json={})
    assert resp.status_code == 422


def test_post_echem_invalid_sign_returns_422(seq_client: TestClient):
    resp = seq_client.post("/api/echem", json={"mpr_path": "x.mpr", "sign": 2})
    assert resp.status_code == 422


def test_post_echem_align_failure_returns_422(
    seq_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import tsumugin.mcp.echem_tools as echem_tools_module

    monkeypatch.setattr(
        echem_tools_module, "align_echem",
        lambda *a, **kw: {"error": "galvani not installed", "error_type": "EchemUnavailableError"},
    )
    resp = seq_client.post(
        "/api/echem", json={"mpr_path": "x.mpr", "offset_s": 0.0, "interval_s": 1.0}
    )
    assert resp.status_code == 422


def test_post_echem_success_returns_curve_and_null_targets(
    seq_client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    import tsumugin.mcp.echem_tools as echem_tools_module

    monkeypatch.setattr(
        echem_tools_module, "align_echem",
        lambda *a, **kw: {
            "curve": {"start_timestamp": 0.0, "n_points": 1, "duration_s": 0.0,
                      "voltage_min": 1.0, "voltage_max": 1.0, "source_path": "x.mpr"},
            "frames": [{"frame": 0, "time_s": 0.0, "time_h": 0.0, "voltage_v": 1.5,
                        "charge_mah": 0.0, "state": "rest", "in_span": True}],
            "n_in_span": 1, "reason": "",
        },
    )
    resp = seq_client.post(
        "/api/echem", json={"mpr_path": "x.mpr", "offset_s": 0.0, "interval_s": 1.0}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["targets"] is None
    assert body["curve"]["n_points"] == 1


def test_project_upload_allows_echem_kind(
    client: TestClient, tmp_path: Path, fake_home: Path
):
    directory = tmp_path / "projects"
    directory.mkdir()
    client.post("/api/project", json={"name": "proj1", "directory": str(directory)})

    resp = client.post(
        "/api/project/upload",
        files={"file": ("run.mpr", io.BytesIO(b"fake mpr bytes"), "application/octet-stream")},
        data={"kind": "echem"},
    )
    assert resp.status_code == 200, resp.text
    stored_path = resp.json()["stored_path"]
    assert Path(stored_path).exists()
    assert Path(stored_path).name == "run.mpr"
