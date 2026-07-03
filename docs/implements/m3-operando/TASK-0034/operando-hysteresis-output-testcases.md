# TASK-0034 TDD テストケース定義 — operando/hysteresis + 結合出力 (FR-315 / FR-314)

**機能名**: operando-hysteresis-output / **タスクID**: TASK-0034 / **要件名**: m3-operando
**実装対象**: `src/tsumugin/operando/hysteresis.py` + `src/tsumugin/operando/output.py`
**テストファイル**: `tests/test_hysteresis_output.py`
**信頼性**: テストケース全 15 件 (正常系 7 / 異常系 3 / 境界値 5)

> 全パスはプロジェクトルートからの相対パス。信頼性 🔵=資料に直接依拠 / 🟡=妥当な推測 / 🔴=資料にない推測。
> 対象契約: `docs/design/m3-operando/interfaces.py` L324-363。
> AC: `docs/spec/m3-operando/acceptance-criteria.md` TC-205-01〜04 (L46-49)。TC-209-01 (E2E) は TASK-0035。

---

## 共通テストフィクスチャ方針 🔵

*参照: note.md §5, `tests/test_trajectory.py` / `tests/test_thermal.py` / `tests/test_discrimination.py` 先例*

- **backend 不要**: 本タスクは純データ (`Trajectory` / `EchemData` / x_values 列) を直接構築する出力層。
  GSAS-II 非依存 (`gsas` マーカー不要)。
- **Trajectory フィクスチャ (`_trajectory`)**: 数フレームの `FrameRecord` (各 `frame_index` + `phases`
  (`PhaseInstance` に `lattice.a/b/c`・`scale`・`wt_frac`)) を組む。`tests/test_trajectory.py` の `_record` を踏襲。
- **EchemData フィクスチャ (`_echem`)**: `EchemData(voltage=(...), current=(...), capacity=(...), composition_x=(...))`
  を Trajectory と同数フレームで用意。位置 index = frame_index。欠損は None、未提供列は `()`。
