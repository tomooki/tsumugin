# TASK-0024 Red フェーズ記録: thermal onset 意味論修正 (Issue #4)

**機能名**: thermal-onset-semantics / **タスクID**: TASK-0024 / **要件名**: m3-operando
**作成日時**: 2026-07-03 / **フェーズ**: Red (失敗テスト作成)
**テストファイル**: `tests/test_thermal.py` (既存 18 件に 1 修正 + 6 新規関数追加)
**対象実装 (未修正)**: `src/tsumugin/sequential/thermal.py::estimate_transition`

> すべてのパスはプロジェクトルートからの相対パス。

## 正しい不変条件 (テスト設計の前提)

- onset は「遷移開始側 (低温側・先行するエッジ)」。**両方向とも `onset < midpoint`**。
- appearing (0→1): onset = 分率 **10%** 交差 (現行維持)。
- disappearing (1→0): onset = 分率 **90%** 交差 (新)。
- `SIGMOID_DOWN` 実測交差: 90% ≈ **366.46 K** < 50% = 400 K < 10% ≈ 433.54 K。
- TASK-0024.md/TC-208-01 の「disappearing: onset > midpoint」は 90% 交差メカニズムと矛盾する誤記のため
  `onset < midpoint` で固定 (requirements §⚠️ / note §⚠️)。

## 作成したテストケース一覧 (7 件: 1 修正 + 6 追加)

| ケースID | テスト関数 | 種別 | 現行実装での結果 |
|---|---|---|---|
| TC-T-N02 | `test_transition_sigmoid_down_direction_disappearing` (既存へ onset 検証追加) | 修正 | **FAIL** (onset 433.54 ≮ 400) |
| TC-T-N03 | `test_transition_disappearing_onset_is_ninety_pct_value` | 追加 | **FAIL** (onset 433.54 ≠ 366.46) |
| TC-T-E01 | `test_transition_disappearing_shallow_below_ninety_returns_none` | 追加 | PASS (midpoint 未達で None, 縮退不変) |
| TC-T-B01 | `test_transition_disappearing_ninety_pct_on_grid_point` | 追加 | **FAIL** (onset 450 ≠ 350) |
| TC-T-B02 | `test_transition_direction_tie_is_appearing_with_ten_pct_onset` | 追加 | PASS (appearing 経路は不変) |
| TC-T-B03 | `test_transition_disappearing_deterministic_bit_identical` | 追加 | PASS (決定論は不変) |
| TC-T-B04 | `test_transition_no_nonfinite_leak_both_directions` (parametrize 2) | 追加 | PASS (非有限漏洩なし不変) |

- **回帰 (無改変 green で担保・新規コードなし)**: TC-T-N01 / TC-T-E02 / TC-T-E03 / TC-T-R01〜R03 (計 6)。
- **設計意図**: 中核の意味論変更を突く N02/N03/B01 が現行実装 (disappearing も 10% 交差) に対して失敗する。
  E01/B02/B03/B04 は「修正前後で不変であるべき不変条件」を固定するガードテストで、現行実装でも green。

## 期待される失敗内容 (現行実装 = disappearing も 10% 交差)

```
FAILED tests/test_thermal.py::test_transition_sigmoid_down_direction_disappearing
  assert est.onset < est.midpoint  → 433.54 < 400.0 が False
FAILED tests/test_thermal.py::test_transition_disappearing_onset_is_ninety_pct_value
  assert est.onset == approx(366.46, abs=1.0)  → Obtained 433.54
FAILED tests/test_thermal.py::test_transition_disappearing_ninety_pct_on_grid_point
  assert est.onset == approx(350.0)  → Obtained 450.0
```

実行: `uv run --extra gsas python -m pytest tests/test_thermal.py -v` → **3 failed, 22 passed** (25 items)。
ruff: `uvx ruff check tests/test_thermal.py` → All checks passed (line-length 100)。

## Green フェーズで実装すべき内容

`src/tsumugin/sequential/thermal.py::estimate_transition` L204-206 の onset 推定を direction 依存化する (最小差分):

```python
# 【onset 推定】: direction に応じ appearing=10% / disappearing=90% 交差 (遷移開始側=低温側) を採る。
onset_level = _ONSET_LEVEL if direction == "appearing" else (1.0 - _ONSET_LEVEL)
onset_hit = _interpolate_crossing(temperatures, fractions, onset_level)
onset = onset_hit[0] if onset_hit is not None else None
```

- midpoint 算出・direction 判定・σ 算出・点数不足縮退・`_interpolate_crossing` は無改変。
- `TransitionEstimate` の署名 (`onset` フィールド名含む) は不変 (API 非破壊 / P2 / REQ-404)。
- L7-8 モジュール docstring・L29-32 onset 定数コメント・L204 onset 推定コメントを direction 依存へ更新。
- 完了後: `uv run --extra gsas python -m pytest tests/test_thermal.py` 全 green、`uvx ruff check src tests` clean。
