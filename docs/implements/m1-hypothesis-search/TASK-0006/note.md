# TASK-0006 木探索コア (best-first 展開 / 探索モード精密化 / ledger) — TDD コンテキストノート

## 作成日時
2026-07-03

## タスク要約
`src/tsumugin/search/tree.py` (新規) に木探索コアを実装する (FR-110/113/115, REQ-001/003/004/101/102/201/202/401/402):
- `SearchConfig` — frozen dataclass。探索設定 (既定値は §4 参照)
- `SearchResult` — **骨格のみ**。本タスクで実体を持つのは `ranked` / `hypotheses` / `alternatives` / `ledger` / `snapshots`。
  `good_cluster_ids` / `final_reports` / `unmatched` / `warnings` / `to_summary()` は**ダミー (空値) で置き、TASK-0007 が実装**する
- `HypothesisTreeSearch.__init__ / search()` — 探索コア:
  候補正規化 (PhaseInstance→PhaseCandidate) → find_peaks → match_score → jaccard 縮約 (alternatives 保持) →
  dynamic_threshold 枝刈り → **best-first 木探索** (組合せ重複排除、backend.refine 直呼び scale+lattice ≤ explore_max_cycles、
  Rwp 改善 ≥ r_improve_pct で展開、max_phases 上限) → BIC 評価 → rank。全操作を ledger に理由付き記録

- **タスクタイプ**: TDD (Red → Green → Refactor → verify-complete) / 推定 6h / Phase 3 探索エンジン
- **テスト**: `tests/test_tree_search.py` (新規、SimulatedBackend 使用)
- **依存**: 前提 TASK-0004 (pruning) ・TASK-0005 (clustering) 完了済み / 後続 TASK-0007 (探索後処理が SearchResult を完成させる)
- **信頼性**: 🔵 10 / 🟡 0 (完了条件はすべて acceptance-criteria の TC に遡及)
- **参照元**: `docs/tasks/m1-hypothesis-search/TASK-0006.md`, `docs/tasks/m1-hypothesis-search/overview.md`

---

## 1. 技術スタック
- **言語**: Python >= 3.12 (CPython)。コア依存は **numpy >= 1.26 のみ** (scipy / GSAS-II 非依存 — 本タスクは SimulatedBackend で完結)
- **パッケージマネージャー**: uv 0.9.x (src layout + hatchling)。テスト実行 `uv run pytest`
- **アーキテクチャ**: 木探索は M0 資産 (`RefinementBackend` / `EvidenceBackend` / `Ledger`+`SnapshotStore`) の上の
  **純粋なオーケストレーション層**。ノード評価は (入力, 設定) → 結果の純関数構成 (REQ-404、将来の並列 map 置換を阻害しない)
- **参照元**: `pyproject.toml`, `docs/spec/m1-hypothesis-search/note.md` (§技術スタック), `docs/design/m1-hypothesis-search/architecture.md`

## 2. 開発ルール
- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしのコミット禁止。**git commit は本セッションでは行わない**
- **決定論 (NFR-102 / REQ-403 / TC-001-05)**: 乱数不使用。**全ソートはキー明示の安定ソート、同点は候補 index 順**で固定。
  2 回実行でランキング・確率が**ビット同一** (`==` 比較、`pytest.approx` 不可の箇所)
- **非破壊性 (P2 / NFR-101 / TC-008-03)**: 探索エンジン・SearchResult に**削除・上書き API を実装しない**。
  枝刈り・降格は理由付き ledger 記録のみ (Dara 教訓: 候補除外はしない、REQ-405)
