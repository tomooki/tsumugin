# TASK-0035 TDD 開発コンテキストノート

**タスク**: M3 公開 API 統合 + E2E + ドキュメント (M3 operando 総仕上げ / 最終統合タスク)。
`src/tsumugin/__init__.py` へ M3 公開シンボルを **非破壊 re-export** し、operando 一気通貫 E2E
(`tests/test_operando_e2e.py`) を追加、README M3 使用例・`docs/dev/context.md`・検証レポートを整備する。
**要件名**: m3-operando / **タスクID**: TASK-0035 / **タイプ**: TDD / **推定 4h**
**フェーズ**: Phase 5 / **信頼性**: 🔵 5/5 (M0〜M2 統合タスク TASK-0022 の踏襲)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando (想定)
**依存タスク**: 前提 TASK-0023〜0034 (全完了) / 後続 なし (M3 PR へ)。

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

M3 で追加した operando 各層 (multistart / absorption / echem / cell_phases / discrimination /
segmentation / hysteresis / output / model.cell) の公開シンボルを **トップレベル `tsumugin` 名前空間へ
re-export** し、`from tsumugin import MultistartEngine, ...` を成立させる (完了条件①)。加えて、公開 API のみで
operando 一気通貫パイプラインを結線する **E2E テスト** を追加する (完了条件②③)。実装ロジックは新規に書かず、
**配線 (re-export) + 結線検証 (E2E) + ドキュメント** に徹する統合タスク。

### 0.1 公開 API 統合 (`src/tsumugin/__init__.py`) 🔵

- **既存 `__init__.py` の `__all__` はアルファベット昇順 (L65-118)** で、`test_m1/m2_symbols_in_dunder_all_and_sorted`
  が `list(__all__) == sorted(__all__)` を固定している。M3 シンボルも **昇順維持で非破壊追記** する (既存 M0/M1/M2
  シンボルは 1 つも削除・改名しない = REQ-404)。
- 追記対象は各サブパッケージ実体からの **re-export** (別実装・コピーでなく `is` 同一実体)。先例 (M2) は
  `assert SequentialEngine is tsumugin.sequential.SequentialEngine` を検証している (`tests/test_m2_e2e.py` L304-308)。
- **再エクスポート元と候補シンボル** (all public M3 surface):
  - `tsumugin.multistart` → `MultistartEngine` / `MultistartConfig` / `MultistartResult` / `BasinInfo` /
    `PerturbationSpec` / `cluster_basins` / `generate_starts`
  - `tsumugin.absorption` → `AbsorptionConfig` / `transmission_factor`
  - `tsumugin.operando` → `read_echem_csv` / `EchemData` / `EchemLoader` / `BiologicMprLoader` /
    `CELL_PHASE_PRESETS` / `FixedPhaseSpec` / `fixed_free_suffixes` / `DiscriminationConfig` /
    `DiscriminationResult` / `discriminate_interval` / `SegmentationConfig` / `SegmentationResult` /
    `segment_series` / `combined_csv` / `transition_point` / `TransitionPoint` / `BranchComparison` /
    `split_branches` / `branch_differences`
  - `tsumugin.model` (M3 セル系。現状トップレベル未 re-export) → `CellConfig` / `CellLayer` / `BeamConfig` /
    `MuCalculator` / `XraylibMuCalculator`
- **どこまでトップレベルへ昇格するか** は tdd-requirements で確定 (タスク文が明示するのは `MultistartEngine` /
  `MultistartConfig` / `CellConfig` / `AbsorptionConfig` / `read_echem_csv` / `EchemData` /
  `CELL_PHASE_PRESETS` / `discriminate_interval` / `segment_series` / `combined_csv` の 10 中核 + "等")。
  **推奨案 = M3 公開面全体 (上記) を昇順で昇格** (M2 が sequential/selection/store/model の全公開面を昇格した先例に倣う)。

### 0.2 E2E テスト (`tests/test_operando_e2e.py`) 🔵

**TC-209-01 (一気通貫・マーカー無し / SimulatedBackend)**: echem CSV 同期 → セル固定相込み逐次解析 →
IC 区間分割 → 区間ごと FR-313 判別 (マルチスタート) → 結合出力 CSV → `ledger.verify()` まで完走する。
公開 API (`from tsumugin import ...`) のみを使う (サブパッケージ直 import しない = 配線検証)。

