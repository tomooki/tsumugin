# TASK-0035 TDD 要件定義書 — M3 公開 API 統合 + E2E + ドキュメント

**機能名**: operando-integration-e2e (M3 公開 API 統合 + E2E + ドキュメント)
**タスクID**: TASK-0035 / **要件名**: m3-operando / **タイプ**: TDD (最終統合タスク) / **推定 4h**
**フェーズ**: Phase 5 / **信頼性サマリー**: 🔵 5/5 (M2 統合タスク TASK-0022 の踏襲)

> 本書のすべてのファイルパスはプロジェクトルートからの相対パス。信頼性レベル 🔵 青 / 🟡 黄 / 🔴 赤。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M3 (operando) で追加した各層 (multistart / absorption / echem / cell_phases /
  discrimination / segmentation / hysteresis / output / model.cell) の公開シンボルを、トップレベル
  `tsumugin` パッケージ (`src/tsumugin/__init__.py`) へ **非破壊 re-export** する。加えて、公開 API のみで
  operando 一気通貫パイプラインを結線する **E2E テスト** を追加し、README M3 使用例・`docs/dev/context.md`・
  検証レポートを整備する。**新規解析ロジックは実装しない**（TASK-0023〜0034 で完了済み）。配線・結線検証・
  ドキュメントに徹する統合タスク。
- 🔵 **解決する問題**: M3 の機能はサブパッケージ (`tsumugin.operando` / `tsumugin.multistart` /
  `tsumugin.absorption`) には配線済みだが、トップレベル `tsumugin` からは未到達 (`from tsumugin import
  MultistartEngine` が ImportError)。利用者が単一 import で M3 API へ到達できず、また operando の縦串
  (echem→固定相→分割→判別→結合出力→ledger) が公開 API 経由で一度も通し検証されていない。
- 🔵 **想定ユーザー**: Tsumugin を `import tsumugin` で使う解析スクリプト作成者・下流連携 (WebUI / MCP 予定)。
  および M3 の後方互換・結線健全性を保証したい開発者。
- 🔵 **システム内での位置づけ**: 公開面 (パッケージ `__init__`) の配線層 + 統合テスト層。M0/M1/M2 で確立した
  「サブパッケージ実体を `__all__` 昇順で re-export し、E2E で公開 API 経由の縦串を検証する」統合タスクの M3 版。
- **参照した EARS 要件**: REQ-404 (後方互換), NFR-001 (性能), AC TC-209-01〜03
- **参照した設計文書**: `docs/tasks/m3-operando/TASK-0035.md` (L10-27),
  `docs/design/m3-operando/dataflow.md` (operando 縦串), `docs/design/m3-operando/interfaces.py` (公開契約),
  `docs/implements/m3-operando/TASK-0035/note.md` §0

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

本タスクの成果物は「配線 (re-export)」「E2E テスト」「ドキュメント」の 3 種。入出力はそれぞれの成果物単位で定義する。

### 2.1 公開 API 統合（`src/tsumugin/__init__.py`）🔵

- **入力**: 各サブパッケージの実装済み公開シンボル (実体)。
- **出力**: トップレベル `tsumugin` から解決可能な M3 シンボル群 + 昇順維持の `__all__`。
- **昇格対象シンボル（推奨案 = M3 公開面全体）**:
  - 🔵 multistart: `MultistartEngine`, `MultistartConfig`, `MultistartResult`, `BasinInfo`,
    `PerturbationSpec`, `cluster_basins`, `generate_starts`
  - 🔵 absorption: `AbsorptionConfig`, `transmission_factor`
  - 🔵 operando: `read_echem_csv`, `EchemData`, `EchemLoader`, `BiologicMprLoader`, `CELL_PHASE_PRESETS`,
    `FixedPhaseSpec`, `fixed_free_suffixes`, `DiscriminationConfig`, `DiscriminationResult`,
    `discriminate_interval`, `SegmentationConfig`, `SegmentationResult`, `segment_series`,
    `combined_csv`, `transition_point`, `TransitionPoint`, `BranchComparison`, `split_branches`,
    `branch_differences`
  - 🔵 model.cell: `CellConfig`, `CellLayer`, `BeamConfig`, `MuCalculator`, `XraylibMuCalculator`
