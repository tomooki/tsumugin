# TASK-0009 Web UI 最小版 (FastAPI read-only) — TDD テストケース定義書

- **機能名**: Web UI 最小版 (read-only 結果閲覧) / `web-ui-readonly`
- **タスクID**: TASK-0009
- **要件名**: m1-hypothesis-search
- **対象実装**: `src/tsumugin/webui/app.py` (`create_app` / `serve`), `src/tsumugin/webui/static/index.html`, `src/tsumugin/errors.py` (`WebUIUnavailableError` 追加)
- **テストファイル**: `tests/test_webui.py` (新規)
- **作成日**: 2026-07-03
- **総合信頼性**: 🟡 (REQ-007 / 設計 D6 由来。read-only 制約・API スキーマ・関数契約は REQ-007 / api-endpoints.md / interfaces.py に遡及)

**【信頼性レベル凡例】**: 🔵 元資料 (要件/設計/既存実装) を参照しほぼ推測なし / 🟡 元資料からの妥当な推測 / 🔴 元資料にない推測

**【受け入れ基準対応】**: TC-007-01〜04 (acceptance-criteria.md L70-75)
- TC-007-01: `GET /api/result` が `to_summary()` の JSON (id/確率/rwp/evidence, ranked/unknown_phase_flag) を返す
- TC-007-02: `GET /` が HTML を返し仮説 ID/ランクを含む
- TC-007-03: 変更系ルート (POST/PUT/DELETE) が存在しない (read-only 保証)
- TC-007-04: 未知相フラグが応答に含まれる + 不明 id で 404 JSON

---

## 0. テスト戦略・共通フィクスチャ

- **read-only 保証は「変更系ハンドラを書かないこと自体」が担保**。テストは変更系リクエストが 405/404 になることで構造的不存在を検証する (TC-007-03 / REQ-007)。🔵
- **フィクスチャ**: 探索を実走させると重いため、`SearchResult` を**直接組み立てる軽量フィクスチャ**を用いる (`tests/test_tree_search.py` の `_phase()` / `GRID` ヘルパ流用)。最小構成: `ranked=(RankedHypothesis...)`, `hypotheses={id: Hypothesis}`, `good_cluster_ids`, `alternatives={}`, `unmatched=UnmatchedPeakReport(...)`, `final_reports={}`, `ledger=Ledger()`, `snapshots=SnapshotStore()`, `warnings=()`。🟡
- **web extra 未導入環境**: テストモジュール冒頭で `fastapi = pytest.importorskip("fastapi")` / `pytest.importorskip("fastapi.testclient")` により自動 skip (新規マーカー登録不要)。本環境は fastapi 導入済みのため実際には実行される。🟡

```python
# tests/test_webui.py 冒頭
import pytest

fastapi = pytest.importorskip("fastapi")            # web extra 未導入環境は全 skip 🟡
pytest.importorskip("fastapi.testclient")           # TestClient は httpx 依存 (dev group) 🟡
from fastapi.testclient import TestClient
from tsumugin.webui.app import create_app

@pytest.fixture
def result():
    # 【テストデータ準備】: ranked 2 件 + unranked 1 件を持つ軽量 SearchResult を直接構築
    # 【初期条件設定】: metrics 付き仮説・格子 a/b/c・evidence を最小構成で用意
    ...  # 上記共通フィクスチャに従い SearchResult を返す

@pytest.fixture
def client(result):
    # 【環境初期化】: create_app(result) を ASGI アプリとして TestClient に渡す (serve は起動しない)
    return TestClient(create_app(result))
```

---

## 1. 正常系テストケース（基本的な動作）

### TC-007-01-N1: `GET /api/result` が `to_summary()` の JSON を完全一致で返す

- **テスト名**: api_result_returns_to_summary_json
  - **何をテストするか**: `GET /api/result` の応答ボディが `result.to_summary()` と完全一致し、200 で返ること
  - **期待される動作**: app は加工せず `to_summary()` の純 dict をそのまま JSON 配信する (下流の薄い配信層)
- **入力値**: 軽量 `SearchResult` フィクスチャ (ranked 2 件) を `create_app` に渡した TestClient で `client.get("/api/result")`
  - **入力データの意味**: 実探索を回さず to_summary スキーマを満たす最小データ。決定論・スキーマ準拠を担保する