**TC-209-02 (@gsas)**: `GSASIIBackend` で `MultistartEngine(backend, config=MultistartConfig(n_starts=4)).run(...)`
の N=4 smoke が完走する (GSAS-II 未導入環境は `tests/conftest.py` が自動 skip)。

**TC-209-03 (NFR-001 / 🟡)**: 判別 1 区間 (N=8) が 30 秒以内。

### 0.3 ドキュメント

- **README.md**: 「使い方 (M3): operando 解析」節を追加 (M2 節 L116-161 と同型)。使用例コードは E2E で
  写経実行して回帰保護する (M2 の `test_readme_m2_example_executes` L669 が先例)。
- **docs/dev/context.md**: 「M3 実装済み」の 1 行追記 (M2 行 L 末尾に続けて operando 層を記載)。
- **検証レポート**: `docs/tasks/m3-operando/reports/verification.md` (ディレクトリ未作成 = 新規作成)。全テスト green・
  カバレッジ 90%+・ruff clean の結果を記録。

**🚨 絶対制約 (完了条件 = AC TC-209)**:
1. `from tsumugin import MultistartEngine, ...` で M3 API が利用可能 🔵 *完了条件① / TC-209 前提*
2. TC-209-01 一気通貫 E2E green 🔵
3. (@gsas) TC-209-02 マルチスタート N=4 smoke 🔵
4. 全テスト green・カバレッジ 90% 以上・ruff clean (line-length 100) 🔵
5. README M3 例 (実行確認) + context.md 更新 + 検証レポート 🔵
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行・推奨案で確定)。
- **既存テスト無改変で green** (後方互換 REQ-404)。`__all__` は昇順維持。
- 非破壊性 (P2): re-export のみ。既存モジュールのロジック改変・破壊 API 追加をしない。

**⚠️ スコープ外**: 新規解析ロジックの実装 (TASK-0023〜0034 で完了済み)。本タスクは配線・E2E・ドキュメントに徹する。
MEM / nested sampling / REST/MCP / joint refinement は M4+ スコープ。

**参照元**: `docs/tasks/m3-operando/TASK-0035.md`, `docs/spec/m3-operando/acceptance-criteria.md` (TC-209-01〜03 / L82-85),
`tests/test_m2_e2e.py` (統合タスク先例), `src/tsumugin/__init__.py` (現行 __all__ L65-118)

---

## 1. 技術スタック

- **言語 / ランタイム**: Python >=3.12 (`pyproject.toml`、uv 管理、src layout + hatchling)。数値は numpy のみ (REQ-403)。
  CSV は stdlib `csv`。
- **依存導入**: `uv sync --extra gsas` (**プレーン `uv sync` は禁止** — gsas 依存が外れる)。
- **テスト**: `uv run pytest` / カバレッジ `uv run pytest --cov=tsumugin`。GSAS-II 限定 `uv run pytest -m gsas`
  (未導入環境で自動 skip)。Lint `uvx ruff check src tests` (line-length 100)。
- **GSAS-II** (TC-209-02 用): ソースツリー `C:\Users\tomoo\G2` + venv の `gsas2-source.pth` + バイナリ
  `~/.GSASII/GSASII-bin/win_64_p3.12_n2.2`。import は `from GSASII import GSASIIscriptable`。
- **アーキテクチャパターン**: 不変データ (frozen dataclass + `with_updates()`) + `typing.Protocol` 境界 + 純関数コア +
  追記専用 Ledger。本タスクの成果物は **パッケージ `__init__` の re-export (配線)** と **E2E テスト (結線検証)** のみ。
- **本タスクの対象**: `src/tsumugin/__init__.py` (re-export 追記) / `tests/test_operando_e2e.py` (新規) /
  `README.md` / `docs/dev/context.md` / `docs/tasks/m3-operando/reports/verification.md` (新規)。
- **参照元**: `pyproject.toml`, `CLAUDE.md` (L15-27, L63-77), `docs/dev/context.md`

## 2. 開発ルール

