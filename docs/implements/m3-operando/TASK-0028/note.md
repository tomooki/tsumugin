# TASK-0028 TDD 開発コンテキストノート

**タスク**: multistart/basin + MultistartEngine (FR-230/232 / 設計 D2/D3)
**要件名**: m3-operando / **タスクID**: TASK-0028 / **タイプ**: TDD / **推定 5h**
**フェーズ**: Phase 2 / **信頼性**: 🔵 5 / 🟡 1 (FR-230/232 / 設計 D2/D3 / REQ-002〜006・102 / AC TC-201 系)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

マルチスタート大域最適確認 (FR-230) の**basin クラスタリング**と**実行エンジン**を、
TASK-0027 で実装済みの決定論摂動列 (`generate_starts`) の上に構築する。新設 2 ファイル:

### (A) `src/tsumugin/multistart/basin.py` — 収束解の basin クラスタ (D3)

1. **`BasinInfo` (frozen dataclass)** — 1 つの basin の要約 (interfaces.py L143-151):
   - `representative: RefinementResult` — **chi2 最小解** (basin 代表)。
   - `member_starts: tuple[int, ...]` — この basin に属する start index 群 (昇順)。
   - `chi2: float` — 代表の chi2。
   - `evidence: float` — 代表の bic (BICBackend で算出)。
2. **basin クラスタ関数** (例 `cluster_basins(results, *, basin_rel_tol)`):
   - 各収束解 (`RefinementResult`) を**正規化パラメータベクトル**へ変換 (初期値スケールで無次元化)。
   - 2 解の**相対距離 < `basin_rel_tol`** (既定 1e-2) を同一 basin へ連結。
   - **union-find** で連結成分を作る (`search/clustering.py` の `_UnionFind` パターン再利用)。
   - basin 代表 = **chi2 最小解** (同点は start index 小優先で決定論)。
   - basins は **evidence 昇順** で並べる (小さいほど良い = BIC 慣習)。

### (B) `src/tsumugin/multistart/engine.py` — `MultistartEngine` (D2)

3. **`MultistartResult` (frozen dataclass)** (interfaces.py L153-162):
   - `basins: tuple[BasinInfo, ...]` (evidence 昇順) / `n_starts: int` / `n_diverged: int` (除外数) /
     `promoted: tuple[Hypothesis, ...]` (複数 basin 時の昇格仮説、単一なら空) /
     `is_global_corroborated: bool` (n_basins==1) / `warnings: tuple[str, ...] = ()`。
4. **`MultistartEngine(backend, *, config=MultistartConfig(), ledger=None)`** + **`.run(...)`** (L172-191):
   - **`generate_starts(phases, config)`** で N 組の初期値を生成 (TASK-0027)。
   - 各 start を **`backend.refine`** で**direct 精密化** (staged でなく `free_suffixes` を free_params に、
     `max_cycles=config.ms_max_cycles` 既定 15)。**純関数ループ = map 置換可能** (REQ-005 並列化非阻害)。
   - **発散除外**: `chi2 == inf` (or 非有限) の start を basin から除外し **`n_diverged`** にカウント。
   - 残りを **basin クラスタ** (B の関数) にかける。
   - **複数 basin → 各 basin を `Hypothesis` へ昇格** (`metrics.multistart` 付き / REQ-003)。
     単一 basin → `is_global_corroborated=True` (「大域最適の傍証あり」)。
   - **全滅 (全 start 発散)** → 警告 + 空 basins (元仮説維持) (REQ-102 / EDGE-002)。
   - **全操作を ledger 記録** (ledger 提供時)。**決定論** (2 回でビット同一 / NFR-102)。

