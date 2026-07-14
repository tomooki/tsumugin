"""TASK-0009 Web UI 最小版 (FastAPI read-only) の TDD Red フェーズテスト。

対象実装 (未実装):
- ``src/tsumugin/webui/app.py`` の ``create_app(result) -> fastapi.FastAPI`` / ``serve(...)``
- ``src/tsumugin/errors.py`` への ``WebUIUnavailableError(TsumuginError)`` 追加

現時点で ``tsumugin.webui.app`` モジュールが存在しないため、モジュール冒頭の
``from tsumugin.webui.app import create_app`` が collection 時に ImportError となり、本ファイルの
全テストがエラー (= 失敗) になる想定 (tests/test_tree_search.py と同一の Red 方針)。

方針:
- ``SearchResult`` は ``HypothesisTreeSearch`` + ``SimulatedBackend`` の小規模データで生成する
  (tests/test_tree_search.py の ``GRID`` / ``_phase`` ヘルパを踏襲)。境界値 (空/未知相フラグ/
  metrics None/unranked ノード) はその基点結果から ``dataclasses.replace`` で決定論的に派生させる。
- テストは ``fastapi.testclient.TestClient`` で ASGI アプリを直接叩き、``serve`` (ブロッキング
  uvicorn) は起動しない。
- web extra 未導入環境では ``pytest.importorskip`` によりモジュール全体を自動 skip する。

テストケース定義 (17 件: 正常系 N1-N7 / 異常系 E1-E5 / 境界値 B1-B5) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses
import json
import sys

import numpy as np
import pytest

# 【環境ガード】: web extra 未導入環境ではモジュール全体を skip する (本環境は導入済みで実行) 🟡
fastapi = pytest.importorskip("fastapi")  # web extra 未導入環境は全 skip
pytest.importorskip("fastapi.testclient")  # TestClient は httpx 依存 (dev group)
from fastapi.testclient import TestClient  # noqa: E402

from tsumugin.backends.simulated import SimulatedBackend  # noqa: E402
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance  # noqa: E402
from tsumugin.search.matcher import UnmatchedPeakReport  # noqa: E402
from tsumugin.search.peaks import Peak  # noqa: E402
from tsumugin.search.tree import HypothesisTreeSearch  # noqa: E402

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定。
from tsumugin.webui.app import create_app  # noqa: E402


# ---------------------------------------------------------------------------
# 共通テストデータ・ヘルパ (tests/test_tree_search.py の慣習を踏襲)
# ---------------------------------------------------------------------------

# 【観測グリッド】: 全候補のピークが収まる 15-60° / step 0.02。範囲を縮めて実行時間を抑える。🔵
GRID = np.arange(15.0, 60.0, 0.02)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンスを作る (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


# 【候補相】: A/B は真の相、C/D は無関係相 (test_tree_search.py と同一定義)。🔵
PHASE_A = _phase(5.0, "A")
PHASE_B = _phase(6.0, "B")
PHASE_C = _phase(4.5, "C")
PHASE_D = _phase(7.0, "D")

# 【派生ノード ID】: 基点結果へ後付けする境界値ノードの ID (既存 hyp-XXXX と衝突しない)。🟡
_NONE_METRICS_ID = "hyp-none-metrics"
_UNRANKED_ID = "hyp-unranked-only"


def _make_result(candidates, *, truth=(PHASE_A, PHASE_B)):
    """SimulatedBackend の合成パターンに対し実探索を回して ``SearchResult`` を得る。🔵"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate(list(truth), GRID)
    return HypothesisTreeSearch(backend).search(GRID, y, list(candidates))


# ---------------------------------------------------------------------------
# フィクスチャ (実探索は module スコープで 1 度だけ、境界値は replace で派生)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def result():
    # 【テストデータ準備】: 真の 2 相 (A+B) + 無関係 2 相 (C/D) の 4 候補で探索し ranked を実体化
    # 【初期条件設定】: 完全説明できるため unknown_phase_flag は False 側に落ちる想定
    return _make_result([PHASE_A, PHASE_B, PHASE_C, PHASE_D])


