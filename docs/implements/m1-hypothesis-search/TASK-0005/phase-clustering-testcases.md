# TASK-0005 Jaccard クラスタリング + FoM 代表選出 + Jenks natural breaks — TDD テストケース定義書

- **機能名**: 相候補クラスタリング (phase-clustering: `jaccard_clusters` / FoM / `jenks_breaks`)
- **タスクID**: TASK-0005
- **要件名**: m1-hypothesis-search
- **対象実装**: `src/tsumugin/search/clustering.py` (新規) — `PhaseCandidate`, `ClusterResult`, `jaccard_clusters()`, `jenks_breaks()`
- **テストファイル**: `tests/test_clustering.py` (新規)
- **書式の範**: `tests/test_pruning.py` / `tests/test_matcher.py` / `tests/test_peaks.py`

> **【信頼性レベル凡例】**
> - 🔵 **青信号**: EARS要件定義書・設計文書 (`interfaces.py` / `architecture.md` / `acceptance-criteria.md`) を参考にほぼ推測していない
> - 🟡 **黄信号**: 要件・設計から妥当な推測
> - 🔴 **赤信号**: 要件・設計にない推測

## テストケース一覧サマリー

| 区分 | 件数 | ケースID |
|------|------|----------|
| 正常系 | 7 | TC-N01〜TC-N07 |
| 異常系 (縮退) | 6 | TC-E01〜TC-E06 |
| 境界値 | 6 | TC-B01〜TC-B06 |
| **合計** | **19** | |

信頼性内訳: 🔵 15 / 🟡 4

---

## 0. 共通テストデータ・前提

- 🔵 **入力構築**: `Peak(position, height)` (`src/tsumugin/search/peaks.py`) の素の `list`、`fits: list[float]` [0,1]、`delta_us: list[float]` ≥ 0 を直接構築。GSAS-II backend 不要 (`@pytest.mark.gsas` 不要 / `tests/conftest.py` の gsas skip に非該当)。
- 🔵 **共有入力例 (bin 化 = 既定 0.2°)**:
  - `IDENTICAL_A`, `IDENTICAL_B`: ピーク位置 `[10.00, 20.00, 30.00]` と `[10.05, 20.03, 29.98]` — 既定 `bin_width_deg=0.2` で同一 bin に落ち Jaccard ≈ 1.0 ≥ 0.85 (TC-004-01 / TC-B01)。
  - `DIFFERENT_C`: ピーク位置 `[15.0, 25.0, 35.0]` — A/B と別 bin, Jaccard = 0 < 0.85 (TC-004-02)。
  - `JENKS_TWO_GROUP`: `[1.0, 2.0, 3.0, 100.0, 110.0]` — 既知 2 群 (低群 {1,2,3} / 高群 {100,110})、境界は 3〜100 の間 (TC-004-03)。
- 🔵 **FoM 定義 (architecture.md D4 / FR-114)**: `FoM = 1 / ((1 − fit) + ΔU)`。fit 高・ΔU 小ほど大。`fit=1.0, ΔU=0.0` は `float("inf")`。
- 🔵 **正規化規則 (requirements §2.3)**: `ClusterResult.members` は index 昇順、`representative` はクラスタ内 FoM 最大 (同点は index 小優先)、出力タプルは代表 index 昇順。

---

## 1. 正常系テストケース（基本的な動作）

### TC-N01: ほぼ同一ピークの 2 候補が 1 クラスタに縮約され FoM 最大が代表 (TC-004-01)

- **テスト名**: `test_near_identical_peaks_merge_into_one_cluster`
  - **何をテストするか**: ピーク位置がほぼ同一 (bin 一致) の 2 候補が 1 クラスタに縮約され、FoM (fit) 最大が `representative`、他方が `members` に保持されること。
  - **期待される動作**: `jaccard_clusters` が長さ 1 のタプルを返し、`representative` は fit の高い候補 index、`members` は両候補 index を昇順で含む。
- **入力値**: `peak_sets=[IDENTICAL_A, IDENTICAL_B]`, `fits=[0.9, 0.6]`, `delta_us=[0.0, 0.0]` (既定閾値)
  - **入力データの意味**: bin 化で同一集合になる 2 候補。index 0 の fit が高く FoM 最大 = 代表になる代表的パターン。
- **期待される結果**: `len(result) == 1`、`result[0].representative == 0`、`result[0].members == (0, 1)`
  - **期待結果の理由**: Jaccard ≈ 1.0 ≥ 0.85 で同一クラスタ。FoM(0)=1/0.1=10 > FoM(1)=1/0.4=2.5 で index 0 が代表。非破壊性 (REQ-103) で index 1 は削除されず members に残る。
