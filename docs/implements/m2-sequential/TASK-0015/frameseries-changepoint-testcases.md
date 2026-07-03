# TASK-0015 FrameSeries + changepoint 検出 — TDD テストケース定義書

- **機能名**: FrameSeries + changepoint 検出 (frameseries-changepoint)
- **タスクID**: TASK-0015
- **要件名**: m2-sequential
- **対象実装**:
  - `src/tsumugin/sequential/series.py` (新規) — `FrameSeries` (frozen dataclass + `n_frames` + 形状検証)
  - `src/tsumugin/sequential/changepoint.py` (新規) — `ChangepointConfig` / `ChangepointSignal` / `detect_changepoint()`
  - `src/tsumugin/sequential/__init__.py` (新規) — re-export
- **テストファイル**: `tests/test_sequential_series.py` (新規) / `tests/test_changepoint.py` (新規)
- **書式の範**: `tests/test_model_m2.py` (TASK-0011: frozen 検証 / `pytest.approx` / 【】コメント / 🔵🟡 注記)

> **【信頼性レベル凡例】**
> - 🔵 **青信号**: 要件定義書・設計文書 (`interfaces.py` / `design-interview.md` / `dataflow.md` / `acceptance-criteria.md`) を参考にほぼ推測していない
> - 🟡 **黄信号**: 要件・設計から妥当な推測
> - 🔴 **赤信号**: 要件・設計にない推測

## テストケース一覧サマリー

| 区分 | FrameSeries (`test_sequential_series.py`) | changepoint (`test_changepoint.py`) | 小計 |
|------|------|------|------|
| 正常系 | 3 (TC-S-N01〜03) | 6 (TC-C-N01〜06) | 9 |
| 異常系 (縮退・非破壊) | 3 (TC-S-E01〜03) | 3 (TC-C-E01〜03) | 6 |
| 境界値 | 3 (TC-S-B01〜03) | 5 (TC-C-B01〜05) | 8 |
| **合計** | **9** | **14** | **23** |

信頼性内訳: 🔵 15 / 🟡 8 / 🔴 0

### 完了条件・受け入れ基準カバレッジ

| 完了条件 / 受け入れ基準 | 対応ケース |
|---|---|
| ① 形状不一致で明示エラー 🟡 | TC-S-E01 (列数) / TC-S-E02 (フレーム数) |
| ② 各指標単独で triggered=True 🔵 *TC-102-06* | TC-C-N01 (rwp) / TC-C-N02 (lattice) / TC-C-N03 (new_peaks) |
| ③ 滑らかな系列で triggered=False 🔵 *TC-102-04* | TC-C-N04 |
| ④ warm-up では検出しない 🟡 | TC-C-E01 / TC-C-B01 (境界) |
| ⑤ reasons に発火指標名 (説明可能性) 🔵 | TC-C-N01/02/03/05/06 |
| ⑥ MAD=0 縮退で誤発火しない 🟡 | TC-C-E02 |
| 決定論 (REQ-402) 🔵 | TC-C-B04 |
| 契約 (frozen / 既定値) 🔵 | TC-S-E03 / TC-C-E03 / TC-C-B05 |

---

## 0. 共通テストデータ・前提

- 🔵 **観測グリッド**: `tt = np.arange(15.0, 80.0, 0.02)` (`n_points == len(tt)`)。`intensities` は `(n_frames, n_points)` の 2D 配列 (`np.stack` / `np.zeros((n_frames, n_points))` で構築)。
- 🔵 **ExternalChannel (TASK-0011)**: `from tsumugin.model import ExternalChannel`。`ExternalChannel("temperature", {0: 300.0, 1: 310.0})` を `FrameSeries.channels` に渡す。
- 🔵 **import 経路**: 本タスクは対象モジュールを直 import (`from tsumugin.sequential.series import FrameSeries` / `from tsumugin.sequential.changepoint import ChangepointConfig, ChangepointSignal, detect_changepoint`)。`sequential/__init__.py` re-export の検証は TC で併せて確認可。
- 🟡 **changepoint 履歴の構築規約 (Red で exact z を較正)**: `detect_changepoint` に渡す履歴は末尾が現フレーム。以下の代表パターンを用いる:
  - **flat_rwp** `= [10.0, 10.1, 9.95, 10.05, 9.98, 10.02]` — 微小ノイズの滑らかな Rwp (現フレームが窓の median±数 MAD 以内 → z < 5)。
  - **spike_rwp** `= [10.0, 10.1, 9.9, 10.0, 10.05, 25.0]` — 末尾に急上昇 (z ≫ 5)。
  - **flat_lattice** `= [{"a": 5.0}] * 6` — 完全同値 → 差分全 0 → MAD=0 縮退 (z_lattice=0, 非発火)。
  - **linear_lattice** `= [{"a": 5.00 + 0.01*i} for i in range(6)]` — 線形熱膨張 → 差分一定 0.01 → MAD=0 → z_lattice=0 (非発火, TC-102-04 の要)。
  - **jump_lattice** `= [{"a":5.0},{"a":5.001},{"a":5.002},{"a":5.001},{"a":5.0},{"a":5.5}]` — 末尾で急ジャンプ (差分 0.5 vs 微小ベースライン → z ≫ 5)。
- 🔵 **数値比較の使い分け**: 決定論 (ビット同一) は `==`、z 値等の物理量近似は `pytest.approx`。`triggered` / `reasons` / `frame_index` は `==`。
- 🟡 **窓包含・z 定義・境界 (`>` か `>=`)・a/b/c 集約は Red で確定**: modified z-score `0.6745·(x−median)/MAD`、窓 = 末尾 `window` 要素、閾値判定は `z > z_threshold` (strict、dataflow「z_rwp > 5」)、`z_lattice` は a/b/c の最大絶対 z、`new_peaks` は `new_unmatched >= min_new_peaks`。各値は Red の期待値計算で固定し docstring に根拠を残す。

---

