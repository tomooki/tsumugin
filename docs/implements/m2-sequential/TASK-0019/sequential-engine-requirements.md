# TASK-0019 TDD要件定義 — SequentialEngine (オンライン逐次精密化 + 局所木探索)

**要件名**: m2-sequential / **タスクID**: TASK-0019 / **機能名 (英)**: sequential-engine
**対象実装**: `src/tsumugin/sequential/engine.py` (新規) / **テスト**: `tests/test_sequential_engine.py` (新規)
**作成日**: 2026-07-03 / **信頼性サマリー**: 完了条件 🔵 6 / 🟡 3 — 高品質

> 本書は TDD の要件整理。EARS 要件定義書 (`docs/spec/m2-sequential/requirements.md`) と設計文書
> (`docs/design/m2-sequential/interfaces.py` / `architecture.md` / `dataflow.md`)、開発ノート
> (`docs/implements/m2-sequential/TASK-0019/note.md`) を参照。全パスはプロジェクトルート相対。

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 時系列 (時間/温度軸) の粉末回折フレーム列 `FrameSeries` を先頭から
  **オンライン単一パス**で逐次 Rietveld 精密化し、相構成の変化点 (changepoint) でのみ多仮説木探索を
  局所起動して相構成を更新しながら、フレームごとの結果を `Trajectory` に組み立てるオーケストレーション本体。
- 🔵 **解決する問題**: 各フレームを独立にフル探索するのは計算的に非現実的。前フレームの解を warm start で
  引き継ぎ、changepoint でのみ探索を起動することで、決定論を保ちつつ実用的な計算量で時系列相同定を可能にする (P5)。
- 🟡 **想定ユーザー**: 昇温/経時その場測定 (in-situ / operando) の粉末回折データを解析する研究者・エンジニア、
  および上位の解析パイプライン (M3 以降)。
- 🔵 **システム内での位置づけ**: M0 (単発精密化) / M1 (多仮説木探索) の上に載る**時系列レイヤ**の中核エンジン。
  下位の `StagedRefinementEngine` / `HypothesisTreeSearch` / `detect_changepoint` / `LifecycleTracker` /
  `Trajectory` を束ねる。M2 Phase 3 のエンジン (最終選択エンジン FinalSelectionEngine は別タスク)。
- **参照した EARS 要件**: REQ-001, REQ-002, REQ-101, REQ-105 / FR-301, FR-302, FR-303, FR-304, FR-305, FR-306
- **参照した設計文書**: `docs/design/m2-sequential/architecture.md` (システム概要 / D1・D2・D3),
  `docs/design/m2-sequential/dataflow.md` (シーケンシャル解析の全体フロー)

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 コンストラクタ入力 `SequentialEngine.__init__` 🔵 (`docs/design/m2-sequential/interfaces.py` L237-249)

| 引数 | 型 | 既定 | 意味 | 信頼性 |
|---|---|---|---|---|
| `backend` | `RefinementBackend` (Protocol) | — | 精密化バックエンド (`refine`/`simulate`)。検証は `SimulatedBackend` | 🔵 |
| `candidates` | `Sequence[PhaseCandidate \| PhaseInstance]` | `()` | 局所木探索の候補プール (REQ-101) | 🔵 |
| `evidence` | `EvidenceBackend \| None` | `None`→`BICBackend` | evidence 評価器 (採択判定に使用) | 🔵 |
| `config` | `SequentialConfig` | `SequentialConfig()` | 逐次エンジン設定 | 🔵 |
| `ledger` | `Ledger \| None` | `None`→内部生成 | 追記専用台帳 (Persistent 版注入可, REQ-012) | 🔵 |
| `snapshots` | `SnapshotStore \| None` | `None`→内部生成 | スナップショットストア (Persistent 版注入可) | 🔵 |

### 2.2 `SequentialConfig` 🔵 (`interfaces.py` L211-221)