**🚨 絶対制約 (完了条件と直結)**:
- **単峰 → n_basins=1・`is_global_corroborated=True`** (TC-201-02 / EDGE-001)。
- **双峰 (FakeBackend で初期値依存の 2 解) → n_basins=2・両 basin の chi2/evidence 報告** (TC-201-03)。
- **複数 basin が Hypothesis へ昇格し rank 可能** (TC-201-04 / FR-232 / REQ-003)。
- **発散 start (chi2=inf) 除外 + カウント、全滅で警告 + 空 basins** (TC-201-05 / REQ-102 / EDGE-002) 🟡。
- **`metrics.multistart {n, n_basins, n_diverged}` 記録** (TC-201-06 / REQ-006)。
- **決定論**: 乱数不使用、2 回実行でビット同一 (basins 順・member_starts・promoted すべて `==`) 🔵。
- **非破壊性 (P2)**: 入力 `phases` を破壊しない。ledger は append のみ (削除・上書き API 禁止)。
- **バックエンド失敗は例外でなく chi2=inf 結果** に変換しガードレールで処理 (CLAUDE.md 不変条件)。
- **git commit しない** / **質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0028.md`, `docs/design/m3-operando/interfaces.py` L143-191,
`docs/design/m3-operando/architecture.md` D2 (L62-64) / D3 (L66-69) / モジュール表 L35-36,
`docs/spec/m3-operando/requirements.md` REQ-002〜006 / REQ-102 / EDGE-001/002/101,
`docs/spec/m3-operando/acceptance-criteria.md` TC-201-02〜06

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。**numpy 依存** (正規化パラメータベクトル距離)。
  GSAS-II 非依存 (FakeBackend でテスト → `gsas` マーカー不要)。
- **アーキテクチャパターン**: frozen dataclass 不変値オブジェクト (`BasinInfo` / `MultistartResult`) +
  **純関数コア** (basin クラスタは副作用なし・決定論) + **薄いオーケストレータ** (`MultistartEngine`)。
  精密化バックエンドは `typing.Protocol` (`RefinementBackend`) で交換可能。evidence は `BICBackend`。
- **モジュール配置**: `src/tsumugin/multistart/` に **`basin.py` / `engine.py` を追加** (`perturb.py` は TASK-0027 済)。
  `__init__.py` の `__all__` に新公開シンボルを追記 (非破壊)。
- **参照元**: `CLAUDE.md` (技術スタック / 不変条件), `pyproject.toml`, `src/tsumugin/multistart/__init__.py`,
  `docs/design/m3-operando/architecture.md` (ディレクトリ構造 L108-123)

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: 型 PascalCase (`BasinInfo` / `MultistartResult` / `MultistartEngine`)、関数/フィールド snake_case
  (`member_starts` / `n_diverged` / `is_global_corroborated` / `cluster_basins` / `run`)、ファイル snake_case。
- **型注釈必須** (`any` 回避)。`tuple[BasinInfo, ...]` / `tuple[Hypothesis, ...]` / `RefinementResult` /
  `np.ndarray` / `Ledger | None`。新規ファイル冒頭に `from __future__ import annotations`。
  docstring 日本語可、FR/REQ/TC 番号 + 信頼性 🔵🟡🔴 を付す慣習。
- **キーワード専用引数**: interfaces.py の契約に厳密準拠 —
  `MultistartEngine(backend, *, config=..., ledger=...)` / `.run(phases, two_theta, intensity, *,
  free_suffixes=("scale","lattice.a","lattice.b","lattice.c"), weights=None)`。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **不変条件 (仕様由来・違反禁止)**:
  - **P2 非破壊性**: 入力破壊なし。Ledger は append のみ (削除・上書き API を実装しない)。
  - **NFR-102 決定論**: 乱数不使用。2 回実行でビット同一。
  - **NFR-105**: ledger は追記専用 + ハッシュチェーン (`verify()` 常に True)。
  - **バックエンド失敗は chi2=inf 結果へ変換** (例外にしない)。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。**質問しない** (自律実行)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `CLAUDE.md` (コーディング規約 / 不変条件), `docs/spec/m3-operando/note.md`,
  `docs/implements/m3-operando/TASK-0027/note.md` (前タスク運用の範)

---

## 3. 関連実装 (依存・参考パターン)

### 依存する既存実装 (そのまま利用)

- **`src/tsumugin/multistart/perturb.py`** (TASK-0027 **完了済・実 API 確認済**):
  - `generate_starts(phases, *, config: MultistartConfig) -> tuple[tuple[PhaseInstance, ...], ...]`
    (L76-138)。**i=0 無摂動 (基準)**、i≥1 は決定論摂動。戻り値は長さ `config.n_starts`、各要素は
    摂動済み phases (相数・相順保存)。**MultistartEngine.run はこれを各 start の初期値に使う**。
  - `MultistartConfig(n_starts=8, spec=PerturbationSpec(), basin_rel_tol=1e-2, ms_max_cycles=15)` (L36-49)。
    **本タスクで `basin_rel_tol` (basin 距離閾値) と `ms_max_cycles` (refine 上限) を消費**。
  - `PerturbationSpec(lattice_frac=0.02, scale_log_range=0.5, occupancy_delta=0.1)` (L22-33)。
- **`src/tsumugin/backends/base.py`**:
  - `RefinementBackend` Protocol (L46-53): `name: str` + `refine(model, *, max_cycles=20) -> RefinementResult`。
    **engine は `backend.refine` を direct で N 回呼ぶ** (D2)。
  - `RefinementModel(phases, free_params, two_theta, intensity, weights=None)` (L17-25)。
    **`free_params` は `"phase{i}.{suffix}"` 形式** — engine は `free_suffixes` × 全相で構築。
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params, globals, warnings)`
    (L28-43)。**basin の正規化ベクトルは result.phases のパラメータから作る。chi2 で代表選出/発散判定**。
  - `param_name(phase_index, key) -> "phase{i}.{key}"` (L56-58) — **free_params 構築に使う**。
    `parse_param` (L61-74) は逆変換 (相 index 抽出、global は -1)。
