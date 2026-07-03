# TASK-0008 .gpx 書き出し export_gpx — TDD テストケース定義書

- **機能名**: .gpx 書き出し (`export_gpx` 新規実装 + `GSASIIBackend._build_project()` 抽出リファクタ)
- **タスクID**: TASK-0008
- **要件名**: m1-hypothesis-search
- **テストファイル**: `tests/test_gpx_export.py` (新規、`@pytest.mark.gsas`)
- **対象実装**: `src/tsumugin/export/gpx.py` (新規) / `src/tsumugin/backends/gsasii.py` (`_build_project()` 抽出) / `src/tsumugin/export/__init__.py` (re-export)
- **プログラミング言語**: Python >= 3.12 / **テストフレームワーク**: pytest >= 8 (+ pytest-cov)
- **マーカー方針**: GSAS-II 依存ケースは `@pytest.mark.gsas` (未導入環境では `conftest.py` が自動 skip)。未導入経路ケース (TC-006-03) は**マーカー無し** + `if gsasii_available(): pytest.skip(...)` 分岐。

---

## 0. テストケース一覧サマリー

| # | 分類 | テストID | テスト名 | マーカー | 信頼性 |
|---|------|----------|----------|----------|--------|
| 1 | 正常系 | TC-006-01a | 書き出した .gpx を再オープンでき相数が一致 | `@gsas` | 🔵 |
| 2 | 正常系 | TC-006-01b | 再オープンした相の格子定数 a/b/c が入力と一致 | `@gsas` | 🔵 |
| 3 | 正常系 | TC-006-02 | .gpx にヒストグラム (観測 Yobs) が含まれ入力 intensity と整合 | `@gsas` | 🔵 |
| 4 | 正常系 | TC-006-04 | 戻り値が書き出しパス str であり入力 path と一致 | `@gsas` | 🔵 |
| 5 | 正常系 | TC-006-05 | .gpx に計算パターン (Ycalc) が埋め込まれている | `@gsas` | 🔵 |
| 6 | 正常系 | TC-006-06 | 複数相を書き出し再オープンで全相の格子が一致 | `@gsas` | 🔵 |
| 7 | 正常系 | TC-006-07 | `export_gpx` が `tsumugin.export` から re-export され import 可能 | なし | 🔵 |
| 8 | 異常系 | TC-006-03 | GSAS-II 未導入環境で `GSASUnavailableError` を送出 | なし | 🟡 |
| 9 | 異常系 | TC-006-08 | 未導入経路は副作用ゼロで早期 raise (ファイルを生成しない) | なし | 🟡 |
| 10 | 境界値 | TC-006-09 | 単相 (最小の非空 phases=1) で正常に書き出せる | `@gsas` | 🔵 |
| 11 | 境界値 | TC-006-10 | TemporaryDirectory の with 脱出後も .gpx が再オープン可能 | `@gsas` | 🔵 |
| 12 | 境界値 | TC-006-11 | `weights=None` 既定と明示 `weights` の双方で書き出し成功 | `@gsas` | 🟡 |
| 13 | リグレッション | TC-006-12 | `_build_project()` 抽出後も既存 contract test 群が退行しない | `@gsas` + なし | 🔵 |
| 14 | リグレッション | TC-006-13 | gpx 構築が `_build_project()` 単一実装に統合されている (D-Q8) | なし | 🔵 |

**ケース数内訳**: 正常系 7 / 異常系 2 / 境界値 3 / リグレッション 2 = **合計 14**
（うち `@gsas` = 8、マーカー無し = 6。信頼性: 🔵 11 / 🟡 3 / 🔴 0）

---

## 1. 正常系テストケース（基本的な動作）

### TC-006-01a: 書き出した .gpx を再オープンでき相数が一致

- **テスト名**: 書き出した .gpx を GSASIIscriptable で再オープンでき相数が保存時と一致する
  - **何をテストするか**: `export_gpx()` が生成した `.gpx` を `G2sc.G2Project(<path>)` で開き直したとき、含まれる相の数が入力 `phases` の要素数と一致すること。
  - **期待される動作**: 有効な GSAS-II プロジェクトファイルが永続パスに生成され、再オープンした `project.phases()` の長さが入力相数に等しい。