- **テストの目的**: 等構造縮約 + FoM 代表選出 + 代替解保持の中核契約を確認。
  - **確認ポイント**: 代替解 (index 1) が members から欠落しないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-004-01 / 完了条件1 / requirements §4.1 に直接依拠。

### TC-N02: ピーク位置が異なる候補は別クラスタ (TC-004-02)

- **テスト名**: `test_different_peaks_form_separate_clusters`
  - **何をテストするか**: Jaccard < `similarity_threshold` の候補対が別クラスタに分かれること。
  - **期待される動作**: 2 つの `ClusterResult` (各 members 長 1) が返る。
- **入力値**: `peak_sets=[IDENTICAL_A, DIFFERENT_C]`, `fits=[0.8, 0.7]`, `delta_us=[0.0, 0.0]`
  - **入力データの意味**: bin が全く重ならず Jaccard = 0 になる 2 候補。
- **期待される結果**: `len(result) == 2`、`result[0].members == (0,)`、`result[1].members == (1,)`、各 `representative` が自身の index。
  - **期待結果の理由**: Jaccard 0 < 0.85 なので union されず単独クラスタ。出力は代表 index 昇順。
- **テストの目的**: クラスタ分割条件 (閾値未満は非結合) を確認。
  - **確認ポイント**: 誤って 1 クラスタに統合しないこと。
- 🔵 信頼性レベル: 受け入れ基準 TC-004-02 / requirements §4.1 に直接依拠。

### TC-N03: delta_u が大きい候補は FoM で代表になれない (完了条件3)

- **テスト名**: `test_large_delta_u_cannot_be_representative`
  - **何をテストするか**: 同一クラスタ内で fit 同値でも `delta_u` が大きい候補は FoM が下がり代表にならないこと。
  - **期待される動作**: ΔU が小さい候補が `representative` に選ばれる。
- **入力値**: `peak_sets=[IDENTICAL_A, IDENTICAL_B]`, `fits=[0.8, 0.8]`, `delta_us=[0.5, 0.0]`
  - **入力データの意味**: fit を同値に固定し ΔU のみ差をつけることで FoM 差の原因を ΔU に限定。
- **期待される結果**: `result[0].representative == 1` (ΔU=0.0 の候補)、`members == (0, 1)`
  - **期待結果の理由**: FoM(0)=1/((1−0.8)+0.5)=1/0.7≈1.43 < FoM(1)=1/0.2=5.0。ΔU が大きい index 0 は代表になれない。
- **テストの目的**: FoM 式の ΔU 項が代表選出に効くことを確認。
  - **確認ポイント**: fit 同値のとき ΔU で代表が反転すること。
- 🔵 信頼性レベル: 完了条件3 / FR-114 式 / requirements §4.2 に直接依拠。

### TC-N04: FoM 計算値が式 1/((1−fit)+ΔU) に一致

- **テスト名**: `test_fom_value_matches_formula`
  - **何をテストするか**: FoM の数値が `1/((1−fit)+ΔU)` に一致すること (代表選出の根拠値)。
  - **期待される動作**: FoM 最大の候補が式通りに選ばれる。同一クラスタ内で FoM 大小関係が式と整合。
- **入力値**: `peak_sets=[IDENTICAL_A, IDENTICAL_B]`, `fits=[0.5, 0.75]`, `delta_us=[0.0, 0.0]`
  - **入力データの意味**: 手計算で FoM が明確に分離する値。FoM(0)=1/0.5=2.0, FoM(1)=1/0.25=4.0。
- **期待される結果**: `result[0].representative == 1`、`members == (0, 1)`
  - **期待結果の理由**: FoM(1)=4.0 > FoM(0)=2.0 で index 1 が代表。式通りの単調性 (fit 増で FoM 増) を確認。
- **テストの目的**: FoM 定義式 (architecture.md D4) の正確な適用を確認。
  - **確認ポイント**: fit の単調性が代表選出に正しく反映されること。
- 🔵 信頼性レベル: FoM 式 (architecture.md D4 L108-114) に直接依拠。

### TC-N05: jenks_breaks が既知 2 群を分離 (TC-004-03)

- **テスト名**: `test_jenks_breaks_separates_two_known_groups`
  - **何をテストするか**: `jenks_breaks([1,2,3,100,110], n_classes=2)` が両群の間に境界値を返すこと。
  - **期待される動作**: 境界値が低群最大 (3) と高群最小 (100) の間に入る。
