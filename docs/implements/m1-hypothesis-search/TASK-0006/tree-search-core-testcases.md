# TASK-0006 木探索コア (best-first 展開 / 探索モード精密化 / ledger) — TDD テストケース定義書

- **機能名**: 木探索コア (tree-search-core: `SearchConfig` / `SearchResult` / `HypothesisTreeSearch`)
- **タスクID**: TASK-0006
- **要件名**: m1-hypothesis-search
- **対象実装**: `src/tsumugin/search/tree.py` (新規) — `SearchConfig`, `SearchResult` (骨格), `HypothesisTreeSearch.__init__ / search()`
- **テストファイル**: `tests/test_tree_search.py` (新規、SimulatedBackend 使用・GSAS-II 非依存)
- **書式の範**: `tests/test_pipeline.py` (合成データ) / `tests/test_pruning.py` / `tests/test_clustering.py` (コメント様式)

> **【信頼性レベル凡例】**
> - 🔵 **青信号**: EARS要件定義書・設計文書 (`interfaces.py` / `architecture.md` / `dataflow.md` / `acceptance-criteria.md`) を参考にほぼ推測していない
> - 🟡 **黄信号**: 要件・設計から妥当な推測
> - 🔴 **赤信号**: 要件・設計にない推測

## テストケース一覧サマリー

| 区分 | 件数 | ケースID |
|------|------|----------|
| 正常系 | 10 | TC-N01〜TC-N10 |
| 異常系 (縮退・非破壊契約) | 4 | TC-E01〜TC-E04 |
| 境界値 | 6 | TC-B01〜TC-B06 |
| **合計** | **20** | |

信頼性内訳: 🔵 16 / 🟡 4 / 🔴 0

### 受け入れ基準カバレッジ (acceptance-criteria.md)

| 受け入れ基準 | 対応ケース |
|---|---|
| TC-001-01 / 02 / 03 / 04 / 05 | TC-N01 / TC-N02 / TC-N03 / TC-N04 / TC-B04 |
| TC-002-02 / 03 (統合視点) | TC-N05 / TC-B06 |
| TC-003-01 / 02 / 03 | TC-N02 / TC-B01 / TC-B02 |
| TC-008-01 / 02 / 03 | TC-N07 / TC-N08 / TC-E04 |
| TC-E01 / E03 / E04 (Edge) | TC-E01 / TC-E02 / TC-B03 |

---

## 0. 共通テストデータ・前提

- 🔵 **観測グリッド (`tests/test_pipeline.py` の範)**: `tt = np.arange(15.0, 80.0, 0.02)`。
  合成強度は `y = SimulatedBackend().simulate(truth_phases, tt)` (決定論的ガウシアン合成)。
- 🔵 **候補相 (立方格子、a を変えるとピーク位置が変わる)**:
  - `PHASE_A`: `PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0), scale=1.0)` — 真の相 1
  - `PHASE_B`: 同形で `a=6.0` — 真の相 2 (2 相合成は A+B を重ねる)
  - `PHASE_C`: 同形で `a=4.5` — 無関係相 (A/B とピーク位置が合わない)
  - `PHASE_D`: 同形で `a=7.0` — 無関係相
  - 🟡 具体的な a 値は「6 反射 (`_DEFAULT_HKL`) が 15–80° 内で相互に偶然一致しない」よう Red フェーズで較正する。
- 🔵 **仮説 ID 規約**: `f"hyp-{i:04d}"` 連番 (M0 pipeline 規約)。
- 🔵 **ledger kind の設計名 (dataflow.md)**: `match_score` / `cluster` / `prune_threshold` / `node_refine` / `branch_prune` + `ranking`。
- 🟡 **FakeBackend (スタブ)**: `RefinementBackend` は Protocol のため、テスト側で
  「相組合せ → 固定 (rwp, chi2)」を返す決定論スタブを定義できる。境界値 (TC-B05) と
  失敗注入 (TC-E02/E03) は SimulatedBackend では Rwp を厳密制御できないためスタブを使う。
  `simulate` も実装し候補ピーク生成 (simulate → find_peaks) 経路を成立させる。
- 🔵 **数値比較の使い分け**: 決定論 (ビット同一) は `==`、物理量の近似は `pytest.approx`。
- 🔵 **根ノードの基準 Rwp**: 空集合の根 = ゼロモデルで Rwp 100.0。改善判定式は
  `parent_rwp - child_rwp >= r_improve_pct` (rwp は % 値、絶対ポイント解釈 🟡)。

---

## 1. 正常系テストケース（基本的な動作）

### TC-N01: 2 相合成 (A+B)・4 候補で {A,B} 仮説が最上位 (TC-001-01)

- **テスト名**: `test_two_phase_truth_ranks_ab_first`
  - **何をテストするか**: A+B の合成パターンに候補 A,B,C,D を与えたとき、best-first 探索が {A,B} 組合せ仮説を最上位ランクに返すこと。
  - **期待される動作**: `search()` の `ranked[0]` の仮説が相 A と B の 2 相構成 (`phase_ref` 集合が {"A","B"})。
- **入力値**: `y = backend.simulate([PHASE_A, PHASE_B], tt)`、`candidates=[PHASE_A, PHASE_B, PHASE_C, PHASE_D]`、既定 `SearchConfig()`
  - **入力データの意味**: 真の構成 2 相 + 位置が合わない無関係 2 相という受け入れ基準の標準シナリオ。
- **期待される結果**: `result.ranked` が非空、`result.ranked[0].hypothesis.phases` の `phase_ref` 集合 == {"A","B"}。`result.hypotheses[ranked[0].hypothesis.id]` が存在。
  - **期待結果の理由**: A,B はマッチングスコア高 → 展開、{A,B} は Rwp が最小 → BIC 最小 → rank 1 位 (REQ-001/004/201)。