- **失敗の非例外化 (M0 規約 / EDGE-004)**: 精密化失敗は例外でなく **chi2=inf の結果**として扱い、当該ノードを降格して探索続行
- **仮説 ID**: `"hyp-XXXX"` 連番 (M0 pipeline 規約 `f"hyp-{i:04d}"`)。SearchResult 内の全 ID は一意・整合
- **命名/型**: snake_case / PascalCase / UPPER_SNAKE。型注釈必須 (`any` 回避)。キーワード専用引数は `*` 区切り
- **docstring**: 日本語可。FR/REQ 番号と 🔵🟡 信頼性レベルを紐づける慣習 (search/ 配下の既存 4 モジュール参照)
- **Lint**: `uvx ruff check src tests` (line-length 100, target py312)
- **__init__.py re-export**: `search/__init__.py` への `SearchConfig` / `SearchResult` / `HypothesisTreeSearch` 追加は
  TASK-0007 の実装項目に明記されている — 本タスクでは `tree.py` 直 import でテストしてよい (先行追加しても可、アルファベット順維持)
- **参照元**: `CLAUDE.md`, `docs/spec/m1-hypothesis-search/note.md` (§開発ルール), `docs/tasks/m1-hypothesis-search/TASK-0006.md` (注意事項)

## 3. 関連実装

### 3.1 完了済み前提 (M1 Phase 2 — search() が順に呼ぶ部品)
- **`src/tsumugin/search/peaks.py`**: `Peak(position, height)` frozen dataclass /
  `find_peaks(two_theta, intensity, *, min_height_frac=0.05) -> tuple[Peak, ...]` — 局所極大+高さ閾値。空入力・フラットは `()` へ縮退
- **`src/tsumugin/search/matcher.py`**: `match_score(candidate_peaks, observed_peaks, *, tol_deg=0.15, candidate_index=0) -> MatchResult`
  — `MatchResult(candidate_index, score∈[0,1], matched_observed, unmatched_candidate)`。1:1 貪欲一致。
  `unmatched_peaks()` / `UnmatchedPeakReport` もあるが**呼び出しは TASK-0007 スコープ**
- **`src/tsumugin/search/pruning.py`**: `dynamic_threshold(scores, *, min_candidates=4) -> float` — 累積分布の変曲点。
  縮退 (候補 < 4・全同値) は `-inf` (全展開)。**枝刈りは「閾値未満」を落とし、閾値ちょうどは展開側** (REQ-101)
- **`src/tsumugin/search/clustering.py`**: `PhaseCandidate(phase: PhaseInstance, delta_u=0.0, label=None)` /
  `jaccard_clusters(peak_sets, fits, delta_us, *, similarity_threshold=0.85, bin_width_deg=0.2) -> tuple[ClusterResult, ...]`
  — `ClusterResult(representative, members)` 代表 index 昇順。**代表のみ木探索へ、members は `SearchResult.alternatives` に保持**
  (`jenks_breaks` は TASK-0007 スコープ)

### 3.2 M0 資産 (直接利用)
- **`src/tsumugin/backends/base.py`**:
  - `RefinementBackend` (Protocol): `name: str` / `refine(model: RefinementModel, *, max_cycles=20) -> RefinementResult`
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)`
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params)`
  - `param_name(phase_index, key) -> "phase{i}.{key}"` — 探索モードの free_params 構築に使う
- **`src/tsumugin/backends/simulated.py`** (`SimulatedBackend`, テストの backend):
  - `simulate(phases, two_theta) -> np.ndarray` — 決定論的ガウシアン合成 (**候補相の計算ピーク生成に利用**)
  - `peak_positions(phase, two_theta) -> list[float]` — 反射 2θ 位置 (直方近似、既定 6 反射 `_DEFAULT_HKL`)
  - `refine()` は LM 法。`rwp` は % 値 (0–100、`_rwp()` が ×100)
- **`src/tsumugin/evidence/ic.py`**: `BICBackend` (name="bic") — `value = chi2 + n_params·ln(n_obs)`。evidence 既定
- **`src/tsumugin/evidence/ranking.py`**: `rank(hypotheses, backend, *, temperature=1.0, close_threshold=10.0) -> tuple[RankedHypothesis, ...]`
  — evidence 昇順 + softmax(-value/2T) + close_competitor。**`metrics=None` の仮説を渡すと ValueError** — 全ノードに metrics 必須
- **`src/tsumugin/model/hypothesis.py`**: `Hypothesis(id, phases, parent_id=None, metrics=None, status="candidate", accepted_by=None)`
  — status は `candidate|refined|accepted|rejected|superseded`。**parent_id が木の系譜 (TC-001-04 / REQ-202)**。
  `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence: Mapping[str, float])`
