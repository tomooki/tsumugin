# TASK-0017 TDD テストケース定義書: Trajectory + FrameRecord + to_csv

**機能名**: trajectory-csv / **要件名**: m2-sequential / **タスクID**: TASK-0017
**出力ファイル**: `docs/implements/m2-sequential/TASK-0017/trajectory-csv-testcases.md`
**テストファイル**: `tests/test_trajectory.py` (新規) / **作成日**: 2026-07-03

> すべてのファイルパスはプロジェクトルートからの相対パス。
> 【信頼性凡例】🔵 要件/設計にほぼ依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

## テストケースサマリー

| 分類 | 件数 | テスト ID |
|---|---|---|
| 正常系 | 6 | T-N01〜T-N06 |
| 異常系 | 4 | T-E01〜T-E04 |
| 境界値 | 7 | T-B01〜T-B07 |
| **合計** | **17** | |

**受け入れ基準対応**: TC-104-01 → T-N01 / TC-104-02 → T-N02 / TC-104-03 → T-E01 / REQ-402(完了条件④) → T-B05。

---

## 0. 共通テストフィクスチャ (Given の土台) 🔵

- 書き出し先は pytest `tmp_path` フィクスチャ (`tmp_path / "traj.csv"`) を使う (TASK-0017.md 明記)。
- 相の生成: `PhaseInstance(phase_ref="A", lattice=LatticeParams(a=5.0, b=6.0, c=7.0), scale=1.0, wt_frac=0.5)` を基本に、必要な相 (A/B) を組む (`src/tsumugin/model/phase.py`)。
- lifecycle: `PhaseLifecycle(birth_frame=0, death_frame=None, confidence=1.0)` を `lifecycles={"A": ...}` に入れる。
- import: `from tsumugin.sequential import FrameRecord, Trajectory` / `from tsumugin.model import PhaseInstance, PhaseLifecycle, LatticeParams`。
- 読み戻し: stdlib `import csv` の `csv.reader` / `csv.DictReader` を使用。

---

## 1. 正常系テストケース

### T-N01: 必須列がヘッダに含まれる (TC-104-01) 🔵
- **何をテストするか**: `to_csv` が生成する CSV のヘッダ行に必須列 (軸値・相ごと格子 a/b/c・scale・wt_frac・Rwp・changepoint・lifecycle birth/death/confidence) が全て含まれること。
- **期待される動作**: ヘッダに `frame_index, axis_value, temperature, rwp, chi2, changepoint, changepoint_reasons, refine_failed` と、相 A について `A.a, A.b, A.c, A.scale, A.wt_frac, A.birth_frame, A.death_frame, A.confidence` (列名規約は実装で凍結) が現れる。
- **入力値**: 相 A を含む `FrameRecord` 2 件 + `lifecycles={"A": PhaseLifecycle(0, None, 1.0)}` の `Trajectory`。
  - **入力の意味**: 完了条件①「必須列」を満たすか最小構成で確認。
- **期待される結果**: `csv.reader` の 1 行目 (ヘッダ) に上記列名が部分集合として含まれる。軸値列 (`axis_value`)・相ごと格子/scale/wt_frac・`rwp`・`changepoint`・lifecycle 列が全て存在。
  - **期待結果の理由**: TC-104-01 が列の存在を要求。
- **確認ポイント**: 列の欠落がないこと。列名は実装確定後に定数で固定しテストで凍結。
- 🔵 (TC-104-01 / interfaces.py L141-165 / 完了条件①)

### T-N02: to_csv 読み戻し・行数=フレーム数 (TC-104-02) 🔵
- **何をテストするか**: `to_csv(path)` が `csv.reader` で読み戻せるファイルを生成し、**データ行数 (ヘッダ除く) == `len(records)`** であること。
- **期待される動作**: ヘッダ 1 行 + フレーム数分のデータ行。
- **入力値**: `records` 長 3 の `Trajectory`。
  - **入力の意味**: 「行数 = フレーム数」を代表的な複数フレームで検証。
- **期待される結果**: `rows = list(csv.reader(open(path, newline="")))`; `len(rows) == 1 + 3` かつヘッダ除くと 3 行。`DictReader` でも 3 レコード。
  - **期待結果の理由**: TC-104-02 の中核 (1 フレーム 1 行)。