- **テストの目的**: 探索パイプライン全体 (find_peaks → match → cluster → prune → 木探索 → BIC → rank) の中核契約を確認。
  - **確認ポイント**: 単相 {A} や {B} でなく 2 相 {A,B} が 1 位になること。
- 🔵 信頼性レベル: 受け入れ基準 TC-001-01 / REQ-001 に直接依拠。

### TC-N02: 余剰相追加は R 改善 2pt 未満で打ち切られ ledger に branch_prune が記録される (TC-001-02 / TC-003-01)

- **テスト名**: `test_redundant_phase_addition_pruned_with_ledger_record`
  - **何をテストするか**: 1 相 (A) 合成データ・3 候補 (A,B,C) で {A} が 1 位になり、A への余剰相追加が `parent_rwp - child_rwp < r_improve_pct` で展開キューに入らず、`branch_prune` kind の ledger エントリが残ること。
  - **期待される動作**: {A} が最上位。{A,B} 等の子は評価されても展開されない or 生成打ち切りが理由付き記録される。
- **入力値**: `y = backend.simulate([PHASE_A], tt)`、`candidates=[PHASE_A, PHASE_B, PHASE_C]`、既定設定 (`r_improve_pct=2.0`)
  - **入力データの意味**: 単相で完全に説明できるデータ。余剰相を足しても Rwp 改善はほぼ 0。
- **期待される結果**: `ranked[0]` が単相 {A}。`any(e.kind == "branch_prune" for e in result.ledger.entries)` が True で、payload に打ち切り理由 (改善不足) を示す素の型の情報を含む。
  - **期待結果の理由**: REQ-102 (R 改善 < 2pt で打ち切り) と REQ-402 (判断の理由付き記録)。候補は削除されず記録のみ (REQ-405)。
- **テストの目的**: R 改善打ち切り則と監査記録の両立を確認。
  - **確認ポイント**: 打ち切りが「例外」でも「無言のスキップ」でもなく ledger 記録を伴うこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-001-02 / TC-003-01 / REQ-102/402 に直接依拠。

### TC-N03: 全 refined 仮説の metrics.evidence に "bic" キーが付与される (TC-001-03)

- **テスト名**: `test_all_refined_hypotheses_have_bic_evidence`
  - **何をテストするか**: `search()` 後の `result.hypotheses` の全ノードが `status="refined"` かつ `metrics is not None` かつ `"bic" in metrics.evidence` であること。
  - **期待される動作**: 評価済みノード全数に BIC 値が格納される (rank() の前提: metrics=None は ValueError)。
- **入力値**: TC-N01 と同じ 2 相合成・4 候補入力。
  - **入力データの意味**: 複数ノード (深さ 1〜2) が評価される代表シナリオ。
- **期待される結果**: `all(h.metrics is not None and "bic" in h.metrics.evidence for h in result.hypotheses.values())`。`gof` が `sqrt(chi2 / max(n_obs - n_params, 1))` と `pytest.approx` で一致 (代表 1 ノードで確認)。
  - **期待結果の理由**: REQ-004 (BIC 一次評価) / 要件定義書 §2.4 (`evidence={"bic": value}`、`_gof` 同式)。
- **テストの目的**: evidence 格納契約と RefinementResult→RefinementMetrics 変換式を確認。
  - **確認ポイント**: metrics 欠落ノードが 1 つもないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-001-03 / REQ-004 / staged.py `_gof` 同式に直接依拠。

### TC-N04: 子仮説の parent_id が親 ID と一致する (系譜) (TC-001-04)

- **テスト名**: `test_child_hypothesis_parent_id_links_lineage`
  - **何をテストするか**: 深さ 2 の仮説 (2 相) の `parent_id` が深さ 1 の親仮説 (その部分集合 1 相) の `id` と一致し、`hypotheses` 内で解決できること。
  - **期待される動作**: 全ノードについて `parent_id is None` (深さ 1) または `parent_id in result.hypotheses` で、親の相集合が子の相集合の真部分集合。
- **入力値**: TC-N01 と同じ 2 相合成・4 候補入力 (深さ 2 のノードが必ず生成される)。
  - **入力データの意味**: 親子 2 世代以上の木が構築される最小の代表入力。
- **期待される結果**: {A,B} 仮説の `parent_id` が {A} または {B} 単相仮説の ID と一致。全ノードで親子の相集合包含が成り立つ。グラフの別持ちなし (parent_id のみで系譜表現)。
  - **期待結果の理由**: REQ-202 (parent_id 系譜) / dataflow.md データ整合性 (親子関係は parent_id のみ)。
- **テストの目的**: 探索木の系譜が Hypothesis の標準フィールドだけで追跡可能なことを確認。
  - **確認ポイント**: 存在しない ID を指す parent_id (ダングリング) がないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-001-04 / REQ-202 に直接依拠。

### TC-N05: 枝刈り閾値未満の候補はノード展開されない (TC-002-02 統合視点)

- **テスト名**: `test_below_threshold_candidates_not_expanded`
  - **何をテストするか**: `dynamic_threshold` 未満のマッチングスコアの候補 (無関係相) が深さ 1 のノードとして評価されず、`prune_threshold` kind の ledger 記録が残ること。
  - **期待される動作**: 低スコア候補の単相仮説が `hypotheses` に現れない。閾値と各候補スコアが ledger で追跡できる。