| フィールド | 型 | 既定 | 意味 | 信頼性 |
|---|---|---|---|---|
| `orchestration` | `Literal["independent","native"]` | `"independent"` | native は NotImplementedError (REQ-105) | 🔵 |
| `inherit` | `Literal["phases","lattice_only"]` | `"phases"` | warm start 継承対象 (FR-301) | 🔵 (選択肢は 🟡) |
| `seq_max_cycles` | `int` | `10` | 後続フレームの精密化サイクル (D2) | 🟡 |
| `first_frame_staged` | `bool` | `True` | 初回フレームの staged フル確立 (D2) | 🟡 |
| `changepoint` | `ChangepointConfig` | `ChangepointConfig()` | window=5, z_threshold=5.0, min_new_peaks=1 | 🔵 |
| `lifecycle` | `LifecycleConfig` | `LifecycleConfig()` | hysteresis=3, presence_wt_frac=1e-3 | 🔵 |
| `search` | `SearchConfig` | `SearchConfig()` | 局所木探索設定 (REQ-101) | 🔵 |

### 2.3 `run` 入力 🔵 (`interfaces.py` L251-253)

- `series: FrameSeries` — 共通 2θ グリッド + `(n_frames, n_points)` 強度行列 + 軸値 + channels (温度等)。
- `initial_phases: Sequence[PhaseInstance]` — frame 0 の初期相構成 (staged 確立の入力)。

### 2.4 出力 `SequentialResult` 🔵 (`interfaces.py` L224-234)

| フィールド | 型 | 意味 | 信頼性 |
|---|---|---|---|
| `trajectory` | `Trajectory` | フレーム順 `FrameRecord` 列 + `lifecycles` | 🔵 |
| `hypotheses` | `Mapping[str, Hypothesis]` | 採択構成の系譜 (`frame_range` 付き) | 🔵 |
| `search_results` | `Mapping[int, SearchResult]` | changepoint フレーム (key=frame_index) の局所探索結果 | 🔵 |
| `first_frame_report` | `RefinementReport \| None` | 初回フレームの staged 確立結果 (空 series は None) | 🟡 |
| `ledger` | `Ledger` | 全操作を理由付きで記録 (adopt/reject 含む) | 🔵 |
| `snapshots` | `SnapshotStore` | スナップショットストア実体 | 🔵 |
| `warnings` | `tuple[str, ...]` | 失敗フレーム・チャネル欠損等の警告 (既定 `()`) | 🔵 |

### 2.5 データフロー 🔵 (`docs/design/m2-sequential/dataflow.md` 全体フロー)

1. **frame 0**: `StagedRefinementEngine(backend, snapshots, ledger).run(initial_phases, two_theta, intensity[0])`
   → `first_frame_report`。現行相 = `report.final_phases`。
2. **frame i (1..N-1)**: warm start = 直近**成功**フレームの phases (inherit に従う) →
   `backend.refine(RefinementModel(phases, free={scale+lattice}, two_theta, intensity[i]), max_cycles=seq_max_cycles)`。
3. **フレーム指標**: Rwp / 格子 a/b/c フレーム間差分 / 新規未マッチピーク数を蓄積し
   `detect_changepoint(rwp_history, lattice_history, new_unmatched, config=cfg.changepoint)` を評価。
4. **changepoint 発火時のみ**: `HypothesisTreeSearch(backend, evidence, config=cfg.search, ledger, snapshots)
   .search(two_theta, intensity[i], candidates=現行相+候補プール)` を実行 → `search_results[i]` に格納。
5. **採択判定 (D3)**: 最良仮説 `ranked[0]` の相集合が現行と異なり、かつ **evidence 改善**時のみ採択
   (現行相を更新、ledger `adopt`)。非改善は現行維持 (ledger `reject`)。
