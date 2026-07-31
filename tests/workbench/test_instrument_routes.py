"""GUI workbench の装置パラメータ導線 (FR-502) のテスト。

**なぜ GUI にも要るか**: workbench は `kind="instrument"` のアップロードしか持たず、
**装置ファイルを既に持っている**ことが前提だった。しかも `add_histogram` はデータファイルを
読んで検証する (`convert_histogram_for_runner`) のに**装置ファイルは一度も開かない**という
非対称があり、存在しないパスや別測定のファイルがそのまま spec に入っていた。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from tsumugin.instprm import build_instprm_text  # noqa: E402
from tsumugin.workbench.app import create_workbench_app  # noqa: E402
from tsumugin.workbench.session import WorkbenchSession  # noqa: E402


@pytest.fixture()
def client(tmp_path) -> TestClient:
    c = TestClient(create_workbench_app(WorkbenchSession.create_demo()))
    c.post("/api/project", json={"name": "proj", "directory": str(tmp_path / "ws")})
    return c


def _instprm(tmp_path, name: str = "x.instprm", **kwargs) -> str:
    kwargs.setdefault("radiation", "xray_lab")
    kwargs.setdefault("wavelength", 1.5405)
    p = tmp_path / name
    p.write_text(build_instprm_text(**kwargs), encoding="utf-8")
    return str(p)


# =====================================================================
# 作る / 検査する
# =====================================================================


def test_create_instrument_writes_a_file(client: TestClient, tmp_path):
    out = tmp_path / "made.instprm"
    resp = client.post(
        "/api/instrument/create",
        json={"out_path": str(out), "radiation": "xray_synchrotron", "wavelength": 0.79958},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["path"] == str(out)
    assert body["type"] == "PXC"
    assert out.exists()


def test_create_instrument_reports_errors_as_dict_not_500(client: TestClient, tmp_path):
    """既存の規約どおり error dict → 4xx (500 やスタックトレースにしない)。"""
    resp = client.post(
        "/api/instrument/create", json={"out_path": str(tmp_path / "x.instprm")}
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error_type"] == "ValueError"
    assert "radiation" in body["error"]


def test_inspect_instrument_returns_findings(client: TestClient, tmp_path):
    path = _instprm(tmp_path, radiation="neutron_cw", wavelength=1.909)
    resp = client.post(
        "/api/instrument/inspect", json={"path": path, "radiation": "xray_lab"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "radiation_type_mismatch" in {f["code"] for f in body["findings"]}


def test_instrument_presets_route_exists(client: TestClient):
    resp = client.get("/api/instrument/presets")
    assert resp.status_code == 200
    body = resp.json()
    # GSAS-II 未導入環境では error dict へ縮退する (500 にしない)
    assert "presets" in body or "error" in body


# =====================================================================
# add_histogram が装置ファイルを見るようになったこと
# =====================================================================


def test_add_histogram_rejects_a_missing_instrument_file(client: TestClient, tmp_path):
    """データ側と同じ厳しさで装置ファイルも見る (従来は一度も開いていなかった)。"""
    data = tmp_path / "d.xye"
    data.write_text("10.0 100.0 10.0\n10.1 110.0 10.5\n", encoding="utf-8")
    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": str(data),
            "instrument_path": str(tmp_path / "nope.instprm"),
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XYE",
        },
    )
    body = resp.json()
    assert "error" in body
    assert "instrument" in body["error"].lower()


def test_add_histogram_rejects_a_mismatched_instrument_file(client: TestClient, tmp_path):
    """宣言と違う放射源の装置ファイルは `error` 指摘なので追加を拒む。"""
    data = tmp_path / "d.xye"
    data.write_text("10.0 100.0 10.0\n10.1 110.0 10.5\n", encoding="utf-8")
    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": str(data),
            "instrument_path": _instprm(tmp_path, radiation="neutron_cw", wavelength=1.909),
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XYE",
        },
    )
    body = resp.json()
    assert "error" in body
    assert "radiation_type_mismatch" in body["error"]


def test_add_histogram_surfaces_non_blocking_findings(client: TestClient, tmp_path):
    """`question`/`info` は追加を拒まないが**黙って捨てない** (Kα2 の確認は人間の仕事)。"""
    data = tmp_path / "d.xye"
    data.write_text("10.0 100.0 10.0\n10.1 110.0 10.5\n", encoding="utf-8")
    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": str(data),
            "instrument_path": _instprm(tmp_path, wavelength=1.5405, wavelength_ka2=1.5443),
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XYE",
        },
    )
    body = resp.json()
    assert "error" not in body
    codes = {f["code"] for f in body["instrument_findings"]}
    assert "kalpha2_consistency_question" in codes


def test_add_histogram_still_accepts_a_clean_instrument_file(client: TestClient, tmp_path):
    """非回帰: 正しい組み合わせは従来どおり通り、findings は空。"""
    data = tmp_path / "d.xye"
    data.write_text("10.0 100.0 10.0\n10.1 110.0 10.5\n", encoding="utf-8")
    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": str(data),
            "instrument_path": _instprm(tmp_path, radiation="xray_synchrotron", wavelength=0.8),
            "radiation": "xray_synchrotron",
            "geometry": "debye_scherrer",
            "data_format": "XYE",
        },
    )
    body = resp.json()
    assert "error" not in body
    assert body["instrument_findings"] == []


def test_add_histogram_accepts_a_legacy_prm(client: TestClient, tmp_path):
    """旧 `.PRM` を「装置ファイルではない」と断じないこと (README の例もこの形式)。"""
    from pathlib import Path

    prm = Path("docs/benchmark/testdata/INST_XRY.PRM")
    if not prm.is_file():
        pytest.skip("チュートリアルデータ未取得")
    data = tmp_path / "d.xye"
    data.write_text("10.0 100.0 10.0\n10.1 110.0 10.5\n", encoding="utf-8")
    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": str(data),
            "instrument_path": str(prm.resolve()),
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XYE",
        },
    )
    assert "error" not in resp.json()


# =====================================================================
# 構造ガード (既存の不変条件を壊していないこと)
# =====================================================================


def test_new_routes_are_post_or_get_only(client: TestClient):
    """P2 構造ガード: DELETE/PUT を増やしていないこと。"""
    for route in client.app.routes:
        methods = getattr(route, "methods", set()) or set()
        assert not ({"DELETE", "PUT"} & set(methods)), getattr(route, "path", route)


def test_status_reports_the_real_mcp_tool_count(client: TestClient):
    """「MCP tools N · layer ② reachable」は事実の主張なので固定値にしない。

    実際 36 で固定されたまま 38 → 43 とドリフトしていた。② の到達可能性を名乗る表示が
    実際と食い違うのは、この一連の作業が塞ごうとしている穴そのもの。
    """
    from tsumugin.mcp.tools import MCP_TOOLS

    assert client.get("/api/state").json()["status"]["mcp_tools"] == len(MCP_TOOLS)


def test_create_instrument_writes_inside_the_project_not_the_server_cwd(
    client: TestClient, tmp_path
):
    """相対 `out_path` はプロジェクトの中に解決すること。

    実 UI で発見: フロントは `data/<name>.instprm` という**相対**パスを送るので、
    サーバのカレントディレクトリ (リポジトリ直下) に書かれていた。プロジェクトは
    「ディレクトリ + project.json + data/」で**自己完結**する約束 (api-contract.md) なので、
    外に書くとプロジェクトを移動した時点で装置ファイルが失われる。
    """
    resp = client.post(
        "/api/instrument/create",
        json={"out_path": "data/made.instprm", "radiation": "xray_lab", "wavelength": 1.5405},
    )
    assert resp.status_code == 200
    written = Path(resp.json()["path"])
    assert written.is_file()
    spec_dir = tmp_path / "ws" / "proj"
    assert written.resolve().is_relative_to(spec_dir.resolve()), written


def test_created_instrument_path_is_usable_by_add_histogram(client: TestClient, tmp_path):
    """作った path をそのまま `instrument_path` に渡せること (§4.5 の往復を GUI でも)。"""
    created = client.post(
        "/api/instrument/create",
        json={"out_path": "data/made.instprm", "radiation": "xray_lab", "wavelength": 1.5405},
    ).json()
    data = tmp_path / "d.xye"
    data.write_text("10.0 100.0 10.0\n10.1 110.0 10.5\n", encoding="utf-8")
    resp = client.post(
        "/api/project/histograms",
        json={
            "data_path": str(data),
            "instrument_path": created["path"],
            "radiation": "xray_lab",
            "geometry": "bragg_brentano",
            "data_format": "XYE",
        },
    )
    assert "error" not in resp.json()


def test_create_instrument_without_a_project_is_refused(tmp_path):
    """プロジェクト未読込では相対パスの行き先が決まらない — 黙って CWD に書かない。"""
    c = TestClient(create_workbench_app(WorkbenchSession.create_demo()))
    resp = c.post(
        "/api/instrument/create",
        json={"out_path": "data/made.instprm", "radiation": "xray_lab", "wavelength": 1.5405},
    )
    body = resp.json()
    assert "error" in body
    assert "project" in body["error"].lower()


# =====================================================================
# /code-review 指摘の回帰テスト
# =====================================================================


def test_unknown_json_keys_do_not_500(client: TestClient, tmp_path):
    """未知キー 1 つで 500 にしない。他の project 系ルートと同じ `body.get` 流儀にする。"""
    resp = client.post(
        "/api/instrument/create",
        json={
            "out_path": str(tmp_path / "x.instprm"),
            "radiation": "xray_lab",
            "wavelength": 1.5405,
            "bogus": 1,
        },
    )
    assert resp.status_code == 200, resp.json()
    resp2 = client.post(
        "/api/instrument/inspect",
        json={"path": str(tmp_path / "x.instprm"), "radiation": "xray_lab", "bogus": 1},
    )
    assert resp2.status_code == 200, resp2.json()


def test_inspect_resolves_relative_paths_like_create_does(client: TestClient):
    """create が書いた相対パスを inspect にそのまま渡せること。

    spec は `instrument_path` を spec_dir 相対で保存するので、解決しないと
    **存在するファイルを file_not_found と答える**。
    """
    created = client.post(
        "/api/instrument/create",
        json={"out_path": "data/x.instprm", "radiation": "xray_lab", "wavelength": 1.5405},
    ).json()
    assert "error" not in created
    rel = client.post(
        "/api/instrument/inspect", json={"path": "data/x.instprm", "radiation": "xray_lab"}
    ).json()
    assert "file_not_found" not in {f["code"] for f in rel["findings"]}
    assert rel["ok"] is True


def test_inspect_absolute_paths_still_work(client: TestClient, tmp_path):
    """非回帰: 絶対パスは従来どおり (プロジェクト外のファイルも検査できる)。"""
    p = _instprm(tmp_path, radiation="neutron_cw", wavelength=1.909)
    r = client.post("/api/instrument/inspect", json={"path": p, "radiation": "xray_lab"}).json()
    assert "radiation_type_mismatch" in {f["code"] for f in r["findings"]}


def test_inspect_without_a_project_still_works_on_absolute_paths(tmp_path):
    c = TestClient(create_workbench_app(WorkbenchSession.create_demo()))
    p = _instprm(tmp_path, radiation="xray_lab", wavelength=1.5405)
    r = c.post("/api/instrument/inspect", json={"path": p}).json()
    assert r["ok"] is True
