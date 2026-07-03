# TASK-0010 開発コンテキストノート — 公開 API 統合 + E2E + ドキュメント

## 作成日時
2026-07-03

## タスク要約
M1 (多仮説木探索) の総仕上げ統合タスク。実装済み成果物 (TASK-0001〜0009) を公開面へ配線し、
E2E テストとドキュメントで裏取りする。信頼性レベル 🔵 6 / 🟡 1 (M0 統合タスク 010/011 の踏襲)。

- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0010.md`, `docs/tasks/m1-hypothesis-search/overview.md`, `docs/spec/m1-hypothesis-search/note.md`

### 完了条件 (TASK-0010.md より)
1. `from tsumugin import HypothesisTreeSearch, ...` で M1 API が利用可能 🔵
2. E2E: 合成 2 相データの search が真の構成を 1 位にし、summary が JSON 化できる 🔵
3. (@gsas) GSASIIBackend での search E2E が完走 🔵
4. 全テスト green・カバレッジ 90% 以上・ruff clean 🔵
5. README に M1 使用例 (10-15 行)、`docs/dev/context.md` の実装済みモジュール表更新 🔵
6. 検証レポート `docs/tasks/m1-hypothesis-search/reports/verification.md` 作成 🟡 (`reports/` は未作成、要新規)

### TDD フロー
tdd-red (E2E) → tdd-green → tdd-refactor → tdd-verify-complete

---

## 1. 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12 (`target-version = "py312"`)
- **数値**: numpy >= 1.26 (コア唯一の必須依存)
- **パッケージ管理 / ビルド**: uv 0.9.x + hatchling (src layout)
- **Rietveld バックエンド**: GSAS-II 2.0 (`from GSASII import GSASIIscriptable`)。optional extra `gsas` (scipy / pycifrw / requests)。導入済み (ソースツリー `C:\Users\tomoo\G2` + `.pth` + `~/.GSASII/GSASII-bin`)
- **Web UI (M1 新規)**: FastAPI + uvicorn。optional extra `web`。app 内で遅延 import (未導入でも re-export は失敗しない = D6 遅延 import 契約)
- **テスト**: pytest >= 8 + pytest-cov >= 5。TestClient は httpx (dev group) 依存

### アーキテクチャパターン
- レイヤ分離 + 境界は `typing.Protocol` で抽象化 (バックエンド交換可能, P7)
- frozen dataclass による不変値オブジェクト、非破壊更新 (`with_updates()`)
- 全状態遷移は追記専用 Ledger (ハッシュチェーン) + Snapshot (revert 可能, P2)
- 「失敗は例外でなく chi2=inf の結果に変換」しガードレールに処理させる原則

- **参照元**: `pyproject.toml`, `docs/dev/context.md`, `docs/spec/m1-hypothesis-search/note.md`, `README.md`

---

## 2. 開発ルール

### プロジェクト固有ルール (必須)
- **TDD 厳守**: Red → Green → Refactor。テストなし実装コミット禁止
- **本タスク制約**: git commit しない / 質問しない (呼び出し側指示)
- **モデル指定**: 実装エージェント (サブ含む) は Opus
- **成果物保存先**: 要件・設計・タスク・レポートは `docs/` 配下
- **非破壊 (P2 / NFR-101)**: 生データ削除・上書き・履歴改変 API を作らない。Ledger/Snapshot に削除・上書きメソッド追加禁止

### コーディング規約
- **命名**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE
- **型注釈必須** (`any` 回避)。境界は `Protocol` (`@runtime_checkable`)
- **docstring**: 日本語可。FR/NFR/REQ/TC 番号を紐づける慣習
- **Lint/Format**: `uvx ruff check src tests` (line-length 100, target py312) — clean 必須
- **カバレッジ**: TASK-0010 完了条件は 90% 以上 (M0 実績 95%)

### テスト運用
- テストは実装ファイルと 1:1 対応の `tests/test_*.py`
- **GSAS-II 依存**: `@pytest.mark.gsas` を付与 → `tests/conftest.py::pytest_collection_modifyitems` が未導入環境で自動 skip (マーカーは `pyproject.toml [tool.pytest.ini_options] markers` に定義済み)
- **web extra 依存**: モジュール冒頭で `pytest.importorskip("fastapi")` により未導入環境は全 skip
- **未導入経路の否定テスト** (例: 例外送出) はマーカー無し + `gsasii_available()` で分岐
- テストコマンド: `uv run pytest` / `uv run pytest --cov=tsumugin` / `uv run pytest -m gsas`

- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0010.md`, `docs/dev/context.md`, `pyproject.toml`, `tests/conftest.py`, `tests/test_gpx_export.py`, `tests/test_webui.py`

---

## 3. 関連実装 (統合対象の M1 成果物 — すべて実装済み)

