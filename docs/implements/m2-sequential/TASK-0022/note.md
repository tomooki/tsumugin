# TASK-0022 開発コンテキストノート — 公開 API 統合 + E2E + ドキュメント (M2 総仕上げ)

## 作成日時
2026-07-03

## タスク要約
M2 (シーケンシャル解析基盤) の総仕上げ統合タスク。実装済み成果物 (TASK-0011〜0021) を公開面
(`src/tsumugin/__init__.py`) へ配線し、統合 E2E テストとドキュメントで裏取りする。M1 の
TASK-0010 (公開 API 統合) を範とする同型タスク。信頼性レベル 🔵 5/5 (高品質)。

- **参照元**: `docs/tasks/m2-sequential/TASK-0022.md`, `docs/tasks/m2-sequential/overview.md`, `docs/spec/m2-sequential/note.md`

### 完了条件 (TASK-0022.md より、5 項目)
1. `from tsumugin import SequentialEngine, ...` で M2 API が利用可能 🔵
2. TC-108-01 一気通貫 E2E green (逐次精密化 → changepoint → 局所探索で新相 → lifecycle →
   転移温度 → agent 裁定 → 永続 ledger verify() True → CSV 出力) 🔵
3. (@gsas) TC-108-02 GSASIIBackend で 3 フレーム逐次精密化 smoke が完走 🔵
4. 全テスト green・カバレッジ 90% 以上・ruff clean 🔵
5. README M2 使用例 (10-15 行、実行確認) + `docs/dev/context.md` 更新 + 検証レポート
   (`docs/tasks/m2-sequential/reports/verification.md`) 作成 🔵

### TDD フロー
tdd-red (E2E) → tdd-green → tdd-refactor → tdd-verify-complete

### 主要実装ファイル
- `src/tsumugin/__init__.py` (M2 シンボル re-export + `__all__` 昇順統合)
- `tests/test_m2_e2e.py` (新規、TC-108 系)
- `README.md` (M2 使用例節 + アーキテクチャ表)
- `docs/dev/context.md` (実装済みモジュール表更新)
- `docs/tasks/m2-sequential/reports/verification.md` (新規、`reports/` ごと未作成)

---

## 1. 技術スタック

### 使用技術・フレームワーク
- **言語**: Python >= 3.12 (`target-version = "py312"`)
- **数値**: numpy >= 1.26 (コア唯一の必須依存)
- **パッケージ管理 / ビルド**: uv + hatchling (src layout)
- **Rietveld バックエンド**: GSAS-II 2.0 (`from GSASII import GSASIIscriptable`)。optional extra `gsas` (scipy / pycifrw / requests)。導入済み (ソースツリー `C:\Users\tomoo\G2` + `.pth` + `~/.GSASII/GSASII-bin`)
- **Web UI (M1 導入済)**: FastAPI + uvicorn。optional extra `web`。遅延 import (D6 契約)
- **永続化 (M2 新規)**: stdlib json による **JSONL 追記** (`store/persistent.py`)。DB (HDF5/SQLite) は M3+
- **CSV 出力 (M2 新規)**: stdlib csv (`sequential/trajectory.py::Trajectory.to_csv`)。parquet は M2 スコープ外
- **テスト**: pytest >= 8 + pytest-cov >= 5。TestClient は httpx (dev group) 依存

### アーキテクチャパターン
- レイヤ分離 + 境界は `typing.Protocol` で抽象化 (バックエンド交換可能, P7)
- frozen dataclass による不変値オブジェクト、非破壊更新 (`with_updates()` / `dataclasses.replace()`)
- 全状態遷移は追記専用 Ledger (ハッシュチェーン) + Snapshot (revert 可能, P2 / NFR-101 / NFR-105)
- 時系列は **オンライン単一パス** (フレーム順に検出→対応→継続、architecture.md D1)
- 「失敗は例外でなく chi2=inf の結果に変換」しガードレールに処理させる原則
- 決定論 (NFR-102): 乱数不使用・中央値/MAD ロバスト統計・canonical JSON ソート・ID 決定論採番

