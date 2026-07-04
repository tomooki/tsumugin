# TASK-0032 TDD 開発コンテキストノート

**タスク**: operando/discrimination — 固溶体 vs 二相判別 (FR-313)。`operando/discrimination.py` に
`DiscriminationConfig` / `DiscriminationResult` / `discriminate_interval(backend, series, frame_range, initial_phases, ...)` を実装する
**要件名**: m3-operando / **タスクID**: TASK-0032 / **タイプ**: TDD / **推定 6h**
**フェーズ**: Phase 4 / **信頼性**: 🔵 6 / 🟡 1 (FR-313 / 設計 D4 / REQ-010/101 / EDGE-005 / AC TC-204 系)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando (想定)
**依存タスク**: 前提 TASK-0026/0028/0030/0031 (すべて完了) / 後続 TASK-0035

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

operando 区間 (フレーム範囲) に対し、**同一データを説明する 2 つの競合仮説**を構築して evidence (bic) で判別する:

- **仮説 A (固溶体 = "solid_solution")**: 区間フレームを**単相 warm-start 逐次 direct refine (格子解放)** し、
  区間合計 Σbic_A + 格子トラジェクトリを得る 🔵 *設計 D4*
- **仮説 B (二相 = "two_phase")**: **端成分 2 相** — 区間端点の A 仮説格子で初期化・**格子固定、
  scale/wt のみ解放**で逐次精密化し、区間合計 Σbic_B + 分率トラジェクトリを得る 🔵 *設計 D4 (端点格子初期化は 🟡)*
- **両仮説の区間端点フレームでマルチスタート必須適用** (REQ-004/FR-233、N=8 既定)。
  basin 情報を `metrics.multistart` に記録 🔵
- **verdict**: ΔBIC ≥ 閾値 (既定 10.0) で優位側、未満は `"undecided"` + ReviewQueue 通知
  (**ブロックしない**) 🔵 *REQ-101/FR-122*
- **両仮説とも高 R** (rwp > `high_r_threshold`、既定 30.0): 未知相フラグ + エスカレーション、**判別しない** 🔵 *EDGE-005*
- **固定相 (`FixedPhaseSpec`) 対応**: 両仮説に常駐・構造固定・scale のみ解放 🔵 *FR-312 連携*
- **全操作 ledger 記録** (追記専用、`verify()` 常に True) 🔵 *P2/NFR-105*

**🚨 絶対制約 (完了条件 7 項目と直結)**:
1. 固溶体合成データで `"solid_solution"` 判別 🔵 *TC-204-01*
2. 二相合成データで `"two_phase"` 判別 🔵 *TC-204-02*
3. マルチスタート必須適用 (spy 検証) + `metrics.multistart` 付与 🔵 *TC-204-03*
4. 僅差 → `"undecided"` + Queue 通知 (処理をブロックしない) 🔵 *TC-204-04*
5. 両仮説高 R → エスカレーション・判別なし 🔵 *TC-204-05/EDGE-005*
6. 決定論: 判別一式が 2 回実行でビット同一 (乱数不使用) 🔵 *TC-204-06/NFR-102*
7. 判別 1 区間 (N=8) < 30 秒 smoke 🟡 *TC-209-03/NFR-001*
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行)。
- 失敗は例外でなく chi2=inf の結果へ変換し縮退処理 (CLAUDE.md 不変条件)。
- 既存テスト無改変 green (後方互換 REQ-404)。

**参照元**: `docs/tasks/m3-operando/TASK-0032.md`, `docs/design/m3-operando/architecture.md` D4 (L71-76),
`docs/design/m3-operando/dataflow.md` (FR-313 判別のシーケンス L53-77), `docs/design/m3-operando/interfaces.py` L252-284,
`docs/spec/m3-operando/requirements.md` REQ-010 (L48-51)/REQ-101 (L94-95)/EDGE-005 (L125),
`docs/spec/m3-operando/acceptance-criteria.md` TC-204-01〜06 (L37-42)/TC-209-03 (L85)

---

## 1. 技術スタック

- **言語 / ランタイム**: Python >=3.12 (`pyproject.toml`、uv 管理、src layout + hatchling)。数値は numpy のみ (REQ-403)。
- **テスト**: `uv run pytest` / カバレッジ `uv run pytest --cov=tsumugin`。Lint `uvx ruff check src tests` (line-length 100)。
- **依存導入**: `uv sync --extra gsas` (プレーン `uv sync` は禁止 — gsas 依存が外れる)。
- **アーキテクチャパターン**: 不変データ (frozen dataclass + `with_updates()`) + `typing.Protocol` 境界 +
  追記専用ストア (Ledger/Snapshot) + 純関数コア。M0〜M2 と同一。
