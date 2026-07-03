# TASK-0011 model 拡張 Redフェーズ記録

**機能名**: model 拡張 (PhaseLifecycle / ExternalChannel / frame_range)
**タスクID**: TASK-0011 / **要件名**: m2-sequential
**作成日時**: 2026-07-03
**テストファイル**: `tests/test_model_m2.py` (新規)
**テスト対象実装**: `src/tsumugin/model/{phase,hypothesis,channel,__init__}.py` (未実装)

---

## 1. 作成したテストケース一覧 (15 件)

テストケース定義 (`model-extension-testcases.md`) の 15 件に 1:1 対応。

| ID | テスト関数 | 分類 | 信頼性 |
|---|---|---|---|
| N-01 | `test_phase_lifecycle_explicit_construction_holds_attributes` | 正常系 | 🔵 |
| N-02 | `test_phase_lifecycle_equality_is_structural` | 正常系 | 🔵 |
| N-03 | `test_external_channel_value_for_existing_frame_returns_value` | 正常系 | 🔵 |
| N-04 | `test_external_channel_equality_with_mapping_field` | 正常系 | 🔵 |
| N-05 | `test_phase_instance_lifecycle_with_updates_is_nondestructive` | 正常系 | 🔵 |
| N-06 | `test_hypothesis_frame_range_explicit_construction` | 正常系 | 🔵 |
| N-07 | `test_model_reexports_new_symbols_in_dunder_all` | 正常系 | 🔵 |
| E-01 | `test_phase_lifecycle_is_frozen` | 異常系 | 🔵 |
| E-02 | `test_external_channel_is_frozen` | 異常系 | 🔵 |
| E-03 | `test_value_for_missing_frame_returns_none` | 異常系 | 🔵 |
| B-01 | `test_phase_lifecycle_all_defaults` | 境界値 | 🔵 |
| B-02 | `test_phase_instance_positional_construction_lifecycle_default_none` | 境界値 | 🔵 |
| B-03 | `test_hypothesis_minimal_construction_frame_range_default_none` | 境界値 | 🔵 |
| B-04 | `test_empty_sync_map_value_for_always_none` | 境界値 | 🟡 |
| B-05 | `test_phase_lifecycle_confidence_boundary_values` | 境界値 | 🟡 |

**信頼性分布**: 🔵 13 / 🟡 2 / 🔴 0

---

## 2. 期待される失敗

- 実行コマンド: `uv run pytest tests/test_model_m2.py`
- 結果: **collection 時 ImportError** で全テストがエラー(=失敗)。

```
tests\test_model_m2.py:22: in <module>
    from tsumugin.model import (
E   ImportError: cannot import name 'ExternalChannel' from 'tsumugin.model'
```

`PhaseLifecycle` / `ExternalChannel` が未実装かつ `model/__init__.py` で
re-export されていないため、import 段階で失敗する。これは Red フェーズの正しい状態。

- Lint: `uvx ruff check tests/test_model_m2.py` → All checks passed (line-length 100)。

---

## 3. Green フェーズで実装すべき内容

1. `src/tsumugin/model/phase.py`:
   - `PhaseLifecycle` を frozen dataclass で新設
     (`birth_frame: int | None = None`, `death_frame: int | None = None`, `confidence: float = 1.0`)。
   - `PhaseInstance` 末尾に `lifecycle: PhaseLifecycle | None = None` を追加。
2. `src/tsumugin/model/hypothesis.py`:
   - `Hypothesis` 末尾に `frame_range: tuple[int, int] | None = None` を追加。
3. `src/tsumugin/model/channel.py` (新規):
   - `ExternalChannel` を frozen dataclass で新設
     (`kind: Literal["temperature","time","pressure","custom"]`, `sync_map: Mapping[int, float]`,
     `label: str | None = None`)。
   - `value_for(self, frame_index: int) -> float | None`: `sync_map.get(frame_index)`
     (欠損は None、例外を出さない = EDGE-102)。
4. `src/tsumugin/model/__init__.py`:
   - `PhaseLifecycle`・`ExternalChannel` を import + `__all__` に追加。

**回帰ゲート**: `uv run pytest` 全体で既存 226 テスト (223 passed / 3 skipped) を無改変で維持。
既存テストファイルは 1 行も変更しない。全フィールド既定値付きの末尾追加 (REQ-404 非破壊)。
