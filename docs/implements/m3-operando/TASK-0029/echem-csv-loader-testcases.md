# TASK-0029 TDDテストケース定義: operando/echem — CSV マッパ + Loader Protocol (FR-311)

**機能名**: echem-csv-loader / **タスクID**: TASK-0029 / **要件名**: m3-operando
**信頼性サマリー**: 🔵 11 / 🟡 4 (FR-311 / REQ-007/008 / EDGE-003 / D-Q7 / AC TC-202-01〜04)
**対象実装**: `src/tsumugin/operando/echem.py` (新規) / **テストファイル**: `tests/test_echem.py` (新規)

> AC の受け入れ基準 TC-202-01〜04 と本書のテスト ID (N/A/BV) の対応を各ケースに明記する。
> 本書のすべてのパスはプロジェクトルートからの相対パス。

---

## 0. テスト方針・共通事項

- **対象 API** (`docs/design/m3-operando/interfaces.py` L199-228):
  `EchemData` (frozen dataclass, `to_channels()`) / `read_echem_csv(path, *, column_map, capacity_to_x=None)` /
  `EchemLoader` Protocol / `BiologicMprLoader` スタブ。
- **CSV 入力**: pytest `tmp_path` フィクスチャで一時 CSV を書き出して読む (`tests/test_trajectory.py` の I/O パターンに準拠)。
- **列マッピング前提**: `column_map` は論理名 (`frame`/`voltage`/`current`/`capacity`) → CSV ヘッダ列名。
  `to_channels()` の `sync_map` は frame 列由来の frame_index → 値。**None 値は sync_map に含めない** (欠損=不同期)。
- **警告捕捉**: `with pytest.warns(UserWarning):`。**明示エラー**: `with pytest.raises(ValueError) as exc:` +
  `assert "<列名>" in str(exc.value)`。
- **決定論**: `read_echem_csv(...) == read_echem_csv(...)` (等価比較)。
- **テストデータ例** (共通): ヘッダ `index,Ewe/V,I/mA,Q/mAh`、行 `0,3.20,0.50,0.00 / 1,3.50,0.50,1.00 / 2,3.80,0.50,2.00`。
  `column_map = {"frame":"index","voltage":"Ewe/V","current":"I/mA","capacity":"Q/mAh"}`。

---

## 1. 正常系テストケース（基本的な動作）

### TC-N01: 列マッピング読込 + V/I/Q フレーム同期チャネル群 🔵 (対応: TC-202-01 / REQ-007)

- **テスト名**: `test_read_echem_csv_maps_columns_and_syncs_vic`
  - **何をテストするか**: `frame,V,I,Q` 列 CSV を `column_map` で読み、`to_channels()` が voltage/current/capacity kind の
    `ExternalChannel` 群を返し、フレーム同期が正しいこと。
  - **期待される動作**: 3 フレーム分の V/I/Q が対応 kind のチャネルに格納され、`value_for(frame)` が正しい値を返す。
- **入力値**: 上記共通テストデータ CSV + `column_map` (frame/voltage/current/capacity)。
  - **入力データの意味**: REQ-007 が要求する最小構成 (frame,V,I,Q の 4 論理列)。operando 充放電の代表列。
- **期待される結果**: `data.voltage == (3.20, 3.50, 3.80)`, `data.current == (0.50, 0.50, 0.50)`,
  `data.capacity == (0.00, 1.00, 2.00)`。`channels = data.to_channels()` に kind `"voltage"/"current"/"capacity"` が含まれ、
  voltage チャネルの `value_for(1) == 3.50`。
  - **期待結果の理由**: 列名マッピングで抽出→フレーム同期という REQ-007/dataflow.md L16-17 の中核契約。
- **テストの目的**: 基本読込 + 同期経路の確立。
  - **確認ポイント**: 列名 (`Ewe/V` 等特殊文字含む) が `column_map` 経由で正しく解決されること、frame_index 対応。
- 🔵 信頼性: TC-202-01 / REQ-007 / interfaces.py L211-218 に直接依拠。

### TC-N02: 容量→x 線形換算 (composition チャネル生成) 🔵 (対応: TC-202-02 / REQ-007)

- **テスト名**: `test_read_echem_csv_applies_linear_capacity_to_x`
  - **何をテストするか**: `capacity_to_x=(slope, intercept)` 指定時、`composition_x[i] == slope·Q[i] + intercept`。
  - **期待される動作**: 全フレームに線形換算が適用され `composition` kind チャネルが生成される。
