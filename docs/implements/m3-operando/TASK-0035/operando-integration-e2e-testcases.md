# TASK-0035 TDD テストケース定義 — M3 公開 API 統合 + E2E + ドキュメント

**機能名**: operando-integration-e2e / **タスクID**: TASK-0035 / **要件名**: m3-operando
**対象テストファイル**: `tests/test_operando_e2e.py` (新規)
**テストフレームワーク**: pytest (>=8) + pytest-cov / 実行 `uv run pytest tests/test_operando_e2e.py`

> 信頼性レベル: 🔵 青 (要件・実 API・AC に直接依拠) / 🟡 黄 (妥当な推測) / 🔴 赤 (資料外推測)。
> 内部 ID は TC-035-NN。対応する受け入れ基準 (AC) は TC-209-01〜03 (`docs/spec/m3-operando/acceptance-criteria.md` L82-85)。

## 共通前提・テストデータ (モジュールレベルで構築し不変共有)

- 🔵 観測グリッド `GRID = np.arange(15.0, 60.0, 0.05)` (判別/分割テストと同較正・固定相 Al (211)≈55.5° を捉える <30 秒 smoke)。
- 🔵 `@gsas` グリッド `GRID_GSAS = np.arange(20.0, 80.0, 0.05)` (`tests/test_m2_e2e.py` L95 と同一)。
- 🔵 二相反応系列 `_two_phase_series` (端成分 α:1→0 / β:0→1 の scale 漸移。`tests/test_discrimination.py` L77-93 に倣う)。
- 🔵 固定相 `AL = CELL_PHASE_PRESETS["Al"]` (FixedPhaseSpec)。系列へ `AL.phase.with_updates(scale=0.7)` を重畳可。
- 🔵 初期相 `INITIAL = (PhaseInstance("A", LatticeParams(5.0,5.0,5.0)),)`。
- 🟡 実行時間短縮の判別 config `CONFIG_FAST = DiscriminationConfig(multistart=MultistartConfig(n_starts=2))` (verdict は本数非依存)。
- 🔵 一気通貫は **module スコープ fixture `operando_run`** で 1 回だけ実行し正常系で読み取り専用共有 (M2 `warming_run` L220 の範)。共有 `Ledger` を segment/discriminate へ注入する。

---

## 1. 正常系テストケース（基本的な動作）

### TC-035-01: M3 公開シンボルが `from tsumugin import ...` で解決する 🔵
- **何をテストするか**: M3 中核シンボルがトップレベル `tsumugin` 名前空間から import でき、期待の型 (class/dataclass/関数) を持つ。
- **期待される動作**: `MultistartEngine`/`MultistartConfig`/`CellConfig`/`AbsorptionConfig`/`read_echem_csv`/`EchemData`/`CELL_PHASE_PRESETS`/`discriminate_interval`/`segment_series`/`combined_csv` 等が解決する。
- **入力値**: モジュール冒頭の `from tsumugin import (...)` (M3 シンボル束)。
  - **入力データの意味**: 未 re-export なら collection 時 ImportError → 全テスト失敗 (Red の失敗機構)。
- **期待される結果**: `inspect.isclass(MultistartEngine)`, `dataclasses.is_dataclass(MultistartConfig/CellConfig/AbsorptionConfig/EchemData/...)`, `callable(read_echem_csv/discriminate_interval/segment_series/combined_csv)`, `isinstance(CELL_PHASE_PRESETS, Mapping)`。
  - **期待結果の理由**: 完了条件① (`from tsumugin import MultistartEngine, ...` で M3 API 利用可能)。
- **テストの目的**: 公開面への配線 (re-export) が成立していること。
  - **確認ポイント**: エンジン系=クラス / 値オブジェクト系=dataclass / 純関数系=callable の区別。
- 🔵 対応 AC: TC-209 前提 / 要件定義 §2.1。先例: `tests/test_m2_e2e.py::test_m2_public_symbols_are_reexported`。

### TC-035-02: `__all__` が M3 を昇順包含し M0/M1/M2 を後方互換維持 🔵
- **何をテストするか**: 昇格 M3 シンボルが `tsumugin.__all__` に含まれ、昇順ソート維持、既存 M0/M1/M2 シンボルが 1 つも削除・改名されていない。
- **期待される動作**: `_M3_PROMOTED_SYMBOLS <= set(tsumugin.__all__)` かつ `_M0M1M2_PUBLIC_SYMBOLS <= set(tsumugin.__all__)`。
- **入力値**: `tsumugin.__all__` (追記後)。
  - **入力データの意味**: 公開契約の集合。