- **入力値**: `values=JENKS_TWO_GROUP`, `n_classes=2` (既定)
  - **入力データの意味**: 群内分散が明確に小さい 2 群。境界が一意に定まる典型入力。
- **期待される結果**: 返り値が `tuple[float, ...]`、境界値 `b` が `3.0 < b <= 100.0` (低群と高群を分離)。
  - **期待結果の理由**: SDCM 最小化 DP は {1,2,3} と {100,110} を 2 群に分ける。境界はこの 2 群の間。
- **テストの目的**: Jenks natural breaks の群分離 (FR-116) を確認。
  - **確認ポイント**: 境界が群の間に入り、群内を割らないこと。返り値が素の `float`。
- 🔵 信頼性レベル: 受け入れ基準 TC-004-03 / requirements §4.3 に直接依拠。

### TC-N06: PhaseCandidate / ClusterResult の frozen・既定値契約

- **テスト名**: `test_value_objects_frozen_and_defaults`
  - **何をテストするか**: `PhaseCandidate` の既定値 (`delta_u=0.0`, `label=None`) と両 dataclass の frozen (再代入不可) 契約。
  - **期待される動作**: 既定引数省略で構築でき、フィールド再代入で `FrozenInstanceError`。
- **入力値**: `PhaseCandidate(phase=<PhaseInstance>)`、`ClusterResult(representative=0, members=(0,1))`
  - **入力データの意味**: 契約 (interfaces.py L103-118) の最小構築。
- **期待される結果**: `pc.delta_u == 0.0`、`pc.label is None`、再代入で `dataclasses.FrozenInstanceError` を送出。
  - **期待結果の理由**: 値オブジェクトは不変。既定値は M1 で ΔU=0 / label 無し前提 (requirements §2.1)。
- **テストの目的**: 値オブジェクトの型契約・不変性を確認。
  - **確認ポイント**: frozen が効いていること。
- 🟡 信頼性レベル: 既定値・型は interfaces.py 🔵 だが frozen 例外検証は妥当な推測 🟡。

### TC-N07: 出力の正規化 (members 昇順・クラスタは代表 index 昇順)

- **テスト名**: `test_output_normalized_and_sorted`
  - **何をテストするか**: `members` が index 昇順、出力タプルがクラスタ代表 index 昇順に正規化されること。
  - **期待される動作**: 複数クラスタ・複数メンバーの出力が決定論的順序で返る。
- **入力値**: `peak_sets=[DIFFERENT_C, IDENTICAL_A, IDENTICAL_B]`, `fits=[0.7, 0.9, 0.6]`, `delta_us=[0,0,0]`
  - **入力データの意味**: クラスタ {1,2} (A,B) と単独 {0} (C) が混在。代表は index 1 (FoM 最大) と 0。
- **期待される結果**: `result[0].representative == 0`(C 単独)、`result[1].representative == 1`、`result[1].members == (1, 2)` (昇順)。
  - **期待結果の理由**: members は昇順で `(1,2)`、出力は代表 index 昇順 `[0, 1]`。決定論正規化 (requirements §2.3)。
- **テストの目的**: 決定論的な出力正規化を確認。
  - **確認ポイント**: members が入力順でなく index 昇順であること。
- 🔵 信頼性レベル: requirements §2.3 正規化規則に依拠 (順序詳細の一部は 🟡)。

---

## 2. 異常系テストケース（縮退・エラーハンドリング）

> **M0 規約**: ドメイン的縮退は**例外化せず**縮退値/自然な結果に一元化する (requirements §3)。異常系は「例外を投げない」ことの検証が中心。

### TC-E01: 空入力 peak_sets == [] → 空タプル

- **テスト名**: `test_empty_input_returns_empty_tuple`
  - **エラーケースの概要**: 候補が 1 件も無い空入力。
  - **エラー処理の重要性**: 探索初期・全枝刈り後に空集合が渡され得る。IndexError で落とさない。
- **入力値**: `peak_sets=[]`, `fits=[]`, `delta_us=[]`
  - **不正な理由**: 厳密には不正でなくドメイン縮退。処理対象ゼロ。
  - **実際の発生シナリオ**: 上流の枝刈りで全候補が除外された場合。
- **期待される結果**: `jaccard_clusters([], [], []) == ()` (空タプル)。例外を送出しない。
  - **エラーメッセージの内容**: なし (縮退値で表現)。
  - **システムの安全性**: 呼び出し側は空タプルを空ループで安全に処理できる。
