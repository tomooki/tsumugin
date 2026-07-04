# TASK-0025 TDD 開発コンテキストノート

**タスク**: model 拡張 (CellConfig / CellLayer / BeamConfig / channel kind 拡張 / metrics.multistart / MuCalculator)
**要件名**: m3-operando / **タスクID**: TASK-0025 / **タイプ**: TDD / **推定 3h**
**フェーズ**: Phase 1 (技術負債+モデル) / **信頼性**: 🔵 4/4 (§4 CellConfig / REQ-006/007/016/404)
**作成日時**: 2026-07-04 / **ブランチ**: milestone/m3-operando

> 本ノートのすべてのパスはプロジェクトルートからの相対パス。

---

## 0. タスク要旨 (最優先で守る不変条件)

M3 operando 解析基盤の 4 つのデータモデル拡張を、既存 API を一切壊さずに追加する:

1. **`model/cell.py` 新設** — `CellLayer` (role/material/thickness_mm/density) / `BeamConfig`
   (wavelength/energy_kev/size_mm) / `CellConfig` (geometry: transmission|capillary、layers/beam/mu_t_calc)
   の frozen dataclass 3 種。すべて生成・等価比較・`dataclasses.asdict` 直列化が可能。
2. **`model/channel.py` の `ChannelKind` Literal 拡張** — `"voltage" | "current" | "capacity" | "composition"`
   の 4 種を **末尾に追加** (後方互換)。既存 `temperature/time/pressure/custom` は不変。
3. **`model/hypothesis.py` の `RefinementMetrics.multistart`** — `Mapping[str, int] | None = None` を
   **末尾・既定 None** で追加 (非破壊)。例: `{"n": 8, "n_basins": 1, "n_diverged": 0}`。
4. **`MuCalculator` Protocol + `XraylibMuCalculator` スタブ** — `model/cell.py` に定義。
   `mu_t(config: CellConfig) -> float`。スタブは呼ぶと `NotImplementedError` (M3 は Protocol のみ)。
5. **`model/__init__.py` re-export** — 新規公開シンボルを import + `__all__` に追加。

**🚨 絶対制約 (完了条件と直結)**:
- **全フィールド既定値付きの非破壊追加** — 既存モデルの位置引数・比較・生成を一切壊さない (REQ-404)。
- **既存全テストが無改変で green** — 既存テストファイルは 1 行も変更しない。`ChannelKind` 拡張は
  temperature 等の既存テストを壊さない (Literal への末尾追加は既存値の型を狭めない)。
- **CellConfig/CellLayer/BeamConfig が frozen で生成・比較・シリアライズ可能** (TC-207-01)。
  「シリアライズ」= `dataclasses.asdict(cell_config)` が JSON ネイティブ型のみのネスト dict を返す
  (専用 to_dict/from_dict の新設は本タスク非スコープ)。
- **metrics.multistart 既定 None・非破壊** (REQ-006)。既存 `RefinementMetrics(rwp,gof,chi2,n_obs,n_params)`
  生成が後方互換で動く。
- **XraylibMuCalculator が NotImplementedError** (TC-207-07 / REQ-019)。
- **決定論 (NFR-102)** — 純データ構造のため自然に満たす。乱数・IO なし。
- **git commit しない** (本セッションはユーザー判断)。**質問しない** (自律実行)。

**参照元**: `docs/tasks/m3-operando/TASK-0025.md`, `docs/design/m3-operando/interfaces.py` L40-76,
`docs/spec/m3-operando/requirements.md` REQ-006/007/016/017/018/019/404,
`docs/spec/m3-operando/acceptance-criteria.md` TC-201-06 / TC-207-01/07

---

## 1. 技術スタック

- **言語**: Python >= 3.12 (uv 管理, src layout + hatchling)。本タスクは **純データモデル拡張のみ**で
  numpy にも GSAS-II にも依存しない (標準ライブラリ `dataclasses` / `typing` のみ)。
- **アーキテクチャパターン**: frozen dataclass の不変値オブジェクト + `dataclasses.replace()` /
  `with_updates()` 非破壊更新 (P2)。境界は `typing.Protocol` (`MuCalculator`)。
  `MuCalculator` は M0/M1/M2 の Protocol 境界パターン (`RefinementBackend` / `EchemLoader` 等) に準拠。