- **入力値**: 共通 CSV + `capacity_to_x=(0.5, 0.1)` (Q=0,1,2 → x=0.1,0.6,1.1)。
  - **入力データの意味**: 容量→組成 x の線形係数設定 (REQ-007「換算則 (線形係数) を設定可能」)。
- **期待される結果**: `data.composition_x == pytest.approx((0.1, 0.6, 1.1))`。`to_channels()` に kind `"composition"` があり
  `value_for(2) == pytest.approx(1.1)`。
  - **期待結果の理由**: `x = a·Q + b` の直接適用 (interfaces.py L215)。
- **テストの目的**: 換算則の正確な適用。
  - **確認ポイント**: 浮動小数は `pytest.approx`、換算は capacity から派生 (独立入力でない)。
- 🔵 信頼性: TC-202-02 / REQ-007 / interfaces.py L215 に直接依拠。

### TC-N03: capacity_to_x 未指定なら composition_x は空 🔵 (対応: TC-202-01/02 の補集合)

- **テスト名**: `test_read_echem_csv_no_conversion_leaves_composition_empty`
  - **何をテストするか**: `capacity_to_x=None` (既定) のとき `composition_x` が空、`composition` チャネルが生成されない。
  - **期待される動作**: 換算則未指定では x を捏造しない。
- **入力値**: 共通 CSV、`capacity_to_x` 省略。
  - **入力データの意味**: 換算不要 (V/I/Q のみ利用) の一般ケース。
- **期待される結果**: `data.composition_x == ()`。`to_channels()` の kind に `"composition"` を**含まない**。
  - **期待結果の理由**: x は換算則からの派生。未指定なら生成しない (欠損は捏造しない / dataflow.md L124)。
- **テストの目的**: 任意フィールドの非生成。
  - **確認ポイント**: composition チャネルが誤生成されないこと。
- 🔵 信頼性: interfaces.py L206/L215 (x は換算済み) / dataflow.md L124 に依拠。

### TC-N04: 任意列省略 (voltage のみ) の最小読込 🟡 (対応: TC-202-01 の縮退)

- **テスト名**: `test_read_echem_csv_voltage_only_leaves_others_empty`
  - **何をテストするか**: `column_map` に voltage(+frame) のみ指定した場合、current/capacity が空 tuple になる。
  - **期待される動作**: 指定されない論理列は空、voltage チャネルのみ生成。
- **入力値**: ヘッダ `index,Ewe/V` の CSV + `column_map={"frame":"index","voltage":"Ewe/V"}`。
  - **入力データの意味**: 電圧のみ取得する簡略計測。任意列の既定 `()` を代表。
- **期待される結果**: `data.current == ()`, `data.capacity == ()`, `data.composition_x == ()`。
  `to_channels()` の kind は `("voltage",)` のみ。
  - **期待結果の理由**: EchemData の current/capacity/composition_x 既定 `()` (interfaces.py L204-206)。
- **テストの目的**: 部分列マッピングの縮退挙動。
  - **確認ポイント**: 未指定列でエラーにならず空縮退すること。
- 🟡 信頼性: interfaces.py L204-206 (既定 `()`) から妥当推測 (voltage 位置必須は明示、他省略時挙動は自然帰結)。

### TC-N05: EchemData の frozen・構造的等価・to_channels 直接 🔵 (対応: §4 データモデル)

- **テスト名**: `test_echem_data_frozen_and_structural_equality`
  - **何をテストするか**: `EchemData` を直接生成し frozen (再代入不可)・等価比較 (`==`)・`to_channels()` が動く。
  - **期待される動作**: 同値 EchemData は `==` で真、フィールド再代入は `FrozenInstanceError`。
- **入力値**: `EchemData(voltage=(3.2, 3.5), current=(0.5, 0.5))` を 2 つ。
  - **入力データの意味**: I/O を介さない純データモデル契約 (frozen dataclass)。
- **期待される結果**: 2 インスタンスが `==`。`with pytest.raises(dataclasses.FrozenInstanceError): data.voltage = ()`。
  `to_channels()` が voltage/current チャネルを返す。
  - **期待結果の理由**: interfaces.py L199-208 の frozen dataclass 契約 (全 tuple → ハッシュ可・等価可)。
- **テストの目的**: データモデルの不変性・等価性。
  - **確認ポイント**: read 経路と独立にモデル単体が健全。
- 🔵 信頼性: interfaces.py L199-208 / CLAUDE.md (frozen dataclass 規約) に依拠。

