# TASK-0010 公開 API 統合 + E2E + ドキュメント — TDD 要件定義書

- **機能名**: 公開 API 統合 + E2E テスト + ドキュメント (M1 総仕上げ統合)
- **タスクID**: TASK-0010
- **要件名**: m1-hypothesis-search
- **実装ファイル**:
  - `src/tsumugin/__init__.py` (M1 公開シンボルの re-export 追加 + `__all__` 拡張)
  - `README.md` (M1 使用例 + アーキテクチャ表更新)
  - `docs/dev/context.md` (Overview / Project Structure / Tech Stack / Additional Notes 更新)
  - `docs/tasks/m1-hypothesis-search/reports/verification.md` (新規、`reports/` ごと作成)
- **テストファイル**: `tests/test_m1_e2e.py` (新規)
- **タスクタイプ**: TDD (Red(E2E) → Green → Refactor → verify-complete) / 推定 3h / Phase 4 相互運用・UI・統合
- **信頼性サマリー**: 🔵 6 / 🟡 1 / 🔴 なし — 品質評価: 高品質

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M1 で実装済みの成果物 (TASK-0001〜0009) を**公開面へ配線**し、E2E テストとドキュメントで
  裏取りする総仕上げ統合タスク。具体的には (1) `src/tsumugin/__init__.py` に M1 の公開シンボル
  (`HypothesisTreeSearch`, `SearchConfig`, `SearchResult`, `PhaseCandidate`, `export_gpx` 等) を re-export、
  (2) 合成 2 相データの E2E (search → ranking → summary JSON 化、`@gsas` 経路で GSASIIBackend search + gpx 連携)、
  (3) README / `docs/dev/context.md` の更新、(4) 検証レポート作成。(TASK-0010.md 完了条件 6 項目)
- 🔵 **解決する問題**: サブパッケージ (`tsumugin.search` / `tsumugin.export` / `tsumugin.webui`) 側では
  re-export 済みだが、トップレベル `from tsumugin import HypothesisTreeSearch, ...` が未対応で、利用者が M1 API に
  到達できない。本タスクでトップレベル公開面を M0 と同格に整え、E2E で「探索木 → ランキング → summary/gpx」の
  一連の連携が破綻なく動くことを保証し、ドキュメントで利用方法と検証結果を明文化する。
- 🔵 **想定ユーザー**: 粉末 XRD の相同定を行う研究者 (公開 API の直接利用者)、および M1 PR のレビュア・後続
  マイルストーン (M2+) の実装者。本タスクの直接の下流は「M1 PR」(後続タスクなし)。
- 🔵 **システム内での位置づけ**: M1 の**最終統合レイヤ**。新規のドメインロジックは実装せず、既に実装・検証済みの
  各コンポーネント (TASK-0002〜0009) を横断的に配線・結線検証する。M0 の統合タスク (010/011) のパターンを踏襲する
  (信頼性根拠)。破壊的変更・新規アルゴリズムは持ち込まない (統合と検証に限定)。
- **本タスクのスコープ境界**:
  - **スコープ内**: `__init__.py` の re-export + `__all__` 追記 (ソート維持)、`tests/test_m1_e2e.py` の新規 E2E、
    README の M1 節 + アーキテクチャ表更新、`docs/dev/context.md` 更新、`reports/verification.md` 新規作成。
  - **スコープ外**: 各コンポーネントのロジック変更 (TASK-0002〜0009 で完了)、REST API / MCP (M2+/M4)、
    nested 再裁定 (M5)、永続化 DB (M2+)、Web UI の機能拡張 (TASK-0009 の read-only 版で確定)。
- **参照したEARS要件**: REQ-001 (探索木 → RankedHypothesis)、REQ-006 (.gpx)、REQ-007 (Web UI)、REQ-402/403 (ledger/決定論)
- **参照した設計文書**: `docs/tasks/m1-hypothesis-search/TASK-0010.md` (完了条件 6 項目)、`overview.md` (Phase 4)、
  `note.md` §3-5 (公開シンボル一覧・E2E 設計方針)

---

## 2. 入力・出力の仕様（公開 API / E2E の型契約ベース）

### 2.1 公開 API 統合 (`src/tsumugin/__init__.py`) 🔵

