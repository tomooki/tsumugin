# TASK-0025 model 拡張 TDD要件定義書

**機能名**: model 拡張 (CellConfig / CellLayer / BeamConfig / channel kind / metrics.multistart / MuCalculator)
**タスクID**: TASK-0025
**要件名**: m3-operando
**タスクタイプ**: TDD / **推定工数**: 3h / **フェーズ**: Phase 1 - 技術負債+モデル
**作成日**: 2026-07-04
**出力ファイル**: `docs/implements/m3-operando/TASK-0025/model-cell-extension-requirements.md`

**【信頼性レベル凡例】**:
- 🔵 **青信号**: EARS要件定義書・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: EARS要件定義書・設計文書から妥当な推測
- 🔴 **赤信号**: EARS要件定義書・設計文書にない推測

---

## 1. 機能の概要（EARS要件定義書・設計文書ベース）

- 🔵 **何をする機能か**: M3 operando (電池その場計測) 解析基盤で用いる 4 つのデータモデル拡張を、既存 API を一切壊さずに追加する。具体的には (1) セル構成値オブジェクト群 `CellLayer` / `BeamConfig` / `CellConfig` を `model/cell.py` に新設、(2) `model/channel.py` の `ChannelKind` Literal に electrochemistry 用の 4 種 (`voltage` / `current` / `capacity` / `composition`) を末尾追加、(3) `model/hypothesis.py` の `RefinementMetrics` に `multistart` フィールドを末尾・既定 None で追加、(4) 組成→μt 計算の `MuCalculator` Protocol と未実装スタブ `XraylibMuCalculator` を新設、である。
- 🔵 **どのような問題を解決するか**: operando 解析では「セルの層構成・ビーム条件 (吸収補正 v1 の入力)」「フレームに同期する電気化学量 (電圧/電流/容量/組成 x)」「マルチスタート精密化の多峰性メタ情報」を表現する器が現行モデルに存在しない。後続の吸収補正 (TASK-0026)・マルチスタートエンジン (TASK-0027)・echem 読込 (TASK-0029) が依存する土台を、非破壊で用意する。
- 🔵 **想定されるユーザー**: 直接のユーザーは後続タスク (TASK-0026 / 0027 / 0029) の実装コードおよび operando 電池解析を実行する研究者。本タスク自体は内部データモデル層であり外部 UI を持たない。
- 🔵 **システム内での位置づけ**: `src/tsumugin/model/` 配下の frozen dataclass 値オブジェクト層 + `typing.Protocol` 境界。M0〜M2 で確立した「不変値オブジェクト + `dataclasses.replace()` 非破壊更新」パターン (P2) と「Protocol による交換境界」パターンに完全準拠する純データ拡張であり、numpy・GSAS-II・xraylib には依存しない (REQ-403 コア依存 numpy のみ維持)。
- **参照したEARS要件**: REQ-006 (metrics.multistart)、REQ-007 (echem kind)、REQ-016 (CellConfig)、REQ-019 (MuCalculator Protocol)、REQ-404 (非破壊追加)
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L40-87 (CellLayer / BeamConfig / CellConfig / MuCalculator / XraylibMuCalculator 定義、ExternalChannel.kind / RefinementMetrics.multistart 追記メモ)、`docs/design/m3-operando/architecture.md`

---

## 2. 入力・出力の仕様（EARS機能要件・型定義ベース）

### 2.1 CellLayer（新設 / `src/tsumugin/model/cell.py`）🔵

- 🔵 **入力パラメータ (フィールド)**:
  - `role: Literal["window", "electrode", "electrolyte", "separator", "collector"]` — 位置必須。層の役割。
  - `material: str` — 位置必須。組成式 or 物質名。
  - `thickness_mm: float` — 位置必須。層厚 (mm)。
  - `density: float | None = None` — 密度 (g/cm3)。既定 None (🟡 interfaces.py で 🟡 付与)。
- 🔵 **出力/振る舞い**: `@dataclass(frozen=True)`。生成・等価比較 (`==`) 可能。フィールド再代入は `dataclasses.FrozenInstanceError`。
- 🔵 **例**: `CellLayer(role="window", material="Be", thickness_mm=0.5)` → `density is None`。

