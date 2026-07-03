# TASK-0033 TDD 開発コンテキストノート

**タスク**: operando/segmentation — IC ペナルティ付き区間自動分割 (FR-316)。
`operando/segmentation.py` に `SegmentationConfig` / `SegmentationResult` /
`segment_series(backend, series, initial_phases, *, config, fixed_phases, ledger)` を実装する
**要件名**: m3-operando / **タスクID**: TASK-0033 / **タイプ**: TDD / **推定 5h**
**フェーズ**: Phase 4 / **信頼性**: 🔵 5 / 🟡 1 (FR-316/§15-1 / 設計 D5/D6 / REQ-013/014 / EDGE-004 / AC TC-206 系)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando (想定)
**依存タスク**: 前提 TASK-0028 (multistart)/TASK-0031 (changepoint 較正) — すべて完了 / 後続 TASK-0035 (E2E)

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

operando フレーム列 (FrameSeries) を **IC (bic) ペナルティ付きで区間自動分割**し、区間数 k と境界を
自動決定する**オーケストレーション純関数** `segment_series` を実装する。

- **区間コスト** = 区間内の**軽量 warm-start 逐次 direct refine の Σbic** (changepoint・木探索なし)。
  区間コストは **(start, end) をキーにメモ化**し、貪欲挿入・細密スキャンでの再評価を回避 🔵 *設計 D5*
- **探索順序 (貪欲挿入)** 🔵 *§15-1 / 設計 D5*:
  1. k=1 (境界なし = 全区間 1 セグメント) の合計コストを基準にする。
  2. 既存分割へ**境界 1 本を追加する全候補** (粗グリッド刻み `coarse_step` G=5、フレーム index) を評価。
  3. **合計コスト = Σ(区間 bic) + penalty_beta·(境界数)·ln(n_frames)** が最小の挿入を採用。
  4. 直前 k からの**改善が `improvement_threshold` (=10.0) 未満で打ち切り** (`max_segments` まで走らない)。
  5. 採用した各境界を **±G の細密スキャン**で再配置 (粗→細 2 段)。
- **分割仮説の保存** 🔵 *設計 D6 / REQ-014*: 各 k の分割を **1 個の `Hypothesis`**
  (id=`"seg-k{K}-XXXX"`, `frame_range`=全区間, phases=区間代表相) として `partitions` に保存し代替閲覧可。
  境界・evidence は ledger payload と `SegmentationResult.evidence_by_k` (k -> 合計コスト) に保持。
- **EDGE-004**: k=1 (分割なし) が最良ならそのまま採択 (固溶体単区間、過分割しない) 🔵
- **固定相 (`FixedPhaseSpec`) 対応**: 区間逐次 refine に常駐・構造固定・scale のみ解放 (FR-312 連携) 🔵
- **全操作 ledger 記録** (追記専用、`verify()` 常に True) 🔵 *P2/NFR-105*
- **決定論** (乱数/IO なし・安定ソート・dict 反復順非依存) 🔵 *NFR-102*

**🚨 絶対制約 (完了条件 6 項目と直結、= AC TC-206)**:
1. 2 区間合成データ (前半固溶体・後半二相) で **k=2 採択・境界が真値 ±2 フレーム** 🔵 *TC-206-01*
2. 一様データで **k=1** (過分割しない) 🔵 *TC-206-02 / EDGE-004*
3. k 逐次追加が **改善閾値未満で打ち切り** (`max_segments` まで走らない) 🔵 *TC-206-03*
4. 分割仮説 (k=1,2,…) が **Hypothesis として保存**され `evidence_by_k`/`partitions` で閲覧可 🔵 *TC-206-04*
5. **細密化で境界が粗スキャンより改善** + **区間コストのメモ化** (評価回数抑制を spy 検証) 🟡 *TC-206-05*
6. **決定論**: 分割結果が 2 回実行でビット同一 🔵 *TC-206-07 / NFR-102*
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行)。
- 失敗フレームは例外でなく chi2=inf の結果へ変換し縮退処理 (CLAUDE.md 不変条件)。非有限を Σbic に混ぜない。
- 既存テスト無改変 green (後方互換 REQ-404)。