- **期待される結果**: `resp.status_code == 200` かつ `resp.json() == result.to_summary()`
  - **期待結果の理由**: api-endpoints.md L30-52「`/api/result` = `to_summary()` そのまま」。to_summary は素の型へ変換済みで JSON 化保証 (tree.py L163-173)
- **テストの目的**: 配信レイヤーが to_summary を無改変で返すことの検証 (TC-007-01)
  - **確認ポイント**: `ranked` に `id` / `probability` / `rwp` / `evidence` キーが含まれること、numpy スカラー混入なしで一致すること
- 🔵 (api-endpoints.md L30-52 / tree.py `to_summary` L113-173 / acceptance-criteria TC-007-01 に遡及)

### TC-007-01-N2: `/api/result` の ranked 各行が必須キーを持つ

- **テスト名**: api_result_ranked_row_has_required_keys
  - **何をテストするか**: `ranked[0]` が `{id, rank, probability, close_competitor, rwp, gof, evidence:{backend,value}, phases:[{phase_ref, wt_frac, lattice:{a,b,c}}], parent_id, in_good_cluster}` を持つこと
  - **期待される動作**: 各キーが素の型 (str/int/float/bool/None/list/dict) で存在する
- **入力値**: `client.get("/api/result").json()["ranked"][0]`
  - **入力データの意味**: ランキング 1 行のスキーマ完全性検証。UI 描画が依存するキー集合を固定する
- **期待される結果**: `rank == 1` (1 起番)、`evidence` が `backend`/`value` を持つ dict、`phases[0].lattice` が `a`/`b`/`c` を持つ
  - **期待結果の理由**: note.md §3.1 / tree.py L144-159 の行スキーマ。rank は `i+1` の 1 起番
- **テストの目的**: UI が参照する ranked 行スキーマの網羅確認 (TC-007-01)
  - **確認ポイント**: `rank` が 1 から連番、`in_good_cluster` が bool
- 🔵 (tree.py L144-160 / note.md §3.1)

### TC-007-02-N3: `GET /` が HTML を 200 で返す

- **テスト名**: root_returns_html
  - **何をテストするか**: `GET /` が静的 `index.html` を 200 / `content-type: text/html` で返すこと
  - **期待される動作**: `webui/static/index.html` を `HTMLResponse`/`FileResponse` で配信する
- **入力値**: `client.get("/")`
  - **入力データの意味**: トップページ配信の基本動作。SPA のためデータは fetch 後描画
- **期待される結果**: `resp.status_code == 200` かつ `resp.headers["content-type"]` が `text/html` を含む
  - **期待結果の理由**: dataflow.md L98「GET / → index.html (静的)」/ requirements §2.2
- **テストの目的**: トップページの HTML 応答検証 (TC-007-02)
  - **確認ポイント**: content-type が HTML、body が非空
- 🟡 (dataflow.md L90-109 / requirements §2.2)

### TC-007-02-N4: トップページに仮説 ID/ランク表示領域が存在する（SPA 分割検証）

- **テスト名**: root_html_contains_id_render_target_and_api_id_matches
  - **何をテストするか**: `GET /` の HTML にランキング/ID を描画する DOM 要素 (例: `id="ranking"` 等のテーブル領域) があり、かつ `/api/result` の ID が想定と一致すること
  - **期待される動作**: index.html はビルド無しで `fetch("/api/result")` 結果を描画する土台を持つ
- **入力値**: `body = client.get("/").text` と `ids = [r["id"] for r in client.get("/api/result").json()["ranked"]]`
  - **入力データの意味**: SPA では ID が fetch 後に注入されるため、HTML 側は「表示領域の存在」、ID 一致は API 経由で分割検証する
- **期待される結果**: HTML にランキング描画用要素が含まれる **または** `fetch`/`/api/result` 参照が含まれる ; `ids` がフィクスチャの仮説 ID と一致
  - **期待結果の理由**: note.md TC-007-02 注記「SPA なら HTML 200 + テンプレートに ID 表示領域、または API 経由 ID 一致で担保」
