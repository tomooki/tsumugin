# TASK-0017 Red フェーズ記録: Trajectory + FrameRecord + to_csv

**機能名**: trajectory-csv / **要件名**: m2-sequential / **タスクID**: TASK-0017
**テストファイル**: `tests/test_trajectory.py` (新規) / **作成日**: 2026-07-03
**対象実装 (未実装)**: `src/tsumugin/sequential/trajectory.py` の `FrameRecord` / `Trajectory`

> すべてのファイルパスはプロジェクトルートからの相対パス。

---

## 1. 作成したテストケース一覧 (17 件)

| ID | テスト関数 | 分類 | 信頼性 |
|---|---|---|---|
| T-N01 | `test_header_contains_required_columns` | 正常系 | 🔵 |
| T-N02 | `test_row_count_equals_frame_count` | 正常系 | 🔵 |
| T-N03 | `test_common_columns_roundtrip` | 正常系 | 🔵 |
| T-N04 | `test_phase_columns_values` | 正常系 | 🔵 |
| T-N05 | `test_to_csv_returns_input_path` | 正常系 | 🔵 |
| T-N06 | `test_changepoint_reasons_joined_single_cell` | 正常系 | 🟡 |
| T-E01 | `test_failed_frame_blanks_and_no_nonfinite_leak` | 異常系 | 🔵 |
| T-E02 | `test_phase_nonfinite_wt_frac_blank` | 異常系 | 🟡 |
| T-E03 | `test_none_axis_and_temperature_blank` | 異常系 | 🔵 |
| T-E04 | `test_phaseless_frame_blank_phase_columns` | 異常系 | 🟡 |
| T-B01 | `test_empty_trajectory_no_data_rows` | 境界値 | 🟡 |
| T-B02 | `test_single_frame_one_data_row` | 境界値 | 🟡 |
| T-B03 | `test_phase_union_sorted_and_absent_blank` | 境界値 | 🔵 |
| T-B04 | `test_lifecycle_only_phase_columns` | 境界値 | 🟡 |
| T-B05 | `test_deterministic_byte_identical` | 境界値 | 🔵 |
| T-B06 | `test_frozen_immutability` | 境界値 | 🔵 |
| T-B07 | `test_finite_endpoints_preserved` | 境界値 | 🔵 |

信頼性内訳: 🔵 10 / 🟡 7 / 🔴 0。

---

## 2. Red フェーズで凍結した CSV レイアウト契約

テスト側で以下を定数化し (`FRAME_COMMON_COLUMNS` / `PHASE_FIELD_SUFFIXES` / `REASONS_DELIMITER`)、
Green 実装が満たすべき契約として固定した:

- **フレーム共通列 (固定・先頭順)**:
  `frame_index, axis_value, temperature, rwp, chi2, changepoint, changepoint_reasons, refine_failed`
- **相ごと列**: 全 `records[*].phases` の `phase_ref` と `lifecycles` キーの**和集合を `sorted()` 昇順**で確定し、
  各 ref につき `<ref>.a, <ref>.b, <ref>.c, <ref>.scale, <ref>.wt_frac, <ref>.birth_frame, <ref>.death_frame, <ref>.confidence`。
- **bool 表現**: `str(bool)` = `"True"` / `"False"` (T-N03/T-E01 で凍結)。
- **数値表現**: `str(v)` (例 `5.0`, `300.0`, `-273.15`, `1e-12`)。frame_index は `str(int)`。
- **changepoint_reasons**: tuple を `"|"` 区切りで 1 セル連結 (T-N06)。空 tuple は空欄。
- **空欄化**: `None` / `inf` / `-inf` / `NaN` の数値セルは空文字列 `""`。有限端点 (0.0/負値/極小) は保持 (T-B07)。
- **決定論 I/O**: `open(newline="", encoding="utf-8")` 固定でバイト同一 (T-B05)。

> 上記のうち (b) `bool` 表現, (c) `changepoint_reasons` 区切り `"|"`, (d) 相列名規約 `<ref>.a` 等は
> requirements/testcases で「Red で凍結」とされた事項であり、本テストで確定した。α/β/γ・σ・volume は列に含めない。

---

## 3. 期待される失敗内容 (確認済み)

新規テストファイルのみ実行 (`uv run pytest tests/test_trajectory.py -q`):

```
ImportError: cannot import name 'FrameRecord' from 'tsumugin.sequential'
(C:\...\src\tsumugin\sequential\__init__.py)
ERROR tests/test_trajectory.py — Interrupted: 1 error during collection
```

`src/tsumugin/sequential/trajectory.py` が未実装で `FrameRecord` / `Trajectory` を re-export していないため、
collection 時の import で失敗し、17 テスト全てがエラー (=失敗) になる。これは Red フェーズの期待どおり。
`uvx ruff check tests/test_trajectory.py` は line-length 100 でクリーン (All checks passed)。

---

## 4. Green フェーズで実装すべき内容

1. **`src/tsumugin/sequential/trajectory.py` を新設**:
   - `@dataclass(frozen=True) class FrameRecord`: interfaces.py L141-153 のフィールド順・型を厳守
     (`frame_index, axis_value, temperature, phases, rwp, chi2, changepoint, changepoint_reasons, refine_failed`)。
   - `@dataclass(frozen=True) class Trajectory`: `records: tuple[FrameRecord, ...]` /
     `lifecycles: Mapping[str, PhaseLifecycle]` + `to_csv(self, path: str) -> str`。
   - `PhaseInstance` / `PhaseLifecycle` / `LatticeParams` は `tsumugin.model` から import して再利用 (新設しない)。
2. **`to_csv` の実装方針**:
   - 相 ref = `sorted(全 records の phase_ref ∪ lifecycles.keys())` で列順を決定論化。
   - 列ヘッダ = `FRAME_COMMON_COLUMNS` + 各 ref の 8 相列 (`§2` の順)。
   - 数値セルはローカル純化ヘルパ (`_finite_or_none` と同思想) を通し、`None`/非有限 → `""`、有限 → `str(v)`。
   - `bool` → `str(bool)`、`changepoint_reasons` → `"|".join(...)`。
   - `open(path, "w", newline="", encoding="utf-8")` + `csv.writer` (既定 excel 方言)。
   - 書き出した `path` を返す。
3. **`src/tsumugin/sequential/__init__.py`**: `__all__` に `FrameRecord` / `Trajectory` をアルファベット昇順維持で追加、re-export する。
4. **Lint**: `uvx ruff check src tests` (line-length 100, py312) をクリーンに保つ。