**⚠️ スコープ外**: TC-206-06 (Issue #3 = 新規ピーク指標の持続 M フレーム発火) は **TASK-0031**
(`sequential/changepoint.py` 較正) の担当で完了済み。本タスク (TASK-0033) の完了条件には含まれない。
本タスクの区間コストは changepoint を**使わない**軽量逐次 refine の Σbic である (設計 D5 明記)。

**参照元**: `docs/tasks/m3-operando/TASK-0033.md`, `docs/design/m3-operando/architecture.md` D5/D6 (L78-86)・分割表 (L40),
`docs/design/m3-operando/dataflow.md` (FR-316 ノード L20)、`docs/design/m3-operando/design-interview.md` D-Q5/D-Q6 (L28-38),
`docs/design/m3-operando/interfaces.py` L287-321,
`docs/spec/m3-operando/requirements.md` REQ-013/014/015 (L59-66)・EDGE-004 (L124),
`docs/spec/m3-operando/acceptance-criteria.md` TC-206-01〜07 (L53-60)・TC-209-01 (L82)

---

## 1. 技術スタック

- **言語 / ランタイム**: Python >=3.12 (`pyproject.toml`、uv 管理、src layout + hatchling)。数値は numpy のみ (REQ-403)。
- **テスト**: `uv run pytest` / カバレッジ `uv run pytest --cov=tsumugin`。Lint `uvx ruff check src tests` (line-length 100)。
- **依存導入**: `uv sync --extra gsas` (プレーン `uv sync` は禁止 — gsas 依存が外れる)。
- **アーキテクチャパターン**: 不変データ (frozen dataclass + `with_updates()`) + `typing.Protocol` 境界 +
  追記専用ストア (Ledger/Snapshot) + 純関数コア。M0〜M2 / TASK-0032 と同一。
- **本タスクの対象レイヤ**: `operando/segmentation.py` = **オーケストレーション純関数**
  (`segment_series` は下位部品 — 区間逐次 refine / BICBackend / Hypothesis / Ledger — を束ねる)。
  TASK-0032 (`operando/discrimination.py`) と同型の「区間 Σbic を求める warm-start 逐次 refine」を再利用。
- **参照元**: `pyproject.toml`, `CLAUDE.md` (L15-27, L63-77), `docs/design/m3-operando/architecture.md` (L18-22)

## 2. 開発ルール

- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしの実装コミット禁止。
- **テスト配置 1:1**: 本タスクは `tests/test_segmentation.py` (新規) — 設計のテストファイル一覧に明記
  (`docs/design/m3-operando/architecture.md` L121-122)。
- **決定論 (NFR-102)**: 乱数/IO なし・安定ソート・dict 反復順非依存。同一入力 2 回でビット同一。
  貪欲挿入の tie-break (同コストの境界候補) は決定論的順序 (例: 小さい index 優先) で固定する。
- **非破壊性 (P2)**: 入力 phases / series を破壊しない。Ledger は append のみ。`evidence_by_k`/`partitions` は追記型。
- **非有限を漏らさない** (M1 教訓): inf/NaN を Σbic・合計コストへ混ぜない。バックエンド失敗は chi2=inf 結果 → 縮退処理。
- **後方互換 (REQ-404)**: 新規モジュール追加のみ。`operando/__init__.py` の `__all__` へ非破壊追記。
- **コーディング規約**: snake_case / 型注釈必須 / 日本語 docstring 可 / 実装コメントに信頼性レベル (🔵🟡) 併記が先例。
- **参照元**: `CLAUDE.md` (L40-77), `docs/implements/m3-operando/TASK-0032/note.md` (直近先例),
  `src/tsumugin/operando/__init__.py`

## 3. 関連実装 (実 API 確認済み)

### 3.1 `src/tsumugin/operando/discrimination.py` — 区間 Σbic 逐次 refine の直近先例 (TASK-0032 完了)
- **本タスクが最も強く踏襲する先例**。区間コスト算出の内部ヘルパ `_refine_interval(backend, series,
  frame_range, phases, *, free_suffixes, fixed_specs, seq_max_cycles, warm_start, label)` が
  「区間フレームを warm-start 逐次 direct refine し Σbic を返す」処理を実装済み (非公開・非 frozen の
  `_IntervalRefinement(sum_bic, ..., n_finite)` を返す)。**segment_series の区間コストはこの
  warm-start=True 経路と同型** (固溶体追従のため warm start 継承)。
- `_HYPOTHESIS_A_SUFFIXES` = `("scale","lattice.a","lattice.b","lattice.c")` (単相格子解放) が区間コストの解放 suffix。
- 非有限フレームは Σbic に混ぜず `n_finite` で管理 → 全フレーム非有限は縮退経路。segmentation も同様に扱う。
- ledger kind は `"discrimination.*"` 前置。segmentation は `"segmentation.*"` 前置を採る想定。

### 3.2 `src/tsumugin/evidence/ic.py` — BICBackend (区間 bic の算出源)
- `BICBackend.score(metrics: RefinementMetrics) -> EvidenceResult`、
  `value = metrics.chi2 + metrics.n_params * math.log(max(metrics.n_obs, 1))` (n_obs=0 は log(1)=0 で非例外)。
- 区間 Σbic = 各フレーム `RefinementResult` から `RefinementMetrics` を組んで `score().value` を加算 (discrimination と同一)。
- **合計コストのペナルティ項 `penalty_beta·(境界数)·ln(n_frames)`** は BIC の境界数ペナルティで、
  bic 内部の `k·ln(n_obs)` とは別軸 (分割数に対する Occam ペナルティ)。両者を混同しない。

### 3.3 `src/tsumugin/sequential/engine.py` — warm-start 逐次パターン (TASK-0011 完了)
- `SequentialEngine`: 直近成功フレームの確定 phases を `warm_phases` として次フレーム direct refine の
  初期値に使う (L199-328)。失敗フレームは warm start に採らない。`seq_max_cycles=10` 既定 (L72)。
- **本タスクの区間逐次 refine は changepoint/木探索なしの軽量版** (設計 D5)。SequentialEngine フル再利用は
  探索が混ざり過剰 (D-Q5) → discrimination の `_refine_interval` パターンを踏襲する。

### 3.4 `src/tsumugin/sequential/changepoint.py` — (本タスクでは不使用、スコープ確認用)
- `detect_changepoint(...)` / `ChangepointConfig` (`new_peak_min_height_frac=0.05`, `new_peak_persistence=2`)。
- 区間コストには使わない。REQ-013 の「changepoint 分割」は本タスクでは **IC ペナルティ付き貪欲区間分割**
  として実現される (D5)。changepoint 指標自体の較正は TASK-0031 で完了。

### 3.5 `src/tsumugin/sequential/series.py` — FrameSeries (TASK-0011 完了)
- `FrameSeries(two_theta, intensities[(n_frames, n_points)], axis_values=(), axis_kind="index", channels=())` (frozen)。
  `__post_init__` で形状検証 (ValueError)。`n_frames` プロパティ。区間 refine は `series.intensities[i]` を使う。

### 3.6 `src/tsumugin/operando/cell_phases.py` — FixedPhaseSpec (TASK-0030 完了)
- `FixedPhaseSpec(phase, label)` (frozen)。`fixed_free_suffixes(spec) -> ("scale",)` — 固定相は scale のみ解放。
  `CELL_PHASE_PRESETS` = "Be"/"Al"/"graphite" (テストデータに利用可)。discrimination と同じ組み込み契約。

### 3.7 `src/tsumugin/backends/` — 精密化契約
- `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)` (frozen)。
- `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, ...)` (frozen)。
- `RefinementBackend` Protocol: `name` + `refine(model, *, max_cycles=20) -> RefinementResult`。
- `param_name(i, key) -> "phase{i}.{key}"`。
- `SimulatedBackend` (`backends/simulated.py`): `simulate(phases, two_theta)` は Ycalc・乱数なし → ビット同一。
  固溶体系列 = 単相 `lattice.a` をフレームで線形変化、二相系列 = 端成分 2 相 scale を漸移。`_SCALAR_KEYS=("scale","wt_frac")`。

### 3.8 `src/tsumugin/model/hypothesis.py` — Hypothesis / RefinementMetrics
- `Hypothesis(id, phases, parent_id=None, metrics=None, status="candidate", accepted_by=None, frame_range=None)` (frozen)。
  分割仮説は `id="seg-k{K}-XXXX"` / `frame_range`=全区間 / `phases`=区間代表相 で構築 (D6)。
- `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence={}, multistart=None)`。分割仮説の合計コストは
  `evidence` や metrics 経由で保持可能 (evidence_by_k が正の保持先)。

### 3.9 store
- `src/tsumugin/store/ledger.py::Ledger.append(kind, payload)` / `verify()`。payload は素の型のみ (int/float/str/list/dict)。
  境界 tuple・k・合計コストを payload 化。`ledger=None` なら記録スキップでも結果不変 (先例 TC-BV05 系)。

## 4. 設計文書

- **契約 (必達)**: `docs/design/m3-operando/interfaces.py` L287-321
  - `SegmentationConfig(penalty_beta=5.0, improvement_threshold=10.0, coarse_step=5, max_segments=6, seq_max_cycles=10)` (frozen)
  - `SegmentationResult(boundaries: tuple[int,...] (昇順), n_segments: int, evidence_by_k: Mapping[int,float] (k->合計コスト),
    partitions: tuple[Hypothesis,...] (各 k), ledger: Ledger, warnings: tuple[str,...]=())` (frozen)
  - `segment_series(backend, series, initial_phases, *, config=SegmentationConfig(),
    fixed_phases: tuple[FixedPhaseSpec,...]=(), ledger: Ledger | None = None) -> SegmentationResult`
- **設計 D5** (`architecture.md` L78-82): §15-1 確定案。k=1 から貪欲挿入 — 既存分割に境界 1 本追加の全候補
  (粗グリッド G=5) を評価、合計コスト = Σ区間 bic + β·(境界数)·ln(n_frames) 最小の挿入採用、
  改善 < 閾値 (10.0) で打ち切り、採用境界を ±G 細密スキャンで再配置。区間コストは軽量逐次 refine の bic 和。
- **設計 D6** (`architecture.md` L84-86): 各 k の分割を `Hypothesis` (id="seg-k{K}-XXXX", frame_range=全区間,
  phases=区間代表相) として保存し `partitions` で代替閲覧可。ledger に境界・evidence を記録。
- **D-Q5/D-Q6** (`design-interview.md` L28-38): 区間コスト = warm-start 逐次 direct refine の bic 和
  (changepoint/木探索なし軽量版)・**メモ化して貪欲挿入の再評価を回避**。分割仮説は各 k を **1 個の Hypothesis**
  とし境界は ledger payload と evidence_by_k に保持 (区間ごとの相構成は判別 FR-313 側が持つ)。
- **要件**: REQ-013 (IC ペナルティ付き changepoint 分割、k を 1 から逐次追加、改善閾値未満で打ち切り、粗→細 2 段)、
  REQ-014 (各分割仮説を Hypothesis 保存・代替閲覧)、EDGE-004 (k=1 最良ならそのまま採択・過分割しない)。
- **AC**: TC-206-01〜05/07 (`acceptance-criteria.md` L53-60)。TC-206-06 はスコープ外 (TASK-0031)。
  TC-209-01 (E2E 一気通貫) は TASK-0035 で検証。
- **参照元**: `docs/design/m3-operando/architecture.md`, `docs/design/m3-operando/dataflow.md`,
  `docs/design/m3-operando/design-interview.md`, `docs/design/m3-operando/interfaces.py`,
  `docs/spec/m3-operando/requirements.md`, `docs/spec/m3-operando/acceptance-criteria.md`

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov (`pyproject.toml [tool.pytest.ini_options]`, testpaths=["tests"])。
  `tests/conftest.py` が GSAS-II 未導入環境で `gsas` マーカーを自動 skip — **本タスクは SimulatedBackend /
  Fake/Spy のみで GSAS-II 非依存 (マーカー不要)**。
- **新規テストファイル**: `tests/test_segmentation.py` (実装 `src/tsumugin/operando/segmentation.py` と 1:1)。
- **命名/コメント規約**: 関数名 `test_*`、日本語コメント【テスト目的】【テスト内容】【期待される動作】+
  信頼性レベル 🔵🟡 (先例: `tests/test_discrimination.py`, `tests/test_sequential_engine.py`)。
- **合成データの作り方 (決定論)**:
  - **2 区間系列 (TC-206-01)**: 前半フレームを固溶体 (単相 `lattice.a` 連続変化)、後半を二相 (端成分 2 相 scale 漸移)
    として `FrameSeries(two_theta, np.stack(rows))` を構成。真の境界を既知にして採択境界を ±2 で検証。
  - **一様系列 (TC-206-02)**: 全フレームほぼ同一 (固溶体で `lattice.a` 変化を微小/ゼロ) → k=1 が最良になる系。
  - 先例グリッド: `GRID = np.arange(15.0, 60.0, 0.02)` (`tests/test_sequential_engine.py`)。smoke には粗いグリッド可。
- **テストダブルの先例**: `tests/test_discrimination.py` / `tests/test_sequential_engine.py` の
  `PhaseRecordingSpyBackend` / `FrameFailBackend` / `InitialValueFakeBackend` 系。
  **TC-206-05 のメモ化検証**は「`backend.refine` (または区間コスト評価) の呼び出し回数が、同一 (start,end)
  区間の再評価でキャッシュヒットし増えない」を記録スパイ (呼び出しカウンタ) で検証するのが既存流儀。
  細密化改善は「粗スキャン採択境界コスト >= 細密スキャン後コスト」を数値比較。
- **決定論検証 (TC-206-07)**: `result_a == result_b` (frozen dataclass の `==` ビット同一)。数値近似は `pytest.approx`。
  Mapping (`evidence_by_k`) の等価も dict 比較で担保。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError)`。
- **実行**: `uv run pytest tests/test_segmentation.py`。ベースラインは全テスト green を維持 (既存無改変)。
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_discrimination.py`,
  `tests/test_sequential_engine.py`, `CLAUDE.md` (L21-23)