- **TDD 厳守**: tdd-red (E2E 失敗テスト) → tdd-green (re-export 最小追記で通す) → tdd-refactor →
  tdd-verify-complete。テストなしの実装コミット禁止。統合タスクの Red 機構は「M3 シンボルがトップレベル未
  re-export のため `from tsumugin import MultistartEngine, ...` が collection 時 ImportError で全テスト失敗」
  (M2 `tests/test_m2_e2e.py` L50-52 と同一方針)。
- **`__all__` は昇順維持** (`list(tsumugin.__all__) == sorted(tsumugin.__all__)`)。M0/M1/M2 分は削除・改名禁止
  (REQ-404 / `tests/test_m2_e2e.py` L311-327)。
- **re-export は同一実体** (`X is tsumugin.<subpkg>.X`)。別実装・ラッパを作らない。
- **決定論 (NFR-102)**: E2E は乱数不使用。物理量は `pytest.approx`、決定論は `==` ビット同一、非有限漏洩は
  `math.isfinite` で検証 (M2 E2E の慣習)。CSV バイト同一で再現性を担保。
- **非破壊性 (P2 / NFR-105)**: E2E は共有 `Ledger` を segment/discriminate へスレッドし、末尾で `verify() is True` +
  `len(entries) > 0` (空 ledger の自明 True でない) を確認。破損検知は既存テストが担保済み。
- **テスト配置**: `tests/test_operando_e2e.py` (新規)。命名 `test_*`、日本語コメント【テスト目的】【テスト内容】
  【期待される動作】+ 信頼性レベル 🔵🟡 (先例 `tests/test_m2_e2e.py` / `tests/test_discrimination.py`)。
- **実行時間の抑制**: 一気通貫は module スコープ fixture で 1 回だけ実行し正常系で読み取り専用共有する
  (M2 `warming_run` fixture L220-251 の範)。観測グリッドは判別/分割テストと同較正の粗グリッド (下記 §5)。
- **参照元**: `CLAUDE.md` (L29-77), `tests/test_m2_e2e.py`, `docs/implements/m3-operando/TASK-0034/note.md` (直近先例)

## 3. 関連実装 (実 API 確認済み — Explore 精査済み)

> すべて実装完了・テスト green の資産。本タスクはこれらを **公開面へ配線** し **公開 API 経由で結線** する。

### 3.1 `src/tsumugin/multistart/` — マルチスタート (TASK-0027/0028 完了) 🔵
- **`MultistartEngine(backend, *, config=MultistartConfig(), ledger=None)`** / メソッド
  `run(phases: tuple[PhaseInstance,...], two_theta: np.ndarray, intensity: np.ndarray, *, free_suffixes=("scale","lattice.a","lattice.b","lattice.c"), weights=None) -> MultistartResult` (`engine.py` L54-84)。
  N 本の摂動 start を direct refine → 発散除外 → basin クラスタ → 複数 basin なら昇格。**TC-209-02 の主対象**。
- **`MultistartConfig(n_starts=8, spec=PerturbationSpec(), basin_rel_tol=1e-2, ms_max_cycles=15)`** (frozen, `perturb.py` L36-49)。
  **N は `n_starts`** (seed フィールドは無い = 乱数不使用の決定論生成)。TC-209-02 は `MultistartConfig(n_starts=4)`。
- **`MultistartResult(basins, n_starts, n_diverged, promoted, is_global_corroborated, warnings=())`** (frozen, `engine.py` L36-51)。
- **`BasinInfo(representative, member_starts, chi2, evidence)`** / `cluster_basins(results, *, basin_rel_tol=1e-2)` / `generate_starts(phases, *, config)`。
- **参照元**: `src/tsumugin/multistart/engine.py`, `perturb.py`, `basin.py`, `src/tsumugin/multistart/__init__.py`

### 3.2 `src/tsumugin/absorption/model.py` — 吸収補正 v1 (TASK-0026 完了) 🔵
- **`AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=None, restraint_weight=100.0, empirical_mode=False, restraint_width=0.3)`** (frozen)。
  staticmethod `from_cell_config(config: CellConfig) -> AbsorptionConfig` / `empirical() -> AbsorptionConfig`。