- **参照元**: `pyproject.toml`, `docs/dev/context.md`, `docs/spec/m2-sequential/note.md`, `docs/design/m2-sequential/architecture.md`, `README.md`

---

## 2. 開発ルール

### プロジェクト固有ルール (必須)
- **TDD 厳守**: Red → Green → Refactor。テストなし実装コミット禁止
- **本タスク制約**: git commit しない / 質問しない (呼び出し側指示)
- **モデル指定**: 実装エージェント (サブ含む) は Opus
- **成果物保存先**: 要件・設計・タスク・レポートは `docs/` 配下
- **非破壊 (P2 / NFR-101)**: 生データ削除・上書き・履歴改変 API を作らない。Ledger/Snapshot/
  PersistentLedger/PersistentSnapshotStore/ReviewQueue に削除・上書きメソッド追加禁止 (追記 + revert のみ)

### コーディング規約
- **命名**: 変数/関数 snake_case、クラス/型 PascalCase、ファイル snake_case、定数 UPPER_SNAKE
- **型注釈必須** (`any` 回避)。境界は `Protocol` (`@runtime_checkable`)
- **docstring**: 日本語可。FR/NFR/REQ/TC 番号を紐づける慣習
- **Lint/Format**: `uvx ruff check src tests` (line-length 100, target py312) — clean 必須
- **カバレッジ**: 本タスク完了条件は 90% 以上 (M1 実績 96%)
- **公開 API**: `src/tsumugin/__init__.py::__all__` はアルファベット昇順を維持
  (`test_m1_symbols_in_dunder_all_and_sorted` が昇順固定を検証済み → M2 追加後も維持必須)

### テスト運用
- テストは実装ファイルと 1:1 対応の `tests/test_*.py`。本タスクで新規 `tests/test_m2_e2e.py`
- **GSAS-II 依存**: `@pytest.mark.gsas` を付与 → `tests/conftest.py::pytest_collection_modifyitems` が未導入環境で自動 skip
- **web extra 依存**: モジュール冒頭で `pytest.importorskip("fastapi")` により未導入環境は全 skip
- テストコマンド: `uv run pytest` / `uv run pytest --cov=tsumugin` / `uv run pytest -m gsas`
- **依存導入**: `uv sync --extra gsas --extra web` (プレーン `uv sync` は gsas extra が外れるため禁止)

- **参照元**: `docs/tasks/m2-sequential/TASK-0022.md`, `docs/spec/m2-sequential/note.md`, `CLAUDE.md`, `pyproject.toml`, `tests/conftest.py`, `docs/implements/m1-hypothesis-search/TASK-0010/note.md`

---

## 3. 関連実装 (統合対象の M2 成果物 — すべて実装済み TASK-0011〜0021)

### 公開 API の現状 (要更新の中心ファイル)
- `src/tsumugin/__init__.py`: **現状 M0 + M1 分のみ re-export** (`AICBackend`, `AnalysisResult`,
  `BICBackend`, `Hypothesis`, `HypothesisTreeSearch`, `LatticeParams`, `Ledger`, `Peak`,
  `PhaseCandidate`, `PhaseInstance`, `Project`, `RankedHypothesis`, `RefinementBackend`,
  `RefinementMetrics`, `RefinementModel`, `RefinementReport`, `RefinementResult`, `SearchConfig`,
  `SearchResult`, `SimulatedBackend`, `SnapshotStore`, `StagedRefinementEngine`,
  `UnmatchedPeakReport`, `analyze_single_pattern`, `export_gpx`, `rank`)。
  → **M2 分の追加が必要**。`__all__` へも追記しアルファベット昇順を維持。

### M2 サブパッケージの公開シンボル (サブパッケージ側は re-export 済み。トップレベルへ昇格が本タスク)
- `src/tsumugin/sequential/__init__.py` (`__all__`): `ChangepointConfig`, `ChangepointSignal`,
  `FrameRecord`, `FrameSeries`, `LifecycleConfig`, `LifecycleTracker`, `SequentialConfig`,
  `SequentialEngine`, `SequentialResult`, `ThermalBaseline`, `Trajectory`, `TransitionEstimate`,
  `detect_changepoint`, `estimate_transition`, `fit_thermal_baseline`
