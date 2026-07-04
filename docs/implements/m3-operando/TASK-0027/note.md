# TASK-0027 TDD 開発コンテキストノート

**タスク**: multistart/perturb — 決定論摂動列 (FR-231 / 設計 D1)
**要件名**: m3-operando / **タスクID**: TASK-0027 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 2 / **信頼性**: 🔵 2 / 🟡 2 (FR-231 / 設計 D1 / REQ-001 / AC TC-201-01・07)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

マルチスタート大域最適確認 (FR-230) の**初期値摂動列生成器**を、**乱数を一切使わない index ベースの
決定論列**として新設 `multistart/perturb.py` に実装する:

1. **`PerturbationSpec` (frozen dataclass)** — 摂動幅の設定値のみ保持:
   - `lattice_frac: float = 0.02` (格子 ±2% の相対幅)
   - `scale_log_range: float = 0.5` (log10 スケールの片側幅)
   - `occupancy_delta: float = 0.1` (占有率 LHS 幅)
2. **`MultistartConfig` (frozen dataclass)** — マルチスタート全体設定 (本タスクで使うのは主に `n_starts`/`spec`):
   - `n_starts: int = 8` (FR-231 の 8-16)
   - `spec: PerturbationSpec = PerturbationSpec()`
   - `basin_rel_tol: float = 1e-2` (TASK-0028 の basin クラスタで使用、本タスクでは器のみ)
   - `ms_max_cycles: int = 15` (TASK-0028 の refine で使用、本タスクでは器のみ)
3. **`generate_starts(phases, *, config) -> tuple[tuple[PhaseInstance, ...], ...]`**:
   - start index `i` (0..N-1) ごとに摂動を適用した `phases` 列 (計 N 組) を返す。
   - **i=0 は無摂動 (基準解そのもの)**。**i≥1 は index から一意に決まる決定論値**:
     - **格子**: `lattice_frac` 幅の**等間隔グリッド**上の点 (相の a/b/c を index で決まる係数だけ相対スケール)。
     - **scale**: `scale_log_range` 幅の**対数一様グリッド** (log10 空間で等間隔、10^offset を乗算)。
     - **占有率**: **固定ラテン超方格 (LHS) テーブル**から index で引いた値 (occupancy_delta 幅、[0,1] クリップ)。
   - **多相 phases**: 各相すべてに摂動を適用 (相ごとに一意な決定論オフセット)。
   - 更新はすべて `PhaseInstance.with_updates()` / `LatticeParams` 再構築による**非破壊生成**。

**🚨 絶対制約 (完了条件と直結)**:
- **決定論・乱数不使用 (NFR-102 / REQ-402 / TC-201-01)**: `random`/`np.random` を import しない。
  摂動値は start index `i` と相 index `j`、パラメータ種別のみから純関数的に導出。
  **同一 `(phases, config)` で 2 回 `generate_starts` を呼ぶとビット同一** (格子値・scale・占有率すべて `==`)。
- **摂動範囲が spec どおり (TC-201-01)**: 格子は基準 ±`lattice_frac` の範囲内、scale は
  `10^(±scale_log_range)` の対数域内、占有率は `occupancy_delta` 幅の LHS 値かつ **[0,1] にクリップ**。
- **i=0 無摂動 (TC-201-07 / EDGE-101)**: `generate_starts(...)[0]` は入力 `phases` と同値 (格子/scale/占有率とも基準)。
  **N=1 縮退**: `config.n_starts=1` のとき戻り値は基準 1 組のみ (`len == 1`、摂動なし、basin=1 相当)。