- **`transmission_factor(two_theta_deg: np.ndarray, mu_t: float) -> np.ndarray`** (A = exp(-μt/cosθ))。
- **参照元**: `src/tsumugin/absorption/model.py`, `src/tsumugin/absorption/__init__.py`

### 3.3 `src/tsumugin/operando/echem.py` — echem 同期 (TASK-0029 完了) 🔵
- **`read_echem_csv(path: str, *, column_map: Mapping[str,str], capacity_to_x: tuple[float,float]|None=None) -> EchemData`** (L76-81)。
  `column_map` は論理名 ("frame"/"voltage"/"current"/"capacity") → CSV 列名。**"frame" が同期キー**。
  `capacity_to_x=(slope, intercept)` で x = slope·Q + intercept。欠損列は `ValueError`、行不揃いは None + `UserWarning`。
  **TC-209-01 の入口 (echem CSV 同期)**。
- **`EchemData(voltage, current=(), capacity=(), composition_x=())`** (frozen)。各 `tuple[float|None,...]`、位置 index = frame_index。
  `to_channels() -> tuple[ExternalChannel,...]` で `FrameSeries.channels` へ供給可。
- `EchemLoader` (Protocol: `load(path)->EchemData`) / `BiologicMprLoader` (`load` は NotImplementedError スタブ)。
- **参照元**: `src/tsumugin/operando/echem.py`

### 3.4 `src/tsumugin/operando/cell_phases.py` — セル固定相 (TASK-0030 完了) 🔵
- **`CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]`** (read-only `MappingProxyType`, L123)。キー `"Be"` / `"Al"` /
  `"graphite"`。`CELL_PHASE_PRESETS["Al"].phase` (PhaseInstance) / `.label`。**TC-209-01 の "セル固定相"**。
- **`FixedPhaseSpec(phase: PhaseInstance, label: str)`** (frozen)。`fixed_free_suffixes(spec) -> ("scale",)` (構造固定・scale のみ解放)。
- **参照元**: `src/tsumugin/operando/cell_phases.py`

### 3.5 `src/tsumugin/operando/segmentation.py` — IC 区間分割 (TASK-0033 完了) 🔵
- **`segment_series(backend, series: FrameSeries, initial_phases: tuple[PhaseInstance,...], *, config=SegmentationConfig(), fixed_phases: tuple[FixedPhaseSpec,...]=(), ledger=None) -> SegmentationResult`** (L89-97)。
  `ledger=None` なら内部で `Ledger()` を生成し結果に格納。**`fixed_phases` でセル固定相を常駐** (scale のみ解放)。
  **TC-209-01 の "セル固定相込み逐次解析 + IC 区間分割"** を担う (内部で区間 warm-start direct refine を実施)。
- **`SegmentationResult(boundaries, n_segments, evidence_by_k, partitions, ledger, warnings=())`** (frozen)。
  **`boundaries: tuple[int,...]`** (昇順・端 0/n 含まず) が **判別対象区間の切れ目** = discriminate_interval の入力。
- **`SegmentationConfig(penalty_beta=5.0, improvement_threshold=10.0, coarse_step=5, max_segments=6, seq_max_cycles=10)`**。
- **参照元**: `src/tsumugin/operando/segmentation.py`

### 3.6 `src/tsumugin/operando/discrimination.py` — FR-313 判別 (TASK-0032 完了) 🔵
- **`discriminate_interval(backend, series: FrameSeries, frame_range: tuple[int,int], initial_phases: tuple[PhaseInstance,...], *, config=DiscriminationConfig(), fixed_phases: tuple[FixedPhaseSpec,...]=(), ledger=None, queue=None) -> DiscriminationResult`** (L111-121)。
  入力は **FrameSeries + frame_range (両端 inclusive) + initial_phases** (生パターンでない)。**区間端点でマルチスタート必須適用**。
  **TC-209-01 の "区間ごと FR-313 判別 (マルチスタート)"**。
- **`DiscriminationConfig(close_threshold=10.0, multistart=MultistartConfig(), high_r_threshold=30.0, seq_max_cycles=10)`** (frozen)。
  **マルチスタート N は `config.multistart.n_starts` (既定 8)**。TC-209-03 の N=8 はこの既定。実行時間短縮は `DiscriminationConfig(multistart=MultistartConfig(n_starts=2))` (テスト先例 `test_discrimination.py` L59)。