- `src/tsumugin/selection/__init__.py` (`__all__`): `Decision`, `EscalationReason`,
  `FinalSelectionEngine`, `ReviewItem`, `ReviewQueue`, `detect_escalations`
- `src/tsumugin/store/__init__.py` (`__all__`): `GENESIS_HASH`, `Ledger`, `LedgerEntry`,
  `PersistentLedger`, `PersistentSnapshotStore`, `Snapshot`, `SnapshotStore`, `phase_from_dict`,
  `phase_to_dict` (`PersistentLedger` / `PersistentSnapshotStore` / `phase_*_dict` が M2 新規)
- `src/tsumugin/model/__init__.py` (`__all__`): `ExternalChannel`, `PhaseLifecycle` が M2 新規追加
  (`Hypothesis.frame_range` / `PhaseInstance.lifecycle` は非破壊フィールド追加)

### 昇格候補シンボル (task 概要で明示 + サブパッケージ __all__ から確定)
必須中核: `SequentialEngine`, `SequentialConfig`, `SequentialResult`, `FrameSeries`, `Trajectory`,
`FrameRecord`, `ExternalChannel`, `PhaseLifecycle`, `PersistentLedger`, `PersistentSnapshotStore`,
`FinalSelectionEngine`, `ReviewQueue`, `ReviewItem`, `Decision`, `detect_escalations`,
`detect_changepoint`, `estimate_transition`, `fit_thermal_baseline`, `LifecycleTracker`,
`ThermalBaseline`, `TransitionEstimate`, `ChangepointConfig`, `ChangepointSignal`,
`LifecycleConfig`, `phase_to_dict`, `phase_from_dict`。
(最終集合は Green で確定。M1 の昇格粒度 = 「サブパッケージ __all__ に準じつつ E2E/summary 解釈に
必要なものを昇格」を踏襲する)

### E2E で直接使う主要シグネチャ (実装済みソースで確認済み)
- `SequentialEngine(backend, *, candidates=(), evidence=None, config=SequentialConfig(), ledger=None, snapshots=None)`
  - `.run(series: FrameSeries, initial_phases: Sequence[PhaseInstance]) -> SequentialResult`
  - `ledger`/`snapshots` に **Persistent 版を注入可能** (REQ-012)。未指定なら内部生成
  - `config.orchestration == "native"` は副作用前に `NotImplementedError` (REQ-105)
  - 空 series でも例外化せず空値へ縮退 (EDGE-001)
- `SequentialConfig(orchestration="independent", inherit="phases", seq_max_cycles=10, first_frame_staged=True, changepoint=ChangepointConfig(), lifecycle=LifecycleConfig(), search=SearchConfig())`
- `SequentialResult(trajectory: Trajectory, hypotheses: Mapping[str, Hypothesis], search_results: Mapping[int, SearchResult], first_frame_report: RefinementReport | None, ledger: Ledger, snapshots: SnapshotStore, warnings=())`
- `FrameSeries(two_theta: np.ndarray, intensities: np.ndarray (n_frames, n_points), axis_values: tuple[float,...]=(), axis_kind="index", channels: tuple[ExternalChannel,...]=())` + `.n_frames`
- `ExternalChannel(kind: "temperature"|"time"|"pressure"|"custom", sync_map: Mapping[int,float], label=None)` + `.value_for(frame_index) -> float|None`
- `Trajectory(records: tuple[FrameRecord,...], lifecycles: Mapping[str, PhaseLifecycle])` + `.to_csv(path) -> str` (stdlib csv、非有限値は空欄)
- `FrameRecord(frame_index, axis_value, temperature, phases, rwp, chi2, changepoint, changepoint_reasons, refine_failed)`
- `fit_thermal_baseline(temperatures, values, *, degree=1) -> ThermalBaseline`
- `estimate_transition(temperatures, fractions, *, phase_ref) -> TransitionEstimate | None` (遷移なしは None)
- `PersistentLedger(path)` : `.append(kind, payload) -> LedgerEntry` / `.entries` / `.verify() -> bool`。
  `__init__` で既存 JSONL を読込み全チェーン検証 (破損で `LedgerIntegrityError`、修復しない, EDGE-003)