### 2.2 BeamConfig（新設 / `src/tsumugin/model/cell.py`）🔵

- 🔵 **入力パラメータ (フィールド、全て既定値付き)**:
  - `wavelength: float | None = None` — 波長 (Å)。
  - `energy_kev: float | None = None` — エネルギー (keV)。
  - `size_mm: tuple[float, float] | None = None` — ビームサイズ (mm)。
- 🔵 **出力/振る舞い**: `@dataclass(frozen=True)`。全フィールド既定値付きのため `BeamConfig()` で生成可能。生成・等価比較可能。再代入は `FrozenInstanceError`。
- 🟡 **補足**: energy か wavelength の一方必須という制約は interfaces.py で 🟡 とされており、本タスクでは**バリデーションを課さない** (器のみ)。
- 🔵 **例**: `BeamConfig(wavelength=0.7)` / `BeamConfig(energy_kev=20.0, size_mm=(0.5, 0.5))`。

### 2.3 CellConfig（新設 / `src/tsumugin/model/cell.py`）🔵

- 🔵 **入力パラメータ (フィールド)**:
  - `geometry: Literal["transmission", "capillary"]` — 位置必須。セル形状。層状セルは透過法のみ (v0.3 確定 / FR-317)。
  - `layers: tuple[CellLayer, ...] = ()` — セル層構成。既定は空 tuple。
  - `beam: BeamConfig | None = None` — ビーム条件。既定 None。
  - `mu_t_calc: float | None = None` — 組成計算済み μt (MuCalculator or 手入力)。既定 None (🟡 D8)。
- 🔵 **出力/振る舞い**: `@dataclass(frozen=True)`。生成・等価比較可能。再代入は `FrozenInstanceError`。tuple/None フィールドのみのため `dataclasses.asdict()` で JSON ネイティブ型のネスト dict へ再帰展開でき round-trip 可能。
- 🔵 **例**: `CellConfig(geometry="transmission", layers=(CellLayer("window","Be",0.5),), beam=BeamConfig(wavelength=0.7))`。

### 2.4 ChannelKind 拡張（拡張 / `src/tsumugin/model/channel.py`）🔵

- 🔵 **現行**: `ChannelKind = Literal["temperature", "time", "pressure", "custom"]`
- 🔵 **拡張**: Literal の**末尾に** `"voltage"`, `"current"`, `"capacity"`, `"composition"` の 4 値を追加。既存 4 値は不変。
- 🔵 **入出力関係**: `ExternalChannel` 本体・`value_for` シグネチャは**無改変**。新 kind を渡した `ExternalChannel(kind="voltage", sync_map={...})` が生成でき、`value_for` は従来どおり存在フレーム→値 / 欠損→None を返す。
- 🔵 **後方互換**: Literal への末尾追加は既存値 (`"temperature"` 等) の型・意味を狭めないため、既存の生成・型注釈・比較を壊さない。
- 🟡 **補足**: `ExternalChannel` の echem 同期 (CSV マッパ経由の生成) 実体は TASK-0029 スコープ。本タスクは kind の値追加のみ (REQ-007 の器)。

### 2.5 RefinementMetrics.multistart（拡張 / `src/tsumugin/model/hypothesis.py`）🔵

- 🔵 **追加フィールド**: 既存フィールド末尾 (`evidence` の後ろ) に `multistart: Mapping[str, int] | None = None` を追加。
- 🔵 **現行シグネチャ**: `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence=field(default_factory=dict))`
- 🔵 **入出力関係**: 既定 None のため既存生成 `RefinementMetrics(rwp=..., gof=..., chi2=..., n_obs=..., n_params=...)` が後方互換で動作。frozen 維持。
- 🔵 **例**: `RefinementMetrics(1.0, 1.0, 1.0, 100, 5, multistart={"n": 8, "n_basins": 1, "n_diverged": 0})` → multistart メタ情報を保持。
- 🔵 **意味**: マルチスタート実行結果のメタ (`n`=start 本数、`n_basins`=収束 basin 数、`n_diverged`=発散除外数) を仮説へ記録 (REQ-006 / TC-201-06)。値の書込は TASK-0027 スコープ。