- **CSV 出力先**: pytest `tmp_path` フィクスチャへ書き、`csv.DictReader` で読み戻して検証。
- **決定論検証**: `combined_csv` を 2 回実行しファイルのバイト列一致。dataclass 結果は `==` でビット同一。
  数値は `pytest.approx`。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError)`。
- **警告検証**: `with pytest.warns(UserWarning)` (EDGE-007 片枝欠損)。

---

## 1. 正常系テストケース（基本的な動作）

### N1. 結合 CSV に V/x 列 + wt_frac(x)/格子(x) が入り読み戻せる 🔵 *TC-205-01 / 完了条件1*

- **テスト名**: `test_combined_csv_contains_vx_and_wtfrac_lattice_readback`
  - **何をテストするか**: `combined_csv(trajectory, echem, path)` が生成した CSV に echem 由来の V/x 列と
    trajectory 由来の wt_frac/格子(a/b/c) 列が同一行に入り、`csv.DictReader` で読み戻せること。
  - **期待される動作**: frame_index 外部結合で各行に相列 + echem 列が並ぶ。
- **入力値**: `_trajectory` (3 フレーム、各相の a/scale/wt_frac 既知) + `_echem`
  (`voltage=(3.0,3.5,4.0)`, `composition_x=(0.0,0.3,0.6)`)、`path=tmp_path/"c.csv"`
  - **入力データの意味**: REQ-011「wt_frac(x)/格子(x)/V を CSV に含める」の代表入力。
- **期待される結果**: 戻り値 == path。読み戻した各行に `voltage`/`composition_x` (or `x`) 列があり期待値一致、
  かつ相の `{ref}.wt_frac`/`{ref}.a` 列が trajectory の値と一致。行数 = フレーム数。
  - **期待結果の理由**: D9「echem 列 (V/I/Q/x) を frame_index で外部結合して CSV 化」。
- **テストの目的**: 結合出力の中核 (wt_frac(x)/格子(x) の同一行結合) を保証。
  - **確認ポイント**: V/x 列の存在と値、相列との行整合、読み戻し可能性。
- 🔵 *acceptance-criteria.md L46, architecture.md D9 L104-106, interfaces.py L349-350*

### N2. 転移点 x/V±σ が境界フレームから算出される 🔵 *TC-205-02 / 完了条件2*

- **テスト名**: `test_transition_point_interpolates_xv_and_sigma_from_boundary`
  - **何をテストするか**: 既知の境界フレーム index `b` に対し `transition_point(echem, b)` が x/V を隣接補間、
    σ_x/σ_v を隣接フレーム echem 差として `TransitionPoint` に格納すること。
  - **期待される動作**: x = 補間値 (既定=中点相当)、σ = `abs(v[b]-v[b-1])`。
- **入力値**: `_echem(composition_x=(0.0,0.2,0.4,0.6), voltage=(3.0,3.3,3.6,3.9))`, `frame_index=2`
  - **入力データの意味**: D-Q10「境界フレームの echem 値を線形補間、σ は隣接差」の代表。
- **期待される結果**: `tp.frame_index == 2`、`tp.x == approx((0.2+0.4)/2)` (=0.3 相当の補間)、
    `tp.voltage == approx((3.3+3.6)/2)`、`tp.sigma_x == approx(abs(0.4-0.2))`、`tp.sigma_v == approx(abs(3.6-3.3))`。
    (補間規約は tdd-red で凍結し、テストは凍結した式に一致させる。)
  - **期待結果の理由**: D-Q10 + M2 `estimate_transition` の σ 算法 (隣接間隔) と同型。
- **テストの目的**: 転移点の電気化学量表現 (x/V±σ) の算出を保証。
  - **確認ポイント**: x/V の補間値、σ の隣接差、frame_index 保持。
- 🔵 *acceptance-criteria.md L47, design-interview.md D-Q10 L55-57, thermal.py L207-226*

### N3. 非単調 x の往復データで充電枝/放電枝が自動分離される 🟡 *TC-205-03 / 完了条件3*

- **テスト名**: `test_split_branches_separates_charge_discharge_on_nonmonotonic_x`
  - **何をテストするか**: 上昇後に下降する非単調 x 列を `split_branches` に渡すと、上昇区間フレーム群と
    下降区間フレーム群が dx 符号で分離されること。
  - **期待される動作**: dx>0 のフレーム群と dx<0 のフレーム群を別 tuple で返す。
- **入力値**: `x_values=[0.0, 0.2, 0.5, 0.8, 0.5, 0.2, 0.0]` (0→0.8 上昇後 0.8→0 下降)
  - **入力データの意味**: REQ-104「x が非単調 (往復) なら枝分離を自動判定」の代表。
- **期待される結果**: 一方の枝 = 上昇区間の index 群 (例 `{1,2,3}` 相当)、他方 = 下降区間 (例 `{4,5,6}`)。
    折返しフレーム (index 3) の帰属は決定論規約に従い一意。両 tuple は昇順・重複なし。
  - **期待結果の理由**: dx = x[i]−x[i−1] の符号で往路/復路を分ける (REQ-104)。
- **テストの目的**: ヒステリシス解析の前提となる枝自動分離を保証。
  - **確認ポイント**: 枝の index 集合、折返し点の一意帰属、昇順・重複なし。
- 🟡 *acceptance-criteria.md L48 (🟡), interfaces.py L339-341, requirements.md REQ-104 L100-101*

### N4. 同一 x での枝間差分 (格子/分率) が出力される 🟡 *TC-205-04 前半 / 完了条件4*

- **テスト名**: `test_branch_differences_computes_same_x_charge_discharge_diff`
  - **何をテストするか**: 充電枝と放電枝が重なる x 域で `branch_differences(x_values, values)` が
    共通 x グリッド上の `BranchComparison(x, charge_value, discharge_value, difference)` を返すこと。
  - **期待される動作**: 各グリッド x で charge/discharge を補間し difference = charge − discharge。
- **入力値**: `x_values`=往復列 (N3 と同型)、`values`=各フレームの格子 a (充電枝と放電枝で意図的にずらす)、
    `n_grid=5`
  - **入力データの意味**: REQ-012「同一 x における格子・分率の枝間差分」の代表。
- **期待される結果**: 戻り値は `tuple[BranchComparison,...]`、重なり x 域では `difference` が有限で
    `charge_value − discharge_value` に一致 (`pytest.approx`)、x は昇順グリッド。
  - **期待結果の理由**: FR-315「同一 x の枝間差分」+ 共通グリッド補間。
- **テストの目的**: ヒステリシス定量化 (枝間差分) を保証。
  - **確認ポイント**: difference の算式、共通 x グリッドの昇順、charge/discharge 補間値。
- 🟡 *acceptance-criteria.md L49, interfaces.py L329-346, requirements.md REQ-012 L54-55*

### N5. combined_csv がフレーム数不一致で外部結合し欠損側を空欄化する 🟡 *D9 外部結合*

- **テスト名**: `test_combined_csv_outer_join_blank_for_missing_frames`
  - **何をテストするか**: trajectory と echem のフレーム数が異なる場合、frame_index の和集合 (外部結合) で
    行が作られ、片側に無いフレームの列が空欄になること。
  - **期待される動作**: 外部結合・欠損側空欄・非捏造。
- **入力値**: `_trajectory` (frame 0..3) + `_echem` (voltage が 2 フレームのみ = frame 2,3 は None)
  - **入力データの意味**: 部分同期 (行数不一致) の代表 (echem.py の None 縮退と整合)。
- **期待される結果**: CSV 行数 = 全フレーム和集合、echem 欠損フレームの `voltage` 列セルが空文字、
    trajectory 側は通常値。例外なし。
  - **期待結果の理由**: D9「frame_index で外部結合」+ 非有限/欠損は空欄 (捏造しない)。
- **テストの目的**: 外部結合と欠損縮退の正しさを保証。
  - **確認ポイント**: 行数=和集合、欠損セル空欄、非欠損側は保持。
- 🟡 *architecture.md D9 L104-106, dataflow.md L124 (欠損 None), note.md §6-1*

### N6. combined_csv の出力がバイト同一 (決定論) 🔵 *NFR-102 / 完了条件*

- **テスト名**: `test_combined_csv_deterministic_byte_identical`
  - **何をテストするか**: 同一 `trajectory`/`echem` で `combined_csv` を 2 回実行し、生成ファイルの
    バイト列が完全一致すること。
  - **期待される動作**: 乱数/時刻/集合反復順に依存しない (`newline=""`/`utf-8` 固定)。
- **入力値**: 同一 `_trajectory` + `_echem` を別パスへ 2 回出力。
  - **入力データの意味**: NFR-102 再現性の検証 (trajectory.to_csv と同一保証)。
- **期待される結果**: 2 ファイルの bytes が一致 (`open(...,"rb").read()` 比較)。
  - **期待結果の理由**: 決定論出力 (相 ref sorted・列順固定・改行/エンコーディング固定)。
- **テストの目的**: 出力の再現性 (NFR-102) を保証。
  - **確認ポイント**: バイト同一、相 ref の sorted 昇順、echem 列順の安定。
- 🔵 *CLAUDE.md NFR-102, trajectory.py L107-108 (newline/utf-8)*

### N7. hysteresis/transition 純関数がビット同一 (決定論) 🔵 *NFR-102*

- **テスト名**: `test_hysteresis_and_transition_deterministic_bit_identical`
  - **何をテストするか**: `split_branches`/`branch_differences`/`transition_point` を同一入力で 2 回呼び、
    結果がビット同一であること。
  - **期待される動作**: dataclass の `==`・tuple 一致で再現性を担保。
- **入力値**: 同一 `x_values`/`values`/`echem`/`frame_index` で 2 回呼ぶ。
  - **入力データの意味**: NFR-102 再現性 (枝分離 tie-break・補間の決定論)。
- **期待される結果**: `split_branches(...) == split_branches(...)`、
    `branch_differences(...) == branch_differences(...)`、`transition_point(...) == transition_point(...)`。
  - **期待結果の理由**: 安定 tie-break + 決定論補間。
- **テストの目的**: ヒステリシス/転移点算出の再現性を保証。
  - **確認ポイント**: 全フィールド一致、折返し/dx==0 tie-break の安定性。
- 🔵 *CLAUDE.md NFR-102, note.md §6-3/6-6*

---

## 2. 異常系テストケース（エラーハンドリング）

### E1. 片枝のみのデータ → 枝間差分 None + 警告 🟡 *EDGE-007 / TC-205-04 後半*

- **テスト名**: `test_branch_differences_single_branch_yields_none_and_warns`
  - **エラーケースの概要**: 充電枝のみ (または放電枝のみ) しか存在しない (単調 x = 往復なし) データ。
  - **エラー処理の重要性**: 片枝しかない x で差分を捏造すると誤ったヒステリシスを示す。None + 警告が必須。
- **入力値**: 単調増加のみの `x_values=[0.0,0.2,0.4,0.6,0.8]` (放電枝が空) + `values` + `n_grid=5`
  - **不正な理由**: 往復がなく枝間差分が定義できない x 域が生じる。
  - **実際の発生シナリオ**: 片方向スキャン (充電のみ or 放電のみ) の operando 測定。
- **期待される結果**: 例外を投げず、片枝しかない x の `BranchComparison` は
    `discharge_value is None`/`difference is None` (欠損枝側 None)、かつ `UserWarning` が 1 回出る
    (`pytest.warns(UserWarning)`)。処理はブロックしない。
  - **エラーメッセージの内容**: 「片枝のみのため枝間差分を算出できません」等の説明的 warning。
  - **システムの安全性**: None 縮退 + 警告で上位を止めない。
- **テストの目的**: EDGE-007 (片枝のみ → 差分 None + 警告) の保証。
  - **品質保証の観点**: 欠損を捏造せず明示的に None + 警告で通知する CLAUDE.md 不変条件。
- 🟡 *acceptance-criteria.md L49, requirements.md EDGE-007 L127, echem.py L137-143 (警告先例)*

### E2. 非有限 (inf/NaN)/None が CSV セルに漏れない 🔵 *完了条件5 / M1/M2 教訓*

- **テスト名**: `test_combined_csv_never_leaks_nonfinite_values`
  - **エラーケースの概要**: trajectory の rwp/chi2/格子や echem に inf/NaN/None が混在する病的ケース。
  - **エラー処理の重要性**: 非有限を CSV へ書くと下流の読み戻し・数値処理が壊れる (M1/M2 教訓)。
- **入力値**: `_trajectory` の一部 `FrameRecord` に `chi2=float("inf")`/`rwp=None`、格子 a を `float("nan")`、
    `_echem` の `voltage` に `None` を含める。
  - **不正な理由**: 非有限/None は数値として無効。
  - **実際の発生シナリオ**: 精密化失敗フレーム・echem 欠損行。
- **期待される結果**: CSV の該当セルがすべて空文字 (`""`)。数値列に "inf"/"nan"/"None" 文字列が現れない。
    例外なし・他セルは保持。
  - **システムの安全性**: 非有限を空欄化し下流へ漏らさない。
- **テストの目的**: 非有限漏洩防止 (完了条件5) の保証。
  - **品質保証の観点**: `trajectory._num_cell` と同思想の純化を全出口で守る。
- 🔵 *note.md §0.2/§6-5, trajectory.py L183-197, CLAUDE.md 不変条件*

### E3. TransitionPoint / BranchComparison の float フィールドに非有限を格納しない 🟡 *非有限縮退*

- **テスト名**: `test_transition_and_comparison_degrade_nonfinite_to_none`
  - **エラーケースの概要**: 転移点/枝間差分の算出中に非有限 (echem 欠損の隣接差など) が生じるケース。
  - **エラー処理の重要性**: float フィールドに inf/NaN を入れると `==` 比較・下流が壊れる。
- **入力値**: `_echem(composition_x=(0.0, None, 0.4), voltage=(3.0, None, 3.6))`, `frame_index=1`
    (境界に欠損が隣接)。
  - **不正な理由**: 欠損隣接で補間/差分が定義できない。
  - **実際の発生シナリオ**: 部分同期 echem の境界フレーム。
- **期待される結果**: 該当フィールド (`x`/`voltage`/`sigma_x`/`sigma_v`) が `None` (inf/NaN を格納しない)。
    例外なし。
  - **システムの安全性**: None 縮退で下流の等価比較・出力を保護。
- **テストの目的**: 非有限を dataclass へ漏らさない縮退を保証。
  - **品質保証の観点**: 出力層全体で非有限→None 縮退を統一。
- 🟡 *note.md §6-2/6-5, thermal.py (欠損→None 先例)*

---

## 3. 境界値テストケース（最小値・最大値・null 等）

### B1. 境界端フレーム (b=0 / b=n-1) で隣接不能 → 該当フィールド None 🟡 *D-Q10 縮退*

- **テスト名**: `test_transition_point_at_series_ends_returns_none_fields`
  - **境界値の意味**: 転移点の隣接補間は b-1/b+1 が必要。端フレームは片側隣接が無い最小/最大境界。
- **入力値**: `_echem` (4 フレーム) + `frame_index=0` および `frame_index=3` の 2 パターン。
  - **境界値選択の根拠**: b=0 は前フレームなし、b=n-1 は後フレームなしで σ/補間が定義できない端。
- **期待される結果**: 隣接不能側に依存する `x`/`voltage`/`sigma_x`/`sigma_v` が None (定義可能な側のみ値)。
    例外なし。`frame_index` は保持。
  - **境界での正確性**: 端で捏造せず None 縮退。
- **テストの目的**: 端フレームでの安全動作 (D-Q10 縮退) を保証。
- 🟡 *design-interview.md D-Q10 L55-57, note.md §6-2*

### B2. echem 欠損フレーム (None) を含む結合 CSV → 該当セル空欄 🟡 *部分同期*

- **テスト名**: `test_combined_csv_blank_for_none_echem_cells`
  - **境界値の意味**: echem 列に None (欠損フレーム) が混じる部分同期の境界。
- **入力値**: `_echem(voltage=(3.0, None, 4.0), composition_x=(0.0, 0.3, None))` + `_trajectory` (3 フレーム)
  - **境界値選択の根拠**: echem.py の None 縮退政策 (欠損は捏造しない) との整合検証。
- **期待される結果**: None の echem セルは空文字、非 None セルは値保持。行数=フレーム数。例外なし。
  - **一貫した動作**: 欠損セルのみ空欄で他に波及しない。
- **テストの目的**: 部分同期 echem での結合の堅牢性を保証。
- 🟡 *echem.py L122-124 (None 縮退), dataflow.md L124*

### B3. echem 未提供列 (空 tuple) → 該当 echem 列を CSV に出さない/全空欄 🟡 *列縮退*

- **テスト名**: `test_combined_csv_handles_absent_echem_columns`
  - **境界値の意味**: `EchemData` の current/capacity が既定 `()` (未提供) の最小構成。
- **入力値**: `EchemData(voltage=(3.0,3.5,4.0))` (current/capacity/composition_x は空 `()`) + `_trajectory`
  - **境界値選択の根拠**: voltage-only の echem (echem.py の空縮退) の代表。
- **期待される結果**: 空 tuple の列は CSV に列を追加しない (または全行空欄) — tdd-red で 1 規約に固定。
    voltage 列は正常出力。例外なし。
  - **一貫した動作**: 未提供列で列数が破綻しない。
- **テストの目的**: 最小 echem 構成での列生成の堅牢性を保証。
- 🟡 *echem.py L62-64 (空縮退), note.md §6-1*

### B4. BranchComparison / TransitionPoint の不変性 (frozen) 🔵 *不変データ契約*

- **テスト名**: `test_branch_comparison_and_transition_point_are_frozen`
  - **境界値の意味**: frozen dataclass 契約 (生成後の属性代入拒否)。
- **入力値**: `BranchComparison(...)` / `TransitionPoint(...)` インスタンスへ属性代入。
  - **境界値選択の根拠**: 不変データ (P2 / コーディング規約) の境界検証。
- **期待される結果**: `with pytest.raises(dataclasses.FrozenInstanceError)` で代入が拒否される。
  - **境界での正確性**: 生成後の状態変更不可。
- **テストの目的**: 不変データ規約の遵守を保証。
- 🔵 *interfaces.py L329/L354 (@dataclass(frozen=True)), CLAUDE.md コーディング規約*

### B5. 空/単一フレームの x_values・dx==0 平坦の枝分離 決定論規約 🟡 *最小入力/tie-break*

- **テスト名**: `test_split_branches_empty_single_and_flat_deterministic`
  - **境界値の意味**: 分離には 2 フレーム以上必要。空/単一/全平坦 (dx==0) は枝分離の最小縮退境界。
- **入力値**: (a) `x_values=[]`、(b) `x_values=[0.5]`、(c) `x_values=[0.5,0.5,0.5]` (全 dx==0) の 3 パターン。
  - **境界値選択の根拠**: dx 未定義 (空/単一) と dx==0 (平坦) の帰属規約を固定検証。
- **期待される結果**: 例外なし。空/単一は両枝とも空 tuple (or 単一フレームを一方へ規約帰属)、
    全平坦は決定論規約 (例: 全フレームを充電枝側 or 両枝除外) に従い一意。2 回実行で同一。
  - **一貫した動作**: 最小入力でも Result 契約 (tuple ペア) を満たし決定論。
- **テストの目的**: 枝分離の最小縮退と tie-break 安定性を保証 (tdd-red で規約凍結)。
- 🟡 *note.md §6-3 (dx==0/None/折返し帰属), interfaces.py L339-341*

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout + hatchling)。数値は numpy のみ (REQ-403)、
    CSV は stdlib csv (trajectory と統一)。
  - **テストに適した機能**: frozen dataclass の `==` ビット同一比較、`pytest.warns`/`pytest.raises`、`tmp_path`。
- **テストフレームワーク**: pytest (>=8) + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` (testpaths=["tests"])。
    既存テスト (`tests/test_trajectory.py` / `tests/test_thermal.py` 等) と統一。
  - **テスト実行環境**: `uv run pytest tests/test_hysteresis_output.py`。GSAS-II 非依存 (backend 不要)、
    `gsas` マーカー不要。数値近似は `pytest.approx`、frozen 検証は `dataclasses.FrozenInstanceError`、
    警告は `pytest.warns(UserWarning)`、CSV 出力は `tmp_path`。