- **入力値**:
  - `phases = (_phase(a=4.0, scale=1.0),)`（1 相）
  - `two_theta = np.arange(20.0, 80.0, 0.05)`、`intensity = backend.simulate(phases, two_theta)`（合成パターン）
  - `path = str(tmp_path / "out.gpx")`
  - **入力データの意味**: 既存 `tests/test_gsasii_backend.py` の `_phase()` / `_grid()` 慣習を踏襲し、GSAS-II が確実に計算できる直方晶 1 相 + 標準的な 2θ グリッドを代表値として選定。
- **期待される結果**: `len(G2sc.G2Project(path).phases()) == len(phases)`（= 1）。
  - **期待結果の理由**: TC-006-01 は「相数・格子定数が保存時と一致」を契約とする (acceptance-criteria L65-66)。相数一致は書き出し完全性の最小保証。
- **テストの目的**: `.gpx` が破損なく永続化され、GSAS-II GUI 互換のプロジェクトとして再オープンできることの確認。
  - **確認ポイント**: 永続パスにファイルが実在し、`G2Project` コンストラクタが例外なく開けること。
- 🔵 信頼性: acceptance-criteria TC-006-01 / note §4.4 完了条件① / 要件定義 §4.1 に明記。

### TC-006-01b: 再オープンした相の格子定数 a/b/c が入力と一致

- **テスト名**: 再オープンした各相の格子定数 a/b/c が入力 LatticeParams と近似一致する
  - **何をテストするか**: 再オープンした `project.phases()[i].get_cell()` の `length_a/b/c` が入力 `phases[i].lattice.a/b/c` と `pytest.approx` で一致すること。
  - **期待される動作**: 書き出し時の格子定数が `.gpx` に正しく保存され、再オープンで復元できる。
- **入力値**: TC-006-01a と同じ合成データ。参照キーは `get_cell()["length_a"]`（`gsasii.py::_read_back` L271-278 と同じアクセス）。
  - **入力データの意味**: CIF 簡約モデル (P m m m・Ni 1 原子) では相数・格子 a/b/c・角度までが再現検証可能な範囲 (要件定義 §3.7)。
- **期待される結果**: 各相について `cell["length_a"] == pytest.approx(4.0, abs=1e-3)`（b, c も同様）。
  - **期待結果の理由**: 0 サイクル `do_refinements` は格子を変えないため、書き出し値がそのまま復元される。
- **テストの目的**: 格子定数の永続化ラウンドトリップ (write → reopen → read) の正確性確認。
  - **確認ポイント**: `pytest.approx` の許容誤差 (格子定数近似は既存テストの `abs=0.005` 級) を踏襲。
- 🔵 信頼性: acceptance-criteria TC-006-01 / note §5「各相の get_cell() の a/b/c が入力 LatticeParams と pytest.approx 一致」に明記。

### TC-006-02: .gpx にヒストグラム (観測 Yobs) が含まれ入力 intensity と整合

- **テスト名**: 再オープンした project のヒストグラムが非空で観測 Yobs が入力 intensity と整合する
  - **何をテストするか**: 再オープンした `project.histograms()` が非空であり、その観測データ (Yobs) が書き出し時の `intensity` と整合すること。
  - **期待される動作**: `add_powder_histogram` 経由の観測ヒストグラムが `.gpx` に埋め込まれ、再オープンで観測強度を取り出せる。
- **入力値**: TC-006-01a と同じ合成データ。検証は `hist.getdata("Yobs")` 相当（または `hist.data["data"][1]` の Yobs 列）を入力 `intensity` と長さ・値で照合。
  - **入力データの意味**: `simulate` 生成の合成パターンは観測強度として意味のある非ゼロプロファイルを持ち、Yobs 埋め込みの検証に十分。
- **期待される結果**: `len(project.histograms()) >= 1` かつ Yobs 配列長が `intensity` と一致（値は補間/丸め差を許容し `pytest.approx` で照合）。
  - **期待結果の理由**: REQ-006「.gpx はヒストグラム (観測データ) を含む」/ TC-006-02 の契約 (acceptance-criteria L67)。