- **多相対応**: `phases` が複数相でも各相へ摂動が適用される (どの相も i=0 で基準、i≥1 で摂動)。
- **非破壊性 (P2 / REQ-404)**: 入力 `phases` を変更しない。`with_updates` / frozen 再構築のみ。返り値は新インスタンス群。
- **コア依存 numpy のみ (REQ-403)**: 追加依存なし。格子/対数グリッド計算は numpy or 標準 math で可。
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0027.md`, `docs/design/m3-operando/interfaces.py` L124-169,
`docs/design/m3-operando/architecture.md` D1 (L58-60) / モジュール表 L34,
`docs/spec/m3-operando/requirements.md` REQ-001/402/403/404, EDGE-101,
`docs/spec/m3-operando/acceptance-criteria.md` TC-201-01 / TC-201-07

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは **numpy 依存** (対数グリッド・
  等間隔グリッドのベクトル生成)。GSAS-II には依存しない (@gsas マーカー不要、純粋なモデル変換)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (`PerturbationSpec` / `MultistartConfig`) +
  **純関数コア** (`generate_starts` は副作用なし・決定論)。摂動列は start index の関数で、乱数を持たない
  (NFR-102 の「乱数種固定でビット同一」を、そもそも乱数を使わない index 列で実現)。
- **モジュール配置**: `src/tsumugin/multistart/` **新設** (`__init__.py` + `perturb.py`)。
  本タスクは `perturb.py` のみ (`basin.py` / `engine.py` は TASK-0028)。
- **参照元**: `CLAUDE.md` (技術スタック節 / 不変条件), `pyproject.toml`,
  `docs/spec/m3-operando/note.md`, `docs/design/m3-operando/architecture.md` (ディレクトリ構造 L108-123)

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: クラス/型 PascalCase (`PerturbationSpec` / `MultistartConfig`)、関数/フィールド snake_case
  (`generate_starts` / `lattice_frac` / `scale_log_range` / `occupancy_delta` / `n_starts`)、
  ファイル snake_case (`perturb.py`)、定数 UPPER_SNAKE (固定 LHS テーブル等は `_LHS_TABLE` 相当)。
- **型注釈必須** (`any` 回避)。`tuple[PhaseInstance, ...]` / `tuple[tuple[PhaseInstance, ...], ...]` /
  `float` / `int` / `PerturbationSpec` / `MultistartConfig`。`from __future__ import annotations` を
  新規ファイル冒頭に置く。docstring 日本語可、FR/REQ/TC 番号 + 信頼性レベル 🔵🟡🔴 を付す慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **不変条件 (仕様由来・違反禁止)**:
  - **非破壊更新**: frozen + `with_updates()`。入力 `phases` を破壊しない (P2)。
  - **決定論 (NFR-102)**: 乱数不使用。摂動は index の純関数。2 回生成でビット同一。
- **キーワード専用引数**: interfaces.py L165-167 の `generate_starts(phases, *, config)` に従い、
  `config` は keyword-only (`*` 区切り) で受ける。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。**質問しない** (自律実行)。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `CLAUDE.md` (コーディング規約 / 不変条件), `docs/spec/m3-operando/note.md`,
  `docs/implements/m3-operando/TASK-0026/note.md` (前タスク運用の範)

---

## 3. 関連実装 (依存・参考パターン)

### 依存する既存モデル (そのまま利用、TASK-0025 までに実装済)

- `src/tsumugin/model/phase.py`:
  - `PhaseInstance(phase_ref, lattice, scale=1.0, wt_frac=None, occupancies={}, lifecycle=None)` (L48-62)。
    - `scale: float` — **scale 摂動の対象**。対数一様グリッドで `scale * 10^offset`。
    - `occupancies: Mapping[str, float]` — **占有率摂動の対象**。LHS 表の値で site ごとに摂動 + [0,1] クリップ。
    - `with_updates(**changes) -> PhaseInstance` (L60-62) — 非破壊更新の唯一手段 (`replace` ラッパ)。
  - `LatticeParams(a, b, c, alpha=90, beta=90, gamma=90, sigma={})` (L10-30)。
    - `a`/`b`/`c` — **格子摂動の対象** (相対スケール `a * (1 + delta)`)。角度 (alpha/beta/gamma) は本タスク非摂動 (格子長のみ)。
    - frozen なので摂動は `LatticeParams(a=..., b=..., c=..., alpha=..., ...)` の再構築 or `dataclasses.replace`。
    - `volume()` (L22-30) — 摂動後の体積検証にテストで使えるが実装は触らない。
- `src/tsumugin/model/__init__.py`: `PhaseInstance` / `LatticeParams` を re-export (L8, L23)。
  `from tsumugin.model import PhaseInstance, LatticeParams` で import 可能。

### 設計契約 (interfaces.py L124-169 準拠、そのまま実装可)

```python
# multistart/ (FR-230〜234) — 本タスクは PerturbationSpec / MultistartConfig / generate_starts のみ

@dataclass(frozen=True)
class PerturbationSpec:                  # 🔵 FR-231 (幅の既定は 🟡)
    lattice_frac: float = 0.02           # 格子 ±2%
    scale_log_range: float = 0.5         # log10 スケール幅
    occupancy_delta: float = 0.1         # LHS 幅

@dataclass(frozen=True)
class MultistartConfig:
    n_starts: int = 8                    # 🔵 FR-231 (8-16)
    spec: PerturbationSpec = PerturbationSpec()
    basin_rel_tol: float = 1e-2          # 🟡 D3 (本タスクでは器のみ、TASK-0028 で使用)
    ms_max_cycles: int = 15              # 🟡 D2 (本タスクでは器のみ、TASK-0028 で使用)

