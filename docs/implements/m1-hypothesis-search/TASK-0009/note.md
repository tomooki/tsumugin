# TASK-0009 Web UI 最小版 (FastAPI read-only) — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`src/tsumugin/webui/app.py` に **`create_app(result: SearchResult) -> fastapi.FastAPI`** と
**`serve(result, *, host="127.0.0.1", port=8765) -> None`**、**`src/tsumugin/webui/static/index.html`**
(fetch でランキングを描画する単一ページ) を新規実装し、`SearchResult` を**読み取り専用**でブラウザ閲覧可能にする (REQ-007 / 設計 D6)。
公開ルートは **GET / (HTML)** / **GET /api/result** / **GET /api/hypotheses/{id}** の 3 本のみ。
`SearchResult.to_summary()` (TASK-0007 完了・api-endpoints スキーマ準拠) をそのまま `/api/result` で配信する。
fastapi 未導入環境では **import 時に extra `web` を案内する明確なエラー**を出し、テストは **fastapi TestClient (httpx)** で書き
web extra 未導入環境では skip する。

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 4 相互運用・UI・統合
- **信頼性レベル**: 🟡 *REQ-007 / D6 (「Web UI 最小版」の語のみで推測比率高。read-only 制約と表示項目は REQ-007 に遡及)*
  完了条件 5 件のうち 🔵 1 (read-only 保証 = 変更系ルート不存在) / 🟡 4
- **主要実装**:
  1. `src/tsumugin/webui/app.py`: `create_app()` / `serve()` 🟡
  2. `src/tsumugin/webui/static/index.html`: 単一ページ結果ビュー (fetch で JSON 描画、ビルドツール無し) 🟡