- **テストの目的**: 仮説 ID がユーザーに到達可能であることの検証 (TC-007-02)
  - **確認ポイント**: HTML 直書きに ID を要求しすぎない (SPA 前提)。ID 一致は API 側で担保
- 🟡 (note.md §4.5 TC-007-02 / requirements §5)

### TC-007-04-N5: `GET /api/hypotheses/{known_id}` が詳細 JSON を返す

- **テスト名**: hypothesis_detail_returns_full_json
  - **何をテストするか**: 既知 id の詳細エンドポイントが相・格子・scale・metrics 全量・系譜を含む JSON を 200 で返すこと
  - **期待される動作**: `result.hypotheses[id]` から独自シリアライズ (to_summary の外)
- **入力値**: `known_id = ranked 行の id`; `client.get(f"/api/hypotheses/{known_id}")`
  - **入力データの意味**: ranked ⊆ hypotheses なので ranked 行 id は必ず引ける。詳細ビューが依存するデータ
- **期待される結果**: 200 / JSON に `id` / `parent_id` / `status` / `phases[].{phase_ref, scale, wt_frac, occupancies, lattice}` / `lattice.{a,b,c,alpha,beta,gamma,sigma}` / `metrics.{rwp,gof,chi2,n_obs,n_params,evidence}` を含む
  - **期待結果の理由**: api-endpoints.md L54-58「相ごとの格子・scale・metrics 全量・系譜」/ note.md §3.2。to_summary は a/b/c のみだが詳細は角度・sigma まで含めてよい
- **テストの目的**: 詳細エンドポイントのシリアライズ網羅検証 (TC-007-04)
  - **確認ポイント**: metrics 全量 (evidence 含む) と格子角度・sigma まで含まれること
- 🟡 (api-endpoints.md L54-58 / note.md §3.2 / model/hypothesis.py / model/phase.py)

### TC-007-04-N6: 詳細エンドポイント応答が純型で JSON 化可能

- **テスト名**: hypothesis_detail_is_json_serializable_pure_types
  - **何をテストするか**: 詳細 JSON に numpy スカラー・dataclass が素通しされておらず `json.dumps` が成功すること
  - **期待される動作**: `float()`/`str()`/`dict(...)` で純 Python 型へ明示変換されている (to_summary と同流儀)
- **入力値**: `data = client.get(f"/api/hypotheses/{known_id}").json()`; `json.dumps(data)`
  - **入力データの意味**: 数値は numpy 由来になりうるため純型化を検証。UI/クライアント互換性の担保
- **期待される結果**: `json.dumps(data)` が例外なく成功。`data["metrics"]["rwp"]` 等が `float`、`lattice.a` が `float`
  - **期待結果の理由**: note.md §6「numpy スカラーや dataclass を素通しすると json 化に失敗しうる」
- **テストの目的**: 詳細シリアライズの型安全性検証 (TC-007-04 補強)
  - **確認ポイント**: TestClient の `.json()` 通過だけでなく `json.dumps` の明示検証
- 🟡 (note.md §6 / requirements §2.4)

### TC-007-01-N7: ranked 応答順序が決定論的 (rank 昇順、app 側で並べ替えない)

- **テスト名**: api_result_ranked_is_deterministic_rank_order
  - **何をテストするか**: `/api/result` の `ranked` が `rank` 昇順 (1,2,...) で、`to_summary()` の順序と一致すること
  - **期待される動作**: app はソートを行わず to_summary の決定論的順序をそのまま配信する
- **入力値**: `rows = client.get("/api/result").json()["ranked"]`
  - **入力データの意味**: 決定論保証 (REQ-403)。同一入力で同一順序であることを固定
- **期待される結果**: `[r["rank"] for r in rows] == list(range(1, len(rows)+1))` かつ `rows == result.to_summary()["ranked"]`
  - **期待結果の理由**: note.md §2「to_summary は rank 昇順を保証済み。app 側で並べ替えない」/ REQ-403
- **テストの目的**: 配信順序の決定論検証 (TC-007-01 / REQ-403)
  - **確認ポイント**: app が独自ソートを混入していないこと
- 🔵 (tree.py L147 / note.md 決定論 / requirements §3 REQ-403)

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-007-03-E1: `POST /api/result` が変更系未定義で 405/404

