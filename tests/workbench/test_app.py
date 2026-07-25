"""``tsumugin.workbench.app`` の FastAPI ルート層テスト (`tests/test_webui.py` の流儀を踏襲)。

read-only 保証 (webui) と対称に、ワークベンチは「削除系ルートが存在しない」ことを構造的に
担保する (P2 / NFR-GUI-001)。DELETE/PUT ルート不在はガードテストとして扱い、実装を一時的に
壊して fail することを確認したうえで元に戻した (レポート参照)。
"""

from __future__ import annotations

import sys

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from tsumugin.workbench.app import create_workbench_app  # noqa: E402
from tsumugin.workbench.session import WorkbenchSession  # noqa: E402


@pytest.fixture()
def session() -> WorkbenchSession:
    return WorkbenchSession.create_demo()


@pytest.fixture()
def client(session: WorkbenchSession) -> TestClient:
    return TestClient(create_workbench_app(session))


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