- 🔵 *pyproject.toml, tests/conftest.py, CLAUDE.md L21-23*

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下を必ず付す (先例 `tests/test_trajectory.py` / `tests/test_discrimination.py`):

```python
def test_combined_csv_contains_vx_and_wtfrac_lattice_readback(tmp_path):
    # 【テスト目的】: combined_csv が V/x 列 + wt_frac(x)/格子(x) を同一行に結合し読み戻せることを確認する
    # 【テスト内容】: Trajectory + EchemData を frame_index 外部結合で CSV 化し DictReader で読み戻す
    # 【期待される動作】: 各行に echem 列と相列が並び、値が入力と一致
    # 🔵 acceptance-criteria.md TC-205-01

    # 【テストデータ準備】: 相列既知の Trajectory と V/x 既知の EchemData を用意する理由 = REQ-011 の代表入力
    # 【初期条件設定】: backend 不要・純データ・出力先は tmp_path
    trajectory = _trajectory()
    echem = _echem()

    # 【実際の処理実行】: combined_csv を呼び出す
    # 【処理内容】: frame_index 外部結合で trajectory 列 + echem 列 (V/I/Q/x) を CSV 出力
    out = combined_csv(trajectory, echem, str(tmp_path / "c.csv"))

    # 【結果検証】: 読み戻して V/x 列と wt_frac/格子 列を検証
    # 【期待値確認】: echem 列の値一致・相列の値一致・行数一致
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[1]["voltage"] == "3.5"  # 【検証項目】: V 列が入る 🔵
    assert rows[1]["composition_x"] == "0.3"  # 【検証項目】: x 列が入る 🔵
```