- **入出力関係 (契約)**:
  - 🔵 `X is tsumugin.<subpkg>.X` (別実装・コピーでなく同一実体)。
  - 🔵 `list(tsumugin.__all__) == sorted(tsumugin.__all__)` (昇順維持)。
  - 🔵 既存 M0/M1/M2 シンボル (現行 `__all__` L65-118 の全 54 件) は 1 つも削除・改名しない (REQ-404)。
  - 🔵 `for name in tsumugin.__all__: hasattr(tsumugin, name)` (`__all__` と実属性の乖離なし)。
- **参照した EARS 要件**: REQ-404 / **参照した設計文書**: `docs/tasks/m3-operando/TASK-0035.md` L10-14,
  `src/tsumugin/__init__.py`, 各サブパッケージ `__init__.py`

### 2.2 E2E テスト（`tests/test_operando_e2e.py`）🔵

- **入力 (合成データ)**: `SimulatedBackend(peak_fwhm=0.2)` 由来の `FrameSeries` (二相反応系列 + 固定相重畳)、
  `tmp_path` に書いた echem 小 CSV、`CELL_PHASE_PRESETS["Al"]` (固定相)、共有 `Ledger`。
- **出力 (検証対象)**: `SegmentationResult.boundaries`、区間ごとの `DiscriminationResult.verdict`、
  `combined_csv` の生成 CSV パス、`ledger.verify() is True`。
- **TC-209-01 一気通貫のデータフロー (公開 API のみ)**:
  1. 🔵 `echem = read_echem_csv(path, column_map={"frame":..,"voltage":..,"capacity":..}, capacity_to_x=(slope,intercept))`
  2. 🔵 `fixed = CELL_PHASE_PRESETS["Al"]` を `fixed_phases=(fixed,)` として付与
  3. 🔵 `seg = segment_series(backend, series, initial_phases, fixed_phases=(fixed,), ledger=ledger)` → `seg.boundaries`
  4. 🔵 各区間 `(start, end)` へ `disc = discriminate_interval(backend, series, (start,end), initial_phases, fixed_phases=(fixed,), config=DiscriminationConfig(multistart=MultistartConfig(n_starts=N)), ledger=ledger, queue=queue)` → `disc.verdict ∈ {"solid_solution","two_phase","undecided"}`
  5. 🟡 `combined_csv(trajectory, echem, path)` (trajectory の入手経路は §4/設計判断②で確定)
  6. 🔵 `ledger.verify() is True` かつ `len(ledger.entries) > 0`
- **TC-209-02 (@gsas)**: `MultistartEngine(GSASIIBackend(), config=MultistartConfig(n_starts=4)).run(phases, two_theta, intensity)`
  → `MultistartResult` (basins 非空・完走)。🔵
- **TC-209-03 (性能)**: `discriminate_interval` 1 区間 (N=8) の経過時間 < 30 秒。🟡
- **配線検証テスト**: M3 シンボルが `from tsumugin import ...` で解決 + `__all__` 昇順包含 + `is` 同一実体。🔵
- **参照した EARS 要件**: AC TC-209-01〜03, NFR-001 / **参照した設計文書**: `tests/test_m2_e2e.py` (統合 E2E 先例),
  `docs/design/m3-operando/dataflow.md`

### 2.3 ドキュメント 🔵