@pytest.fixture(scope="module")
def client(result):
    # 【環境初期化】: create_app(result) を ASGI アプリとして TestClient に渡す (serve は起動しない)
    return TestClient(create_app(result))


@pytest.fixture(scope="module")
def empty_result():
    # 【境界値】: 候補ゼロ (EDGE-001) → 空 SearchResult (ranked=() / hypotheses={})
    return _make_result([])


@pytest.fixture(scope="module")
def unknown_phase_result(result):
    # 【境界値】: 未マッチ観測ピークを持つ未知相状態を基点結果から派生 (unknown_phase_flag=True)
    unmatched = UnmatchedPeakReport(
        unmatched_observed=(Peak(position=42.0, height=123.0),),
        extra_calculated=(),
        unknown_phase_flag=True,
    )
    return dataclasses.replace(result, unmatched=unmatched)


@pytest.fixture(scope="module")
def result_with_extra_nodes(result):
    # 【境界値】: metrics=None ノードと ranked 外 (hypotheses のみ) ノードを後付けした派生結果
    none_metrics_node = Hypothesis(
        id=_NONE_METRICS_ID,
        phases=(_phase(5.0, "Z"),),
        parent_id=None,
        metrics=None,
        status="candidate",
    )
    # 【unranked ノード】: 既存 ranked 先頭の実 metrics を流用しつつ ID だけ差し替え ranked へは入れない
    unranked_node = dataclasses.replace(result.ranked[0].hypothesis, id=_UNRANKED_ID)
    merged = {
        **dict(result.hypotheses),
        _NONE_METRICS_ID: none_metrics_node,
        _UNRANKED_ID: unranked_node,
    }
    return dataclasses.replace(result, hypotheses=merged)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース
# ---------------------------------------------------------------------------


def test_api_result_returns_to_summary_json(client, result):
    # 【テスト目的】: GET /api/result が to_summary() の JSON を無改変で返すことを確認 🔵
    # 【テスト内容】: TestClient で /api/result を GET し応答を to_summary() と完全比較
    # 【期待される動作】: 200 かつ resp.json() == result.to_summary()
    resp = client.get("/api/result")

    assert resp.status_code == 200  # 【検証項目】: 正常配信 🔵
    assert resp.json() == result.to_summary()  # 【検証項目】: to_summary 無改変配信 🔵


def test_api_result_ranked_row_has_required_keys(client):
    # 【テスト目的】: /api/result の ranked 各行が UI 描画に必要な全キーを持つことを確認 🔵
    # 【テスト内容】: ranked[0] のキー集合・型・rank 1 起番・evidence/phases/lattice 構造を検証
    # 【期待される動作】: 各キーが素の型 (str/int/float/bool/None/list/dict) で存在する
    row = client.get("/api/result").json()["ranked"][0]

    required = {
        "id", "rank", "probability", "close_competitor", "rwp", "gof",
        "evidence", "phases", "parent_id", "in_good_cluster",
    }
    assert required <= set(row)  # 【検証項目】: ranked 行スキーマの網羅 🔵
    assert row["rank"] == 1  # 【検証項目】: rank は 1 起番 🔵
    assert set(row["evidence"]) >= {"backend", "value"}  # 【検証項目】: evidence 構造 🔵
    assert set(row["phases"][0]["lattice"]) >= {"a", "b", "c"}  # 【検証項目】: 格子 a/b/c 🔵
    assert isinstance(row["in_good_cluster"], bool)  # 【検証項目】: 良好解メンバ判定は bool 🔵


def test_root_returns_html(client):
    # 【テスト目的】: GET / が静的 index.html を 200 / text/html で返すことを確認 🟡
    # 【テスト内容】: トップページの status・content-type・body 非空を検証
    # 【期待される動作】: HTMLResponse/FileResponse で index.html を配信する
    resp = client.get("/")

    assert resp.status_code == 200  # 【検証項目】: トップページ配信 🟡
    assert "text/html" in resp.headers["content-type"]  # 【検証項目】: HTML content-type 🟡
    assert resp.text.strip()  # 【検証項目】: body が非空 🟡