- **テストの目的**: 空入力の非例外縮退を確認。
  - **品質保証の観点**: EDGE の非例外化契約 (M0) を担保。
- 🔵 信頼性レベル: M0 規約 / requirements §3・§4.4 に依拠。

### TC-E02: FoM 分母ゼロ (fit=1.0, delta_u=0.0) → inf 扱い・ZeroDivisionError なし

- **テスト名**: `test_fom_zero_denominator_guarded_as_inf`
  - **エラーケースの概要**: `(1−fit)+ΔU = 0` によるゼロ除算。
  - **エラー処理の重要性**: 完全一致 (fit=1.0) の候補で必ず起こり得る。ZeroDivisionError 禁止。
- **入力値**: `peak_sets=[IDENTICAL_A, IDENTICAL_B]`, `fits=[1.0, 0.9]`, `delta_us=[0.0, 0.0]`
  - **不正な理由**: fit=1.0 かつ ΔU=0.0 で FoM 分母が 0。
  - **実際の発生シナリオ**: 観測と計算が完全一致する理想候補。
- **期待される結果**: 例外を送出せず `result[0].representative == 0` (inf は最大 FoM として代表)。
  - **エラーメッセージの内容**: なし。`float("inf")` へ縮退。
  - **システムの安全性**: inf が最大 FoM として代表選出に整合。
- **テストの目的**: 分母ゼロガード (note.md §6) を確認。
  - **品質保証の観点**: 数値例外の非発生を担保。
- 🔵 信頼性レベル: note.md §6 / requirements §3 FoM 分母ゼロガードに依拠。

### TC-E03: 空ピーク集合を含む候補の Jaccard 縮退

- **テスト名**: `test_empty_peak_set_jaccard_degenerate`
  - **エラーケースの概要**: `Peak` 列が空の候補が混在 (`|A∪B|=0` の 0/0)。
  - **エラー処理の重要性**: ピーク検出ゼロの候補が渡され得る。ZeroDivisionError 禁止・独立クラスタ化。
- **入力値**: `peak_sets=[[], IDENTICAL_A]`, `fits=[0.5, 0.8]`, `delta_us=[0.0, 0.0]`
  - **不正な理由**: 空集合の Jaccard が数学的に未定義 (0/0)。
  - **実際の発生シナリオ**: 弱すぎて `find_peaks` が空を返した候補。
- **期待される結果**: 例外なし。空候補は非空候補と結合しない (別クラスタ扱い) → `len(result) == 2`。
  - **エラーメッセージの内容**: なし。縮退規則 (空 vs 非空は非類似) を適用。
  - **システムの安全性**: 空候補も index を保持し members から消えない。
- **テストの目的**: 空ピーク集合の Jaccard 縮退規則を確認 (実装時較正)。
  - **品質保証の観点**: 0/0 を例外化しないことを担保。
- 🟡 信頼性レベル: 縮退規則の必要性は note.md §6 🔵 だが「空 vs 非空は非類似」の具体規則は実装時較正 🟡。

### TC-E04: jenks_breaks の空入力 → 縮退境界

- **テスト名**: `test_jenks_breaks_empty_input_degenerate`
  - **エラーケースの概要**: `values=[]` で分割対象なし。
  - **エラー処理の重要性**: evidence 列が空になる場合があり例外化しない。
- **入力値**: `values=[]`, `n_classes=2`
  - **不正な理由**: 分割不能なドメイン縮退。
  - **実際の発生シナリオ**: 探索で良好解が 1 件も無い。
- **期待される結果**: 例外なしで空タプル `()` を返す。
  - **エラーメッセージの内容**: なし。自然な縮退境界。
  - **システムの安全性**: 呼び出し側 (TASK-0007) が空を安全に扱える。
- **テストの目的**: Jenks の空入力縮退を確認。
  - **品質保証の観点**: 非例外化 (M0) を担保。
- 🟡 信頼性レベル: requirements §4.4 縮退の精神 🔵 だが空返却の具体値は妥当な推測 🟡。

### TC-E05: jenks_breaks で n_classes ≥ 要素数 → 縮退

- **テスト名**: `test_jenks_breaks_n_classes_ge_len_degenerate`
  - **エラーケースの概要**: 群数が要素数以上で有効分割が定義できない。
  - **エラー処理の重要性**: 呼び出し側が過大な `n_classes` を渡しても例外化しない。