- Given: 【テストデータ準備】【初期条件設定】【前提条件確認】
- When: 【実際の処理実行】【処理内容】
- Then: 【結果検証】【期待値確認】【品質保証】、各 assert に【検証項目】+ 信頼性レベル

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `operando-hysteresis-output-requirements.md` §1 (結合出力 FR-314・ヒステリシス FR-315)
- **参照した入力・出力仕様**: 同 §2 (`combined_csv`/`TransitionPoint`/`split_branches`/`branch_differences`/
  `BranchComparison` シグネチャ・結合/補間/枝分離規約)
- **参照した制約条件**: 同 §3 (非有限漏洩防止 / 決定論 NFR-102 / 非破壊 P2 / 後方互換 REQ-404 / numpy のみ /
  警告政策 EDGE-007)
- **参照した使用例**: 同 §4 (結合出力・転移点定量化・ヒステリシス解析・各縮退)

### AC カバレッジ表

| AC / 完了条件 | 対応テスト | 信頼性 |
|---|---|---|
| TC-205-01 (V/x 列入り結合 CSV・wt_frac(x)/格子(x)) | N1 | 🔵 |
| TC-205-02 (転移点 x/V±σ) | N2 | 🔵 |
| TC-205-03 (非単調 x の充放電枝自動分離) | N3 | 🟡 |
| TC-205-04 (同一 x 枝間差分・片枝のみ None+警告) | N4, E1 | 🟡 |
| 完了条件5 (CSV に非有限漏れない) | E2, E3 | 🔵🟡 |
| D9 外部結合 (フレーム不一致/欠損空欄) | N5, B2, B3 | 🟡 |
| NFR-102 (決定論ビット同一) | N6, N7 | 🔵 |
| D-Q10 縮退 (境界端/欠損隣接) | B1, E3 | 🟡 |
| 不変データ契約 (frozen) | B4 | 🔵 |
| 枝分離最小縮退・tie-break | B5 | 🟡 |
| **スコープ外** TC-209-01 (E2E) | — (TASK-0035) | — |
| **スコープ外** dQ/dV プロット描画 | — (M3 スコープ外・データ出力のみ) | — |

