# TASK-0019 開発コンテキストノート — SequentialEngine (オンライン逐次精密化 + 局所木探索)

**要件名**: m2-sequential / **タスクID**: TASK-0019 / **タスクタイプ**: TDD / **推定工数**: 6h
**対象実装**: `src/tsumugin/sequential/engine.py` (新規) / **テスト**: `tests/test_sequential_engine.py` (新規)
**フェーズ**: Phase 3 - エンジン / **信頼性レベル**: 🔵 FR-301〜305 / REQ-001/002/101/105 / 設計 D1〜D3
**作成日**: 2026-07-03

> このノートは TDD 各フェーズ (requirements → testcases → red → green → refactor → verify) が
> 再探索なしで参照できるコンテキスト集約。全パスはプロジェクトルート相対。

---

## 1. 技術スタック

- **言語**: Python 3.12 (uv 管理、src layout + hatchling)
- **数値計算**: numpy (>=1.26) のみ (コア依存)。CSV は stdlib `csv`、JSONL は stdlib `json`。
- **アーキテクチャパターン**: 「不変データ (frozen dataclass) + Protocol 境界 + 追記専用ストア」。
  本タスクは**オンライン単一パス**のオーケストレーション本体 (フレーム順に 検出→対応→継続)。
- **決定論 (NFR-102)**: 乱数禁止・安定ソート。ローリング統計は中央値/MAD。同一入力 2 回でビット同一 (`==`)。
- **テスト**: pytest (`uv run pytest`)。カバレッジ `uv run pytest --cov=tsumugin`。既存 226 件 (M0/M1) を無改変で維持。
- **Lint**: `uvx ruff check src tests` (line-length 100)。
- 参照元: `CLAUDE.md`, `pyproject.toml`, `docs/design/m2-sequential/architecture.md`

## 2. 開発ルール

- **frozen dataclass + 非破壊更新** (`dataclasses.replace` / `with_updates`)。snake_case / PascalCase、日本語 docstring 可、型注釈必須。
- **非有限値を漏らさない (M1 教訓)**: 精密化失敗フレームは例外化せず `chi2=inf` の結果として扱い、
  `rwp`/`chi2` は下流 (FrameRecord) に None で伝播 (`inf`/`nan` を漏らさない)。EDGE-002。
- **後方互換 (REQ-404)**: model 拡張フィールド (`PhaseInstance.lifecycle` / `Hypothesis.frame_range`) は
  末尾・既定 None 済み (実装確認済)。既存テスト無改変で通ること。
- **ledger/snapshots は注入式**: 既定は in-memory (`Ledger`/`SnapshotStore`)、Persistent 版を注入可能 (REQ-012)。
- **純関数的ノード評価 (REQ-404 並列化余地)**: 局所木探索は `HypothesisTreeSearch` に委譲 (自前で乱数を持たない)。
- **モジュール実装後は `src/tsumugin/sequential/__init__.py` に re-export を追加** (既存 series/changepoint/lifecycle/thermal/trajectory と同様)。
- **信頼性レベル注記**: コード/テストのコメントに 🔵(仕様依拠) / 🟡(妥当な推測) / 🔴(根拠なし) を付す慣習。
- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなしの実装禁止。
- 参照元: `CLAUDE.md`, `src/tsumugin/search/tree.py`, `src/tsumugin/sequential/changepoint.py`, `src/tsumugin/sequential/__init__.py`

## 3. 関連実装 (再利用する実 API — 実装済み資産の署名を確認済み)

本タスクは**新規ロジックは薄く、既存部品のオーケストレーション**が主。以下は実装確認済みの実 API。

### 3.1 フレーム精密化 (D2 の 2 段構え)
- **初回フレーム (frame 0)**: `StagedRefinementEngine` フル確立 (`first_frame_staged=True` 時)。
  - `src/tsumugin/refinement/staged.py`:
    `StagedRefinementEngine(backend, store, ledger, *, template=DEFAULT_STAGE_TEMPLATE, config=GuardConfig(), max_retries=3, worsen_tol=1e-9)`
  - `run(phases: tuple[PhaseInstance,...], two_theta: np.ndarray, intensity: np.ndarray, *, weights=None) -> RefinementReport`
  - `RefinementReport(final_phases, metrics: RefinementMetrics, stage_outcomes, escalated, free_params)`
