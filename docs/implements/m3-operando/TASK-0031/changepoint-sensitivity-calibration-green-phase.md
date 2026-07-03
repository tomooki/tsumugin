# TASK-0031 Green フェーズ記録: changepoint 感度較正 (Issue #3)

**機能名**: changepoint-sensitivity-calibration / **タスクID**: TASK-0031 / **要件名**: m3-operando
**フェーズ**: Green (最小実装でテストを通す) / **実装日時**: 2026-07-04

> すべてのパスはプロジェクトルートからの相対パス。

---

## 1. 実装方針

Red フェーズの 12 新規テスト + 1 修正テスト (相 B 発火 frame10→11) を通す最小実装を行った。
純関数 `detect_changepoint` の判定式・シグネチャは不変に保ち、強度/持続ゲートは engine 側で
`new_unmatched` を組み立てる段階に閉じた (設計 D7 / requirements §2)。

## 2. 実装コード

### 2.1 `src/tsumugin/sequential/changepoint.py` (ChangepointConfig 非破壊拡張)

`ChangepointConfig` に既定値付き末尾追加 (frozen 維持・純関数不変):

```python
new_peak_min_height_frac: float = 0.05  # 未マッチピークを計上する相対高さ下限 (engine 側適用)
new_peak_persistence: int = 2           # 同一位置ビンで連続 M フレーム継続時のみ計上 (M=1 は現行等価)
```

### 2.2 `src/tsumugin/sequential/engine.py` (位置ビンごと連続出現カウンタ + 強度/持続ゲート)

- モジュール定数 `_NEW_PEAK_BIN_WIDTH_DEG = 0.15` (2θ 位置ビン幅、match_tol_deg 相当)。
- `run()` 逐次状態に `persistence_counter: dict[int, int]` を追加 (rwp_history 等と同格のローカル状態)。
- 成功フレームで:
  1. `_unmatched_observed_peaks(...)` が未マッチ観測ピーク列 (位置+高さ, `tuple[Peak, ...]`) を返す
     (旧 `_count_unmatched` の「件数のみ」から拡張)。
  2. `_gate_new_unmatched(...)` が (a) 相対高さ >= `new_peak_min_height_frac` で強度ゲート、
     (b) `_position_bin(...)` で 2θ を決定論ビンへ量子化、(c) 継続ビン +1 / 非継続ビンはリセット
     (新 dict へ載せない)、(d) 連続 >= `new_peak_persistence` のビン数を `new_unmatched` として返す。
- 失敗フレーム (非有限 chi2) は既存どおり `continue` で履歴非更新のため、`persistence_counter` も
  据え置き (成功フレーム系列で連続性を評価)。

## 3. テスト実行結果

- 対象: `uv run pytest tests/test_changepoint.py tests/test_sequential_engine.py` → **46 passed** (Red の 10 failed を解消)。
- 全体: `uv run pytest` → **577 passed, 3 skipped**。
- Lint: `uvx ruff@latest check src tests` → **All checks passed!**

## 4. 完了条件との対応

- [x] 単発ノイズ 1 フレームで非発火 (TC-CP-N01 / B02(a) / B06)
- [x] 持続 M=2 以上で発火 (TC-CP-N02 / B01 / B02(b))
- [x] 強度閾値未満の微小ピーク非計上 (TC-CP-E01)
- [x] persistence=1 で即発火に縮退 (TC-CP-B03)
- [x] 既存 changepoint/engine テスト無改変 green (相 B のみ R03 合意例外 frame10→11) (TC-CP-R01/R04/R03)
- [x] 決定論維持 (カウンタも決定論・失敗フレーム跨ぎでビット同一) (TC-CP-E02 / B05)

## 5. 課題・改善点 (Refactor フェーズ候補)

- `_unmatched_observed_peaks` は `HypothesisTreeSearch` 内の未マッチ算出と類似構造 (simulate→find_peaks→
  match_score→unmatched_peaks)。共通化余地があるが、テスト独立性・依存方向に留意が必要。
- ビン幅定数 `_NEW_PEAK_BIN_WIDTH_DEG` と `SearchConfig.match_tol_deg` の関係は現状ハードコード。
  結合するか独立に保つかは要判断 (現状は独立の module 定数)。
- 強度ゲート (`new_peak_min_height_frac`) は既存 `find_peaks(min_height_frac=min_peak_height_frac)` と
  既定が同値 (0.05) で二重適用。役割分担 (別ゲート) は要件どおりだが冗長性の整理余地あり。