- **本タスクの対象レイヤ**: `operando/discrimination.py` = **オーケストレーション純関数**
  (`discriminate_interval` は下位部品 — 逐次 refine / MultistartEngine / BICBackend / ReviewQueue / Ledger — を束ねる)。
- **参照元**: `pyproject.toml`, `CLAUDE.md` (L15-27, L63-77), `docs/design/m3-operando/architecture.md` (L18-22)

## 2. 開発ルール

- **TDD 厳守**: Red (失敗テスト) → Green (最小実装) → Refactor。テストなしの実装コミット禁止。
- **テスト配置 1:1**: 本タスクは `tests/test_discrimination.py` (新規) — 設計のテストファイル一覧に明記
  (`docs/design/m3-operando/architecture.md` L121-122)。
- **決定論 (NFR-102)**: 乱数/IO なし・安定ソート・dict 反復順非依存。同一入力 2 回でビット同一。
- **非破壊性 (P2)**: 入力 phases / series を破壊しない。Ledger は append のみ。ReviewQueue は追記型。
- **非有限を漏らさない** (M1 教訓): inf/NaN を下流へ漏らさない。バックエンド失敗は chi2=inf 結果 → 縮退処理。
- **後方互換 (REQ-404)**: 新規モジュール追加のみ。`operando/__init__.py` の `__all__` へ非破壊追記。
- **コーディング規約**: snake_case / 型注釈必須 / 日本語 docstring 可 / 実装コメントに信頼性レベル (🔵🟡) 併記が先例。
- **参照元**: `CLAUDE.md` (L40-77), `docs/implements/m3-operando/TASK-0028/note.md` (先例),
  `src/tsumugin/operando/__init__.py`

## 3. 関連実装 (実 API 確認済み)

### 3.1 `src/tsumugin/multistart/engine.py` — MultistartEngine (TASK-0028 完了・本タスクが消費)
- `MultistartEngine(backend, *, config: MultistartConfig = MultistartConfig(), ledger: Ledger | None = None)`
- `run(phases, two_theta, intensity, *, free_suffixes=("scale","lattice.a","lattice.b","lattice.c"), weights=None) -> MultistartResult`
- `MultistartResult(basins, n_starts, n_diverged, promoted, is_global_corroborated, warnings=())` (frozen)。
  複数 basin 時のみ `promoted` に `Hypothesis` (id=`multistart-basin-{order}`、`metrics.multistart={"n","n_basins","n_diverged"}`)。
  全滅は警告 + 空 basins (非例外)。ledger kind は `"multistart.*"`。
- `MultistartConfig(n_starts=8, spec=PerturbationSpec(), basin_rel_tol=1e-2, ms_max_cycles=15)`
  (`src/tsumugin/multistart/perturb.py`)。
- **判別での使い方**: 両仮説の**区間端点フレーム**で `run` を呼ぶ (仮説 B は格子固定なので
  `free_suffixes` を `("scale","wt_frac")` 等へ差し替える設計余地 — tdd-red で確定)。

### 3.2 `src/tsumugin/operando/cell_phases.py` — FixedPhaseSpec (TASK-0030 完了)
- `FixedPhaseSpec(phase: PhaseInstance, label: str)` (frozen)。
- `fixed_free_suffixes(spec) -> ("scale",)` — 固定相は常に scale のみ解放。呼び側が
  `param_name(i, "scale")` で free_params を構成する契約 (docstring に TASK-0032 が呼び側と明記)。
- `CELL_PHASE_PRESETS` — "Be"/"Al"/"graphite" (テストデータとして利用可)。

### 3.3 `src/tsumugin/sequential/series.py` — FrameSeries (TASK-0011 完了)
- `FrameSeries(two_theta, intensities[(n_frames, n_points)], axis_values=(), axis_kind="index", channels=())` (frozen)。
  `__post_init__` で形状検証 (ValueError)。`n_frames` プロパティ。
- 判別は `series.intensities[i]` でフレーム i の強度を取り出して refine する。