- **テスト名**: post_api_result_is_not_allowed
  - **エラーケースの概要**: read-only アプリに対する書き込み試行。POST ハンドラは一切定義しない
  - **エラー処理の重要性**: read-only 保証 (REQ-007 / P2 非破壊) の構造的担保。書き込み口を作らないこと自体が完了条件
- **入力値**: `client.post("/api/result")` (および任意ボディ)
  - **不正な理由**: `/api/result` は GET 専用。POST ハンドラが存在しないため FastAPI が拒否する
  - **実際の発生シナリオ**: 誤操作・悪意ある書き込み・API 誤用時にデータが変更されないことの保証
- **期待される結果**: `resp.status_code in (404, 405)` (GET のみ定義パスは 405、完全未定義は 404)
  - **エラーメッセージの内容**: FastAPI 標準の Method Not Allowed / Not Found
  - **システムの安全性**: 状態は不変。`SearchResult` は frozen で書き込み不能
- **テストの目的**: 変更系ハンドラ不存在の検証 (TC-007-03 / REQ-007)
  - **品質保証の観点**: 非破壊性 (P2) がルーティング構造で担保されていること
- 🔵 (requirements §3 REQ-007 / note.md §2,§6 / acceptance-criteria TC-007-03)

### TC-007-03-E2: `PUT /` と `DELETE /api/hypotheses/{id}` が 405/404

- **テスト名**: put_and_delete_routes_are_absent
  - **エラーケースの概要**: PUT/DELETE を含む全変更系メソッドが未定義であること
  - **エラー処理の重要性**: POST 以外の変更系メソッドも一切受け付けないことを網羅的に確認
- **入力値**: `client.put("/")`, `client.delete("/api/hypotheses/some-id")`, `client.patch("/api/result")`
  - **不正な理由**: いずれのパスにも変更系ハンドラを定義しない設計
  - **実際の発生シナリオ**: ranked 行 id へ DELETE/PUT しても書き込めないこと
- **期待される結果**: すべて `status_code in (404, 405)`
  - **エラーメッセージの内容**: 標準の 405/404
  - **システムの安全性**: どの変更系メソッドでも状態変更が起きない
- **テストの目的**: 変更系メソッド全種の不存在検証 (TC-007-03 / REQ-007)
  - **品質保証の観点**: read-only 保証の網羅性 (PUT/DELETE/PATCH まで)
- 🔵 (requirements §4「POST/PUT/DELETE → 405/404」/ note.md §5 TC-007-03)

### TC-007-04-E3: 不明 id で `404 {"detail": "hypothesis not found"}`

- **テスト名**: hypothesis_detail_unknown_id_returns_404_json
  - **エラーケースの概要**: 存在しない hypothesis id への詳細リクエスト
  - **エラー処理の重要性**: 不正 id を明確な JSON エラーで返し、クライアントが判別可能にする
- **入力値**: `client.get("/api/hypotheses/nope")` (hypotheses に存在しない id)
  - **不正な理由**: `result.hypotheses` にキーが無い。ルックアップ失敗
  - **実際の発生シナリオ**: 古いリンク・打ち間違い・存在しないノード参照
- **期待される結果**: `resp.status_code == 404` かつ `resp.json() == {"detail": "hypothesis not found"}`
  - **エラーメッセージの内容**: api-endpoints.md L60 の定義文字列 (`raise HTTPException(status_code=404, detail="hypothesis not found")`)
  - **システムの安全性**: 例外は握られ 404 JSON に整形される (スタックトレース露出なし)
- **テストの目的**: 不明 id のエラーハンドリング検証 (TC-007-04)
  - **品質保証の観点**: エラー形状が仕様どおり固定されていること
- 🟡 (api-endpoints.md L54-60 / dataflow.md L102,L122 / note.md §3.2)

### E4: fastapi 未導入時に `WebUIUnavailableError` (extra web 案内) を送出

- **テスト名**: create_app_without_fastapi_raises_web_unavailable
  - **エラーケースの概要**: web extra 未導入環境で `create_app`/`serve` を呼び出した場合の誘導エラー
  - **エラー処理の重要性**: コア依存 (numpy のみ) を汚染せず、未導入ユーザーに導入手順を明確に案内する