- **README.md**: 「使い方 (M3): operando 解析」節を追加 (M2 節 L116-161 と同型・使用例コード付き)。出力 = 追記後 README。
- **docs/dev/context.md**: 「M3 実装済み」1 行追記。出力 = 追記後 context.md。
- **docs/tasks/m3-operando/reports/verification.md**: 新規作成 (全テスト green・カバレッジ・ruff の結果)。
- **参照した設計文書**: `README.md` (L116-180), `docs/dev/context.md`, `docs/tasks/m3-operando/TASK-0035.md` L14

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🟡 **パフォーマンス (NFR-001)**: 判別 1 区間 (N=8) が 30 秒以内 (TC-209-03)。粗グリッド (step 0.05) + 小フレーム数
  (n≈8) + N=8 で担保。CI 変動を見て閾値マージンを取る (M2 の 100 フレーム 60 秒 smoke 流儀)。
- 🔵 **後方互換 (REQ-404)**: `__init__.py` は re-export の追記のみ。既存 M0/M1/M2 公開シンボルを削除・改名しない。
  `tests/test_m1_e2e.py` / `tests/test_m2_e2e.py` の `__all__` 昇順・非削除検証が green を維持すること。
- 🔵 **非破壊性 (P2 / NFR-101)**: 既存モジュールのロジック・シグネチャを変えない。破壊 API を足さない。
  E2E は共有 `Ledger` に追記のみ (削除・上書きしない)。
- 🔵 **監査整合 (NFR-105)**: 一気通貫の全操作を 1 本の追記専用ハッシュチェーン (共有 Ledger) に集約し
  `verify()` が True。空 ledger の自明 True を避けるため `len(entries) > 0` も確認。
- 🔵 **再現性 (NFR-102)**: E2E は乱数不使用。2 回実行で `verdict` / `boundaries` / CSV バイト列が `==` 一致。
  マルチスタートも `n_starts` 決定論 (seed 不使用)。
- 🔵 **numpy のみ (REQ-403)**: 合成データ生成は numpy + SimulatedBackend。pandas 等を持ち込まない。CSV は stdlib csv。
- 🔵 **アーキテクチャ制約**: re-export は同一実体 (`is`)。サブパッケージの `__all__` は既に全公開面を列挙済みで無改変流用可。
- 🔵 **GSAS-II 制約**: TC-209-02 のみ `@pytest.mark.gsas`。`tests/conftest.py` が未導入環境で自動 skip。
- 🔵 **カバレッジ / Lint**: `uv run pytest --cov=tsumugin` で 90% 以上、`uvx ruff check src tests` clean (line-length 100)。
- **参照した EARS 要件**: NFR-001, NFR-102, NFR-105, REQ-403, REQ-404 / **参照した設計文書**: `CLAUDE.md` (不変条件 L40-77),
  `docs/spec/m3-operando/requirements.md`, `docs/spec/m3-operando/acceptance-criteria.md`

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 基本的な使用パターン 🔵
- **単一 import**: `from tsumugin import (MultistartEngine, MultistartConfig, CellConfig, AbsorptionConfig,
  read_echem_csv, EchemData, CELL_PHASE_PRESETS, discriminate_interval, segment_series, combined_csv, ...)`
  ですべての M3 API に到達できる。
- **operando 一気通貫 (dataflow.md の縦串)**: echem 同期 → セル固定相込み逐次解析 (segment/discriminate 内部の区間
  warm-start refine) → IC 区間分割 → 区間ごと FR-313 判別 (端点マルチスタート) → 結合出力 CSV → ledger verify。

### エッジケース / エラーケース 🔵🟡
- 🔵 **区間数 1 の縮退**: `boundaries` が空 (単一セグメント) の場合、区間 `(0, n-1)` 1 本を判別する。E2E は最小 1〜2 区間で足りる。
- 🔵 **判別の undecided**: 僅差/高 R で `verdict == "undecided"` かつ `escalations` 非空となっても E2E はブロックせず完走する
  (auto 確定しないが例外化しない)。
- 🟡 **combined_csv 用 Trajectory 不在**: `SequentialEngine` は `fixed_phases` 非対応のため、trajectory の入手経路を
  設計判断②で確定 (推奨: 固定相を初期相に含めた `SequentialEngine.run` の trajectory を使う / または端点相から手組み)。