### TC-N06: to_channels が None 値を sync_map に含めない 🟡 (対応: dataflow.md L124 欠損政策)

- **テスト名**: `test_to_channels_excludes_none_frames_from_sync_map`
  - **何をテストするか**: フィールドに None を含む EchemData で、`to_channels()` の sync_map が None フレームを除外。
  - **期待される動作**: 欠損フレームは不同期 (キー不在)、`value_for` が None を返す。
- **入力値**: `EchemData(voltage=(3.2, None, 3.8))`。
  - **入力データの意味**: 部分同期 (欠損 None) の内部表現。行数不一致縮退後の状態を代表。
- **期待される結果**: voltage チャネルの `value_for(0) == 3.2`, `value_for(1) is None` (キー不在), `value_for(2) == 3.8`。
  sync_map に frame 1 のキーが存在しない。
  - **期待結果の理由**: 欠損は frame_index キーの外部結合で捏造しない (dataflow.md L124)、`ExternalChannel.value_for` は
    `sync_map.get` で欠損を None 縮退 (channel.py L43)。
- **テストの目的**: 欠損の非捏造・None 縮退の一貫性。
  - **確認ポイント**: None を 0 や補間で埋めないこと。
- 🟡 信頼性: dataflow.md L124 / channel.py L43 から妥当推測 (to_channels の None 扱い詳細は 🟡)。

### TC-N07: 決定論 — 同一 CSV を 2 回読んでビット同一 🔵 (対応: NFR-102 / REQ-402)

- **テスト名**: `test_read_echem_csv_is_deterministic`
  - **何をテストするか**: 同一 CSV・同一引数で `read_echem_csv` を 2 回呼び結果が等価。
  - **期待される動作**: 行順・列順で結果が揺れず `==`。
- **入力値**: 共通 CSV + `column_map` + `capacity_to_x=(0.5, 0.0)`、2 回呼出。
  - **入力データの意味**: 再現性 (NFR-102) の検証。
- **期待される結果**: `read_echem_csv(...) == read_echem_csv(...)` が真。
  - **期待結果の理由**: 純 I/O・乱数不使用のため決定論 (CLAUDE.md 不変条件)。
- **テストの目的**: 再現性保証。
  - **確認ポイント**: dict イテレーション順等に依存しないこと。
- 🔵 信頼性: NFR-102 / REQ-402 / CLAUDE.md 不変条件に直接依拠。

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-A01: 列欠損 = 列名を示す明示エラー 🔵 (対応: TC-202-03a / EDGE-003 / D-Q7)

- **テスト名**: `test_read_echem_csv_missing_column_raises_valueerror_with_name`
  - **エラーケースの概要**: `column_map` が要求する CSV 列がヘッダに存在しない。
  - **エラー処理の重要性**: 誤った列参照で沈黙して不正データを生むのを防ぐ。処理継続不能を明示。
- **入力値**: ヘッダ `index,Ewe/V` の CSV に対し `column_map={"frame":"index","voltage":"Ewe/V","capacity":"Q/mAh"}`
  (CSV に `Q/mAh` 列が無い)。
  - **不正な理由**: マッピング先の実列がヘッダに無く抽出不能。
  - **実際の発生シナリオ**: 列名の打ち間違い、機種違いの CSV を誤った column_map で読む。
- **期待される結果**: `ValueError` が送出され、メッセージに欠損列名 `"Q/mAh"` を含む。
  - **エラーメッセージの内容**: どの列が見つからないかをユーザが特定できる (列名提示)。
  - **システムの安全性**: 例外で停止し不完全な EchemData を返さない。
- **テストの目的**: 列欠損の明示エラー化 (D-Q7「列欠損 = 明示エラー (列名提示)」)。
  - **品質保証の観点**: EDGE-003 の「明示エラー (列名を示す)」を満たす。
- 🔵 信頼性: TC-202-03 / EDGE-003 / dataflow.md L110 / design-interview D-Q7 に直接依拠。

### TC-A02: 数値変換失敗 = 列名を示す明示エラー / eval 不使用 🔵 (対応: TC-202-03 / 完了条件・NFR)

- **テスト名**: `test_read_echem_csv_non_numeric_cell_raises_explicit_error`
  - **エラーケースの概要**: 数値であるべきセルが非数値文字列 (例 `"abc"`)。
  - **エラー処理の重要性**: `float()` 変換失敗を握りつぶさず明示。信頼できない CSV を eval で評価しない (セキュリティ)。