- **モジュール配置**: `src/tsumugin/model/` 配下 (`cell.py` 新設、`channel.py` / `hypothesis.py` /
  `__init__.py` を非破壊拡張)。
- **参照元**: `docs/spec/m3-operando/note.md` (技術スタック節), `pyproject.toml`, `CLAUDE.md`

---

## 2. 開発ルール

- **TDD 厳守**: tdd-red → tdd-green → tdd-refactor → tdd-verify-complete。テストなし実装コミット禁止。
- **命名規則**: クラス/型 PascalCase、フィールド/関数 snake_case、ファイル snake_case (`cell.py`)、
  定数 UPPER_SNAKE。
- **型注釈必須** (`any` 回避)。`Literal` / `Mapping` / `tuple[float, float] | None` / `float | None` を正しく付す。
  docstring 日本語可、FR/NFR/REQ 番号を紐づけ、信頼性レベル 🔵🟡🔴 を付す慣習。
- **フォーマット/Lint**: `uvx ruff check src tests` clean (line-length 100, target py312)。
- **データモデリング**: frozen dataclass 基本。`Mapping` フィールドは `field(default_factory=dict)` で既定
  (可変デフォルト共有回避)。tuple フィールド (`layers` / `size_mm`) は既定 `()` / `None`。
- **git commit はユーザー判断** (本セッションでは commit 禁止)。**質問しない**。
- 追加ルールファイルは**不在**: `AGENTS.md` なし / `docs/rule/`・`docs/rule/tdd/` なし。規約は `CLAUDE.md` に集約。
- **参照元**: `CLAUDE.md`, `docs/spec/m3-operando/note.md` (開発ルール節), `docs/tasks/m3-operando/overview.md`

---

## 3. 関連実装 (拡張・参考パターン)

### 拡張対象の既存実装 (現状のシグネチャ)

- `src/tsumugin/model/channel.py`:
  - `ChannelKind = Literal["temperature", "time", "pressure", "custom"]` (L8)
  - `ExternalChannel(kind: ChannelKind, sync_map: Mapping[int, float], label: str | None = None)`
    + `value_for(frame_index) -> float | None` (欠損は None)。
  - → **`ChannelKind` の Literal 末尾に** `"voltage", "current", "capacity", "composition"` を追加。
    `ExternalChannel` 本体・`value_for` は**無改変**。echem 拡張は kind の値追加のみ (REQ-007)。
- `src/tsumugin/model/hypothesis.py`:
  - `RefinementMetrics(rwp, gof, chi2, n_obs, n_params, evidence=field(default_factory=dict))` (L14-22)
  - → **末尾に** `multistart: Mapping[str, int] | None = None` を追加。`evidence` の後ろ。
  - `Hypothesis` / `HypothesisStatus` は本タスク非変更。
- `src/tsumugin/model/cell.py`: **新規作成**。CellLayer / BeamConfig / CellConfig / MuCalculator /
  XraylibMuCalculator を定義。
- `src/tsumugin/model/__init__.py`:
  - 現状 `__all__`: Dataset/ExternalChannel/Frame/HistogramRef/Hypothesis/HypothesisStatus/
    LatticeParams/PhaseInstance/PhaseLifecycle/Probe/Project/RefinementMetrics。
  - → `CellLayer`, `BeamConfig`, `CellConfig`, `MuCalculator`, `XraylibMuCalculator` を import + `__all__` 追加。

### 設計契約 (interfaces.py L40-76 準拠、そのまま実装可)

```python
@dataclass(frozen=True)
class CellLayer:                       # model/cell.py (§4)
    role: Literal["window", "electrode", "electrolyte", "separator", "collector"]
    material: str                      # 組成式 or 物質名
    thickness_mm: float
    density: float | None = None       # g/cm3

@dataclass(frozen=True)
class BeamConfig:                      # model/cell.py (§4)
    wavelength: float | None = None    # Å
    energy_kev: float | None = None
    size_mm: tuple[float, float] | None = None

@dataclass(frozen=True)
class CellConfig:                      # model/cell.py (§4 / FR-317。層状セルは透過法のみ)
    geometry: Literal["transmission", "capillary"]     # 位置必須
    layers: tuple[CellLayer, ...] = ()
    beam: BeamConfig | None = None
    mu_t_calc: float | None = None     # 組成計算済み μt (MuCalculator or 手入力)

class MuCalculator(Protocol):          # 組成→μt のエネルギー依存計算 (REQ-019)
    def mu_t(self, config: CellConfig) -> float: ...

class XraylibMuCalculator:             # M3 ではスタブ (呼ぶと NotImplementedError)
    ...
```