- `PersistentSnapshotStore(path, ledger=None)` : `.save(phases, *, label)` / `.load(id)` / `.revert(id) -> tuple[PhaseInstance,...]` / `.snapshots` / `.current_id`
- `FinalSelectionEngine(*, mode="agent", ledger=None, queue=None)` : `.decide(result, *, frame_index=None) -> Decision` / `.accept(result, hypothesis_id, *, by)` / `.revert(hypothesis_id, *, note="")` / `.set_mode(mode)` / `.accepted`
- `detect_escalations(result: SearchResult, *, staged_escalated=False, high_r_threshold=30.0) -> tuple[EscalationReason,...]` (純関数、宣言順: all_high_r → unknown_phase → close_competitor → guard_escalated)
- `Decision(mode, accepted: Hypothesis|None, provisional_id, recommended_id, escalations, rationale)`
- `ReviewQueue(ledger=None)` : `.add(reason, *, hypothesis_id=None, frame_index=None, detail="")` / `.resolve(item_id, *, note="")` / `.items` / `.unresolved` (追記型・削除 API なし)

### M2 が土台にする M0/M1 資産 (再利用)
- `RefinementBackend` (`SimulatedBackend` / `GSASIIBackend`) — フレーム精密化 (`refine`) + パターン計算 (`simulate`)
- `StagedRefinementEngine` — 初回フレームの確立精密化 (D2、`escalated` が guard_escalated 材料)
- `HypothesisTreeSearch` + `PhaseCandidate` — changepoint 近傍の局所探索 (REQ-101、共有 ledger 注入)
- `find_peaks` / `match_score` / `unmatched_peaks` / `UnmatchedPeakReport.unknown_phase_flag` — 新規未マッチ指標・未知相判定
- `BICBackend` / `rank` / `RankedHypothesis.close_competitor` — evidence・僅差競合判定
- `Ledger` / `SnapshotStore` — 永続版が同一契約を実装する参照実装

- **参照元**: `src/tsumugin/__init__.py`, `src/tsumugin/sequential/{__init__,engine,series,changepoint,lifecycle,trajectory,thermal}.py`, `src/tsumugin/selection/{__init__,engine,review_queue}.py`, `src/tsumugin/store/{__init__,persistent,serialization,ledger,snapshot}.py`, `src/tsumugin/model/{__init__,channel,phase,hypothesis}.py`, `src/tsumugin/search/tree.py`, `src/tsumugin/refinement/staged.py`, `src/tsumugin/backends/{simulated,gsasii}.py`

---

## 4. 設計文書

### データフロー (SequentialEngine.run、architecture.md D1〜D3 / dataflow.md)
frame 0 = `StagedRefinementEngine` フル確立 → 後続フレーム = 直近**成功**フレームの phases を warm start
(EDGE-002) して `backend.refine` 直呼び (scale + lattice、`seq_max_cycles=10`) → フレーム指標蓄積 →
`detect_changepoint` (直近窓の中央値/MAD ロバスト z: Rwp 跳ね / 格子微分 / 新規未マッチ) → 発火フレーム
のみ `HypothesisTreeSearch.search` (現行相 + 候補プール、共有 ledger) → evidence 改善時のみ採択し以後
継続 (D3、採択/棄却とも理由付き ledger 記録) → `LifecycleTracker` (ヒステリシス N=3 で birth/death 確定) →
`Trajectory` (FrameRecord 列 + lifecycles) 組立。高温: `fit_thermal_baseline` で格子-T 熱膨張ベースライン
分離、`estimate_transition` で相分率シグモイドから転移温度 onset/midpoint±σ を推定。