## 1. 正常系テストケース（基本的な動作）

### TC-S-N01: FrameSeries 明示構築で全フィールド保持 + n_frames が行数を返す

- **テスト名**: `test_frameseries_holds_fields_and_n_frames`
  - **何をテストするか**: `FrameSeries` を全フィールド明示で生成し、各属性と `n_frames == intensities.shape[0]` を確認。
  - **期待される動作**: frozen 値オブジェクトとして生成され、`n_frames` プロパティが強度行列の行数を返す。
- **入力値**: `tt` (n_points), `intensities = np.zeros((3, len(tt)))`, `axis_values=(300.0, 310.0, 320.0)`, `axis_kind="temperature"`, `channels=()`。
  - **入力データの意味**: 3 フレームの温度シーケンシャル入力という代表ケース。
- **期待される結果**: `fs.n_frames == 3`、`fs.axis_kind == "temperature"`、`fs.axis_values == (300.0, 310.0, 320.0)`、`fs.two_theta is tt`、`fs.intensities.shape == (3, len(tt))`。
  - **期待結果の理由**: interfaces.py L62-73 のフィールド定義と `n_frames = intensities.shape[0]` に一致。
- **テストの目的**: `FrameSeries` の基本契約 (保持 + n_frames) を確認。
  - **確認ポイント**: `n_frames` が `axis_values` 長ではなく `intensities` 行数由来であること。
- 🔵 信頼性レベル: interfaces.py L62-73 に直接依拠。

### TC-S-N02: channels に ExternalChannel を紐付けて保持する (REQ-006)

- **テスト名**: `test_frameseries_retains_external_channels`
  - **何をテストするか**: `channels` に温度チャネルを渡すと `tuple[ExternalChannel, ...]` として保持され `value_for` が引けること。
  - **期待される動作**: TASK-0011 の `ExternalChannel` がそのまま格納される。
- **入力値**: `channels=(ExternalChannel("temperature", {0: 300.0, 1: 310.0}),)`, `intensities=np.zeros((2, len(tt)))`, `axis_values=(300.0, 310.0)`。
  - **入力データの意味**: 高温モードで温度ログをフレームへ同期する中核経路 (REQ-006 / FR-321)。
- **期待される結果**: `len(fs.channels) == 1`、`fs.channels[0].value_for(1) == pytest.approx(310.0)`、`fs.channels[0].kind == "temperature"`。
  - **期待結果の理由**: REQ-006 (ExternalChannel をフレームへ紐付け) / interfaces.py L72。
- **テストの目的**: FrameSeries ↔ ExternalChannel の結線を確認。
  - **確認ポイント**: 既存モデル (TASK-0011) を無改変で再利用できること。
- 🔵 信頼性レベル: REQ-006 / interfaces.py L72 / `model/channel.py` に直接依拠。

### TC-S-N03: axis_kind と axis_values の既定/明示が保持される

- **テスト名**: `test_frameseries_axis_kind_and_values`
  - **何をテストするか**: `axis_kind="time"` と対応 `axis_values` を明示した場合の保持を確認。
  - **期待される動作**: Literal 軸種別と float タプル軸値が独立に保持される。
- **入力値**: `intensities=np.zeros((4, len(tt)))`, `axis_values=(0.0, 1.0, 2.0, 3.0)`, `axis_kind="time"`。
  - **入力データの意味**: 時間軸シーケンシャル (§4 sequence_axis) の代表。
- **期待される結果**: `fs.axis_kind == "time"`、`fs.axis_values == (0.0, 1.0, 2.0, 3.0)`、`fs.n_frames == 4`。
  - **期待結果の理由**: interfaces.py L70-71。
- **テストの目的**: 軸メタデータの保持を確認。
  - **確認ポイント**: axis_values 長と n_frames が整合する正常ケース。
- 🔵 信頼性レベル: interfaces.py L70-71 に直接依拠。

### TC-C-N01: Rwp 跳ねのみで triggered=True・reasons=("rwp_jump",) (TC-102-06)

- **テスト名**: `test_rwp_jump_alone_triggers`
  - **何をテストするか**: Rwp 系列末尾のみ急上昇し、格子は完全同値・新規ピーク 0 のとき、`rwp_jump` 単独で発火すること。
  - **期待される動作**: `z_rwp > z_threshold`、他 2 指標は非発火。
- **入力値**: `rwp_history=spike_rwp`、`lattice_history=flat_lattice`、`new_unmatched=0`、既定 `ChangepointConfig()`。
  - **入力データの意味**: 残差だけが跳ねる相転移初期 (格子はまだ動かず新相ピーク未検出) の代表。
- **期待される結果**: `sig.triggered is True`、`sig.reasons == ("rwp_jump",)`、`sig.z_rwp > 5.0`、`sig.z_lattice == pytest.approx(0.0)` (flat_lattice → MAD=0 縮退)、`sig.new_unmatched == 0`。
  - **期待結果の理由**: dataflow.md 複合指標 (B→E `z_rwp>5`) / REQ-003(a) / 完了条件② / TC-102-06。
- **テストの目的**: Rwp 指標の単独検出と reasons の説明可能性を確認。
  - **確認ポイント**: 格子・新規ピークが混入して false-positive にならないこと。
- 🔵 信頼性レベル: TC-102-06 / dataflow.md / REQ-003 に直接依拠 (exact z は Red 較正 🟡)。

### TC-C-N02: 格子ジャンプのみで triggered=True・reasons=("lattice_jump",) (TC-102-06)

- **テスト名**: `test_lattice_jump_alone_triggers`
  - **何をテストするか**: 格子 a のフレーム間差分が末尾で急変し、Rwp 滑らか・新規ピーク 0 のとき、`lattice_jump` 単独で発火すること。
  - **期待される動作**: `z_lattice > z_threshold`、他 2 指標は非発火。