- 🔵 **echem 欠損**: `read_echem_csv` の欠損列は `ValueError`、行不揃いは None + `UserWarning`。E2E は正常系 CSV を用意。
- 🔵 **@gsas skip**: GSAS-II 未導入環境では TC-209-02 が自動 skip され、他テストは green。

### データフロー
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md` (operando 縦串), `docs/implements/m3-operando/TASK-0035/note.md` §3・§6
- **参照した EARS 要件**: EDGE-002/005 (判別縮退・エスカレーション), REQ-404 (後方互換)

### ⚠️ 設計判断フラグ (tdd-testcases / tdd-red で確定)
1. 🟡 **昇格シンボルの範囲**: 推奨案 = M3 公開面全体 (§2.1) を昇順昇格 (M2 の全公開面昇格に一致)。
2. 🟡 **combined_csv 用 Trajectory の入手経路**: 推奨 = 固定相を初期相に含めた `SequentialEngine.run` の trajectory。
3. 🔵 **"逐次解析" の実体**: segment_series / discriminate_interval 内部の区間 warm-start refine (独立 SequentialEngine でない)。
4. 🔵 **区間 → 判別のループ索引規約**: `boundaries` から `[(0,b0),(b0,b1),...,(bk,n-1)]` (両端 inclusive)。
5. 🔵 **ledger 一本化**: segment/discriminate に同一 `Ledger` を明示注入し 1 本のチェーンへ集約。

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: operando 電池モードの多相・時系列自動解析 (M3 総仕上げ)
- **参照した機能要件**: FR-313 (固溶体 vs 二相判別), FR-314 (結合出力), FR-316 (区間分割), FR-230〜234 (マルチスタート),
  FR-312 (セル固定相), FR-317 (吸収補正), REQ-016 (CellConfig)
- **参照した非機能要件**: NFR-001 (性能 30 秒), NFR-102 (再現性), NFR-105 (ledger 追記+ハッシュチェーン),
  REQ-403 (numpy のみ), REQ-404 (後方互換)
- **参照したEdgeケース**: EDGE-002 (マルチスタート全滅縮退), EDGE-005 (両仮説高 R → エスカレーション)
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` TC-209-01 (一気通貫), TC-209-02 (@gsas N=4 smoke),
  TC-209-03 (性能), 統合 E2E サマリ 3 件 (L101)
- **参照した設計文書**:
  - **タスク定義**: `docs/tasks/m3-operando/TASK-0035.md` (公開シンボル / 完了条件 / TDD 手順)
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` (D2/D3/D4/D5/D9), `CLAUDE.md` (不変条件)
  - **データフロー**: `docs/design/m3-operando/dataflow.md` (operando 縦串)
  - **型定義 (公開契約)**: `docs/design/m3-operando/interfaces.py`, 各サブパッケージ実 API (note §3 で確認済み)
  - **統合先例**: `tests/test_m2_e2e.py`, `src/tsumugin/__init__.py` (現行 `__all__`)
  - **コンテキストノート**: `docs/implements/m3-operando/TASK-0035/note.md`

---

## 品質判定

✅ **高品質**:
- 要件の曖昧さ: なし (成果物 3 種の入出力・契約を具体化)
- 入出力定義: 完全 (昇格シンボル一覧・E2E データフロー・検証契約を明記)
- 制約条件: 明確 (NFR-001/102/105・REQ-403/404 を紐付け)
- 実装可能性: 確実 (依存 TASK-0023〜0034 完了・実 API 確認済み・M2 統合先例あり)
- 信頼性レベル: 🔵 が大半 (🟡 は性能閾値と combined_csv 経路の設計判断のみ)

**残る設計判断** (tdd-testcases / tdd-red で確定): 昇格シンボル範囲 / combined_csv 用 Trajectory 経路。いずれも推奨案を提示済み。
