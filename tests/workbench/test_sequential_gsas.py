"""V2b 逐次/operando 接続 (B1-B3) の gated end-to-end テスト (`@pytest.mark.gsas`)。

CaTeO3 alpha (M9 検証データ, `tests/insitu/test_engine_gsas.py::test_cateo3_two_frame_sequential_converges`
と同一設定) の 2 フレーム (frame030/frame180) を FastAPI TestClient 経由で
POST /api/project/frames → POST /api/sequential (forward/anchored) の実 GSAS-II 精密化として駆動する。

⚠ プロジェクトは ``lifecycle.create_project`` で **tmp_path 配下**に新規作成する (``examples/
cateo3_project.json`` を直接ロードしない) — ``POST /api/project/frames`` は
``lifecycle.save_project_spec`` で spec を自動保存するため、既存 spec を直接ロードすると
リポジトリ配下の ``examples/`` を実行の副作用で汚してしまう (実害: 初版実装でこれが実際に
起きた — `examples/project.json`/`examples/workbench_out/` が生成された)。CaTeO3 の実データ
ファイル自体は絶対パス参照のみで読み取り専用のまま。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("fastapi.testclient")
from fastapi.testclient import TestClient  # noqa: E402

from tsumugin.workbench import lifecycle  # noqa: E402
from tsumugin.workbench.app import create_workbench_app  # noqa: E402
from tsumugin.workbench.session import WorkbenchSession  # noqa: E402

_CATEO3 = Path("docs/benchmark/testdata/m9/cateo3")


def _have_data() -> bool:
    return all(
        (_CATEO3 / name).exists()
        for name in (
            "NB-LM01MO_030.XRDML",
            "NB-LM01MO_180.XRDML",
            "alpha_CaTeO3_H2O.cif",
            "cateo3_CuKa.instprm",
        )
    )


pytestmark = [
    pytest.mark.gsas,
    pytest.mark.skipif(not _have_data(), reason="M9 CaTeO3 検証データが未配置"),
]


def _frames_body() -> dict:
    return {
        "frames": [
            {
                "data_path": str((_CATEO3 / "NB-LM01MO_030.XRDML").resolve()),
                "axis_value": 30.0,
                "data_format": "XRDML",
                "two_theta_limits": [12.0, 70.0],
                "label": "frame030",
            },
            {
                "data_path": str((_CATEO3 / "NB-LM01MO_180.XRDML").resolve()),
                "axis_value": 180.0,
                "data_format": "XRDML",
                "two_theta_limits": [12.0, 70.0],
                "label": "frame180",
            },
        ],
        "frame_axis": "temperature",
    }


def _new_client(tmp_path: Path) -> tuple[TestClient, WorkbenchSession]:
    """tmp_path 配下に新規プロジェクトを作り、CaTeO3 alpha を実データ絶対パスで登録する。"""
    project = lifecycle.create_project("cateo3-seq", str(tmp_path))
    session = WorkbenchSession.open_persistent(project)
    session.add_histogram(
        data_path=str((_CATEO3 / "NB-LM01MO_030.XRDML").resolve()),
        instrument_path=str((_CATEO3 / "cateo3_CuKa.instprm").resolve()),
        radiation="xray_lab",
        geometry="bragg_brentano",
        data_format="XRDML",
        two_theta_limits=[12.0, 70.0],
    )
    session.add_phase(
        structure_path=str((_CATEO3 / "alpha_CaTeO3_H2O.cif").resolve()), phase_name="alpha"
    )
    return TestClient(create_workbench_app(session)), session


def test_forward_sequential_two_frame_cateo3_converges(tmp_path: Path):
    """B1+B2: frames 設定 → forward 逐次 (alpha 単相, warm start) の実走 green を確認する。

    frame030/frame180 とも frame ごとの実 Rwp が返り、sequence viewmodel の rwp/lattice/
    phase_fraction 3 チャートが実データを持つことを検証する (数分要する)。
    """
    client, session = _new_client(tmp_path)

    resp = client.post("/api/project/frames", json=_frames_body())
    assert resp.status_code == 200, resp.text
    assert len(client.get("/api/viewmodel").json()["project"]["frames"]) == 2

    resp = client.post("/api/sequential", json={"mode": "forward"})
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=600)

    status = client.get("/api/sequential/status").json()
    assert status["status"] == "done", f"sequential did not complete: {status}"
    assert status["kind"] == "sequential"

    vm = client.get("/api/viewmodel").json()
    seq = vm["sequence"]
    assert len(seq["frames"]) == 2
    for row in seq["frames"]:
        assert row["rwp"] is not None
        assert row["rwp"] > 0.0
        assert "alpha" in row["cells"]
        assert row["cells"]["alpha"][0] > 1.0  # 格子崩壊していない

    rwp_chart = next(c for c in seq["charts"] if c["id"] == "rwp")
    assert rwp_chart["series"]["x"] == [0, 1]
    assert all(v is not None and v > 0.0 for v in rwp_chart["series"]["ys"][0])

    lattice_chart = next(c for c in seq["charts"] if c["id"] == "lattice")
    assert lattice_chart["series"] is not None
    assert any("alpha a" in label for label in lattice_chart["series"]["labels"])

    fraction_chart = next(c for c in seq["charts"] if c["id"] == "phase_fraction")
    assert fraction_chart["series"] is not None

    ledger = client.get("/api/ledger").json()
    assert any(e["text"].startswith("sequential requested") for e in ledger["entries"])
    assert any(e["text"].startswith("sequential finished") for e in ledger["entries"])

    print(
        "frame030 rwp="
        f"{seq['frames'][0]['rwp']:.2f}% frame180 rwp={seq['frames'][1]['rwp']:.2f}%"
    )


def test_anchored_sequential_two_frame_cateo3_runs_via_shared_job_slot(tmp_path: Path):
    """B3: mode=anchored (anchor_table 両フレームとも alpha) が同一ジョブ枠経由で実走する。"""
    client, session = _new_client(tmp_path)

    resp = client.post("/api/project/frames", json=_frames_body())
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/api/sequential",
        json={"mode": "anchored", "anchor_table": {"0": ["alpha"], "1": ["alpha"]}},
    )
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=600)

    status = client.get("/api/sequential/status").json()
    assert status["status"] == "done", f"anchored sequential did not complete: {status}"
    assert status["kind"] == "sequential"

    vm = client.get("/api/viewmodel").json()
    seq = vm["sequence"]
    assert len(seq["frames"]) == 2
    # 【アンカー確定数は物理依存】: anchor_table は両フレームを候補にするが、① extract_anchors は
    # 段階 B (Rietveld+validity 再確認) で高 Rwp/転移共存フレームを不採用にしうる (実測: frame180
    # は転移共存域で Rwp が高く不採用 — M9 の先例どおり)。プラミングの検証としては「1 件以上確定」
    # かつ「2 フレームとも系列結果に現れる」ことを見る (確定アンカー数そのものは固定しない)。
    assert 1 <= len(seq["anchors"]) <= 2
    for row in seq["frames"]:
        assert row["rwp"] is not None and row["rwp"] > 0.0