- **追加 re-export シンボル** (サブパッケージ側は re-export 済み、トップレベルへ昇格):

  | シンボル | 由来モジュール | 種別 |
  |----------|----------------|------|
  | `HypothesisTreeSearch` | `tsumugin.search` (`.tree`) | クラス (探索エンジン) |
  | `SearchConfig` | `tsumugin.search` | frozen dataclass (探索設定) |
  | `SearchResult` | `tsumugin.search` | frozen dataclass (探索結果) |
  | `PhaseCandidate` | `tsumugin.search` | dataclass (候補相) |
  | `export_gpx` | `tsumugin.export` | 関数 (.gpx 書き出し) |

  - **最小必須**: 完了条件① / TASK-0010.md タスク概要が明示する
    `HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate, export_gpx`。
  - **推奨追加 (実装時に確定)**: `tsumugin.search.__all__` の残り (`ClusterResult`, `MatchResult`,
    `UnmatchedPeakReport`, `Peak`, `find_peaks`, `match_score`, `unmatched_peaks`, `dynamic_threshold`,
    `jaccard_clusters`, `jenks_breaks`) や webui の `create_app` / `serve` の昇格可否は、M0 の公開粒度
    (中核クラス + 主要関数を昇格) に合わせて Green で確定する。**推奨案**: 完了条件①が要求する 5 シンボル +
    `UnmatchedPeakReport` (summary/結果解釈に必要) を昇格し、下位ヘルパ (find_peaks 等) は
    サブパッケージ経由アクセスに留める。
- **`__all__` の扱い**: 追加シンボルを `__all__` へ追記し、**アルファベット昇順ソートを維持** (既存 `__init__.py` の慣習)。
- **契約 (D6 遅延 import)**: `tsumugin.webui` を昇格する場合も、FastAPI 未導入環境で `import tsumugin` が
  失敗してはならない (webui は app 内で遅延 import する契約)。`export_gpx` も import 時点では GSAS-II 不要。

### 2.2 E2E テスト (`tests/test_m1_e2e.py`) の入出力契約 🔵

- **入力 (合成データ)**: `tests/test_tree_search.py` の観測グリッド `np.arange(15.0, 60.0, 0.02)` と `_phase(a, ref)`
  パターンを流用し、立方 2 相 (A + B) を重ねた観測パターンを生成。候補には真の相 (A, B) + 誤り相を混ぜる。
  **step 0.02 は clustering の bin 較正上、変更不可** (note §6)。
- **主要シグネチャ (E2E で直接使用)** (note §3):
  - `HypothesisTreeSearch(backend, *, evidence=None, config=SearchConfig(), ledger=None, snapshots=None)`
    - `evidence=None` → 既定 `BICBackend()` (name="bic")
  - `.search(two_theta, intensity, candidates: Sequence[PhaseCandidate | PhaseInstance], *, weights=None) -> SearchResult`
    - `candidates` は `PhaseCandidate` か `PhaseInstance` の並び (`PhaseInstance` は内部で `PhaseCandidate(phase=...)` に正規化)
  - `SearchResult.to_summary() -> dict`: `/api/result` スキーマ準拠の純 dict (`json.dumps` 可能)。
    キー: `ranked` (各行 id/rank/probability/close_competitor/rwp/gof/evidence/phases/parent_id/in_good_cluster),
    `unknown_phase_flag`, `unmatched_observed`, `extra_calculated`, `warnings`, `n_hypotheses`
  - `export_gpx(path, phases, two_theta, intensity, *, weights=None, wavelength=1.5406) -> str` (@gsas 経路)
- **検証する出力 (assert)**:
  - `result.ranked[0]` が真の 2 相構成 {A,B} (完了条件②)
  - `result.to_summary()` が `json.dumps` 可能 (完了条件②)
  - `result.ledger.verify()` が True (NFR-201 / TC-008-01)
  - (`@gsas`) GSASIIBackend の `search` E2E が完走 (完了条件③)、`export_gpx` の書き出した .gpx が再オープン可能
- **参照したREQ**: REQ-001 (ランキング)、REQ-403 (決定論)、REQ-402/NFR-201 (ledger.verify)
- **参照した設計文書**: `api-endpoints.md` GET /api/result (to_summary スキーマ)、`note.md` §3.3-§5、
  `acceptance-criteria.md` TC-001-01 / TC-008-01

### 2.3 ドキュメント成果物の出力 🔵/🟡

