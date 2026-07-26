"""MEM 密度マップ (V3b, FR-601) の gated 実走テスト (``@pytest.mark.gsas``)。

`examples/cateo3_project.json` (M9 CaTeO3 alpha, `test_analysis_loop_gsas.py` と同一設定) を実
プロジェクトとしてロードし、FastAPI TestClient 経由で (1) 実 GSAS-II Rietveld 精密化を 1 回駆動
して gpx を作り、(2) 続けて POST /api/mem で実 Dysnomia MEM を回し、
``viewmodel.structure.mem.map.values`` が実密度で埋まることを確認する。

Dysnomia バイナリが解決できない環境では ``resolve_dysnomia_binary()`` が None を返す時点で skip
する (`docs/design/gui-workbench/api-contract.md` §MEM 密度マップ「Dysnomia バイナリ不在は 422」
と同じ縮退 — gated テストでは高価な refine の前に確認し、時間を無駄にしない)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from tsumugin.mem.gsas import resolve_dysnomia_binary  # noqa: E402
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


def test_run_mem_on_refined_cateo3_produces_real_density_map():
    if resolve_dysnomia_binary() is None:
        pytest.skip("Dysnomia バイナリが見つかりません (resolve_dysnomia_binary() が None)")

    project = load_project_spec(_SPEC)
    session = WorkbenchSession.from_project(project)
    client = TestClient(create_workbench_app(session))

    # --- (1): 実 GSAS-II Rietveld 精密化を 1 回駆動して gpx を作る --------------------
    resp = client.post("/api/refine", json={})
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=900)
    status = client.get("/api/refine/status").json()
    assert status["status"] == "done", f"refine did not complete: {status}"

    # --- (2): 実 Dysnomia MEM を回す -------------------------------------------------
    resp = client.post("/api/mem", json={"map_type": "Fobs"})
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=300)
    mem_status = client.get("/api/mem/status").json()
    assert mem_status["status"] == "done", f"mem did not complete: {mem_status}"

    vm = client.get("/api/viewmodel").json()
    mem = vm["structure"]["mem"]
    assert mem is not None
    map_ = mem["map"]
    assert map_ is not None, "MEM 完了後も structure.mem.map が None (実 .grd が読めなかった?)"
    assert map_["axis"] == "c"
    assert map_["nx"] > 0
    assert map_["ny"] > 0
    assert len(map_["values"]) == map_["nx"]
    assert all(len(row) == map_["ny"] for row in map_["values"])
    assert map_["vmin"] < map_["vmax"], f"vmin/vmax が実密度でない: {map_['vmin']} / {map_['vmax']}"