- **入力値**: `y = backend.simulate([PHASE_A, PHASE_B], tt)`、`candidates=[PHASE_A, PHASE_B, PHASE_C, PHASE_D]` (候補 4 = `prune_min_candidates` で枝刈り有効)。
  - **入力データの意味**: スコア分布に明確な変曲点 (A,B 高 / C,D 低) がある入力。
- **期待される結果**: `hypotheses` の全仮説の相集合に C 単独・D 単独ノードが含まれない (C/D のスコアが閾値未満の場合)。`any(e.kind == "prune_threshold" for e in ledger.entries)` が True。
  - **期待結果の理由**: REQ-101 (閾値未満は非展開・閾値ちょうどは展開側)。単体は TASK-0004 で済みのため、ここでは tree.py への結線を統合確認する。
- **テストの目的**: pruning.dynamic_threshold が探索前段に正しく結線されていることを確認。
  - **確認ポイント**: 候補が「削除」でなく「非展開 + 記録」で扱われること (REQ-405)。
- 🟡 信頼性レベル: 受け入れ基準 TC-002-02 は 🔵 だが、TASK-0006 での統合確認という位置づけ (note.md §5「確認するとよい」) は妥当な推測。

### TC-N06: jaccard 縮約で代表のみ探索し alternatives に代替候補を保持 (FR-114)