### 2.6 MuCalculator Protocol + XraylibMuCalculator スタブ（新設 / `src/tsumugin/model/cell.py`）🔵

- 🔵 **`MuCalculator(Protocol)`**: `mu_t(self, config: CellConfig) -> float` を定義する構造的型境界。組成→μt のエネルギー依存計算 (xraylib 等) の交換境界。
- 🔵 **`XraylibMuCalculator`**: `MuCalculator` を満たす実装予定スタブ。`mu_t` を呼ぶと `raise NotImplementedError`。M3 では Protocol のみ提供し xraylib への実依存を持たない (REQ-019 / REQ-403)。
- 🔵 **例**: `XraylibMuCalculator().mu_t(CellConfig(geometry="transmission"))` → `NotImplementedError` を送出 (TC-207-07)。

### 2.7 re-export（拡張 / `src/tsumugin/model/__init__.py`）🔵

- 🔵 `CellLayer`, `BeamConfig`, `CellConfig`, `MuCalculator`, `XraylibMuCalculator` を import し `__all__` に追加。`from tsumugin.model import CellConfig, CellLayer, BeamConfig, MuCalculator, XraylibMuCalculator` が解決可能となる。
- 🟡 top-level `src/tsumugin/__init__.py` への昇格は本タスクの必須スコープ外 (最小構成では model/__init__.py の re-export のみ)。昇格する場合は `__all__` の昇順必須制約を維持する必要がある。

- **参照したEARS要件**: REQ-006、REQ-007、REQ-016、REQ-019、REQ-404
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L40-87、既存実装 `src/tsumugin/model/{channel,hypothesis,__init__}.py`

---

## 3. 制約条件（EARS非機能要件・アーキテクチャ設計ベース）

- 🔵 **後方互換 / 非破壊性 (REQ-404 / NFR-101 / P2)**: 追加は必ず既定値付きフィールドを既存フィールドの**末尾**に置く。`ChannelKind` は Literal の**末尾に値追加** (既存値の意味・型を狭めない)。既存フィールドの順序・型・既定を一切変えない。既存の位置引数生成・比較・生成を壊さない。
- 🔵 **既存テスト無改変 green (完了ゲート)**: 既存テストが**無改変**で green を維持する。既存テストファイル (`tests/test_model.py` / `tests/test_model_m2.py` 等) は 1 行も変更しない。
- 🔵 **frozen dataclass 制約**: `CellLayer` / `BeamConfig` / `CellConfig` はすべて `@dataclass(frozen=True)`。生成・等価比較可能。再代入不可 (`FrozenInstanceError`)。
- 🟡 **ハッシュ制約**: `RefinementMetrics.multistart` は `Mapping` (dict) のため frozen でも `__hash__` は非ハッシュ化型で失敗し得る。テストは等価比較 (`==`) と生成に留め、set/dict キー化はしない (既存 `evidence` / `LatticeParams.sigma` と同扱い)。`CellConfig.layers` (tuple) はハッシュ可。
- 🔵 **未実装エラー制約 (REQ-019)**: `XraylibMuCalculator.mu_t` は必ず `NotImplementedError` を送出する。M3 では算出ロジックを実装しない。
- 🔵 **シリアライズ制約 (TC-207-01)**: `CellConfig` は `dataclasses.asdict()` で JSON ネイティブ型のネスト dict へ変換可能 (round-trip 可)。専用の `cell_to_dict`/`cell_from_dict` は**本タスク非スコープ** (永続化統合は後続)。
- 🔵 **コア依存 (REQ-403)**: xraylib / .mpr パーサへの実依存を持たない (Protocol + 未実装エラー)。コア依存は numpy のみ維持。本タスクは numpy にも依存しない純データ層。
- 🔵 **決定論 (NFR-102 / REQ-402)**: 乱数不使用。純データ構造のため自然に満たす。
- 🔵 **型注釈必須**: `Literal` / `Mapping[str, int]` / `tuple[CellLayer, ...]` / `tuple[float, float] | None` / `float | None` を正しく付す。`any` 回避。新規 `cell.py` 冒頭に `from __future__ import annotations` を置く (前方参照 + Protocol)。
- 🔵 **命名規則**: クラス/型は PascalCase、フィールド/関数は snake_case、ファイルは snake_case (`cell.py`)。
- 🔵 **Lint/フォーマット**: `uvx ruff check src tests` (line-length 100, target py312) 準拠。
- 🔵 **アーキテクチャ制約**: `src/tsumugin/model/` 配下の純データモデル層 + Protocol 境界。可変デフォルトは `field(default_factory=...)`、tuple 既定は `()` で回避。
- 🔴 **git commit しない** (ユーザー判断。本セッション制約)。**質問しない** (自律実行)。