- **`src/tsumugin/model/phase.py`**: `PhaseInstance(phase_ref, lattice, scale, wt_frac=None, occupancies)` + `with_updates()` / `LatticeParams(a,b,c,...)`
- **`src/tsumugin/store/ledger.py`**: `Ledger.append(kind, payload) -> LedgerEntry` / `entries` / `verify() -> bool`。削除・改変 API なし
- **`src/tsumugin/store/snapshot.py`**: `SnapshotStore(ledger=None)` — `save(phases, *, label)` / `load` / `revert`。ledger 連携は生成時に渡す

### 3.3 参考パターン
- **`src/tsumugin/pipeline.py::analyze_single_pattern`** — 構造の範: `hid = f"hyp-{i:04d}"`、
  `replace(report.metrics, evidence={ev.backend: ev.value})` で evidence 格納、
  `ledger.append("hypothesis_evaluated", {...})` / `ledger.append("ranking", {...})`、`AnalysisResult` の組み立て
- **`src/tsumugin/refinement/staged.py`** — `_gof(result) = sqrt(chi2 / max(n_obs - n_params, 1))`:
  `RefinementResult` → `RefinementMetrics` 変換式の範 (tree.py は backend.refine 直呼びのため自前で変換する)。
  `RefinementReport` は `SearchResult.final_reports` の値型 (本タスクでは空 Mapping)
- **参照元**: `src/tsumugin/search/*.py`, `src/tsumugin/backends/{base,simulated}.py`, `src/tsumugin/evidence/{ic,ranking}.py`,
  `src/tsumugin/model/{hypothesis,phase}.py`, `src/tsumugin/store/{ledger,snapshot}.py`, `src/tsumugin/pipeline.py`, `src/tsumugin/refinement/staged.py`

## 4. 設計文書 (tree.py の契約)

### 4.1 interfaces.py L143-199 の契約
```python
@dataclass(frozen=True)
class SearchConfig:
    max_phases: int = 5              # 🔵 FR-115
    r_improve_pct: float = 2.0       # Rwp 改善打ち切り閾値 (ポイント) 🔵 FR-115 (絶対点解釈は 🟡)
    match_tol_deg: float = 0.15      # 🟡
    min_peak_height_frac: float = 0.05  # 🟡
    prune_min_candidates: int = 4    # 🟡
    jaccard_threshold: float = 0.85  # 🟡
    explore_max_cycles: int = 5      # 🔵 FR-113 保守的設定 (値は 🟡)
    final_full_refine: bool = True   # TASK-0007 用 🟡 D3
    max_final_refine: int = 3        # TASK-0007 用 🟡
    high_r_threshold: float = 30.0   # TASK-0007 用 (Rwp%) 🟡 REQ-106
    close_threshold: float = 10.0    # ΔBIC 僅差競合 🔵 FR-122

@dataclass(frozen=True)
class SearchResult:
    ranked: tuple[RankedHypothesis, ...]        # refined のみ、良い順 🔵
    hypotheses: Mapping[str, Hypothesis]        # 全評価ノード (parent_id で系譜) 🔵
    good_cluster_ids: tuple[str, ...]           # TASK-0007 (本タスクはダミー空)
    alternatives: Mapping[int, tuple[int, ...]] # 代表候補idx -> 代替候補idx 🔵 FR-114
    unmatched: UnmatchedPeakReport              # TASK-0007 (本タスクはダミー空)
    final_reports: Mapping[str, RefinementReport]  # TASK-0007 (本タスクはダミー空)
    ledger: Ledger                              # 🔵 REQ-402
    snapshots: SnapshotStore                    # 🔵
    warnings: tuple[str, ...] = ()              # TASK-0007
    def to_summary(self) -> dict: ...           # TASK-0007

class HypothesisTreeSearch:
    def __init__(self, backend: RefinementBackend, *,
                 evidence: EvidenceBackend | None = None,  # 既定 BICBackend 🔵
                 config: SearchConfig = SearchConfig(),
                 ledger: Ledger | None = None,
                 snapshots: SnapshotStore | None = None) -> None: ...
    def search(self, two_theta, intensity,
               candidates: Sequence[PhaseCandidate | PhaseInstance],
               *, weights=None) -> SearchResult: ...
```