- **入力値**: `rwp_history=flat_rwp`、`lattice_history=jump_lattice`、`new_unmatched=0`、既定設定。
  - **入力データの意味**: 格子定数が不連続にジャンプする構造相転移の代表。
- **期待される結果**: `sig.triggered is True`、`sig.reasons == ("lattice_jump",)`、`sig.z_lattice > 5.0`、`sig.z_rwp <= 5.0`、`sig.new_unmatched == 0`。
  - **期待結果の理由**: dataflow.md (C→F `z_lattice>5`) / REQ-003(b) — 生値でなく差分に適用。
- **テストの目的**: 格子差分指標の単独検出を確認。
  - **確認ポイント**: 差分ベース (raw 値でなく) で判定していること (TC-C-N04 と対)。
- 🔵 信頼性レベル: TC-102-06 / dataflow.md「格子 a/b/c のフレーム間差分」に直接依拠 (集約規則は Red 🟡)。

### TC-C-N03: 新規ピークのみで triggered=True・reasons=("new_peaks",) (TC-102-06)

- **テスト名**: `test_new_peaks_alone_triggers`
  - **何をテストするか**: Rwp 滑らか・格子同値で新規未マッチピークだけが下限以上のとき、`new_peaks` 単独で発火すること。
  - **期待される動作**: `new_unmatched >= min_new_peaks` で発火、z 系は非発火。
- **入力値**: `rwp_history=flat_rwp`、`lattice_history=flat_lattice`、`new_unmatched=2`、既定設定 (`min_new_peaks=1`)。
  - **入力データの意味**: 新相の未知ピークが現れ始めた瞬間 (残差/格子はまだ動かない) の代表。
- **期待される結果**: `sig.triggered is True`、`sig.reasons == ("new_peaks",)`、`sig.new_unmatched == 2`、`sig.z_rwp <= 5.0`、`sig.z_lattice == pytest.approx(0.0)`。
  - **期待結果の理由**: dataflow.md (D→G) / REQ-003(c) / interfaces.py `min_new_peaks`。
- **テストの目的**: 新規ピーク指標の単独検出を確認 (カウント閾値解釈)。
  - **確認ポイント**: `new_peaks` は z を持たず `new_unmatched >= 1` の単純判定であること (dataflow「z 超過」注記との解釈確定)。
- 🟡 信頼性レベル: TC-102-06 は 🔵 だが「new_peaks の z 非依存カウント解釈」は妥当な推測 (requirements §2.4 / note.md §6)。

### TC-C-N04: 滑らかな系列で triggered=False・reasons=() (TC-102-04)

- **テスト名**: `test_smooth_series_no_trigger`
  - **何をテストするか**: Rwp が微小ノイズで安定、格子が線形膨張、新規ピーク 0 の系列で変化点が検出されないこと。
  - **期待される動作**: 全 3 指標が閾値未満 → `triggered=False`。
- **入力値**: `rwp_history=flat_rwp`、`lattice_history=linear_lattice`、`new_unmatched=0`、既定設定。
  - **入力データの意味**: 変化のない安定加熱区間 (線形熱膨張は「正常」であり変化点ではない) の代表。
- **期待される結果**: `sig.triggered is False`、`sig.reasons == ()`、`sig.z_lattice == pytest.approx(0.0)` (線形膨張 → 差分一定 → MAD=0)、`sig.z_rwp <= 5.0`。
  - **期待結果の理由**: TC-102-04 (変化のない滑らかなシーケンスで changepoint ゼロ)。差分ベース判定により線形トレンドを誤発火させない。
- **テストの目的**: false-positive 抑制 (最重要) を確認。
  - **確認ポイント**: 線形膨張 (raw 値は毎フレーム変化) を「変化点」と誤検出しないこと — 差分+MAD=0 縮退の正しさ。
- 🔵 信頼性レベル: 受け入れ基準 TC-102-04 に直接依拠。

### TC-C-N05: 複数指標同時発火 → reasons に複数入り triggered=True (OR)

- **テスト名**: `test_multiple_indicators_or_combined`
  - **何をテストするか**: Rwp 跳ね + 格子ジャンプ + 新規ピークが同時に起きたとき、`reasons` に複数指標が入り OR で発火すること。
  - **期待される動作**: `triggered=True`、`reasons` が発火した全指標を含む。
- **入力値**: `rwp_history=spike_rwp`、`lattice_history=jump_lattice`、`new_unmatched=3`、既定設定。
  - **入力データの意味**: 明確な相転移フレーム (3 指標すべてが同時に動く) の代表。
- **期待される結果**: `sig.triggered is True`、`set(sig.reasons) == {"rwp_jump", "lattice_jump", "new_peaks"}`、`len(sig.reasons) == 3`。順序は発生順で決定論的 (Red で固定)。
  - **期待結果の理由**: dataflow.md「E/F/G --or--> H」(3 指標 OR)。
- **テストの目的**: OR 結合と複数 reasons の集約を確認。
  - **確認ポイント**: 単一指標に潰れず全発火指標が記録されること (説明可能性)。
- 🔵 信頼性レベル: dataflow.md 複合指標 OR に直接依拠 (reasons 順序規則は Red 🟡)。

### TC-C-N06: ChangepointSignal のフィールドが正しく設定される (説明可能性 / 完了条件⑤)

- **テスト名**: `test_signal_fields_populated`
  - **何をテストするか**: `frame_index` / `z_rwp` / `z_lattice` / `new_unmatched` / `reasons` が判定内容と整合して埋まること。
  - **期待される動作**: 全フィールドが判定過程の定量値を反映 (REQ-402 説明可能性)。
- **入力値**: `rwp_history=spike_rwp` (長さ 6)、`lattice_history=flat_lattice`、`new_unmatched=0`。
  - **入力データの意味**: 発火時の signal 内容を検査する代表。
- **期待される結果**: `sig.frame_index == 5` (`len(rwp_history)-1`)、`sig.z_rwp > 5.0`、`sig.new_unmatched == 0`、`sig.reasons == ("rwp_jump",)`。`ChangepointSignal` は frozen dataclass。
  - **期待結果の理由**: interfaces.py L90-99 (説明可能性フィールド) / 完了条件⑤。