- **入力値**: `values=[5.0, 7.0]`, `n_classes=5`
  - **不正な理由**: 2 要素を 5 群に分割不能。
  - **実際の発生シナリオ**: 良好解が少数のとき既定より大きい群数指定。
- **期待される結果**: 例外なし。自然な縮退境界 (各点が単独群になる全境界、または縮退した境界列) を返す。
  - **エラーメッセージの内容**: なし。
  - **システムの安全性**: IndexError を出さない。
- **テストの目的**: `n_classes` 過大時の縮退を確認。
  - **品質保証の観点**: 境界条件での堅牢性を担保。
- 🟡 信頼性レベル: requirements §4.4 縮退規則 🔵 だが具体的な返却形は実装時確定 🟡。

### TC-E06: 例外・NaN・None を返さない (型健全性)

- **テスト名**: `test_never_returns_nan_none_or_raises`
  - **エラーケースの概要**: あらゆる縮退で戻り値が健全な型に一元化される。
  - **エラー処理の重要性**: 下流の代表展開・ledger 追記が None/NaN 混入で壊れないため。
- **入力値**: `jaccard_clusters` に単一候補 `[IDENTICAL_A]`, `fits=[0.7]`, `delta_us=[0.0]`。`jenks_breaks([42.0], n_classes=2)`。
  - **不正な理由**: 縮退寄りの最小入力で型健全性を横断確認。
  - **実際の発生シナリオ**: 探索の縮退経路全般。
- **期待される結果**: `jaccard_clusters` は `tuple[ClusterResult, ...]`、各 `representative` は素の `int`、`members` は `tuple[int, ...]`。`jenks_breaks` は `tuple[float, ...]` で各要素が `math.isnan` でない。`None` を返さない。
  - **エラーメッセージの内容**: なし。
  - **システムの安全性**: numpy スカラーを露出せず素の型で返す (requirements §3)。
- **テストの目的**: 戻り値の型健全性・NaN/None 非返却を確認。
  - **品質保証の観点**: 下流の型安全性を担保。
- 🔵 信頼性レベル: requirements §3 (素の tuple/int/float・numpy 非露出) / §4.5 に依拠。

---

## 3. 境界値テストケース（最小・最大・全同一・決定論）

### TC-B01: 全候補同一構造 → クラスタ 1 個 (代表 1 + 代替 N−1) (TC-004-04 / EDGE-103)

- **テスト名**: `test_all_identical_structure_single_cluster`
  - **境界値の意味**: 全候補が完全 Jaccard 重複する最大縮約ケース。
  - **境界値での動作保証**: クラスタが 1 個に潰れ、members に全 index が残る。
- **入力値**: `peak_sets=[IDENTICAL_A, IDENTICAL_B, IDENTICAL_A]` (N=3), `fits=[0.7, 0.9, 0.5]`, `delta_us=[0,0,0]`
  - **境界値選択の根拠**: 全候補が同一 bin 集合 → 全対 Jaccard ≥ 0.85。
  - **実際の使用場面**: 同一相の微小バリアントが多数展開される探索状況。
- **期待される結果**: `len(result) == 1`、`result[0].members == (0, 1, 2)` (長 N)、`representative == 1` (FoM 最大)。
  - **境界での正確性**: N=3 全 index が members に保持され欠落ゼロ。
  - **一貫した動作**: 代表 1 + 代替 N−1 の形。
- **テストの目的**: EDGE-103 全同一構造の縮約を確認。
  - **堅牢性の確認**: 完全重複でも非破壊性が保たれること。
- 🔵 信頼性レベル: 受け入れ基準 TC-004-04 / EDGE-103 / requirements §4.4 に直接依拠。

### TC-B02: 単一候補 → クラスタ 1 個 (代表 = members = その index) (EDGE-102)

- **テスト名**: `test_single_candidate_single_cluster`
  - **境界値の意味**: 候補 1 個の最小非空入力。
  - **境界値での動作保証**: 単独でクラスタ化され例外を出さない。
- **入力値**: `peak_sets=[IDENTICAL_A]`, `fits=[0.7]`, `delta_us=[0.0]`
  - **境界値選択の根拠**: N=1 は union-find の下限。
  - **実際の使用場面**: 候補が 1 相に絞られた探索終端。
- **期待される結果**: `len(result) == 1`、`result[0].representative == 0`、`members == (0,)`
  - **境界での正確性**: 自己ループなく単独クラスタ。
  - **一貫した動作**: 代表と members が同一 index。