- **期待される結果**: `list(tsumugin.__all__) == sorted(tsumugin.__all__)` (昇順) / 既存 54 件 (現行 L65-118) が全て残存 (REQ-404)。
  - **期待結果の理由**: `tests/test_m1_e2e.py` / `tests/test_m2_e2e.py` の `__all__` 検証が昇順+非削除を固定している。
- **テストの目的**: 後方互換 (REQ-404) と公開面の一貫性。
  - **確認ポイント**: 追記漏れ・順序崩れ・既存削除の検出。
- 🔵 対応 AC: 完了条件① / REQ-404。先例: `tests/test_m2_e2e.py::test_m2_symbols_in_dunder_all_and_sorted`。

### TC-035-03: re-export は同一実体 (`is`) である 🔵
- **何をテストするか**: トップレベルのシンボルがサブパッケージ実体と同一オブジェクト (別実装・コピーでない)。
- **期待される動作**: `MultistartEngine is tsumugin.multistart.MultistartEngine`, `discriminate_interval is tsumugin.operando.discriminate_interval`, `CellConfig is tsumugin.model.CellConfig`, `AbsorptionConfig is tsumugin.absorption.AbsorptionConfig`。
- **入力値**: トップレベル属性 と サブパッケージ属性。
- **期待される結果**: 全て `is` で一致。
  - **期待結果の理由**: re-export の定義 (実体の別名付け)。
- **テストの目的**: 二重実装や意図せぬラップの防止。
  - **確認ポイント**: `__all__` の全 M3 名について `hasattr` + 実体一致。
- 🔵 対応: 要件定義 §2.1。先例: `tests/test_m2_e2e.py` L304-308。

### TC-035-04: operando 一気通貫が例外なく完走する (TC-209-01) 🔵
- **何をテストするか**: echem 同期 → 固定相込み segment_series → 区間ごと discriminate_interval → combined_csv → ledger verify が単一パスで完走する。
- **期待される動作**: `operando_run` fixture が例外を出さず `SegmentationResult` / `list[DiscriminationResult]` / CSV パス / 健全 `Ledger` を返す。
- **入力値**: 二相反応 `FrameSeries` (n=8) + 固定相 AL + echem CSV。
  - **入力データの意味**: operando 電池モードの最小代表 (固溶体/二相の切替を含む)。
- **期待される結果**: fixture が正常終了し、後続の正常系 TC-035-05〜09 で読み取り共有できる。
  - **期待結果の理由**: 完了条件② (TC-209-01 一気通貫 green)。
- **テストの目的**: dataflow.md の operando 縦串が公開 API 経由で通ること。
  - **確認ポイント**: 各層の受け渡し (series/echem/fixed_phases/ledger) が破綻しない。
- 🔵 対応 AC: TC-209-01 / `docs/design/m3-operando/dataflow.md`。

### TC-035-05: echem CSV が EchemData へ同期される 🔵
- **何をテストするか**: `read_echem_csv(path, column_map=..., capacity_to_x=(slope,intercept))` が frame 同期の `EchemData` を返す。
- **期待される動作**: `EchemData.voltage` / `composition_x` が frame_index 位置に整列 (長さ = n_frames)。
- **入力値**: frame/voltage/capacity 列の小 CSV (n_frames 行) + `capacity_to_x=(slope,intercept)`。
- **期待される結果**: `len(echem.voltage) == n_frames` / `echem.composition_x[i] == pytest.approx(slope*Q_i + intercept)`。
  - **期待結果の理由**: `read_echem_csv` の "frame" 同期キー + 容量→組成線形換算 (実 API note §3.3)。
- **テストの目的**: 一気通貫の入口 (echem 同期) の正当性。
  - **確認ポイント**: 位置 index = frame_index、x 換算の一致。
- 🔵 対応 AC: TC-209-01 (echem CSV 同期) / REQ (FR-311 echem)。

