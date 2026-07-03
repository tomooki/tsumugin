# TASK-0006 木探索コア — TDD 要件定義書

- **機能名**: 木探索コア (best-first 展開 / 探索モード精密化 / ledger)
- **タスクID**: TASK-0006
- **要件名**: m1-hypothesis-search
- **実装ファイル**: `src/tsumugin/search/tree.py` (新規)
- **テストファイル**: `tests/test_tree_search.py` (新規、SimulatedBackend 使用)
- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 6h / Phase 3 探索エンジン
- **信頼性サマリー**: 🔵 多数 / 🟡 一部 (既定値の絶対点解釈・候補ピーク生成方式) / 🔴 なし

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: 観測パターン (2θ, 強度) と候補相集合から、相組合せ仮説の**探索木**を
  best-first で構築し、精密化・BIC 評価・ランキングまで行って `SearchResult` を返す木探索エンジン。
  (REQ-001 / FR-110)
- 🔵 **解決する問題**: 複数相の混合試料に対し「どの相の組合せが観測パターンを説明するか」を、
  候補を機械的に総当りせず、マッチングスコアと Rwp 改善を指標に**有望な枝だけを展開**して
  効率的かつ決定論的に探索する。全判断を理由付きで残し追跡可能にする。(REQ-001/402)
- 🔵 **想定ユーザー**: 粉末 XRD 解析を行う研究者・解析パイプライン。`HypothesisTreeSearch` を
  直接呼ぶ上位モジュール (M1 パイプライン、後続 TASK-0007 の後処理層)。
- 🔵 **システム内での位置づけ**: M0 資産 (`RefinementBackend` / `EvidenceBackend` / `Ledger` +
  `SnapshotStore`) と Phase 2 部品 (`find_peaks` / `match_score` / `jaccard_clusters` /
  `dynamic_threshold`) の上に立つ**純粋なオーケストレーション層**。ノード評価は
  (入力, 設定) → 結果の純関数構成 (REQ-404、将来の並列 map 置換を阻害しない)。
- **本タスクのスコープ境界**: 探索コア + `SearchResult` 骨格まで。`good_cluster_ids` /
  `unmatched` / `final_reports` / `warnings` / `to_summary()` は**ダミー (空値/スタブ)** とし、
  実体は **TASK-0007** が実装する。
- **参照したEARS要件**: REQ-001, REQ-003, REQ-004, REQ-101, REQ-102, REQ-201, REQ-202, REQ-401, REQ-402
- **参照した設計文書**: `docs/design/m1-hypothesis-search/architecture.md` D1 (L81-90) / D2 (L92-98)、
  `docs/design/m1-hypothesis-search/interfaces.py` (L143-199)

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 コンストラクタ `HypothesisTreeSearch.__init__` 🔵

```python
def __init__(self, backend: RefinementBackend, *,
             evidence: EvidenceBackend | None = None,   # 既定 BICBackend 🔵 REQ-004
             config: SearchConfig = SearchConfig(),
             ledger: Ledger | None = None,              # None なら内部生成
             snapshots: SnapshotStore | None = None) -> None
```
- 🔵 `evidence=None` のとき既定で `BICBackend` (name="bic") を使用 (REQ-004 / FR-121)。
- 🔵 `ledger` / `snapshots` は search() ごとに単一インスタンスとして利用・返却。
  `snapshots` は生成時に `ledger` 連携 (`SnapshotStore(ledger=...)`) を持たせる。

### 2.2 `search()` の入力 🔵

```python
def search(self, two_theta: np.ndarray, intensity: np.ndarray,
           candidates: Sequence[PhaseCandidate | PhaseInstance],
           *, weights: np.ndarray | None = None) -> SearchResult
```
- 🔵 `two_theta`, `intensity`: 観測パターン (numpy 1D、同長)。`weights` は任意。
- 🔵 `candidates`: `PhaseCandidate` または `PhaseInstance` の並び。`PhaseInstance` は
  `PhaseCandidate(phase=..., delta_u=0.0, label=None)` へ**正規化**する (M1 では `delta_u` は常に 0.0)。

### 2.3 `SearchConfig` (frozen dataclass) の既定値 🔵/🟡

