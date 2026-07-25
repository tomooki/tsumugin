"""解析ループ完成 (V2a' A1-A6) の gated end-to-end テスト (`@pytest.mark.gsas`)。

`examples/cateo3_project.json` (M9 CaTeO3 alpha, `tests/workbench/test_e2e_gsas.py` と同一設定
[Kα1 instprm・背景 24 項・two_theta_limits 12-70°]) を実プロジェクトとしてロードし、FastAPI
TestClient 経由で実 GSAS-II 精密化を駆動する。

- (a)+(b)+(c) を 1 テスト関数に統合 (実行時間節約, PLAYBOOK/task 指示どおり):
  (a) ``stages_on`` で 1 段 off → stage 履歴にその段が現れない (A1)
  (b) refine 後 ``structure.sites`` に実サイト (Ca/Te/O 系ラベル) + lock (A2)
  (c) occ apply → 再 refine → gpx 抽出サイトの occ 初期値が反映されている (A3)
- (d) ``run_multistart_rietveld`` n=3 → basin 3 点 (A5, 独立テスト — 3 回の完全精密化を要するため
  実行時間の見積りを分離する)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from tsumugin.workbench.app import create_workbench_app  # noqa: E402
from tsumugin.workbench.project import load_project_spec  # noqa: E402
from tsumugin.workbench.session import WorkbenchSession  # noqa: E402

_SPEC = Path("examples/cateo3_project.json")
_CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")


def _have_data() -> bool:
    return _SPEC.exists() and all(
        (_CATEO3 / name).exists()
        for name in ("NB-LM01MO_030.XRDML", "alpha_CaTeO3_H2O.cif", "cateo3_CuKa.instprm")
    )


pytestmark = [
    pytest.mark.gsas,
    pytest.mark.skipif(
        not _have_data(), reason="examples/cateo3_project.json 又は M9 CaTeO3 検証データが未配置"
    ),
]


def test_stages_on_filters_real_sites_and_occ_revision_round_trip():
    """(a) stages_on off の段が stage 履歴に現れない / (b) 実サイト抽出 / (c) occ revision 再精密化。"""
    project = load_project_spec(_SPEC)
    session = WorkbenchSession.from_project(project)
    client = TestClient(create_workbench_app(session))

    stages_before = client.get("/api/viewmodel").json()["stages"]
    assert len(stages_before) >= 2
    disabled = stages_before[-1]  # 最終段 (asymmetry 等) を off にしても収束は妨げない

    # --- (a): stages_on で最終段を off にして精密化 -----------------------------------
    resp = client.post("/api/refine", json={"stages_on": {disabled["nn"]: False}})
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=600)
    status = client.get("/api/refine/status").json()
    assert status["status"] == "done", f"refine did not complete: {status}"

    vm = client.get("/api/viewmodel").json()
    history_stages = [row["stage"] for row in vm["fit"]["history"]]
    assert not any(disabled["name"] in stage for stage in history_stages), (
        f"off にした段 {disabled['name']!r} が stage 履歴に現れている: {history_stages}"
    )

    # --- (b): 実サイト抽出 (Ca/Te/O 系ラベル + lock) -----------------------------------
    sites = vm["structure"]["sites"]
    assert len(sites) > 0
    elements = {s["el"] for s in sites}
    assert elements & {"Ca", "Te", "O"}, f"CaTeO3 の元素が実サイトに見当たらない: {elements}"
    for s in sites:
        assert set(s["lock"]) == {"x", "y", "z"}
        assert all(isinstance(v, bool) for v in s["lock"].values())
        assert s["occ"] != ""  # 占有率が実値で埋まっている (空文字=未抽出ではない)

    # --- (c): occ を変えて apply → 再精密化 → gpx 抽出サイトの occ 初期値へ反映 ----------
    target = sites[0]
    original_occ = float(target["occ"])
    new_occ = 0.5 if abs(original_occ - 0.5) > 0.05 else 0.4
    revised_sites = [dict(s) for s in sites]
    revised_sites[0]["occ"] = f"{new_occ:.4f}"

    apply_resp = client.post(
        "/api/structure/apply", json={"sites": revised_sites, "note": "A3 occ revision test"}
    )
    assert apply_resp.status_code == 200, apply_resp.text

    refine_resp = client.post("/api/refine", json={})
    assert refine_resp.status_code == 202, refine_resp.text
    session._job.join(timeout=600)
    status2 = client.get("/api/refine/status").json()
    assert status2["status"] == "done", f"second refine did not complete: {status2}"

    vm2 = client.get("/api/viewmodel").json()
    site_after = next(s for s in vm2["structure"]["sites"] if s["label"] == target["label"])
    # alpha CaTeO3 は混合占有サイトを持たないため、occupancy 段は recipe に含まれず
    # initial_occupancies でシードした値がそのまま (未精密化で) 保持される。
    assert float(site_after["occ"]) == pytest.approx(new_occ, abs=1e-3), (
        f"occ revision が再精密化に反映されていない: expected~{new_occ}, got {site_after['occ']}"
    )


def test_multistart_three_starts_populate_basin_points():
    """(d) run_multistart_rietveld n=3 → hypotheses.basin に 3 点 + evidence に corroborated 行。"""
    project = load_project_spec(_SPEC)
    session = WorkbenchSession.from_project(project)
    client = TestClient(create_workbench_app(session))

    resp = client.post("/api/multistart", json={"n_starts": 3, "scale": 0.007})
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=600)

    status = client.get("/api/multistart/status").json()
    assert status["status"] == "done", f"multistart did not complete: {status}"

    hyp = client.get("/api/hypotheses").json()
    basin = hyp["basin"]
    assert basin is not None
    assert len(basin["points"]) == 3
    for point in basin["points"]:
        assert point["x"] is not None
        assert point["y"] is not None
    assert any(row[0] == "corroborated" for row in hyp["evidence"])

    ledger = client.get("/api/ledger").json()
    assert any(e["text"].startswith("multistart finished") for e in ledger["entries"])