### TC-035-06: segment_series が固定相込みで boundaries を返す 🔵
- **何をテストするか**: `segment_series(backend, series, INITIAL, fixed_phases=(AL,), ledger=ledger)` が `SegmentationResult` を返し `boundaries` が昇順 int tuple。
- **期待される動作**: `seg.boundaries` は昇順・端 0/n を含まない / `seg.n_segments == len(seg.boundaries)+1` / `seg.ledger` は注入 Ledger。
- **入力値**: 二相反応系列 + 固定相 AL。
  - **入力データの意味**: セル固定相を常駐させた区間分割 (FR-316 / FR-312)。
- **期待される結果**: `all(0 < b < series.n_frames for b in seg.boundaries)` / 昇順 / n_segments 整合。
  - **期待結果の理由**: `SegmentationResult.boundaries` 契約 (note §3.5)。
- **テストの目的**: "セル固定相込み逐次解析 + IC 区間分割" が公開 API で成立。
  - **確認ポイント**: 固定相 scale-only 解放で verdict/分割が破綻しない。
- 🔵 対応 AC: TC-209-01 (固定相 + 区間分割)。先例: `tests/test_segmentation.py` L406。

### TC-035-07: 区間ごとに discriminate_interval が verdict とマルチスタートを返す 🔵
- **何をテストするか**: `boundaries` から構成した各区間 `(start,end)` へ `discriminate_interval(...)` を適用し `DiscriminationResult` を得る。
- **期待される動作**: 各 `disc.verdict ∈ {"solid_solution","two_phase","undecided"}` / `disc.multistart_single`・`disc.multistart_two_phase` が `MultistartResult`。
- **入力値**: `discriminate_interval(backend, series, (start,end), INITIAL, fixed_phases=(AL,), config=DiscriminationConfig(multistart=MultistartConfig(n_starts=N)), ledger=ledger, queue=queue)`。
  - **入力データの意味**: 区間ごとの FR-313 判別 (端点マルチスタート必須)。
- **期待される結果**: verdict が 3 値のいずれか / `isinstance(disc.multistart_single, MultistartResult)` / `disc.multistart_single.n_starts == N`。
  - **期待結果の理由**: DiscriminationResult 契約 + マルチスタートは `config.multistart.n_starts` 本 (note §3.6)。
- **テストの目的**: "区間ごと FR-313 判別 (マルチスタート)" の結線。
  - **確認ポイント**: 二相区間で `two_phase` 傾向 (少なくとも 1 区間が非 undecided) を確認 (🟡 データ依存)。
- 🔵 対応 AC: TC-209-01 (区間判別)。先例: `tests/test_discrimination.py` L238/342。

### TC-035-08: combined_csv が echem 列入り CSV を書き出し読み戻せる 🔵
- **何をテストするか**: `combined_csv(trajectory, echem, path)` が trajectory + echem (V/I/Q/x) を frame_index 外部結合し CSV を書き、`csv.DictReader` で読み戻せる。
- **期待される動作**: 戻り値パスが実在し、ヘッダに wt_frac/格子 列 + voltage/composition_x 列を含む。非有限/None は空欄。
- **入力値**: `Trajectory` (設計判断②の入手経路) + `EchemData` + `tmp_path/combined.csv`。
- **期待される結果**: `Path(written).exists()` / DictReader で V/x 列が読める / セルに `inf`/`nan` 文字列が無い。
  - **期待結果の理由**: `combined_csv` 契約 (note §3.7 / TASK-0034 実装)。
- **テストの目的**: "結合出力 CSV" の生成・読み戻し。
  - **確認ポイント**: 非有限漏洩なし / 往復読み戻し。
- 🔵 対応 AC: TC-209-01 (結合出力 CSV) / FR-314。

### TC-035-09: 共有 ledger の verify() が True かつ entries 非空 🔵
- **何をテストするか**: 一気通貫で segment/discriminate へ注入した共有 `Ledger` が実行後に無傷。
- **期待される動作**: `ledger.verify() is True` かつ `len(ledger.entries) > 0`。
- **入力値**: fixture の共有 `Ledger`。
- **期待される結果**: True + 非空 (空 ledger の自明 True でない)。
  - **期待結果の理由**: 全操作が追記専用ハッシュチェーンに記録 (NFR-105 / P2)。
- **テストの目的**: "ledger verify" (監査整合)。
  - **確認ポイント**: segment と discriminate が同一チェーンに集約されている。