- **テスト**: `tests/test_webui.py` (新規、fastapi TestClient)
- **依存**: 前提 [TASK-0007](../../../tasks/m1-hypothesis-search/TASK-0007.md) (`SearchResult.to_summary()` 実装済み) / 後続 TASK-0010 (公開 API 統合 + E2E)
- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0009.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。frozen dataclass + `typing.Protocol` 境界 (CLAUDE.md 規約)
- **Web フレームワーク (M1 新規)**: **FastAPI >= 0.110 + uvicorn >= 0.29** (optional extra `web`)。ビルドツール無し、静的 HTML 1 枚を `fetch` で描画する構成 (architecture.md D6)
- **コア依存の維持**: コアは numpy のみ。fastapi/uvicorn は **optional extra `web`**、httpx は **dev group**。`app.py` の webui 依存は本体 import を汚染しない (lazy import 方針、下記 §6)
- **パッケージマネージャー**: uv 0.9.x (src layout + hatchling)。web extra 導入は `uv sync --extra web` (gsas と併用なら `uv sync --extra gsas --extra web`)。テスト実行 `uv run pytest`
- **本環境の導入状況 (確認済み)**: 現 venv では **fastapi / uvicorn / httpx いずれも import 可能**。よって本環境では Web テストは skip されず**実行される** (skip 分岐は web 未導入環境向けの移植性ガード)
- **アーキテクチャ**: webui は探索コアの**下流の薄い配信層**。ロジックは持たず `SearchResult.to_summary()` / `result.hypotheses` を JSON 化して返すだけ。read-only 保証は「変更系ルートを定義しない」ことで構造的に担保する (D6)
- **参照元**: `pyproject.toml` (`[project.optional-dependencies].web` / `[dependency-groups].dev`), `docs/design/m1-hypothesis-search/architecture.md` (D6 / 依存追加表), `docs/spec/m1-hypothesis-search/note.md` (§技術スタック), `CLAUDE.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止。**git commit は本セッションでは行わない (制約)**
- **read-only / 非破壊 (P2 / NFR-101 / REQ-007)**: **GET 以外のルートを一切定義しない**。POST/PUT/DELETE/PATCH ハンドラを書かない (未定義パスは FastAPI が自然に 405/404 を返す)。これがそのまま完了条件③ (TC-007-03) の担保
- **localhost バインド既定 (NFR-101)**: `serve` の既定 host は `127.0.0.1`、port `8765`。外部公開は非サポートと明記
- **未導入時の明確な誘導**: fastapi 未導入で `create_app`/`serve` 呼び出し時に **extra `web` の導入を案内する明確なメッセージ**を出す (詳細 §3.3 / §6)
- **命名/型**: snake_case / PascalCase / UPPER_SNAKE。型注釈必須 (`any` 回避)。`host`/`port` は kw-only (`*` 区切り、interfaces.py 契約通り)
- **docstring**: 日本語可。REQ/FR 番号と 🔵🟡 信頼性レベルを紐づける (既存モジュールの慣習を踏襲)
- **Lint**: `uvx ruff check src tests` (line-length 100, target py312)
- **決定論**: `to_summary()` は既に決定論的順序 (rank 昇順) を保証済み。app 側で並べ替えない
- **参照元**: `CLAUDE.md` (実装上の不変条件/規約), `docs/spec/m1-hypothesis-search/note.md` (§開発ルール/§セキュリティ制約), `docs/design/m1-hypothesis-search/architecture.md` (D6 / セキュリティ)

## 3. 関連実装

### 3.1 配信対象データ (最重要) — `SearchResult` (`src/tsumugin/search/tree.py` L94-173、TASK-0007 完了)
- **`SearchResult.to_summary() -> dict`** (L113-173): **`/api/result` スキーマに完全準拠済み**。app は**加工せずそのまま返すだけ**。返す純 dict のトップレベルキー:
  - `ranked: list[dict]` — 各行 `{id, rank(1起番), probability, close_competitor, rwp, gof, evidence:{backend,value}, phases:[{phase_ref, wt_frac, lattice:{a,b,c}}], parent_id, in_good_cluster}`
  - `unknown_phase_flag: bool` (完了条件④ TC-007-04 の担保元)、`unmatched_observed: [{position,height}]`、`extra_calculated: [float]`、`warnings: [str]`、`n_hypotheses: int`
  - 全値が素の型 (str/int/float/bool/None/list/dict) へ明示変換済みで `json.dumps` 成功保証。**numpy スカラー混入なし** — app 側で追加変換は不要
- **`SearchResult.hypotheses: Mapping[str, Hypothesis]`** (L104): 全評価ノード (ranked は refined の部分集合)。**`/api/hypotheses/{id}` のルックアップ元はこちら** (ranked ではなく hypotheses 全体)。キー = `hyp-XXXX` (評価順連番)
- **参照元**: `src/tsumugin/search/tree.py` (`SearchResult` / `to_summary`), `docs/design/m1-hypothesis-search/api-endpoints.md`

### 3.2 `/api/hypotheses/{id}` の詳細 JSON 化 (app 側で新規に組む部分)
- **`to_summary()` は per-id 詳細を提供しない**ため、詳細エンドポイントは **`result.hypotheses[id]` (`Hypothesis`) から独自にシリアライズ**する必要がある。api-endpoints.md L54-60: 「相ごとの格子・scale・metrics 全量・系譜」
- `Hypothesis` (`src/tsumugin/model/hypothesis.py`): `id` / `phases: tuple[PhaseInstance,...]` / `parent_id` / `metrics: RefinementMetrics | None` / `status`
- `PhaseInstance` (`src/tsumugin/model/phase.py`): `phase_ref` / `lattice: LatticeParams` / `scale` / `wt_frac` / `occupancies: Mapping[str,float]`
- `LatticeParams`: `a/b/c/alpha/beta/gamma` + `sigma: Mapping[str,float]` + `volume()`。**to_summary は a/b/c のみだが、詳細は角度・sigma・scale・occupancies まで含めてよい** (「格子・scale・metrics 全量」)
- `RefinementMetrics`: `rwp/gof/chi2/n_obs/n_params/evidence: Mapping[str,float]` — 詳細では evidence を全量で返す
- **エラー**: 存在しない id → **`404 {"detail": "hypothesis not found"}`** (api-endpoints.md L60)。FastAPI なら `raise HTTPException(status_code=404, detail="hypothesis not found")`。完了条件④「不明 id で 404 JSON」
- **注意**: metrics が None のノードは無いが (全評価ノードに metrics 付与済み)、防御的に None 分岐を用意してよい

### 3.3 fastapi 未導入時の明確なエラー (完了条件・「extra web の案内」)
- **既存に web 用の例外は無い** (`src/tsumugin/errors.py`: `TsumuginError` / `GuardrailError` / `EscalationRequired` / `GSASUnavailableError`)。実装時に選択:
  - (推奨) **`errors.py` に `WebUIUnavailableError(TsumuginError)` を新設**し、fastapi import 失敗時に「`pip install 'tsumugin[web]'` / `uv sync --extra web`」を案内するメッセージで送出。GSASUnavailableError と対称的で TDD しやすい
  - もしくは素の `ImportError`/`RuntimeError` を明確メッセージで送出 (テストが型を握れれば可)
- **モジュール import 汚染を避ける**: `webui/__init__.py` (現状 `__all__=[]` の空) と `app.py` は **fastapi/uvicorn を遅延 import** する。`import tsumugin.webui.app` 自体は web 未導入でも成功し、**`create_app`/`serve` 呼び出し時点**で fastapi を import → 失敗時に上記エラー。これによりコア import が web extra に依存しない (CLAUDE.md「コア依存は numpy のみ」)
- **参照元**: `src/tsumugin/errors.py`, `src/tsumugin/webui/__init__.py`, `docs/tasks/m1-hypothesis-search/TASK-0009.md` (L13-14)

### 3.4 参考にする既存パターン
- **未導入判定 + 専用例外の型**: `src/tsumugin/backends/gsasii.py::gsasii_available()` (`@lru_cache`・副作用なし find_spec) + `GSASUnavailableError` 送出 → **web 版の相似パターン**として踏襲可 (`web_available()` 相当を任意で用意)
- **静的ファイル配信**: FastAPI の `FileResponse` / `HTMLResponse` で `webui/static/index.html` を返す。パス解決は `importlib.resources` か `Path(__file__).parent/"static"/"index.html"` (パッケージ同梱を hatchling wheel に含める点は §6 注意)
- **参照元**: `src/tsumugin/backends/gsasii.py` (available パターン)

## 4. 設計文書 (契約)

### 4.1 型契約 (interfaces.py L221-233)
```python
def create_app(result: "SearchResult"):  # -> fastapi.FastAPI 🟡 D6
    """read-only アプリ。GET / (HTML), GET /api/result, GET /api/hypotheses/{id} のみ。"""