- **`DiscriminationResult(verdict, delta_evidence, hypothesis_single, hypothesis_two_phase, multistart_single, multistart_two_phase, escalations, warnings=())`** (frozen)。
  **`verdict: Literal["solid_solution","two_phase","undecided"]`**。僅差/高 R は auto 確定せず ReviewQueue へエスカレーション。
- **参照元**: `src/tsumugin/operando/discrimination.py`

### 3.7 `src/tsumugin/operando/output.py` — 結合出力 (TASK-0034 完了) 🔵
- **`combined_csv(trajectory: Trajectory, echem: EchemData, path: str) -> str`** (L121)。`Trajectory` (=
  `tsumugin.sequential.trajectory.Trajectory`) と `EchemData` を **frame_index で外部結合**し CSV 書き出し、パスを返す。
  非有限/None は空欄。**TC-209-01 の "結合出力 CSV"**。
- **`transition_point(echem: EchemData, frame_index: int) -> TransitionPoint`** (L79)。境界フレームの x/V±σ を隣接補間で導出。
  boundaries の各要素を TransitionPoint 化するのが E2E の自然な流れ。
- **`TransitionPoint(frame_index, x, voltage, sigma_x, sigma_v)`** (frozen)。
- **参照元**: `src/tsumugin/operando/output.py`

### 3.8 `src/tsumugin/operando/hysteresis.py` — ヒステリシス (TASK-0034 完了) 🔵
- **`split_branches(x_values) -> (charge_idx, discharge_idx)`** / **`branch_differences(x_values, values, *, n_grid=20) -> tuple[BranchComparison,...]`** /
  **`BranchComparison(x, charge_value, discharge_value, difference)`** (frozen)。TC-209-01 の必須経路ではないが公開面には含める。
- **参照元**: `src/tsumugin/operando/hysteresis.py`

### 3.9 `src/tsumugin/model/cell.py` — セル構成 (TASK-0023 完了) 🔵
- **`CellConfig(geometry: Literal["transmission","capillary"], layers=(), beam=None, mu_t_calc=None)`** (frozen, L47-64)。
  **すでに `tsumugin.model.__init__` 経由で re-export 済み** (`from tsumugin.model import CellConfig`) だが **トップレベル `tsumugin` は未 re-export**。
  タスク文が明示的に昇格対象へ列挙 (`TASK-0035.md` L11)。
- 併存: `CellLayer` / `BeamConfig` / `MuCalculator` (Protocol) / `XraylibMuCalculator` (mu_t は NotImplementedError スタブ)。
- **参照元**: `src/tsumugin/model/cell.py`, `src/tsumugin/model/__init__.py` (L5, L13)

### 3.10 `src/tsumugin/sequential/` — Trajectory 供給元 (M2 完了) 🔵
- **`SequentialEngine(backend, *, candidates=(), evidence=None, config=SequentialConfig(), ledger=None, snapshots=None)`** /
  `run(series: FrameSeries, initial_phases) -> SequentialResult`。`SequentialResult.trajectory: Trajectory` を持つ。
- **⚠️ 重要**: `SequentialEngine` は **`fixed_phases` / `CellConfig` / `cell` パラメータを持たない**。per-frame direct refine が
  全相の scale + 格子 a/b/c を解放するため、固定相を initial に混ぜても構造固定にならない。→ **"セル固定相込み逐次解析" は
  `segment_series` / `discriminate_interval` 側の区間内 warm-start refine が担う** (両者が `fixed_phases` を受ける)。
- combined_csv 用 `Trajectory` の入手経路は E2E 設計判断 (§6-2)。
- **参照元**: `src/tsumugin/sequential/engine.py` (L123-158), `src/tsumugin/sequential/trajectory.py`

## 4. 設計文書