- 🔵 対応 AC: TC-209-01 (ledger verify) / NFR-105。

### TC-035-10: README M3 使用例コードが実行され完走する 🟡
- **何をテストするか**: README「使い方 (M3)」節と同等の写経コード (公開 API のみ) が例外なく実行される。
- **期待される動作**: import → 合成 → segment/discriminate → combined_csv → verify が完走し CSV が実在。
- **入力値**: README 記載の最小使用例と同等コード。
- **期待される結果**: 実行が完走し `Path(written).exists()` / `ledger.verify() is True`。
  - **期待結果の理由**: 完了条件⑤ (README M3 例の実行確認)。文面は Green で確定。
- **テストの目的**: ドキュメントと実 API シグネチャの乖離防止。
  - **確認ポイント**: README 変更時に破れる回帰ガード。
- 🟡 対応: 完了条件⑤ (README 文面は妥当な推測)。先例: `tests/test_m2_e2e.py::test_readme_m2_example_executes`。

### TC-035-11 (@gsas): GSASIIBackend でマルチスタート N=4 smoke が完走 (TC-209-02) 🔵
- **何をテストするか**: 実 GSAS-II で `MultistartEngine(GSASIIBackend(), config=MultistartConfig(n_starts=4)).run(phases, two_theta, intensity)` が破綻せず完走。
- **期待される動作**: `MultistartResult` を返し `basins` 非空 / `n_starts == 4`。
- **入力値**: 立方相 1 相 + `GRID_GSAS` の合成強度 (`backend.simulate`)。
  - **入力データの意味**: バックエンド交換 (P7) 後もマルチスタートが同契約で動くか。
- **期待される結果**: `isinstance(result, MultistartResult)` / `len(result.basins) >= 1` / `result.n_starts == 4`。
  - **期待結果の理由**: 完了条件③ (TC-209-02)。
- **テストの目的**: 実バックエンドでのマルチスタート smoke。
  - **確認ポイント**: GSAS-II 未導入は `conftest.py` が自動 skip。
- 🔵 対応 AC: TC-209-02。マーカー `@pytest.mark.gsas`。先例: `tests/test_m2_e2e.py` L497-519。

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-035-12: echem CSV の必須列欠損は ValueError 🔵
- **エラーケースの概要**: `column_map` が指す列が CSV に存在しない。
- **エラー処理の重要性**: 沈黙した誤同期を防ぎ fail-loud にする (M1/M2 教訓)。
- **入力値**: voltage 列を欠く CSV + `column_map={"frame":..,"voltage":"missing"}`。
  - **不正な理由**: 同期に必要な列が無い。
  - **発生シナリオ**: 機種違いの CSV・列名タイプミス。
- **期待される結果**: `pytest.raises(ValueError)`。
  - **システムの安全性**: 誤った EchemData を作らず即停止。
- **テストの目的**: echem 入口のバリデーション。
  - **品質保証の観点**: 下流 (combined_csv) への不正伝播を断つ。
- 🔵 対応: `read_echem_csv` 欠損列 ValueError (note §3.3)。

### TC-035-13: 判別 undecided はエスカレーションのみで例外化しない 🔵
- **エラーケースの概要**: 僅差/両仮説高 R で verdict が確定できない区間。
- **エラー処理の重要性**: 縮退 (エスカレーション) で処理をブロックせず一気通貫を止めない。
- **入力値**: 僅差を誘発する系列 (or 高 R 系列) で `discriminate_interval` を実行。
  - **不正な理由**: 判別材料が曖昧。
  - **発生シナリオ**: ノイズ・端成分分離不足。
- **期待される結果**: 例外を出さず `disc.verdict == "undecided"` かつ `disc.escalations` 非空 (queue へ通知)。
  - **システムの安全性**: 誤自動確定せず人間介入点へ回す。
- **テストの目的**: EDGE-002/005 の縮退挙動が E2E を破綻させないこと。
  - **品質保証の観点**: Dara 教訓 (降格のみ・候補除外しない) の遵守。
- 🔵 対応: EDGE-002/005 / 要件定義 §4。先例: `tests/test_discrimination.py` (E01/E02/E03)。