- **入力値**: fastapi の import を失敗させる状況 (`monkeypatch` で `import fastapi` を `ImportError` にする / または未導入環境) で `create_app(result)` を呼ぶ
  - **不正な理由**: fastapi/uvicorn が optional extra `web`。未導入では app 生成不能
  - **実際の発生シナリオ**: `uv sync` のみ (web extra 未指定) でインストールしたユーザーが webui を使おうとする
- **期待される結果**: `WebUIUnavailableError` (TsumuginError 派生) が送出され、メッセージに `pip install 'tsumugin[web]'` または `uv sync --extra web` を含む
  - **エラーメッセージの内容**: GSASUnavailableError と対称の明確な導入誘導
  - **システムの安全性**: `import tsumugin.webui.app` 自体は成功し (遅延 import)、呼び出し時点でのみ失敗する
- **テストの目的**: 未導入時の明確な誘導と遅延 import 契約の検証
  - **品質保証の観点**: コア import が web extra に依存しない構造 (CLAUDE.md「コア依存 numpy のみ」)
- 🟡 (note.md §3.3,§6 / requirements §3「WebUIUnavailableError 新設」/ errors.py 例外階層)
- **補足**: 本ケースは fastapi 導入済み環境では monkeypatch で import 失敗を模擬する。モジュール冒頭の `importorskip` は「fastapi あり」を前提とするため、本テストのみ import 失敗注入で検証する (skip 対象外)

### E5: 未定義パスへの GET が 404

- **テスト名**: unknown_get_route_returns_404
  - **エラーケースの概要**: 定義されていない任意パスへの GET リクエスト
  - **エラー処理の重要性**: 想定外パスが 404 で安全に処理され、意図しないハンドラに落ちないこと
- **入力値**: `client.get("/api/does-not-exist")`, `client.get("/admin")`
  - **不正な理由**: 公開ルートは GET `/` / `/api/result` / `/api/hypotheses/{id}` の 3 本のみ
  - **実際の発生シナリオ**: 誤ったパス・スキャン・タイポ
- **期待される結果**: `status_code == 404`
  - **エラーメッセージの内容**: 標準の Not Found
  - **システムの安全性**: catch-all/StaticFiles マウントで書き込み口や広すぎる配信面を作っていないこと
- **テストの目的**: 公開ルートが 3 本に限定されていることの検証 (read-only 補強)
  - **品質保証の観点**: ルーティング面の最小化 (note.md §6「汎用ルータで書き込み口を作らない」)
- 🟡 (note.md §1,§6 / requirements §2.2)

---

## 3. 境界値テストケース（最小値・最大値・null 等）

### B1: 空ランキング (ranked=()) でも `/api/result` が例外なく `ranked=[]` を返す

- **テスト名**: api_result_empty_ranking_returns_empty_list
  - **境界値の意味**: 候補ゼロ (EDGE-001) の下限ケース。ランキングが空でも配信層が破綻しないこと
  - **境界値での動作保証**: 空リストでも 200 / スキーマ (トップレベルキー) を維持する
- **入力値**: `ranked=()` かつ `hypotheses={}` の `SearchResult` フィクスチャ; `client.get("/api/result")`
  - **境界値選択の根拠**: EDGE-001「候補ゼロ → 空ランキング、例外なし」(acceptance-criteria TC-E01)
  - **実際の使用場面**: マッチ候補が全く無いパターン投入時
- **期待される結果**: 200 / `resp.json()["ranked"] == []` / `unknown_phase_flag` と `n_hypotheses`(=0) キーが存在
  - **境界での正確性**: 空でも to_summary スキーマ全キーが揃う
  - **一貫した動作**: 非空時と同じトップレベル構造
- **テストの目的**: 空入力の堅牢性検証 (EDGE-001)
  - **堅牢性の確認**: `ranked[0]` アクセス等の暗黙前提がないこと
- 🟡 (acceptance-criteria TC-E01 / requirements §4 / to_summary L163-173)

### B2: `unknown_phase_flag=True` が `/api/result` トップレベルに含まれる

- **テスト名**: api_result_includes_unknown_phase_flag_true
  - **境界値の意味**: 全仮説高 R / 未マッチ非空 (EDGE-002 / REQ-106) の未知相状態。フラグが必ず表面化すること
  - **境界値での動作保証**: フラグ True/False いずれでもトップレベルに常在する