### 参考パターン (既存コードから踏襲)

- **Literal 拡張の後方互換性**: `ChannelKind` に値を追加しても、既存の `"temperature"` 等は依然として
  合法値。Literal の末尾追加は**既存の型注釈・生成・比較を狭めない**ため非破壊 (D-Q4 🟡)。
- **末尾フィールド追加の後方互換**: `RefinementMetrics.multistart` は `evidence`
  (`field(default_factory=dict)`) の後ろに既定 None で追加。`TASK-0011` の
  `PhaseInstance.lifecycle` / `Hypothesis.frame_range` 追加と**完全に同型**の非破壊パターン。
- **Protocol + 未実装スタブ**: `EchemLoader` / `BiologicMprLoader` (interfaces.py L221-228)、
  `MuCalculator` / `XraylibMuCalculator` (L69-76) が同型。スタブは `mu_t` を呼ぶと
  `raise NotImplementedError(...)`。Protocol は `@runtime_checkable` 不要 (静的境界のみ)。
- **frozen + tuple/Mapping フィールド**: `CellConfig.layers: tuple[CellLayer, ...]` は immutable tuple の
  ため frozen と両立 (ハッシュ可能)。ただし `RefinementMetrics.multistart` (Mapping) は非ハッシュ化型の
  ため、テストは**等価比較 (`==`) と生成**に留める (既存 `LatticeParams.sigma` / `evidence` と同扱い)。
- **シリアライズ**: `dataclasses.asdict(CellConfig(...))` がネスト dataclass (CellLayer/BeamConfig) を
  再帰的に素の dict へ展開する。**tuple は Python 仕様上 tuple のまま保持される (list へ変換されない)**
  ため layers は `tuple[dict, ...]` として展開される (json モジュールが最終的に tuple を配列化するため
  round-trip 可能 / TC-207-01)。tuple/list を同一視する equality ハックは設けない (== の対称性を守る)。
  専用の `cell_to_dict`/`cell_from_dict` は**本タスク非スコープ** (吸収補正実装 TASK-0026 以降)。

### top-level 公開面の扱い (要判断・後続タスク影響)

- `src/tsumugin/__init__.py` の `__all__` はアルファベット昇順必須で
  `tests/test_m1/m2_symbols_in_dunder_all_and_sorted` が固定。
- TASK-0025 の明記スコープは **`model/__init__.py` の re-export のみ**。top-level 昇格は必須ではない。
  昇格する場合は `__all__` の昇順 (B: BeamConfig, C: CellConfig/CellLayer, M: MuCalculator,
  X: XraylibMuCalculator) を維持すること。**最小構成では model/__init__.py だけで足りる。**

- **参照元**: `src/tsumugin/model/{channel,hypothesis,phase,__init__}.py`, `src/tsumugin/__init__.py`,
  `docs/design/m3-operando/interfaces.py` L40-76,
  `docs/implements/m2-sequential/TASK-0011/` (非破壊拡張の範)

---

## 4. 設計文書

- **型/インターフェース契約**: `docs/design/m3-operando/interfaces.py`
  - L40-48: `CellLayer` / L50-57: `BeamConfig` / L59-67: `CellConfig`
  - L69-72: `MuCalculator` Protocol / L75-76: `XraylibMuCalculator` スタブ
  - L83-87: model 拡張メモ — `ExternalChannel.kind` に voltage/current/capacity/composition 追加、
    `RefinementMetrics.multistart: Mapping[str, int] | None = None` 追加。
