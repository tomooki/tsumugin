"""GUI workbench 実解析接続の gated end-to-end テスト (`@pytest.mark.gsas`)。

`examples/cateo3_project.json` (M9 CaTeO3 alpha, `tests/insitu/test_engine_gsas.py` と同一設定
[Kα1 instprm・背景 24 項・two_theta_limits 12-70°]) を実プロジェクトとしてロードし、FastAPI
TestClient 経由で POST /api/refine → ポーリング完了 → viewmodel の fit.metrics/plot/validity が
実値で埋まることを検証する (REQ-GUI-012/013)。M9 の既知到達 (~13.4%) に対する緩い受け入れ
(20% 未満) とする。データ未同梱環境は skip。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gsas

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
        for name in (
            "NB-LM01MO_030.XRDML",
            "alpha_CaTeO3_H2O.cif",
            "cateo3_CuKa.instprm",
        )
    )


@pytest.mark.skipif(
    not _have_data(),
    reason="examples/cateo3_project.json 又は M9 CaTeO3 検証データが未配置",
)
def test_project_refine_end_to_end_converges_below_20_percent_rwp():
    project = load_project_spec(_SPEC)
    session = WorkbenchSession.from_project(project)
    client = TestClient(create_workbench_app(session))

    resp = client.post("/api/refine", json={})
    assert resp.status_code == 202
    assert resp.json() == {"status": "started"}

    # 【上限 10 分】: CaTeO3 alpha 単相・背景 24 項・max_cyc 20 (M9 実測で数分オーダー)。
    session._job.join(timeout=600)

    status = client.get("/api/refine/status").json()
    assert status["status"] == "done", f"refine did not complete: {status}"

    vm = client.get("/api/viewmodel").json()

    rwp_row = next(m for m in vm["fit"]["metrics"] if m["key"] == "rwp")
    rwp_value = float(rwp_row["value"].rstrip("%"))
    assert rwp_value < 20.0, f"Rwp={rwp_value}% (M9 既知到達 ~13.4%)"

    plot = vm["fit"]["plot"]["h0"]
    assert plot["ycalc"] is not None
    assert len(plot["ycalc"]) == len(plot["x"])

    assert len(vm["fit"]["validity"]) > 0

    ledger = client.get("/api/ledger").json()
    assert ledger["verified"] is True
    assert any(e["text"].startswith("refine finished") for e in ledger["entries"])