- **テストの目的**: 単一候補の縮退を確認。
  - **堅牢性の確認**: N=1 で破綻しないこと。
- 🟡 信頼性レベル: EDGE-102 (候補 1 相) / requirements §4.4 に依拠 (具体挙動は妥当な推測 🟡)。

### TC-B03: Jaccard がちょうど閾値 → 同一クラスタ (>= 境界)

- **テスト名**: `test_jaccard_exactly_threshold_merges`
  - **境界値の意味**: Jaccard = `similarity_threshold` ちょうどの境界 (`>=` か `>` かの分岐)。
  - **境界値での動作保証**: 閾値ちょうどは同一クラスタ (境界包含 `≥`)。
- **入力値**: 明示 `similarity_threshold` を Jaccard 実値に一致させた 2 候補 (例: 共有 bin 数を調整して `|A∩B|/|A∪B|` が閾値と厳密一致する `peak_sets`)、`bin_width_deg` 明示。
  - **境界値選択の根拠**: requirements の判定式「Jaccard ≥ similarity_threshold」の等号側を検証。
  - **実際の使用場面**: 類似度が閾値ぴったりの微妙な候補対。
- **期待される結果**: `len(result) == 1` (等号で結合)。
  - **境界での正確性**: `≥` 比較 (閾値を含む) が実装されていること。
  - **一貫した動作**: 閾値未満は TC-N02 で別クラスタ、閾値以上はここで同一クラスタ。
- **テストの目的**: 閾値境界の包含判定を確認。
  - **堅牢性の確認**: 浮動小数境界での比較 (`>=`) の正しさ。
- 🟡 信頼性レベル: 判定式は requirements §2.2/§4.1 🔵 だが「等号を含む (`≥`)」の確定は実装時較正 🟡。

### TC-B04: 決定論 — 入力順を入れ替えても同一クラスタ構造 (完了条件6)

- **テスト名**: `test_deterministic_regardless_of_input_order`
  - **境界値の意味**: 入力順という「順序の境界」を跨いでも出力がビット同一。
  - **境界値での動作保証**: union-find 走査順・出力順が入力順に依存しない。
- **入力値**: 基準 `peak_sets=[IDENTICAL_A, DIFFERENT_C, IDENTICAL_B]` と、その並べ替え。それぞれ対応する fits/delta_us も同時に並べ替え、正規化後の**クラスタ内容 (メンバー集合と代表の相 identity)** を比較。
  - **境界値選択の根拠**: 決定論 (NFR-102/REQ-403) の中核。順序不変性を跨ぐ。
  - **実際の使用場面**: 呼び出し側が候補列を異なる順で構築するケース。
- **期待される結果**: 並べ替え前後で、正規化されたクラスタ構造 (members が指す候補の集合と代表候補) が一致。同一列を 2 回呼べば `result_a == result_b` でビット同一 (`==`)。
  - **境界での正確性**: 出力タプルの順・members 昇順が入力順非依存。
  - **一貫した動作**: 何度呼んでも同一結果。
- **テストの目的**: 決定論・ビット同一 (完了条件6) を確認。
  - **堅牢性の確認**: 順序依存の非決定性が無いこと。
- 🔵 信頼性レベル: 完了条件6 / REQ-403 / NFR-102 / requirements §3・§4.4 に依拠 (index 再マップの検証設計は 🟡)。

### TC-B05: FoM 同点 → index 小優先で代表決定 (完了条件6)

- **テスト名**: `test_fom_tie_breaks_by_smaller_index`
  - **境界値の意味**: FoM が完全同値 (タイ) という代表選出の境界。
  - **境界値での動作保証**: 同点時に index 小を代表に固定 (一意規則)。
- **入力値**: `peak_sets=[IDENTICAL_A, IDENTICAL_B]`, `fits=[0.8, 0.8]`, `delta_us=[0.0, 0.0]`
  - **境界値選択の根拠**: fit・ΔU とも同値で FoM が厳密同点。タイ処理を単独で検証。
  - **実際の使用場面**: 同スコア・同 ΔU の等価候補が並ぶ状況。
- **期待される結果**: `result[0].representative == 0` (index 小優先)、`members == (0, 1)`
  - **境界での正確性**: 同点で index 0 が確定的に選ばれる。
  - **一貫した動作**: TC-B04 の決定論と整合。
- **テストの目的**: タイ処理規則 (index 小優先) を確認。
  - **堅牢性の確認**: 同点で非決定にならないこと。