- 🔵 `README.md`: 「使い方 (M1)」節 (10-15 行、`HypothesisTreeSearch` の最小使用例)。アーキテクチャ表に
  `tsumugin.search` / `tsumugin.export` / `tsumugin.webui` の行を追加。既存 M0 使用例 (L48-75) が書式の範。
- 🔵 `docs/dev/context.md`: Overview を M1 スコープへ、Project Structure に search/export/webui、Tech Stack に
  FastAPI/uvicorn (web extra)、Additional Notes の「M0 スコープ外」記述を更新。
- 🟡 `docs/tasks/m1-hypothesis-search/reports/verification.md`: `reports/` ディレクトリごと新規作成。M0 の
  `docs/dev/plans/m0-refinement-core/reports/verification.md` の構成 (サマリ / タスク別テスト内訳表 / 仕様適合の要点) を範とする。
  🟡 の理由: `reports/` が未作成で、構成は M0 レポートからの妥当な踏襲 (完了条件⑥が 🟡)。

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

### 3.1 品質ゲート (完了条件④ / CLAUDE.md 品質基準) 🔵

- **全テスト green**: 既存全テスト (M0 + M1 TASK-0002〜0009) + 新規 `tests/test_m1_e2e.py` が green。
- **カバレッジ 90% 以上**: `uv run pytest --cov=tsumugin` で 90% 以上 (M0 実績 95%)。
- **ruff clean**: `uvx ruff check src tests` (line-length 100, target py312) がクリーン。
- **依存導入**: `uv sync --extra gsas --extra web` を使用 (プレーン `uv sync` は gsas extra が外れるため禁止 / note §6)。

### 3.2 非破壊性 (P2 / NFR-101 / REQ-402) 🔵

- 統合作業で**破壊的 API を追加しない**。Ledger/Snapshot に削除・上書きメソッドを追加してはならない。
- re-export は既存シンボルの公開面追加のみ。既存公開シンボルの削除・改名・シグネチャ変更をしない (後方互換維持)。
- E2E では `result.ledger.verify()` が True であることを assert する (NFR-105 / note §6)。

### 3.3 決定論・再現性 (NFR-102 / REQ-403) 🔵

- E2E は同一入力で 2 回実行しビット同一を検証可能な構成にする (決定論は `==` でビット同一、物理量は `pytest.approx`)。
- canonical JSON ソート順を維持 (summary の決定論)。乱数を使う箇所は種固定。

### 3.4 遅延 import 契約 (D6) 🔵

- `tsumugin.webui` を昇格する場合でも、FastAPI 未導入環境で `import tsumugin` が失敗しないこと
  (webui は app 内で遅延 import)。`export_gpx` の import も GSAS-II 非依存 (実行時に初めて判定)。
- E2E の web/gsas 依存テストは、モジュール冒頭 `pytest.importorskip("fastapi")` / `@pytest.mark.gsas` で
  未導入環境を自動 skip する (note §5)。

### 3.5 テスト運用制約 (note §2/§5) 🔵

- `tests/test_m1_e2e.py` を新規追加。SimulatedBackend 経路は**マーカー無し** (どの環境でも実行)。
  GSASIIBackend + export_gpx 経路は `@pytest.mark.gsas` (未導入は `tests/conftest.py` が自動 skip)。
- E2E の観測グリッドは範囲を絞り実行時間を抑える (`15–60°` / step 0.02)。**step 0.02 は clustering の bin 較正上変更しない**。
- モック/スタブ: E2E は実バックエンド (SimulatedBackend / GSASIIBackend) を使う (統合の裏取りが目的のため、
  FakeBackend 等の単体スタブは使わない)。公開面確認は `from tsumugin import ...` の成功をテスト化する
  (`test_export_gpx_is_reexported` パターンの範)。

### 3.6 コーディング / 品質制約 (CLAUDE.md) 🔵

- Python >= 3.12。型注釈必須 (`any` 回避)、キーワード専用引数は `*` 区切り、snake_case / PascalCase / UPPER_SNAKE。
- docstring は日本語可、FR/NFR/REQ/TC 番号 + 🔵🟡 信頼性レベルを紐づける慣習。
- 全ファイルパスは相対パス記載 (本タスク運用ルール / note §6)。

### 3.7 本タスク運用制約 (呼び出し側指示 / note §2) 🔵

- **git commit しない** / **質問しない** (推奨案で確定する)。
- 実装エージェント (サブ含む) は Opus。

