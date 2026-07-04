# TASK-0025 model 拡張 Redフェーズ記録

**機能名**: model 拡張 (CellConfig / CellLayer / BeamConfig / channel kind / metrics.multistart / MuCalculator)
**タスクID**: TASK-0025 / **要件名**: m3-operando
**作成日時**: 2026-07-04
**テストファイル**: `tests/test_model_m3.py` (新規)
**テスト対象実装**: `src/tsumugin/model/{cell,channel,hypothesis,__init__}.py` (cell.py 新設・他は非破壊拡張、未実装)

---

## 1. 作成したテストケース一覧 (21 件)

テストケース定義 (`model-cell-extension-testcases.md`) の 21 件に 1:1 対応。

| ID | テスト関数 | 分類 | 信頼性 |
|---|---|---|---|
| N-01 | `test_cell_layer_explicit_construction_holds_attributes` | 正常系 | 🔵 |
| N-02 | `test_cell_layer_equality_is_structural` | 正常系 | 🔵 |
| N-03 | `test_beam_config_construction_wavelength_and_energy_variants` | 正常系 | 🔵 |
| N-04 | `test_cell_config_explicit_construction_holds_attributes` | 正常系 | 🔵 |
| N-05 | `test_cell_config_equality_including_nested_values` | 正常系 | 🔵 |
| N-06 | `test_cell_config_asdict_serializes_nested_to_json_native` | 正常系 | 🟡 |
| N-07 | `test_external_channel_voltage_kind_value_for` | 正常系 | 🔵 |
| N-08 | `test_refinement_metrics_multistart_explicit_construction` | 正常系 | 🔵 |
| N-09 | `test_xraylib_mu_calculator_satisfies_mu_calculator_protocol` | 正常系 | 🟡 |
| N-10 | `test_model_reexports_cell_symbols_in_dunder_all` | 正常系 | 🔵 |
| E-01 | `test_cell_layer_is_frozen` | 異常系 | 🔵 |
| E-02 | `test_beam_config_is_frozen` | 異常系 | 🔵 |
| E-03 | `test_cell_config_is_frozen` | 異常系 | 🔵 |
| E-04 | `test_xraylib_mu_calculator_mu_t_raises_not_implemented` | 異常系 | 🔵 |
| B-01 | `test_beam_config_all_defaults` | 境界値 | 🔵 |
| B-02 | `test_cell_config_minimal_construction_defaults` | 境界値 | 🔵 |
| B-03 | `test_cell_layer_density_default_none` | 境界値 | 🔵 |
| B-04 | `test_existing_temperature_kind_backward_compatible` | 境界値 | 🔵 |
| B-05 | `test_refinement_metrics_minimal_construction_multistart_default_none` | 境界値 | 🔵 |
| B-06 | `test_cell_config_empty_layers_asdict` | 境界値 | 🟡 |
| B-07 | `test_all_four_new_channel_kinds_constructible` | 境界値 | 🔵 |

**信頼性分布**: 🔵 18 / 🟡 3 / 🔴 0 (テストケース定義の 🔵 17/🟡 4 に対し N-06/B-06/N-09 を 🟡 維持、
kind 網羅 B-07 は interfaces.py 明記のため 🔵)

---

## 2. 期待される失敗

- 実行コマンド: `uv run pytest tests/test_model_m3.py`
- 結果: **collection 時 ImportError** で全 21 テストがエラー(=失敗)。

```
tests\test_model_m3.py:28: in <module>
    from tsumugin.model import (
E   ImportError: cannot import name 'BeamConfig' from 'tsumugin.model'
```

`CellLayer` / `BeamConfig` / `CellConfig` / `MuCalculator` / `XraylibMuCalculator` が未実装かつ
`model/__init__.py` で re-export されていないため、import 段階で失敗する。
`ChannelKind` 拡張 (N-07/B-07) と `RefinementMetrics.multistart` (N-08/B-05) も同一ファイルの
import 失敗により全件 Red。これは Red フェーズの正しい状態。

- Lint: `uvx ruff check tests/test_model_m3.py` → All checks passed (line-length 100)。
- 回帰確認: `uv run pytest --ignore=tests/test_model_m3.py` → **453 passed, 3 skipped** (既存テスト無退行)。

---

## 3. Green フェーズで実装すべき内容

1. `src/tsumugin/model/cell.py` (新規):
   - 冒頭に `from __future__ import annotations`。
   - `CellLayer` frozen dataclass
     (`role: Literal["window","electrode","electrolyte","separator","collector"]`, `material: str`,
     `thickness_mm: float`, `density: float | None = None`)。
   - `BeamConfig` frozen dataclass
     (`wavelength: float | None = None`, `energy_kev: float | None = None`,
     `size_mm: tuple[float, float] | None = None`)。
   - `CellConfig` frozen dataclass
     (`geometry: Literal["transmission","capillary"]`, `layers: tuple[CellLayer, ...] = ()`,
     `beam: BeamConfig | None = None`, `mu_t_calc: float | None = None`)。
   - `MuCalculator(Protocol)`: `mu_t(self, config: CellConfig) -> float`。
   - `XraylibMuCalculator`: `mu_t` が `raise NotImplementedError(...)` (xraylib 実依存なし)。
2. `src/tsumugin/model/channel.py`:
   - `ChannelKind` Literal の**末尾に** `"voltage", "current", "capacity", "composition"` を追加。
     `ExternalChannel` 本体・`value_for` は無改変。
3. `src/tsumugin/model/hypothesis.py`:
   - `RefinementMetrics` の `evidence` の後ろに `multistart: Mapping[str, int] | None = None` を追加。
4. `src/tsumugin/model/__init__.py`:
   - `CellLayer` / `BeamConfig` / `CellConfig` / `MuCalculator` / `XraylibMuCalculator` を
     import + `__all__` に追加。

**回帰ゲート**: `uv run pytest` 全体で既存 453 passed / 3 skipped を無改変で維持。
既存テストファイルは 1 行も変更しない。全フィールド既定値付きの末尾追加 (REQ-404 非破壊)。
バリデーション (energy/wavelength 一方必須・mu_t_calc>0 等) は実装しない (器のみ、後続 TASK-0026)。