- **テストの目的**: 観測データが計算パターンとは別に保持され、GSAS-II GUI で観測 vs 計算を比較できることの確認。
  - **確認ポイント**: ヒストグラムが空でないこと、Yobs が計算値ではなく入力観測値であること。
- 🔵 信頼性: acceptance-criteria TC-006-02 / note §5 TC-006-02「histograms() が非空で観測 Yobs が入力 intensity と整合」に明記。

### TC-006-04: 戻り値が書き出しパス str であり入力 path と一致

- **テスト名**: export_gpx の戻り値が書き出した .gpx パス (str) であり入力 path と一致する
  - **何をテストするか**: `export_gpx(path, ...)` の戻り値が `str` 型で、値が入力 `path` と等しいこと。
  - **期待される動作**: 書き出し成功時、確定した永続パスを文字列で返す。
- **入力値**: `path = str(tmp_path / "out.gpx")`、他は TC-006-01a と同じ。
  - **入力データの意味**: 呼び出し元 (TASK-0010 の公開 API) が返却パスを利用するため、戻り値契約を明示。
- **期待される結果**: `result = export_gpx(path, ...)` に対し `isinstance(result, str)` かつ `result == path`、かつ `Path(result).exists()`。
  - **期待結果の理由**: 要件定義 §2.2「戻り値 str: 書き出しに成功した .gpx の永続パス (入力 path と一致)」。
- **テストの目的**: 戻り値の型・値契約とファイル実在の同時確認。
  - **確認ポイント**: 返却値がパスであること、実ファイルが存在すること。
- 🔵 信頼性: 要件定義 §2.2 出力仕様 / interfaces.py `-> str` に明記。

### TC-006-05: .gpx に計算パターン (Ycalc) が埋め込まれている

- **テスト名**: 書き出した .gpx に計算パターン Ycalc が埋め込まれている
  - **何をテストするか**: 再オープンした `.gpx` のヒストグラムに計算強度 (Ycalc) が存在し、全ゼロや未計算でないこと。
  - **期待される動作**: `max cyc = 0` → `do_refinements([{}])` を 1 度回すことで Ycalc が計算され `.gpx` に保存される。
- **入力値**: TC-006-01a と同じ合成データ。検証は `hist.getdata("Ycalc")` 相当が有限かつ非全ゼロであること。
  - **入力データの意味**: 回折ピークを持つ 1 相なので、Ycalc は明確な非ゼロプロファイルになる。
- **期待される結果**: Ycalc 配列が有限値 (`np.all(np.isfinite(...))`) かつ `np.any(ycalc > 0)`（未計算の全ゼロでない）。
  - **期待結果の理由**: 要件定義 §3.5 / REQ-006「計算パターン (Ycalc) 込みの .gpx」。回さないと Ycalc 未計算になる恐れ (note §6)。
- **テストの目的**: D5 の「計算パターン込み」契約と 0 サイクル `do_refinements` 手法の正しさ確認。
  - **確認ポイント**: Ycalc が観測 Yobs と別に存在し、GUI で計算曲線が描けること。
- 🔵 信頼性: 要件定義 §3.5 / architecture.md D5 / note §6「計算パターンの埋め込み」に明記。

### TC-006-06: 複数相を書き出し再オープンで全相の格子が一致

- **テスト名**: 複数相 (2 相) を書き出し再オープンで相数と全相の格子定数が一致する
  - **何をテストするか**: `phases` に 2 相を渡した場合、再オープンで相数が 2、各相の格子 a/b/c が入力と一致すること。
  - **期待される動作**: `_add_phases` が全相を追加し、複数相が独立に永続化される。
- **入力値**: `phases = (_phase(a=4.0, ref="A"), _phase(a=5.0, ref="B"))`、`intensity = backend.simulate(phases, tt)`。
  - **入力データの意味**: 単相だけでなく多相混合の書き出しを保証する（探索結果は複数相集合になりうる）。
- **期待される結果**: `len(project.phases()) == 2` かつ各相の `get_cell()` の a が 4.0 / 5.0 と `pytest.approx` 一致。
  - **期待結果の理由**: `phases: Sequence[PhaseInstance]` は複数要素を許容し、相数一致は全要素に対する契約。