- **参照したNFR/REQ**: NFR-101/102/105/201 (非破壊/決定論/ledger)、REQ-402/403、完了条件④
- **参照した設計文書**: `CLAUDE.md` (品質基準/不変条件)、`note.md` §2/§6、`pyproject.toml`、`tests/conftest.py`

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本パターン — 公開 API 再エクスポート確認 (完了条件①) 🔵 マーカー無し

- `from tsumugin import HypothesisTreeSearch, SearchConfig, SearchResult, PhaseCandidate, export_gpx` が
  例外なく成功する。`test_export_gpx_is_reexported` (TASK-0008) と同じ公開面確認パターン。
- 各シンボルが期待の型 (クラス / dataclass / 関数) であることを確認。`tsumugin.__all__` に含まれることも確認可。

### 4.2 基本パターン — SimulatedBackend E2E (完了条件② / TC-001-01) 🔵 マーカー無し

- 合成 2 相データ (立方 A+B) + 真の候補 + 誤り候補 → `HypothesisTreeSearch(SimulatedBackend()).search(tt, y, candidates)` →
  (1) `result.ranked[0]` が真の {A,B} 構成、(2) `json.dumps(result.to_summary())` が成功、
  (3) `result.ledger.verify()` が True。

### 4.3 @gsas E2E — GSASIIBackend search + gpx 連携 (完了条件③ / TC-006-01) 🔵 @gsas

- `@pytest.mark.gsas` で `HypothesisTreeSearch(GSASIIBackend()).search(...)` が完走 →
  `export_gpx(tmp_path/"m1.gpx", phases, tt, y)` の書き出した .gpx が `G2sc.G2Project(<path>)` で再オープン可能。
  未導入環境は conftest が自動 skip。

### 4.4 データフロー (search / note §4) 🔵

- 候補正規化 → `find_peaks` (観測ピーク) → 各候補 simulate→`match_score` → Jaccard 縮約 (代替は `alternatives` 非破壊保持) →
  `dynamic_threshold` 枝刈り → best-first 木探索 (`backend.refine` 直呼び) → BIC 評価 → `rank` (softmax) →
  後処理 (良好解抽出 / フル精密化 / 未マッチ集約) → `SearchResult`。全操作を単一 `ledger` に理由付き記録。
  E2E はこの一連が破綻なく最終 `SearchResult` に至ることを検証する。

### 4.5 エッジ / 整合ケース

- 🔵 **候補ゼロ縮退 (EDGE-001)**: 候補ゼロでも例外化せず空 `SearchResult` へ縮退することを E2E でも軽く確認可 (回帰防止)。
- 🔵 **未知相フラグ (TC-005-01)**: 「候補にない相」を混ぜたデータで `unknown_phase_flag=True`、
  `unmatched_observed` が位置・強度付きで報告されることを summary で確認可 (E2E の追加 assert 候補、推奨採用)。
- 🔵 **決定論 (TC-001-05 / REQ-403)**: 2 回実行でランキング・確率がビット同一 (E2E に含めることを推奨)。
- 🟡 **web 経路 (TC-007 系)**: `create_app(result)` を昇格した場合の TestClient E2E は TASK-0009 で
  検証済みのため本タスクでは必須ではない (重複回避)。E2E に含めるかは実装時に確定 (**推奨: 含めない**、
  webui は TASK-0009 の `tests/test_webui.py` に委譲)。

- **参照したEDGE**: EDGE-001 (候補ゼロ)、EDGE-002 (全高 R → 未知相フラグ)
- **参照した設計文書**: `note.md` §4 (データフロー) / §5 (テスト設計)、`acceptance-criteria.md` TC-001/005/006/008 系、
  `tests/test_tree_search.py` (合成データの範)、`tests/test_gpx_export.py` (@gsas + 再エクスポート確認の範)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 「研究者が `from tsumugin import HypothesisTreeSearch` で相同定を実行し、
  結果を summary/gpx で取り出す」(M1 統合の総括)
- **参照した機能要件**: REQ-001 (探索木 → RankedHypothesis)、REQ-005 (未マッチ/未知相)、REQ-006 (.gpx)、
  REQ-007 (Web UI、本タスクでは import 経路確認まで)
