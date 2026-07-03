# TASK-0009 Web UI 最小版 (FastAPI read-only) — TDD 要件定義書

- **機能名**: Web UI 最小版 (read-only 結果閲覧)
- **タスクID**: TASK-0009
- **要件名**: m1-hypothesis-search
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 4h / Phase 4
- **作成日**: 2026-07-03
- **総合信頼性**: 🟡 (REQ-007 / 設計 D6 由来。「Web UI 最小版」の語のみで推測比率高。read-only 制約・表示項目・API スキーマは REQ-007 / api-endpoints.md に遡及)

**【信頼性レベル凡例】**: 🔵 EARS 要件・設計文書を参考にほぼ推測なし / 🟡 要件・設計から妥当な推測 / 🔴 要件・設計にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🟡 **何をする機能か**: 木探索の出力 `SearchResult` を、ローカルブラウザから**読み取り専用**で閲覧できる最小構成の Web UI を提供する。FastAPI + 同梱の静的 HTML 1 枚 (ビルドツール無し、`fetch` で JSON を描画) で、仮説ランキング・Rwp/GOF・確率・僅差競合フラグ・未知相フラグを表示する。
- 🟡 **どのような問題を解決するか**: CLI/プログラム出力の `SearchResult` を、非開発者でも「仮説ランキングと主要メトリクスを一覧・詳細確認」できる形で可視化する。解析結果の閲覧に GSAS-II GUI 起動やコード読解を不要にする。
- 🔵 **想定されるユーザー**: ローカル環境の単一ユーザー (解析者)。認証なし・localhost バインド前提の個人閲覧ツール。
- 🔵 **システム内での位置づけ**: 探索コアの**下流の薄い配信層**。ロジックを持たず `SearchResult.to_summary()` / `result.hypotheses` を JSON 化して返すだけ。コア依存 (numpy のみ) を汚染しない optional extra `web` として分離。read-only 保証は「変更系ルートを定義しない」構造で担保 (D6)。
- **参照した EARS 要件**: REQ-007 (読み取り専用結果表示 🟡), REQ-301 (簡易比較・任意 🟡), NFR-101 (localhost バインド 🟡)
- **参照した設計文書**: architecture.md D6 (L124-131 Web UI 最小版), dataflow.md (L90-123 Web UI フロー), api-endpoints.md (共通仕様/エンドポイント)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 公開関数シグネチャ 🔵 (interfaces.py L221-233 契約)

```python
# src/tsumugin/webui/app.py
def create_app(result: "SearchResult"):  # -> fastapi.FastAPI
    """read-only アプリ。GET / (HTML), GET /api/result, GET /api/hypotheses/{id} のみ。"""

def serve(result: "SearchResult", *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """uvicorn でローカル配信 (ブロッキング)。"""
```

- **入力 `result`**: `SearchResult` (frozen dataclass, `src/tsumugin/search/tree.py` L94-173)。`ranked` / `hypotheses` / `to_summary()` を保持済み (TASK-0007 完了)。🔵
- **`host` / `port`**: kw-only (`*` 区切り、interfaces.py 契約通り)。既定 `127.0.0.1` / `8765`。🔵 NFR-101
- **`create_app` の戻り値**: `fastapi.FastAPI` インスタンス (テストは TestClient で叩く)。🔵
- **`serve` の戻り値**: `None` (`uvicorn.run(create_app(result), host=host, port=port)` 相当のブロッキング呼び出し)。🟡

### 2.2 エンドポイントの入出力 🟡 (api-endpoints.md / dataflow.md L90-109)

| メソッド/パス | 入力 | 出力 |
|---|---|---|
| `GET /` | なし | 静的 `index.html` (HTML 200, `content-type: text/html`)。`fetch` でランキング/詳細を描画 🟡 |
| `GET /api/result` | なし | `result.to_summary()` の JSON をそのまま配信 (200) 🟡 |
| `GET /api/hypotheses/{id}` | パスパラメータ `id` (str) | 仮説 1 件詳細 JSON (相ごとの格子・scale・metrics 全量・系譜)。不明 id → 404 🟡 |

### 2.3 `GET /api/result` レスポンススキーマ 🔵 (to_summary() 準拠, api-endpoints.md L30-52)

- トップレベルキー: `ranked: list[dict]`, `unknown_phase_flag: bool`, `unmatched_observed: [{position, height}]`, `extra_calculated: [float]`, `warnings: [str]`, `n_hypotheses: int`
- `ranked` 各行: `{id, rank(1起番), probability, close_competitor, rwp, gof, evidence:{backend,value}, phases:[{phase_ref, wt_frac, lattice:{a,b,c}}], parent_id, in_good_cluster}`
- 全値が素の型 (str/int/float/bool/None/list/dict) に明示変換済み。**numpy スカラー混入なし** — app 側で追加変換不要。`resp.json() == result.to_summary()` が成立。🔵

### 2.4 `GET /api/hypotheses/{id}` 詳細シリアライズ (app 側で新規実装) 🟡