- **テストの目的**: 複数相ケースでの相数・格子の網羅的一致確認。
  - **確認ポイント**: 相の順序が保持され、各相の格子が取り違えられないこと。
- 🔵 信頼性: 入力仕様 (Sequence[PhaseInstance]) + TC-006-01 契約からの妥当な網羅拡張。

### TC-006-07: export_gpx が tsumugin.export から re-export され import 可能

- **テスト名**: export_gpx が tsumugin.export パッケージから import できる
  - **何をテストするか**: `from tsumugin.export import export_gpx` および `from tsumugin.export.gpx import export_gpx` が成功し、callable であること。
  - **期待される動作**: `export/__init__.py` に `from .gpx import export_gpx` が追加され `__all__` に含まれる。
- **入力値**: import 文のみ（GSAS-II 不要 — 関数オブジェクトの解決のみで実行はしない）。
  - **入力データの意味**: re-export はモジュール読込のみで検証でき、GSAS-II 導入状態に依存しない。
- **期待される結果**: `callable(export_gpx)` が True、`"export_gpx" in tsumugin.export.__all__`。
  - **期待結果の理由**: 要件定義 §「公開 API」/ note §3.3「export/__init__.py に export_gpx を re-export に追加」。
- **テストの目的**: パッケージ公開面の配線 (re-export) が正しいことの確認。
  - **確認ポイント**: マーカー無しで常時実行され、import 経路が壊れていないこと。
- 🔵 信頼性: note §3.3 / 要件定義 §5「export/__init__.py に from .gpx import export_gpx を追加」に明記。

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-006-03: GSAS-II 未導入環境で GSASUnavailableError を送出

- **テスト名**: GSAS-II 未導入環境で export_gpx が GSASUnavailableError を送出する
  - **エラーケースの概要**: `gsasii_available()` が False の環境で `export_gpx()` を呼ぶと、書き出しに入る前に `GSASUnavailableError` を送出する。
  - **エラー処理の重要性**: 書き出しは GSASIIscriptable の保存 API に本質的に依存するため、未導入で暗黙に失敗させず明示的に通知する必要がある (REQ-105)。
- **入力値**: 任意の有効引数（`phases`, `two_theta`, `intensity`）。**テスト前段で `if gsasii_available(): pytest.skip("GSAS-II is installed; unavailable path not exercised")`**。
  - **不正な理由**: 未導入環境そのものが「実行不能な前提」であり、入力値の不正ではなく環境の欠如が原因。
  - **実際の発生シナリオ**: GSAS-II を導入していない解析環境・CI で書き出しを試みた場合。**本環境は導入済みのため skip される**（契約として定義）。
- **期待される結果**: `with pytest.raises(GSASUnavailableError): export_gpx(...)`。
  - **エラーメッセージの内容**: 既存 `GSASIIBackend.__init__` のメッセージ（GSAS-II 導入 or SimulatedBackend 使用を促す）が再利用される想定。
  - **システムの安全性**: 早期 raise により中途半端なファイルを残さない (§3.2 非破壊)。
- **テストの目的**: REQ-105 の未導入通知契約と、`test_backend_raises_when_unavailable` (L25-29) と同一パターンの担保。
  - **品質保証の観点**: 依存欠如を握り潰さず、呼び出し元が回復・代替 (SimulatedBackend) を選べるようにする。
- 🟡 信頼性: acceptance-criteria TC-006-03 / 要件定義 §4.3 に定義があるが、導入済み環境では skip されるため本環境では未実行（黄信号）。

### TC-006-08: 未導入経路は副作用ゼロで早期 raise (ファイルを生成しない)

- **テスト名**: 未導入経路では出力パスにファイルを生成せず副作用ゼロで raise する
  - **エラーケースの概要**: 未導入で `GSASUnavailableError` を送出する際、出力 `path` にファイル (作りかけの .gpx) を残さない。
  - **エラー処理の重要性**: 非破壊・冪等性 (P2 / NFR-101)。失敗が中途生成物として残るとワークフローを汚染する。
