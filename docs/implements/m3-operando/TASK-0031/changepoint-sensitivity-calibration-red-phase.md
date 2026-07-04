# TASK-0031 Red フェーズ記録: changepoint 感度較正 (Issue #3)

**機能名**: changepoint-sensitivity-calibration / **タスクID**: TASK-0031 / **要件名**: m3-operando
**フェーズ**: Red (失敗するテスト作成) / **作成日時**: 2026-07-04

> すべてのパスはプロジェクトルートからの相対パス。

---

## 1. 作成したテストケース一覧

### 新規テストコード (12 件)

| ケースID | テスト関数 | ファイル | 分類 | 現状 (Red) |
|---|---|---|---|---|
| TC-CP-N01 | `test_single_frame_noise_does_not_trigger_new_peaks` | test_sequential_engine.py | 正常系 | ❌ FAIL (現行は frame10 で即発火) |
| TC-CP-N02 | `test_persistent_new_peak_triggers_after_persistence_frames` | test_sequential_engine.py | 正常系 | ❌ FAIL (現行は frame10 で発火。持続なし) |
| TC-CP-N03 | `test_search_runs_only_on_gated_changepoint_frames` | test_sequential_engine.py | 正常系 | ❌ FAIL (単発フレーム 10 で探索起動) |
| TC-CP-E01 | `test_below_intensity_threshold_micro_peak_never_counts` | test_sequential_engine.py | 異常系 | ✅ PASS (既存 find_peaks 0.05 で微小 0.02 は非検出。強度ゲートの担保) |
| TC-CP-E02 | `test_failed_frame_between_persistent_peaks_is_deterministic` | test_sequential_engine.py | 異常系 | ✅ PASS (失敗フレーム継続 + 決定論の担保) |
| TC-CP-E03 | `test_flat_pattern_yields_no_unmatched_and_no_trigger` | test_sequential_engine.py | 異常系 | ✅ PASS (空縮退の担保) |
| TC-CP-B01 | `test_persistence_boundary_fires_exactly_at_m_frames` | test_sequential_engine.py | 境界値 | ❌ FAIL (持続境界未実装) |
| TC-CP-B02 | `test_intensity_threshold_boundary_gates_new_peaks` | test_sequential_engine.py | 境界値 | ❌ FAIL (0.06 持続が frame10 で即発火) |
| TC-CP-B03 | `test_persistence_one_degenerates_to_immediate_trigger` | test_sequential_engine.py | 境界値 | ❌ FAIL (`new_peak_persistence` フィールド未実装) |
| TC-CP-B06 | `test_non_consecutive_unmatched_resets_persistence_counter` | test_sequential_engine.py | 境界値 | ❌ FAIL (連続カウンタ未実装) |
| TC-CP-B04 | `test_changepoint_config_calibration_field_defaults` | test_changepoint.py | 境界値 | ❌ FAIL (新規 2 フィールド未実装 → AttributeError) |
| TC-CP-R02 | `test_changepoint_config_backward_compatible_constructor` | test_changepoint.py | 回帰 | ❌ FAIL (新規 2 フィールド未実装 → AttributeError) |

### 修正した既存テスト (相互作用の合意例外, TC-CP-R03)

- `test_sequential_engine.py::test_phase_b_emergence_triggers_changepoint`:
  期待発火フレームを **frame10 → frame11** へ理由コメント付き最小修正 (持続 M=2 の設計上の 1 フレーム遅延)。
  現状は Red (現行実装は frame10 で発火、frame11 では非発火のため修正後 assert が失敗)。

### 回帰確認 (既存テスト無改変 green で担保・新規コードなし)

- TC-CP-R01: `tests/test_changepoint.py` 純関数テスト群 (TC-C-*) は無改変 green。
- TC-CP-R04: `tests/test_sequential_engine.py` の相 B 以外の既存 engine テストは無改変 green。
- TC-CP-B05 (決定論): 既存 `test_deterministic_bit_identical_across_runs` が担保。

---

## 2. テスト実行コマンド

