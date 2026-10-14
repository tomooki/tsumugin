"""fit-then-judge P1c: GUI の精密化が実 GSAS で出版状態と sidecar を作る (合成 `S-dev` — hold-out を使わない)。

GUI の MEM が同じ gpx から `input_publication.state: "known"` を読めることまで確かめる (以前は GUI の精密化が
sidecar を書かなかったので、GUI の MEM の入力は常に状態不明だった)。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gsas


def test_a_gui_refinement_writes_the_publication_state_and_the_sidecar(tmp_path):
    import importlib.util
    from pathlib import Path

    import numpy as np

    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.claims.publication import input_publication
    from tsumugin.workbench.project import WorkbenchProject
    from tsumugin.workbench.session import WorkbenchSession

    # 合成 ZnO の生成は既存の gated テストの関数を使う (別パッケージなのでパスで読む)
    src = Path(__file__).resolve().parents[1] / "autorietveld" / "test_engine_polar_origin.py"
    spec = importlib.util.spec_from_file_location("_zno_synthetic", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    _synthetic_zno = mod._synthetic_zno

    xye, instprm, start = _synthetic_zno(tmp_path)
    x, y, _ = np.loadtxt(xye, unpack=True)
    noisy = np.random.default_rng(0).poisson(y).astype(float)
    np.savetxt(xye, np.column_stack([x, noisy, np.sqrt(np.maximum(noisy, 1.0))]), fmt="%.6f")
    out = tmp_path / "workbench_out"
    out.mkdir()
    project = WorkbenchProject(
        name="zno",
        histograms=(HistogramSpec(
            data_path=str(xye), instrument_path=str(instprm), radiation=Radiation.XRAY_LAB,
            geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
        ),),
        phases=(PhaseSpec(str(start), "ZnO"),),
        gpx_path=str(out / "refined.gpx"),
        spec_dir=str(tmp_path),
    )
    session = WorkbenchSession.from_project(project)
    assert session.request_refine() == {"status": "started"}
    session._job.join(timeout=600)
    assert session.refine_status()["status"] == "done", session.refine_status()

    pub = session.viewmodel()["publication"]
    assert pub["error"] is None and pub["n_values"] > 0
    assert pub["sidecar"].endswith("refined.claims.json")
    assert any(r["key"].startswith("coord:ZnO.O1") for r in pub["rows"])
    # GUI の MEM の入力 (同じ gpx) から出版状態が読める
    assert input_publication(project.gpx_path)["state"] == "known"