### 4.2 D1: 探索木の展開戦略 (architecture.md 🔵/🟡)
- ノード = 相組合せ (**候補 index の frozenset**)。根 = 空集合
- **Best-first 展開**: 生存候補を**マッチングスコア降順**で試行。深さ d の仮説に候補を 1 相追加した子を評価し、
  **Rwp 改善が r_improve_pct (既定 2.0 ポイント) 以上**の子のみ展開キューへ
- 停止条件: max_phases (既定 5) 到達 / 改善なし / キュー空
- 評価済みノードはすべて `Hypothesis(status="refined")` として保持 — 枝刈り理由は ledger へ
- **同一組合せの重複評価はソート済みインデックスタプルのキーで排除**

### 4.3 D2: 探索モード精密化 (architecture.md 🔵)
- **backend.refine を直接呼ぶ** (StagedRefinementEngine は使わない):
  `free = {param_name(i, k) for 全相 i, k in ("scale", "lattice.a", "lattice.b", "lattice.c")}`、
  `max_cycles = config.explore_max_cycles` (既定 5)
- 失敗 (chi2=inf) は当該ノードの降格として扱い探索は継続 (EDGE-004)

### 4.4 dataflow.md のシーケンス (ledger kind の設計名)
`find_peaks → 各候補 match_score (ledger "match_score") → jaccard_clusters (ledger "cluster") →
dynamic_threshold (ledger "prune_threshold") → 木探索ループ (ledger "node_refine" / "branch_prune") → rank`
— TC-008-02 は「ノード生成/枝刈り/精密化/クラスタ縮約/採択が **kind 別に記録**」を要求。
ledger は search() ごとに単一インスタンス、親子関係は parent_id のみで表現 (グラフの別持ち禁止)

### 4.5 TASK-0007 とのスコープ境界
- 本タスク: 探索コア (上記) + SearchResult 骨格。`good_cluster_ids=()` / `final_reports={}` /
  `unmatched` は空ダミー / `warnings=()` / `to_summary()` は未実装スタブでよい
- TASK-0007: jenks 良好解・StagedRefinementEngine フル精密化・unmatched_peaks/unknown_phase_flag・warnings・to_summary
- **参照元**: `docs/design/m1-hypothesis-search/interfaces.py` (L143-199), `docs/design/m1-hypothesis-search/architecture.md` (D1 L81-98, D2 L92-98),
  `docs/design/m1-hypothesis-search/dataflow.md` (シーケンス L39-74, データ整合性 L125-129), `docs/tasks/m1-hypothesis-search/TASK-0007.md`