### 統合 E2E の設計方針 (tests/test_m2_e2e.py 新規)
- **TC-108-01 (SimulatedBackend、マーカー無し、一気通貫)**: 昇温合成シーケンスを作る。
  熱膨張で格子定数が単調変化する主相 + フレーム途中で相転移 (新相の出現/主相の消失) を含む
  `FrameSeries` (温度チャネル同期) を `SequentialEngine.run` に投入。検証: (1) 逐次精密化が全フレーム完走、
  (2) changepoint が転移フレーム近傍で発火 (`FrameRecord.changepoint` / `search_results` に該当フレーム)、
  (3) 局所探索で新相が採択され `hypotheses` の相集合に反映、(4) lifecycle に birth/death が記録、
  (5) `estimate_transition` が転移温度を推定 (None でない)、(6) `FinalSelectionEngine(mode="agent").decide`
  で agent 裁定、(7) 永続 `PersistentLedger` 注入時 `verify()` True + 再オープン検証、
  (8) `Trajectory.to_csv` で CSV 書き出し (ヘッダ + 行数 = n_frames)。
- **TC-108-02 (@gsas、smoke)**: `GSASIIBackend` で短い **3 フレーム**逐次精密化が破綻せず完走し
  `SequentialResult` を返すことのみ確認 (実 GSAS-II 精密化の統合 smoke)。未導入環境は conftest が自動 skip。
- **公開シンボル re-export 検証**: `from tsumugin import SequentialEngine, FrameSeries, ...` が解決し
  期待の型 (class / dataclass / 関数) を持つこと + `__all__` 昇順・M0/M1 後方互換 (削除なし) を検証。
- **決定論 (NFR-102 / REQ-402)**: 2 回実行で trajectory / CSV / ranking がビット同一 (`==`)。
- **性能 smoke (TC-108-03、任意)**: 合成 100 フレーム (changepoint なし) が 60 秒以内 (NFR-001)。
  CI 実用性の観点で E2E に含めるか verify-complete で担保するかは testcases で切り分け。
- 決定論は `==` ビット同一、物理量は `pytest.approx`。既存 `tests/test_sequential_engine.py` の
  合成データ生成パターンと `tests/test_m1_e2e.py` の GRID (`np.arange(15.0, 60.0, 0.02)`) が流用可能。

### 更新対象ドキュメント
- `README.md`: 「使い方 (M2)」節を追加 (10-15 行、`SequentialEngine` の最小使用例)。
  アーキテクチャ表に `tsumugin.sequential` / `tsumugin.selection` / `store.persistent` 行を追加。
  M1 使用例 (L84-105 付近) が書式の範。
- `docs/dev/context.md`: Overview を M2 スコープへ、Project Structure に sequential/selection/persistent、
  Additional Notes の「M1 スコープ外」記述を更新。
- `docs/tasks/m2-sequential/reports/verification.md`: `reports/` ディレクトリごと新規作成。M1 の
  `docs/tasks/m1-hypothesis-search/reports/verification.md` の構成 (サマリ / タスク別テスト内訳表 /
  完了条件充足表 / 仕様適合の要点) を範とする。

- **参照元**: `docs/design/m2-sequential/architecture.md`, `docs/design/m2-sequential/interfaces.py`, `docs/design/m2-sequential/dataflow.md`, `docs/spec/m2-sequential/requirements.md`, `docs/spec/m2-sequential/acceptance-criteria.md`, `docs/tasks/m1-hypothesis-search/reports/verification.md`, `README.md`, `docs/dev/context.md`

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`
- **マーカー**: `gsas` (定義済み)。GSAS-II 未導入時は `tests/conftest.py::pytest_collection_modifyitems` が自動 skip
- **テストディレクトリ / 命名**: `tests/test_*.py`、実装ファイルと 1:1。**本タスクで新規追加**: `tests/test_m2_e2e.py`
- **現状ベースライン**: M2 実装済みタスク分を含め全 green (M1 時点 218 passed / 3 skipped、M2 各タスクで積み上げ済み)
- **既存参照テスト (書式の範)**:
  - `tests/test_m1_e2e.py` — M1 の公開 API 統合 E2E 13 ケース (公開シンボル re-export・`__all__` 昇順・
    実バックエンド E2E・@gsas・決定論・縮退・README 例)。**本タスク E2E の直接の範**
  - `tests/test_sequential_engine.py` — `SequentialEngine.run` の 18 ケース (SE-N/E/B)、昇温合成データ生成
  - `tests/test_persistent_store.py` — `PersistentLedger` / `PersistentSnapshotStore` 再オープン + `verify()`
  - `tests/test_selection.py` — `FinalSelectionEngine` / `detect_escalations` / `ReviewQueue`
  - `tests/test_thermal.py` — `fit_thermal_baseline` / `estimate_transition`
  - `tests/test_trajectory.py` — `Trajectory.to_csv` (CSV 書式・非有限値の空欄化)
  - `tests/test_gsasii_backend.py` — `@pytest.mark.gsas` の実 GSAS-II smoke パターン
- **公開 API の再エクスポート検証パターン**: `test_m1_symbols_in_dunder_all_and_sorted` 同様に
  `from tsumugin import SequentialEngine, FrameSeries, ...` の成功 + `__all__` 昇順 + M0/M1 非破壊を検証

- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_m1_e2e.py`, `tests/test_sequential_engine.py`, `tests/test_persistent_store.py`, `tests/test_selection.py`, `tests/test_thermal.py`, `tests/test_trajectory.py`, `tests/test_gsasii_backend.py`