- **確認ポイント**: ヘッダを二重カウントしない。`to_csv` の戻り値パスがそのまま読める。
- 🔵 (TC-104-02 / 完了条件②)

### T-N03: フレーム共通列の値が正しく往復する 🔵
- **何をテストするか**: `frame_index / axis_value / temperature / rwp / chi2 / changepoint / refine_failed` の各値が CSV セルに正しく反映されること (有限値・True/False)。
- **期待される動作**: `DictReader` で読んだ各セルが元の値と対応 (数値は文字列化、bool は実装凍結の表現)。
- **入力値**: `FrameRecord(frame_index=5, axis_value=300.0, temperature=305.0, phases=(A,), rwp=2.5, chi2=1.3, changepoint=True, changepoint_reasons=("rwp_jump",), refine_failed=False)`。
  - **入力の意味**: 全共通列に有限・非 None 値を与え往復同一性を確認。
- **期待される結果**: `row["frame_index"]=="5"`, `row["axis_value"]=="300.0"`, `row["temperature"]=="305.0"`, `row["rwp"]=="2.5"`, `row["chi2"]=="1.3"`, `changepoint` セルが真表現, `refine_failed` セルが偽表現。
  - **期待結果の理由**: 完了条件① の軸値/Rwp/changepoint を値レベルで担保。
- **確認ポイント**: `float` の文字列化が決定論。`bool` 表現 (`True`/`1` 等) を凍結。
- 🔵 (interfaces.py L141-153 / 完了条件①)

### T-N04: 相ごと列 (格子/scale/wt_frac/lifecycle) の値が正しい 🔵
- **何をテストするか**: 相 A の `lattice.a/b/c`・`scale`・`wt_frac`、および `lifecycles["A"]` の `birth_frame/death_frame/confidence` が対応する相列セルに入ること。
- **期待される動作**: 相の存在するフレーム行で `A.a==5.0` 等が入り、lifecycle 列は全行で同じ値 (相単位のメタ)。
- **入力値**: A=`PhaseInstance("A", LatticeParams(5.0,6.0,7.0), scale=1.0, wt_frac=0.5)`, `lifecycles={"A": PhaseLifecycle(2, 8, 0.75)}`。
  - **入力の意味**: 相ごとの格子・分率・寿命を代表値で検証。
- **期待される結果**: `row["A.a"]=="5.0"`, `row["A.b"]=="6.0"`, `row["A.c"]=="7.0"`, `row["A.scale"]=="1.0"`, `row["A.wt_frac"]=="0.5"`, `row["A.birth_frame"]=="2"`, `row["A.death_frame"]=="8"`, `row["A.confidence"]` が 0.75 相当。
  - **期待結果の理由**: 完了条件①「相ごと格子 abc/scale/wt_frac + lifecycle」。
- **確認ポイント**: lifecycle 列がフレーム行ではなく相のメタとして全行一貫。`death_frame=None` でないケースを確認。
- 🔵 (完了条件① / interfaces.py L31-45,141-153)

### T-N05: to_csv の戻り値が入力パスと一致 🔵
- **何をテストするか**: `to_csv(path)` の戻り値が `str` で、渡した `path` と等しいこと (`export_gpx` 同一契約)。
- **入力値**: `path = str(tmp_path / "out.csv")`。
- **期待される結果**: `traj.to_csv(path) == path` かつ `os.path.exists(path)` True。
  - **期待結果の理由**: interfaces.py L163 の戻り値契約。
- **確認ポイント**: 戻り値型が `str`。ファイルが実在。
- 🔵 (interfaces.py L163-165 / gpx.py 契約)

### T-N06: changepoint_reasons (tuple) が決定論的に 1 セル化される 🟡
- **何をテストするか**: `changepoint_reasons=("rwp_jump","new_peaks")` が単一 CSV セルへ決定論区切りで連結されること。
- **期待される動作**: 区切り文字 (例 `|`) で `rwp_jump|new_peaks` の形。CSV デリミタ `,` と衝突しない。
- **入力値**: `changepoint=True, changepoint_reasons=("rwp_jump","new_peaks")`。
  - **入力の意味**: 複数理由の説明可能性 (FR-303) を CSV に落とす。
- **期待される結果**: `row["changepoint_reasons"] == "rwp_jump|new_peaks"` (区切りは実装凍結)。空 tuple は空欄。
  - **期待結果の理由**: 説明可能性を保ちつつ 1 セル 1 行構造を維持。