```bash
uv run pytest tests/test_sequential_engine.py tests/test_changepoint.py
```

## 3. Red フェーズ実行結果 (現行 src/ 実装に対して)

```
10 failed, 36 passed
```

**失敗 10 件の内訳**:
- 持続ゲート未実装による即発火: N01 / N02 / N03 / B01 / B02 / B06 (engine 6 件)
- config 新規フィールド未実装 (AttributeError/TypeError): B03 / B04 / R02 (3 件)
- 相互作用の期待フレームシフト (R03 修正): test_phase_b_emergence_triggers_changepoint (1 件)

**通過している新規テスト (安全側縮退の担保, Red でも意図的に green)**:
- E01 (強度閾値未満の微小ピーク非計上) — 既存 `find_peaks(min_height_frac=0.05)` が 0.02 バンプを既に非検出。
- E02 (失敗フレームを跨ぐ決定論) — 既存の非有限継続 + 決定論が担保。
- E03 (フラットパターンの空縮退) — 既存 `_count_unmatched` 空縮退が担保。

## 4. 期待される失敗内容 (代表)

```
AttributeError: 'ChangepointConfig' object has no attribute 'new_peak_min_height_frac'
assert False is True   (records[10].changepoint is False を期待するが現行は True)
```

## 5. テストデータ設計 (合成データ・決定論)

- `_clean_a_series(n_frames)`: 全フレーム同一の単一相 A (相構成不変・完全適合) 列。Rwp/格子が不変で
  robust z の窓が MAD=0 縮退 → **rwp_jump / lattice_jump が非発火**し、changepoint の発火を new_peaks 指標へ単離。
- `_inject_peak(series, two_theta=50.0, frames=..., height_frac=...)`: 相 A/B のピーク位置から十分離れた
  2θ=50.0 (最近接 A ピーク 44.34 と 5.66° 離れ) へ相対高さ指定のガウスバンプを直接加算 → 未マッチ観測ピーク化。
- 相対高さは各フレームのクリーン最大強度 (単一相 A で ~1.0) に対する比。numpy 加算のみで乱数なし → ビット同一。

## 6. Green フェーズで実装すべき内容 (src/, 本フェーズ対象外)

1. `src/tsumugin/sequential/changepoint.py::ChangepointConfig` に既定値付き末尾追加:
   `new_peak_min_height_frac: float = 0.05` / `new_peak_persistence: int = 2`。
   純関数 `detect_changepoint` の判定式・シグネチャは不変に保つ。
2. `src/tsumugin/sequential/engine.py`:
   - `_count_unmatched` 相当を拡張し、未マッチ観測ピークの**位置 (2θ) と相対高さ**を取り出す
     (`unmatched_peaks(...).unmatched_observed` から位置/高さ)。
   - `run` の逐次状態に**位置ビンごと連続未マッチフレーム数**カウンタ (例: `dict[bin_key, int]`) を追加。
   - 処理: (a) `new_peak_min_height_frac` 未満の未マッチピークを除外、(b) 位置を決定論ビンにキー化 (2θ 量子化)、
     (c) 前フレーム継続ビンは +1 / 非継続ビンは 0/削除、(d) `>= new_peak_persistence` のビン数を集計し
     `new_unmatched` として `detect_changepoint` へ渡す。
   - 失敗フレーム (非有限) では持続カウンタを**据え置き** (更新しない) とし決定論を維持。
3. 決定論: ビンキー化・カウンタ更新順・dict 反復順を安定化し同一入力でビット同一。

## 7. 完了条件との対応

- [ ] 単発ノイズ 1 フレームで非発火 → TC-CP-N01 / B02(a) / B06
- [ ] 持続 M=2 以上で発火 → TC-CP-N02 / B01 / B02(b)
- [ ] 強度閾値未満の微小ピーク非計上 → TC-CP-E01
- [ ] 既存 changepoint/engine テスト無改変 green (相 B のみ R03 合意例外) → TC-CP-R01 / R04 / R03