- 🟡 信頼性レベル: 完了条件6 のタイ規則 (index 小優先) は 🟡 (要件で残る唯一の 🟡)。

### TC-B06: jenks_breaks の単一要素・全同値入力 → 縮退境界

- **テスト名**: `test_jenks_breaks_singleton_and_uniform_degenerate`
  - **境界値の意味**: 分割不能な最小/退化入力 (要素 1 個・全同値)。
  - **境界値での動作保証**: 分散 0 でも例外化せず自然な境界に縮退。
- **入力値**: `values=[5.0]` (単一)、および `values=[3.0, 3.0, 3.0]` (全同値)、`n_classes=2`
  - **境界値選択の根拠**: SDCM=0 で群分割の実益が無い退化ケース。
  - **実際の使用場面**: evidence がすべて同値/1 件の良好解群。
- **期待される結果**: 例外なし。単一/全同値では有意な分割境界を作れないため縮退した境界 (空タプル、または群を分けない境界) を返す。返り値は `tuple[float, ...]`。
  - **境界での正確性**: 群内分散 0 で DP が破綻しない。
  - **一貫した動作**: 空/縮退入力 (TC-E04/E05) と方針一致。
- **テストの目的**: Jenks の退化入力縮退を確認。
  - **堅牢性の確認**: ゼロ分散・単一要素で例外を出さないこと。
- 🟡 信頼性レベル: requirements §4.4 縮退の精神 🔵 だが具体的縮退値は実装時確定 🟡。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 (CPython)
  - **言語選択の理由**: プロジェクト標準 (`pyproject.toml` src layout / hatchling)。`peaks.py` / `matcher.py` / `pruning.py` と同一言語で `search/` パッケージに配置。
  - **テストに適した機能**: `dataclasses` (frozen 値オブジェクト)、型注釈、numpy ベクトル演算。
- **テストフレームワーク**: pytest >= 8 + pytest-cov
  - **フレームワーク選択の理由**: プロジェクト既定 (`[tool.pytest.ini_options]` `testpaths=["tests"]`)。`test_pruning.py` 等が同フレームワークを使用。
  - **テスト実行環境**: `uv run pytest tests/test_clustering.py` / `uv run pytest --cov=tsumugin`。numpy のみ依存、GSAS-II 非依存で backend/fixture 不要。
- 🔵 信頼性レベル: note.md §5 / `pyproject.toml` / 既存テスト群に直接依拠。

**数値検証の使い分け (書式の範: `tests/test_pruning.py`)**:
- 🔵 FoM・Jaccard・Jenks 境界などの数値は `pytest.approx` を使用。
- 🔵 決定論のビット同一検証 (TC-B04/B05) は `==` を使用。
- 🔵 各テストに【テスト目的/テスト内容/期待される動作/信頼性レベル】コメントを付す (Given/When/Then コメント指針に準拠)。

---

## 5. テストケース実装時の日本語コメント指針

`tests/test_pruning.py` / `tests/test_matcher.py` の書式に倣い、各テストに以下を付与する。

### テストケース開始時のコメント

```python
# 【テスト目的】: ほぼ同一ピークの 2 候補が 1 クラスタに縮約され FoM 最大が代表になることを確認 (TC-004-01)
# 【テスト内容】: bin 一致する 2 候補 + fit 差で jaccard_clusters の代表/members を検証
# 【期待される動作】: len==1, representative=0, members=(0,1)
# 🔵 信頼性レベル: 受け入れ基準 TC-004-01 / 完了条件1 に直接依拠
```

### Given（準備フェーズ）のコメント

```python
# 【テストデータ準備】: bin_width_deg=0.2 で同一 bin に落ちる 2 ピーク集合を用意する理由
# 【初期条件設定】: fits=[0.9,0.6] で index0 の FoM を大きくし代表を確定させる
# 【前提条件確認】: similarity_threshold は既定 0.85、Jaccard≈1.0 で結合
```

### When（実行フェーズ）のコメント

```python
# 【実際の処理実行】: jaccard_clusters(peak_sets, fits, delta_us) を呼び出す
# 【処理内容】: bin 化 → 集合化 → Jaccard union-find → 各クラスタ FoM 最大を代表選出
# 【実行タイミング】: 入力構築直後 (純関数のため副作用なし)
```

### Then（検証フェーズ）のコメント