- **完了条件 / AC**: `docs/spec/m3-operando/acceptance-criteria.md` TC-209-01〜03 (L82-85)。E2E サマリ「統合 E2E: 3 件」(L101)。
- **タスク定義**: `docs/tasks/m3-operando/TASK-0035.md` (公開 API シンボル列挙 L10-14 / 完了条件 L20-24 / 実装手順 TDD L27)。
- **データフロー (一気通貫)**: `docs/design/m3-operando/dataflow.md` — echem 同期 → 固定相込み逐次 → 区間分割 →
  区間判別 (マルチスタート) → 結合出力/ヒステリシス。TC-209-01 はこの縦串を公開 API で再現する。
- **契約 (interfaces.py)**: `docs/design/m3-operando/interfaces.py` — 各 dataclass/関数シグネチャの正 (実装は §3 で確認済み実 API と一致)。
  `CellConfig` は L60 で定義。
- **要件**: `docs/spec/m3-operando/requirements.md` REQ-016 (CellConfig / L70)・REQ-404 (後方互換)・NFR-001 (30 秒 / TC-209-03)。
- **統合タスク先例**: M2 の TASK-0022 (`docs/implements/m2-sequential/TASK-0022/` があれば参照) と `tests/test_m2_e2e.py`。
- **参照元**: `docs/spec/m3-operando/acceptance-criteria.md`, `docs/tasks/m3-operando/TASK-0035.md`,
  `docs/design/m3-operando/dataflow.md`, `docs/design/m3-operando/interfaces.py`, `docs/spec/m3-operando/requirements.md`

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov (`pyproject.toml [tool.pytest.ini_options]`, testpaths=["tests"])。
  `tests/conftest.py` が GSAS-II 未導入環境で `@pytest.mark.gsas` を自動 skip → **TC-209-02 のみ @gsas、他は backend 非依存**。
- **新規テストファイル**: `tests/test_operando_e2e.py`。TC-209-01 (一気通貫) / TC-209-02 (@gsas smoke) / TC-209-03 (性能)
  に加え、公開 API 配線検証 (M3 シンボルが `from tsumugin import ...` 解決 + `__all__` 昇順包含 + 同一実体) を追加する
  (M2 `test_m2_public_symbols_are_reexported` / `test_m2_symbols_in_dunder_all_and_sorted` の範)。
- **合成データ (決定論)**:
  - **FrameSeries**: `SimulatedBackend(peak_fwhm=0.2)` で相を simulate し `(n_frames, n_points)` 行列を組む。グリッドは
    判別/分割テストと同較正の **`np.arange(15.0, 60.0, 0.05)`** (固定相 Al の (211)≈55.5° まで捉え <30 秒 smoke)。
    二相反応系列は端成分 α/β の scale 漸移 (`test_discrimination.py` `_two_phase_series` L77-93)、固溶体は単相格子の
    連続変化 (`_solid_solution_series` L67-74)。固定相重畳は `CELL_PHASE_PRESETS["Al"].phase.with_updates(scale=0.7)` (L99)。
  - **echem CSV**: `tmp_path` に frame/voltage/capacity 列の小 CSV を書き `read_echem_csv(path, column_map={"frame":..,"voltage":..,"capacity":..}, capacity_to_x=(slope,intercept))` で読む (`test_echem.py` の慣習に倣う)。
  - **@gsas smoke (TC-209-02)**: `GRID_GSAS = np.arange(20.0, 80.0, 0.05)`、立方相 1 相、`MultistartEngine(GSASIIBackend(), config=MultistartConfig(n_starts=4)).run(phases, two_theta, intensity)` (`test_m2_e2e.py` L497-519 の @gsas パターン)。
- **共有 fixture**: 一気通貫は module スコープ fixture で 1 回実行し正常系で読み取り専用共有 (`test_m2_e2e.py` `warming_run` L220)。
- **決定論検証**: E2E を 2 回実行し `verdict` / `boundaries` / CSV バイト列が `==` 一致。物理量は `pytest.approx`。非有限漏洩は
  `math.isfinite`。