- **確認ポイント**: 連結順が tuple 順で決定論。区切り文字が `,`/改行を含まない。
- 🟡 (要件 §2.3 の 1 セル化は実装確定事項)

---

## 2. 異常系テストケース

### T-E01: 失敗フレームで rwp/chi2 が空欄・非有限がファイルに漏れない (TC-104-03) 🔵
- **エラーケースの概要**: 精密化失敗フレーム (`rwp=None`, `chi2=float("inf")`, `refine_failed=True`) の CSV 化。
- **エラー処理の重要性**: `inf`/`nan` が文字列で CSV に混入すると外部ツールで破損 (M1 レビュー教訓)。
- **入力値**: `FrameRecord(..., rwp=None, chi2=float("inf"), refine_failed=True)` を含む `Trajectory`。
  - **不正な理由**: `None`/非有限は数値セルとして無効。
  - **発生シナリオ**: バックエンド失敗 → chi2=inf 変換 (CLAUDE.md 不変条件) の下流。
- **期待される結果**: `row["rwp"]==""` かつ `row["chi2"]==""`。ファイル全文 (テキスト) に `"inf"`/`"nan"`/`"Infinity"`/`"NaN"` が**出現しない**。`refine_failed` セルは真表現。
  - **システムの安全性**: 空欄化で読み戻しが数値欠損として一貫。
- **品質保証の観点**: 完了条件③ の直接検証。`store/serialization.py _finite_or_none` と同思想。
- 🔵 (TC-104-03 / 完了条件③ / M1 教訓)

### T-E02: 相の wt_frac / 格子が非有限のとき空欄化 🟡
- **エラーケースの概要**: `PhaseInstance(wt_frac=float("nan"))` や `LatticeParams(a=float("inf"))` の相列。
- **入力値**: 相 A の `wt_frac=float("nan")`。
  - **発生シナリオ**: 精密化縮退で分率/格子が発散。
- **期待される結果**: `row["A.wt_frac"]==""`。ファイルに `nan`/`inf` 文字列が出ない。
  - **システムの安全性**: 数値セルは常に純化を経由する保証。
- **品質保証の観点**: 非有限純化が共通列だけでなく相列にも適用されることを担保。
- 🟡 (完了条件③ を相列へ拡張した妥当な推測)

### T-E03: axis_value / temperature が None のとき空欄 🔵
- **エラーケースの概要**: index 軸 (`axis_value=None`) やチャネル欠損 (`temperature=None`, EDGE-102) フレーム。
- **入力値**: `FrameRecord(axis_value=None, temperature=None, ...)`。
  - **発生シナリオ**: index 軸のシーケンス / 温度チャネル欠損フレーム。
- **期待される結果**: `row["axis_value"]==""` かつ `row["temperature"]==""`。例外は発生しない。
  - **システムの安全性**: None を空欄化し、読み戻しで欠損として扱える。
- **品質保証の観点**: `None` (欠損) と非有限 (縮退) を同じ空欄で表現する一貫性。
- 🔵 (interfaces.py L143-147 / EDGE-102)

### T-E04: 相なしフレーム (phases=()) で相列が空欄・例外なし 🟡
- **エラーケースの概要**: `phases=()` のフレーム (未確定/全消滅) でも CSV 化が成功すること。
- **入力値**: `records` に `phases=()` のフレームと `phases=(A,)` のフレームを混在。
  - **発生シナリオ**: 立ち上げ直後や全相消滅区間。
- **期待される結果**: 相 A の列は `phases=()` のフレーム行で全て空欄、`phases=(A,)` の行で値。例外なし。共通列は両行とも埋まる。
  - **システムの安全性**: 相集合が行ごとに欠けても列構造 (和集合) が崩れない。
- **品質保証の観点**: フレーム間の相の出入りに対する頑健性 (EC-3/EC-4 の基礎)。
- 🟡 (要件 §4.3 EC-3)

---

## 3. 境界値テストケース

### T-B01: 空トラジェクトリ (records=()) 🟡
- **境界値の意味**: フレーム 0 件は最小境界 (EDGE-001 の CSV 面)。
- **入力値**: `Trajectory(records=(), lifecycles={})`。
  - **根拠**: 空シーケンスでも例外なく CSV を出す (EDGE-001)。