def test_root_html_contains_id_render_target_and_api_id_matches(client, result):
    # 【テスト目的】: トップ HTML がランキング描画の土台を持ち、ID が API 経由で到達可能なことを確認 🟡
    # 【テスト内容】: HTML に描画領域/fetch 参照が含まれ、/api/result の ID がフィクスチャと一致
    # 【期待される動作】: SPA なので HTML は表示領域を持ち、ID 一致は API 側で担保する
    body = client.get("/").text.lower()
    ids = [r["id"] for r in client.get("/api/result").json()["ranked"]]

    assert ("fetch" in body) or ("/api/result" in body) or ("ranking" in body)
    # 【検証項目】: HTML がランキング描画用要素または API 参照を含む (SPA 前提) 🟡
    assert ids == [r["id"] for r in result.to_summary()["ranked"]]
    # 【検証項目】: API 経由の ID がフィクスチャの仮説 ID と一致 🟡


def test_hypothesis_detail_returns_full_json(client, result):
    # 【テスト目的】: 既知 id の詳細エンドポイントが相/格子/scale/metrics 全量/系譜を返すことを確認 🟡
    # 【テスト内容】: result.hypotheses から独自シリアライズした詳細 JSON のキー網羅を検証
    # 【期待される動作】: 200 かつ格子は角度/sigma、metrics は evidence まで含む
    known_id = result.ranked[0].hypothesis.id
    resp = client.get(f"/api/hypotheses/{known_id}")

    assert resp.status_code == 200  # 【検証項目】: 既知 id は 200 🟡
    data = resp.json()
    assert {"id", "parent_id", "status", "phases"} <= set(data)  # 【検証項目】: 仮説トップ構造 🟡
    phase = data["phases"][0]
    assert {"phase_ref", "scale", "wt_frac", "occupancies", "lattice"} <= set(phase)
    # 【検証項目】: 相ごとの scale/wt_frac/occupancies/格子まで含む 🟡
    assert {"a", "b", "c", "alpha", "beta", "gamma", "sigma", "sigma_source"} <= set(
        phase["lattice"]
    )
    # 【検証項目】: 格子は a/b/c に加え角度・sigma・σ 由来 (sigma_source) まで含める 🟡
    assert isinstance(phase["lattice"]["sigma_source"], str)
    # 【検証項目】: sigma_source は str で純型化される (Issue #66 / NFR-107) 🔵
    assert {"rwp", "gof", "chi2", "n_obs", "n_params", "evidence"} <= set(data["metrics"])
    # 【検証項目】: metrics 全量 (evidence 含む) 🟡


def test_hypothesis_detail_metrics_noise_scale_defaults_to_null(client, result):
    # 【テスト目的】: Issue #64 / FR-123 (NFR-107 σ の由来明示) — metrics に noise_scale キーが
    #   常に含まれ、EM 未推定 (既定 None) の仮説では JSON null で配信されることを確認。
    known_id = result.ranked[0].hypothesis.id
    data = client.get(f"/api/hypotheses/{known_id}").json()
    assert "noise_scale" in data["metrics"]
    assert data["metrics"]["noise_scale"] is None


def test_hypothesis_detail_is_json_serializable_pure_types(client, result):
    # 【テスト目的】: 詳細 JSON が numpy スカラー/dataclass を素通しせず純型化されていることを確認 🟡
    # 【テスト内容】: json.dumps の成功と rwp/lattice.a が float であることを検証
    # 【期待される動作】: float()/str()/dict(...) で純 Python 型へ明示変換されている
    known_id = result.ranked[0].hypothesis.id
    data = client.get(f"/api/hypotheses/{known_id}").json()

    json.dumps(data)  # 【検証項目】: 純型化済みで json 化が例外なく成功 🟡
    assert isinstance(data["metrics"]["rwp"], float)  # 【検証項目】: rwp が float 🟡
    assert isinstance(data["phases"][0]["lattice"]["a"], float)  # 【検証項目】: 格子 a が float 🟡


