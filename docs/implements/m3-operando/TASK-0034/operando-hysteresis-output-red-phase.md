# TASK-0034 TDD Red フェーズ記録 — operando/hysteresis + 結合出力 (FR-315 / FR-314)

**機能名**: operando-hysteresis-output / **タスクID**: TASK-0034 / **要件名**: m3-operando
**テストファイル**: `tests/test_hysteresis_output.py` (15 件 / ruff line-length 100 pass)
**対象実装 (未実装)**: `src/tsumugin/operando/hysteresis.py` + `src/tsumugin/operando/output.py`
**作成日時**: 2026-07-04

---

## 1. 作成したテストケース一覧 (15 件 = 正常系 7 / 異常系 3 / 境界値 5)

| # | テスト名 | 対応 | 信頼性 |
|---|---|---|---|
| N1 | `test_combined_csv_contains_vx_and_wtfrac_lattice_readback` | TC-205-01 | 🔵 |
| N2 | `test_transition_point_interpolates_xv_and_sigma_from_boundary` | TC-205-02 / D-Q10 | 🔵 |
| N3 | `test_split_branches_separates_charge_discharge_on_nonmonotonic_x` | TC-205-03 / REQ-104 | 🟡 |
| N4 | `test_branch_differences_computes_same_x_charge_discharge_diff` | TC-205-04 前半 / REQ-012 | 🟡 |
| N5 | `test_combined_csv_outer_join_blank_for_missing_frames` | D9 外部結合 | 🟡 |
| N6 | `test_combined_csv_deterministic_byte_identical` | NFR-102 | 🔵 |
| N7 | `test_hysteresis_and_transition_deterministic_bit_identical` | NFR-102 | 🔵 |
| E1 | `test_branch_differences_single_branch_yields_none_and_warns` | EDGE-007 / TC-205-04 後半 | 🟡 |
| E2 | `test_combined_csv_never_leaks_nonfinite_values` | 完了条件5 / M1/M2 教訓 | 🔵 |
| E3 | `test_transition_and_comparison_degrade_nonfinite_to_none` | 非有限縮退 | 🟡 |
| B1 | `test_transition_point_at_series_ends_returns_none_fields` | D-Q10 縮退 | 🟡 |
| B2 | `test_combined_csv_blank_for_none_echem_cells` | 部分同期 | 🟡 |
| B3 | `test_combined_csv_handles_absent_echem_columns` | 列縮退 | 🟡 |
| B4 | `test_branch_comparison_and_transition_point_are_frozen` | 不変データ契約 | 🔵 |
| B5 | `test_split_branches_empty_single_and_flat_deterministic` | 最小入力/tie-break | 🟡 |

## 2. Red フェーズで凍結した設計判断 (契約)

1. **echem 列名**: `EchemData` フィールド名をそのまま列名にする (`voltage`/`current`/`capacity`/`composition_x`)。
   空 tuple の echem 列は CSV に**列自体を追加しない** (`echem.to_channels` の空縮退と同流儀) → N1/B3。
2. **外部結合**: 行集合 = trajectory ∪ echem の frame_index 和集合。片側欠損・None・非有限は空欄 → N5/B2/E2。
3. **転移点 (D-Q10 認可式・(b-1,b) 採用)**: `transition_point(echem, b)` は隣接 2 フレーム (b-1, b) を用い、
   `x=(x[b-1]+x[b])/2`・`voltage=(v[b-1]+v[b])/2`・`sigma_x=abs(x[b]-x[b-1])`・`sigma_v=abs(v[b]-v[b-1])`。
   `b<=0`/`b>=n`/隣接 echem 欠損 (None)/非有限は該当フィールド None。`frame_index` は常に保持 → N2/E3/B1。
   *(N2 が 🔵 で midpoint=(x[b-1]+x[b])/2 を凍結するため (b-1,b) を採用。B1 の「端」は隣接不能端 b<=0 / b>=n と解釈。)*
4. **枝分離 (REQ-104)**: `dx=x[i]-x[i-1]` の符号で分離。`dx>0`→`charge_idx` (第1)、`dx<0`→`discharge_idx` (第2)。
   `dx==0`/先頭フレーム (dx 未定義)/None フレームは両枝除外。昇順・重複なし → N3/B5。
5. **枝間差分 (EDGE-007)**: 共通 x グリッドは両枝の finite な x の**全域** (min..max) を n_grid 分割。各グリッド x で
   線形補間し `difference = charge_value - discharge_value`。片枝のみの x は該当 value/difference を None + UserWarning → N4/E1。

## 3. 期待される失敗内容 (確認済み)

`uv run pytest tests/test_hysteresis_output.py -q` は collection 時に
`ModuleNotFoundError: No module named 'tsumugin.operando.hysteresis'` で失敗 (対象モジュール未実装のため import 失敗 → 全 15 件エラー)。
`uvx ruff check tests/test_hysteresis_output.py` は All checks passed。

## 4. Green フェーズで実装すべき内容

- `src/tsumugin/operando/hysteresis.py`: `BranchComparison` (frozen) / `split_branches` / `branch_differences`。
- `src/tsumugin/operando/output.py`: `TransitionPoint` (frozen) / `combined_csv` / `transition_point`。
  非有限→空欄化は `trajectory._num_cell` と同思想のローカル純化を持つ (レイヤ横断 import を避ける)。
- `src/tsumugin/operando/__init__.py` の `__all__` へ 5 シンボルをアルファベット順維持で非破壊追記。
- 補間は numpy (`np.interp`)、CSV は stdlib `csv` のみ。既存テスト green 維持 (REQ-404)。

**次のステップ**: `/tsumiki:tdd-green m3-operando TASK-0034` で最小実装。