- `to_summary()` は per-id 詳細を提供しないため、**`result.hypotheses[id]` (`Hypothesis`) から独自シリアライズ**する。ルックアップ元は `ranked` ではなく `hypotheses` 全体 (ranked ⊆ hypotheses)。🔵
- 含める内容 (api-endpoints.md L54-58「相ごとの格子・scale・metrics 全量・系譜」):
  - `Hypothesis`: `id` / `parent_id` / `status` / `phases`
  - `PhaseInstance`: `phase_ref` / `scale` / `wt_frac` / `occupancies` / `lattice`
  - `LatticeParams`: `a/b/c/alpha/beta/gamma` + `sigma` + `volume()` (to_summary は a/b/c のみだが詳細は角度・sigma まで可)
  - `RefinementMetrics`: `rwp/gof/chi2/n_obs/n_params/evidence` (evidence 全量)
- **純型変換必須**: numpy スカラー・dataclass を素通しせず `float()`/`str()`/`dict(...)` で明示変換 (`json` 化失敗回避、to_summary と同流儀)。🟡

### データフロー 🟡 (dataflow.md L90-109)

```
Br->>W: GET /                    → index.html (静的)
Br->>W: GET /api/result          → result.to_summary() → JSON
Br->>W: GET /api/hypotheses/{id}  → result.hypotheses[id] を詳細 JSON 化
不明 id → 404 JSON               (エラーハンドリングフロー L122)
変更系ルートは存在しない (read-only)
```

- **参照した EARS 要件**: REQ-007, REQ-301, NFR-101
- **参照した設計文書**: interfaces.py L221-233, api-endpoints.md, dataflow.md L90-109, tree.py `to_summary()` L113-173, model/hypothesis.py, model/phase.py

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **read-only 保証 (最重要)**: **GET 以外のルートを一切定義しない**。`@app.post/put/delete/patch` を書かない。未定義パスは FastAPI が自然に 405/404 を返す。これがそのまま TC-007-03 (REQ-007) の担保。StaticFiles マウントや汎用ルータで書き込み口を作らない。🔵 REQ-007
- 🟡 **localhost バインド既定 (NFR-101)**: `serve` の既定 `host=127.0.0.1` / `port=8765`。外部公開は非サポート。🟡 NFR-101
- 🔵 **CORS/認証/バージョニング/レート制限なし**: M1 スコープ外を明示 (api-endpoints.md L15)。ローカル単一ユーザー閲覧前提。🔵
- 🔵 **コア依存非汚染**: コアは numpy のみ。fastapi/uvicorn は optional extra `web`、httpx は dev group。**fastapi/uvicorn の import は `create_app`/`serve` 関数内に遅延**させ、`import tsumugin.webui.app` 自体は web 未導入でも成功させる。`webui/__init__.py` は空のまま (eager import しない)。🔵 CLAUDE.md
- 🟡 **未導入時の明確な誘導**: fastapi 未導入で `create_app`/`serve` 呼び出し時、extra `web` の導入を案内する明確なメッセージ (`pip install 'tsumugin[web]'` / `uv sync --extra web`) で送出。**推奨**: `src/tsumugin/errors.py` に `WebUIUnavailableError(TsumuginError)` を新設 (GSASUnavailableError と対称、TDD しやすい)。🟡
- 🔵 **決定論**: `to_summary()` は rank 昇順で決定論的順序を保証済み。app 側で並べ替えない。🔵 REQ-403
- 🟡 **静的ファイル同梱**: `webui/static/index.html` を wheel に含める。パス解決は `Path(__file__).parent / "static" / "index.html"` が確実 (editable install でテスト通過)。🟡
- 🟡 **REQ-301 (簡易比較) は任意**: メトリクス並置は「してもよい」。最小版は ranked テーブル表示で足り、フル diff は M2 (FR-422)。過剰実装しない。🟡
- 🔵 **命名/型/Lint**: snake_case / PascalCase / UPPER_SNAKE、型注釈必須 (`any` 回避)、`uvx ruff check` (line-length 100, py312)。🔵 CLAUDE.md
- **参照した EARS 要件**: REQ-007, REQ-301, REQ-403, NFR-101
- **参照した設計文書**: architecture.md D6 (依存追加表/セキュリティ), api-endpoints.md 共通仕様, errors.py, CLAUDE.md, pyproject.toml (web extra / wheel packages)

---

## 4. 想定される使用例（Edgeケース・データフローベース）

### 基本的な使用パターン 🟡

1. 解析側で `SearchResult` を取得 → `serve(result)` でローカルサーバ起動 → ブラウザで `http://127.0.0.1:8765/` を開く。
2. `index.html` が `GET /api/result` を `fetch` し、ranked テーブル (id/rank/probability/rwp/gof/未知相フラグ) を描画。
3. 行クリック等で `GET /api/hypotheses/{id}` を `fetch` し、相・格子・metrics 詳細を表示。

### エッジケース / エラーケース 🟡 (dataflow.md L122, api-endpoints.md L60)