- **入力値**: `path = str(tmp_path / "out.gpx")`（存在しないパス）。前段で `if gsasii_available(): pytest.skip(...)`。
  - **不正な理由**: 未導入という前提欠如下での呼び出し。
  - **実際の発生シナリオ**: 未導入環境で書き出しを試み、その後ディレクトリを検査する運用。
- **期待される結果**: `pytest.raises(GSASUnavailableError)` の後 `not Path(path).exists()`（ファイル未生成）。
  - **エラーメッセージの内容**: TC-006-03 と同じ例外。
  - **システムの安全性**: 判定 (`gsasii_available()`) が書き出し処理の**前**に行われ、ファイル作成の副作用が発生しない。
- **テストの目的**: 「書き出し処理に入る前に副作用ゼロで raise」(要件定義 §2.2 / §3.2) の担保。
  - **品質保証の観点**: エラー時のクリーンな状態保証。導入済み環境では skip。
- 🟡 信頼性: 要件定義 §3.2「ファイルを作りかけて失敗する状態を残さない」からの妥当な検証（導入済みでは skip のため黄信号）。

---

## 3. 境界値テストケース（最小値、最大値、null等）

### TC-006-09: 単相 (最小の非空 phases=1) で正常に書き出せる

- **テスト名**: 単相 (phases 長 1) の最小構成で書き出しと再オープンが成功する
  - **境界値の意味**: `phases` は「空でないこと」が制約 (要件定義 §2.1)。長さ 1 は許容される最小の非空境界。
  - **境界値での動作保証**: 最小要素数でも相追加・書き出しが破綻しない。
- **入力値**: `phases = (_phase(a=4.0, scale=1.0),)`（長さ 1）。
  - **境界値選択の根拠**: 非空 Sequence の下限。多相 (TC-006-06) の対極として最小境界を固定。
  - **実際の使用場面**: 単一相の同定結果を書き出す最も一般的なケース。
- **期待される結果**: 書き出し成功、`len(project.phases()) == 1`、格子 a が 4.0 と一致。
  - **境界での正確性**: 1 相でもヒストグラム・Ycalc・格子が正しく保存される。
  - **一貫した動作**: TC-006-06 (複数相) と同じ検証が長さ 1 でも成立。
- **テストの目的**: 非空下限境界での堅牢性確認。
  - **堅牢性の確認**: 最小構成で機能全体 (write→reopen→verify) が通ること。
- 🔵 信頼性: 要件定義 §2.1「空でないこと」/ TC-006-01 の基本ケースが実質単相であることに一致。

### TC-006-10: TemporaryDirectory の with 脱出後も .gpx が再オープン可能

- **テスト名**: 作業一時ディレクトリ破棄後も永続 .gpx が有効に再オープンできる
  - **境界値の意味**: instprm/xye/cif は一時ディレクトリに置くが、`.gpx` 本体だけ永続パスに置く分離設計 (§3.4) の境界。with ブロック脱出＝一時補助ファイル消滅のタイミングが境界。
  - **境界値での動作保証**: 補助ファイル参照が gpx に埋め込まれても、消滅後の再オープンに支障がない。
- **入力値**: `path = str(tmp_path / "out.gpx")`（`export_gpx` 内部の TemporaryDirectory とは別の pytest tmp_path）。`export_gpx` 呼び出し完了（＝内部 with 脱出）後に `G2sc.G2Project(path)` を実行。
  - **境界値選択の根拠**: 「TemporaryDirectory の with ブロックを抜けた後もファイルとして残る」保証が最重要な実装制約 (note §6 / §3.4)。
  - **実際の使用場面**: `export_gpx` は関数戻り後にユーザ/後続処理が `.gpx` を開く。関数内一時ディレクトリは既に消えている。
- **期待される結果**: 関数戻り後の `G2sc.G2Project(path)` が例外なく開け、相数・格子が一致（TC-006-01 相当の検証が「後から」成立）。
  - **境界での正確性**: `gpx.save()` が with ブロック内で完了し、永続ファイルが自己完結していること。
  - **一貫した動作**: 呼び出し直後でも後からでも再オープン結果が同一。