### TC-035-14: 単一セグメント (boundaries 空) でも完走する 🔵
- **エラーケースの概要**: `segment_series` が境界を検出せず `boundaries == ()` (単一区間)。
- **エラー処理の重要性**: 区間ループが 0 反復にならず区間 `(0, n-1)` 1 本を判別する。
- **入力値**: 固溶体 (格子連続変化) 系列で segment → boundaries 空。
  - **不正な理由**: 「異常」ではなく縮退境界 (エッジ)。
  - **発生シナリオ**: 相変化のない滑らかな operando 区間。
- **期待される結果**: 例外なく完走し `disc` が 1 区間分得られ `ledger.verify() is True`。
  - **システムの安全性**: 空境界でパイプラインがクラッシュしない。
- **テストの目的**: 区間ループの索引規約 (両端 inclusive) の堅牢性。
  - **品質保証の観点**: 最小構成での連続動作。
- 🔵 対応: 要件定義 §4 (区間数 1 の縮退)。

---

## 3. 境界値テストケース（最小値・最大値・決定論）

### TC-035-15: 同一入力 2 回実行で verdict/boundaries/CSV がビット同一 🔵
- **境界値の意味**: 決定論 (NFR-102) の境界 — 乱数・時刻・集合反復順に依存しないこと。
- **境界値での動作保証**: 2 回の独立実行で完全一致。
- **入力値**: 同一合成系列・同一 config で E2E を 2 回 (独立 Ledger)。
  - **境界値選択の根拠**: 再現性はビット同一が上限要件。
  - **使用場面**: 監査・再解析での完全再現。
- **期待される結果**: `[d.verdict for d in run1] == [d.verdict for d in run2]` / `seg1.boundaries == seg2.boundaries` / `csv1_bytes == csv2_bytes`。
  - **境界での正確性**: マルチスタートも `n_starts` 決定論 (seed 不使用)。
- **テストの目的**: NFR-102 (再現性)。
  - **堅牢性の確認**: 出力の完全一致。
- 🔵 対応: NFR-102 / REQ-402。先例: `tests/test_m2_e2e.py` L603。

### TC-035-16: `__all__` の全名称が実属性として解決できる 🔵
- **境界値の意味**: 公開契約 (`__all__`) と実装 (実属性) の乖離ゼロ。
- **境界値での動作保証**: dangling な名前が無い。
- **入力値**: `tsumugin.__all__` の全要素。
  - **境界値選択の根拠**: 追記時の typo・実体欠落の検出境界。
- **期待される結果**: `all(hasattr(tsumugin, name) for name in tsumugin.__all__)`。
  - **一貫した動作**: 宣言と実体が一致。
- **テストの目的**: 公開面の整合性。
  - **堅牢性の確認**: import 可能性の全数確認。
- 🔵 対応: 要件定義 §2.1。先例: `tests/test_m2_e2e.py` L326-327。

### TC-035-17: 判別 1 区間 (N=8) が 30 秒以内 (TC-209-03) 🟡
- **境界値の意味**: NFR-001 の性能境界。
- **境界値での動作保証**: 実用規模の最小担保。
- **入力値**: 二相系列 (n≈8) + `DiscriminationConfig(multistart=MultistartConfig(n_starts=8))` を 1 区間。
  - **境界値選択の根拠**: N=8 はマルチスタート既定下限 (FR-231)。
  - **使用場面**: operando 各区間のリアルタイム性。
- **期待される結果**: `time.perf_counter()` 経過 < 30.0 秒。
  - **境界での正確性**: 粗グリッド (step 0.05) + 小フレームで担保。
- **テストの目的**: NFR-001。
  - **堅牢性の確認**: CI 変動を見た閾値マージン。
- 🟡 対応 AC: TC-209-03 (性能閾値は妥当な推測)。

### TC-035-18: 空 FrameSeries など最小入力で縮退する 🟡
- **境界値の意味**: n_frames の最小境界 (空 / 1 フレーム)。
- **境界値での動作保証**: 空・単一入力でも例外化しない。
- **入力値**: `FrameSeries(GRID, np.empty((0, GRID.size)))` を segment_series に渡す。
  - **境界値選択の根拠**: 上流フィルタで全除外された等の縮退境界。
- **期待される結果**: 例外なく空/縮退結果 + `ledger.verify() is True` (segment_series の縮退規約に従う)。
  - **一貫した動作**: 空と複数区間の中間で連続的に動く。