def serve(result: "SearchResult", *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """uvicorn でローカル配信。🟡 NFR-101"""
```
- `serve` は `uvicorn.run(create_app(result), host=host, port=port)` 相当。テストは `create_app` を TestClient で叩き `serve` はブロッキングなので直接テストしない (起動確認は任意)

### 4.2 D6 Web UI (architecture.md L124-131, 🟡 interview Q2 確定案)
- FastAPI + 同梱静的 HTML 1 枚 (ビルドツール無し、fetch で JSON 描画)
- **GET のみ実装** (read-only 保証は「変更系ルートの不存在」で担保、テストで検証)
- `SearchResult.to_summary()` が JSON 化可能な dict を返し、app はそれを配信するだけ
- 既定バインド 127.0.0.1 (NFR-101)

### 4.3 Web UI データフロー (dataflow.md L90-109, 🟡)
```
Br->>W: GET /        → W-->>Br: index.html (静的)
Br->>W: GET /api/result       → W->>R: to_summary() → JSON
Br->>W: GET /api/hypotheses/{id} → 仮説詳細 JSON (相・格子・metrics)
Note: 変更系ルートは存在しない (read-only)
不明な hypothesis id (Web) → 404 JSON  (エラーハンドリングフロー L122)
```

### 4.4 API スキーマ (api-endpoints.md)
- 共通: 127.0.0.1 既定・認証なし・バージョニング/CORS/レート制限なし (M1 スコープ外を明示) 🔵。read-only は GET 以外のルート非定義で担保 (TC-007-03) 🔵 REQ-007
- `GET /api/result` = `to_summary()` そのまま (§3.1 の JSON 例が正)
- `GET /api/hypotheses/{id}` = 仮説 1 件詳細、不明 id → `404 {"detail": "hypothesis not found"}`

### 4.5 完了条件 (TASK-0009.md L19-24、= TC-007 系へ遡及)
- [ ] **TC-007-01** 🟡: `GET /api/result` が `to_summary()` の JSON (ranked / unknown_phase_flag 含む) を返す
- [ ] **TC-007-02** 🟡: `GET /` が HTML を返し**仮説 ID を含む** (ランキング描画。index.html が fetch で描くので、テストはトップページ HTML 応答 + 中に ID/ランク要素が現れることを検証。※SPA の場合は fetch 後描画のため、少なくとも HTML 200 + テンプレートに ID 表示領域があること、または API 経由 ID 一致で担保)
- [ ] **TC-007-03** 🔵 *REQ-007*: **POST/PUT/DELETE ルートが存在しない** (405/404) — read-only 保証
- [ ] **TC-007-04** 🟡: 不明 id で **404 JSON**、および `/api/result` 応答に **`unknown_phase_flag` が含まれる**
- [ ] 🟡: テストは **fastapi TestClient (httpx)**。**web extra 未導入環境では skip** マーカー
- **参照元**: `docs/design/m1-hypothesis-search/interfaces.py` (L221-233), `architecture.md` (D6 L124-131), `dataflow.md` (L90-123),
  `api-endpoints.md`, `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-007-01〜04 L70-75), `requirements.md` (REQ-007 L42 / REQ-301 L71 / NFR-101 L96)

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-q"`)
- **新規テストファイル**: **`tests/test_webui.py`** (実装ファイルと 1:1)。`from fastapi.testclient import TestClient` + `from tsumugin.webui.app import create_app`
- **web 未導入 skip の実現手段 (いずれか)**:
  1. (最小・推奨) テストモジュール冒頭で **`fastapi = pytest.importorskip("fastapi")`** / `pytest.importorskip("fastapi.testclient")` → 未導入環境は自動 skip。**新規マーカー登録不要**
  2. (gsas と対称) `pyproject.toml` の `markers` に `web` を追加し `tests/conftest.py::pytest_collection_modifyitems` に web 未導入自動 skip を追記 (`gsas` の既存パターン L8-15 を踏襲) → `@pytest.mark.web` を各テストに付与
  - **本環境では fastapi 導入済みのため実際には実行される** (skip 分岐は移植性ガード)。マーカー方式を選ぶ場合は `pyproject.toml` の `markers` 追記を忘れない (未登録マーカーは警告)