```python
# 【結果検証】: クラスタ数・代表 index・members の内容と順序を検証
# 【期待値確認】: 代表は FoM 最大 (index0)、members は昇順 (0,1) で代替解を保持
# 【品質保証】: 非破壊性 (REQ-103) — 代替解が members から欠落しないことを担保
assert len(result) == 1          # 【検証項目】: 2 候補が 1 クラスタに縮約 🔵
assert result[0].representative == 0  # 【検証項目】: FoM 最大が代表 🔵
assert result[0].members == (0, 1)    # 【検証項目】: 全 index を昇順保持 (代替解削除なし) 🔵
```

### セットアップ・クリーンアップのコメント

```python
# 本タスクは純関数 + 素の list 入力のため beforeEach/afterEach 相当のフィクスチャは原則不要。
# 共有入力 (IDENTICAL_A 等) はモジュールレベル定数で用意し、テスト間で不変・非破壊に共有する。
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: requirements §1 (4 シンボルの純関数 + 値オブジェクト)、note.md §タスク要約
- **参照した入力・出力仕様**: requirements §2.1 (値オブジェクト契約)、§2.2/§2.3 (`jaccard_clusters` 入出力)、§2.4 (`jenks_breaks` 入出力)、`interfaces.py` L103-135
- **参照した制約条件**: requirements §3 (決定論・非破壊性・非例外化・FoM 分母ゼロガード・numpy コア・命名/Lint)、note.md §6 (注意事項)
- **参照した使用例**: requirements §4.1〜§4.5 (基本パターン / FoM 代表 / Jenks / エッジケース / エラーケース)
- **参照した受け入れ基準**: `acceptance-criteria.md` TC-004-01〜04 (L48-54)、TASK-0005.md 完了条件1〜6

### テストケース ↔ 受け入れ基準/完了条件 トレーサビリティ

| テストケース | 対応する受け入れ基準 / 完了条件 | 信頼性 |
|-------------|-------------------------------|--------|
| TC-N01 | TC-004-01 / 完了条件1 | 🔵 |
| TC-N02 | TC-004-02 / 完了条件2 | 🔵 |
| TC-N03 | 完了条件3 (FR-114 式) | 🔵 |
| TC-N04 | FoM 式 (architecture.md D4) | 🔵 |
| TC-N05 | TC-004-03 / 完了条件4 | 🔵 |
| TC-N06 | interfaces.py L103-118 (値オブジェクト契約) | 🟡 |
| TC-N07 | requirements §2.3 (正規化) | 🔵 |
| TC-E01 | requirements §4.4 (空入力縮退) / M0 | 🔵 |
| TC-E02 | note.md §6 (FoM 分母ゼロガード) | 🔵 |
| TC-E03 | note.md §6 (空ピーク集合縮退) | 🟡 |
| TC-E04 | requirements §4.4 (Jenks 空縮退) | 🟡 |
| TC-E05 | requirements §4.4 (n_classes 過大) | 🟡 |
| TC-E06 | requirements §3/§4.5 (型健全性・NaN/None 非返却) | 🔵 |
| TC-B01 | TC-004-04 / EDGE-103 / 完了条件5 | 🔵 |
| TC-B02 | EDGE-102 (候補 1 相) | 🟡 |
| TC-B03 | requirements §2.2 (閾値境界 `≥`) | 🟡 |
| TC-B04 | 完了条件6 / REQ-403 / NFR-102 (決定論) | 🔵 |
| TC-B05 | 完了条件6 (FoM 同点 index 小優先) | 🟡 |
| TC-B06 | requirements §4.4 (Jenks 退化縮退) | 🟡 |

---

## 7. 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 7 / 異常系 6 / 境界値 6 = 19 件で網羅 (TC-004-01〜04 + 完了条件3/6 + 縮退全経路をカバー)
- 期待値定義: 各ケースに具体的な入力値・期待戻り値・判定式を明記
- 技術選択: Python 3.12 + pytest 8 + numpy (確定)
- 実装可能性: interfaces.py に契約確定・参照実装 3 件あり (peaks/matcher/pruning)
- 信頼性レベル: 🔵 15 / 🟡 4 — 中核契約・FoM 式・受け入れ基準は要件に依拠
```

- **残る 🟡 (実装時較正)**: (a) FoM 同点タイ処理 index 小優先 (TC-B05/完了条件6)、(b) `similarity_threshold=0.85`・`bin_width_deg=0.2` の閾値境界 `≥` 挙動 (TC-B03)、(c) 空ピーク集合同士の Jaccard 縮退規則 (TC-E03)、(d) Jenks の空/退化入力の具体的縮退返却形 (TC-E04/E05/B06)。いずれも Red → Green で挙動を確定させる。