- **テストの目的**: signal の説明可能性 (どの指標がどれだけ逸脱したか) を確認。
  - **確認ポイント**: `frame_index` が履歴末尾由来で決定論的であること。
- 🟡 信頼性レベル: interfaces.py L90-99 は 🔵 だが `frame_index = len-1` の由来は妥当な推測 (Red で確定)。

---

## 2. 異常系テストケース（縮退・エラーハンドリング・非破壊契約）

> **M0 規約**: ドメイン的縮退 (warm-up・MAD=0) は例外化せず縮退値に一元化。一方 `FrameSeries` の構造的形状不一致は明示エラー (器の契約違反)。

### TC-S-E01: intensities 列数 ≠ two_theta 長 → 明示エラー (完了条件①)

- **テスト名**: `test_frameseries_column_mismatch_raises`
  - **エラーケースの概要**: `intensities.shape[1]` (測定点数) が `len(two_theta)` と一致しない構築。
  - **エラー処理の重要性**: 強度行列とグリッドの不整合は後続の全フレーム解析を静かに壊すため、生成時点で弾く。
- **入力値**: `two_theta=np.arange(15.0, 80.0, 0.02)` (n_points), `intensities=np.zeros((3, 10))` (列数 10 ≠ n_points)。
  - **不正な理由**: 各フレームの強度長がグリッド長と一致しない (物理的に対応不能)。
  - **実際の発生シナリオ**: 別グリッドで測定したフレームを誤って束ねる。
- **期待される結果**: 生成時に明示エラー (`pytest.raises(...)`) が送出され、メッセージに shape 不一致の旨を含む。副作用なし。
  - **エラーメッセージの内容**: 期待 shape と実 shape を示す (例 `intensities columns (10) != two_theta length (...)`)。
  - **システムの安全性**: 不整合な `FrameSeries` インスタンスが存在し得ないことを型/生成レベルで担保。
- **テストの目的**: 形状検証 (列方向) の明示エラーを確認。
  - **品質保証の観点**: 完了条件①の中核。縮退 None ではなく明示エラーであること。
- 🟡 信頼性レベル: 完了条件① (🟡) に依拠。エラー型 (`ValueError` 想定) は Red で確定。

### TC-S-E02: axis_values 非空で長さ ≠ n_frames → 明示エラー (完了条件①)

- **テスト名**: `test_frameseries_axis_values_length_mismatch_raises`
  - **エラーケースの概要**: `axis_values` が非空だが `len(axis_values) != intensities.shape[0]`。
  - **エラー処理の重要性**: 軸値とフレームのずれはトラジェクトリの軸ラベルを恒久的に崩す。
- **入力値**: `intensities=np.zeros((3, len(tt)))`, `axis_values=(300.0, 310.0)` (長さ 2 ≠ 3 フレーム)。
  - **不正な理由**: フレーム軸値の数がフレーム数と一致しない。
  - **実際の発生シナリオ**: 温度ログの行数と測定フレーム数の食い違い。
- **期待される結果**: 生成時に明示エラー。メッセージに axis_values 長と n_frames の不一致を含む。
  - **エラーメッセージの内容**: 例 `axis_values length (2) != n_frames (3)`。
  - **システムの安全性**: 軸整合が保証された `FrameSeries` のみ生成される。
- **テストの目的**: 形状検証 (フレーム軸方向) の明示エラーを確認。
  - **品質保証の観点**: 完了条件① (interfaces.py「axis_values と intensities」)。
- 🟡 信頼性レベル: 完了条件① / interfaces.py L69-70 に依拠 (妥当な推測)。

### TC-S-E03: FrameSeries は frozen で再代入不可

- **テスト名**: `test_frameseries_is_frozen`
  - **エラーケースの概要**: 生成後にフィールドを再代入する誤用。
  - **エラー処理の重要性**: 不変値オブジェクト (P2) の同一性・共有安全性を守る。
- **入力値**: 正常な `FrameSeries` の `axis_kind` へ再代入を試みる。
  - **不正な理由**: frozen dataclass はフィールド再代入を禁止。
  - **実際の発生シナリオ**: 解析中に軸種別を後から書き換える誤用。
- **期待される結果**: `dataclasses.FrozenInstanceError` が送出される。
  - **エラーメッセージの内容**: dataclass 標準メッセージ。
  - **システムの安全性**: 生成後の改変不能を型レベルで担保。
- **テストの目的**: 非破壊・不変性 (P2 / CLAUDE.md) を確認。
  - **品質保証の観点**: 共有された FrameSeries が事後改変されない。
- 🔵 信頼性レベル: CLAUDE.md frozen 規約 / test_model_m2.py の frozen 検証パターンに直接依拠。

### TC-C-E01: warm-up (履歴 < window) では検出しない (完了条件④)

- **テスト名**: `test_warmup_below_window_no_detection`
  - **エラーケースの概要**: 履歴長が `window` 未満の序盤フレーム。
  - **エラー処理の重要性**: 統計母数が足りない序盤で誤検出すると逐次探索が無駄に走る。
- **入力値**: `rwp_history=[10.0, 30.0, 8.0]` (長さ 3 < window 5、末尾は大きく跳ねている)、`lattice_history` 同長、`new_unmatched=0`、既定 `ChangepointConfig(window=5)`。
  - **不正な理由**: 窓を満たさない (縮退であり不正入力ではない)。
  - **実際の発生シナリオ**: シーケンス最初の数フレーム。
- **期待される結果**: 例外なし。`sig.triggered is False`、`sig.reasons == ()`、`sig.z_rwp == pytest.approx(0.0)`、`sig.z_lattice == pytest.approx(0.0)`。inf/nan なし。
  - **エラーメッセージの内容**: なし (縮退で表現)。
  - **システムの安全性**: 末尾が跳ねていても窓未満なら発火しない (母数不足の安全側)。
