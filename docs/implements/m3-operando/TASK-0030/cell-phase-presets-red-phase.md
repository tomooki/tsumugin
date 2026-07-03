# TASK-0030 Red フェーズ記録: operando/cell_phases — セル固定相プリセット (FR-312)

**機能名**: cell-phase-presets / **タスクID**: TASK-0030 / **要件名**: m3-operando
**テストファイル**: `tests/test_cell_phases.py` (新規, 12 ケース) / **作成日時**: 2026-07-04

> パスはプロジェクトルートからの相対パス。

---

## 1. 作成したテストケース一覧 (12 件)

| ID | テスト名 | 対応 AC | 信頼性 |
|---|---|---|---|
| TC-N01 | `test_cell_phase_presets_has_three_fixed_phase_specs` | TC-203-01 | 🔵 |
| TC-N02 | `test_cell_phase_presets_lattice_matches_literature` | 完了条件3 | 🟡 |
| TC-N03 | `test_fixed_free_suffixes_returns_scale_only` | TC-203-02 | 🟡 |
| TC-N04 | `test_fixed_phase_spec_frozen_and_structural_equality` | §4 データモデル | 🔵 |
| TC-N05 | `test_cell_phase_presets_have_valid_phase_and_label` | TC-203-01 | 🔵 |
| TC-N06 | `test_active_phase_refines_with_fixed_cell_phase` | TC-203-03 | 🔵 |
| TC-N07 | `test_cell_phase_presets_deterministic` | NFR-102 | 🔵 |
| TC-A01 | `test_fixed_phase_spec_is_frozen` | §4 不変性 | 🔵 |
| TC-A02 | `test_cell_phase_presets_unknown_key_raises_keyerror` | Mapping 契約 | 🟡 |
| TC-BV01 | `test_hexagonal_presets_orthohexagonal_b_equals_a_sqrt3` | 直方近似の核心 | 🟡 |
| TC-BV02 | `test_al_preset_is_cubic_isotropic` | 完了条件3 | 🟡 |
| TC-BV03 | `test_fixed_phase_lattice_unchanged_after_scale_only_refine` | TC-203-02 | 🟡 |

## 2. 期待される失敗

- `from tsumugin.operando.cell_phases import CELL_PHASE_PRESETS, FixedPhaseSpec, fixed_free_suffixes`
  が `ModuleNotFoundError: No module named 'tsumugin.operando.cell_phases'` を送出し、全 12 ケースが
  collection error で失敗する (対象モジュール未実装のため)。

実行コマンド: `uv run pytest tests/test_cell_phases.py -q`
結果: `ERROR tests/test_cell_phases.py` (1 error during collection) — Red 確認済み。

## 3. Green フェーズで実装すべき内容

1. `src/tsumugin/operando/cell_phases.py` を新規作成:
   - `FixedPhaseSpec` frozen dataclass (`phase: PhaseInstance` / `label: str`)。
   - `CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]` (キー "Be"/"Al"/"graphite")。
     格子は直方近似 — Be(a=2.2858, b=a·√3, c=3.5843) / Al(a=b=c=4.0495) / graphite(a=2.464, b=a·√3, c=6.711)。
     **docstring に直方近似・文献値出典・実回折とのずれを明記**。
   - `fixed_free_suffixes(spec) -> tuple[str, ...]` は常に `("scale",)` を返す。
2. `src/tsumugin/operando/__init__.py` に 3 シンボルを re-export 追加。
