# TASK-0015 FrameSeries + changepoint 検出 — TDD Red フェーズ記録

- **機能名**: FrameSeries + changepoint 検出 (frameseries-changepoint)
- **タスクID**: TASK-0015 / **要件名**: m2-sequential
- **作成日時**: 2026-07-03
- **フェーズ**: Red (失敗するテスト作成)
- **テストファイル**: `tests/test_sequential_series.py` (9 件) / `tests/test_changepoint.py` (14 件) = 23 件
- **対象実装 (未実装)**: `src/tsumugin/sequential/series.py` / `src/tsumugin/sequential/changepoint.py` / `src/tsumugin/sequential/__init__.py`

## 1. 作成したテストケース一覧 (23 件 = 正常系 9 / 異常系 6 / 境界値 8)

### FrameSeries (`tests/test_sequential_series.py`, 9 件)

| TC | テスト名 | 検証内容 | 信頼性 |
|---|---|---|---|
| TC-S-N01 | `test_frameseries_holds_fields_and_n_frames` | 全フィールド保持 + `n_frames == intensities.shape[0]` | 🔵 |
| TC-S-N02 | `test_frameseries_retains_external_channels` | `channels` に `ExternalChannel` 紐付け (REQ-006) | 🔵 |
| TC-S-N03 | `test_frameseries_axis_kind_and_values` | `axis_kind="time"` / `axis_values` 保持 | 🔵 |
| TC-S-E01 | `test_frameseries_column_mismatch_raises` | 列数 != two_theta 長 → `ValueError` (完了条件①) | 🟡 |
| TC-S-E02 | `test_frameseries_axis_values_length_mismatch_raises` | 非空 axis_values 長 != n_frames → `ValueError` | 🟡 |
| TC-S-E03 | `test_frameseries_is_frozen` | frozen 再代入で `FrozenInstanceError` | 🔵 |
| TC-S-B01 | `test_frameseries_single_frame` | 単一フレーム `n_frames==1` (EDGE-101) | 🔵 |
| TC-S-B02 | `test_frameseries_empty_axis_values_is_index` | 空 axis_values は index 軸で検証免除 | 🔵 |
| TC-S-B03 | `test_frameseries_exact_shape_ok` | 形状ちょうど一致で構築成功 (許可側境界) | 🔵 |

### changepoint (`tests/test_changepoint.py`, 14 件 / parametrize 込み 15 items)

| TC | テスト名 | 検証内容 | 信頼性 |
|---|---|---|---|
| TC-C-N01 | `test_rwp_jump_alone_triggers` | Rwp 単独発火 `reasons==("rwp_jump",)` (TC-102-06) | 🔵 |
| TC-C-N02 | `test_lattice_jump_alone_triggers` | 格子差分単独発火 `("lattice_jump",)` | 🔵 |
| TC-C-N03 | `test_new_peaks_alone_triggers` | 新規ピーク単独発火 `("new_peaks",)` | 🟡 |
| TC-C-N04 | `test_smooth_series_no_trigger` | 滑らかな系列で `triggered=False` (TC-102-04) | 🔵 |
| TC-C-N05 | `test_multiple_indicators_or_combined` | 3 指標 OR で reasons 複数 | 🔵 |
| TC-C-N06 | `test_signal_fields_populated` | signal 各フィールド埋まる `frame_index==5` | 🟡 |
| TC-C-E01 | `test_warmup_below_window_no_detection` | warm-up (履歴<window) 非検出 (完了条件④) | 🟡 |
| TC-C-E02 | `test_mad_zero_degeneracy_no_false_trigger` | MAD=0 縮退で誤発火なし・isfinite (完了条件⑥) | 🟡 |
| TC-C-E03 | `test_changepoint_dataclasses_are_frozen` | config/signal frozen | 🔵 |
| TC-C-B01 | `test_history_exactly_window_detects` | 履歴長==window で検出実行 (warm-up 許可側) | 🟡 |
| TC-C-B02 | `test_z_exactly_threshold_not_triggered` | z==閾値は非発火 (strict `>`) | 🟡 |
| TC-C-B03 | `test_new_peaks_threshold_boundary` | new_unmatched 下限境界 (parametrize 1/0) | 🔵 |
| TC-C-B04 | `test_deterministic_bit_identical` | 決定論ビット同一 `sig1==sig2` (REQ-402) | 🔵 |
| TC-C-B05 | `test_changepoint_config_defaults` | 既定値 window=5/z=5.0/min=1 + frozen | 🔵 |