- **TestClient は httpx 依存**: httpx は dev group 導入済み・本環境で import 可。fastapi の TestClient がそのまま使える
- **書くべきケース (最小、TC-007 対応)**:
  - **TC-007-01**: `SimulatedBackend` + `HypothesisTreeSearch.search(...)` で `SearchResult` を作り (あるいは軽量な合成 `SearchResult` を直接構築) → `client.get("/api/result")` → 200 / JSON に `ranked` (id/probability/rwp/evidence) と `unknown_phase_flag` キーが存在。`resp.json() == result.to_summary()` の一致検証が堅い
  - **TC-007-02**: `client.get("/")` → 200 / `content-type` が HTML / body に仮説 ID (または ID を描画する DOM 要素) を含む。SPA なら「/ が HTML 200」+「/api/result の ID が想定と一致」で分割検証
  - **TC-007-03** (read-only): `client.post("/api/result")` / `.put` / `.delete("/api/hypotheses/xxx")` が **405 か 404** (変更系ハンドラ未定義)。ranked 行の id へ POST しても書き込めないこと
  - **TC-007-04**: `client.get(f"/api/hypotheses/{known_id}")` → 200 / 相・格子・metrics を含む ; `client.get("/api/hypotheses/nope")` → 404 / `{"detail": "hypothesis not found"}` ; `/api/result` に `unknown_phase_flag` 有
- **テストフィクスチャの作り方**: 探索を実走させると重い場合、`SearchResult` を**直接組み立てる**軽量フィクスチャが有効 (frozen dataclass。`ranked`/`hypotheses`/`unmatched=UnmatchedPeakReport(...)`/`ledger=Ledger()`/`snapshots=SnapshotStore()` を最小構成で)。`tests/test_tree_search.py` の合成データ生成ヘルパ (`GRID = np.arange(...)`, `_phase(...)`) を流用可
- **既存テスト範**: `tests/test_tree_search.py` (SearchResult 構築・to_summary 検証の書式), `tests/test_gpx_export.py` (skip 分岐の書き方)。現状テスト構成は `tests/test_*.py` が実装 1:1
- **参照元**: `pyproject.toml` (`[tool.pytest.ini_options]` / `markers`), `tests/conftest.py` (gsas 自動 skip パターン), `tests/test_tree_search.py` (SearchResult/to_summary の範), `tests/test_gpx_export.py`