- **入力値**: `unmatched=UnmatchedPeakReport(unmatched_observed=(Peak,...), extra_calculated=(), unknown_phase_flag=True)` を持つフィクスチャ; `client.get("/api/result")`
  - **境界値選択の根拠**: TC-007-04「未知相フラグが応答に含まれる」/ EDGE-002 / REQ-106
  - **実際の使用場面**: 既知相で説明しきれない未知相の存在をユーザーに警告する場面
- **期待される結果**: `resp.json()["unknown_phase_flag"] is True` (キーが常在し bool 型)
  - **境界での正確性**: `bool(self.unmatched.unknown_phase_flag)` の純 bool 変換 (tree.py L165)
  - **一貫した動作**: False ケース (B1) でも同キーが存在
- **テストの目的**: 未知相フラグの応答内包検証 (TC-007-04 / REQ-106)
  - **堅牢性の確認**: フラグが欠落しないこと
- 🟡 (acceptance-criteria TC-007-04/TC-E02 / requirements §4 / tree.py L165)

### B3: `metrics=None` のノード詳細が防御的に null を返す

- **テスト名**: hypothesis_detail_with_none_metrics
  - **境界値の意味**: metrics 未付与ノードの防御分岐。全評価ノードに metrics 付与済みだが防御的 None 分岐を検証
  - **境界値での動作保証**: metrics None でも 500 でなく metrics=null (または None フィールド) で 200 を返す
- **入力値**: `Hypothesis(..., metrics=None)` を `hypotheses` に含めたフィクスチャ; `client.get(f"/api/hypotheses/{none_metrics_id}")`
  - **境界値選択の根拠**: note.md §3.2「metrics が None のノードは無いが、防御的に None 分岐を用意してよい」
  - **実際の使用場面**: 将来 unranked/未精密化ノードを詳細表示する場合の安全弁
- **期待される結果**: 200 / `data["metrics"] is None` (または metrics キーが None) / 例外・500 が発生しない
  - **境界での正確性**: None 分岐で `metrics.rwp` へアクセスしない
  - **一貫した動作**: metrics 有ノード (N5) と同じトップレベル構造 (metrics のみ null)
- **テストの目的**: metrics None の防御的処理検証
  - **堅牢性の確認**: None アクセスによる AttributeError が起きないこと
- 🟡 (note.md §3.2,§6 / model/hypothesis.py `metrics: RefinementMetrics | None`)

### B4: unranked ノード (hypotheses にのみ存在) の詳細も引ける

- **テスト名**: hypothesis_detail_lookup_from_hypotheses_not_ranked
  - **境界値の意味**: ルックアップ元が `ranked` ではなく `hypotheses` 全体であることの境界。ranked に無い id も引ける
  - **境界値での動作保証**: ranked ⊆ hypotheses。ranked 外 id でも 200 で詳細を返す
- **入力値**: `hypotheses` にのみ存在し `ranked` に含まれない id を持つフィクスチャ; `client.get(f"/api/hypotheses/{unranked_id}")`
  - **境界値選択の根拠**: note.md §3.1,§6「ルックアップ元は ranked ではなく hypotheses 全体」「unranked ノード id も引けてよい」
  - **実際の使用場面**: 系譜 (parent_id) 辿りで ranked 外ノードを参照する場合
- **期待される結果**: 200 / 詳細 JSON が返る (404 にならない)
  - **境界での正確性**: `result.hypotheses[id]` を参照し `ranked` を参照しない
  - **一貫した動作**: ranked 内 id (N5) と同じスキーマで返る
- **テストの目的**: ルックアップ元が hypotheses 全体であることの検証
  - **堅牢性の確認**: ranked に限定した実装バグを検出
- 🔵 (note.md §3.1 L54,§6 / api-endpoints.md L54-58)

### B5: web extra 未導入環境ではテストモジュールが skip される

- **テスト名**: module_skipped_without_web_extra
  - **境界値の意味**: 依存の有無という環境境界。fastapi 未導入では実行不能なため自動 skip する
  - **境界値での動作保証**: 未導入環境で collection エラーにせず skip、導入環境では実行する