| フィールド | 既定値 | 意味 | 信頼性 |
|---|---|---|---|
| `max_phases` | 5 | 1 仮説の最大相数 | 🔵 FR-115/REQ-401 |
| `r_improve_pct` | 2.0 | Rwp 改善打ち切り閾値 (ポイント) | 🔵 FR-115 (絶対点解釈は 🟡) |
| `match_tol_deg` | 0.15 | マッチング許容 2θ | 🟡 |
| `min_peak_height_frac` | 0.05 | ピーク高さ閾値 | 🟡 |
| `prune_min_candidates` | 4 | 枝刈り最小候補数 | 🟡 |
| `jaccard_threshold` | 0.85 | クラスタ類似閾値 | 🟡 |
| `explore_max_cycles` | 5 | 探索モード精密化サイクル | 🔵 FR-113 (値は 🟡) |
| `final_full_refine` | True | (TASK-0007 用) | 🟡 D3 |
| `max_final_refine` | 3 | (TASK-0007 用) | 🟡 |
| `high_r_threshold` | 30.0 | (TASK-0007 用, Rwp%) | 🟡 REQ-106 |
| `close_threshold` | 10.0 | ΔBIC 僅差競合 | 🔵 FR-122 |

### 2.4 `SearchResult` (frozen dataclass) の出力 🔵

| フィールド | 型 | 本タスクでの値 | 信頼性 |
|---|---|---|---|
| `ranked` | `tuple[RankedHypothesis, ...]` | refined 仮説を良い順で実体化 | 🔵 REQ-201 |
| `hypotheses` | `Mapping[str, Hypothesis]` | 全評価ノード (parent_id で系譜) | 🔵 REQ-202 |
| `alternatives` | `Mapping[int, tuple[int, ...]]` | 代表候補idx → 代替候補idx | 🔵 FR-114 |
| `ledger` | `Ledger` | 全操作を理由付き記録 | 🔵 REQ-402 |
| `snapshots` | `SnapshotStore` | 実体を返す | 🔵 |
| `good_cluster_ids` | `tuple[str, ...]` | **ダミー `()`** | TASK-0007 |
| `unmatched` | `UnmatchedPeakReport` | **空ダミー** | TASK-0007 |
| `final_reports` | `Mapping[str, RefinementReport]` | **ダミー `{}`** | TASK-0007 |
| `warnings` | `tuple[str, ...]` | **ダミー `()`** | TASK-0007 |
| `to_summary()` | `dict` | **未実装スタブ可** | TASK-0007 |

- 🔵 **仮説 ID**: `f"hyp-{i:04d}"` 連番 (M0 pipeline 規約)。SearchResult 内の全 ID は一意・整合。
- 🔵 **全 refined ノードに `metrics.evidence["bic"]`** を格納 (REQ-004 / TC-001-03)。
  `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence={ "bic": value })`。
  `gof = sqrt(chi2 / max(n_obs - n_params, 1))` (staged.py `_gof` と同式)。

### 2.5 データフロー 🔵

`find_peaks → 各候補 match_score → jaccard_clusters (縮約, alternatives 保持) →
dynamic_threshold 枝刈り → best-first 木探索 (backend.refine 直呼び → BIC 評価) → rank`
(`docs/design/m1-hypothesis-search/dataflow.md` シーケンス L39-74)

- **参照したEARS要件**: REQ-001/003/004/101/102/201/202/401/402
- **参照した設計文書**: interfaces.py `SearchConfig` / `SearchResult` / `HypothesisTreeSearch` (L143-199)、
  dataflow.md シーケンス

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **決定論 (REQ-403 / NFR-102 / TC-001-05)**: 乱数不使用。全ソートは**キー明示の安定ソート、
  同点は候補 index 昇順**で固定。同一入力・同一設定の 2 回実行でランキング・確率が
  **ビット同一** (`==` 比較、`pytest.approx` 不可)。best-first のキュー処理・組合せキー
  (ソート済みインデックスタプル)・仮説 ID 採番のすべてを入力順非依存の一意規則にする。
- 🔵 **非破壊性 (REQ-402/405 / P2 / NFR-101 / TC-008-03)**: 探索エンジン・`SearchResult` に
  **削除・上書き API (delete/remove/clear/overwrite 系) を実装しない**。枝刈り・降格は
  理由付き ledger 記録のみ (候補除外はしない)。
