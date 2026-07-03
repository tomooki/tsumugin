# TASK-0026 TDD 開発コンテキストノート

**タスク**: backends 拡張 — global パラメータ文法 + 吸収補正 v1 (FR-317)
**要件名**: m3-operando / **タスクID**: TASK-0026 / **タイプ**: TDD / **推定 5h**
**フェーズ**: Phase 2 / **信頼性**: 🔵 6/6 (FR-317 / 設計 D8 / REQ-017〜020/103)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

M3 operando 解析の **実効 μt 吸収補正 v1** を、パラメータ文法拡張 + 新 `absorption/model.py` +
`SimulatedBackend` 前方モデル拡張として、既存 API を一切壊さずに追加する:

1. **`backends/base.py` 拡張 (非破壊)**:
   - `parse_param("global.mu_t") -> (-1, "mu_t")` を追加。頭が `"global"` のとき相インデックス `-1` を
     返す。既存 `"phase{i}.{suffix}"` の解釈は完全に不変 (既存テスト green)。不正名は従来どおり
     `ValueError`。`param_name` 側は本タスクでは触れなくてよい (global 名の生成が要れば別途)。
   - `RefinementResult` に **末尾フィールド** `globals: Mapping[str, float] = field(default_factory=dict)`
     を追加 (既定 空 dict、非破壊)。fitted μt 等の大域パラメータを `{"mu_t": 0.42}` 形式で記録。
   - `RefinementResult` に **末尾フィールド** `warnings: tuple[str, ...] = ()` を追加 (既定 空、非破壊)。
     経験推定モード明示・restraint 幅超過の相関疑いを文字列で載せる (D8/REQ-018/REQ-103 の警告の器)。
     ※ 既存コード (tree.py `SearchResult.warnings` / sequential engine 結果) と同じ house style の
       `warnings: tuple[str, ...]` フィールド方式を踏襲する (Python `warnings.warn` は使わない)。
2. **`absorption/model.py` 新設**:
   - `transmission_factor(two_theta_deg: np.ndarray, mu_t: float) -> np.ndarray`:
     平板透過の吸収因子 **A(θ; μt) = exp(−μt / cos θ)**。θ は 2θ(度)の半分をラジアン化。
     **μt=0 で全域 1** (EDGE-006 境界。0 乗算でなく exp(0)=1 で自然に 1)。
   - `AbsorptionConfig` (frozen dataclass): `mu_t_initial: float = 0.0` /
     `mu_t_calc: float | None = None` (restraint 中心) / `restraint_weight: float = 100.0` (w_r) /
     `empirical_mode: bool = False`。
   - `AbsorptionConfig.from_cell_config(config: CellConfig) -> AbsorptionConfig` (staticmethod):
     `config.mu_t_calc` を restraint 中心 (`mu_t_calc`) かつ `mu_t_initial` に採用、強 restraint
     (w_r=既定 100.0)、`empirical_mode=False`。`config.mu_t_calc is None` の場合は経験推定へフォールバック
     (= `empirical()` 相当) が妥当 (要件 tdd-requirements で確定)。
   - `AbsorptionConfig.empirical() -> AbsorptionConfig` (staticmethod): `mu_t_calc=None`・
     弱 restraint (w_r 小、interfaces 注記の既定 1.0)・`empirical_mode=True` (REQ-018)。
3. **`SimulatedBackend(absorption: AbsorptionConfig | None = None)`**:
   - `__init__` に `absorption` キーワード引数を **末尾追加** (既定 None = 従来挙動、非破壊)。
   - `simulate`: 生成強度 y に `transmission_factor(two_theta, mu_t)` を **乗算**。μt は精密化中は
     現在のフィット値、absorption=None または μt=0 のときは係数 1 (無補正 = 既存と一致)。
   - `_recognized`: `"global.mu_t"` を認識キーに追加 (absorption 設定時のみ)。
   - `refine`: `"global.mu_t"` ∈ free_params かつ absorption 設定時、μt を **フィットベクトルへ追加**。
     残差二乗和に **restraint ペナルティ w_r·(μt − μt_calc)²** を chi2 として加算 (soft bound)。
     収束後の μt を `RefinementResult.globals["mu_t"]` に記録。
   - **経験推定モード** (`empirical_mode=True` or CellConfig 未提供): 弱 restraint で μt を精密化し、
     `warnings` に経験推定モード明示 + 逆算 μt 提示メッセージを載せる (REQ-018)。
   - **restraint 幅超過警告**: fitted μt が restraint 中心から許容幅を超えて逸脱したら `warnings` に
     相関疑い警告 (REQ-103 / §14)。