- **ledger 検証**: 共有 `Ledger` を segment/discriminate へ渡し末尾で `verify() is True` + `len(entries) > 0`。
- **README 回帰**: `test_readme_m3_example_executes` で README M3 使用例コードを写経実行し完走検証 (M2 L669 先例)。
- **実行**: `uv run pytest tests/test_operando_e2e.py` / `uv run pytest -m gsas` / `uv run pytest --cov=tsumugin` (90%+)。
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_m2_e2e.py`, `tests/test_discrimination.py`,
  `tests/test_segmentation.py`, `tests/test_echem.py`, `tests/test_multistart_engine.py`

## 6. 注意事項

### ⚠️ 設計判断フラグ (tdd-requirements / tdd-testcases / tdd-red で確定すべき点)

1. **昇格シンボルの範囲**: タスク文の明示 10 中核 + "等" をどこまで広げるか。**推奨案 = M3 公開面全体 (§0.1 の全シンボル)
   を昇順で昇格** (M2 の全公開面昇格の先例に一致・公開面の一貫性)。`hysteresis` 系 (`split_branches` 等) や `EchemLoader` /
   `BiologicMprLoader` / `MuCalculator` / `XraylibMuCalculator` の昇格是非を tdd-requirements で 1 つに固定する。
2. **combined_csv 用 Trajectory の入手経路**: `SequentialEngine` は `fixed_phases` 非対応 (§3.10)。E2E で結合出力用の
   `Trajectory` をどう作るか — **推奨案: (a) 固定相を初期相に含めた `SequentialEngine.run` でトラジェクトリを得て
   combined_csv へ渡す** (固定相の格子は refine で微動するが CSV 出力の結線検証には十分)、または (b) 判別/分割の
   端点相から Trajectory を手組み。TC-209-01 の主眼は「echem 列入り CSV が生成・読み戻せる」ことなので (a) が軽量。
   tdd-red で結線を凍結。
3. **E2E の "逐次解析" の実体**: "セル固定相込み逐次解析" は独立の SequentialEngine 実行ではなく、
   `segment_series` / `discriminate_interval` が内部で回す **区間 warm-start direct refine** を指す (fixed_phases 常駐)。
   tdd-testcases でこの解釈を明記し、固定相の scale-only 解放が効いていること (verdict が破綻しない) を確認する。
4. **区間 → 判別のループ**: `segment_series` の `boundaries` から区間 `[(0,b0),(b0,b1),...,(bk,n-1)]` を構成し
   各区間へ `discriminate_interval` を適用する索引規約 (両端 inclusive / 境界の帰属) を凍結。最小 E2E は 1〜2 区間で足りる。
5. **ledger の一本化**: segment_series は `ledger=None` で内部 Ledger を生成するため、E2E では **共有 Ledger を明示注入**
   (segment と discriminate に同一 Ledger を渡す) して 1 本のハッシュチェーンに集約し `verify()` する。tdd-red で注入経路を固定。
6. **性能 (TC-209-03 / NFR-001 / 🟡)**: 判別 1 区間 N=8 が 30 秒以内。粗グリッド (step 0.05) + 小フレーム数 (n=8 程度) +
   N=8 で担保。CI 変動を見て閾値マージンを取る (M2 の 100 フレーム 60 秒 smoke L710 の流儀)。
7. **後方互換の回帰**: 既存 `tests/test_m1_e2e.py` / `tests/test_m2_e2e.py` の `__all__` 検証が **昇順 + M0/M1/M2 非削除**
   を固定している。M3 追記後もこれらが green であることを tdd-verify-complete で確認 (追記漏れ・順序崩れの検出)。

### その他の技術的制約

- **非破壊 (P2 / REQ-404)**: `__init__.py` は re-export の追記のみ。既存モジュールのロジック・シグネチャを変えない。
  operando/multistart/absorption の各サブパッケージ `__all__` は既に全公開面を列挙済み (無改変で流用可)。
- **numpy のみ** (REQ-403): E2E の合成データ生成も numpy + SimulatedBackend。pandas 等を持ち込まない。
- **カバレッジ**: 90% 以上 (完了条件④)。統合タスクは新規実装が薄いので既存カバレッジを維持しつつ E2E で結線経路を通す。
- **ドキュメントの実行確認**: README M3 例は E2E で写経実行し、文面と公開 API 実シグネチャの乖離を防ぐ。
- **参照元**: `CLAUDE.md` (不変条件 L40-49), `docs/spec/m3-operando/requirements.md` (REQ-403/404),
  `src/tsumugin/operando/__init__.py`, `src/tsumugin/multistart/__init__.py`, `src/tsumugin/absorption/__init__.py`