### 公開 API の現状 (要更新の中心ファイル)
- `src/tsumugin/__init__.py`: **現状 M0 分のみ re-export** (`AICBackend`, `AnalysisResult`, `BICBackend`, `Hypothesis`, `LatticeParams`, `Ledger`, `PhaseInstance`, `Project`, `RankedHypothesis`, `RefinementBackend`, `RefinementMetrics`, `RefinementModel`, `RefinementReport`, `RefinementResult`, `SimulatedBackend`, `SnapshotStore`, `StagedRefinementEngine`, `analyze_single_pattern`, `rank`)。
  → **M1 分の追加が必要** (`HypothesisTreeSearch`, `SearchConfig`, `SearchResult`, `PhaseCandidate`, `export_gpx` 等)。`__all__` へも追記しソート維持。

### M1 モジュールの公開シンボル (サブパッケージ側は re-export 済み)
- `src/tsumugin/search/__init__.py` (`__all__`): `HypothesisTreeSearch`, `SearchConfig`, `SearchResult`, `PhaseCandidate`, `ClusterResult`, `MatchResult`, `UnmatchedPeakReport`, `Peak`, `find_peaks`, `match_score`, `unmatched_peaks`, `dynamic_threshold`, `jaccard_clusters`, `jenks_breaks`
- `src/tsumugin/export/__init__.py`: `export_gpx`
- `src/tsumugin/webui/__init__.py`: `create_app`, `serve` (遅延 import)

### 主要シグネチャ (E2E で直接使う)
- `HypothesisTreeSearch(backend, *, evidence=None, config=SearchConfig(), ledger=None, snapshots=None)`
  - `evidence=None` → 既定 `BICBackend()` (name="bic")
  - `.search(two_theta, intensity, candidates: Sequence[PhaseCandidate | PhaseInstance], *, weights=None) -> SearchResult`
    - candidates は `PhaseCandidate` か `PhaseInstance` の並び (PhaseInstance は内部で `PhaseCandidate(phase=...)` に正規化)
    - 候補ゼロでも例外化せず空 `SearchResult` へ縮退 (EDGE-001)
- `SearchConfig` (frozen dataclass, 主要既定値): `max_phases=5`, `r_improve_pct=2.0`, `match_tol_deg=0.15`, `min_peak_height_frac=0.05`, `prune_min_candidates=4`, `jaccard_threshold=0.85`, `explore_max_cycles=5`, `final_full_refine=True`, `max_final_refine=3`, `high_r_threshold=30.0`, `close_threshold=10.0`
- `SearchResult` (frozen dataclass): `ranked: tuple[RankedHypothesis, ...]`, `hypotheses: Mapping[str, Hypothesis]`, `good_cluster_ids`, `alternatives`, `unmatched: UnmatchedPeakReport`, `final_reports`, `ledger: Ledger`, `snapshots: SnapshotStore`, `warnings=()`
  - `.to_summary() -> dict`: `/api/result` スキーマ準拠の純 dict (json.dumps 可能)。キー: `ranked` (各行 id/rank/probability/close_competitor/rwp/gof/evidence/phases/parent_id/in_good_cluster), `unknown_phase_flag`, `unmatched_observed`, `extra_calculated`, `warnings`, `n_hypotheses`
- `export_gpx(path, phases: Sequence[PhaseInstance], two_theta, intensity, *, weights=None, wavelength=1.5406) -> str`
  - 戻り値 = 書き出した .gpx パス。GSAS-II 未導入時は書き出し前に副作用ゼロで `GSASUnavailableError` (`tsumugin.errors`)
- `create_app(result: SearchResult) -> FastAPI` / `serve(...)` (webui, read-only)

### M1 が土台にする M0 資産 (踏襲パターン)
- `src/tsumugin/pipeline.py::analyze_single_pattern` — 単一パターン多相精密化 (木探索版の構造母体)
- `src/tsumugin/refinement/staged.py::StagedRefinementEngine` — 段階解放 + ガード + revert
- `src/tsumugin/evidence/ranking.py::rank` — softmax 確率 + `close_competitor` (ΔBIC<10)
- `src/tsumugin/backends/simulated.py::SimulatedBackend` (GSAS 不要, `simulate` で Ycalc 生成) / `src/tsumugin/backends/gsasii.py::GSASIIBackend`, `gsasii_available`

- **参照元**: `src/tsumugin/__init__.py`, `src/tsumugin/search/{__init__,tree,peaks,matcher,pruning,clustering}.py`, `src/tsumugin/export/{__init__,gpx}.py`, `src/tsumugin/webui/{__init__,app}.py`, `src/tsumugin/pipeline.py`, `src/tsumugin/backends/{simulated,gsasii}.py`, `src/tsumugin/errors.py`

---

## 4. 設計文書

### データフロー (search)
候補正規化 → `find_peaks` (観測ピーク) → 各候補 simulate→`match_score` → Jaccard 縮約 (代替は `alternatives` に非破壊保持) → `dynamic_threshold` 枝刈り → best-first 木探索 (`backend.refine` 直呼び, scale+lattice, `max_cycles=explore_max_cycles`) → BIC 評価 → `rank` (softmax) → 後処理 (良好解抽出 / フル精密化 / 未マッチ集約) → `SearchResult`。全操作を単一 `ledger` に理由付き記録、`snapshots` を実体で返す。