- **`src/tsumugin/evidence/`** (`BICBackend`):
  - `evidence/ic.py` の `BICBackend.score(metrics) -> EvidenceResult` (L16-22):
    **`BIC = chi2 + n_params·ln(max(n_obs,1))`** (小さいほど良い)。**basin の `evidence` フィールドはこれで算出**。
  - `evidence/base.py` の `EvidenceResult(backend, value, logz_err=None)` (L11-17)。
    `RefinementResult` → `RefinementMetrics` へ詰め替えて `score` に渡す (rwp/gof は basin では chi2 主体で可)。
- **`src/tsumugin/model/hypothesis.py`** (TASK-0025 で `multistart` 追加済):
  - `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence={}, multistart=None)` (L13-25)。
    **`multistart: Mapping[str, int] | None`** — 昇格仮説に `{"n","n_basins","n_diverged"}` を記録 (REQ-006/TC-201-06)。
  - `Hypothesis(id, phases, parent_id=None, metrics=None, status="candidate", accepted_by=None,
    frame_range=None)` (L27-38)。**複数 basin → 各 basin の代表 phases で `Hypothesis` を生成し `promoted` へ**。
- **`src/tsumugin/store/ledger.py`**:
  - `Ledger.append(kind, payload) -> LedgerEntry` (L70-83)。**追記のみ**。engine の各操作 (start refine /
    発散除外 / basin 確定 / 昇格) を `append("multistart.*", {...})` で記録。`verify()` (L89) は常に True。

### 参考パターン (既存コードから踏襲)

- **union-find (basin 連結)**: `src/tsumugin/search/clustering.py` の **`_UnionFind`** (L107-138) をそのまま範に:
  - `__init__(size)` / `find(x)` (経路圧縮) / `union(a,b)` (根は**常に index 小へ寄せて決定論**)。
  - `jaccard_clusters` (L141-209) の**クラスタ集約 → 代表選出 → 出力正規化**の流れが basin と同型:
    全対 (i<j) 距離評価 → 閾値以下を union → `clusters.setdefault(find(i), []).append(i)` で集約 →
    各クラスタで代表選出 (clustering は FoM 最大、basin は **chi2 最小**) → **出力を昇順 key でソート**
    (clustering は代表 index、basin は **evidence 昇順**)。**縮退 (空入力) は空タプルへ**。
- **正規化パラメータ距離 (D3)**: 各解のパラメータ (格子 a/b/c、scale、占有率) を**初期値スケールで無次元化**
  したベクトルにし、相対距離 (例 L2 or 最大成分) が `basin_rel_tol` 未満で同一 basin。乱数不使用・
  安定順で決定論 (architecture.md L129「クラスタ順は index 安定ソート」)。🟡 距離式の詳細は tdd-testcases で確定。
- **frozen dataclass + 昇順正規化**: `ClusterResult` (clustering L35-41) が `member_starts` 昇順・
  代表 index の範。`BasinInfo` も `member_starts` 昇順で正規化。