## 6. 注意事項

### ⚠️ 設計判断フラグ (tdd-requirements / tdd-testcases で確定すべき点)

1. **区間コストのメモ化キー**: `(start, end)` (両端 inclusive) をキーに `dict[tuple[int,int], float]` で
   Σbic をキャッシュ。貪欲挿入・±G 細密スキャンで同一区間が繰り返し出るため必須 (TC-206-05 の呼び出し抑制)。
   warm-start 逐次は区間先頭からの依存があるため「(start,end) が同じなら Σbic も同一」が成立する前提を明示する。
2. **合計コストの定義の一貫性**: `total_cost(boundaries) = Σ_{seg} interval_bic(seg) + penalty_beta·len(boundaries)·ln(n_frames)`。
   `evidence_by_k[k]` はこの total_cost を保持 (k = セグメント数 = len(boundaries)+1)。ペナルティは**境界数**
   (= k-1) に比例 (D5「β·(境界数)」)。テスト期待値はこの式で固定する。
3. **打ち切り条件 (TC-206-03)**: 「直前 k の最良 total_cost − 現 k の最良 total_cost」= 改善量。
   改善量 < `improvement_threshold` で打ち切り、その k は**採択しない** (直前 k を最終採択)。
   `max_segments` は安全上限 (境界数ではなくセグメント数 k の上限、既定 6) — 到達前に閾値で止まるのが正常系。