def generate_starts(
    phases: tuple[PhaseInstance, ...], *, config: MultistartConfig
) -> tuple[tuple[PhaseInstance, ...], ...]:
    """start index ごとの決定論摂動 phases 列 (i=0 は無摂動)。🔵 D1"""
```

### 参考パターン (既存コードから踏襲)

- **frozen dataclass + 既定値**: `PerturbationSpec` / `MultistartConfig` は `LatticeParams` / `AbsorptionConfig`
  (TASK-0026) と同型。**ネストした既定値** (`MultistartConfig.spec = PerturbationSpec()`) は
  `RefinementModel`/`AbsorptionConfig` の既定値付きフィールド方式に倣う。frozen なので既定インスタンスの
  共有は安全 (不変)。
- **非破壊摂動生成**: `PhaseInstance.with_updates(scale=..., lattice=..., occupancies=...)` で新インスタンス。
  `LatticeParams` は frozen のため `dataclasses.replace(lattice, a=..., b=..., c=...)` or 明示再構築。
  `src/tsumugin/model/phase.py` の `with_updates` (`replace` ラッパ) が範。
- **決定論 index 列の範**: 既存コードは「安定ソート・index 順」で決定論を担保 (architecture.md L129
  「摂動列・クラスタ順・境界候補順すべて index 安定ソート」)。摂動値は
  `i / (N-1)` 等の index 正規化 → グリッド点、で乱数を排除。
- **占有率 LHS 固定表**: ラテン超方格は本来乱数だが、本タスクでは **N×site の固定順列テーブル**を
  index で引く決定論版とする (D1「占有率は固定ラテン超方格テーブルで一意に決まる」)。
  N を跨いでも同じ規則で生成できる決定論的順列 (例: index の巡回シフト) を用いる 🟡。

### 後続タスクが利用する契約 (壊さない)

- **TASK-0028** (`multistart/basin.py` / `engine.py`): `generate_starts` の戻り値 (N 組の phases) を
  各 start として `backend.refine` に渡す。`MultistartConfig.basin_rel_tol` / `ms_max_cycles` は
  TASK-0028 で消費 (本タスクは器として正しい既定値で持つだけ)。
- `PerturbationSpec` フィールド名・`MultistartConfig` フィールド名・`generate_starts` シグネチャは
  interfaces.py D1 契約どおり固定すること。

- **参照元**: `src/tsumugin/model/phase.py`, `src/tsumugin/model/__init__.py`,
  `src/tsumugin/backends/simulated.py` (with_updates 利用例),
  `docs/design/m3-operando/interfaces.py` L124-169, `docs/implements/m3-operando/TASK-0026/note.md`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m3-operando/interfaces.py`
  - L126-133: `PerturbationSpec` (lattice_frac=0.02 / scale_log_range=0.5 / occupancy_delta=0.1)。
  - L135-141: `MultistartConfig` (n_starts=8 / spec / basin_rel_tol=1e-2 / ms_max_cycles=15)。
  - L165-169: `generate_starts(phases, *, config) -> tuple[tuple[PhaseInstance, ...], ...]`、i=0 無摂動、D1。
- **アーキテクチャ**: `docs/design/m3-operando/architecture.md`
  - **D1 (L58-60)**: 「マルチスタート摂動は決定論列」。乱数不使用。start index i (0..N-1) に対し
    格子 ±frac の**等間隔グリッド**・scale の**対数一様グリッド**・占有率は**固定ラテン超方格テーブル**で
    一意に決まる (NFR-102)。**i=0 は無摂動 (基準解)**。
  - モジュール表 L34: `multistart/perturb.py` — 決定論摂動列 (格子グリッド/scale 対数/占有率 LHS 固定表)、
    要件 REQ-001、信頼性 🔵 (列生成式 🟡)。
  - ディレクトリ構造 L108-123: `multistart/` 新規 (perturb / basin / engine)、テスト `test_multistart*.py`。
  - 非機能 L129: 「摂動列・クラスタ順・境界候補順すべて index 安定ソート」(決定論の実現方法)。