- **テストの目的**: warm-up スキップの非例外縮退を確認。
  - **品質保証の観点**: 完了条件④ / D-Q3「warm-up (W 未満) は検出スキップ」。
- 🟡 信頼性レベル: 完了条件④ / design-interview D-Q3 に依拠 (妥当な推測)。

### TC-C-E02: MAD=0 縮退 (全同値履歴) で誤発火しない (完了条件⑥)

- **テスト名**: `test_mad_zero_degeneracy_no_false_trigger`
  - **エラーケースの概要**: 窓内の値が全同値で MAD=0 → robust z が 0 除算になる。
  - **エラー処理の重要性**: 0 除算で inf/nan が発生すると `triggered`/下流へ伝播し全滅する。
- **入力値**: `rwp_history=[10.0]*6` (全同値)、`lattice_history=flat_lattice` (全同値)、`new_unmatched=0`、既定設定。
  - **不正な理由**: 分散ゼロで z が定義できない縮退。
  - **実際の発生シナリオ**: 完全に安定した平衡区間 / シミュレーションの定数入力。
- **期待される結果**: 例外なし・inf/nan なし。`sig.triggered is False`、`sig.z_rwp == pytest.approx(0.0)`、`sig.z_lattice == pytest.approx(0.0)`、`math.isfinite(sig.z_rwp)` と `math.isfinite(sig.z_lattice)` が True。
  - **エラーメッセージの内容**: なし。
  - **システムの安全性**: 全同値 = 変化なし → 発火しない (安全側縮退)。
- **テストの目的**: MAD=0 縮退ガードを確認。
  - **品質保証の観点**: 完了条件⑥ / CLAUDE.md「非有限値を漏らさない」(M1 教訓)。
- 🟡 信頼性レベル: 完了条件⑥ に依拠。ガード方針 (z=0.0) は妥当な推測 (Red で docstring 根拠化)。

### TC-C-E03: ChangepointConfig / ChangepointSignal は frozen で再代入不可

- **テスト名**: `test_changepoint_dataclasses_are_frozen`
  - **エラーケースの概要**: 設定/結果 dataclass のフィールド再代入。
  - **エラー処理の重要性**: 設定・判定結果の不変性 (決定論の前提)。
- **入力値**: `ChangepointConfig().window` および `detect_changepoint(...)` 戻り値の `triggered` へ再代入を試みる。
  - **不正な理由**: frozen dataclass は再代入禁止。
  - **実際の発生シナリオ**: 設定を実行中に書き換える誤用。
- **期待される結果**: 両者とも `FrozenInstanceError`。
  - **エラーメッセージの内容**: dataclass 標準メッセージ。
  - **システムの安全性**: 設定/結果の事後改変不能。
- **テストの目的**: frozen 契約 (interfaces.py の `@dataclass(frozen=True)`) を確認。
  - **品質保証の観点**: 非破壊・決定論の構造的担保。
- 🔵 信頼性レベル: interfaces.py L81/L90 (frozen) / test_model_m2.py パターンに直接依拠。

---

## 3. 境界値テストケース（窓境界・閾値境界・決定論・既定値）

### TC-S-B01: 単一フレーム FrameSeries (n_frames=1)

- **テスト名**: `test_frameseries_single_frame`
  - **境界値の意味**: フレーム軸の最小非空ケース (1 フレーム)。
  - **境界値での動作保証**: 1 行の強度行列でも生成でき `n_frames==1`。
- **入力値**: `intensities=np.zeros((1, len(tt)))`, `axis_values=(300.0,)`, `axis_kind="temperature"`。
  - **境界値選択の根拠**: EDGE-101 (単一フレーム) の入力側最小ケース。
  - **実際の使用場面**: 静的単一パターン解析を逐次 API で扱う。
- **期待される結果**: `fs.n_frames == 1`、生成成功、形状検証を通過。
  - **境界での正確性**: 2D 形状 `(1, n_points)` が 1D と誤解されない。
  - **一貫した動作**: TC-S-N01 (複数フレーム) と同一検証ロジック。
- **テストの目的**: 最小フレーム数での構築を確認。
  - **堅牢性の確認**: `intensities.shape[0]` が 1 を返すこと。
- 🔵 信頼性レベル: EDGE-101 / interfaces.py に依拠。

### TC-S-B02: axis_values 空 (既定) → index 軸として検証免除

- **テスト名**: `test_frameseries_empty_axis_values_is_index`
  - **境界値の意味**: `axis_values` の既定 `()` (フレーム軸値なし)。
  - **境界値での動作保証**: 空軸値では長さ検証をスキップし、`n_frames` は intensities 由来。
- **入力値**: `intensities=np.zeros((5, len(tt)))`、`axis_values` 省略 (既定 `()`)、`axis_kind` 省略 (既定 `"index"`)。
  - **境界値選択の根拠**: interfaces.py「空なら index」の縮退境界。
  - **実際の使用場面**: 軸メタデータのない生フレーム列。
- **期待される結果**: 生成成功、`fs.axis_values == ()`、`fs.axis_kind == "index"`、`fs.n_frames == 5`。エラーにならない。
  - **境界での正確性**: 空 axis_values は「長さ不一致」と誤判定されない (TC-S-E02 と対)。
  - **一貫した動作**: 非空 axis_values のみ長さ検証が働く。
- **テストの目的**: 空軸値の検証免除を確認。
  - **堅牢性の確認**: 既定値のみでの構築 (REQ 非破壊追加の前提)。
- 🔵 信頼性レベル: interfaces.py L70「空なら index」に直接依拠。

### TC-S-B03: 形状ちょうど一致で構築成功 (検証の許可側境界)

- **テスト名**: `test_frameseries_exact_shape_ok`
  - **境界値の意味**: `intensities.shape == (n_frames, len(two_theta))` かつ `len(axis_values) == n_frames` のちょうど一致。
  - **境界値での動作保証**: 検証の「不一致で raise」の裏返し (一致で成功)。