- **テスト名**: `test_jaccard_reduction_keeps_alternatives`
  - **何をテストするか**: ピーク位置がほぼ同一の 2 候補 (A と A') が 1 クラスタに縮約され、代表のみが木探索対象になり、`SearchResult.alternatives` に {代表idx: (代替idx,)} が保持されること。
  - **期待される動作**: A' 単独ノードは `hypotheses` に現れず、`alternatives` 経由で追跡できる。`cluster` kind の ledger 記録が残る。
- **入力値**: `y = backend.simulate([PHASE_A], tt)`、`candidates=[PHASE_A, PHASE_A_PRIME, PHASE_C]` (`PHASE_A_PRIME` は `a=5.0` に微小差 (同一 bin に落ちる程度、例 a=5.001) を与えた等構造候補)。
  - **入力データの意味**: 等構造縮約 (EDGE-103 の縮小版) が探索前段で起きる入力。fits には match_score の score、delta_u は常に 0.0。
- **期待される結果**: `result.alternatives` に代表 idx → 代替 idx タプルのエントリが存在 (例 `{0: (1,)}`)。代替候補 idx の単相仮説が `hypotheses` にない。`any(e.kind == "cluster" for e in ledger.entries)`。
  - **期待結果の理由**: FR-114 / REQ-103 (縮約しても代替解は削除せず保持)。interfaces.py `alternatives: Mapping[int, tuple[int, ...]]`。
- **テストの目的**: clustering.jaccard_clusters の結線と alternatives 構築を確認。
  - **確認ポイント**: 代替候補が結果から消失しないこと (非破壊性)。
- 🔵 信頼性レベル: interfaces.py L143-199 / FR-114 / 要件定義書 §2.4 に直接依拠。

### TC-N07: 探索実行後 ledger.verify() が True (TC-008-01)

- **テスト名**: `test_ledger_verify_true_after_search`
  - **何をテストするか**: `search()` 完走後に `result.ledger.verify()` が True (ハッシュ連鎖が無傷) であること。
  - **期待される動作**: 探索中の全 append が正しく連鎖し、改竄検証が通る。
- **入力値**: TC-N01 と同じ 2 相合成・4 候補入力。
  - **入力データの意味**: match/cluster/prune/refine/rank の全記録経路を通る代表入力。
- **期待される結果**: `result.ledger.verify() is True` かつ `len(result.ledger.entries) > 0`。
  - **期待結果の理由**: REQ-402 / NFR-201 (追記のみの監査ログ)。
- **テストの目的**: ledger 連鎖の健全性を確認。
  - **確認ポイント**: 空 ledger での自明 True でないこと (entries 非空を併せて検証)。
- 🔵 信頼性レベル: 受け入れ基準 TC-008-01 に直接依拠。

### TC-N08: ノード生成/枝刈り/精密化/クラスタ縮約/採択が kind 別に ledger 記録される (TC-008-02)

- **テスト名**: `test_ledger_records_all_operation_kinds`
  - **何をテストするか**: 探索の主要 5 操作が設計名 kind (`match_score` / `cluster` / `prune_threshold` / `node_refine` / `branch_prune` / `ranking`) で区別されて記録されること。
  - **期待される動作**: 各 kind が 1 件以上存在し、payload が素の型 (float/int/str/list) で canonical JSON 化可能。
- **入力値**: TC-N02 と同じ 1 相合成・3 候補 + 等構造候補を混ぜた入力 (branch_prune と cluster の両方が発生するよう構成。必要なら 2 入力に分けて検証)。
  - **入力データの意味**: 全 kind の記録経路を最少入力で踏むシナリオ。
- **期待される結果**: `kinds = {e.kind for e in ledger.entries}` が `{"match_score", "cluster", "prune_threshold", "node_refine", "branch_prune", "ranking"}` を包含。各 payload が JSON シリアライズ可能で仮説 ID / 候補 idx / 理由を含む。
  - **期待結果の理由**: REQ-402 / dataflow.md の kind 設計名 / note.md §6 (payload 型制約)。
- **テストの目的**: 監査の粒度 (kind 別) と payload 健全性を確認。
  - **確認ポイント**: 全操作が単一 kind に潰れていないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-008-02 / dataflow.md 設計名に直接依拠。

### TC-N09: SearchResult 骨格契約 — ID 形式・PhaseInstance 正規化・TASK-0007 フィールドは空ダミー

- **テスト名**: `test_search_result_skeleton_contract`
  - **何をテストするか**: (a) 仮説 ID が `hyp-XXXX` 形式の一意連番、(b) `candidates` に素の `PhaseInstance` を渡しても `PhaseCandidate(delta_u=0.0)` へ正規化されて動く、(c) TASK-0007 スコープのフィールドが空ダミー (`good_cluster_ids=()`, `final_reports=={}`, `warnings==()`, `unmatched` 空) であること。
  - **期待される動作**: interfaces.py の SearchResult 契約どおりの骨格が返る。
- **入力値**: `candidates=[PHASE_A, PHASE_B]` (素の PhaseInstance) と `[PhaseCandidate(phase=PHASE_A), PhaseCandidate(phase=PHASE_B)]` の両形。
  - **入力データの意味**: 入力正規化 (要件定義書 §2.2) の両受け入れ形。
- **期待される結果**: 全 `hypotheses` キーが正規表現 `^hyp-\d{4}$` に一致し重複なし。両入力形で探索が成功。`result.good_cluster_ids == ()`、`result.final_reports == {}` (空 Mapping)、`result.warnings == ()`。`ranked` の各要素の id が `hypotheses` に存在 (ID 整合)。
  - **期待結果の理由**: M0 pipeline の ID 規約 / interfaces.py / TASK-0007 スコープ境界 (要件定義書 §2.4)。
- **テストの目的**: 骨格 dataclass の契約とスコープ境界を固定し、TASK-0007 の受け口を保証。
  - **確認ポイント**: ダミーフィールドに実値が混入しないこと。
- 🔵 信頼性レベル: interfaces.py L143-199 / 要件定義書 §2.2・§2.4 に直接依拠。

### TC-N10: 探索モード精密化 — backend.refine が scale+lattice の free_params と explore_max_cycles で呼ばれる (D2)

- **テスト名**: `test_explore_mode_refine_uses_scale_lattice_and_max_cycles`
  - **何をテストするか**: 木探索のノード評価が `backend.refine` 直呼びで、`free_params == {param_name(i,k) for 全相 i, k in ("scale","lattice.a","lattice.b","lattice.c")}`、`max_cycles == config.explore_max_cycles` (既定 5) であること。
  - **期待される動作**: StagedRefinementEngine を経由せず、探索モードの限定パラメータで精密化される。
- **入力値**: SimulatedBackend をラップした記録スパイ (refine 呼び出しの model.free_params / max_cycles を記録して委譲) を注入し、`candidates=[PHASE_A]` で実行。`SearchConfig(explore_max_cycles=3)` の明示値も 1 ケース確認。
  - **入力データの意味**: 呼び出し契約 (D2) をブラックボックス境界で観測する最小入力。
- **期待される結果**: 記録された全呼び出しで `max_cycles == 5` (既定) / `== 3` (明示時)。深さ 1 (1 相) の `free_params == {"phase0.scale", "phase0.lattice.a", "phase0.lattice.b", "phase0.lattice.c"}`。
  - **期待結果の理由**: architecture.md D2 (探索モード精密化) / REQ-003 / FR-113。
- **テストの目的**: 探索が「軽い精密化」で走る性能契約を構造的に固定。
  - **確認ポイント**: 全相の 4 パラメータ以外 (occupancy 等) が free に入らないこと。
- 🔵 信頼性レベル: architecture.md D2 / REQ-003 に直接依拠 (スパイによる検証方式は 🟡)。

---

## 2. 異常系テストケース（縮退・エラーハンドリング・非破壊契約）

> **M0 規約**: ドメイン的縮退・失敗は**例外化せず**縮退値/降格に一元化する。異常系は「例外を投げずに完走する」ことの検証が中心。

### TC-E01: 候補ゼロ → 空ランキング・例外なし (TC-E01 / EDGE-001)

- **テスト名**: `test_zero_candidates_returns_empty_result_without_error`
  - **エラーケースの概要**: `candidates=[]` で探索対象が存在しない。
  - **エラー処理の重要性**: 上流のデータベース照合が 0 件を返す実運用ケース。IndexError / ValueError で落とさない。
- **入力値**: `y = backend.simulate([PHASE_A], tt)`、`candidates=[]`
  - **不正な理由**: 厳密には不正でなくドメイン縮退 (探索空間が空)。
  - **実際の発生シナリオ**: 候補データベース検索がヒットしなかった試料。
- **期待される結果**: 例外なし。`result.ranked == ()`、`result.hypotheses == {}` (空 Mapping)、`result.alternatives == {}`。`result.ledger` / `result.snapshots` は実体が返り `ledger.verify() is True`。
  - **エラーメッセージの内容**: なし (空 SearchResult で表現)。
  - **システムの安全性**: 呼び出し側 (TASK-0007 / UI) が空結果を安全にレンダリングできる。
- **テストの目的**: 空入力の非例外縮退と「空でも ledger/snapshots を返す」契約を確認。
  - **品質保証の観点**: EDGE-001 の非例外化契約を担保。
- 🔵 信頼性レベル: 受け入れ基準 TC-E01 / EDGE-001 / note.md §6 に直接依拠。

### TC-E02: ノード精密化が chi2=inf を返しても探索全体は完走する (TC-E03 / EDGE-004)

- **テスト名**: `test_infinite_chi2_node_demoted_search_completes`
  - **エラーケースの概要**: 特定の相組合せで精密化が失敗し `chi2=inf` の RefinementResult が返る。
  - **エラー処理の重要性**: 実 backend (GSAS-II) では発散・特異行列が日常的に起こる。1 ノードの失敗で探索全体を落とさない (Dara 教訓)。
- **入力値**: FakeBackend — 組合せ {B} を含むノードだけ `chi2=inf, converged=False` を返し、他は有限値を返すスタブ。`candidates=[PHASE_A, PHASE_B]`。
  - **不正な理由**: chi2=inf は数値評価不能なノード。
  - **実際の発生シナリオ**: 不適合な相を含むモデルの LM 発散。
- **期待される結果**: 例外なし。`search()` が SearchResult を返し、有限 chi2 の {A} 系仮説が `ranked` 上位。inf ノードも `hypotheses` に `RefinementMetrics` 付きで残る (metrics=None にしない — rank() の ValueError 回避)。降格が ledger に理由付き記録される。
  - **エラーメッセージの内容**: なし (降格 + ledger 記録で表現)。
  - **システムの安全性**: 失敗ノードの子は展開されず、探索は残りの枝で継続。
- **テストの目的**: 失敗の非例外化 (D2 / EDGE-004) と降格ルートを確認。
  - **品質保証の観点**: inf が softmax で確率 0 になり有限仮説のランキングを壊さないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-E03 / EDGE-004 / architecture.md D2 に直接依拠。

### TC-E03: 全仮説 chi2=inf でも NaN に縮退せず完走する (NaN ガード)

- **テスト名**: `test_all_infinite_hypotheses_guarded_against_nan`
  - **エラーケースの概要**: 全評価ノードが chi2=inf → 全 BIC=inf → softmax logit が全て -inf で確率が NaN 化し得る。
  - **エラー処理の重要性**: 全滅ケースで NaN が UI / to_summary へ伝播すると下流全体が壊れる。
- **入力値**: FakeBackend — 全組合せで `chi2=inf` を返すスタブ。`candidates=[PHASE_A, PHASE_B]`。
  - **不正な理由**: 有限な evidence が 1 つもなく softmax が 0/0 になる。
  - **実際の発生シナリオ**: 候補が全て試料と無関係な場合の全滅。
- **期待される結果**: 例外なし・NaN なしで SearchResult が返る。`ranked` の各 `probability` が `math.isnan` でない (ガード方針: 確率均等 or ランキング末尾扱い — 実装時に確定した方針をこのテストで固定)。
  - **エラーメッセージの内容**: なし。
  - **システムの安全性**: 下流が確率値を安全に集計・表示できる。
- **テストの目的**: 全滅ケースの NaN 縮退ガード (note.md §6) を確認。
  - **品質保証の観点**: 数値健全性 (NaN/None 非返却) を担保。
- 🟡 信頼性レベル: ガードの必要性は note.md §6 / 要件定義書 §3 に依拠 🔵 だが、具体的なガード方針 (均等確率 or 末尾扱い) は実装時確定 🟡。

### TC-E04: 探索エンジン・SearchResult に削除・上書き API が存在しない (TC-008-03)

- **テスト名**: `test_no_destructive_api_on_engine_and_result`
  - **エラーケースの概要**: 非破壊性契約 (P2 / NFR-101) の静的検証。誤って mutation API が生えるリグレッションを防ぐ。
  - **エラー処理の重要性**: Dara 教訓 — 候補・仮説の削除/上書きは監査可能性を破壊する。
- **入力値**: `HypothesisTreeSearch` と `SearchResult` の公開属性名 (`dir()` から `_` 始まりを除外)。
  - **不正な理由**: `delete` / `remove` / `clear` / `overwrite` / `pop` / `update` 系の公開メソッドは契約違反。
  - **実際の発生シナリオ**: 将来のリファクタリングで utility メソッドが混入するケース。
- **期待される結果**: 両クラスの公開名に破壊系プレフィックス/名称が 1 つも含まれない。`SearchResult` は frozen dataclass でフィールド再代入が `dataclasses.FrozenInstanceError`。
  - **エラーメッセージの内容**: なし (構造検証)。
  - **システムの安全性**: 探索結果が事後改変できないことを型レベルで担保。
- **テストの目的**: 非破壊 API 契約 (TC-008-03) を確認。
  - **品質保証の観点**: 監査可能性 (REQ-402/405) の構造的担保。
- 🔵 信頼性レベル: 受け入れ基準 TC-008-03 / NFR-101 に直接依拠 (dir() による検証方式は 🟡)。

---

## 3. 境界値テストケース（上限・最小・決定論・閾値境界）

### TC-B01: max_phases=2 で 3 相仮説が生成されない (TC-003-02)

- **テスト名**: `test_max_phases_two_blocks_three_phase_hypotheses`
  - **境界値の意味**: 相数上限のちょうど超過側 (上限 2 に対し 3 相)。
  - **境界値での動作保証**: 上限到達枝は展開停止し、3 相の Hypothesis 自体が「生成前に」打ち切られる (EDGE-101)。
- **入力値**: `y = backend.simulate([PHASE_A, PHASE_B], tt)` に第 3 相を混ぜた 3 相合成 (A+B+C')、候補 4 以上、`SearchConfig(max_phases=2)`
  - **境界値選択の根拠**: 上限がなければ 3 相仮説が改善を生む状況を作り、上限だけが阻止要因になるよう設計。
  - **実際の使用場面**: 計算資源制約下で探索を浅く抑える運用。
- **期待される結果**: `all(len(h.phases) <= 2 for h in result.hypotheses.values())`。2 相仮説は存在する (上限ちょうどは生成される)。
  - **境界での正確性**: 「2 は許可 / 3 は不許可」の境界が正しい。
  - **一貫した動作**: TC-B02 (既定 5) と同一ロジックの設定値違い。
- **テストの目的**: max_phases ガード (REQ-401) を確認。
  - **堅牢性の確認**: 上限超の仮説がゼロ件であること (ID 連番にも穴を作らない実装なら尚良)。
- 🔵 信頼性レベル: 受け入れ基準 TC-003-02 / REQ-401 / EDGE-101 に直接依拠。

### TC-B02: SearchConfig 既定値の確認 — max_phases=5 ほか (TC-003-03)

- **テスト名**: `test_search_config_defaults`
  - **境界値の意味**: 設定契約の既定値そのもの (仕様の境界)。
  - **境界値での動作保証**: 既定 `SearchConfig()` が interfaces.py の全既定値と一致し frozen であること。
- **入力値**: `SearchConfig()` (引数なし構築)。
  - **境界値選択の根拠**: 既定値は FR-113/115/122 の仕様値。変更はリグレッション。
  - **実際の使用場面**: config 省略でコンストラクトする標準利用。
- **期待される結果**: `max_phases == 5`、`r_improve_pct == 2.0`、`match_tol_deg == 0.15`、`min_peak_height_frac == 0.05`、`prune_min_candidates == 4`、`jaccard_threshold == 0.85`、`explore_max_cycles == 5`、`final_full_refine is True`、`max_final_refine == 3`、`high_r_threshold == 30.0`、`close_threshold == 10.0`。フィールド再代入で `FrozenInstanceError`。
  - **境界での正確性**: 全 11 フィールドの既定値が仕様どおり。
  - **一貫した動作**: 既定 evidence が BICBackend (name=="bic") である `__init__` 既定も併せて確認 (REQ-004)。
- **テストの目的**: 設定契約 (interfaces.py L143-160) の固定。
  - **堅牢性の確認**: frozen による不変性。
- 🔵 信頼性レベル: 受け入れ基準 TC-003-03 / interfaces.py 既定値表 (要件定義書 §2.3) に直接依拠。

### TC-B03: 候補 1 相 → 深さ 1 の木・単一仮説 (TC-E04 / EDGE-102)

- **テスト名**: `test_single_candidate_yields_depth_one_tree`
  - **境界値の意味**: 探索空間の最小非空ケース (N=1)。
  - **境界値での動作保証**: 組合せ展開なしで単一仮説が評価・ランクされる。
- **入力値**: `y = backend.simulate([PHASE_A], tt)`、`candidates=[PHASE_A]`
  - **境界値選択の根拠**: best-first キューが 1 要素で開始即終了する下限。
  - **実際の使用場面**: 既知単相試料の確認解析。
- **期待される結果**: `len(result.hypotheses) == 1`、その仮説は 1 相・`parent_id is None` (深さ 1)、`ranked` 長 1、`probability == pytest.approx(1.0)` (単独 softmax)。
  - **境界での正確性**: 深さ 2 への展開が起きない (追加候補が存在しないため)。
  - **一貫した動作**: TC-E01 (N=0) と TC-N01 (N=4) の間を埋める。
- **テストの目的**: 最小探索空間での完走と木形状を確認。
  - **堅牢性の確認**: N=1 で枝刈り (候補 < 4 → -inf 全展開) が破綻しないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-E04 / EDGE-102 に直接依拠。

### TC-B04: 決定論 — 同一入力 2 回実行でランキング・確率がビット同一 (TC-001-05)

- **テスト名**: `test_deterministic_bit_identical_across_runs`
  - **境界値の意味**: 実行回数という境界を跨いだ完全再現性 (REQ-403 / NFR-102)。
  - **境界値での動作保証**: キュー順・組合せキー・ID 採番のすべてが入力のみに依存する。
- **入力値**: TC-N01 と同一の 2 相合成・4 候補入力で `search()` を独立に 2 回実行 (エンジンも 2 個生成)。
  - **境界値選択の根拠**: 決定論は「ほぼ同じ」では不可 — `pytest.approx` 禁止、`==` 比較。
  - **実際の使用場面**: 再解析・監査での結果再現。
- **期待される結果**: `[(r.hypothesis.id, r.probability, r.evidence) for r in run1.ranked] == [(...) for r in run2.ranked]` がビット同一 (`==`)。`hypotheses` のキー列・各仮説の phases / metrics も同一。ledger の kind 列が同順。
  - **境界での正確性**: float の `==` 一致 (丸め揺らぎゼロ)。
  - **一貫した動作**: 同点スコアは候補 index 昇順で固定 (順序規則の副検証)。
- **テストの目的**: 決定論契約 (TC-001-05) を確認。
  - **堅牢性の確認**: set/dict 順序・非安定ソート由来の非決定性がないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-001-05 / REQ-403 / NFR-102 に直接依拠。

### TC-B05: R 改善がちょうど r_improve_pct → 展開側 (境界包含 >=)

- **テスト名**: `test_r_improve_exactly_threshold_expands`
  - **境界値の意味**: 判定式 `parent_rwp - child_rwp >= r_improve_pct` の等号側 (`>=` か `>` かの分岐)。
  - **境界値での動作保証**: 改善がちょうど 2.0 ポイントの子は展開キューに入る (閾値包含)。改善 2.0 未満 (例 1.99) は打ち切り。
- **入力値**: FakeBackend — 親 {A} の rwp=10.0、子 {A,B} の rwp=8.0 (改善ちょうど 2.0)、子 {A,C} の rwp=8.01 (改善 1.99) を返す決定論スタブ。`SearchConfig(r_improve_pct=2.0)`。
  - **境界値選択の根拠**: SimulatedBackend では Rwp を厳密制御できないため、Protocol スタブで境界値を直接注入する。
  - **実際の使用場面**: 改善幅が閾値近傍の微妙な相追加判断。
- **期待される結果**: {A,B} は `hypotheses` に存在し展開扱い。{A,C} は展開されず `branch_prune` が記録される。
  - **境界での正確性**: 等号包含 (`>=`) が実装されていること。
  - **一貫した動作**: TC-N02 (明確な改善不足) と連続した判定規則。
- **テストの目的**: R 改善打ち切りの境界規則を固定。
  - **堅牢性の確認**: 浮動小数の等号境界で判定が揺れないこと。
- 🟡 信頼性レベル: 判定式・絶対ポイント解釈は interfaces.py / note.md §6 に依拠するが「絶対点解釈 + 等号包含」自体が 🟡 (実装時に docstring へ根拠を残し確定)。

### TC-B06: 候補 3 以下では枝刈り無効 (全展開へフォールバック) (TC-002-03 統合視点)

- **テスト名**: `test_fewer_than_min_candidates_disables_pruning`
  - **境界値の意味**: `prune_min_candidates=4` の直下 (候補 3) で dynamic_threshold が -inf に縮退する境界。
  - **境界値での動作保証**: 低スコア候補も含め全候補が深さ 1 ノードとして評価される (枝刈りで消えない)。
- **入力値**: `y = backend.simulate([PHASE_A], tt)`、`candidates=[PHASE_A, PHASE_C, PHASE_D]` (候補 3、C/D は低スコア)。
  - **境界値選択の根拠**: 候補 4 (TC-N05) では C/D が枝刈りされるのと対で、候補 3 では刈られないことを確認。
  - **実際の使用場面**: 候補が少ない絞り込み済み解析。
- **期待される結果**: 深さ 1 の単相仮説が 3 候補すべてについて `hypotheses` に存在する (jaccard 縮約で潰れない相異ピークを前提)。`prune_threshold` 記録の閾値が -inf 相当 (全展開) を示す。
  - **境界での正確性**: `min_candidates` 境界 (3 は無効 / 4 は有効) の食い違いがない。
  - **一貫した動作**: TASK-0004 の単体契約 (`dynamic_threshold` 縮退) と結線後も一致。
- **テストの目的**: 少数候補時の全展開フォールバックの結線を確認。
  - **堅牢性の確認**: -inf 閾値が比較演算 (`score >= threshold`) で安全に働くこと。
- 🟡 信頼性レベル: 受け入れ基準 TC-002-03 が 🟡 (妥当な推測) であることに準ずる。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 (CPython)
  - **言語選択の理由**: プロジェクト標準 (`pyproject.toml` src layout / hatchling / uv 0.9.x)。`search/` 配下の既存 4 モジュールと同一パッケージに `tree.py` を新設。
  - **テストに適した機能**: `dataclasses` (frozen 値オブジェクト)、Protocol による FakeBackend スタブ注入、型注釈、numpy ベクトル演算。
- **テストフレームワーク**: pytest >= 8 + pytest-cov
  - **フレームワーク選択の理由**: プロジェクト既定 (`[tool.pytest.ini_options]` `testpaths=["tests"]`)。既存 `tests/test_*.py` と同一様式。
  - **テスト実行環境**: `uv run pytest tests/test_tree_search.py` / `uv run pytest --cov=tsumugin`。**SimulatedBackend のみ使用・GSAS-II 非依存** (`@pytest.mark.gsas` 不要、`tests/conftest.py` の gsas skip に非該当)。
- 🔵 信頼性レベル: note.md §1・§5 / `pyproject.toml` / 既存テスト群に直接依拠。

**数値検証の使い分け (書式の範: `tests/test_pruning.py` / `tests/test_clustering.py`)**:
- 🔵 決定論のビット同一検証 (TC-B04) と ID・kind・構造の検証は `==` を使用 (`pytest.approx` 不可)。
- 🔵 gof 変換式・probability 等の物理量近似は `pytest.approx` を使用。
- 🔵 本タスクのテストは `tree.py` 直 import (`from tsumugin.search.tree import ...`) — `search/__init__.py` re-export は TASK-0007。

---

## 5. テストケース実装時の日本語コメント指針

`tests/test_pruning.py` / `tests/test_clustering.py` の書式に倣い、各テストに以下を付与する。

### テストケース開始時のコメント

```python
# 【テスト目的】: 2 相合成 (A+B)・4 候補で {A,B} 仮説が最上位ランクになることを確認 (TC-001-01)
# 【テスト内容】: SimulatedBackend の合成パターンに対する search() のフルパイプライン統合
# 【期待される動作】: ranked[0] の相集合 == {"A", "B"}
# 🔵 信頼性レベル: 受け入れ基準 TC-001-01 / REQ-001 に直接依拠
```

### Given（準備フェーズ）のコメント

```python
# 【テストデータ準備】: a=5.0 / 6.0 の 2 立方相を重ねた合成パターン (tt = 15–80°, step 0.02)
# 【初期条件設定】: 候補は真の 2 相 + 無関係 2 相 (a=4.5 / 7.0) — 枝刈りが有効になる候補 4 件
# 【前提条件確認】: 既定 SearchConfig() (max_phases=5, r_improve_pct=2.0, explore_max_cycles=5)
```

### When（実行フェーズ）のコメント

```python
# 【実際の処理実行】: HypothesisTreeSearch(backend).search(tt, y, candidates) を呼び出す
# 【処理内容】: find_peaks → match_score → jaccard 縮約 → dynamic_threshold → best-first 展開 → BIC → rank
# 【実行タイミング】: 入力構築直後 (乱数不使用・決定論のため副作用なし)
```

### Then（検証フェーズ）のコメント

```python
# 【結果検証】: ランキング先頭の仮説構成・hypotheses の系譜・ledger 記録を検証
# 【期待値確認】: {A,B} が 1 位、全 refined に evidence("bic")、parent_id が解決可能
# 【品質保証】: 非破壊性 (REQ-402/405) — 枝刈りは削除でなく ledger 記録で表現されることを担保
assert {p.phase_ref for p in result.ranked[0].hypothesis.phases} == {"A", "B"}  # 【検証項目】: 真の構成が最上位 🔵
assert result.ledger.verify()  # 【検証項目】: 監査ログの連鎖健全性 🔵
```

### セットアップ・クリーンアップのコメント

```python
# 合成データ (tt, y) と PhaseInstance 定数はモジュールレベルで一度だけ構築し、テスト間で不変共有する。
# SimulatedBackend / HypothesisTreeSearch は状態を持たない (純関数構成) ため fixture の後始末は不要。
# FakeBackend (RefinementBackend Protocol 準拠スタブ) は境界値・失敗注入テスト専用に定義する。
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `tree-search-core-requirements.md` §1 (木探索エンジン + SearchResult 骨格)、note.md §タスク要約
- **参照した入力・出力仕様**: requirements §2.1〜§2.5 (`__init__` / `search()` / `SearchConfig` 既定値 / `SearchResult` 骨格 / データフロー)、`interfaces.py` L143-199
- **参照した制約条件**: requirements §3 (決定論・非破壊・非例外化・探索モード精密化・枝刈り境界・R 改善打ち切り・相数上限・重複排除・ledger payload 型)、note.md §2・§6
- **参照した使用例**: requirements §4.1〜§4.4 (基本パターン / データフロー / 決定論・監査 / エッジケース)
- **参照した受け入れ基準**: `docs/spec/m1-hypothesis-search/acceptance-criteria.md` TC-001-01〜05 (L27-32)、TC-002-02/03 (L37-39)、TC-003-01〜03 (L44-46)、TC-008-01〜03 (L79-81)、TC-E01/E03/E04 (L85-88)

### テストケース ↔ 受け入れ基準/要件 トレーサビリティ

| テストケース | 対応する受け入れ基準 / 要件 | 信頼性 |
|-------------|-------------------------------|--------|
| TC-N01 | TC-001-01 / REQ-001 | 🔵 |
| TC-N02 | TC-001-02 / TC-003-01 / REQ-102/402 | 🔵 |
| TC-N03 | TC-001-03 / REQ-004 | 🔵 |
| TC-N04 | TC-001-04 / REQ-202 | 🔵 |
| TC-N05 | TC-002-02 (統合視点) / REQ-101 | 🟡 |
| TC-N06 | FR-114 / REQ-103 (alternatives 保持) | 🔵 |
| TC-N07 | TC-008-01 / REQ-402 | 🔵 |
| TC-N08 | TC-008-02 / dataflow.md kind 設計名 | 🔵 |
| TC-N09 | interfaces.py 契約 / requirements §2.2・§2.4 | 🔵 |
| TC-N10 | architecture.md D2 / REQ-003 / FR-113 | 🔵 |
| TC-E01 | TC-E01 / EDGE-001 | 🔵 |
| TC-E02 | TC-E03 / EDGE-004 / D2 | 🔵 |
| TC-E03 | note.md §6 (NaN ガード) / requirements §3 | 🟡 |
| TC-E04 | TC-008-03 / NFR-101 / REQ-405 | 🔵 |
| TC-B01 | TC-003-02 / REQ-401 / EDGE-101 | 🔵 |
| TC-B02 | TC-003-03 / interfaces.py 既定値表 | 🔵 |
| TC-B03 | TC-E04 / EDGE-102 | 🔵 |
| TC-B04 | TC-001-05 / REQ-403 / NFR-102 | 🔵 |
| TC-B05 | REQ-102 境界 (等号包含・絶対点解釈 🟡) | 🟡 |
| TC-B06 | TC-002-03 (候補 3 以下は全展開) | 🟡 |

---

## 7. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 10 / 異常系 4 / 境界値 6 = 20 件で網羅
  (TASK-0006 完了条件の TC-001-01〜05 / TC-003-01〜03 / TC-008-01〜03 / TC-E01/E03/E04 の 14 基準を全カバー
   + 統合視点 TC-002-02/03 + D2 呼び出し契約 + NaN ガード)
- 期待値定義: 各ケースに具体的な入力構築・期待戻り値・判定式・ledger kind を明記
- 技術選択: Python 3.12 + pytest 8 + numpy + SimulatedBackend / FakeBackend スタブ (確定)
- 実装可能性: interfaces.py L143-199 に契約確定、前提 TASK-0004/0005 完了、M0 資産すべて実在
- 信頼性レベル: 🔵 16 / 🟡 4 / 🔴 0 — 中核契約は受け入れ基準・設計文書に直接依拠
```

- **残る 🟡 (Red → Green で挙動を確定させ docstring に根拠を残す)**:
  (a) R 改善判定の絶対ポイント解釈 + 等号包含 `>=` (TC-B05)、
  (b) 全仮説 chi2=inf 時の NaN ガード方針 — 確率均等 or ランキング末尾 (TC-E03)、
  (c) 候補ピーク生成方式 simulate → find_peaks の較正 — PHASE_A〜D の a 値が偶然一致しないこと (共通データ)、
  (d) 候補 3 以下の全展開フォールバックの結線挙動 (TC-B06)。
- **次のステップ**: `/tsumiki:tdd-red` で `tests/test_tree_search.py` に本 20 ケースの失敗テストを実装する。