## 5. テスト関連情報
- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`
- **テストコマンド**: `uv run pytest` / `uv run pytest tests/test_tree_search.py` / `uv run pytest --cov=tsumugin`
- **配置/命名**: `tests/test_tree_search.py` を**新規作成** (`tree.py` 未作成 → Red で import 失敗し全 fail)
- **backend**: **SimulatedBackend のみ使用、GSAS-II 非依存** (`@pytest.mark.gsas` 不要)。`tests/conftest.py` は gsas 自動 skip のみ
- **合成データの範 (`tests/test_pipeline.py`)**: `tt = np.arange(15.0, 80.0, 0.02)` /
  `PhaseInstance(phase_ref, LatticeParams(a,a,a), scale)` (立方格子) / `y = backend.simulate(truth_phases, tt)`。
  格子定数 a を変えるとピーク位置が変わる (a=5.0 と 4.5/6.0 は不一致) — 2 相合成は a の異なる 2 相を重ねる。
  決定論テストは `once() == once()` の完全一致比較
- **カバーすべき受け入れ基準 (acceptance-criteria.md / TASK-0006 完了条件)**:
  - **TC-001-01** 🔵: 2 相合成 (A+B)・4 候補 (A,B 妥当 + C,D 無関係) → {A,B} 仮説が最上位
  - **TC-001-02 / TC-003-01** 🔵: 余剰相追加は R 改善 2pt 未満で打ち切られ、**ledger に branch_prune (枝刈り) が記録**される
  - **TC-001-03** 🔵: 全 refined 仮説の `metrics.evidence` に `"bic"` キー
  - **TC-001-04** 🔵: 子仮説の `parent_id` が親 ID と一致 (系譜)
  - **TC-001-05** 🔵: 同一入力 2 回実行でランキング・確率が**ビット同一** (REQ-403)
  - **TC-003-02** 🔵: `SearchConfig(max_phases=2)` で 3 相仮説が生成されない
  - **TC-003-03** 🔵 (境界): max_phases=5 既定値の確認
  - **TC-008-01** 🔵: 探索実行後 `ledger.verify()` が True
  - **TC-008-02** 🔵: ノード生成/枝刈り/精密化/クラスタ縮約/採択が kind 別に ledger 記録
  - **TC-008-03** 🔵: 探索エンジンに削除・上書き API が存在しない
  - **TC-E01** 🔵 (EDGE-001): 候補ゼロ → 空ランキング、例外なし
  - **TC-E03** 🔵 (EDGE-004): ノード精密化が chi2=inf を返しても探索全体は完走
  - **TC-E04** 🔵 (EDGE-102): 候補 1 相 → 深さ 1 の木、単一仮説
  - (TC-002 系は TASK-0003/0004 で単体済みだが、統合として「閾値未満の相がノード展開されない」を確認するとよい)
- **書式の範**: `tests/test_pruning.py` / `tests/test_clustering.py` — 【テスト目的/内容/期待/信頼性レベル】コメント、
  `pytest.approx` (数値近似) と `==` (決定論) の使い分け、`@pytest.mark.parametrize`
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_pipeline.py`, `tests/test_clustering.py`,
  `docs/spec/m1-hypothesis-search/acceptance-criteria.md` (TC-001 L27-32, TC-003 L44-46, TC-008 L79-81, Edge L85-88)

## 6. 注意事項
- **候補相の計算ピーク生成 (設計未確定点)**: `match_score` は候補側 `Sequence[Peak]` を要するが、
  `RefinementBackend` Protocol に simulate は無い。実装済みの `SimulatedBackend.simulate(phases, two_theta)` /
  `GSASIIBackend.simulate` (両方に存在) を利用する想定 (`docs/spec/m1-hypothesis-search/note.md` §注意事項)。
  推奨: 候補 1 相を観測グリッド上で simulate → `find_peaks(min_height_frac=config.min_peak_height_frac)` で Peak 化。
  TDD 中に方式を確定し docstring に根拠を残すこと
- **根ノードの基準 Rwp**: 空集合の根は精密化できない。SimulatedBackend の `_rwp` はゼロモデルで 100.0 を返すため、
  「根の Rwp = 100.0 (ゼロモデル)」を基準に深さ 1 の改善判定をするのが自然。判定式は
  `parent_rwp - child_rwp >= r_improve_pct` (rwp は % 値なので「絶対ポイント」解釈、interfaces.py 🟡)
- **chi2=inf ノードの扱い (TC-E03)**: BIC 値も inf になる。`rank()` は `metrics=None` で ValueError を投げるので
  **全評価ノードに必ず RefinementMetrics を付ける** (`gof = sqrt(chi2 / max(n_obs - n_params, 1))` — staged.py の `_gof` と同式)。
  inf 仮説を rank に混ぜる場合、softmax の logit が -inf → 有限仮説があれば確率 0 で無害だが、
  **全仮説 inf だと NaN 縮退の恐れ** — 実装時にガード (例: inf のみなら確率均等 or ランキング末尾扱い) を検討しテストで固定
- **決定論の要 (TC-001-05)**: best-first の順序はスコア降順 + **同点は候補 index 昇順**で固定。
  キュー処理・組合せキー (ソート済みタプル)・仮説 ID 採番 (評価順連番) のすべてを入力順非依存の一意規則にする