def test_api_result_ranked_is_deterministic_rank_order(client, result):
    # 【テスト目的】: /api/result の ranked が rank 昇順で to_summary 順と一致することを確認 🔵
    # 【テスト内容】: rank が 1..N の連番で、app 側の並べ替え混入が無いことを検証
    # 【期待される動作】: app はソートせず to_summary の決定論的順序をそのまま配信する
    rows = client.get("/api/result").json()["ranked"]

    assert [r["rank"] for r in rows] == list(range(1, len(rows) + 1))
    # 【検証項目】: rank が 1 起番の連番 🔵
    assert rows == result.to_summary()["ranked"]  # 【検証項目】: to_summary 順を無改変配信 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (read-only 保証 / エラーハンドリング)
# ---------------------------------------------------------------------------


def test_post_api_result_is_not_allowed(client):
    # 【テスト目的】: read-only 保証 — 変更系ハンドラが存在しないことを確認 🔵 REQ-007
    # 【テスト内容】: POST /api/result が 405/404 になることを検証
    # 【期待される動作】: 書き込み口が構造的に存在しない
    resp = client.post("/api/result", json={"x": 1})

    assert resp.status_code in (404, 405)  # 【検証項目】: 変更系ハンドラ不存在 🔵


def test_put_and_delete_routes_are_absent(client):
    # 【テスト目的】: PUT/DELETE/PATCH の全変更系メソッドが未定義であることを確認 🔵 REQ-007
    # 【テスト内容】: 各パスへの変更系リクエストが一律 405/404 になることを検証
    # 【期待される動作】: どの変更系メソッドでも状態変更が起きない
    assert client.put("/").status_code in (404, 405)  # 【検証項目】: PUT / 不存在 🔵
    assert client.delete("/api/hypotheses/some-id").status_code in (404, 405)
    # 【検証項目】: DELETE 詳細ルート不存在 🔵
    assert client.patch("/api/result").status_code in (404, 405)  # 【検証項目】: PATCH 不存在 🔵


def test_hypothesis_detail_unknown_id_returns_404_json(client):
    # 【テスト目的】: 不明 id への詳細リクエストが 404 JSON で返ることを確認 🟡
    # 【テスト内容】: 存在しない id で status 404 かつ {"detail": "hypothesis not found"} を検証
    # 【期待される動作】: 例外は握られ 404 JSON に整形される (スタックトレース露出なし)
    resp = client.get("/api/hypotheses/nope")

    assert resp.status_code == 404  # 【検証項目】: 不明 id は 404 🟡
    assert resp.json() == {"detail": "hypothesis not found"}  # 【検証項目】: エラー形状固定 🟡


def test_create_app_without_fastapi_raises_web_unavailable(result, monkeypatch):
    # 【テスト目的】: fastapi 未導入時に WebUIUnavailableError (extra web 案内) を送出することを確認 🟡
    # 【テスト内容】: import fastapi を失敗させ create_app 呼び出しで誘導エラーが上がることを検証
    # 【期待される動作】: 遅延 import 契約 — import は成功し呼び出し時点でのみ失敗する
    from tsumugin.errors import TsumuginError, WebUIUnavailableError

    # 【import 失敗注入】: sys.modules に None を差し込み `import fastapi` を ImportError にする 🟡
    monkeypatch.setitem(sys.modules, "fastapi", None)

    with pytest.raises(WebUIUnavailableError) as exc:
        create_app(result)

    assert issubclass(WebUIUnavailableError, TsumuginError)  # 【検証項目】: 例外階層 🟡
    message = str(exc.value)
    assert ("tsumugin[web]" in message) or ("uv sync --extra web" in message)
    # 【検証項目】: extra web の導入手順を案内するメッセージ 🟡


def test_unknown_get_route_returns_404(client):
    # 【テスト目的】: 未定義パスへの GET が 404 になり公開ルートが 3 本に限定されることを確認 🟡
    # 【テスト内容】: 定義外パスへの GET が catch-all に落ちず 404 を返すことを検証
    # 【期待される動作】: StaticFiles マウント等で広すぎる配信面を作っていない
    assert client.get("/api/does-not-exist").status_code == 404  # 【検証項目】: 未定義 API 404 🟡
    assert client.get("/admin").status_code == 404  # 【検証項目】: 未定義パス 404 🟡