- **入力値**: `two_theta` (n_points), `intensities=np.zeros((3, n_points))`, `axis_values=(0.0, 1.0, 2.0)`。
  - **境界値選択の根拠**: 検証ロジックの許可側 (off-by-one を検出)。
  - **実際の使用場面**: 正しく整形された標準入力。
- **期待される結果**: 例外なしで生成、`fs.n_frames == 3`。
  - **境界での正確性**: 「等しい」を「不一致」と誤判定しない。
  - **一貫した動作**: TC-S-E01/E02 (不一致で raise) と境界を挟んで対称。
- **テストの目的**: 検証境界の許可側を固定。
  - **堅牢性の確認**: 検証条件が `!=` (厳密) であること。
- 🔵 信頼性レベル: 完了条件① / interfaces.py に依拠。

### TC-C-B01: 履歴長ちょうど window (=5) で検出が実行される (warm-up 境界の許可側)

- **テスト名**: `test_history_exactly_window_detects`
  - **境界値の意味**: `len(history) == window` (warm-up スキップの境界のちょうど超過側)。
  - **境界値での動作保証**: 履歴長が窓に達したフレームで検出が有効化される。
- **入力値**: `rwp_history=[10.0, 10.1, 9.9, 10.0, 30.0]` (長さ 5 == window、末尾跳ね)、`lattice_history=flat_lattice[:5]`、`new_unmatched=0`、`ChangepointConfig(window=5)`。
  - **境界値選択の根拠**: `< window` はスキップ / `== window` は検出、の境界を固定。
  - **実際の使用場面**: warm-up を抜けた最初の判定フレーム。
- **期待される結果**: warm-up スキップされず判定実行。末尾の跳ねで `sig.triggered is True`、`"rwp_jump" in sig.reasons`。
  - **境界での正確性**: warm-up 条件が `len < window` (`<=` でない) であること。
  - **一貫した動作**: TC-C-E01 (長さ 3, スキップ) と境界を挟んで対称。
- **テストの目的**: warm-up 境界 (`< window`) を固定。
  - **堅牢性の確認**: off-by-one (window ちょうどをスキップしてしまう) の検出。
- 🟡 信頼性レベル: D-Q3「W 未満はスキップ」に依拠 (境界の厳密解釈は Red で確定)。

### TC-C-B02: z がちょうど閾値のとき非発火 (strict `>` 境界)

- **テスト名**: `test_z_exactly_threshold_not_triggered`
  - **境界値の意味**: 判定式 `z > z_threshold` の等号側 (`>` か `>=` かの分岐)。
  - **境界値での動作保証**: z がちょうど 5.0 のとき発火しない (dataflow「z_rwp > 5」の strict 解釈)。
- **入力値**: robust z が厳密に 5.0 になるよう構成した `rwp_history` (Red で median/MAD から逆算して較正)、`lattice_history=flat_lattice`、`new_unmatched=0`、`ChangepointConfig(z_threshold=5.0)`。
  - **境界値選択の根拠**: 閾値境界は「ほぼ」では不可。Red で z==5.0 になる入力を数式から構築する。
  - **実際の使用場面**: 逸脱が閾値ちょうどの微妙なフレーム。
- **期待される結果**: `sig.triggered is False`、`"rwp_jump" not in sig.reasons`。z が 5.0 を厳密超過する入力 (別ケース) では発火。
  - **境界での正確性**: `>` (strict) が実装されていること。
  - **一貫した動作**: dataflow.md「z_rwp > 5」/「z_lattice > 5」。
- **テストの目的**: 閾値境界の判定規則を固定。
  - **堅牢性の確認**: 浮動小数の等号境界で判定が揺れないこと。
- 🟡 信頼性レベル: dataflow.md の `>` 表記に依拠するが、strict/非 strict は Red で確定 (妥当な推測)。

### TC-C-B03: new_unmatched が min_new_peaks 境界で発火/非発火 (`>=`)

- **テスト名**: `test_new_peaks_threshold_boundary`
  - **境界値の意味**: `new_unmatched >= min_new_peaks` の等号境界 (既定 min=1)。
  - **境界値での動作保証**: `new_unmatched==1` で発火、`==0` で非発火。
- **入力値**: (a) `new_unmatched=1`, (b) `new_unmatched=0`。いずれも `rwp_history=flat_rwp`、`lattice_history=flat_lattice`、既定 `ChangepointConfig(min_new_peaks=1)`。`@pytest.mark.parametrize` で 2 値。
  - **境界値選択の根拠**: 下限ちょうど (1) と直下 (0) で発火境界を挟む。
  - **実際の使用場面**: 新規ピークが 1 本だけ現れた瞬間。
- **期待される結果**: (a) `sig.triggered is True` かつ `sig.reasons == ("new_peaks",)`; (b) `sig.triggered is False` かつ `"new_peaks" not in sig.reasons`。
  - **境界での正確性**: `>=` (下限包含) が実装されていること。
  - **一貫した動作**: TC-C-N03 (new=2) と連続。
- **テストの目的**: new_peaks 下限境界を固定。
  - **堅牢性の確認**: `min_new_peaks` の包含規則 (`>=`)。
- 🔵 信頼性レベル: interfaces.py L88 `min_new_peaks: int = 1` に直接依拠 (`>=` は 🟡)。

### TC-C-B04: 決定論 — 同一入力 2 回でビット同一の ChangepointSignal (REQ-402)

- **テスト名**: `test_deterministic_bit_identical`
  - **境界値の意味**: 実行回数を跨いだ完全再現性 (REQ-402 / NFR-102)。
  - **境界値での動作保証**: 純関数で乱数・順序依存がなく、2 回呼び出しが `==`。