### 3.4 `src/tsumugin/backends/base.py` — 精密化契約
- `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)` (frozen)。
- `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params=frozenset(), globals={}, warnings=())` (frozen)。
- `RefinementBackend` Protocol: `name` + `refine(model, *, max_cycles=20) -> RefinementResult`。
- `param_name(i, key) -> "phase{i}.{key}"` / `parse_param` ("global.*" は (-1, key))。

### 3.5 `src/tsumugin/backends/simulated.py` — SimulatedBackend (合成データ生成)
- `SimulatedBackend(*, peak_fwhm=0.2, wavelength=..., hkl_table=None, absorption=None)`。
- スカラーキーは `_SCALAR_KEYS = ("scale", "wt_frac")` — **仮説 B の scale/wt 解放は
  `"phase{i}.scale"` / `"phase{i}.wt_frac"` で表現可能**。格子は `"lattice.a/b/c"`。
- `simulate(phases, two_theta)` (Ycalc・乱数なし → ビット同一) で固溶体/二相の合成系列を生成できる:
  固溶体 = 単相の格子 a をフレームで連続変化、二相 = 端成分 2 相の scale (分率) をフレームで漸移。
- `peak_positions(phase, two_theta)` — ピーク位置確認用。

### 3.6 evidence / selection / store
- `src/tsumugin/evidence/ic.py::BICBackend.score(metrics) -> EvidenceResult(value = chi2 + k·ln(max(n_obs,1)))`。
  区間 Σbic は各フレーム RefinementResult から `RefinementMetrics` を組んで加算する。
- `src/tsumugin/selection/review_queue.py::ReviewQueue(ledger=None)`:
  `add(reason, *, hypothesis_id=None, frame_index=None, detail="") -> ReviewItem`。
  `reason` は Literal `"all_high_r" | "unknown_phase" | "close_competitor" | "guard_escalated"`。
  僅差は `"close_competitor"`、EDGE-005 は `"all_high_r"` (または `"unknown_phase"`) が対応。
- `src/tsumugin/selection/engine.py::detect_escalations(..., high_r_threshold=30.0)` —
  高 R 閾値 30.0 の先例 (`DiscriminationConfig.high_r_threshold=30.0` と一致)。
- `src/tsumugin/store/ledger.py::Ledger.append(kind, payload)` / `verify()`。payload は素の型のみ。

### 3.7 warm-start 逐次パターンの先例
- `src/tsumugin/sequential/engine.py::SequentialEngine`: 直近成功フレームの確定 phases を
  `warm_phases` として次フレーム direct refine の初期値に使う (L199-328)。`seq_max_cycles=10` 既定 (L72)。
  失敗フレームは warm start に採らない。**判別の区間内逐次 refine (軽量版) はこのパターンを踏襲**
  (changepoint/木探索なしの直呼びで足りる — 設計 D4/D5「軽量逐次 refine」)。
- `src/tsumugin/model/hypothesis.py`: `Hypothesis(id, phases, parent_id=None, metrics=None, status="candidate", accepted_by=None, frame_range=None)`、
  `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence={}, multistart=None)`。
  `DiscriminationResult.hypothesis_single/two_phase` はこの `Hypothesis` で表す (`frame_range` フィールドが使える)。

## 4. 設計文書

- **契約 (必達)**: `docs/design/m3-operando/interfaces.py` L252-284
  - `DiscriminationConfig(close_threshold=10.0, multistart=MultistartConfig(), high_r_threshold=30.0, seq_max_cycles=10)` (frozen)
  - `DiscriminationResult(verdict: Literal["solid_solution","two_phase","undecided"], delta_evidence: float (= bic_A − bic_B),
    hypothesis_single: Hypothesis, hypothesis_two_phase: Hypothesis, multistart_single: MultistartResult,
    multistart_two_phase: MultistartResult, escalations: tuple[str, ...], warnings: tuple[str, ...] = ())` (frozen)
  - `discriminate_interval(backend, series, frame_range: tuple[int,int], initial_phases, *,
    config=DiscriminationConfig(), fixed_phases: tuple[FixedPhaseSpec, ...] = (), ledger=None, queue=None) -> DiscriminationResult`
- **設計 D4** (`docs/design/m3-operando/architecture.md` L71-76): 仮説 A = 単相 warm-start 逐次 direct refine
  (格子解放)・区間合計 bic / 仮説 B = 端成分 2 相 (区間端点の A 仮説格子で初期化・格子固定 🟡)、
  scale/wt 変化のみ解放で逐次精密化・区間合計 bic / 両仮説の区間端点でマルチスタート必須 (REQ-004) +
  basin 情報を metrics に記録 / verdict: ΔBIC ≥ 閾値で優位側、未満 "undecided" + Review Queue。