- **入力値**: モジュール冒頭 `pytest.importorskip("fastapi")` / `pytest.importorskip("fastapi.testclient")`
  - **境界値選択の根拠**: TASK-0009 完了条件「web extra 未導入環境では skip マーカー」/ note.md §5
  - **実際の使用場面**: コアのみ (`uv sync`) の CI/環境で webui テストが失敗しないこと
- **期待される結果**: fastapi 有 → 全テスト実行 / fastapi 無 → モジュール全体 skip (import 失敗で collection が止まらない)
  - **境界での正確性**: skip は移植性ガードであり、本環境 (fastapi 導入済み) では実行される
  - **一貫した動作**: `tests/test_gpx_export.py` の gsas skip 分岐と同流儀
- **テストの目的**: 環境依存 skip の正当性検証 (完了条件)
  - **堅牢性の確認**: 未導入環境での false failure を防ぐ
- 🟡 (note.md §5 / TASK-0009.md 完了条件 / tests/test_gpx_export.py 参考)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 (CPython)
  - **言語選択の理由**: プロジェクト全体が Python (src layout + uv/hatchling)。frozen dataclass + `typing.Protocol` 境界 (CLAUDE.md)
  - **テストに適した機能**: dataclass ベースのフィクスチャ直接構築、`json.dumps` による純型検証、型注釈による契約明示
- **テストフレームワーク**: pytest >= 8 (+ pytest-cov) / `fastapi.testclient.TestClient` (httpx 依存)
  - **フレームワーク選択の理由**: 既存テストが pytest 1:1 構成 (`tests/test_*.py`)。TestClient は ASGI アプリを直接叩けるため `serve` (ブロッキング uvicorn) を起動せずに検証可能
  - **テスト実行環境**: `uv run pytest`。fastapi/uvicorn/httpx は本 venv に導入済み。未導入環境は `pytest.importorskip` で skip
- 🔵 (note.md §1,§5 / pyproject.toml `[tool.pytest.ini_options]` / requirements §2.1)

---

## 5. テストケース実装時の日本語コメント指針

各テストには Given/When/Then 構造の日本語コメントを付与する。

```python
def test_api_result_returns_to_summary_json(client, result):
    # 【テスト目的】: GET /api/result が to_summary() の JSON を無改変で返すことを確認 🔵
    # 【テスト内容】: TestClient で /api/result を GET し応答を to_summary() と完全比較
    # 【期待される動作】: 200 かつ resp.json() == result.to_summary()

    # 【実際の処理実行】: read-only な /api/result エンドポイントを呼び出す
    resp = client.get("/api/result")

    # 【結果検証】: ステータスと JSON 完全一致を確認
    assert resp.status_code == 200          # 【検証項目】: 正常配信 🔵
    assert resp.json() == result.to_summary()  # 【検証項目】: to_summary 無改変配信 🔵


def test_post_api_result_is_not_allowed(client):
    # 【テスト目的】: read-only 保証 — 変更系ハンドラが存在しないこと 🔵 REQ-007
    # 【テスト内容】: POST /api/result が 405/404 になることを確認
    # 【期待される動作】: 書き込み口が構造的に存在しない
    resp = client.post("/api/result")
    assert resp.status_code in (404, 405)   # 【検証項目】: 変更系ハンドラ不存在 🔵
```

- **Given (準備)**: 軽量 `SearchResult` フィクスチャを構築し `create_app(result)` を TestClient に渡す
- **When (実行)**: `client.get/post/put/delete(...)` で各エンドポイントを叩く (serve は起動しない)
- **Then (検証)**: status_code / JSON 一致 / エラー形状 / キー存在を assert する

---

## 6. 要件定義との対応関係

- **参照した機能概要**: requirements §1 (Web UI 最小版 / 下流の薄い配信層) / note.md §1
- **参照した入力・出力仕様**: requirements §2.1 (関数シグネチャ), §2.2 (3 エンドポイント), §2.3 (`/api/result` スキーマ), §2.4 (詳細シリアライズ) / api-endpoints.md
- **参照した制約条件**: requirements §3 (read-only 構造担保 / 遅延 import / localhost 既定 / extra web 案内 / 決定論) / note.md §2,§6
- **参照した使用例**: requirements §4 (基本パターン / エッジケース: 不明 id 404 / 変更系 405 / 未知相フラグ / metrics None / fastapi 未導入) / dataflow.md L90-123