4. **粗→細 2 段 (TC-206-05)**: 粗グリッド (coarse_step 刻み) で境界候補を評価 → 採択境界の周囲 ±coarse_step を
   1 刻みで再スキャンして最良位置へ再配置。細密化後コストが粗スキャン時以下になること + キャッシュで
   総評価回数が抑制されることの両方を検証。細密スキャンでもメモ化キャッシュを共用する。
5. **境界の表現と昇順不変**: `boundaries` は「セグメント境界となるフレーム index」の昇順 tuple。
   区間 [prev_boundary, next_boundary) の半開/閉区間規約 (start inclusive / end の扱い) を 1 つに固定し、
   `n_segments == len(boundaries)+1` を常に満たす。端 (0 と n_frames) は boundaries に含めない設計が自然。
6. **分割仮説 phases の「区間代表相」(D6)**: 各 k の Hypothesis.phases に何を入れるか。最小実装は
   区間逐次 refine の**代表フレーム (例先頭) の確定相**、または `initial_phases` をそのまま。D6 は
   「区間ごとの相構成は判別 FR-313 側が持つ / 分割仮説は境界情報が主」なので phases は代表相で足りる。
   tdd-red で確定 (テストは主に境界・evidence_by_k・partitions の本数を検証)。
7. **縮退・境界ケース**:
   - `n_frames == 1` / 2 未満: 分割不能 → k=1 のみ返す (warnings に理由)。
   - 全フレーム非有限 (backend 全滅): k=1・Σbic=inf を避け、warnings + 分割なしへ縮退 (非有限を漏らさない)。
   - `coarse_step >= n_frames`: 挿入候補が空 → k=1 で確定。
   - `fixed_phases` 指定時: 区間逐次 refine に固定相を連結、固定相 index は `("scale",)` のみ解放 (n_params 整合)。