- **テストの目的**: 一時ディレクトリと永続 gpx の分離設計 (§3.4) の実効性検証。
  - **堅牢性の確認**: 補助ファイル消滅という極端条件下でも .gpx が壊れない。
- 🔵 信頼性: 要件定義 §3.4 / note §6「TemporaryDirectory 消滅後の永続性」/ §4.5 に明記。

### TC-006-11: weights=None 既定と明示 weights の双方で書き出し成功

- **テスト名**: weights=None 既定と明示 weights 配列の双方で書き出しが成功する
  - **境界値の意味**: `weights` は kw-only の nullable 引数。`None`（既定＝統計重み）と明示配列の 2 経路が境界。
  - **境界値での動作保証**: `_write_xye` の重み分岐 (L89-92) の双方が export 経路で機能する。
- **入力値**:
  - ケースA: `weights` 未指定（`None` → `esd = sqrt(max(intensity, 1.0))`）
  - ケースB: `weights = np.ones_like(intensity)`（明示 → `esd = 1/sqrt(max(weights, 1e-12))`）
  - **境界値選択の根拠**: nullable の両側 (None / 非None) を代表。既定挙動と明示挙動の分岐網羅。
  - **実際の使用場面**: 観測重みが利用可能な場合とそうでない場合の双方。
- **期待される結果**: 双方とも書き出し成功し、`G2Project(path)` で再オープンでき相数・格子が一致（重みは esd に反映されるが相数・格子の一致は不変）。
  - **境界での正確性**: 重み指定の有無で書き出し完全性が損なわれない。
  - **一貫した動作**: 両経路で `.gpx` が有効。
- **テストの目的**: kw-only nullable 引数 `weights` の両分岐の実行担保。
  - **堅牢性の確認**: 既定パラメータ経路と明示経路の等価な健全性。
- 🟡 信頼性: 入力仕様 §2.1 (`weights: np.ndarray | None = None`) と `_write_xye` の既存分岐からの妥当な推測（重み反映値の厳密検証まではしない黄信号）。

---

## 4. リグレッション / リファクタ不変性テスト（完了条件④⑤）

### TC-006-12: _build_project() 抽出後も既存 contract test 群が退行しない

- **テスト名**: _build_project() 抽出リファクタ後も既存 GSASIIBackend contract tests が全 green
  - **何をテストするか**: `tests/test_gsasii_backend.py` の @gsas 6 件 + 未導入経路 1 件 (`test_backend_raises_when_unavailable`) + `test_gsasii_available_returns_bool_without_raising` が退行しないこと。
  - **期待される動作**: `refine` / `simulate` の結果 (chi2/rwp/読み戻し/converged) が 1 ビットも変わらない挙動不変リファクタ。
- **入力値**: 既存テストの入力（`_phase()` / `_grid()` ベース、スケール・格子回復シナリオ）をそのまま使用。
  - **入力データの意味**: 抽出前後で同一入力に対し同一出力になることが D-Q8 リファクタの安全性契約。
- **期待される結果**: `uv run pytest tests/test_gsasii_backend.py` が全 pass（@gsas 6 + unavailable 1、実質 contract 7 群）。
  - **期待結果の理由**: 要件定義 §3.1 / 完了条件④「GSASIIBackend の既存 contract tests が退行しない」。
- **テストの目的**: 「挙動不変の Refactor」であることの安全網（抽出前 green → 抽出 → 再度 green）。
  - **確認ポイント**: 本テストは新規テストを追加せず、既存テストスイートを Green フェーズで必ず走らせることで担保（実装ノート）。
- 🔵 信頼性: 要件定義 §3.1 / note §5 完了条件④ / TASK-0008.md 完了条件に明記。

### TC-006-13: gpx 構築が _build_project() 単一実装に統合されている (D-Q8)

- **テスト名**: refine と export_gpx が単一の _build_project() ヘルパを共有している
  - **何をテストするか**: `GSASIIBackend._build_project` が存在し、`refine` と `export_gpx` の gpx 構築が同一実装 (単一情報源) に統合されていること。
  - **期待される動作**: gpx 構築 (instprm/xye 書き出し + `G2Project(newgpx=...)` + `add_powder_histogram` + `_add_phases`) が重複せず 1 箇所に集約。