### 受け入れ基準 (TC-007) とテストケース対応表

| 受け入れ基準 | 対応テストケース |
|---|---|
| TC-007-01 (`/api/result` が to_summary JSON) | N1, N2, N7, B1 |
| TC-007-02 (`GET /` が HTML + ID) | N3, N4 |
| TC-007-03 (変更系不存在 / read-only) | E1, E2, E5 |
| TC-007-04 (不明 id 404 + 未知相フラグ) | N5, N6, E3, B2, B3, B4 |
| 完了条件 (web extra 未導入 skip / 明確な誘導) | E4, B5 |

---

## 7. テストケース一覧（サマリ）

| # | ID | 分類 | テスト名 | 対応 AC | 信頼性 |
|---|---|---|---|---|---|
| 1 | N1 | 正常系 | api_result_returns_to_summary_json | TC-007-01 | 🔵 |
| 2 | N2 | 正常系 | api_result_ranked_row_has_required_keys | TC-007-01 | 🔵 |
| 3 | N3 | 正常系 | root_returns_html | TC-007-02 | 🟡 |
| 4 | N4 | 正常系 | root_html_contains_id_render_target_and_api_id_matches | TC-007-02 | 🟡 |
| 5 | N5 | 正常系 | hypothesis_detail_returns_full_json | TC-007-04 | 🟡 |
| 6 | N6 | 正常系 | hypothesis_detail_is_json_serializable_pure_types | TC-007-04 | 🟡 |
| 7 | N7 | 正常系 | api_result_ranked_is_deterministic_rank_order | TC-007-01 | 🔵 |
| 8 | E1 | 異常系 | post_api_result_is_not_allowed | TC-007-03 | 🔵 |
| 9 | E2 | 異常系 | put_and_delete_routes_are_absent | TC-007-03 | 🔵 |
| 10 | E3 | 異常系 | hypothesis_detail_unknown_id_returns_404_json | TC-007-04 | 🟡 |
| 11 | E4 | 異常系 | create_app_without_fastapi_raises_web_unavailable | 完了条件 | 🟡 |
| 12 | E5 | 異常系 | unknown_get_route_returns_404 | TC-007-03 | 🟡 |
| 13 | B1 | 境界値 | api_result_empty_ranking_returns_empty_list | TC-007-01/E01 | 🟡 |
| 14 | B2 | 境界値 | api_result_includes_unknown_phase_flag_true | TC-007-04 | 🟡 |
| 15 | B3 | 境界値 | hypothesis_detail_with_none_metrics | TC-007-04 | 🟡 |
| 16 | B4 | 境界値 | hypothesis_detail_lookup_from_hypotheses_not_ranked | TC-007-04 | 🔵 |
| 17 | B5 | 境界値 | module_skipped_without_web_extra | 完了条件 | 🟡 |

**合計 17 件**: 正常系 7 / 異常系 5 / 境界値 5
**信頼性分布**: 🔵 5 / 🟡 12 / 🔴 0

---

## 8. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 (7) / 異常系 (5) / 境界値 (5) を網羅
- 期待値定義: 各ケースに具体的 assert (status_code / JSON 一致 / キー存在 / エラー形状) を明記
- 技術選択: Python 3.12 + pytest + fastapi TestClient (httpx) で確定
- 実装可能性: to_summary は TASK-0007 完成済み、詳細は hypotheses から素直にシリアライズ。フィクスチャは直接構築で軽量
- 信頼性レベル: 🔵 5 / 🟡 12 / 🔴 0 (read-only・スキーマ・関数契約は要件/設計に遡及)
```

- **総合判定**: ✅ 高品質。TC-007-01〜04 と完了条件 (web extra skip / 明確な誘導) を全カバー。read-only 保証は変更系メソッド全種 (POST/PUT/DELETE/PATCH) と未定義パスで多面的に検証。🔴 (根拠なし推測) はゼロ。

---

## 9. 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m1-hypothesis-search TASK-0009` で Red フェーズ (失敗テスト作成) を開始します。