---

## 品質判定

✅ **高品質**:
- テストケース分類: 正常系 7 / 異常系 3 / 境界値 5 = **15 件**、AC TC-205-01〜04 を全網羅 +
  非有限漏洩/外部結合/決定論/frozen/縮退を補完
- 期待値定義: 各ケースに具体的期待値 (V/x 列値・x/V±σ 算式・枝 index 集合・difference・空欄・None・verify) を明記
- 技術選択: Python 3.12 + pytest 確定、backend 不要 (純データ Trajectory/EchemData) で GSAS-II 非依存
- 実装可能性: Trajectory.to_csv / EchemData / estimate_transition の先例再利用で確実
- 信頼性レベル: 🔵 主体 (🟡 は枝分離符号規約・共通グリッド域・結合列順・転移点補間細部の妥当推測、🔴 なし)

**残す設計判断 (tdd-red で凍結)**: combined_csv の列順/結合規約と echem 空 tuple 列の扱い、転移点の補間規約
(中点 or 分数 index) と生成関数シグネチャ、split_branches の符号割当・折返し/dx==0/None 帰属、
branch_differences の共通グリッド域取り (重なり域 or 全域)。

---

**次のお勧めステップ**: `/tsumiki:tdd-red m3-operando TASK-0034` で Red フェーズ (失敗テスト作成) を開始します。