- **後続フレーム (i>=1)**: `backend.refine` 直呼び (scale + lattice、`max_cycles=seq_max_cycles` 既定 10)。
  - `src/tsumugin/backends/base.py`:
    `RefinementBackend.refine(model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult` (Protocol, runtime_checkable)
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)`
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params)`
  - `param_name(phase_index: int, key: str) -> str` → `"phase{i}.{key}"` (free_params 構築に使用)。
    探索キーは `_EXPLORE_KEYS = ("scale","lattice.a","lattice.b","lattice.c")` (tree.py 参照、後続フレームも同種)。
- **warm start**: 直近**成功**フレームの `final_phases` / `result.phases` を次フレームの入力 phases に渡す (EDGE-002)。
  - `inherit="phases"` (既定): 相集合ごと継承 / `inherit="lattice_only"`: 格子のみ継承 (scale 等は初期値へ) 🟡 TC-101-03。

### 3.2 フレーム指標 → changepoint 検出
- `src/tsumugin/sequential/changepoint.py`:
  `detect_changepoint(rwp_history: Sequence[float], lattice_history: Sequence[Mapping[str,float]], new_unmatched: int, *, config=ChangepointConfig()) -> ChangepointSignal`
  - `ChangepointConfig(window=5, z_threshold=5.0, min_new_peaks=1)`
  - `ChangepointSignal(frame_index, triggered, z_rwp, z_lattice, new_unmatched, reasons: tuple[str,...])`
  - warm-up (履歴 < window) は `triggered=False` に安全側縮退。純関数・決定論。
  - engine はフレームごとに `rwp_history` / `lattice_history` (格子 a/b/c の dict) を蓄積して渡す。
  - `new_unmatched` (新規未マッチピーク数) は `search/matcher.py` の `find_peaks`/`match_score`/`unmatched_peaks` で算出 (architecture.md)。

### 3.3 changepoint 時の局所木探索と採択 (D3)
- `src/tsumugin/search/tree.py`:
  `HypothesisTreeSearch(backend, *, evidence: EvidenceBackend|None=None, config=SearchConfig(), ledger=None, snapshots=None)`
  - `search(two_theta, intensity, candidates: Sequence[PhaseCandidate|PhaseInstance], *, weights=None) -> SearchResult`
  - 候補 = **現行相 + 供給された候補プール** (`SequentialEngine.__init__` の `candidates`)。
  - `SearchResult.ranked: tuple[RankedHypothesis,...]` の `ranked[0].hypothesis` が最良仮説。
    `SearchResult.hypotheses`, `.ledger`, `.snapshots` も保持。
  - `SearchConfig(...)` は `SequentialConfig.search` から供給。ledger/snapshots は engine と共有注入 (監査一貫性)。
- **採択判定**: 最良仮説の相集合が現行と異なり、かつ **evidence が改善**する場合のみ採択 (adopt)。
  以後のフレームは新構成で継続。採択・棄却とも理由付き ledger 記録 (adopt / reject)。
  - evidence: `src/tsumugin/evidence/ic.py` `BICBackend` (既定、name="bic")。`EvidenceBackend.score(metrics) -> EvidenceResult(backend,value,...)` (小さいほど良)。

### 3.4 ライフサイクル追跡・トラジェクトリ組立
- `src/tsumugin/sequential/lifecycle.py`:
  `LifecycleTracker(*, config=LifecycleConfig(hysteresis=3, presence_wt_frac=1e-3))`
  - `observe(frame_index: int, present_refs: Sequence[str]) -> None` を毎フレーム、`finalize() -> Mapping[str, PhaseLifecycle]`。
- `src/tsumugin/sequential/trajectory.py`:
  - `FrameRecord(frame_index, axis_value=None, temperature=None, phases=(), rwp=None, chi2=None, changepoint=False, changepoint_reasons=(), refine_failed=False)`
  - `Trajectory(records: tuple[FrameRecord,...]=(), lifecycles: Mapping[str,PhaseLifecycle]={})` / `to_csv(path) -> str`
  - **注**: trajectory.py docstring 明記「上流結果の結合は TASK-0019 の責務」= 本タスクが FrameRecord 列と lifecycles を組み立てる。