- **入力値**: 行 `1,abc,0.50,1.00` を含む CSV + 共通 `column_map`。
  - **不正な理由**: `Ewe/V` 列のセルが float 化不能。
  - **実際の発生シナリオ**: 欠測記号や単位混入、破損 CSV。
- **期待される結果**: 明示的な例外 (`ValueError`) が送出され、問題列名 (`Ewe/V`) を含む。`eval`/`ast.literal_eval` を経由しない
  (実装が float() のみを使用)。
  - **エラーメッセージの内容**: どの列の値が数値化できないかを提示。
  - **システムの安全性**: 任意コード実行経路 (eval) を持たない。
- **テストの目的**: 安全な数値変換 (architecture.md L130「数値変換失敗は明示エラー (eval 不使用)」)。
  - **品質保証の観点**: セキュリティ完了条件 (eval 不使用) を担保。
- 🔵 信頼性: 完了条件「数値変換失敗の明示エラー (eval 不使用)」/ architecture.md L130 に直接依拠。

### TC-A03: 未実装機種ローダ = NotImplementedError 🔵 (対応: TC-202-04 / REQ-008)

- **テスト名**: `test_biologic_mpr_loader_load_raises_not_implemented`
  - **エラーケースの概要**: Biologic .mpr バイナリローダは M3 では未実装。
  - **エラー処理の重要性**: Protocol 境界は用意しつつ未実装を明示し、誤用時に沈黙しない。
- **入力値**: `BiologicMprLoader().load("any.mpr")`。
  - **不正な理由**: M3 スコープ外 (バイナリパーサ未実装)。
  - **実際の発生シナリオ**: 将来対応予定の機種ローダを M3 段階で呼ぶ。
- **期待される結果**: `with pytest.raises(NotImplementedError):`。
  - **エラーメッセージの内容**: 未実装であることが分かる。
  - **システムの安全性**: 中途半端な戻り値を返さず例外で停止。
- **テストの目的**: Protocol + 未実装スタブ契約 (REQ-008「Protocol のみ定義、M3 では未実装エラー」)。
  - **品質保証の観点**: 交換境界の存在と未実装の明示を両立。
- 🔵 信頼性: TC-202-04 / REQ-008 / interfaces.py L227-228 に直接依拠。

### TC-A04: EchemLoader Protocol の構造的準拠 🟡 (対応: REQ-008 交換境界)

- **テスト名**: `test_biologic_mpr_loader_satisfies_echem_loader_protocol`
  - **エラーケースの概要**: (準異常系/境界契約) `BiologicMprLoader` が `EchemLoader` Protocol の構造 (`load` メソッド) を満たす。
  - **エラー処理の重要性**: 交換境界として型互換であることを保証 (実装未完でも境界は成立)。
- **入力値**: `loader: EchemLoader = BiologicMprLoader()` (静的/構造チェック)、`hasattr(loader, "load")`。
  - **不正な理由**: (該当なし — 構造適合の確認)。
  - **実際の発生シナリオ**: 上位が `EchemLoader` 型で機種ローダを差し替える。
- **期待される結果**: `BiologicMprLoader` が `load(path) -> EchemData` シグネチャを持つ (`callable(loader.load)`)。
  - **システムの安全性**: Protocol 境界の型互換を確認。
- **テストの目的**: Protocol 交換境界の成立確認 (`MuCalculator`/`XraylibMuCalculator` の範と同型)。
  - **品質保証の観点**: 後続の機種ローダ差し替え可能性を担保。
- 🟡 信頼性: REQ-008 / interfaces.py L221-228 / TASK-0025 Protocol 範から妥当推測。

---

## 3. 境界値テストケース（最小値、最大値、null等）

### TC-BV01: 行数不一致 = 短い方に合わせ None + 警告 🟡 (対応: TC-202-03b / EDGE-003 / D-Q7)

- **テスト名**: `test_read_echem_csv_ragged_rows_pad_none_and_warn`
  - **境界値の意味**: 列間で行数が異なる (部分同期) 境界。エラーではなく縮退継続する分岐。
  - **境界値での動作保証**: 短い列の欠損を None にし、警告で利用者へ通知。
- **入力値**: capacity 列が voltage 列より短い CSV (例: 一部行の `Q/mAh` セルが空)。
  - **境界値選択の根拠**: EDGE-003「行数不一致」/ D-Q7「短い方に合わせ欠損 None + 警告」。
  - **実際の使用場面**: 電気化学ロガーと回折フレームで記録本数がずれる実運用。