- **参照した制約要件**: REQ-402 (全操作 ledger 記録・非破壊)、REQ-403 (決定論ビット同一)
- **参照した非機能要件**: NFR-101/P2 (非破壊)、NFR-102/202 (再現性)、NFR-105/201 (ledger 追記 + verify)
- **参照した Edge ケース**: EDGE-001 (候補ゼロ縮退)、EDGE-002 (全高 R → 未知相フラグ)
- **参照した受け入れ基準** (acceptance-criteria.md):
  - TC-001-01 🔵 — 2 相合成データ・複数候補で {A,B} が 1 位 (E2E 中核)
  - TC-001-05 🔵 — 決定論: 2 回実行でビット同一 (E2E 推奨採用)
  - TC-005-01 🔵 — 未知相を混ぜたデータで unknown_phase_flag=True + 未マッチ報告 (E2E 追加 assert)
  - TC-006-01/02 🔵 (@gsas) — export_gpx の .gpx が再オープン可能・観測データ含む
  - TC-008-01 🔵 — 探索実行後 `ledger.verify()` が True
  - 完了条件①〜⑥ (TASK-0010.md L19-24)
- **参照した設計文書**:
  - **アーキテクチャ**: `overview.md` (Phase 4 相互運用・UI・統合)、`note.md` §1 (レイヤ分離 + Protocol 境界)
  - **データフロー**: `note.md` §4 (search データフロー)、`docs/spec/m1-hypothesis-search/note.md` (M0→M1 の接続)
  - **型定義**: `note.md` §3 (`HypothesisTreeSearch` / `SearchConfig` / `SearchResult.to_summary` の契約)、
    `src/tsumugin/search/__init__.py` / `export/__init__.py` / `webui/__init__.py` の `__all__`
  - **データベース**: なし (M1 はインメモリ Ledger/Snapshot、永続 DB は M2+)
  - **API 仕様**: `api-endpoints.md` GET /api/result (`to_summary` スキーマ = E2E の JSON 検証対象)
- **前提実装 (統合対象 — すべて実装済み)**:
  - `src/tsumugin/__init__.py` — 現状 M0 分のみ re-export (要 M1 追加)
  - `src/tsumugin/search/{__init__,tree,peaks,matcher,pruning,clustering}.py` — `HypothesisTreeSearch` 等 (re-export 済み)
  - `src/tsumugin/export/{__init__,gpx}.py` — `export_gpx` (re-export 済み)
  - `src/tsumugin/webui/{__init__,app}.py` — `create_app` / `serve` (遅延 import)
  - `src/tsumugin/backends/{simulated,gsasii}.py` — E2E で使う実バックエンド、`gsasii_available`
  - `tests/test_tree_search.py` / `test_gpx_export.py` / `test_webui.py` — 合成データ・書式の範
  - `docs/dev/plans/m0-refinement-core/reports/verification.md` — 検証レポートの構成の範

---

## 6. 品質判定

```
✅ 高品質:
- 要件の曖昧さ: なし (公開シンボルの最小必須集合を確定、推奨追加分のみ「実装時に確定」と明示)
- 入出力定義: 完全 (re-export シンボル表・E2E の入出力/assert・ドキュメント成果物を特定)
- 制約条件: 明確 (品質ゲート/非破壊/決定論/遅延 import/テスト運用を条番号付きで規定)
- 実装可能性: 確実 (統合対象は全て実装済み、主要シグネチャ・to_summary スキーマ・合成データの範が特定済み)
- 信頼性レベル: 🔵 6 / 🟡 1 / 🔴 0 — 🔵 優勢
```

- **要改善点 (実装時に TDD で確定すべき事項)**:
  1. 🔵 トップレベルへ昇格する公開シンボルの最終集合 (**推奨**: 完了条件①の 5 シンボル + `UnmatchedPeakReport`。
     下位ヘルパ・webui はサブパッケージ経由に留める) — Green で確定
  2. 🔵 E2E に含める assert の粒度 (**推奨**: ranked[0] 一致 + summary JSON 化 + ledger.verify + 決定論 +
     未知相フラグ。web 経路は TASK-0009 に委譲し重複回避) — Red で確定
  3. 🟡 `reports/verification.md` の詳細構成 (**推奨**: M0 レポートの「サマリ / タスク別テスト内訳表 / 仕様適合の要点」を踏襲)

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-testcases m1-hypothesis-search TASK-0010` でテストケースの洗い出しを行います。