# ---------------------------------------------------------------------------
# 3. 境界値テストケース
# ---------------------------------------------------------------------------


def test_api_result_empty_ranking_returns_empty_list(empty_result):
    # 【テスト目的】: 空ランキング (EDGE-001) でも /api/result が破綻せず ranked=[] を返すことを確認 🟡
    # 【テスト内容】: ranked=() の SearchResult でトップレベルキーを維持したまま 200 を返すことを検証
    # 【期待される動作】: 空でも to_summary スキーマ全キーが揃う
    client = TestClient(create_app(empty_result))
    resp = client.get("/api/result")

    assert resp.status_code == 200  # 【検証項目】: 空でも正常配信 🟡
    data = resp.json()
    assert data["ranked"] == []  # 【検証項目】: 空ランキングは空リスト 🟡
    assert "unknown_phase_flag" in data  # 【検証項目】: フラグキーが常在 🟡
    assert data["n_hypotheses"] == 0  # 【検証項目】: 仮説数 0 🟡


def test_api_result_includes_unknown_phase_flag_true(unknown_phase_result):
    # 【テスト目的】: 未知相状態で unknown_phase_flag=True がトップレベルに現れることを確認 🟡
    # 【テスト内容】: 未マッチ観測ピークを持つ結果で応答フラグが純 bool True であることを検証
    # 【期待される動作】: フラグ True/False いずれでもトップレベルに常在する
    client = TestClient(create_app(unknown_phase_result))
    data = client.get("/api/result").json()

    assert data["unknown_phase_flag"] is True  # 【検証項目】: 未知相フラグの応答内包 🟡


def test_hypothesis_detail_with_none_metrics(result_with_extra_nodes):
    # 【テスト目的】: metrics=None ノードの詳細が 500 でなく metrics=null で 200 を返すことを確認 🟡
    # 【テスト内容】: None 分岐で metrics.rwp へアクセスせず防御的に処理されることを検証
    # 【期待される動作】: AttributeError を起こさず metrics のみ null で返る
    client = TestClient(create_app(result_with_extra_nodes))
    resp = client.get(f"/api/hypotheses/{_NONE_METRICS_ID}")

    assert resp.status_code == 200  # 【検証項目】: metrics None でも 200 🟡
    assert resp.json()["metrics"] is None  # 【検証項目】: metrics は null で返る 🟡


def test_hypothesis_detail_lookup_from_hypotheses_not_ranked(result_with_extra_nodes):
    # 【テスト目的】: ルックアップ元が ranked ではなく hypotheses 全体であることを確認 🔵
    # 【テスト内容】: ranked に含まれない (hypotheses のみの) id でも詳細が 200 で引けることを検証
    # 【期待される動作】: ranked ⊆ hypotheses。ranked 外 id でも 404 にならない
    ranked_ids = {rk.hypothesis.id for rk in result_with_extra_nodes.ranked}
    assert _UNRANKED_ID not in ranked_ids  # 【前提確認】: 対象は ranked 外ノード 🔵

    client = TestClient(create_app(result_with_extra_nodes))
    resp = client.get(f"/api/hypotheses/{_UNRANKED_ID}")

    assert resp.status_code == 200  # 【検証項目】: hypotheses 全体から引ける 🔵


def test_module_skipped_without_web_extra():
    # 【テスト目的】: web extra 未導入環境ではモジュールが skip される移植性ガードの検証 🟡
    # 【テスト内容】: 導入環境では importorskip が通過し全テストが実行されることを確認
    # 【期待される動作】: 未導入環境では collection エラーにせず skip、導入環境では実行する
    assert fastapi is not None  # 【検証項目】: importorskip 通過 (fastapi 導入済み) 🟡
    assert TestClient is not None  # 【検証項目】: TestClient (httpx) 利用可能 🟡