- **要件**: `docs/spec/m3-operando/requirements.md`
  - REQ-006 (L35-36): multistart 結果を `RefinementMetrics.multistart {n, n_basins}` として仮説へ記録 (非破壊フィールド追加)。
  - REQ-007 (L40-42): 電気化学 CSV マッパで V/I/Q を `ExternalChannel` (kind=echem 拡張) としてフレーム同期。
  - REQ-016 (L70-72): `CellConfig` データモデル (geometry / layers / beam)。層状セルは透過法のみ。
  - REQ-019 (L78-80): 組成→μt 計算 (xraylib 等) は Protocol のみ定義、M3 では未実装エラー。
  - REQ-404 (L110-111): CellConfig 新設 / ExternalChannel の echem 対応 / RefinementMetrics.multistart は
    既存 API 後方互換の非破壊追加でなければならない。
- **アーキテクチャ / データフロー**: `docs/design/m3-operando/architecture.md`, `docs/design/m3-operando/dataflow.md`。
- **受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md`
  - TC-201-06 (L19): metrics.multistart {n, n_basins} が仮説に記録される。
  - TC-207-01 (L64): CellConfig (transmission/layers/beam) が生成・シリアライズできる。
  - TC-207-07 (L70): MuCalculator Protocol 未実装が NotImplementedError。
- **上位仕様**: `docs/tsumugin_spec_v0.3.md` §4 (データモデル)、FR-311 / FR-313 / FR-317。
- **後続タスクの利用先**: TASK-0026 (吸収補正 AbsorptionConfig — CellConfig 由来 μt を restraint 中心に)、
  TASK-0027 (multistart エンジン — metrics.multistart へ書込)、TASK-0029 (echem — voltage/current 等 kind 利用)。
- **参照元**: 上記各ファイル, `docs/tasks/m3-operando/{TASK-0025.md,overview.md}`

---

## 5. テスト関連情報

- **フレームワーク**: pytest >= 8 + pytest-cov。設定は `pyproject.toml [tool.pytest.ini_options]`。
- **実行コマンド**: `uv run pytest tests/test_model_m3.py` (本タスク単体) / `uv run pytest` (全体回帰) /
  `uv run pytest --cov=tsumugin`。**依存導入は `uv sync --extra gsas`** (プレーン `uv sync` は禁止)。
  本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- **本タスクのテストファイル**: `tests/test_model_m3.py` (**新規**)。既存 `tests/test_model.py` /
  `tests/test_model_m2.py` は**無改変** (パターン参照のみ)。
- **既存テスト構成 (1:1 対応)**: `tests/` 直下に impl と対応する `test_*.py`。`tests/conftest.py` に共通フィクスチャ。
- **命名/記述パターン** (`tests/test_model.py` / `test_model_m2.py` に準拠):
  - 関数名 `test_...`、frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - 決定論/等価は `==`、近似は `pytest.approx`。docstring/コメントに 【テスト目的】【テスト内容】
    【期待される動作】と 🔵/🟡 信頼性レベルを付す慣習。
- **本タスクで書くべき代表テスト観点**:
  - `CellLayer` / `BeamConfig` / `CellConfig` が frozen で生成・等価比較でき、再代入が `FrozenInstanceError`。
  - `CellConfig` が明示値 (geometry/layers/beam/mu_t_calc) と既定 (layers=()/beam=None/mu_t_calc=None) の両方で生成。
  - `dataclasses.asdict(CellConfig(...))` が JSON 互換型のネスト dict を返す (layers は tuple のまま保持) (TC-207-01)。
  - `ExternalChannel(kind="voltage", ...)` 等の新 kind で生成でき `value_for` が従来どおり動く (REQ-007)。
  - 既存 kind (`"temperature"` 等) の生成が**無改変で通る** (後方互換 smoke)。
  - `RefinementMetrics(..., multistart={"n":8,"n_basins":1})` が生成でき値を保持、既定 None で後方互換。
  - `XraylibMuCalculator().mu_t(config)` が `NotImplementedError` (TC-207-07)。
  - `XraylibMuCalculator` が `MuCalculator` Protocol の構造 (`mu_t` メソッド) を満たす (静的境界確認)。
  - re-export: `from tsumugin.model import CellConfig, CellLayer, BeamConfig, MuCalculator, XraylibMuCalculator`
    が解決し `__all__` に含まれる。
- **回帰確認 (完了ゲート)**: `uv run pytest` 全体で**既存テストを無改変で維持** (既存 passed/skipped 件数を維持)。
- **参照元**: `pyproject.toml`, `tests/test_model.py`, `tests/test_model_m2.py`, `tests/conftest.py`,
  `docs/spec/m3-operando/acceptance-criteria.md` (TC-201-06 / TC-207-01/07)

---

## 6. 注意事項

### 技術的制約
- **非破壊性 (P2 / NFR-101 / REQ-404)**: 追加は必ず既定値付きフィールドを**末尾**に。`ChannelKind` は
  Literal の**末尾に値追加** (既存値の意味・型を変えない)。既存フィールドの順序・型・既定を変えない。既存テストは無改変。
- **frozen + Mapping のハッシュ**: `RefinementMetrics.multistart` は `Mapping` (dict) のため frozen でも
  `__hash__` は非ハッシュ化型で失敗し得る。テストは**等価比較 (`==`) と生成**に留め、set/dict キー化はしない
  (既存 `evidence` / `LatticeParams.sigma` と同扱い)。`CellConfig.layers` (tuple) はハッシュ可。
- **XraylibMuCalculator は NotImplementedError**: `mu_t` を呼ぶと `raise NotImplementedError`。
  M3 では Protocol 境界のみ提供し、xraylib への実依存を持たない (REQ-403 コア依存は numpy のみ維持)。
- **決定論 (NFR-102)**: 乱数不使用。純データ構造なので自然に満たす。
- **型注釈**: `Literal`, `Mapping[str, int]`, `tuple[CellLayer, ...]`, `tuple[float, float] | None`,
  `float | None` を正しく付す。`from __future__ import annotations` を新規 `cell.py` 冒頭に置く (前方参照 + Protocol)。

### スコープ境界 (やり過ぎ防止)
- 本タスクは **データモデルの器のみ**。`AbsorptionConfig` / `transmission_factor` / `from_cell_config` /
  μt 精密化 (interfaces.py L97-119)・multistart エンジン (L126-191)・echem ローダ実体 (L199-228) は
  **後続 TASK-0026/0027/0029** のスコープ。
- `MuCalculator` の**算出ロジックは実装しない** (Protocol + NotImplementedError スタブのみ)。
- `CellConfig` の**専用シリアライザ (to_dict/from_dict) は新設しない** (`dataclasses.asdict` で足りる。
  永続化統合は後続)。
- `mu_t_calc` の**値検証 (>0 等) はしない** (器のみ。restraint 中心としての利用は TASK-0026)。

### 後続タスクへの影響
- **後続**: TASK-0026 (吸収補正)、0027 (multistart)、0029 (echem) が本モデル拡張に依存。
  フィールド名 (geometry/layers/beam/mu_t_calc, multistart, ChannelKind の 4 新値) と
  `MuCalculator.mu_t` シグネチャは interfaces.py の契約どおりに固定すること。

- **参照元**: `docs/spec/m3-operando/note.md` (注意事項節),
  `docs/spec/m3-operando/{requirements,acceptance-criteria}.md`,
  `docs/design/m3-operando/interfaces.py`, `CLAUDE.md` (不変条件)

---

## 収集したファイル一覧
- タスク: `docs/tasks/m3-operando/{TASK-0025.md,overview.md}`
- 仕様/要件: `docs/spec/m3-operando/{note,requirements,acceptance-criteria,user-stories,interview-record,prep}.md`
- 設計: `docs/design/m3-operando/{interfaces.py,architecture.md,dataflow.md,design-interview.md}`
- 既存実装: `src/tsumugin/model/{channel,hypothesis,phase,project,__init__}.py`, `src/tsumugin/__init__.py`,
  `src/tsumugin/store/serialization.py` (シリアライズ参考)
- テスト参考: `tests/test_model.py`, `tests/test_model_m2.py`, `tests/conftest.py`, `pyproject.toml`
- 非破壊拡張の範: `docs/implements/m2-sequential/TASK-0011/` (note/requirements/testcases)
- 追加ルール: `AGENTS.md`・`docs/rule/` はいずれも**不在** (規約は `CLAUDE.md` に集約)

**注意**: すべてのファイルパスはプロジェクトルートからの相対パスで記載しています。