### E2E テストの設計方針 (tests/test_m1_e2e.py 新規)
- **SimulatedBackend 経路 (マーカー無し)**: 合成 2 相データ (例: 立方 A+B を重ねた観測パターン) を作り、正しい候補と誤り候補を混ぜて `HypothesisTreeSearch.search`。検証: (1) `result.ranked[0]` が真の 2 相構成、(2) `result.to_summary()` が `json.dumps` 可能、(3) `result.ledger.verify()` が True。既存 `tests/test_tree_search.py` の観測グリッド `np.arange(15.0, 60.0, 0.02)` と `_phase(a, ref)` パターンが流用可能 (clustering 較正のため step 0.02 は必須)
- **@gsas 経路**: `@pytest.mark.gsas` で GSASIIBackend の `search` E2E が完走することと、`export_gpx` 連携 (書き出した .gpx が再オープン可能) を確認。未導入環境は conftest が自動 skip
- 決定論 (NFR-102) は `==` ビット同一、物理量は `pytest.approx`

### 更新対象ドキュメント
- `README.md`: 「使い方 (M1)」節を追加 (10-15 行、`HypothesisTreeSearch` の最小使用例)。アーキテクチャ表に `tsumugin.search` / `tsumugin.export` / `tsumugin.webui` 行を追加。M0 使用例 (L48-75) が書式の範
- `docs/dev/context.md`: Overview を M1 スコープへ、Project Structure に search/export/webui、Tech Stack に FastAPI/uvikorn (web extra)、Additional Notes の「M0 スコープ外」記述を更新
- `docs/tasks/m1-hypothesis-search/reports/verification.md`: `reports/` ディレクトリごと新規作成。M0 の `docs/dev/plans/m0-refinement-core/reports/verification.md` の構成 (サマリ / タスク別テスト内訳表 / 仕様適合の要点) を範とする

- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0010.md`, `docs/spec/m1-hypothesis-search/note.md`, `src/tsumugin/search/tree.py`, `README.md`, `docs/dev/context.md`, `docs/dev/plans/m0-refinement-core/reports/verification.md`

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`
- **マーカー**: `gsas` (定義済み)。GSAS-II 未導入時は `tests/conftest.py` が自動 skip
- **テストディレクトリ / 命名**: `tests/test_*.py`、実装ファイルと 1:1。**本タスクで新規追加**: `tests/test_m1_e2e.py`
- **既存参照テスト (書式の範)**:
  - `tests/test_tree_search.py` — 木探索の 20 ケース、共通合成データ (GRID / `_phase` / `_refs`)、FakeBackend / RecordingSpyBackend スタブ
  - `tests/test_gpx_export.py` — `@pytest.mark.gsas` の書き出し検証 + 未導入経路の否定テスト (`gsasii_available()` 分岐)、`test_export_gpx_is_reexported` (公開面確認の範)
  - `tests/test_webui.py` — `pytest.importorskip("fastapi")` + `TestClient`、`to_summary` の JSON 化・スキーマ検証
- **モック/スタブ**: RefinementBackend Protocol 準拠のスタブ (FakeBackend で Rwp/chi2 を厳密制御、RecordingSpyBackend で呼び出し契約観測)
- **公開 API の再エクスポート検証パターン**: `test_export_gpx_is_reexported` 同様に `from tsumugin import HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate, export_gpx` が成功することをテスト化するとよい

- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_tree_search.py`, `tests/test_gpx_export.py`, `tests/test_webui.py`

---

## 6. 注意事項

### 技術的制約
- 木探索は探索モード精密化 (保守的・低コスト) + BIC 即時評価に限定。nested 再裁定は M5 (M1 は close_competitor フラグ提示まで)
- E2E の観測グリッドは範囲を絞って実行時間を抑える (`15–60°` / step 0.02)。step は clustering の bin 較正上変更しない
- `.gpx` (FR-505) は GSAS-II 依存。GSAS-II 起動時の `~/.GSASII/config.ini` 読込警告 (cp932) は無害

### 非破壊 / セキュリティ制約
- **P2 / NFR-101**: 破壊的 API を追加しない。Ledger/Snapshot に削除・上書きメソッド禁止
- **NFR-105**: ledger は追記専用 + ハッシュチェーン。`verify()` が常に True (E2E でも assert 推奨)
- 枝刈り・仮説降格・ガード発動はすべて理由付きで ledger 記録

### 再現性 / データ制約
- **NFR-102**: 乱数種固定でビット同一。決定論的順序 (canonical JSON ソート) を維持
- chi2/rwp のセマンティクスはバックエンド間統一 (BIC 比較の一貫性)。精密化失敗は例外でなく chi2=inf に変換
- **依存導入の落とし穴**: `uv sync --extra gsas --extra web` を使う。プレーン `uv sync` は gsas extra が外れるため禁止

### 本タスク運用上の注意
- git commit しない / 質問しない
- 全パスは相対パスで記載すること (本ノートも遵守)

- **参照元**: `docs/spec/m1-hypothesis-search/note.md`, `CLAUDE.md`, `docs/tasks/m1-hypothesis-search/TASK-0010.md`

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