- **dataflow FR-313 シーケンス** (`docs/design/m3-operando/dataflow.md` L53-77):
  discriminate_interval → 仮説A (Σbic_A + 格子トラジェクトリ) → 仮説B (Σbic_B + 分率トラジェクトリ) →
  MultistartEngine (両仮説端点 N=8、basin 数/昇格仮説/metrics.multistart) → ΔBIC = bic_A − bic_B →
  |ΔBIC| ≥ 閾値なら verdict=優位側 / 僅差なら Queue.add(close_competitor 相当、ブロックしない) +
  verdict="undecided" (暫定 = 優位側)。エラーハンドリング表 (L106-118): 両仮説高 R → 未知相フラグ +
  エスカレーション・判別なし / マルチスタート全滅 → 警告 + 元仮説維持。
- **要件**: REQ-010 (両仮説マルチスタート付き精密化 + bic 判別、ΔBIC<10 はエスカレーション、nested 裁定は M5)、
  REQ-101 (僅差 → 自動確定せず暫定判別 + Queue)、REQ-004 (FR-313 判別時マルチスタート必須)、
  REQ-102 (発散除外・全滅は警告付き継続)、EDGE-005 (両仮説高 R → 未知相フラグ + エスカレーション・判別しない)。
- **AC**: TC-204-01〜06 (`docs/spec/m3-operando/acceptance-criteria.md` L37-42) + TC-209-03 (<30 秒 smoke, L85)。
- **参照元**: `docs/design/m3-operando/architecture.md`, `docs/design/m3-operando/dataflow.md`,
  `docs/design/m3-operando/interfaces.py`, `docs/spec/m3-operando/requirements.md`,
  `docs/spec/m3-operando/acceptance-criteria.md`, `docs/spec/m3-operando/user-stories.md`

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov (`pyproject.toml [tool.pytest.ini_options]`, testpaths=["tests"])。
  `tests/conftest.py` が GSAS-II 未導入環境で `gsas` マーカーを自動 skip — **本タスクは SimulatedBackend /
  Fake/Spy のみで GSAS-II 非依存 (マーカー不要)**。
- **新規テストファイル**: `tests/test_discrimination.py` (実装 `src/tsumugin/operando/discrimination.py` と 1:1)。
- **命名/コメント規約**: 関数名 `test_*`、日本語コメント【テスト目的】【テスト内容】【期待される動作】+
  信頼性レベル 🔵🟡 (先例: `tests/test_multistart_engine.py`, `tests/test_cell_phases.py`)。
- **合成データの作り方 (決定論)**:
  - 固溶体系列: `SimulatedBackend.simulate` で単相の `lattice.a` をフレームごとに線形変化させ
    `FrameSeries(two_theta, np.stack(rows))` を構成 (Ycalc ベース・乱数なし)。
  - 二相系列: 端成分 2 相 (格子固定・別位置ピーク) の scale を α: 1→0 / β: 0→1 で漸移させ重ね合わせ。
  - 先例グリッド: `GRID = np.arange(15.0, 60.0, 0.02)` (`tests/test_sequential_engine.py`)。
    <30 秒 smoke には小さめグリッド (例 0.05 刻み) も可。
- **テストダブルの先例**: `tests/test_multistart_engine.py` の `InitialValueFakeBackend` 系 (初期値依存収束・
  発散注入)、`tests/test_sequential_engine.py` の `PhaseRecordingSpyBackend` / `FrameFailBackend` (L117-229)。
  TC-204-03 のマルチスタート spy は「`backend.refine` 呼び出し回数が端点フレームで n_starts 倍になる」
  「free_params/max_cycles=ms_max_cycles が伝播する」を記録スパイで検証するのが既存流儀。