- **期待される結果**: `with pytest.warns(UserWarning):` の中で読込が成功し、欠損フレームの capacity が None
  (該当フレームは capacity チャネルの sync_map に不在)。voltage 側は全フレーム保持。
  - **境界での正確性**: 存在する値は保持、欠損のみ None。
  - **一貫した動作**: 列欠損 (エラー) とは非対称に、行数不一致は警告で継続。
- **テストの目的**: 欠損政策の非対称 (列欠損=エラー / 行数不一致=警告) の境界固定。
  - **堅牢性の確認**: 不揃いデータでも安全に部分同期。
- 🟡 信頼性: EDGE-003 / TC-202-03 / design-interview D-Q7 に依拠 (警告文言・縮退詳細は 🟡 → tdd-red で確定)。

### TC-BV02: 空データ (ヘッダのみ) → 空 tuple・チャネルなし 🟡 (対応: 最小入力縮退)

- **テスト名**: `test_read_echem_csv_header_only_returns_empty`
  - **境界値の意味**: データ行 0 件 (ヘッダのみ) の最小 CSV。
  - **境界値での動作保証**: 例外を投げず空 EchemData を返す。
- **入力値**: `index,Ewe/V,I/mA,Q/mAh` のみ (データ行なし) + 共通 `column_map`。
  - **境界値選択の根拠**: 要素数 0 の縮退 (空集合)。
  - **実際の使用場面**: 空計測ファイル、初期化直後。
- **期待される結果**: `data.voltage == ()` 等すべて空、`data.to_channels() == ()` (チャネルなし)。
  - **境界での正確性**: 空でも型 (tuple) を保つ。
  - **一貫した動作**: 空チャネルを誤生成しない。
- **テストの目的**: 空入力の安全縮退。
  - **堅牢性の確認**: ゼロ件でクラッシュしない。
- 🟡 信頼性: 空入力縮退の一般規約 (clustering 等の空縮退) から妥当推測。

### TC-BV03: 単一行 CSV → 単一要素 tuple 🟡 (対応: 最小非空)

- **テスト名**: `test_read_echem_csv_single_row`
  - **境界値の意味**: データ行 1 件の最小非空ケース。
  - **境界値での動作保証**: 1 フレームでも正しく同期。
- **入力値**: データ行 `0,3.20,0.50,0.00` 1 行 + 共通 `column_map`。
  - **境界値選択の根拠**: 要素数 1 の境界 (0 と複数の間)。
  - **実際の使用場面**: 単一スナップショット計測。
- **期待される結果**: `data.voltage == (3.20,)`, `to_channels()` の voltage チャネル `value_for(0) == 3.20`。
  - **境界での正確性**: 単一要素でも tuple 構造を保持。
- **テストの目的**: 最小非空の健全性。
  - **堅牢性の確認**: 1 件でオフバイワンしない。
- 🟡 信頼性: interfaces.py 契約からの自然な境界 (妥当推測)。

### TC-BV04: capacity_to_x が恒等 (1, 0) → composition_x == capacity 🔵 (対応: TC-202-02 の境界)

- **テスト名**: `test_capacity_to_x_identity_equals_capacity`
  - **境界値の意味**: `slope=1, intercept=0` の恒等換算 (換算の境界パラメータ)。
  - **境界値での動作保証**: 恒等係数で capacity と一致。
- **入力値**: 共通 CSV + `capacity_to_x=(1.0, 0.0)`。
  - **境界値選択の根拠**: 線形換算 `x = a·Q + b` の a=1,b=0 は capacity をそのまま x とする境界。
  - **実際の使用場面**: 容量そのものを x 軸に使う簡略運用。
- **期待される結果**: `data.composition_x == pytest.approx(data.capacity)`。
  - **境界での正確性**: 換算式が恒等で崩れないこと。
- **テストの目的**: 換算式の代数的正しさ (境界パラメータ)。
  - **堅牢性の確認**: slope/intercept の適用順が正しい。
- 🔵 信頼性: interfaces.py L215 (`x = a·Q + b`) に直接依拠。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **言語選択の理由**: プロジェクト標準 (uv 管理 / src layout + hatchling / CLAUDE.md)。実装対象が Python。
  - **テストに適した機能**: `dataclasses.FrozenInstanceError` による不変性検証、`typing.Protocol` 構造的部分型、
    stdlib `csv` / `warnings` の標準機構。