8. **ledger kind**: `"segmentation.*"` 前置 (discrimination は `"segmentation" ではなく "discrimination.*"`)。
   境界採択・打ち切り・細密化イベントを payload 付きで append。`ledger=None` なら記録スキップで結果不変。
   `SegmentationResult.ledger` は渡された ledger (None なら新規生成) を返す契約 (interfaces.py フィールド必須)。

### その他の技術的制約

- **決定論**: SimulatedBackend / 逐次ループはすべて決定論済み。segmentation 側も乱数・集合反復・時刻を持ち込まない。
  `Hypothesis.id` は決定論的に採番 (先例 `multistart-basin-{order}` / discrimination の id 採番)。
  同コスト候補の tie-break を安定順序で固定 (TC-206-07 ビット同一の要)。
- **性能**: メモ化で区間コスト評価を O(候補数) から実質 O(異なる区間数) に抑える (NFR-002・TC-206-05)。
  逐次は direct refine (`seq_max_cycles=10`)。テストは小グリッド合成で軽量に。
- **後方互換**: `operando/__init__.py` の `__all__` へ `SegmentationConfig`/`SegmentationResult`/`segment_series` を
  アルファベット順維持で追記。既存 export (discrimination/echem/cell_phases) は無改変。
- **参照元**: `src/tsumugin/operando/discrimination.py`, `src/tsumugin/evidence/ic.py`,
  `src/tsumugin/sequential/engine.py`, `src/tsumugin/model/hypothesis.py`,
  `docs/design/m3-operando/architecture.md`, `docs/design/m3-operando/design-interview.md`, `CLAUDE.md`