- 🔵 **失敗の非例外化 (EDGE-004 / D2)**: 精密化失敗は例外でなく **chi2=inf の結果**として扱い、
  当該ノードを降格して探索を続行する。全ノードに必ず `RefinementMetrics` を付与し
  (`rank()` は `metrics=None` で ValueError)、**全仮説 inf の NaN 縮退をガード**する。
- 🔵 **探索モード精密化 (REQ-003 / D2)**: `backend.refine` を**直接呼ぶ** (StagedRefinementEngine 不使用)。
  `free = {param_name(i, k) for 全相 i, k in ("scale","lattice.a","lattice.b","lattice.c")}`、
  `max_cycles = config.explore_max_cycles` (既定 5)。
- 🔵 **枝刈り閾値 (REQ-101 / TC-002 系)**: マッチングスコアが `dynamic_threshold` 未満の候補は
  ノード展開しない。**閾値ちょうどは展開側** (境界包含)。
- 🔵 **R 改善打ち切り (REQ-102 / D1)**: 相追加による `parent_rwp - child_rwp >= r_improve_pct`
  (rwp は % 値なので絶対ポイント解釈 🟡) を満たす子のみ展開キューへ。根の基準 Rwp は
  ゼロモデルの 100.0。
- 🔵 **相数上限 (REQ-401 / FR-115 / TC-003-02)**: `max_phases` 到達枝は展開停止。上限超の
  Hypothesis 自体を**生成前に打ち切る**。
- 🔵 **重複排除 (D1)**: 同一組合せ (ソート済みインデックスタプル) の再評価を排除。
- 🔵 **純関数構成 (REQ-404)**: ノード評価は将来の Worker 並列化を阻害しない (M1 は逐次)。
- 🔵 **ledger payload 型制約**: canonical JSON 化可能な素の型 (float/int/str/list) に限定
  (`_canonical_json` は `default=str` フォールバック — 決定論のため素の型が安全)。
- 🔵 **技術スタック**: Python >= 3.12 / numpy >= 1.26 のみ / scipy・GSAS-II 非依存
  (SimulatedBackend で完結)。型注釈必須 (`any` 回避)、キーワード専用引数は `*` 区切り、
  Lint `uvx ruff check` (line-length 100, py312)。**本セッションで git commit しない**。
- **参照したEARS要件**: NFR-101/102/103/104, REQ-401/402/403/404/405, REQ-101/102/201
- **参照した設計文書**: architecture.md D1/D2、interfaces.py、`CLAUDE.md`、
  `docs/spec/m1-hypothesis-search/note.md` (§技術的制約/§注意事項)

---

## 4. 想定される使用例（Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵
- **TC-001-01**: 2 相合成 (A+B)・4 候補 (A,B 妥当 + C,D 無関係) → **{A,B} 仮説が最上位**。
- **TC-001-02 / TC-003-01**: 余剰相追加は R 改善 < 2pt で打ち切られ、ledger に
  `branch_prune` (枝刈り) が記録される。
- **TC-001-03**: 全 refined 仮説の `metrics.evidence` に `"bic"` キーが存在。
- **TC-001-04**: 子仮説の `parent_id` が親 ID と一致 (系譜)。
- **TC-003-02**: `SearchConfig(max_phases=2)` で 3 相仮説が生成されない。
- **TC-003-03** (境界): `max_phases=5` 既定値の確認。

### 4.2 データフロー 🔵
- 合成データの範 (`tests/test_pipeline.py`): `tt = np.arange(15.0, 80.0, 0.02)`、
  `PhaseInstance(phase_ref, LatticeParams(a,a,a), scale)` (立方格子)、
  `y = backend.simulate(truth_phases, tt)`。格子定数 a を変えるとピーク位置が変わる
  (2 相合成は a の異なる 2 相を重ねる)。
- **候補ピーク生成方式 (設計未確定点 🟡)**: 推奨案で確定 —
  候補 1 相を観測グリッド上で `backend.simulate` → `find_peaks(min_height_frac=config.min_peak_height_frac)`
  で Peak 化し `match_score` に渡す。TDD 中に方式を確定し docstring に根拠を残す。

### 4.3 決定論 / 監査 🔵
- **TC-001-05**: 同一入力 2 回実行でランキング・確率が**ビット同一** (`once() == once()`)。
- **TC-008-01**: 探索実行後 `ledger.verify()` が True。
- **TC-008-02**: ノード生成/枝刈り/精密化/クラスタ縮約/採択が**kind 別に ledger 記録**
  (設計名: `match_score` / `cluster` / `prune_threshold` / `node_refine` / `branch_prune` +
  `ranking`)。