- **入力値**: `rwp_history=spike_rwp`、`lattice_history=jump_lattice` (`a`/`b`/`c` 複数キーで dict 反復順の影響も検査)、`new_unmatched=3` で `detect_changepoint` を 2 回独立に呼ぶ。
  - **境界値選択の根拠**: 決定論は「ほぼ同じ」不可 — `pytest.approx` 禁止、`==` 比較。複数キー格子で Mapping 順序非依存を副検証。
  - **実際の使用場面**: 再解析・監査での結果再現 (NFR-102 ビット同一)。
- **期待される結果**: `sig1 == sig2` (frozen dataclass の構造的等価、`triggered`/`z_rwp`/`z_lattice`/`new_unmatched`/`reasons`/`frame_index` すべて一致)。`reasons` タプルの順序も同一。
  - **境界での正確性**: float フィールドの `==` 一致 (丸め揺らぎゼロ)。
  - **一貫した動作**: 格子キー集約が明示規則で順序非依存。
- **テストの目的**: 決定論契約 (REQ-402) を確認。
  - **堅牢性の確認**: dict/set 反復順・非安定計算由来の非決定性がないこと。
- 🔵 信頼性レベル: REQ-402 / NFR-102 に直接依拠。

### TC-C-B05: ChangepointConfig 既定値の確認 (window=5 / z_threshold=5.0 / min_new_peaks=1)

- **テスト名**: `test_changepoint_config_defaults`
  - **境界値の意味**: 設定契約の既定値そのもの (D-Q3 の仕様値)。
  - **境界値での動作保証**: 引数なし `ChangepointConfig()` が interfaces.py / D-Q3 の既定と一致し frozen。
- **入力値**: `ChangepointConfig()` (引数なし構築)。
  - **境界値選択の根拠**: 既定値は D-Q3 (W=5 / 閾値 5.0 / 下限 1) の仕様値。変更はリグレッション。
  - **実際の使用場面**: config 省略でのデフォルト検出。
- **期待される結果**: `cfg.window == 5`、`cfg.z_threshold == pytest.approx(5.0)`、`cfg.min_new_peaks == 1`。フィールド再代入で `FrozenInstanceError`。
  - **境界での正確性**: 全 3 既定値が仕様どおり。
  - **一貫した動作**: `detect_changepoint` の `config` 既定も `ChangepointConfig()` (同値)。
- **テストの目的**: 設定契約 (interfaces.py L81-88 / D-Q3) の固定。
  - **堅牢性の確認**: frozen による不変性。
- 🔵 信頼性レベル: interfaces.py L81-88 / design-interview D-Q3 に直接依拠。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 (CPython)
  - **言語選択の理由**: プロジェクト標準 (`pyproject.toml` src layout / hatchling / uv)。`sequential/` を新規パッケージとして追加。
  - **テストに適した機能**: `dataclasses` (frozen 値オブジェクト / `FrozenInstanceError`)、`numpy` (median/MAD・強度行列)、型注釈、`math.isfinite` による非有限検査。
- **テストフレームワーク**: pytest >= 8 + pytest-cov
  - **フレームワーク選択の理由**: プロジェクト既定 (`[tool.pytest.ini_options]` `testpaths=["tests"]`)。既存 `tests/test_*.py` と同一様式。
  - **テスト実行環境**: `uv run pytest tests/test_sequential_series.py tests/test_changepoint.py` / `uv run pytest --cov=tsumugin`。**numpy のみ・GSAS-II 非依存** (`@pytest.mark.gsas` 不要、`tests/conftest.py` の gsas skip に非該当)。
- 🔵 信頼性レベル: note.md §1・§5 / `pyproject.toml` / 既存テスト群に直接依拠。

**数値検証の使い分け (書式の範: `tests/test_model_m2.py`)**:
- 🔵 決定論のビット同一検証 (TC-C-B04) と `triggered`/`reasons`/`frame_index`/`n_frames` の検証は `==` を使用。
- 🔵 z 値・温度値等の物理量近似は `pytest.approx` を使用。
- 🔵 非有限漏洩検査 (TC-C-E02) は `math.isfinite(...)` を使用。
- 🔵 本タスクのテストは対象モジュール直 import。`sequential/__init__.py` re-export は併せて確認可。

---

## 5. テストケース実装時の日本語コメント指針

`tests/test_model_m2.py` の書式に倣い、各テストに以下を付与する。

### テストケース開始時のコメント

```python
# 【テスト目的】: Rwp 系列末尾の跳ねのみで rwp_jump が単独発火することを確認 (TC-102-06 / 完了条件②)
# 【テスト内容】: spike_rwp + 同値格子 + new_unmatched=0 で detect_changepoint を呼ぶ
# 【期待される動作】: triggered=True, reasons=("rwp_jump",), z_rwp>5, z_lattice≈0
# 🔵 信頼性レベル: 受け入れ基準 TC-102-06 / dataflow.md 複合指標に直接依拠
```

### Given（準備フェーズ）のコメント

```python
# 【テストデータ準備】: 直近窓が安定 (~10) で末尾のみ 25 に跳ねる Rwp 履歴 (相転移初期を代表)
# 【初期条件設定】: 格子は全同値 (MAD=0 縮退で非発火)、新規ピーク 0 に固定し rwp を単離
# 【前提条件確認】: 履歴長 6 >= window 5 (warm-up を抜けている)
```

### When（実行フェーズ）のコメント

```python
# 【実際の処理実行】: detect_changepoint(rwp_history, lattice_history, new_unmatched, config=ChangepointConfig())
# 【処理内容】: 直近窓の中央値/MAD ロバスト z を 3 指標 OR で判定 (純関数)
# 【実行タイミング】: 履歴構築直後 (乱数不使用・副作用なしのため順序非依存)
```

### Then（検証フェーズ）のコメント