- **テストの目的**: EDGE 縮退の堅牢性。
  - **堅牢性の確認**: E2E が最小入力でクラッシュしない。
- 🟡 対応: M0/M1/M2 縮退規約からの妥当な推測 (segment_series の空入力挙動は tdd-red で実挙動を確認して確定)。

---

## 4. 開発言語・フレームワーク

- 🔵 **プログラミング言語**: Python 3.12。
  - **言語選択の理由**: プロジェクト全体が Python (src layout + hatchling)、GSAS-II も Python API。
  - **テストに適した機能**: dataclass / typing.Protocol / frozen 不変性検証。
- 🔵 **テストフレームワーク**: pytest (>=8) + pytest-cov。`@pytest.mark.gsas` で GSAS-II 依存を分離 (`tests/conftest.py` が自動 skip)。
  - **フレームワーク選択の理由**: 既存テスト全てが pytest。fixture (module スコープ) / `pytest.approx` / `pytest.raises` / `pytest.warns` を活用。
  - **テスト実行環境**: `uv run pytest tests/test_operando_e2e.py` / `uv run pytest -m gsas` / `uv run pytest --cov=tsumugin` (90%+)。
- 🔵 信頼性: `pyproject.toml` / `tests/conftest.py` / 既存 E2E テストに直接依拠。

## 5. テストケース実装時の日本語コメント指針

各テストに `# 【テスト目的】/【テスト内容】/【期待される動作】` + 信頼性レベル、Given/When/Then に
`# 【テストデータ準備】/【実際の処理実行】/【結果検証】`、各 assert に `# 【確認内容】: ...` を付す
(先例: `tests/test_m2_e2e.py` / `tests/test_discrimination.py`)。module fixture `operando_run` に
`# 【テスト前準備】` を付す。

## 6. 要件定義との対応関係

- **参照した機能概要**: requirements §1 (公開 API 統合 + E2E + ドキュメント)
- **参照した入力・出力仕様**: requirements §2.1 (昇格シンボル), §2.2 (E2E データフロー)
- **参照した制約条件**: requirements §3 (NFR-001/102/105, REQ-403/404)
- **参照した使用例**: requirements §4 (一気通貫・エッジケース・設計判断)
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` TC-209-01〜03 (L82-85)
- **コンテキスト**: `docs/implements/m3-operando/TASK-0035/note.md` §3 (実 API), §5 (テスト情報), §6 (設計判断)

---

## テストケースサマリー

| カテゴリ | テストID | 件数 |
|---|---|---|
| 正常系 | TC-035-01〜11 (うち @gsas: TC-035-11) | 11 |
| 異常系 | TC-035-12〜14 | 3 |
| 境界値 | TC-035-15〜18 | 4 |
| **合計** | | **18** (うち @gsas 1 件) |

### 受け入れ基準 (AC) 対応
- **TC-209-01** (一気通貫) → TC-035-04〜09 (+ 決定論 TC-035-15)
- **TC-209-02** (@gsas マルチスタート N=4 smoke) → TC-035-11
- **TC-209-03** (性能 N=8 < 30 秒) → TC-035-17
- **公開 API 配線 / 後方互換** (完了条件① / REQ-404) → TC-035-01〜03, 16
- **README / ドキュメント** (完了条件⑤) → TC-035-10

### 信頼性レベル分布
- 🔵: 14 (78%) / 🟡: 4 (22%) / 🔴: 0 — **品質評価: 高品質**
- 🟡 の 4 件: README 文面 (TC-035-10) / 性能閾値 (TC-035-17) / 空入力縮退 (TC-035-18) / 二相判別のデータ依存傾向 (TC-035-07 の一部)。いずれも tdd-red で実挙動を確認し確定する。

## 品質判定

✅ **高品質**:
- テストケース分類: 正常系 11 / 異常系 3 / 境界値 4 で網羅 (配線・一気通貫・@gsas・性能・後方互換・決定論・エッジ)。
- 期待値定義: 各ケースに具体的期待値 (型・verdict 値域・`is` 一致・bytes 一致・時間境界) を明記。
- 技術選択: Python 3.12 + pytest 確定。
- 実装可能性: 依存 TASK-0023〜0034 完了・実 API 確認済み・M2 統合先例あり。
- 信頼性レベル: 🔵 が大半 (78%)。
