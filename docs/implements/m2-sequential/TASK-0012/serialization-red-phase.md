# TASK-0012 store/serialization Redフェーズ記録

**機能名**: store/serialization — `phase_to_dict` / `phase_from_dict`
**要件名**: m2-sequential / **タスクID**: TASK-0012
**作成日**: 2026-07-03
**テストファイル**: `tests/test_serialization.py` (新規)
**テスト対象実装**: `src/tsumugin/store/serialization.py` (未実装)

---

## 1. 作成したテストケース一覧 (15 件)

テストケース定義 (`serialization-testcases.md`, 15 件) と 1:1 対応。

| ID | テスト関数 | 分類 | 信頼性 |
|---|---|---|---|
| N-01 | `test_full_phase_roundtrip_equal` | 正常系 | 🔵 |
| N-02 | `test_to_dict_schema_keys_and_nesting` | 正常系 | 🟡 |
| N-03 | `test_full_phase_dict_json_dumps_allow_nan_false` | 正常系 | 🔵 |
| N-04 | `test_lifecycle_roundtrip_preserved` | 正常系 | 🔵 |
| N-05 | `test_sigma_occupancies_roundtrip_preserved` | 正常系 | 🔵 |
| N-06 | `test_deterministic_to_dict_and_canonical_json` | 正常系 | 🟡 |
| E-01 | `test_non_finite_scale_becomes_none_and_json_safe` | 異常系 | 🔵 |
| E-02 | `test_non_finite_lattice_and_sigma_become_none` | 異常系 | 🔵 |
| E-03 | `test_non_finite_wt_frac_occupancy_confidence_become_none` | 異常系 | 🟡 |
| B-01 | `test_degenerate_roundtrip_minimal_phase` | 境界値 | 🔵 |
| B-02 | `test_wt_frac_none_roundtrip_not_confused_with_zero` | 境界値 | 🟡 |
| B-03 | `test_from_dict_ignores_unknown_keys` | 境界値 | 🟡 |
| B-04 | `test_from_dict_fills_missing_optional_keys` | 境界値 | 🟡 |
| B-05 | `test_default_lattice_angles_roundtrip` | 境界値 | 🔵 |
| B-06 | `test_confidence_boundary_values_roundtrip` | 境界値 | 🟡 |

**信頼性分布**: 🔵 8 / 🟡 7 / 🔴 0 — 完了条件① N-01 / ② B-01 / ③ N-03・E-01〜E-03 / ④ B-03 に対応。

---

## 2. 期待される失敗内容

現状 `src/tsumugin/store/serialization.py` が未実装のため、テストファイルの
`from tsumugin.store.serialization import phase_from_dict, phase_to_dict` が **collection 時に失敗**し、
全 15 テストがエラー (=失敗) になる。

```
ERROR collecting tests/test_serialization.py
E   ModuleNotFoundError: No module named 'tsumugin.store.serialization'
```

`uvx ruff check tests/test_serialization.py` は **All checks passed!** (line-length 100 準拠)。

---

## 3. Greenフェーズで実装すべき内容

`src/tsumugin/store/serialization.py` を新規作成し、標準ライブラリ (`json`/`math`/`dataclasses`) のみで:

- `phase_to_dict(phase: PhaseInstance) -> dict[str, Any]`:
  - dict スキーマ (キー名・ネスト) を固定: `phase_ref` / `lattice{a,b,c,alpha,beta,gamma,sigma}` /
    `scale` / `wt_frac` / `occupancies` / `lifecycle{birth_frame,death_frame,confidence}|None`。
  - 全 float フィールド (scale / lattice の a〜gamma / sigma 値 / occupancies 値 / wt_frac / confidence)
    を `_finite_or_none` (ローカル定義, `math.isfinite` 判定) で純化し非有限を `None` 化。
  - `sigma` / `occupancies` は `dict(mapping)` で素の dict へコピー。tuple/dataclass を残さない。
- `phase_from_dict(data: Mapping[str, Any]) -> PhaseInstance`:
  - 明示キー取り出し (`data["phase_ref"]` / `data.get("scale", 1.0)` 等) で**未知キーを無視** (前方互換)。
  - 欠損 optional キーを既定補完 (scale→1.0 / wt_frac→None / occupancies→{} / lifecycle→None /
    sigma→{} / 角→90.0)。`lattice` / `lifecycle` は `LatticeParams` / `PhaseLifecycle` として再構築。
- **レイヤ制約**: `search/tree.py::_finite_or_none` を import せず serialization.py にローカル定義する。
- **非破壊**: 既存 model / store の API は無改変。