6. **FrameRecord 確定** → `LifecycleTracker.observe(i, present_refs)`。
7. 全フレーム後: `finalize()` で lifecycle 確定 → `Trajectory` 組立。採択区間を `Hypothesis.frame_range` に格納。
- **参照した EARS 要件**: REQ-001 (逐次), REQ-002 (warm start), REQ-101 (局所探索), REQ-105 (native 未対応)
- **参照した設計文書**: `interfaces.py` (SequentialConfig/SequentialResult/SequentialEngine), `dataflow.md` (全体フロー)

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🟡 **パフォーマンス (NFR-001/REQ-403/FR-403)**: 後続フレームは direct refine (~7 パラメータ × ≤10 cycles)。
  合成 100 フレーム (changepoint なし) が **60 秒以内**を smoke テストで担保 (TC-108-03)。
- 🔵 **決定論 (NFR-102/REQ-402)**: 乱数不使用・安定ソート。ローリング統計は中央値/MAD。dict 反復順依存を作らない。
  同一入力 2 回で `SequentialResult` の全出力が**ビット同一** (`==`) (TC-101-04)。
- 🔵 **非有限を漏らさない (M1 教訓)**: 精密化失敗は例外化せず `chi2=inf` 結果として扱い、
  FrameRecord へは `rwp=None/chi2=None` で伝播、CSV/下流に `inf`/`nan` を漏らさない (EDGE-002)。
- 🔵 **後方互換 (REQ-404)**: model 拡張 (`PhaseInstance.lifecycle` / `Hypothesis.frame_range`) は末尾・既定 None 済み。
  既存 M0/M1 テスト (226 件) を無改変で維持。
- 🔵 **非破壊・追記専用ストア (P2/REQ-405)**: ledger/snapshots への操作は追記のみ。採択/棄却は理由付き記録で表現。
- 🔵 **依存最小**: コア依存 numpy のみ。GSAS-II 非依存 (@gsas は本タスク対象外の TC-108-02)。
- 🔵 **注入式 (REQ-012)**: ledger/snapshots は注入可能。`PersistentLedger`/`PersistentSnapshotStore` を注入して
  M2 経路が無改変で動くことを 1 本検証 (TC-106-06 相当)。
- 🔵 **native 未実装 (REQ-105/FR-302)**: `orchestration="native"` は `NotImplementedError`。
- **参照した EARS 要件**: NFR-001, NFR-102, REQ-402, REQ-403, REQ-404, REQ-405, REQ-012, REQ-105
- **参照した設計文書**: `architecture.md` (非機能要件の実現方法 / 技術的制約 / D2), `dataflow.md` (エラーハンドリングフロー)

## 4. 想定される使用例（Edgeケース・データフローベース）

### 4.1 基本パターン 🔵
- **線形膨張 (TC-101-01/02)**: 格子 a が線形膨張する合成 20 フレーム → 各フレームの精密化格子が真値 ±0.01 Å を追跡、
  フレーム i の入力 phases == フレーム i−1 の出力 (warm start 継承、spy backend で観測)。
- **相 B 出現 (TC-102-01/03)**: 中間フレームで相 B が出現するシーケンス → 当該フレーム近傍が changepoint 判定 →
  局所木探索が B 込み仮説を採択 → 以後のフレームは B 込みで継続。
- **局所探索の起動制御 (TC-102-02)**: 木探索は changepoint フレームでのみ呼ばれる (spy で呼び出し回数検証、EDGE-104)。
- **inherit="lattice_only" (TC-101-03) 🟡**: 継承対象を格子のみに限定した warm start が機能する。

### 4.2 データフロー 🔵
- `dataflow.md` シーケンシャル解析の全体フロー (frame0 staged → 後続 warm start refine → 指標 → changepoint →
  局所探索 → 採択/棄却 → FrameRecord → LifecycleTracker → Trajectory 組立)。永続化は毎フレーム追記 (点線)。

### 4.3 エッジ・エラーケース 🔵🟡
- **EDGE-001 / TC-101-05**: 空フレーム列 (n_frames=0) → 空 `Trajectory(records=(), lifecycles={})`・例外なし。
  `first_frame_report=None`, `search_results={}`。