- **発散を chi2=inf で表現**: `test_tree_search.py` の `FakeBackend` (L85-131) が既に `chi2=inf` を注入し
  `converged=math.isfinite(chi2)` を返す。engine は **`math.isfinite(result.chi2)` で発散判定** (例外化しない)。

### 双峰テスト用ダブルの範 (テスト設計の要)

- **`tests/test_tree_search.py` の `FakeBackend`** (L85-131) は相組合せ (phase_ref の frozenset) をキーに
  固定 chi2 を返す `chi2_by_refs` 方式。**TASK-0028 では「初期値依存で 2 解へ収束」を表現するため、
  この方式を _初期値依存_ へ拡張したダブル**が必要 (双峰 TC-201-03 用):
  - 例: 入力 `model.phases[0].lattice.a` (start ごとに摂動で異なる) を見て、**閾値で 2 つの吸引域へ写像**し、
    吸引域ごとに (固定の収束 phases, chi2) を返す。→ 半数の start が basin1、半数が basin2 へ収束。
  - **単峰用**: どの初期値でも同一収束 phases + 同一 chi2 (basin=1)。
  - **発散用**: 特定 start (or 全 start) に `chi2=inf` を返す (TC-201-05)。
  - `simulate` / `peak_positions` は不要 (engine は refine のみ呼ぶ想定)。`RefinementBackend` Protocol
    (name + refine) だけ満たせばよい。**新ダブルは `tests/test_multistart_engine.py` 内に定義**
    (test_tree_search.py は無改変)。
- **参照元**: `src/tsumugin/multistart/perturb.py`, `src/tsumugin/backends/base.py`,
  `src/tsumugin/evidence/{ic,base}.py`, `src/tsumugin/model/hypothesis.py`, `src/tsumugin/store/ledger.py`,
  `src/tsumugin/search/clustering.py` (`_UnionFind`), `tests/test_tree_search.py` (`FakeBackend`),
  `docs/design/m3-operando/interfaces.py` L143-191

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m3-operando/interfaces.py`
  - **L143-151 `BasinInfo`**: `representative: RefinementResult` (chi2 最小) / `member_starts: tuple[int,...]` /
    `chi2: float` / `evidence: float` (bic)。🔵 FR-232。
  - **L153-162 `MultistartResult`**: `basins` (evidence 昇順) / `n_starts` / `n_diverged` (除外数 🟡) /
    `promoted: tuple[Hypothesis,...]` (単一 basin なら空) / `is_global_corroborated: bool` (n_basins==1) /
    `warnings=()`。🔵 FR-232/REQ-102。
  - **L172-191 `MultistartEngine`**: `__init__(backend, *, config=MultistartConfig(), ledger=None)` /
    `run(phases, two_theta, intensity, *, free_suffixes=("scale","lattice.a","lattice.b","lattice.c"),
    weights=None) -> MultistartResult`。🔵 FR-230。
  - L86 コメント: `RefinementMetrics.multistart = {"n":8,"n_basins":1,"n_diverged":0}` (既定 None 非破壊)。
- **アーキテクチャ**: `docs/design/m3-operando/architecture.md`
  - **D2 (L62-64)**: 「マルチスタートの精密化は **direct refine**」。各 start は `backend.refine` 直呼び
    (scale+lattice、`ms_max_cycles` 既定 15)。staged フルはコスト過大 (FR-234「探索モード精密化と同等に抑える」)。
  - **D3 (L66-69)**: 「**basin クラスタリング**」。収束解を**正規化パラメータベクトル** (初期値スケールで
    無次元化) 化し、相対距離 **< tol (既定 1e-2)** を **union-find** (M1 clustering の実装パターン再利用) で連結。
    **basin 代表は chi2 最小解**。**発散 start (chi2=inf) は除外しカウント報告** (REQ-102)。
  - モジュール表 L35-36: `multistart/basin.py` (正規化距離 + union-find、REQ-002、🟡) /
    `multistart/engine.py` (`MultistartEngine.run → MultistartResult`、REQ-003〜006、🔵)。
  - 非機能 L129: 「摂動列・クラスタ順・境界候補順すべて index 安定ソート」(決定論)。
- **要件**: `docs/spec/m3-operando/requirements.md`
  - **REQ-002 (L27-28)**: 収束解をパラメータ空間でクラスタリングし、basin 数・各 basin の chi2/evidence・
    代表解を報告 🔵 FR-232。
  - **REQ-003 (L29-30)**: 複数 basin → 各 basin を別仮説へ昇格し evidence 比較へ。単一 basin は
    「大域最適の傍証あり」報告 🔵 FR-232。
  - **REQ-004 (L31-32)**: 適用範囲は設定可能、既定は accepted 最終精密化 + FR-313 判別で必須 🔵 FR-233。
  - **REQ-005 (L33-34)**: 各 start は独立な**純関数構成** (map 置換可能、Worker 並列化非阻害)。M3 は逐次で可 🔵 FR-234。
  - **REQ-006 (L35-36)**: `RefinementMetrics.multistart {n, n_basins}` として仮説へ記録 (非破壊) 🔵。
  - **REQ-102 (L96)**: 発散 (chi2=inf) start は basin から除外しカウント報告 🟡。
  - **REQ-402 (L106-107)**: マルチスタート出力は同一入力でビット同一 🔵 NFR-102。
  - **REQ-403 (L108-109)**: コア依存 numpy のみ 🔵。**REQ-404**: 非破壊追加 🔵。
- **エッジケース** (`requirements.md`):
  - **EDGE-001 (L121)**: 全 start 単一 basin → n_basins=1、「大域最適の傍証あり」🔵 (= TC-201-02)。
  - **EDGE-002**: 発散全滅 → 警告 + 空 basins + 元仮説維持 🟡 (= TC-201-05)。
  - **EDGE-101 (L128)**: N=1 → 摂動なし 1 本 (基準解のみ、basin=1) 🟡 (= TC-201-07、perturb 側と連携)。
- **受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` (TC-201 系 L14-20) — **本タスク主対象は
  TC-201-02〜06** (01/07 は TASK-0027 の perturb が主):
  - **TC-201-02 (L15)**: 単峰 → 全 start 同一解収束 → n_basins=1、「傍証あり」🔵 EDGE-001。
  - **TC-201-03 (L16)**: 双峰 (2 局所解を持つ初期値域) → n_basins=2、各 basin の chi2/evidence 報告 🔵。
  - **TC-201-04 (L17)**: 複数 basin が別仮説へ昇格され rank に現れる 🔵 FR-232。
  - **TC-201-05 (L18)**: 発散 start (chi2=inf) は除外・除外数報告、全滅で警告 + 元仮説維持 🟡 REQ-102/EDGE-002。
  - **TC-201-06 (L19)**: `metrics.multistart {n, n_basins}` が仮説に記録 🔵。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §6 FR-230 (マルチスタート) / FR-232 (basin) / FR-234 (並列化) / §13 M3。