- **参照したEARS要件**: REQ-404、REQ-403、REQ-402、REQ-019、NFR-101、NFR-102
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py`、`docs/spec/m3-operando/note.md`、`CLAUDE.md` (不変条件)

---

## 4. 想定される使用例（EARS Edgeケース・データフローベース）

### 4.1 基本的な使用パターン 🔵

- **セル構成**: `CellConfig(geometry="transmission", layers=(CellLayer("window","Be",0.5), CellLayer("electrode","LiFePO4",0.1)), beam=BeamConfig(energy_kev=20.0), mu_t_calc=1.2)` — 吸収補正 v1 (TASK-0026) が CellConfig 由来の μt を restraint 中心として受け取る入力。
- **電気化学同期**: `ExternalChannel(kind="voltage", sync_map={i: V_i for ...})` → 各フレームで `channel.value_for(i)` により電圧をトラジェクトリへ反映 (REQ-007)。kind は `current`/`capacity`/`composition` も同様。
- **マルチスタート記録**: `RefinementMetrics(..., multistart={"n": 8, "n_basins": 2, "n_diverged": 1})` — マルチスタートエンジン (TASK-0027) が多峰性メタを仮説へ記録 (REQ-006 / TC-201-06)。
- **μt 計算境界**: `calc: MuCalculator = XraylibMuCalculator()` として交換境界を確立 (実体は M3 では未実装)。

### 4.2 データフロー 🔵

- 吸収補正: ユーザーが `CellConfig` を提供 → `AbsorptionConfig.from_cell_config(config)` (TASK-0026) が `mu_t_calc` を restraint 中心へ → SimulatedBackend が透過吸収因子を前方モデルへ乗算。
- echem: CSV マッパ (TASK-0029) が V/I/Q 列を読み → `ExternalChannel(kind="voltage"/"current"/...)` を生成 → フレームへ同期。
- マルチスタート: MultistartEngine (TASK-0027) が N 本精密化 → basin クラスタ → `{"n", "n_basins", "n_diverged"}` を `RefinementMetrics.multistart` へ書込。

### 4.3 エッジケース 🔵🟡

- 🔵 **既定値縮退**: `BeamConfig()` (全 None)、`CellConfig(geometry="transmission")` (layers=()/beam=None/mu_t_calc=None)、`CellLayer(..., density=None)`、`RefinementMetrics(...)` (multistart=None) がすべて既定として成立し、既存経路に影響しない。
- 🔵 **後方互換 smoke**: 既存の `ExternalChannel(kind="temperature", sync_map={...})` / `RefinementMetrics(rwp=..., gof=..., chi2=..., n_obs=..., n_params=...)` が従来どおり構築でき比較できる。
- 🟡 **空 layers のシリアライズ**: `dataclasses.asdict(CellConfig(geometry="capillary"))` が `layers=[]`、`beam=None`、`mu_t_calc=None` を持つ dict を返す (毛細管セルは層なしの代表)。

### 4.4 エラーケース 🔵

- 🔵 **frozen 再代入**: `CellLayer` / `BeamConfig` / `CellConfig` のフィールドへ再代入 → `dataclasses.FrozenInstanceError`。
- 🔵 **未実装 μt 計算**: `XraylibMuCalculator().mu_t(config)` → `NotImplementedError` (TC-207-07 / REQ-019)。
- 🟡 **注意 (非スコープのエラー)**: `BeamConfig` の「energy か wavelength の一方必須」・`CellConfig.mu_t_calc > 0` 等のバリデーションは本タスクでは実装しない (器のみ)。検証・利用は後続スコープ (TASK-0026)。

- **参照したEARS要件**: REQ-006、REQ-007、REQ-016、REQ-019、REQ-404、EDGE-006 (μt=0 境界 — 本タスクは器のみ、補正は TASK-0026)
- **参照した設計文書**: `docs/design/m3-operando/dataflow.md`、`docs/design/m3-operando/interfaces.py` (AbsorptionConfig / MultistartEngine / EchemData)

---

## 5. EARS要件・設計文書との対応関係

- **参照したユーザストーリー**: m3-operando 電池 operando モード (吸収補正・echem 同期・マルチスタート判別) — `docs/spec/m3-operando/user-stories.md`
- **参照した機能要件**:
  - REQ-006 (multistart 結果を `RefinementMetrics.multistart {n, n_basins}` として仮説へ記録。非破壊フィールド追加)
  - REQ-007 (電気化学 CSV マッパで V/I/Q を `ExternalChannel` kind=echem 拡張としてフレーム同期)
  - REQ-016 (`CellConfig` データモデル: geometry / layers / beam。層状セルは透過法のみ)
  - REQ-019 (組成→μt 計算は Protocol のみ定義、M3 では未実装エラー)
  - REQ-404 (CellConfig 新設 / ExternalChannel の echem 対応 / RefinementMetrics.multistart は既存 API 後方互換の非破壊追加)
- **参照した非機能要件**: NFR-101 (追記/非破壊 P2)、NFR-102 (決定論・ビット同一)、REQ-402 (ビット同一)、REQ-403 (コア依存 numpy のみ)
- **参照したEdgeケース**: EDGE-006 (μt=0 境界での無退行 — 本タスクは CellConfig の器のみ、補正実体は TASK-0026)
- **参照した受け入れ基準** (`docs/spec/m3-operando/acceptance-criteria.md`):
  - TC-201-06 (metrics.multistart {n, n_basins} が仮説に記録される)
  - TC-207-01 (CellConfig (transmission/layers/beam) が生成・シリアライズできる)
  - TC-207-07 (MuCalculator Protocol 未実装が NotImplementedError)
- **参照した設計文書**:
  - **アーキテクチャ**: `docs/design/m3-operando/architecture.md` (model 拡張層の位置づけ)
  - **データフロー**: `docs/design/m3-operando/dataflow.md`
  - **型定義**: `docs/design/m3-operando/interfaces.py` L40-87 (CellLayer / BeamConfig / CellConfig / MuCalculator / XraylibMuCalculator / kind・multistart 追記メモ)
  - **既存実装**: `src/tsumugin/model/channel.py`、`src/tsumugin/model/hypothesis.py`、`src/tsumugin/model/__init__.py`
  - **タスク定義**: `docs/tasks/m3-operando/TASK-0025.md`
  - **コンテキストノート**: `docs/implements/m3-operando/TASK-0025/note.md`
  - **非破壊拡張の範**: `docs/implements/m2-sequential/TASK-0011/` (PhaseLifecycle/ExternalChannel/frame_range の非破壊追加)

---

## 完了条件（タスク定義より）

- [ ] CellConfig/CellLayer/BeamConfig が frozen dataclass で生成・シリアライズ可能 🔵 *TC-207-01*
- [ ] channel kind 拡張が後方互換 (既存 temperature 等のテスト無改変) 🔵
- [ ] metrics.multistart 既定 None・非破壊 🔵 *REQ-006*
- [ ] XraylibMuCalculator が NotImplementedError 🔵 *TC-207-07*

## 信頼性レベルサマリー

- 🔵 青信号: 大多数 (機能概要・入出力・主要制約・完了条件は interfaces.py / requirements.md / 既存実装に直接依拠)
- 🟡 黄信号: 少数 (density フィールド、BeamConfig の energy/wavelength 一方必須制約の非実装、mu_t_calc の 🟡 由来、top-level 昇格の扱い、空 layers シリアライズ詳細)
- 🔴 赤信号: git commit しない / 質問しない旨のセッション制約のみ (仕様外の運用指示)
- **品質判定**: 高品質 — 要件の曖昧さなし / 入出力定義完全 / 制約条件明確 / 実装可能性確実