- **テストフレームワーク**: pytest (>= 8) + pytest-cov 🔵
  - **フレームワーク選択の理由**: 既存全テストが pytest。`pytest.raises` / `pytest.warns` / `pytest.approx` /
    `tmp_path` フィクスチャが本タスク (例外・警告・近似・一時 CSV) に最適。
  - **テスト実行環境**: `uv run pytest tests/test_echem.py` (単体) / `uv run pytest` (全体回帰)。GSAS-II 非依存 (`gsas` マーカー不要)。
- 🔵 信頼性: `pyproject.toml` / 既存 `tests/*.py` / note.md §5 に直接依拠。

---

## 5. テストケース実装時の日本語コメント指針 (代表例)

```python
def test_read_echem_csv_maps_columns_and_syncs_vic(tmp_path):
    # 【テスト目的】: frame,V,I,Q 列 CSV を column_map で読み V/I/Q がフレーム同期チャネルになることを確認 (TC-202-01)
    # 【テスト内容】: read_echem_csv → to_channels → value_for の一連経路を検証
    # 【期待される動作】: voltage/current/capacity kind の ExternalChannel が生成され値が一致
    # 🔵 信頼性: TC-202-01 / REQ-007 に直接依拠

    # 【テストデータ準備】: 特殊列名 (Ewe/V 等) を含む代表 CSV を tmp_path に用意 (列名マッピング解決の確認のため)
    # 【初期条件設定】: 3 フレーム分の充放電データ
    csv_path = tmp_path / "echem.csv"
    csv_path.write_text("index,Ewe/V,I/mA,Q/mAh\n0,3.20,0.50,0.00\n1,3.50,0.50,1.00\n2,3.80,0.50,2.00\n")
    column_map = {"frame": "index", "voltage": "Ewe/V", "current": "I/mA", "capacity": "Q/mAh"}

    # 【実際の処理実行】: read_echem_csv を呼び EchemData を得る
    # 【処理内容】: stdlib csv で読み column_map で列抽出 (eval 不使用)
    data = read_echem_csv(str(csv_path), column_map=column_map)

    # 【結果検証】: 抽出値とチャネル同期を確認
    # 【期待値確認】: voltage/current/capacity が記載順どおりに tuple 化される
    assert data.voltage == (3.20, 3.50, 3.80)  # 【検証項目】: 電圧列の抽出 🔵
    channels = {ch.kind: ch for ch in data.to_channels()}
    assert channels["voltage"].value_for(1) == 3.50  # 【検証項目】: frame_index 同期 🔵
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `echem-csv-loader-requirements.md` §1 (echem CSV 同期入力層 / operando 入口)
- **参照した入力・出力仕様**: 同 §2 (EchemData / read_echem_csv / EchemLoader・BiologicMprLoader)
- **参照した制約条件**: 同 §3 (eval 不使用・stdlib csv 限定・決定論・非破壊・型注釈)
- **参照した使用例**: 同 §4 (基本読込 / 容量→x / 列欠損エラー / 行数不一致 None+警告 / 未実装ローダ)
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` TC-202-01〜04
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L199-228, `docs/design/m3-operando/dataflow.md` L16-17/L110/L124,
  `docs/design/m3-operando/architecture.md` L37/L114/L130, `docs/design/m3-operando/design-interview.md` D-Q7

---

## テストケース数内訳

| 区分 | 件数 | テスト ID |
|---|---|---|
| 正常系 | 7 | TC-N01〜TC-N07 |
| 異常系 | 4 | TC-A01〜TC-A04 |
| 境界値 | 4 | TC-BV01〜TC-BV04 |
| **合計** | **15** | — |

**AC 対応**: TC-202-01 → TC-N01 / TC-202-02 → TC-N02・TC-BV04 / TC-202-03 → TC-A01・TC-A02・TC-BV01 /
TC-202-04 → TC-A03 (+ TC-A04 Protocol 準拠)。

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 7 / 異常系 4 / 境界値 4 を網羅 (TC-202-01〜04 を全被覆)
- 期待値定義: 各ケースに具体的な期待値 (値・例外型・警告型) を明記
- 技術選択: Python 3.12 + pytest (pytest.raises/warns/approx/tmp_path) で確定
- 実装可能性: 依存は stdlib (csv/warnings/dataclasses) のみ、TASK-0025 で ExternalChannel/ChannelKind 整備済で確実
- 信頼性レベル: 🔵 11 / 🟡 4 — 🟡 は行数不一致の警告詳細・任意列縮退・to_channels の None 扱いに集中 (要件へ遡及可能)
```

**次のお勧めステップ**: `/tsumiki:tdd-red m3-operando TASK-0029` で Red フェーズ (失敗テスト作成) を開始します。