- **前提タスク**: TASK-0026 / TASK-0027 (perturb)。**後続**: TASK-0032 (FR-313 判別で必須適用) / TASK-0033。
- **参照元**: 上記各ファイル, `docs/tasks/m3-operando/{TASK-0028.md,overview.md}`

---

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov。設定 `pyproject.toml [tool.pytest.ini_options]`
  (`markers` に `gsas`)。
- **実行コマンド**: `uv run pytest tests/test_multistart_basin.py tests/test_multistart_engine.py` (本タスク単体) /
  `uv run pytest` (全体回帰) / `uv run pytest --cov=tsumugin`。**依存導入は `uv sync --extra gsas`** (プレーン
  `uv sync` 禁止)。本タスクは FakeBackend でテスト → **GSAS-II 非依存 (`gsas` マーカー不要)**。
- **本タスクのテストファイル** (**新規**、実装 1:1 対応):
  - `tests/test_multistart_basin.py` ↔ `src/tsumugin/multistart/basin.py` (`BasinInfo` / basin クラスタ)。
  - `tests/test_multistart_engine.py` ↔ `src/tsumugin/multistart/engine.py` (`MultistartResult` /
    `MultistartEngine`)。engine 側に**初期値依存ダブル**を定義。
    (単一ファイル `tests/test_multistart_engine.py` に basin + engine をまとめる構成も可。tdd-red で確定。)
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl 対応 `test_*.py`。共通フィクスチャ `tests/conftest.py`。
  **ベースライン 523 collected** (2026-07-04 計測: `pytest --collect-only` 合計)。うち perturb は
  `tests/test_multistart_perturb.py` 18 件。本タスクは新規ファイル分だけ collected 増 (既存無改変)。