---

## 6. 注意事項

### 技術的制約
- 逐次エンジンは非探索区間 = warm start + direct refine (軽量)、changepoint 近傍のみ局所木探索 (FR-304)
  にコストを集中。全フレーム staged は NFR-103 (10 秒/フレーム) に不利のため避ける
- changepoint は複合指標のロバスト z (中央値/MAD)。ローリング窓 `window=5`・`z_threshold=5.0` は
  合成データの発火較正に影響するため E2E データ設計で発火が出る温度ステップ幅を選ぶ
- lifecycle ヒステリシス既定 N=3。E2E の相転移は 3 フレーム以上継続させて birth/death を確定させる
- `estimate_transition` は相分率シグモイドの補間ベース。遷移が明瞭でない合成データでは None を返し得る
  ため、E2E は転移が明瞭に出る合成データ (相分率が 0→1 に単調変化) を設計する
- `.gpx` (M1) / GSAS-II 依存は @gsas のみ (TC-108-02 の 1 本)。GSAS-II 起動時の `~/.GSASII/config.ini`
  読込警告 (cp932) は無害

### 非破壊 / セキュリティ制約
- **P2 / NFR-101**: 破壊的 API を追加しない。Persistent 版も削除・上書きメソッド禁止 (追記 + revert のみ)
- **NFR-105 / NFR-201**: ledger (in-memory / persistent とも) は追記専用 + ハッシュチェーン。
  `verify()` が常に True。永続版は再オープン時に全チェーン再検証し、破損は `LedgerIntegrityError`
  (修復・上書きしない、EDGE-003)。E2E でも `verify()` True を assert
- **NFR-203**: 永続化ファイル書き込みは追記モード (`"a"`) のみ。既存バイト列を書き換えない
- 採択/棄却・モード切替・birth/death・エスカレーションはすべて理由付きで ledger 記録
- Review Queue Web は認証なし。既定 `127.0.0.1` バインドを維持

### 再現性 / データ制約
- **NFR-102 / REQ-402**: 同一入力・同一設定でシーケンシャル解析の全出力はビット同一。乱数不使用、
  中央値/MAD、canonical JSON ソート、ID 決定論採番 (`cfg-XXXX` / `hyp-XXXX` / `rq-XXXX`)
- chi2/rwp のセマンティクスはバックエンド間統一。精密化失敗は例外でなく chi2=inf に変換し、
  失敗フレームは警告付きで記録して直近成功フレームから warm start 継続 (EDGE-002)
- 非有限値 (rwp/chi2) は FrameRecord で None 化し、CSV では空欄化 (M1 教訓)
- **依存導入の落とし穴**: `uv sync --extra gsas --extra web` を使う。プレーン `uv sync` は禁止

### 本タスク運用上の注意
- git commit しない / 質問しない
- 全パスは相対パスで記載すること (本ノートも遵守)
- 後方互換: M0/M1 公開シンボル (現 `__all__` 27 件) を 1 つも削除・改名しない (REQ-404)

- **参照元**: `docs/spec/m2-sequential/note.md`, `docs/spec/m2-sequential/requirements.md`, `docs/design/m2-sequential/architecture.md`, `CLAUDE.md`, `docs/tasks/m2-sequential/TASK-0022.md`

---

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
