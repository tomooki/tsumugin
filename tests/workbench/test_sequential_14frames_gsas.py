"""GUI workbench の SEQUENCE を CaTeO3 全 14 フレーム実データで検証する gated end-to-end テスト。

`tests/workbench/test_sequential_gsas.py` (frame030/frame180 の 2 フレーム) の延長で、同梱の全 14
フレーム (`scratchpad/cateo3_frames14/NB-LM01MO_{030..420}.XRDML`) を **workbench API 経路のみ**
(`POST /api/project/frames` → `POST /api/sequential`) で駆動する。① `run_sequential_rietveld` を
直接呼ばない — GUI が実運用スケールで本当に通るかを検証するのが目的。

instrument 設定は `scratchpad/cateo3_full_mp_gsas.py` / README の教訓 (実験室 X 線は背景 24 項・
max_cyc 20 が必要) に合わせ `POST /api/project/settings` で明示する (既定 background_coeffs=6 は
frame030 単体でも不足することが分かっている)。

forward モード 1 本 (フレーム単相 alpha のみ、B5 承認カードの生成有無を観察) + anchored モード
1 本 (frame0=alpha, frame13=delta の 2 アンカー) を実走する。所要は合計で数十分〜1 時間規模。
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
_FRAMES14 = Path("scratchpad/cateo3_frames14")
_AXES = [30, 60, 90, 120, 150, 180, 210, 240, 270, 300, 330, 360, 390, 420]


def _have_data() -> bool:
    if not all(
        (_CATEO3 / name).exists()
        for name in ("alpha_CaTeO3_H2O.cif", "delta_CaTeO3.cif", "cateo3_CuKa.instprm")
    ):
        return False
    return all((_FRAMES14 / f"NB-LM01MO_{axis:03d}.XRDML").exists() for axis in _AXES)


pytestmark = [
    pytest.mark.gsas,
    pytest.mark.skipif(not _have_data(), reason="CaTeO3 全14フレーム実データが未配置"),
]


def _frames_body() -> dict:
    return {
        "frames": [
            {
                "data_path": str((_FRAMES14 / f"NB-LM01MO_{axis:03d}.XRDML").resolve()),
                "axis_value": float(axis),
                "data_format": "XRDML",
                "two_theta_limits": [12.0, 70.0],
                "label": f"frame{axis:03d}",
            }
            for axis in _AXES
        ],
        "frame_axis": "temperature",
    }


def _new_client(tmp_path: Path) -> tuple[TestClient, WorkbenchSession]:
    """tmp_path 配下に新規プロジェクトを作り、CaTeO3 alpha を実データ絶対パスで登録する。

    ⚠ `examples/` 配下の既存 spec を直接ロードしない (`test_sequential_gsas.py` と同じ理由 —
    POST /api/project/frames は spec を自動保存するため、リポジトリを実行の副作用で汚さないように
    tmp_path 配下で新規作成する)。
    """
    project = lifecycle.create_project("cateo3-seq14", str(tmp_path))
    session = WorkbenchSession.open_persistent(project)
    session.add_histogram(
        data_path=str((_FRAMES14 / "NB-LM01MO_030.XRDML").resolve()),
        instrument_path=str((_CATEO3 / "cateo3_CuKa.instprm").resolve()),
        radiation="xray_lab",
        geometry="bragg_brentano",
        data_format="XRDML",
        two_theta_limits=[12.0, 70.0],
    )
    session.add_phase(
        structure_path=str((_CATEO3 / "alpha_CaTeO3_H2O.cif").resolve()), phase_name="alpha"
    )
    client = TestClient(create_workbench_app(session))
    # README/scratchpad の教訓: 実験室 X 線は既定 background_coeffs=6 では frame030 単体でも
    # 不足 (24 項必要)。max_cyc も 20 に上げる (scratchpad/cateo3_full_mp_gsas.py と同一設定)。
    resp = client.post(
        "/api/project/settings", json={"background_coeffs": 24, "max_cyc": 20}
    )
    assert resp.status_code == 200, resp.text
    return client, session


def test_forward_sequential_14frame_cateo3(tmp_path: Path):
    """B1+B2: 全14フレーム forward 逐次 (alpha 単相, warm start) の実走 green を確認する。

    既知挙動 (docs/benchmark/testdata/m9/README.md): frame030 alpha 単相 Rwp ~12-13%、昇温で
    alpha が脱水し単相 Rwp が上昇 (frame060 ~24%, frame120 ~57%)。GUI 経路 (forward) は phase_id
    を渡さない設計 (B5 承認カード経由が唯一の新相追加経路、提案≠適用) なので、本テストは alpha
    単相のまま全 14 フレームを通し、sequence viewmodel の 3 チャート + per-frame 表が正しく
    埋まることと、Rwp の傾向が既知挙動と整合することを確認する。
    """
    client, session = _new_client(tmp_path)

    resp = client.post("/api/project/frames", json=_frames_body())
    assert resp.status_code == 200, resp.text
    assert len(client.get("/api/viewmodel").json()["project"]["frames"]) == 14

    resp = client.post("/api/sequential", json={"mode": "forward"})
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=None)

    status = client.get("/api/sequential/status").json()
    assert status["status"] == "done", f"sequential did not complete: {status}"
    assert status["kind"] == "sequential"

    vm = client.get("/api/viewmodel").json()
    seq = vm["sequence"]
    assert len(seq["frames"]) == 14

    print("\n===== forward 14-frame CaTeO3 (GUI /api/sequential) =====")
    for row in seq["frames"]:
        print(
            f"  frame {row['frame']} axis={row['axis_value']} rwp={row['rwp']} "
            f"cells={row['cells']} changepoint={row['changepoint']}"
        )

    for row in seq["frames"]:
        assert row["rwp"] is not None and row["rwp"] > 0.0
        assert "alpha" in row["cells"]
        assert row["cells"]["alpha"][0] > 1.0  # 格子崩壊していない

    rwp_chart = next(c for c in seq["charts"] if c["id"] == "rwp")
    assert rwp_chart["series"]["x"] == list(range(14))
    assert all(v is not None and v > 0.0 for v in rwp_chart["series"]["ys"][0])

    lattice_chart = next(c for c in seq["charts"] if c["id"] == "lattice")
    assert lattice_chart["series"] is not None
    assert any("alpha a" in label for label in lattice_chart["series"]["labels"])

    fraction_chart = next(c for c in seq["charts"] if c["id"] == "phase_fraction")
    assert fraction_chart["series"] is not None

    # frame030 (index 0) は既知挙動どおり低 Rwp のはず (~12-13%、大きく外れなければチュートリアル級)。
    rwp0 = seq["frames"][0]["rwp"]
    assert rwp0 < 20.0, f"frame030 rwp unexpectedly high: {rwp0}"

    # 昇温で alpha 単相の Rwp が中盤で悪化する既知挙動 (frame120 目安 ~57%)。
    mid_rwps = [row["rwp"] for row in seq["frames"][2:6]]
    assert max(mid_rwps) > rwp0, "mid-series rwp did not rise above frame030 as expected"

    ledger = client.get("/api/ledger").json()
    assert any(e["text"].startswith("sequential requested") for e in ledger["entries"])
    assert any(e["text"].startswith("sequential finished") for e in ledger["entries"])
    # 進捗ハートビート: 14 フレームの実 GSAS 逐次は既定 15s 間隔のハートビートが 1 件以上
    # ledger に載るはずの所要になる。**ledger view の項目は {index,time,actor,text,hash,
    # revert_to} で `kind` を持たない** (api-contract.md GET /api/ledger) ため、表示テキストで
    # 判定する — kind を見に行くと KeyError で落ちる (実走で踏んだ)。
    progress_entries = [
        e for e in ledger["entries"] if e["text"].startswith("sequential running")
    ]
    assert progress_entries, "進捗ハートビートが ledger に無い (契約: 進捗 = ledger)"
    print(f"  progress heartbeat entries: {len(progress_entries)}")

    # B5: changepoint/未説明残差のフレームで新相提案の承認カードが立つはず (提案≠適用)。
    transcript = client.get("/api/viewmodel").json()["transcript"]
    np_cards = [t for t in transcript if str(t.get("action_id", "")).startswith("np-")]
    print(f"  B5 new-phase approval cards: {[c.get('action_id') for c in np_cards]}")

    print(
        "frame summary: "
        + ", ".join(f"{row['axis_value']}={row['rwp']:.2f}%" for row in seq["frames"])
    )


def test_anchored_sequential_14frame_cateo3(tmp_path: Path):
    """B3: anchor_table (frame0=alpha, frame13=delta) で M10 bic crossover が転移域を拾うか観察する。

    実測 delta CIF (`delta_CaTeO3.cif`) をカタログに含め、frame0 (alpha) と frame13 (delta) を
    アンカーに指定する。M10 の bic crossover 選定が転移フレームをどこに置くかは物理依存 (CLAUDE.md
    "operando 解析の既定手順" 節) — 拾えても拾えなくても結果を正直に報告する。
    """
    client, session = _new_client(tmp_path)
    # anchor_table が delta を参照できるよう phases に追加 (catalog union, api-contract.md)。
    resp = client.post(
        "/api/project/phases",
        json={
            "structure_path": str((_CATEO3 / "delta_CaTeO3.cif").resolve()),
            "phase_name": "delta",
        },
    )
    assert resp.status_code == 200, resp.text

    resp = client.post("/api/project/frames", json=_frames_body())
    assert resp.status_code == 200, resp.text

    resp = client.post(
        "/api/sequential",
        json={
            "mode": "anchored",
            "anchor_table": {"0": ["alpha"], "13": ["delta"]},
        },
    )
    assert resp.status_code == 202, resp.text
    session._job.join(timeout=None)

    status = client.get("/api/sequential/status").json()
    assert status["status"] == "done", f"anchored sequential did not complete: {status}"
    assert status["kind"] == "sequential"

    vm = client.get("/api/viewmodel").json()
    seq = vm["sequence"]
    assert len(seq["frames"]) == 14

    print("\n===== anchored 14-frame CaTeO3 (GUI /api/sequential) =====")
    for row in seq["frames"]:
        print(
            f"  frame {row['frame']} axis={row['axis_value']} rwp={row['rwp']} "
            f"fractions={row['fractions']} changepoint={row['changepoint']}"
        )
    # Windows の cp932 コンソールは en-dash 等を出せず UnicodeEncodeError で落ちる
    # (実走で踏んだ — 実装ではなくテスト側の出力の問題)。ASCII 安全化して出す。
    def _ascii(obj: object) -> str:
        return str(obj).encode("ascii", "replace").decode("ascii")

    print(f"  anchors: {_ascii(seq['anchors'])}")
    print(f"  segments: {_ascii(seq['segments'])}")

    assert 1 <= len(seq["anchors"]) <= 2
    for row in seq["frames"]:
        assert row["rwp"] is not None and row["rwp"] > 0.0