- **要件**: `docs/spec/m3-operando/requirements.md`
  - REQ-001 (L24-26): 初期値を系統摂動した N 本 (既定 8、8-16) の独立精密化。摂動は格子 ±設定幅・
    scale 対数一様・占有率ラテン超方格とし、**決定論的な固定列**で生成 (乱数種固定) 🔵 FR-231/NFR-102。
  - REQ-402 (L106-107): マルチスタート等の全出力は同一入力でビット同一 (摂動列は決定論生成) 🔵 NFR-102。
  - REQ-403 (L108-109): コア依存は numpy のみ 🔵。
  - REQ-404 (L110-111): データモデル拡張は後方互換の非破壊追加 🔵。
  - EDGE-101 (L128): N=1 のマルチスタート → 摂動なし 1 本 (基準解のみ、basin=1) 🟡。
- **受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` (TC-201 系 L12-20)
  - **TC-201-01** (L14): N=8 の摂動列が決定論 (2 回生成でビット同一)、格子±幅/scale 対数一様/占有率 LHS の範囲内 🔵。
  - **TC-201-07** (L20): N=1 縮退 (摂動なし 1 本) 🟡 EDGE-101。
  - (TC-201-02〜06 は basin/engine/metrics の観点で TASK-0028 が主対象。本タスクは摂動列生成に閉じる。)
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §6 FR-230/FR-231 (マルチスタート摂動) / §13 M3。
- **後続タスク利用先**: TASK-0028 (basin クラスタ + MultistartEngine が generate_starts を消費)、
  TASK-0032 (FR-313 判別でマルチスタート必須適用)。
- **参照元**: 上記各ファイル, `docs/tasks/m3-operando/{TASK-0027.md,overview.md}`

---

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov。設定 `pyproject.toml [tool.pytest.ini_options]`
  (`markers` に `gsas`)。
- **実行コマンド**: `uv run pytest tests/test_multistart_perturb.py` (本タスク単体) /
  `uv run pytest` (全体回帰) / `uv run pytest --cov=tsumugin`。**依存導入は `uv sync --extra gsas`**
  (プレーン `uv sync` は禁止)。本タスクのコアは GSAS-II 非依存 → `gsas` マーカー不要。
- **本タスクのテストファイル**: `tests/test_multistart_perturb.py` (**新規**)。
  実装ファイル `src/tsumugin/multistart/perturb.py` と 1:1 対応 (CLAUDE.md 規約)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl 対応 `test_*.py`。`tests/conftest.py` に共通
  フィクスチャ。**ベースライン 505 collected** (502 passed + @gsas 3 skip、2026-07-04 計測)。
  本タスクは `test_multistart_perturb.py` 分だけ collected 数が増える (既存テストは無改変)。
- **命名/記述パターン** (`tests/test_simulated_backend.py` / `tests/test_lifecycle.py` 準拠):
  - `PhaseInstance(phase_ref="A", lattice=LatticeParams(a=..,b=..,c=..), scale=1.0, occupancies={...})`
    を組むヘルパ (`_phase(...)`) をテスト内に用意。
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 近似は `pytest.approx(値, rel=/abs=)`、**決定論は `==` (格子/scale/占有率のビット同一)**。
  - docstring/コメントに 🔵/🟡 信頼性レベルと TC/REQ 番号を付す慣習。
- **本タスクで書くべき代表テスト観点** (詳細は tdd-testcases で洗い出し):
  - `generate_starts(phases, config=MultistartConfig(n_starts=8))` を 2 回呼びビット同一 (TC-201-01)。
  - 戻り値 `len == n_starts`、各要素 `len == len(phases)` (相数保存)。
  - `starts[0]` が入力 `phases` と同値 (i=0 無摂動 / TC-201-07)。
  - 格子: `starts[i][j].lattice.a` が基準 ±`lattice_frac` の範囲内、i によって異なる (グリッド)。
  - scale: `log10(starts[i][j].scale / base_scale)` が ±`scale_log_range` 内、対数等間隔。
  - 占有率: 各 site の値が `[0,1]` 内 (クリップ)、`occupancy_delta` 幅の摂動。
  - N=1 で戻り値 `len == 1` かつ基準のみ (TC-201-07 / EDGE-101)。
  - 多相 (2 相) phases で各相に摂動 (どの相も i=0 基準、i≥1 摂動)。
  - `PerturbationSpec` / `MultistartConfig` の既定値・明示値・frozen。
  - 入力 `phases` が呼び出し後も不変 (非破壊 / P2)。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で **505 → (505 + 新規件数) で無退行維持** (既存 502 passed +
  3 gsas skip はそのまま)。既存テストファイルは 1 行も変更しない。
- **参照元**: `pyproject.toml`, `tests/test_simulated_backend.py`, `tests/test_lifecycle.py`,
  `tests/conftest.py`, `docs/spec/m3-operando/acceptance-criteria.md` (TC-201-01/07)

---

## 6. 注意事項

### 技術的制約
- **決定論・乱数不使用 (NFR-102 / REQ-402 / TC-201-01)**: `random`/`np.random` を **import しない**。
  摂動値は start index `i`・相 index `j`・パラメータ種別のみから純関数導出。基準は `i / max(N-1, 1)` 等の
  index 正規化でグリッド点に写す。2 回生成でビット同一。
- **摂動幅の意味 (TC-201-01)**:
  - **格子**: 相対幅。`a_pert = a * (1 + delta)`、`delta ∈ [-lattice_frac, +lattice_frac]` の等間隔グリッド。
    b/c も同様。角度は非摂動 (本タスクは格子長のみ)。
  - **scale**: 対数一様。`scale_pert = scale * 10^(offset)`、`offset ∈ [-scale_log_range, +scale_log_range]`
    の対数空間等間隔グリッド。
  - **占有率**: `occ_pert = clip(occ + lhs_offset, 0.0, 1.0)`、`lhs_offset` は固定 LHS 表 (幅 occupancy_delta)。
    **[0,1] クリップ必須** (占有率は物理的に [0,1])。
- **i=0 無摂動 (TC-201-07 / EDGE-101)**: `delta=0` / `offset=0` / `lhs_offset=0` を i=0 に割り当て、
  基準 phases をそのまま (同値) 返す。**N=1 縮退**: `n_starts=1` のとき i=0 のみ = 基準 1 組。
  0 除算回避 (`N-1=0` を分母にしない) に注意。
- **非破壊性 (P2 / REQ-404)**: 入力 `phases` / `LatticeParams` / `occupancies` を変更しない。
  `with_updates` / frozen 再構築 / 新 dict で生成。返り値は独立した新インスタンス群。
- **多相の一意性**: 相 index `j` を摂動の決定論式に織り込み、相ごとに異なるが決定論的な摂動を与える
  (全相同一摂動でも決定論は満たすが、D1 の LHS 的意図は相ごとの独立摂動)。設計裁量 🟡、tdd-testcases で確定。
- **コア依存 numpy のみ (REQ-403)**: 対数グリッドは `np.logspace`/`np.linspace` or `math` で。追加依存禁止。
- **型注釈**: `tuple[PhaseInstance, ...]` / `tuple[tuple[PhaseInstance, ...], ...]` / `float` / `int`。
  新規 `multistart/perturb.py` 冒頭に `from __future__ import annotations`。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **決定論摂動列生成 (`PerturbationSpec` / `MultistartConfig` / `generate_starts`)** に閉じる。
- **basin クラスタリング** (正規化距離 + union-find)・**MultistartEngine.run** (N 本独立精密化 + 昇格仮説)・
  **`MultistartResult`/`BasinInfo`** は **TASK-0028** の担当 (本タスクでは実装しない)。
- **metrics.multistart への記録** (REQ-006 / TC-201-06) は TASK-0028/判別側。本タスクは phases 列を返すのみ。
- 角度 (alpha/beta/gamma) 摂動・wt_frac 摂動は非スコープ (格子長・scale・占有率のみ、D1)。

### 後続タスクへの影響
- **後続**: TASK-0028 (`multistart/basin.py` / `engine.py` が `generate_starts` を消費)、
  TASK-0032 (FR-313 判別で必須適用)。`PerturbationSpec`/`MultistartConfig` フィールド名・
  `generate_starts` シグネチャ (`phases, *, config`)・戻り値型は interfaces.py D1 契約どおり固定すること。

- **参照元**: `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/spec/m3-operando/{requirements,acceptance-criteria}.md`,
  `docs/design/m3-operando/{interfaces.py,architecture.md}`, `CLAUDE.md` (不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m3-operando/{TASK-0027.md,overview.md}`
- 仕様/要件: `docs/spec/m3-operando/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md}`
- 依存実装 (利用): `src/tsumugin/model/phase.py` (PhaseInstance/LatticeParams/with_updates),
  `src/tsumugin/model/__init__.py`, `src/tsumugin/model/hypothesis.py` (RefinementMetrics.multistart)
- with_updates 利用例: `src/tsumugin/backends/simulated.py`
- テスト参考: `tests/test_simulated_backend.py`, `tests/test_lifecycle.py`, `tests/conftest.py`, `pyproject.toml`
- 前タスクノートの範: `docs/implements/m3-operando/TASK-0026/note.md`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