- **EDGE-101 / TC-101-06**: 単一フレーム → 長さ 1 の Trajectory (frame0 staged のみ、changepoint は warm-up 非発火)。
- **EDGE-002 / TC-101-07** 🟡: 中間フレームが `chi2=inf` 失敗 → 警告記録 (`warnings`) + FrameRecord に
  `refine_failed=True/rwp=None/chi2=None` + **直近成功フレームから継続** (失敗フレームを warm start に採らない)。
- **EDGE-103 / TC-102-05** 🟡: 全フレーム changepoint でも完走する (毎フレーム局所探索でも例外なく Trajectory を返す)。
- **性能 smoke / TC-108-03** 🟡: 100 フレーム changepoint なしが 60 秒以内 (滑らかな合成データで発火を抑制)。
- **native / REQ-105**: `orchestration="native"` → `NotImplementedError`。
- **参照した EARS 要件**: EDGE-001, EDGE-002, EDGE-101, EDGE-103, EDGE-104
- **参照した設計文書**: `dataflow.md` (エラーハンドリングフロー / データ整合性)

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 時系列その場測定の相同定・トラジェクトリ生成 (`docs/spec/m2-sequential/user-stories.md`)
- **参照した機能要件**: REQ-001 (逐次精密化), REQ-002 (warm start), REQ-101 (局所探索), REQ-105 (native 未対応),
  REQ-402 (決定論), REQ-404 (後方互換), REQ-405 (非破壊), REQ-012 (注入) / FR-301〜306
- **参照した非機能要件**: NFR-001 (性能), NFR-102 (決定論), NFR-105 (改竄検知)
- **参照した Edge ケース**: EDGE-001 (空), EDGE-002 (失敗継続), EDGE-101 (単一), EDGE-103 (全 changepoint), EDGE-104 (局所探索起動)
- **参照した受け入れ基準** (`docs/spec/m2-sequential/acceptance-criteria.md`):
  TC-101-01〜07, TC-102-01/02/03/05, TC-108-03, TC-106-06 (相当を 1 本)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m2-sequential/architecture.md` (システム概要 / D1 オンライン単一パス / D2 精密化 2 段構え / D3 局所木探索と採択)
  - **データフロー**: `docs/design/m2-sequential/dataflow.md` (シーケンシャル解析の全体フロー / エラーハンドリングフロー / データ整合性)
  - **型定義**: `docs/design/m2-sequential/interfaces.py` L211-253 (SequentialConfig / SequentialResult / SequentialEngine)
  - **データベース**: なし (永続化は JSONL。本タスクは注入経由で `store/persistent.py` を利用)
  - **API 仕様**: なし (M2 に新規 HTTP API なし)
- **開発ノート**: `docs/implements/m2-sequential/TASK-0019/note.md`
- **タスク定義**: `docs/tasks/m2-sequential/TASK-0019.md` (完了条件 9 項目)

---

## 品質判定

- **要件の曖昧さ**: なし (完了条件 9 項目 + TC 番号で検証点が確定)
- **入出力定義**: 完全 (interfaces.py L211-253 の frozen dataclass 契約に一致)
- **制約条件**: 明確 (決定論 / 非有限漏洩なし / 後方互換 / 注入 / native 未実装)
- **実装可能性**: 確実 (下位部品 StagedRefinementEngine / HypothesisTreeSearch / detect_changepoint /
  LifecycleTracker / Trajectory / persistent は全て実装済み、本タスクはオーケストレーション)
- **信頼性レベル**: 🔵 (青信号) が支配的。🟡 は inherit="lattice_only" セマンティクス・性能既定・
  seq_max_cycles/first_frame_staged 既定値に限定 (要件へ遡及可能)。

**総合判定: ✅ 高品質** — テストケース洗い出しへ進行可能。