- **テストダブル方針** (双峰の要): 上記 §3「双峰テスト用ダブルの範」参照。
  `tests/test_tree_search.py` の `FakeBackend` (`chi2_by_refs` 方式) を**初期値依存へ拡張**した
  スタブを本タスクのテストファイル内に新設 (test_tree_search.py は無改変)。
  - **単峰スタブ**: 任意初期値 → 同一収束 phases + 同一 chi2 (basin=1)。
  - **双峰スタブ**: `model.phases[0].lattice.a` の閾値で 2 吸引域へ写像、域ごとに (収束 phases, chi2) 固定。
  - **発散スタブ**: 特定/全 start に chi2=inf。
- **命名/記述パターン** (`tests/test_tree_search.py` / `tests/test_clustering.py` / `tests/test_multistart_perturb.py` 準拠):
  - `PhaseInstance(phase_ref=..., lattice=LatticeParams(a,b,c), scale=...)` を組む `_phase(...)` ヘルパ。
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 近似は `pytest.approx`、**決定論は `==` (basins/member_starts/promoted のビット同一)**。
  - docstring/コメントに 🔵/🟡 と TC/REQ 番号を付す慣習。
- **本タスクで書くべき代表テスト観点** (詳細は tdd-testcases で洗い出し):
  - **basin (basin.py)**: 全解近接 → 1 basin / 2 群 → 2 basin / 代表 = chi2 最小 / member_starts 昇順 /
    basins evidence 昇順 / basin_rel_tol 境界 / 空入力縮退 / 決定論。
  - **engine (engine.py)**: 単峰 → n_basins=1・`is_global_corroborated=True` (TC-201-02) /
    双峰 → n_basins=2・両 basin chi2/evidence (TC-201-03) / 複数 basin → `promoted` 非空 & rank 可能
    (TC-201-04) / 発散 start 除外 + `n_diverged` (TC-201-05) / 全滅 → 警告 + 空 basins (TC-201-05/EDGE-002) /
    `metrics.multistart {n,n_basins,n_diverged}` 記録 (TC-201-06) / N=1 縮退 (TC-201-07/EDGE-101) /
    ledger 記録 & `verify()`==True / 2 回実行ビット同一 (決定論) / `backend.refine` が N 回 direct 呼び。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で **523 → (523 + 新規件数) で無退行維持**。
  既存テストファイルは 1 行も変更しない。`uvx ruff check src tests` clean。
- **参照元**: `pyproject.toml`, `tests/test_tree_search.py`, `tests/test_clustering.py`,
  `tests/test_multistart_perturb.py`, `tests/conftest.py`,
  `docs/spec/m3-operando/acceptance-criteria.md` (TC-201-02〜06)

---

## 6. 注意事項

### 技術的制約
- **direct refine (D2)**: engine は各 start に `backend.refine(model, max_cycles=config.ms_max_cycles)` を
  **1 回だけ** (staged 解放ループなし) 呼ぶ。`free_params` は `free_suffixes` × 各相 index を
  `param_name(j, suffix)` で組む (既定 `scale` + `lattice.a/b/c`)。
- **正規化パラメータ距離 (D3)**: 収束解のパラメータを**初期値スケールで無次元化** (相対量) してから距離。
  格子は相対 (a/a0-1 等)、scale は対数比、占有率は差分。距離式 (L2 / L∞) と `basin_rel_tol` の
  意味づけは 🟡 → tdd-testcases で確定 (境界テストで固定)。乱数不使用・安定順で決定論。
- **発散の扱い (REQ-102 / TC-201-05)**: `math.isfinite(result.chi2)` が False の start を**basin 対象から除外**し
  `n_diverged` に加算。**例外化しない** (CLAUDE.md「失敗は chi2=inf 結果へ変換」)。
  **全滅** (残 0) → `basins=()`、`warnings` に警告文、`is_global_corroborated=False`、`promoted=()` (元仮説維持)。
