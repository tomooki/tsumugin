"""``tsumugin.workbench.app`` の FastAPI ルート層テスト (`tests/test_webui.py` の流儀を踏襲)。

read-only 保証 (webui) と対称に、ワークベンチは「削除系ルートが存在しない」ことを構造的に
担保する (P2 / NFR-GUI-001)。DELETE/PUT ルート不在はガードテストとして扱い、実装を一時的に
壊して fail することを確認したうえで元に戻した (レポート参照)。
"""

from __future__ import annotations

import sys
import threading

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