# ---------------------------------------------------------------------------
# PR #1 レビュー指摘対応 (非有限メトリクスの配信 / XSS シンク不在)
# ---------------------------------------------------------------------------

from tsumugin.backends.base import RefinementResult  # noqa: E402
from tsumugin.search.tree import SearchConfig  # noqa: E402
from tsumugin.webui.app import _INDEX_HTML  # noqa: E402


class _AllInfBackend:
    """全ノードの精密化が失敗 (chi2=rwp=inf) する決定論バックエンド (EDGE-004 経路)。

    chi2=inf は仕様上の正常経路のため、配信層 (to_summary / Web API) が inf を
    JSON へ漏らさないことを検証する専用ダブル。simulate/peak_positions は
    候補ピーク生成経路を成立させるため SimulatedBackend へ委譲する。
    """

    name = "allinf"

    def __init__(self) -> None:
        self._sim = SimulatedBackend(peak_fwhm=0.2)

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model, *, max_cycles: int = 20) -> RefinementResult:
        return RefinementResult(
            phases=model.phases,
            chi2=float("inf"),
            rwp=float("inf"),
            n_obs=int(np.asarray(model.intensity).size),
            n_params=len(model.free_params),
            converged=False,
            n_cycles=1,
            free_params=frozenset(model.free_params),
        )


@pytest.fixture(scope="module")
def inf_result():
    # 全ノード chi2=inf の探索結果 (フル精密化は無効化して全 inf のまま配信層へ渡す)
    backend = _AllInfBackend()
    y = backend.simulate([PHASE_A], GRID)
    config = SearchConfig(final_full_refine=False)
    return HypothesisTreeSearch(backend, config=config).search(GRID, y, [PHASE_A, PHASE_C])


@pytest.fixture(scope="module")
def inf_client(inf_result):
    return TestClient(create_app(inf_result))


def test_summary_with_infinite_metrics_is_strict_json(inf_result):
    # 【テスト目的】: chi2=inf (正常経路) が to_summary の JSON を汚染しないことの契約検証
    # 【期待される動作】: allow_nan=False の厳格 JSON 化が成功し、非有限値は None に落ちる
    summary = inf_result.to_summary()
    text = json.dumps(summary, allow_nan=False)  # inf/nan が残っていれば ValueError
    assert text
    assert len(summary["ranked"]) > 0
    for row in summary["ranked"]:
        assert row["rwp"] is None  # 【検証項目】: inf rwp は null 表現 🔵
        assert row["gof"] is None
        assert row["evidence"]["value"] is None  # 【検証項目】: センチネルも露出しない 🔵


def test_api_result_with_infinite_metrics_returns_null(inf_client):
    # 【テスト目的】: /api/result が FastAPI の暗黙変換に依存せず契約として null を返す
    resp = inf_client.get("/api/result")
    assert resp.status_code == 200
    ranked = resp.json()["ranked"]
    assert len(ranked) > 0
    assert ranked[0]["rwp"] is None
    assert ranked[0]["evidence"]["value"] is None


def test_detail_and_summary_evidence_representation_is_consistent(inf_client, inf_result):
    # 【テスト目的】: 失敗ノードの evidence 表現が 2 エンドポイントで一致する (レビュー LOW 対応)
    row = inf_result.to_summary()["ranked"][0]
    detail = inf_client.get(f"/api/hypotheses/{row['id']}")
    assert detail.status_code == 200
    metrics = detail.json()["metrics"]
    assert metrics["rwp"] is None
    assert metrics["chi2"] is None
    assert metrics["evidence"].get("bic") is None
    assert row["evidence"]["value"] is None  # 両者とも null で不一致がない


def test_index_html_has_no_innerhtml_sink():
    # 【テスト目的】: API 由来の任意文字列 (phase_ref/id) を innerHTML に注入する
    #   DOM XSS シンクが存在しないことの構造的検証 (textContent/DOM API のみ許可)
    html = _INDEX_HTML.read_text(encoding="utf-8")
    assert "innerHTML" not in html