- **jaccard 縮約と alternatives**: 代表候補のみを探索対象とし、`ClusterResult.members` から
  `alternatives: {代表idx: (代替idx, ...)}` を構築して SearchResult に保持 (削除しない、REQ-103/405)。
  `PhaseCandidate.delta_u` は M1 では常に 0.0 (fits には match_score の score を渡す)
- **ledger 記録 (TC-008-02 / REQ-402)**: kind は dataflow.md の設計名 (`match_score` / `cluster` / `prune_threshold` /
  `node_refine` / `branch_prune`) + ランキング採択 (pipeline の `ranking` 踏襲) を最低限カバー。payload は canonical JSON 化可能な
  素の型 (float/int/str/list) に限定 (`_canonical_json` は `default=str` フォールバック — 決定論のため素の型が安全)
- **候補ゼロ (TC-E01)**: `search()` は例外なしで空 SearchResult (`ranked=()` 等) を返す。空でも ledger/snapshots は生成して返す
- **max_phases ガード (TC-003-02)**: 生成前に打ち切る (3 相仮説の Hypothesis 自体を作らない)。EDGE-101: 上限到達枝は展開停止
- **非破壊 API (TC-008-03)**: HypothesisTreeSearch / SearchResult に delete/remove/clear/overwrite 系メソッドを作らない
- **スコープ外**: jenks_breaks 呼び出し・フル精密化・unmatched_peaks 呼び出し・to_summary 実装・
  `search/__init__.py` re-export は TASK-0007。`.gpx` (TASK-0008)・Web UI (TASK-0009) も対象外
- **参照元**: `docs/spec/m1-hypothesis-search/note.md` (§技術的制約/§注意事項), `docs/spec/m1-hypothesis-search/requirements.md`
  (REQ-101〜405, EDGE-001〜103), `docs/design/m1-hypothesis-search/architecture.md` (D1/D2), `docs/tasks/m1-hypothesis-search/TASK-0006.md`, `CLAUDE.md`

---

## 収集したファイル一覧
- タスク: `docs/tasks/m1-hypothesis-search/TASK-0006.md`, `docs/tasks/m1-hypothesis-search/TASK-0007.md` (境界確認), `docs/tasks/m1-hypothesis-search/overview.md`
- 仕様: `docs/spec/m1-hypothesis-search/note.md`, `docs/spec/m1-hypothesis-search/requirements.md`, `docs/spec/m1-hypothesis-search/acceptance-criteria.md`
- 設計: `docs/design/m1-hypothesis-search/interfaces.py` (tree 契約 L143-199), `docs/design/m1-hypothesis-search/architecture.md` (D1/D2), `docs/design/m1-hypothesis-search/dataflow.md`
- 完了済み前提実装 (Phase 2): `src/tsumugin/search/peaks.py`, `src/tsumugin/search/matcher.py`, `src/tsumugin/search/pruning.py`, `src/tsumugin/search/clustering.py`, `src/tsumugin/search/__init__.py`
- M0 資産: `src/tsumugin/backends/base.py`, `src/tsumugin/backends/simulated.py`, `src/tsumugin/evidence/ic.py`, `src/tsumugin/evidence/ranking.py`,
  `src/tsumugin/model/hypothesis.py`, `src/tsumugin/model/phase.py`, `src/tsumugin/store/ledger.py`, `src/tsumugin/store/snapshot.py`,
  `src/tsumugin/pipeline.py`, `src/tsumugin/refinement/staged.py` (`_gof` / RefinementReport)
- テスト範/設定: `tests/test_pipeline.py`, `tests/test_clustering.py`, `tests/test_pruning.py`, `tests/conftest.py`, `pyproject.toml`
- 前タスクノート (書式の範): `docs/implements/m1-hypothesis-search/TASK-0005/note.md`
- (`AGENTS.md`, `docs/rule/` は不在 — 追加ルールは `CLAUDE.md` / `docs/spec/m1-hypothesis-search/note.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