- **決定論検証**: `result_a == result_b` (frozen dataclass の `==` ビット同一)。数値近似は `pytest.approx`。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError)`。
- **実行**: `uv run pytest tests/test_discrimination.py`。ベースラインは全テスト green を維持 (既存無改変)。
- **参照元**: `pyproject.toml`, `tests/conftest.py`, `tests/test_multistart_engine.py`,
  `tests/test_sequential_engine.py`, `tests/test_cell_phases.py`, `CLAUDE.md` (L21-23)

## 6. 注意事項

### ⚠️ 設計判断フラグ (tdd-requirements / tdd-testcases で確定すべき点)

1. **EDGE-005 の「判別なし」と verdict Literal の整合**: `DiscriminationResult.verdict` は 3 値
   (`"solid_solution" | "two_phase" | "undecided"`) しかない。両仮説高 R の「判別しない」は
   **verdict="undecided" + escalations に高 R/未知相を示す文字列**で表現するのが契約整合的
   (interfaces.py L270 `escalations: 僅差/高R`)。ReviewQueue の reason は `"all_high_r"` が既存 Literal に存在。
2. **ΔBIC の符号規約**: `delta_evidence = bic_A − bic_B` (interfaces.py L265)。bic は小さいほど良い →
   ΔBIC ≤ −閾値 なら A 優位 ("solid_solution")、ΔBIC ≥ +閾値 なら B 優位 ("two_phase")、
   |ΔBIC| < 閾値 なら "undecided"。テスト期待値はこの規約で固定する。
3. **仮説 B のマルチスタート free_suffixes**: B は格子固定なので既定
   `("scale","lattice.a","lattice.b","lattice.c")` をそのまま使うと格子が動いて D4 違反。
   `("scale","wt_frac")` 等 (SimulatedBackend の `_SCALAR_KEYS` に整合) へ差し替える必要がある。
   `MultistartEngine.run(free_suffixes=...)` が既にキーワードで受ける (追加実装不要)。
4. **`metrics.multistart` の付与先**: `MultistartEngine` は複数 basin 時のみ昇格仮説に multistart を付ける。
   判別では **単一 basin でも** `DiscriminationResult.hypothesis_single/two_phase.metrics.multistart` に
   `{"n","n_basins","n_diverged"}` を判別側で付与する (完了条件 3「metrics.multistart」/D4「basin 情報を
   metrics に記録」)。`MultistartResult` から判別側が組む。
5. **僅差の暫定 verdict**: dataflow は「verdict = undecided (暫定 = 優位側)」と記す。契約フィールドは
   verdict 1 本なので **verdict は "undecided"** とし、暫定優位側は delta_evidence の符号で読める
   (追加フィールドは設けない) のが最小実装。Queue 通知は `queue=None` なら**スキップして続行**
   (ブロックしない、ledger/queue とも省略可能な依存注入)。
6. **固定相の組み込み**: `initial_phases` (活物質) + `fixed_phases` の phase を連結して refine し、
   固定相 index には `fixed_free_suffixes(spec) == ("scale",)` のみ解放。固定相の格子は
   精密化後もビット不変 (先例 `tests/test_cell_phases.py` TC-BV03)。bic の n_params にも整合させる。
7. **区間内逐次 refine の失敗フレーム**: バックエンド失敗 = chi2=inf。区間 Σbic に inf を混ぜると
   判別が壊れる → 高 R/発散フレームの扱い (除外 + 警告 or エスカレーション) を要件で確定する。
   全フレーム inf は EDGE-005 経路に縮退させるのが安全。

### その他の技術的制約

- **決定論**: MultistartEngine / SimulatedBackend / 逐次ループはすべて決定論済み。判別側も
  乱数・集合反復・時刻を持ち込まない。`Hypothesis.id` は決定論的に採番 (先例 `multistart-basin-{order}`)。
- **性能 (TC-209-03)**: 判別 1 区間 <30 秒。マルチスタートは**区間端点 2 フレーム × 2 仮説のみ**
  (全フレームに掛けない)。逐次は direct refine (`seq_max_cycles=10`)。テストは小グリッド合成で smoke。
- **frame_range**: `tuple[int, int]` — 両端 inclusive が自然 (dataflow「区間端点」)。範囲外 index は
  FrameSeries 形状検証外なので判別側で ValueError にする (器の契約違反、`series.py` の慣習)。
- **ledger kind**: `"discrimination.*"` 前置が先例流儀 (multistart は `"multistart.*"`)。
  ledger=None なら記録スキップでも結果不変 (先例 TC-BV05)。
- **参照元**: `src/tsumugin/multistart/engine.py`, `src/tsumugin/backends/simulated.py`,
  `src/tsumugin/operando/cell_phases.py`, `src/tsumugin/selection/review_queue.py`,
  `docs/design/m3-operando/dataflow.md`, `CLAUDE.md`