## 2. Red フェーズで確定した実装契約 (Green への要求事項)

Red の期待値計算で以下を **修正 z スコア `0.6745·(x−median)/MAD`** (MAD=`median(|x−median|)`) を基準に較正・固定した:

- **窓**: 末尾 `window` 要素。median/MAD を窓全体で計算し末尾要素 (現フレーム) の z を評価。
- **閾値判定**: `z > z_threshold` (**strict `>`**、dataflow「z_rwp > 5」)。
- **z_lattice**: 格子 a/b/c 各軸の**フレーム間差分列** (`np.diff`) に robust z を適用し、**各軸の最大絶対 z** を採る。生値ではなく差分 (線形熱膨張の誤発火回避 — TC-C-N04/N02)。存在キーのみ集約 (`sorted` でキー順固定 → 決定論)。
- **new_peaks**: `new_unmatched >= config.min_new_peaks` の**単純カウント閾値** (z 非依存)。
- **warm-up**: `len(rwp_history) < config.window` で `triggered=False, reasons=(), z_rwp=0.0, z_lattice=0.0` に縮退 (例外化しない)。
- **MAD=0 縮退**: 該当指標の z を `0.0` に縮退し発火させない。0 除算ガードを MAD==0 判定で先行。inf/nan を漏らさない。
- **frame_index**: `len(rwp_history) - 1`。
- **reasons 順序**: `rwp_jump` → `lattice_jump` → `new_peaks` の評価順で追加 (決定論)。
- **形状エラー型**: `FrameSeries.__post_init__` で `ValueError` (既存 `backends/base.py:61` 慣習)。属性設定を伴わず raise のみ。空 `axis_values` は検証免除。

### 較正した代表 z 値 (numpy で検算済み)

- `SPIKE_RWP` 末尾 z_rwp ≈ **201.68** (> 5 発火) / `FLAT_RWP` 末尾 z_rwp = **0.0** (末尾が窓 median と一致)。
- `JUMP_LATTICE` 差分 z_lattice ≈ **168.29** (> 5 発火) / `FLAT_LATTICE`・`LINEAR_LATTICE` は差分一定 → MAD=0 → z_lattice = **0.0**。
- TC-C-B02 境界: 窓 `[9.8,9.9,10.0,10.1,x]` は median=10.0 / MAD≈0.1。`x=10.74128984432913` → z=4.9999999999999 (≤5 非発火) / `x=10.756115641215713` → z=5.1 (>5 発火)。round-trip の浮動小数揺らぎを避けるため z≤5.0 側へ較正済み。

## 3. 期待される失敗内容 (確認済み)

```
$ uv run pytest tests/test_sequential_series.py tests/test_changepoint.py
E   ModuleNotFoundError: No module named 'tsumugin.sequential'
ERROR tests/test_sequential_series.py
ERROR tests/test_changepoint.py
!!! Interrupted: 2 errors during collection !!!
2 errors in 0.77s
```

対象モジュール未実装のため import が collection 時に失敗し全 23 件がエラー(=失敗)。Red フェーズとして正当。
`ruff check` (line-length 100) は両ファイルとも `All checks passed!`。

## 4. Green フェーズで実装すべき内容

1. `src/tsumugin/sequential/__init__.py` — `FrameSeries` / `ChangepointConfig` / `ChangepointSignal` / `detect_changepoint` を re-export (アルファベット順 `__all__`)。
2. `src/tsumugin/sequential/series.py` — `FrameSeries` (frozen dataclass, `n_frames` プロパティ, `__post_init__` 形状検証)。
3. `src/tsumugin/sequential/changepoint.py` — `ChangepointConfig` / `ChangepointSignal` (frozen) と §2 の統計契約を満たす純関数 `detect_changepoint`。docstring に上記 🟡 確定事項の根拠を残す。