```python
# 【結果検証】: triggered・reasons・各 z・new_unmatched を検証
# 【期待値確認】: rwp_jump 単独発火・格子/新規は非発火
# 【品質保証】: 説明可能性 (reasons に発火指標名) と false-positive 抑制を担保
assert sig.triggered is True                 # 【検証項目】: 変化点として発火 🔵
assert sig.reasons == ("rwp_jump",)          # 【検証項目】: rwp 指標のみ (説明可能性) 🔵
assert sig.z_rwp > 5.0                        # 【検証項目】: z が閾値超過 🟡(exact は Red 較正)
assert sig.z_lattice == pytest.approx(0.0)   # 【検証項目】: 格子は MAD=0 縮退で非発火 🟡
```

### セットアップ・クリーンアップのコメント

```python
# 共通の観測グリッド tt と履歴パターン (flat/spike/linear/jump) はモジュールレベル定数として一度だけ構築。
# detect_changepoint / FrameSeries は状態を持たない (純関数 / frozen 値オブジェクト) ため fixture 後始末は不要。
# 閾値ちょうどの z (TC-C-B02) は median/MAD から逆算した専用入力を Red フェーズで構築する。
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `frameseries-changepoint-requirements.md` §1 (FrameSeries 保持 + detect_changepoint 複合指標)、note.md §タスク要約
- **参照した入力・出力仕様**: requirements §2.1〜§2.4 (`FrameSeries` / `ChangepointConfig` / `ChangepointSignal` / `detect_changepoint` の型・判定 6 ステップ)、interfaces.py L62-110
- **参照した制約条件**: requirements §3 (決定論・非破壊・非有限値非漏洩・縮退の非例外化 vs 形状明示エラー)、note.md §2・§6
- **参照した使用例**: requirements §4.1〜§4.4 (単独指標検出 / 滑らかな系列 / 決定論 / warm-up・MAD=0 縮退・形状不一致)
- **参照した受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md` TC-102-04 (L33) / TC-102-06 (L35)、TASK-0015 完了条件①〜⑥

### テストケース ↔ 完了条件/受け入れ基準 トレーサビリティ

| テストケース | 対応する完了条件 / 受け入れ基準 / 要件 | 信頼性 |
|-------------|-------------------------------|--------|
| TC-S-N01 | interfaces.py FrameSeries 契約 (n_frames) | 🔵 |
| TC-S-N02 | REQ-006 (channels 紐付け) | 🔵 |
| TC-S-N03 | interfaces.py L70-71 (axis_kind/values) | 🔵 |
| TC-S-E01 | 完了条件① (列数不一致) | 🟡 |
| TC-S-E02 | 完了条件① (axis_values 長不一致) | 🟡 |
| TC-S-E03 | CLAUDE.md frozen 規約 (P2) | 🔵 |
| TC-S-B01 | EDGE-101 (単一フレーム) | 🔵 |
| TC-S-B02 | interfaces.py L70 (空→index) | 🔵 |
| TC-S-B03 | 完了条件① 許可側境界 | 🔵 |
| TC-C-N01 | 完了条件② / TC-102-06 (rwp 単独) | 🔵 |
| TC-C-N02 | 完了条件② / TC-102-06 (lattice 単独) | 🔵 |
| TC-C-N03 | 完了条件② / TC-102-06 (new_peaks 単独) | 🟡 |
| TC-C-N04 | 完了条件③ / TC-102-04 (滑らかで非発火) | 🔵 |
| TC-C-N05 | dataflow.md 3 指標 OR | 🔵 |
| TC-C-N06 | 完了条件⑤ (説明可能性) / interfaces.py L90-99 | 🟡 |
| TC-C-E01 | 完了条件④ / D-Q3 (warm-up スキップ) | 🟡 |
| TC-C-E02 | 完了条件⑥ (MAD=0 縮退) | 🟡 |
| TC-C-E03 | interfaces.py frozen 契約 | 🔵 |
| TC-C-B01 | 完了条件④ 境界 (len==window) | 🟡 |
| TC-C-B02 | dataflow.md `z > 5` strict 境界 | 🟡 |
| TC-C-B03 | interfaces.py L88 (min_new_peaks `>=`) | 🔵 |
| TC-C-B04 | REQ-402 / NFR-102 (決定論) | 🔵 |
| TC-C-B05 | interfaces.py L81-88 / D-Q3 既定値 | 🔵 |

---

## 7. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 9 / 異常系 6 / 境界値 8 = 23 件で網羅
  (FrameSeries 9 + changepoint 14。完了条件①〜⑥ + TC-102-04/06 + 決定論 + frozen/既定値契約を全カバー)
- 期待値定義: 各ケースに具体的な入力履歴・期待 triggered/reasons/z・判定式を明記
- 技術選択: Python 3.12 + pytest 8 + numpy (backend/GSAS-II 非依存) — 確定
- 実装可能性: interfaces.py L62-110 に契約確定、前提 TASK-0011 完了、numpy のみで完結
- 信頼性レベル: 🔵 15 / 🟡 8 / 🔴 0 — 中核契約・受け入れ基準は直接依拠、🟡 は統計式の実装細部に集中
```

- **残る 🟡 (Red → Green で挙動を確定させ docstring に根拠を残す)**:
  (a) `FrameSeries` 形状エラーの型 (`ValueError` 想定 / TC-S-E01/E02)、
  (b) ロバスト z の定義 `0.6745·(x−median)/MAD` と exact 期待値の較正 (TC-C-N01/02 ほか)、
  (c) 窓包含境界・warm-up の `< window` 厳密解釈 (TC-C-B01/E01)、
  (d) z 閾値の strict `>` 境界 (TC-C-B02)、
  (e) `z_lattice` の a/b/c 最大絶対 z 集約 (TC-C-N02)、
  (f) `new_peaks` のカウント閾値解釈と `frame_index = len-1` の由来 (TC-C-N03/N06)。
- **次のステップ**: `/tsumiki:tdd-red m2-sequential TASK-0015` で `tests/test_sequential_series.py` (9 件) と `tests/test_changepoint.py` (14 件) に本 23 ケースの失敗テストを実装する。