4. **`GSASIIBackend`**: v1 は吸収を **scale への畳み込み近似**とする旨を **docstring に明記するのみ**
   (実装追加なし、@gsas テスト増やさない)。REQ-020 の GSAS-II 側 v1 近似の言明。

**🚨 絶対制約 (完了条件と直結)**:
- **非破壊追加のみ** — `RefinementResult` の新規 2 フィールドは末尾・既定値付き。`parse_param` の
  `global.` 分岐は既存 `phase{i}.` 経路に触れない。`SimulatedBackend.__init__` の `absorption` は
  末尾 keyword・既定 None。**既存テストを 1 行も改変しない**。
- **既存テスト無退行で green** — ベースライン **477 collected** (前タスク基準 474 green + @gsas 3 skip)。
  特に `tests/test_backend_interface.py` (parse_param/param_name/frozen) と
  `tests/test_simulated_backend.py` (simulate/refine/決定論) が無改変で通ること。
- **μt=0 境界 = 補正因子 1 で既存一致** (TC-207-05 / EDGE-006): `absorption=None` または μt=0 のとき
  `simulate` 出力は現行とビット一致。無補正回帰を壊さない。
- **真値回収** (TC-207-02): μt>0 で生成した合成データを μt=0 初期から精密化し、restraint 内で真 μt を回収。
- **restraint 機能** (TC-207-03): 中心から遠い解が w_r·(Δμt)² で抑制される。
- **経験推定モード** (TC-207-04): CellConfig 未提供 → 弱 restraint + 警告 + 逆算 μt。
- **restraint 幅超過警告** (TC-207-06 / REQ-103): 逸脱時に相関疑い警告。
- **決定論 (NFR-102)**: 乱数不使用。μt フィットは既存 LM ループの決定論的拡張。2 回実行でビット同一。
- **コア依存 numpy のみ (REQ-403)**: xraylib 非依存。MuCalculator は Protocol のみ (TASK-0025 実装済)。
- **git commit しない** (ユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0026.md`, `docs/design/m3-operando/interfaces.py` L88-118,
`docs/design/m3-operando/architecture.md` D8 (L93-101),
`docs/spec/m3-operando/requirements.md` REQ-016〜020/103/403/404,
`docs/spec/m3-operando/acceptance-criteria.md` TC-207-02〜07 / EDGE-006

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは **numpy 依存** (前方モデルの
  ベクトル乗算・LM 精密化)。GSAS-II には依存しない (@gsas マーカー不要)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト (`AbsorptionConfig`) +
  `typing.Protocol` 境界 (`RefinementBackend` は既存)。前方モデル = 決定論的関数 (乱数なし NFR-102)。
  精密化は既存 Levenberg–Marquardt ループ (`simulated.py` L153-235) の**フィット次元拡張**。
- **モジュール配置**: `src/tsumugin/absorption/` 新設 (`__init__.py` + `model.py`)。
  `src/tsumugin/backends/base.py` / `simulated.py` / `gsasii.py` を非破壊拡張。
- **参照元**: `CLAUDE.md` (技術スタック節 / 不変条件), `pyproject.toml`,
  `docs/spec/m3-operando/note.md`, `docs/design/m3-operando/architecture.md` (ディレクトリ構造 L108-123)

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: クラス/型 PascalCase (`AbsorptionConfig`)、関数/フィールド snake_case
  (`transmission_factor` / `mu_t_calc` / `restraint_weight`)、ファイル snake_case (`model.py`)、
  定数 UPPER_SNAKE。パラメータ名の正準文法は `"global.mu_t"` (既存 `"phase{i}.scale"` と同族)。
- **型注釈必須** (`any` 回避)。`np.ndarray` / `float` / `float | None` / `Mapping[str, float]` /
  `tuple[str, ...]` / `AbsorptionConfig | None` を正しく付す。`from __future__ import annotations` を
  新規ファイル冒頭に置く。docstring 日本語可、FR/REQ/TC 番号 + 信頼性レベル 🔵🟡🔴 を付す慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **不変条件 (仕様由来・違反禁止)**: 精密化失敗は例外でなく chi2=inf 結果へ (ガードレール処理)。
  chi2/rwp のセマンティクスはバックエンド間で統一。frozen + `with_updates()` 非破壊更新。
- **警告の載せ方**: 結果 dataclass の `warnings: tuple[str, ...]` フィールド方式 (house style)。
  `tree.py` `SearchResult.warnings` / `sequential/engine.py` 結果と同一パターン。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。**質問しない**。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `CLAUDE.md` (コーディング規約 / 不変条件), `docs/spec/m3-operando/note.md`,
  `docs/implements/m3-operando/TASK-0025/note.md` (前タスク運用の範)

---

## 3. 関連実装 (拡張・参考パターン)

### 拡張対象の既存実装 (現状のシグネチャ)

- `src/tsumugin/backends/base.py`:
  - `RefinementModel(phases, free_params: frozenset[str], two_theta, intensity, weights=None)` (L17-25)。
    `free_params` は `"phase{i}.{suffix}"` 形式。**吸収の解放は `"global.mu_t"` を free_params に含める**。
  - `RefinementResult(phases, chi2, rwp, n_obs, n_params, converged, n_cycles, free_params=frozenset())`
    (L28-39)。→ **末尾に** `globals: Mapping[str, float] = field(default_factory=dict)` と
    `warnings: tuple[str, ...] = ()` を追加 (`field` は既 import 済 L9)。
  - `param_name(phase_index, key) -> "phase{i}.{key}"` (L52-54)。
  - `parse_param(name) -> (int, str)` (L57-62): 現状 `head.startswith("phase")` 前提。→ **先頭に**
    `if head == "global" and tail: return -1, tail` 分岐を追加し、既存 phase 経路は不変で残す。
- `src/tsumugin/backends/simulated.py`:
  - `SimulatedBackend(*, peak_fwhm=0.2, wavelength=..., hkl_table=None)` (L42-51)。→ `absorption=None` を
    末尾 keyword 追加。`self._absorption` 保持。
  - `simulate(phases, two_theta) -> np.ndarray` (L84-101): ガウシアン重ね合わせ。→ 生成後に
    `y *= transmission_factor(two_theta, mu_t)`。μt はフィット中の現在値 (`simulate` に μt を渡すか、
    内部状態で渡す設計は tdd-requirements で確定。純関数性維持のため `simulate` に `mu_t` 引数を
    足す or private ヘルパ `_simulate_with_mu` を用意する案が有力)。
  - `_recognized(free_params) -> list[str]` (L105-111): 認識キー選別。→ `"global.mu_t"` を認識に追加。
  - `_get` / `_set` (L113-149): 相パラメータの読み書き。global.mu_t は相ではなく backend/absorption 状態の
    μt を読み書きするため、`_get`/`_set` の `idx == -1` 分岐 or μt を別ベクトル成分として refine ループで
    直接扱う設計 (後者が clip/Jacobian と整合しやすい)。tdd-requirements で確定。
  - `refine(model, *, max_cycles=20)` (L153-235): LM ループ。`names = self._recognized(...)`、
    `p = [self._get(...)]`、`residual` → `chi2`、`_jacobian`。→ μt をフィットベクトル (names / p) に含め、
    `chi2 = r@r + w_r·(μt − μt_calc)²` へ restraint 項を加算。結果 `globals={"mu_t": ...}` を設定。
- `src/tsumugin/backends/gsasii.py`:
  - `class GSASIIBackend` (L124-)。→ **docstring に** v1 吸収は scale 畳み込み近似である旨を明記
    (実装追加なし、REQ-020)。
- `src/tsumugin/backends/__init__.py`: 公開面。新規 `AbsorptionConfig` / `transmission_factor` を
  `absorption` から re-export するか否かは tdd-requirements で確定 (最小構成は `absorption` パッケージ直下)。

### 設計契約 (interfaces.py L88-118 準拠、そのまま実装可)

```python
# backends 拡張 (D8, 非破壊)
# parse_param("global.mu_t") -> (-1, "mu_t") を追加 (既存 "phase{i}.*" は不変)
# RefinementResult に追加: globals: Mapping[str, float] = {}  (fitted μt 等)

@dataclass(frozen=True)
class AbsorptionConfig:                 # absorption/model.py 🔵 FR-317/D8
    mu_t_initial: float = 0.0           # 初期実効 μt
    mu_t_calc: float | None = None      # restraint 中心 (CellConfig 由来 or None=経験推定)
    restraint_weight: float = 100.0     # w_r。経験推定モードでは弱 (既定 1.0)
    empirical_mode: bool = False        # CellConfig 未提供 (警告出力) REQ-018

    @staticmethod
    def from_cell_config(config: CellConfig) -> "AbsorptionConfig": ...
    @staticmethod
    def empirical() -> "AbsorptionConfig": ...   # 弱 restraint + empirical_mode

def transmission_factor(two_theta_deg: np.ndarray, mu_t: float) -> np.ndarray:
    """平板透過の吸収因子 A(θ; μt) = exp(-μt / cos θ)。μt=0 で 1。"""

# SimulatedBackend.__init__(..., absorption: AbsorptionConfig | None = None)
#   simulate: I × transmission_factor / refine: "global.mu_t" 認識 + restraint ペナルティ
```

### 参考パターン (既存コードから踏襲)

- **末尾フィールド追加の後方互換**: `RefinementResult.globals` / `.warnings` は既存 8 フィールドの後ろに
  既定値付きで追加。`RefinementResult(phases,chi2,rwp,n_obs,n_params,converged,n_cycles)` の**既存生成
  (test_backend_interface.py L38-40 等) が無改変で通る**。`PhaseInstance.lifecycle` / `RefinementModel`
  の非破壊拡張と同型。
- **正準パラメータ名の分岐追加**: `parse_param` は `head.partition(".")` 済。`"global"` は
  `"phase"` と排他的な head なので、先頭に `global` 分岐を足しても既存 phase 経路と非干渉
  (test_backend_interface.py `test_param_name_roundtrip` / `test_parse_param_multi_dot` green)。
- **警告フィールド方式**: `src/tsumugin/search/tree.py` L112/698/729 (`SearchResult.warnings=(...)`),
  `src/tsumugin/sequential/engine.py` L88/183 が `warnings: tuple[str, ...]` を結果に載せる範。
  テストは `assert "μt" in " ".join(result.warnings)` 等で検証 (Python `warnings.warn` は不使用)。
- **LM 精密化ループの次元拡張**: `simulated.py` refine は `names`/`p`/`residual`/`_jacobian` で汎用化
  済み。μt を names 末尾に 1 成分足せば Jacobian は数値差分で自動対応。restraint はスカラ項を chi2 と
  比較残差に足す (数値的には `residual` に `sqrt(w_r)·(μt−μt_calc)` を 1 行追加する拡張残差ベクトルが
  LM 整合的 — tdd-requirements/testcases で確定)。
- **frozen dataclass + staticmethod ファクトリ**: `AbsorptionConfig.from_cell_config`/`empirical` は
  `LatticeParams` 等の frozen 値 + ファクトリ関数と同型 (副作用なし・決定論)。

### 前タスク成果物 (依存・そのまま利用)

- `src/tsumugin/model/cell.py` (TASK-0025 完了): `CellConfig(geometry, layers=(), beam=None,
  mu_t_calc=None)` / `CellLayer` / `BeamConfig` / `MuCalculator` Protocol / `XraylibMuCalculator` スタブ。
  → `AbsorptionConfig.from_cell_config` は `CellConfig.mu_t_calc` を読むだけ (MuCalculator は呼ばない。
  M3 は Protocol のみ、REQ-019)。

- **参照元**: `src/tsumugin/backends/{base,simulated,gsasii,__init__}.py`,
  `src/tsumugin/model/cell.py`, `src/tsumugin/search/tree.py`, `src/tsumugin/sequential/engine.py`,
  `docs/design/m3-operando/interfaces.py` L88-118, `docs/implements/m3-operando/TASK-0025/note.md`

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m3-operando/interfaces.py`
  - L93-94: `parse_param("global.mu_t") -> (-1, "mu_t")` 追加 (既存 phase 不変)。
  - L95: `RefinementResult.globals: Mapping[str, float] = {}` 追加。
  - L97-109: `AbsorptionConfig` (mu_t_initial/mu_t_calc/restraint_weight/empirical_mode +
    from_cell_config/empirical)。
  - L112-114: `transmission_factor(two_theta_deg, mu_t) = exp(-μt/cosθ)`、μt=0 で 1。
  - L117-118: `SimulatedBackend(absorption=...)` — simulate 乗算 / refine で global.mu_t 認識 + restraint。
- **アーキテクチャ**: `docs/design/m3-operando/architecture.md`
  - **D8 (L93-101)**: 吸収補正の実装位置。パラメータ文法拡張 / 透過因子乗算 / restraint ペナルティ
    w_r·(μt−μt_calc)² / `RefinementResult.globals` 記録 / CellConfig 提供時 μt_calc はユーザー指定値
    (MuCalculator は Protocol のみ) / 未提供時 弱 restraint + warnings 明示 / GSASIIBackend は scale 畳み込み近似。
  - L43: モジュール表 — `absorption/model.py` (AbsorptionConfig/透過因子/restraint/MuCalculator Protocol)。
  - L108-123: ディレクトリ構造 (`absorption/` 新規、`backends/` 拡張、`test_absorption.py`)。
- **要件**: `docs/spec/m3-operando/requirements.md`
  - REQ-017 (L73-75): 実効 μt 1 パラメータをフィット変数、CellConfig 由来計算値を restraint (soft bound)。
  - REQ-018 (L76-77): CellConfig 未提供 → 経験的推定 (弱 restraint) + 明示警告 + 逆算 μt 提示。
  - REQ-019 (L78-80): 組成→μt は Protocol のみ (M3 未実装エラー)。restraint 中心はユーザー指定 μt_calc を受領。
  - REQ-020 (L81-82): 吸収因子を前方モデルに乗算、SimulatedBackend で検証。GSAS-II 側は scale 畳み込み v1 近似 🟡。
  - REQ-103 (L98-99): μt が restraint 幅超逸脱で相関疑い警告 (§14)。
  - REQ-403 (L108-109): コア依存 numpy のみ (xraylib は Protocol + 未実装)。
  - REQ-404 (L110-111): データモデル/バックエンド拡張は後方互換の非破壊追加。
- **受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` (TC-207 系 L62-70)
  - TC-207-02: μt>0 合成データを μt=0 初期から精密化し真値回収 (restraint 内)。
  - TC-207-03: restraint がペナルティとして機能 (遠い解を抑制)。
  - TC-207-04: CellConfig 未提供 → 弱 restraint + 警告 + 逆算 μt。
  - TC-207-05: μt=0 境界で補正因子 1・既存結果一致 (無退行 / EDGE-006)。
  - TC-207-06: μt restraint 幅超で逸脱 → 相関疑い警告 (REQ-103)。
  - (TC-207-01 CellConfig 生成/シリアライズ・TC-207-07 MuCalculator NotImplementedError は TASK-0025 で充足済。
    本タスクは 02〜06 が主対象。01/07 の回帰維持は確認する。)
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §7 FR-317 / §14 (相関リスク緩和)。
- **後続タスク利用先**: TASK-0028 (operando 判別/区間で吸収補正込み精密化)、TASK-0032 (M3 E2E)。
- **参照元**: 上記各ファイル, `docs/tasks/m3-operando/{TASK-0026.md,overview.md}`

---

## 5. テスト関連情報

- **フレームワーク**: pytest (>=8) + pytest-cov。設定 `pyproject.toml [tool.pytest.ini_options]`
  (`markers` に `gsas`)。
- **実行コマンド**: `uv run pytest tests/test_absorption.py` (本タスク単体) / `uv run pytest` (全体回帰) /
  `uv run pytest --cov=tsumugin`。**依存導入は `uv sync --extra gsas`** (プレーン `uv sync` は禁止)。
  本タスクのコアは GSAS-II 非依存 → `gsas` マーカー不要。
- **本タスクのテストファイル**: `tests/test_absorption.py` (**新規**)。
  `tests/test_backend_interface.py` (parse_param/RefinementResult 拡張の回帰) と
  `tests/test_simulated_backend.py` (μt=0 無退行) は **無改変**で維持 (パターン参照のみ)。
  parse_param の global 分岐・RefinementResult 新フィールドの新規正常系テストは
  `tests/test_absorption.py` (または test_backend_interface に追記でなく新規ファイル) 側に書く
  ことで既存ファイルを触らない。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl 対応 `test_*.py`。`tests/conftest.py` に共通
  フィクスチャ。ベースライン **477 collected** (474 green + @gsas 3 skip)。
- **命名/記述パターン** (`tests/test_simulated_backend.py` / `test_backend_interface.py` 準拠):
  - `_phase(a, scale, ref)` ヘルパで `PhaseInstance`、`_grid()` で `np.arange(15,80,0.02)`。
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 近似は `pytest.approx(値, rel=/abs=)`、決定論は `==` (chi2/フィット値のビット同一)。
  - docstring/コメントに 🔵/🟡 信頼性レベルと TC/REQ 番号を付す慣習。
- **本タスクで書くべき代表テスト観点** (詳細は tdd-testcases で洗い出し):
  - `transmission_factor(tt, 0.0)` が全域 1 (== 1.0)、μt>0 で `exp(-μt/cosθ)` と一致、単調減少。
  - `parse_param("global.mu_t") == (-1, "mu_t")`、既存 `phase0.scale` 経路が不変。
  - `RefinementResult(...)` 既定生成で `globals == {}` / `warnings == ()`、明示値で保持、frozen。
  - `AbsorptionConfig` 既定/明示生成・frozen、`from_cell_config(CellConfig(mu_t_calc=0.5))` /
    `empirical()` の各フィールド (w_r 強/弱・empirical_mode・mu_t_calc)。
  - `SimulatedBackend(absorption=None)` の simulate/refine が既存と一致 (無退行 / TC-207-05)。
  - μt>0 生成 → μt=0 初期・`free_params={"global.mu_t"}` で refine → `globals["mu_t"]` が真値回収 (TC-207-02)。
  - restraint 中心から遠い初期を w_r で抑制 (TC-207-03)。
  - 経験推定 (`empirical()`) で warnings に経験モード + 逆算 μt (TC-207-04)。
  - restraint 幅超逸脱で warnings に相関疑い (TC-207-06)。
  - 2 回 refine でビット同一 (NFR-102)。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で **477 collected を無退行維持** (474 passed + 3 gsas skip)。
  既存テストファイルは 1 行も変更しない。
- **参照元**: `pyproject.toml`, `tests/test_simulated_backend.py`, `tests/test_backend_interface.py`,
  `tests/conftest.py`, `docs/spec/m3-operando/acceptance-criteria.md` (TC-207-02〜06)

---

## 6. 注意事項

### 技術的制約
- **非破壊性 (P2 / REQ-404 / NFR-101)**: `RefinementResult` の新フィールドは**末尾・既定値付き**
  (`globals=field(default_factory=dict)` / `warnings=()`)。`parse_param` の `global` 分岐は
  既存 phase 経路を変えない。`SimulatedBackend.__init__` の `absorption` は末尾 keyword・既定 None。
  既存テストファイルは無改変。
- **μt=0 境界 (EDGE-006 / TC-207-05)**: `transmission_factor` は μt=0 で **exp(0)=1** を返し全域 1。
  `absorption=None` のとき simulate は乗算をスキップ (or 係数 1) して**現行とビット一致**。無補正回帰を死守。
- **restraint の数値実装**: chi2 に `w_r·(μt−μt_calc)²` を加算。LM 整合には拡張残差ベクトルへ
  `sqrt(w_r)·(μt−μt_calc)` を 1 行足す実装が勾配/Jacobian と自然に整合 (chi2 = ‖r‖²)。
  経験推定モードは w_r を小 (既定 1.0) にして μt を緩く動かす。
- **μt のフィット扱い**: μt は相 (`PhaseInstance`) に属さない大域量。`_get`/`_set` の `idx==-1` 分岐で
  backend/refine ローカルの μt 状態を読み書きするか、refine ループ内で μt をフィットベクトルの
  独立成分として直接保持するか (clip: μt>=0)。純関数性・決定論を壊さないこと。
- **決定論 (NFR-102)**: 乱数不使用。μt フィットは既存 LM の決定論拡張。2 回実行でビット同一。
  restraint 中心 μt_calc・w_r は AbsorptionConfig の固定値。
- **コア依存 numpy のみ (REQ-403)**: xraylib へ実依存しない。`from_cell_config` は `CellConfig.mu_t_calc`
  (float | None) を読むだけで MuCalculator/xraylib を呼ばない。
- **型注釈**: `np.ndarray` / `float | None` / `Mapping[str, float]` / `tuple[str, ...]` /
  `AbsorptionConfig | None`。新規 `absorption/model.py` 冒頭に `from __future__ import annotations`。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **透過平板の実効 μt 1 パラメータ吸収補正 v1**。中性子吸収 (M4)・フレーム依存 μ 平滑追跡
  (M-later)・角度依存の詳細吸収モデルは非スコープ。
- **MuCalculator/xraylib の算出は実装しない** (TASK-0025 の Protocol + NotImplementedError スタブのまま。
  restraint 中心はユーザー指定 `CellConfig.mu_t_calc` を受け取るだけ、REQ-019)。
- **GSASIIBackend は docstring のみ** (scale 畳み込み v1 近似の言明。実装/テスト追加なし、REQ-020)。
- multistart (TASK-0027) / echem (TASK-0029) / discrimination・segmentation との結線は非スコープ
  (本タスクは backends + absorption 層で閉じる)。後続 TASK-0028/0032 が利用。

### 後続タスクへの影響
- **後続**: TASK-0028 (operando 判別/区間精密化で吸収補正込み)、TASK-0032 (M3 E2E)。
  `AbsorptionConfig` フィールド名・`transmission_factor` シグネチャ・`parse_param("global.mu_t")` 規約・
  `RefinementResult.globals["mu_t"]` キーは interfaces.py D8 契約どおり固定すること。

- **参照元**: `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/spec/m3-operando/{requirements,acceptance-criteria}.md`,
  `docs/design/m3-operando/{interfaces.py,architecture.md}`, `CLAUDE.md` (不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m3-operando/{TASK-0026.md,overview.md}`
- 仕様/要件: `docs/spec/m3-operando/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md}`
- 既存実装 (拡張対象): `src/tsumugin/backends/{base,simulated,gsasii,__init__}.py`
- 前タスク成果 (依存): `src/tsumugin/model/cell.py` (CellConfig/MuCalculator, TASK-0025)
- 警告フィールド方式の範: `src/tsumugin/search/tree.py`, `src/tsumugin/sequential/engine.py`
- テスト参考: `tests/test_simulated_backend.py`, `tests/test_backend_interface.py`, `tests/conftest.py`, `pyproject.toml`
- 前タスクノートの範: `docs/implements/m3-operando/TASK-0025/note.md`
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