- `src/tsumugin/sequential/series.py`:
  `FrameSeries(two_theta, intensities: (n_frames,n_points), axis_values=(), axis_kind="index", channels=())` / `n_frames` property。
  `__post_init__` で形状不一致は `ValueError`。空 series (n_frames=0) → 空 Trajectory (EDGE-001)。

### 3.5 モデル拡張フィールド (実装確認済み・非破壊)
- `src/tsumugin/model/hypothesis.py`: `Hypothesis(..., frame_range: tuple[int,int]|None = None)` → 採択区間を格納。
  `status` / `accepted_by` あり。`RefinementMetrics(rwp,gof,chi2,n_obs,n_params,evidence={})`。
- `src/tsumugin/model/phase.py`: `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies={}, lifecycle=None)`,
  `LatticeParams(a,b,c,alpha=90,beta=90,gamma=90,sigma={})`, `PhaseLifecycle(birth_frame=None,death_frame=None,confidence=1.0)`。

### 3.6 永続化 (注入で TC-106-06 相当を 1 本)
- `src/tsumugin/store/persistent.py`:
  `PersistentLedger(path)` (append/entries/verify、"a" 追記のみ)、
  `PersistentSnapshotStore(path, ledger=None)` (save/load/revert/snapshots/current_id)。
  in-memory `Ledger`/`SnapshotStore` と同一契約。engine へ注入して M2 経路が無改変で動くことを 1 本検証。

## 4. 設計文書 (契約) — SequentialConfig / SequentialResult / SequentialEngine

### 対象シンボル (`docs/design/m2-sequential/interfaces.py` L211-253)

```python
@dataclass(frozen=True)
class SequentialConfig:
    orchestration: Literal["independent", "native"] = "independent"  # native は NotImplementedError (REQ-105)
    inherit: Literal["phases", "lattice_only"] = "phases"             # warm start 継承対象 (FR-301)
    seq_max_cycles: int = 10                                          # 後続フレームの精密化サイクル (D2)
    first_frame_staged: bool = True                                  # 初回フレームのフル確立 (D2)
    changepoint: ChangepointConfig = ChangepointConfig()
    lifecycle: LifecycleConfig = LifecycleConfig()
    search: SearchConfig = SearchConfig()                            # 局所木探索設定 (REQ-101)

@dataclass(frozen=True)
class SequentialResult:
    trajectory: Trajectory
    hypotheses: Mapping[str, Hypothesis]        # 採択構成の系譜 (frame_range 付き)
    search_results: Mapping[int, SearchResult]  # changepoint フレームの局所探索結果 (key=frame_index)
    first_frame_report: RefinementReport | None
    ledger: Ledger
    snapshots: SnapshotStore
    warnings: tuple[str, ...] = ()

class SequentialEngine:
    def __init__(self, backend: RefinementBackend, *,
        candidates: Sequence[PhaseCandidate | PhaseInstance] = (),  # 局所探索プール (REQ-101)
        evidence: EvidenceBackend | None = None,                    # 既定 BIC
        config: SequentialConfig = SequentialConfig(),
        ledger: Ledger | None = None,                               # Persistent 版を注入可能
        snapshots: SnapshotStore | None = None,
    ) -> None: ...
    def run(self, series: FrameSeries, initial_phases: Sequence[PhaseInstance]) -> SequentialResult: ...
```

### 全体フロー (`docs/design/m2-sequential/dataflow.md` シーケンシャル解析の全体フロー / architecture.md D1〜D3)

1. **frame 0**: `StagedRefinementEngine` フル確立精密化 (`first_frame_staged`) → `first_frame_report`。
2. **frame i = 1..N-1**: warm start (直近成功フレームの phases) → `backend.refine` 直呼び (scale+lattice, ≤ seq_max_cycles)。
3. **フレーム指標計算**: Rwp / 格子フレーム間差分 / 新規未マッチピーク。
4. **`detect_changepoint`** → 複合ロバスト z が閾値超なら changepoint。
5. **発火時のみ** `HypothesisTreeSearch.search` (候補=現行相+候補プール、共有 ledger) →
   新構成が **evidence 改善**時のみ採択 (ledger adopt) / 非改善は現行維持 (ledger reject)。