## 6. 注意事項
- **read-only の構造的担保が最優先**: 変更系ハンドラを**書かないこと自体**が TC-007-03。`@app.get(...)` のみを使い、`@app.post/put/delete` を一切書かない。うっかり StaticFiles マウントや汎用ルータで書き込み口を作らない
- **fastapi の遅延 import (コア非汚染)**: `webui/app.py` トップレベルで `import fastapi` すると、`import tsumugin`（もし将来 webui を re-export する場合）やコアのテスト収集が web extra を要求してしまう恐れ。**fastapi/uvicorn の import は `create_app`/`serve` 関数内**に置き、失敗時に extra `web` 案内メッセージ (§3.3)。`webui/__init__.py` は空のまま (app を eager import しない)
- **静的ファイルの同梱**: `webui/static/index.html` を wheel に含める必要。`pyproject.toml [tool.hatch.build.targets.wheel] packages=["src/tsumugin"]` は Python パッケージ配下の**非 .py ファイルも既定で取り込む** (hatchling は package データを含める) が、配布時の取りこぼしに注意。パス解決は `Path(__file__).parent / "static" / "index.html"` が確実 (テストは editable install で通る)
- **`/api/hypotheses/{id}` は to_summary の外**: `/api/result` は `to_summary()` 丸投げで済むが、詳細は `result.hypotheses[id]` から**独自シリアライズが必要** (§3.2)。ここで numpy スカラーや dataclass を素通しすると `json` 化に失敗しうるので、`float()`/`str()`/`dict(...)` で純型へ明示変換する (to_summary と同じ流儀)
- **ID の所在**: ランキング表示 (index.html) の各行 id は `ranked` 由来だが、詳細ルックアップは **`result.hypotheses` (全ノード)**。ranked ⊆ hypotheses なので ranked 行 id は必ず引ける。unranked ノード id も引けてよい
- **serve はブロッキング**: `serve` は `uvicorn.run` でプロセスを占有する。ユニットテストで直接起動しない (TestClient は ASGI アプリを直接叩くので serve 不要)。serve のテストは任意 (import 可能性・シグネチャのみ確認で足りる)
- **CORS/認証/バージョニングは実装しない**: M1 スコープ外を明示 (api-endpoints.md L15)。ローカル単一ユーザー閲覧ツール前提
- **REQ-301 (簡易比較) は任意**: メトリクス並置は「してもよい」。M1 最小版では ranked テーブル表示で足り、フル diff は M2 (FR-422)。過剰実装しない
- **スコープ外**: 公開 API 統合 (`tsumugin/__init__.py __all__` への昇格) / E2E / ドキュメントは **TASK-0010**。汎用 REST API (FR-512) は M4+
- **参照元**: `docs/spec/m1-hypothesis-search/note.md` (§セキュリティ制約/§注意事項), `docs/design/m1-hypothesis-search/architecture.md` (D6 / セキュリティ 🟡), `docs/design/m1-hypothesis-search/api-endpoints.md` (共通仕様), `pyproject.toml` (wheel packages / web extra), `CLAUDE.md` (コア依存 numpy のみ)

---

## 収集したファイル一覧
- **タスク**: `docs/tasks/m1-hypothesis-search/TASK-0009.md`, `docs/tasks/m1-hypothesis-search/overview.md`
- **仕様**: `docs/spec/m1-hypothesis-search/note.md`, `docs/spec/m1-hypothesis-search/requirements.md` (REQ-007 / REQ-301 / NFR-101),
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-007-01〜04)
- **設計**: `docs/design/m1-hypothesis-search/interfaces.py` (create_app/serve 契約 L221-233), `architecture.md` (D6 L124-131 / 依存追加表 L52-54),
  `api-endpoints.md` (エンドポイント/スキーマ), `dataflow.md` (Web UI フロー L90-123)
- **前提実装 (配信対象)**: `src/tsumugin/search/tree.py` (`SearchResult` / `to_summary()` L113-173、TASK-0007 完了),
  `src/tsumugin/model/hypothesis.py` (`Hypothesis` / `RefinementMetrics`), `src/tsumugin/model/phase.py` (`PhaseInstance` / `LatticeParams`),
  `src/tsumugin/search/__init__.py` (公開 re-export), `src/tsumugin/errors.py` (例外階層), `src/tsumugin/backends/gsasii.py` (available パターン参考)
- **実装先 (本タスクで新規作成)**: `src/tsumugin/webui/app.py`, `src/tsumugin/webui/static/index.html` (現状 `src/tsumugin/webui/__init__.py` は空)
- **テスト範/設定**: `tests/conftest.py` (gsas 自動 skip パターン), `tests/test_tree_search.py` (SearchResult/to_summary の範),
  `tests/test_gpx_export.py` (skip 分岐), `pyproject.toml` (`[tool.pytest.ini_options]` / `web` extra / dev group)。新規 `tests/test_webui.py`
- **前タスクノート (書式の範)**: `docs/implements/m1-hypothesis-search/TASK-0008/note.md`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` / `docs/spec/m1-hypothesis-search/note.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