- **入力値**: 構造的検証（`hasattr(GSASIIBackend, "_build_project")`）+ `export_gpx` が内部で `_build_project` を経由すること（動作面は TC-006-01/02 が担保）。
  - **入力データの意味**: D-Q8 の「重複実装しない」設計判断を構造レベルで固定化。
- **期待される結果**: `_build_project` が `GSASIIBackend` の属性として存在し callable。`export_gpx` 実行が `refine` と同じヘルパ経路で gpx を構築する（TC-006-01/02 の成功 = 経路の健全性）。
  - **期待結果の理由**: 完了条件⑤ / D-Q8「gsasii.py の gpx 構築が単一実装に統合」。
- **テストの目的**: 単一情報源リファクタ (D-Q8) の構造的担保。
  - **確認ポイント**: `simulate` は別経路 (`add_simulated_powder_histogram`) のため共有対象外である点に注意。
- 🔵 信頼性: 要件定義 §4.5 / note §4.3 D-Q8 / 完了条件⑤ に明記。

---

## 5. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 (CPython)
  - **言語選択の理由**: プロジェクト全体が Python + src layout (hatchling)。GSAS-II (GSASIIscriptable) が Python API であり、`.gpx` 生成は Python から呼ぶのが自然。
  - **テストに適した機能**: frozen dataclass による不変モデル、`typing.Protocol` 境界、pytest との親和性。
- **テストフレームワーク**: pytest >= 8 (+ pytest-cov)
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `addopts="-q"`) と既存テスト群がすべて pytest。`@pytest.mark.gsas` マーカー + `conftest.py` の自動 skip 機構を再利用。
  - **テスト実行環境**: 導入コマンド `uv sync --extra gsas`、実行 `uv run pytest tests/test_gpx_export.py` / `uv run pytest -m gsas` / `uv run pytest --cov=tsumugin`。本環境は GSAS-II 導入済み (`C:\Users\tomoo\G2` + venv `.pth` + バイナリ) のため `@gsas` は実行される。
- 🔵 信頼性: note §1 技術スタック / §5 テスト関連情報 / `pyproject.toml` に明記。

---

## 6. テストケース実装時の日本語コメント指針

各テストケースの実装時には以下の日本語コメントを必ず含めること。

### テストケース開始時のコメント

```python
# 【テスト目的】: 書き出した .gpx を再オープンでき相数・格子が一致することを確認する
# 【テスト内容】: export_gpx で永続 .gpx を生成 → G2sc.G2Project で再オープン → phases() を照合
# 【期待される動作】: 相数が入力と一致し、各相の get_cell() の a/b/c が入力 LatticeParams と近似一致
# 🔵 信頼性: acceptance-criteria TC-006-01 に基づく
```

### Given（準備フェーズ）のコメント

```python
# 【テストデータ準備】: _phase()/_grid() で直方晶 1 相と標準 2θ グリッドを用意する理由
# 【初期条件設定】: backend.simulate で観測相当の合成 intensity を生成し書き出し入力とする
# 【前提条件確認】: @gsas マーカーにより GSAS-II 導入環境でのみ実行される
```

### When（実行フェーズ）のコメント

```python
# 【実際の処理実行】: export_gpx(path, phases, tt, y) を呼び出し永続 .gpx を書き出す
# 【処理内容】: _build_project による gpx 構築 → max cyc=0 do_refinements (Ycalc) → save()
# 【実行タイミング】: 内部 TemporaryDirectory 脱出後に返却パスへ .gpx が残ることを前提に検証
```

### Then（検証フェーズ）のコメント

```python
# 【結果検証】: 返却パスの .gpx を G2Project で再オープンし相数・格子を照合する
# 【期待値確認】: len(project.phases()) == len(phases)、a/b/c が pytest.approx 一致
# 【品質保証】: GSAS-II GUI 互換の永続 .gpx が破損なく生成されることを保証する
```

### 各 expect（assert）ステートメントのコメント