6. `FrameRecord` 確定 → `LifecycleTracker.observe`。
7. 全フレーム終了 → `finalize()` で lifecycle 確定 → `Trajectory` 組立。`Hypothesis.frame_range` に採択区間。
8. `orchestration="native"` は `NotImplementedError` (REQ-105 / FR-302 は M-later)。

### 設計判断 (architecture.md)
- **D1 オンライン単一パス**: 直近 W=5 フレームのローリング統計 (中央値/MAD) の robust z で changepoint、その場で局所探索→採択→継続。
- **D2 フレーム精密化 2 段構え**: 初回 staged / 後続 direct refine。warm start は**直近成功**フレーム (EDGE-002)。
- **D3 changepoint 時の局所木探索と採択**: 相集合が現行と異なり evidence 改善時のみ採択。採択/棄却とも理由付き ledger。
- 参照元: `docs/design/m2-sequential/interfaces.py`, `docs/design/m2-sequential/architecture.md`,
  `docs/design/m2-sequential/dataflow.md`, `docs/tasks/m2-sequential/TASK-0019.md`

## 5. テスト関連情報

- **フレームワーク**: pytest (`[tool.pytest.ini_options]` in `pyproject.toml`、`testpaths=["tests"]`, `addopts="-q"`)。
- **ディレクトリ / 命名**: `tests/test_<module>.py`。本タスクは `tests/test_sequential_engine.py` (新規)。
- **検証バックエンド**: 原則 `SimulatedBackend(peak_fwhm=0.2)` (GSAS-II 非依存)。合成シーケンス
  (格子/scale を軸に沿って変化させたフレーム列) を numpy で構築。**グリッドは小さく** (実行時間対策、
  tree.py の範: `np.arange(15.0, 60.0, 0.02)`)。
- **テストダブルの範**: `tests/test_tree_search.py` L85-151 の 2 クラスを踏襲・再利用する。
  - **`FakeBackend`** (RefinementBackend Protocol 準拠スタブ): 相組合せ (phase_ref の frozenset) をキーに
    固定の (rwp, chi2) を返し、warm start 継承検証・chi2=inf 失敗注入 (EDGE-002/TC-101-07) を厳密制御。
    `simulate`/`peak_positions` は内蔵 `SimulatedBackend` へ委譲。`refine_calls: list[frozenset[str]]` を記録。
  - **`RecordingSpyBackend`** (SimulatedBackend へ委譲するスパイ): `refine_calls: list[tuple[frozenset, int]]` に
    `(free_params, max_cycles)` を記録。**warm start 継承検証 (TC-101-02)** と **seq_max_cycles 伝播**の観測に使う。
  - 木探索の呼び出し回数観測 (TC-102-02) は `HypothesisTreeSearch` をラップした spy か search 呼び出し回数カウンタで。
- **テスト書式の範**: `tests/test_tree_search.py` / `tests/test_changepoint.py`。
  - モジュール docstring に対象実装・書式方針・Red 期待を記載。
  - 各テスト関数冒頭に `# 【テスト目的】/【テスト内容】/【期待される動作】/🔵🟡 信頼性レベル` ブロック、`assert` 毎に `# 【確認内容】: ... 🔵/🟡`。
  - **決定論テストは `==` (pytest.approx 禁止)**、物理量近似は `pytest.approx`、非有限漏洩は `math.isfinite`。frozen は `pytest.raises(FrozenInstanceError)`。
- **未実装のため import が collection 時に失敗 → 全テスト Red** が Red フェーズの期待 (`from tsumugin.sequential.engine import SequentialEngine, SequentialConfig, SequentialResult`)。
- **conftest**: `tests/conftest.py` は gsas マーカー skip のみ。本タスクは GSAS 非依存 (@gsas は TC-108-02 = 別タスク)。
- 参照元: `tests/test_tree_search.py`, `tests/test_changepoint.py`, `tests/conftest.py`, `pyproject.toml`, `docs/spec/m2-sequential/acceptance-criteria.md`

## 6. 受け入れ基準 (完了条件 9 項目) — 本タスクの検証対象