- **期待される結果**: 例外なし。`to_csv` 成功。データ行数 0 (ヘッダのみ、または相列無しの最小ヘッダ)。空トラジェクトリ時のヘッダ有無は実装で凍結し、行数 0 を保証。
  - **境界での正確性**: `len(records)==0` → データ行 0。
- **堅牢性の確認**: 空入力でクラッシュしない。
- 🟡 (EDGE-001 / TC-101-05 の CSV 面)

### T-B02: 単一フレーム (records 長 1) 🟡
- **境界値の意味**: 最小の非空シーケンス (EDGE-101)。
- **入力値**: `records` 長 1。
- **期待される結果**: データ行 1 行。`len(csv rows) - 1 == 1`。
  - **境界での正確性**: 単数でヘッダ/行の対応が崩れない。
- 🟡 (EDGE-101 / TC-101-06 の CSV 面)

### T-B03: フレーム間で相集合が異なる → 列は和集合 sorted・出現前は空欄 🔵
- **境界値の意味**: 相 B が途中フレームで出現 (changepoint シナリオ) — 列順決定論の中核。
- **入力値**: frame0 `phases=(A,)`, frame1 `phases=(A,B)`。`lifecycles` に A,B。
  - **根拠**: 相の出入りで列順が乱れないか (REQ-402)。
- **期待される結果**: ヘッダの相列は `A.*` → `B.*` の `sorted()` 昇順。frame0 行で `B.*` は全て空欄、frame1 行で `B.*` に値。
  - **一貫した動作**: 列集合は全行共通 (和集合)。
- **堅牢性の確認**: 相の到来順に依存せず列順が安定。
- 🔵 (要件 §4.3 EC-4 / REQ-402 / TC-104-01)

### T-B04: lifecycles にのみ存在する相 🟡
- **境界値の意味**: どのフレームの `phases` にも無いが `lifecycles` にキーがある相 (点滅で phases 未確定だが寿命記録あり等)。
- **入力値**: 全フレーム `phases=(A,)`、`lifecycles={"A":..., "Z":...}`。
  - **根拠**: 列和集合が `phases ∪ lifecycles.keys()` であることの確認。
- **期待される結果**: 相 Z の列が存在し、`Z.a/b/c/scale/wt_frac` は全行空欄、`Z.birth_frame/death_frame/confidence` に値。
  - **境界での正確性**: 格子系列と lifecycle 系列の欠損が独立に扱える。
- 🟡 (要件 §4.3 EC-5)

### T-B05: 決定論 — 2 回出力でバイト同一 (REQ-402 / 完了条件④) 🔵
- **境界値の意味**: 再現性の最重要ゲート。
- **入力値**: 相 A,B が複数フレームにまたがる `Trajectory` を 2 つのパスへ出力。
  - **根拠**: 列順・数値文字列化・改行が完全決定論か。
- **期待される結果**: `open(p1,"rb").read() == open(p2,"rb").read()` (バイト完全一致)。相集合が複数フレームにまたがっても列順が安定。
  - **一貫した動作**: dict/set 反復順・環境非依存。
- **堅牢性の確認**: `newline=""`/`utf-8` 固定で改行・エンコーディング差を排除。
- 🔵 (REQ-402 / 完了条件④ / NFR-102)

### T-B06: frozen 不変性 (FrameRecord / Trajectory) 🔵
- **境界値の意味**: 値オブジェクトの契約 (CLAUDE.md frozen 規約)。
- **入力値**: 生成済み `FrameRecord` / `Trajectory` のフィールドへ代入。
- **期待される結果**: `with pytest.raises(dataclasses.FrozenInstanceError):` で `rec.rwp = 1.0` / `traj.records = ()` が失敗。
  - **境界での正確性**: 生成後は不変。
- **堅牢性の確認**: `@dataclass(frozen=True)` が両クラスに付与されている。
- 🔵 (CLAUDE.md 規約 / interfaces.py frozen)

### T-B07: 有限端点 (0.0 / 負値 / 極小) は空欄化されず保持 🔵
- **境界値の意味**: 純化が「非有限のみ」を落とし、有限の極端値は保持する境界。
- **入力値**: `rwp=0.0`, `axis_value=-273.15`, `wt_frac=1e-12`。
  - **根拠**: `_finite_or_none` は 0.0/負値/極小を保持する (serialization.py B-06 相当)。