- **不明な hypothesis id**: `GET /api/hypotheses/{存在しない id}` → **`404 {"detail": "hypothesis not found"}`** (`raise HTTPException(status_code=404, detail="hypothesis not found")`)。🟡 TC-007-04
- **変更系リクエスト**: `POST /api/result` / `PUT` / `DELETE /api/hypotheses/xxx` → **405 か 404** (変更系ハンドラ未定義)。ranked 行 id へ POST しても書き込めない。🔵 TC-007-03
- **未知相フラグ**: `unknown_phase_flag` は `/api/result` 応答トップレベルに常に含まれる (EDGE-002/REQ-106 由来の全仮説高 R 状態も表示可能)。🟡 TC-007-04
- **metrics が None のノード**: 全評価ノードに metrics 付与済みだが、防御的に None 分岐を用意してよい。🟡
- **fastapi 未導入環境**: `create_app`/`serve` 呼び出しで extra `web` 案内エラー。テストは `pytest.importorskip("fastapi")` で自動 skip。🟡

- **参照した EARS 要件**: REQ-007, REQ-106, EDGE-002
- **参照した設計文書**: dataflow.md L90-123 (Web UI フロー / エラーハンドリング), api-endpoints.md L54-60

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 解析結果の読み取り専用閲覧 (§13 M1「Web UI 最小版」)
- **参照した機能要件**: REQ-007 (読み取り専用表示 🟡), REQ-301 (簡易比較・任意 🟡)
- **参照した非機能要件**: NFR-101 (localhost バインド 🟡), REQ-403 (決定論的順序 🔵)
- **参照した Edge ケース**: EDGE-002 (全仮説高 R → 未知相フラグ), REQ-106 (未知相フラグ強制表示)
- **参照した受け入れ基準**: TC-007-01〜04 (acceptance-criteria.md L70-75)
  - **TC-007-01** 🟡: `GET /api/result` が `to_summary()` の JSON (ranked / unknown_phase_flag 含む) を返す
  - **TC-007-02** 🟡: `GET /` が HTML を返し仮説 ID を含む (SPA なら「/ が HTML 200」+「/api/result の ID 一致」で分割検証)
  - **TC-007-03** 🔵 (REQ-007): POST/PUT/DELETE ルートが存在しない (405/404) — read-only 保証
  - **TC-007-04** 🟡: 不明 id で 404 JSON、かつ `/api/result` に `unknown_phase_flag` 含む
  - テストは fastapi TestClient (httpx)。web extra 未導入環境では skip (`pytest.importorskip`)
- **参照した設計文書**:
  - **アーキテクチャ**: architecture.md D6 (L124-131 Web UI 最小版 / 依存追加表 L52-54)
  - **データフロー**: dataflow.md (L90-123 Web UI フロー・エラーハンドリング)
  - **型定義**: interfaces.py (L221-233 `create_app` / `serve` 契約)
  - **API 仕様**: api-endpoints.md (共通仕様 / `/api/result` / `/api/hypotheses/{id}`)
  - **配信対象実装**: tree.py `SearchResult.to_summary()` (L113-173, TASK-0007 完了), model/hypothesis.py (`Hypothesis`/`RefinementMetrics`), model/phase.py (`PhaseInstance`/`LatticeParams`)
  - **参考パターン**: backends/gsasii.py (`gsasii_available` / `GSASUnavailableError` の available + 専用例外パターン), errors.py (例外階層)

---

## 6. 実装対象ファイル

- **新規実装**: `src/tsumugin/webui/app.py` (`create_app` / `serve`), `src/tsumugin/webui/static/index.html` (単一ページ結果ビュー)
- **新規/変更 (推奨)**: `src/tsumugin/errors.py` に `WebUIUnavailableError(TsumuginError)` 追加
- **新規テスト**: `tests/test_webui.py` (fastapi TestClient, `pytest.importorskip` で web 未導入 skip)
- **スコープ外 (TASK-0010)**: 公開 API 統合 (`tsumugin/__init__.py __all__` 昇格) / E2E / ドキュメント。汎用 REST API (FR-512) は M4+。

---

## 7. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (関数契約・API スキーマ・read-only 制約・エラー仕様が確定済み)
- 入出力定義: 完全 (シグネチャ・3 エンドポイント・JSON スキーマ・エラー形状すべて明記)
- 制約条件: 明確 (read-only 構造担保・遅延 import・localhost 既定・extra web 案内)
- 実装可能性: 確実 (to_summary は完成済み、詳細は hypotheses から素直にシリアライズ)
- 信頼性レベル: 🔵 と 🟡 が主。🔴 なし
```

- **信頼性分布**: 🔵 約 12 / 🟡 約 14 / 🔴 0
- **総合判定**: 要件範囲内で十分。Web UI は仕様上「最小版」の語のみのため機能表現に推測 (🟡) が残るが、read-only 制約・API スキーマ・関数契約は要件/設計に遡及して確定。過剰実装 (REQ-301 フル比較・CORS/認証) を明示的に回避。