`docs/tasks/m2-sequential/TASK-0019.md` 完了条件 / `docs/spec/m2-sequential/acceptance-criteria.md` (TC-101/102/108-03):

- [ ] 線形膨張 20 フレームで格子が真値 ±0.01 追跡 + warm start 継承検証 (spy) 🔵 **TC-101-01/02**
- [ ] 相 B 出現シーケンスで changepoint 検出 → 局所探索 → B 採択 → 以後 B 込み継続 🔵 **TC-102-01/03**
- [ ] 木探索は changepoint フレームのみ (spy 呼び出し回数) 🔵 **TC-102-02** (EDGE-104 含む)
- [ ] 空series → 空Trajectory / 単一フレーム / 失敗フレーム継続 🔵🟡 **TC-101-05/06/07** (EDGE-001/101/002)
- [ ] 決定論: 2 回実行で全出力ビット同一 🔵 **TC-101-04** (REQ-402)
- [ ] inherit="lattice_only" が機能 🟡 **TC-101-03**
- [ ] native → NotImplementedError 🔵 **REQ-105**
- [ ] 全フレーム changepoint でも完走 🟡 **TC-102-05** (EDGE-103)
- [ ] 100 フレーム (changepoint なし) < 60 秒 smoke 🟡 **TC-108-03** (NFR-001/REQ-403)
- [ ] (追加) ledger/snapshots 注入 = PersistentLedger 版で M2 経路が無改変で動く 🔵 **TC-106-06 相当を 1 本**

信頼性サマリー: 🔵 6 / 🟡 3 — 高品質。

## 注意事項 (技術的制約)

- **native は未実装**: `orchestration="native"` は `run()` 冒頭で `NotImplementedError` (FR-302 は M-later、REQ-105)。
- **失敗フレーム継続 (EDGE-002/TC-101-07)**: `backend.refine` が `chi2=inf`/`converged=False` の場合、
  warm start は**その失敗フレームを採用せず直近成功フレーム**を維持。FrameRecord は `rwp=None/chi2=None/refine_failed=True`、
  `warnings` に警告を積む。非有限を CSV/下流に漏らさない (`_num_cell` が空欄化)。
- **空 series (EDGE-001)**: `n_frames == 0` → 空 `Trajectory(records=(), lifecycles={})`、例外なし。
  `first_frame_report=None`、`search_results={}`。
- **単一フレーム (EDGE-101)**: frame 0 の staged 確立のみで長さ 1 の Trajectory。changepoint は warm-up で発火しない。
- **決定論 (TC-101-04/REQ-402)**: 乱数なし・安定ソート。dict 反復順依存を作らない (相 ref は sorted)。
  `search_results` の frame_index キー・`hypotheses` の ID 採番も入力順非依存。2 回実行で `==` ビット同一。
- **ledger/snapshots 共有**: engine の ledger と `HypothesisTreeSearch`/`StagedRefinementEngine` の ledger は
  同一インスタンスを注入して監査一貫性を保つ (tree.py `_final_refine` の共有パターン踏襲)。
- **changepoint 履歴の蓄積**: `rwp_history`/`lattice_history` はフレーム順に append。失敗フレームの扱い
  (履歴に None を入れるか成功値のみか) は testcases で確定 (非有限を robust z に渡さない方針)。
- **inherit="lattice_only" (TC-101-03) 🟡**: 継承時に格子のみ引き継ぎ、scale 等はリセット。詳細セマンティクスは testcases で確定。
- **evidence 改善判定**: BIC は小さいほど良。「改善」= 新構成の最良仮説 evidence < 現行構成 evidence (境界=非改善で現行維持)。
- **性能 (TC-108-03) 🟡**: 100 フレーム changepoint なしで direct refine (~7 パラメータ × ≤10 cycles) が支配的。
  smoke は小グリッドで < 60 秒。changepoint を発火させない滑らかな合成データを使う。
- 参照元: `docs/design/m2-sequential/interfaces.py`, `docs/design/m2-sequential/architecture.md`, `docs/design/m2-sequential/dataflow.md`, `CLAUDE.md`, `src/tsumugin/search/tree.py`, `src/tsumugin/sequential/changepoint.py`