- **TC-008-03**: 探索エンジンに削除・上書き API が存在しない。

### 4.4 エッジケース / エラーケース 🔵
- **TC-E01 (EDGE-001)**: 候補ゼロ → 空ランキング (`ranked=()`)、例外なし。空でも
  ledger/snapshots は生成して返す。
- **TC-E03 (EDGE-004)**: ノード精密化が chi2=inf を返しても探索全体は完走。
- **TC-E04 (EDGE-102)**: 候補 1 相 → 深さ 1 の木、単一仮説。
- **統合確認**: 閾値未満の相がノード展開されないこと (TC-002 系の統合視点)。

- **参照したEARS要件**: EDGE-001, EDGE-004, EDGE-101, EDGE-102, REQ-101/102
- **参照した設計文書**: dataflow.md (シーケンス L39-74 / データ整合性 L125-129)、
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-001/003/008/Edge)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: 多相混合試料の相同定 (P1 探索木構築 / P2 非破壊監査)
- **参照した機能要件**:
  - REQ-001 (探索木構築 + ランキング返却), REQ-003 (探索モード精密化),
    REQ-004 (BIC 一次評価), REQ-101 (枝刈り閾値未満は非展開),
    REQ-102 (R 改善 < 2% で打ち切り), REQ-201 (refined のみランキング対象),
    REQ-202 (parent_id 系譜), REQ-401 (max_phases 既定 5・設定可), REQ-402 (全操作 ledger 記録・非破壊)
- **参照した非機能要件**: NFR-101 (非破壊), NFR-102 (決定論/ビット同一 = REQ-403),
  NFR-103/104 (並列化配慮 = REQ-404)
- **参照したEdgeケース**: EDGE-001 (候補ゼロ), EDGE-004 (精密化失敗の非例外化),
  EDGE-101 (上限到達枝の展開停止), EDGE-102 (候補 1 相 → 深さ 1)
- **参照した受け入れ基準**: TC-001-01〜05, TC-003-01/02/03, TC-008-01/02/03,
  TC-E01/E03/E04 (`acceptance-criteria.md`)
- **参照した設計文書**:
  - **アーキテクチャ**: `architecture.md` D1 (探索木展開戦略 L81-90) / D2 (探索モード精密化 L92-98)
  - **データフロー**: `dataflow.md` (探索シーケンス L39-74、データ整合性 L125-129)
  - **型定義**: `interfaces.py` (`SearchConfig` / `SearchResult` / `HypothesisTreeSearch` L143-199)
  - **既存実装**: `search/peaks.py` `search/matcher.py` `search/pruning.py` `search/clustering.py`、
    `backends/base.py` `backends/simulated.py`、`evidence/ic.py` `evidence/ranking.py`、
    `model/hypothesis.py` `model/phase.py`、`store/ledger.py` `store/snapshot.py`、
    `pipeline.py` (組立ての範)、`refinement/staged.py` (`_gof` 変換式)
  - **スコープ境界**: `docs/tasks/m1-hypothesis-search/TASK-0007.md` (jenks / フル精密化 /
    unmatched_peaks / warnings / to_summary / `search/__init__.py` re-export は後続)

---

## 6. 品質判定

- ✅ **要件の曖昧さ**: ほぼなし (完了条件がすべて acceptance-criteria の TC に遡及)
- ✅ **入出力定義**: 完全 (interfaces.py の frozen dataclass 契約に一致)
- ✅ **制約条件**: 明確 (決定論・非破壊・非例外化・探索モード精密化を数式/閾値で規定)
- ✅ **実装可能性**: 確実 (前提 TASK-0004/0005 完了、M0 資産すべて実在)
- **残る 🟡 (推奨案で確定済み・TDD 中に docstring 根拠化)**:
  1. `r_improve_pct` の絶対ポイント解釈 (rwp は % 値、`parent_rwp - child_rwp >= r_improve_pct`)
  2. 候補ピーク生成方式 (`simulate` → `find_peaks`)
  3. 全仮説 chi2=inf 時の NaN ガード方針 (確率均等 or ランキング末尾扱い)
- **総合判定**: 高品質 (信頼性 🔵 が支配的、🔴 なし)