```python
# 【検証項目】: 再オープンした相数が入力相数と一致すること 🔵
assert len(project.phases()) == len(phases)  # 【確認内容】: 書き出し完全性 (全相保存)
# 【検証項目】: 各相の格子 a が入力と近似一致すること 🔵
assert cell["length_a"] == pytest.approx(4.0, abs=1e-3)  # 【確認内容】: 格子ラウンドトリップ正確性
```

### セットアップ・クリーンアップのコメント

```python
# tmp_path フィクスチャを使用し、永続 .gpx はテストごとに隔離された一時ディレクトリへ書き出す
# （pytest tmp_path はテスト終了後に自動回収されるため明示的な afterEach クリーンアップは不要）
```

---

## 7. 要件定義との対応関係

- **参照した機能概要**: 要件定義書 §1（`export_gpx` = 相集合 + 観測パターン → GSAS-II GUI 互換 .gpx 書き出し。REQ-006 / FR-505 / 設計 D5）
- **参照した入力・出力仕様**: 要件定義書 §2.1（`export_gpx(path, phases, two_theta, intensity, *, weights=None, wavelength=1.5406) -> str` の型契約）、§2.2（戻り値 str・副作用・例外）、§2.3（処理フロー）
- **参照した制約条件**: 要件定義書 §3.1（挙動不変リファクタ / 完了条件④）、§3.2（非破壊性）、§3.3（未導入 raise）、§3.4（一時ディレクトリと永続 gpx の分離）、§3.5（Ycalc 埋め込み）、§3.7（CIF 簡約モデルの検証範囲 = 相数・格子 a/b/c・角度）
- **参照した使用例**: 要件定義書 §4.1（TC-006-01）、§4.2（TC-006-02）、§4.3（TC-006-03 未導入経路）、§4.5（退行なし・単一情報源・永続性）
- **参照した受け入れ基準**: acceptance-criteria.md L63-68（TC-006-01 / TC-006-02 / TC-006-03）
- **参照した設計文書 / 既存実装**: note.md（§3 抽出リファクタ対象・§4 契約・§5 テスト関連・§6 注意事項）、`src/tsumugin/backends/gsasii.py`（`refine` L167-233 の gpx 構築ブロック・`_add_phases`・`_write_xye`・`_read_back` の `get_cell()` キー）、`tests/test_gsasii_backend.py`（`_phase()`/`_grid()` ヘルパ・`@pytest.mark.gsas`・退行対象 contract 群）、`tests/conftest.py`（@gsas 自動 skip）

---

## 8. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 7 / 異常系 2 / 境界値 3 / リグレッション 2 = 14 件で網羅
  （再オープン相数・格子・Yobs・Ycalc・戻り値・複数相・re-export／未導入 raise・副作用ゼロ／
   単相下限・永続性・weights 両分岐／既存退行・単一情報源）
- 期待値定義: 各ケースに具体的な assert (pytest.approx 許容誤差・G2Project 再オープン・exists 判定) を明記
- 技術選択: Python 3.12 + pytest + @pytest.mark.gsas（conftest 自動 skip）で確定
- 実装可能性: 既存 gsasii.py の API (get_cell/histograms/getdata/do_refinements) と test_gsasii_backend.py の書式で実現可能
- 信頼性レベル: 🔵 11 / 🟡 3 / 🔴 0 — 🔵 優勢
```

- **信頼性内訳**: 🟡 3 件 = TC-006-03 / TC-006-08（未導入経路は導入済み本環境では skip され未実行）、TC-006-11（weights 反映値の厳密検証はしない）。いずれも要件・既存パターンに根拠があり赤信号なし。
- **実装時に TDD で確定する事項**: (a) `hist.getdata("Yobs"/"Ycalc")` の正確なアクセス法（`hist.data["data"][1]` 列インデックス vs `getdata`）、(b) `project.phases()[i].get_cell()` の戻り値キー (`length_a` 等) の再オープン時整合、(c) `_build_project()` の最終シグネチャ。

---

## 次のステップ

次のお勧めステップ: `/tsumiki:tdd-red m1-hypothesis-search TASK-0008` で Red フェーズ（失敗テスト作成）を開始します。