- **期待される結果**: `row["rwp"]=="0.0"`, `row["axis_value"]=="-273.15"`, `row["A.wt_frac"]` が `1e-12` 相当で**空欄でない**。
  - **境界での正確性**: 空欄化は None/inf/NaN 限定で 0 や負を巻き込まない。
- **堅牢性の確認**: falsy な 0.0 を欠損扱いしない (`is None` / `isfinite` 判定であること)。
- 🔵 (要件 §3 非有限制約 / serialization.py の有限端点保持)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **選択理由**: プロジェクト全体が Python 3.12 (src layout + uv 管理, `pyproject.toml`)。CSV は stdlib `csv` で完結し外部依存不要。
  - **テストに適した機能**: `dataclasses.FrozenInstanceError`・標準 `csv`・`math.isfinite` を直接検証可能。
- **テストフレームワーク**: pytest (>=8) + pytest-cov 🔵
  - **選択理由**: 既存 25 テストが pytest。`tmp_path` フィクスチャで一時 CSV を安全に生成 (TASK-0017.md 明記)。
  - **テスト実行環境**: `uv run pytest tests/test_trajectory.py` (単体) / `uv run pytest` (回帰) / `uv run pytest --cov=tsumugin`。GSAS-II 非依存のためマーカー不要。
- 🔵 (`pyproject.toml` / `CLAUDE.md` / 既存 `tests/test_changepoint.py`,`test_lifecycle.py`)

---

## 5. テスト実装指針 (日本語コメント様式)

既存 `tests/test_changepoint.py` / `tests/test_lifecycle.py` に準拠し、各テストへ以下を付与する:
- 関数冒頭: `# 【テスト目的】` `# 【テスト内容】` `# 【期待される動作】` + 🔵/🟡/🔴。
- Given: `# 【テストデータ準備】` `# 【初期条件設定】` (相/lifecycles/tmp_path の用意)。
- When: `# 【実際の処理実行】` (`traj.to_csv(path)` 呼び出し)。
- Then: `# 【結果検証】` `# 【期待値確認】` + 各 `assert` に `# 【確認内容】` と信頼性レベル。
- frozen 検証は `with pytest.raises(dataclasses.FrozenInstanceError):`、浮動小数近似は `pytest.approx` (読み戻し値を float 化して比較する場合)。

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `docs/implements/m2-sequential/TASK-0017/trajectory-csv-requirements.md` §1。
- **参照した入力・出力仕様**: 同 §2 (`FrameRecord` 9 フィールド / `Trajectory` / `to_csv` 契約・CSV 列構造)。
- **参照した制約条件**: 同 §3 (stdlib csv 限定・決定論バイト同一・非有限空欄・frozen・型再利用)。
- **参照した使用例**: 同 §4 (基本フロー / EC-1〜5 / ER-1,2)。
- **参照した受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md` TC-104-01/02/03 + REQ-402。
- **参照した設計/実装**: `docs/design/m2-sequential/interfaces.py` L141-165, `src/tsumugin/model/phase.py`, `src/tsumugin/store/serialization.py`(_finite_or_none), `src/tsumugin/export/gpx.py`, `docs/implements/m2-sequential/TASK-0017/note.md`。

---

## 7. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 6 / 異常系 4 / 境界値 7 = 17 件で網羅 (TC-104-01/02/03 + REQ-402 を包含)
- 期待値定義: 各ケースに具体的な入力値・期待セル値・読み戻し検証を明記
- 技術選択: Python 3.12 + pytest + stdlib csv + tmp_path で確定
- 実装可能性: 標準ライブラリのみ・前提 TASK-0011/0016 実装済で確実
- 信頼性レベル: 🔵 12 / 🟡 5 / 🔴 0 — 🟡 は CSV 列レイアウト詳細 (列名/区切り/bool 表現) と
  相列非有限拡張に限定。いずれも Red フェーズで列定数を固定し凍結する
```

**Red フェーズで確定する凍結事項**: (a) 相列名規約 (`A.a` 等) と α/β/γ・σ・volume の要否, (b) `changepoint_reasons` 連結区切り, (c) `bool` の CSV 表現, (d) 空トラジェクトリ時のヘッダ方針。テスト側で期待値を明示し実装を固定する。