- **昇格 (REQ-003 / TC-201-04)**: **複数 basin のときのみ** 各 basin 代表 phases で `Hypothesis` を生成し
  `promoted` に (evidence 昇順)。各 `Hypothesis.metrics.multistart = {"n":N,"n_basins":K,"n_diverged":D}`。
  **単一 basin では `promoted=()`** かつ `is_global_corroborated=True`。metrics 記録は単一 basin 側でも
  「元仮説へ付与」する経路が要る (TC-201-06 は n_basins=1 でも成立 → §3 の `RefinementMetrics.multistart`)。
- **evidence 算出**: basin 代表の `RefinementResult` → `RefinementMetrics` (chi2/n_params/n_obs) →
  `BICBackend.score` の `value`。`BasinInfo.evidence` に格納、basins は **evidence 昇順** (小さいほど良い)。
- **決定論 (NFR-102 / REQ-402)**: `random`/`np.random` 不使用。start 順・union-find (根 index 小)・
  代表選出 (chi2 同点は start index 小) ・basins ソート (evidence 同点は代表 start index 小) すべて安定順。
  **2 回 `run` でビット同一**。
- **非破壊 (P2 / REQ-404)**: 入力 `phases` を破壊しない。ledger は `append` のみ。`RefinementMetrics.multistart`
  は既定 None の非破壊フィールド (TASK-0025 で追加済) を使う。
- **ledger 記録 (NFR-105)**: `ledger` 提供時、各操作 (start refine 結果 / 発散除外 / basin 確定 / 昇格) を
  `append("multistart.xxx", {...})`。**`ledger.verify()` が常に True**。ledger=None なら記録スキップ。
- **コア依存 numpy のみ (REQ-403)**: 距離計算は numpy or math。追加依存禁止。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **basin クラスタ (`basin.py`) + `MultistartEngine` (`engine.py`)** に閉じる。
- **摂動列生成** (`generate_starts` / `PerturbationSpec` / `MultistartConfig`) は **TASK-0027 済**。再実装しない
  (import して使う)。
- **FR-313 判別** (`operando/discrimination.py` で multistart 必須適用) は **TASK-0032**。本タスクは
  汎用 `MultistartEngine` を提供するのみ (判別ロジックは持たない)。
- **Worker 並列化 (FR-234)** は M3 では逐次実行で可 (REQ-005)。純関数ループ = map 置換可能な構造にするが
  実際の並列化はしない。
- 吸収補正・operando・segmentation は別タスク。本タスクは触らない。

### 後続タスクへの影響
- **後続**: TASK-0032 (FR-313 判別が `MultistartEngine.run` を区間端点で必須適用、basin 情報を metrics 記録) /
  TASK-0033。**`BasinInfo` / `MultistartResult` フィールド名・`MultistartEngine` シグネチャ
  (`__init__` / `run` の keyword-only 引数) は interfaces.py L143-191 契約どおり固定**すること。
- `DiscriminationConfig.multistart: MultistartConfig` (interfaces.py L255) が本タスクの config を必須適用する。

- **参照元**: `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/spec/m3-operando/{requirements,acceptance-criteria}.md`,
  `docs/design/m3-operando/{interfaces.py,architecture.md}`, `CLAUDE.md` (不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m3-operando/{TASK-0028.md,overview.md}`
- 仕様/要件: `docs/spec/m3-operando/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md}`
- 依存実装 (利用): `src/tsumugin/multistart/perturb.py` (generate_starts/MultistartConfig — TASK-0027 済),
  `src/tsumugin/backends/base.py` (RefinementBackend/RefinementModel/RefinementResult/param_name),
  `src/tsumugin/evidence/{ic,base}.py` (BICBackend/EvidenceResult),
  `src/tsumugin/model/hypothesis.py` (Hypothesis/RefinementMetrics.multistart — TASK-0025),
  `src/tsumugin/store/ledger.py` (Ledger.append/verify)
- パターン範: `src/tsumugin/search/clustering.py` (`_UnionFind` / クラスタ集約 → 代表 → 昇順正規化)
- テストダブルの範: `tests/test_tree_search.py` (`FakeBackend` — chi2_by_refs を初期値依存へ拡張),
  `tests/test_clustering.py`, `tests/test_multistart_perturb.py`, `tests/conftest.py`, `pyproject.toml`
- 前タスクノートの範: `docs/implements/m3-operando/TASK-0027/note.md`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
