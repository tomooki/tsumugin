# TASK-0030 TDDテストケース定義: operando/cell_phases — セル固定相プリセット (FR-312)

**機能名**: cell-phase-presets / **タスクID**: TASK-0030 / **要件名**: m3-operando
**信頼性サマリー**: 🔵 6 / 🟡 6 (FR-312 / REQ-009 / AC TC-203-01〜03)
**対象実装**: `src/tsumugin/operando/cell_phases.py` (新規) / **テストファイル**: `tests/test_cell_phases.py` (新規)

> AC の受け入れ基準 TC-203-01〜03 と本書のテスト ID (N/A/BV) の対応を各ケースに明記する。
> 本書のすべてのパスはプロジェクトルートからの相対パス。

---

## 0. テスト方針・共通事項

- **対象 API** (`docs/design/m3-operando/interfaces.py` L232-244):
  `FixedPhaseSpec` (frozen dataclass, フィールド `phase: PhaseInstance` / `label: str`) /
  `CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]` (キー `"Be"`/`"Al"`/`"graphite"`) /
  `fixed_free_suffixes(spec) -> tuple[str, ...]` (常に `("scale",)`)。
- **正典契約**: AC 原文 TC-203-01 は "PhaseCandidate" と記すが、本タスクは interfaces.py / TASK-0030.md の
  `FixedPhaseSpec` を正典としてテストを記述する (要件定義書「契約の不一致」参照)。
- **文献格子定数 (直方近似)** — 実装 docstring と一致させる期待値:
  - Be (hcp): a=2.2858, b=a·√3≈3.9591, c=3.5843 (Å)
  - Al (fcc): a=b=c=4.0495 (Å)
  - graphite (hex): a=2.464, b=a·√3≈4.2678, c=6.711 (Å)
- **合成検証の範** (`tests/test_simulated_backend.py`): `SimulatedBackend(peak_fwhm=0.2)` +
  `two_theta = np.arange(15.0, 80.0, 0.02)` + `RefinementModel(phases, free_params, two_theta, intensity)`。
  `free_params` は `param_name(i, "scale")` (`src/tsumugin/backends/base.py`) で構成。
- **frozen 検証**: `with pytest.raises(dataclasses.FrozenInstanceError):`。**近似一致**: `== pytest.approx(...)`。
- **決定論**: プリセットの 2 回参照が等価 (`==`)。

---

## 1. 正常系テストケース（基本的な動作）

### TC-N01: プリセット 3 種が FixedPhaseSpec として取得できる 🔵 (対応: TC-203-01 / REQ-009)

- **テスト名**: `test_cell_phase_presets_has_three_fixed_phase_specs`
  - **何をテストするか**: `CELL_PHASE_PRESETS` に `"Be"`/`"Al"`/`"graphite"` の 3 キーがあり、各値が `FixedPhaseSpec`。
  - **期待される動作**: 3 プリセットが `FixedPhaseSpec` インスタンスとして取り出せる。
- **入力値**: `CELL_PHASE_PRESETS` (定数、引数なし)。
  - **入力データの意味**: REQ-009 が要求するセル固定相テンプレート (Be 窓・Al 集電体・グラファイト) の最小集合。
- **期待される結果**: `set(CELL_PHASE_PRESETS) == {"Be", "Al", "graphite"}`。各 `CELL_PHASE_PRESETS[k]` が
  `isinstance(..., FixedPhaseSpec)`。
  - **期待結果の理由**: interfaces.py L244「"Be" | "Al" | "graphite"」/ L236-241 の型契約に直接対応。
- **テストの目的**: プリセット提供の中核契約 (取得可能性)。
  - **確認ポイント**: キー集合が過不足なく 3 種、値の型が `FixedPhaseSpec`。
- 🔵 信頼性: TC-203-01 / REQ-009 / interfaces.py L236-244 に直接依拠。

### TC-N02: プリセット格子値が文献値 (直方近似) と一致 🟡 (対応: 完了条件3)

- **テスト名**: `test_cell_phase_presets_lattice_matches_literature`
  - **何をテストするか**: 各プリセット `phase.lattice` の a/b/c が docstring 記載の文献値 (直方近似後) と一致。
  - **期待される動作**: Be/Al/graphite の格子定数が期待値どおり。
- **入力値**: `CELL_PHASE_PRESETS["Be"|"Al"|"graphite"].phase.lattice`。
  - **入力データの意味**: 完了条件「プリセット格子値が文献値近傍 (docstring 記載値と一致)」の直接検証。
- **期待される結果**:
  - Be: `a == pytest.approx(2.2858)`, `c == pytest.approx(3.5843)`
  - Al: `a == pytest.approx(4.0495)`, `b == pytest.approx(4.0495)`, `c == pytest.approx(4.0495)`
  - graphite: `a == pytest.approx(2.464)`, `c == pytest.approx(6.711)`
  - **期待結果の理由**: 文献格子定数 (要件・タスク指示で提示された値)。実装 docstring と同一値。
- **テストの目的**: 格子定数のハードコード正しさ。
  - **確認ポイント**: 文献値と実装値が乖離しない (0.001 Å 精度)。
- 🟡 信頼性: TASK-0030.md 完了条件・タスク指示の格子値に依拠 (格子値そのものは 🟡)。

### TC-N03: fixed_free_suffixes が ("scale",) を返す 🟡 (対応: TC-203-02 / REQ-009)

- **テスト名**: `test_fixed_free_suffixes_returns_scale_only`
  - **何をテストするか**: `fixed_free_suffixes(spec)` が構造を解放せず scale のみを返す。
  - **期待される動作**: 全プリセットで戻り値が `("scale",)`。
- **入力値**: 各 `CELL_PHASE_PRESETS[k]` (Be/Al/graphite)。
  - **入力データの意味**: 「構造固定・scale のみ解放」(REQ-009 字義) の解放パラメータ展開契約。
- **期待される結果**: `fixed_free_suffixes(spec) == ("scale",)`。`"lattice.a"` 等・`"occ."` 系を含まない。
  - **期待結果の理由**: interfaces.py L238「構造固定・scale のみ解放」/ REQ-009。
- **テストの目的**: scale のみ解放ヘルパの単一の真実源としての正しさ。
  - **確認ポイント**: lattice/occupancy suffix が漏れ出ないこと。
- 🟡 信頼性: TC-203-02 / REQ-009 / interfaces.py L238 に依拠 (ヘルパ戻り形は妥当推測)。

### TC-N04: FixedPhaseSpec の frozen・構造的等価 🔵 (対応: §4 データモデル)

- **テスト名**: `test_fixed_phase_spec_frozen_and_structural_equality`
  - **何をテストするか**: `FixedPhaseSpec` を直接生成し、frozen (再代入不可)・等価比較 (`==`) が成立する。
  - **期待される動作**: 同値 spec は `==` で真、フィールド再代入は `FrozenInstanceError`。
- **入力値**: 同一 `phase` (PhaseInstance)・同一 `label` で `FixedPhaseSpec` を 2 つ生成。
  - **入力データの意味**: プリセット定数を介さない純データモデル契約 (frozen dataclass)。
- **期待される結果**: 2 インスタンスが `==`。（frozen の再代入検証は異常系 TC-A01 で実施）。
  - **期待結果の理由**: interfaces.py L236-241 の frozen dataclass 契約 (phase/label いずれもハッシュ可)。
- **テストの目的**: 値オブジェクトの不変性・等価性。
  - **確認ポイント**: プリセット取得と独立にモデル単体が健全。
- 🔵 信頼性: interfaces.py L236-241 / CLAUDE.md (frozen dataclass 規約) に依拠。

### TC-N05: プリセットの label が非空 str・phase が PhaseInstance 🔵 (対応: TC-203-01)

- **テスト名**: `test_cell_phase_presets_have_valid_phase_and_label`
  - **何をテストするか**: 各プリセットの `phase` が `PhaseInstance`、`label` が非空 `str`。
  - **期待される動作**: 固定相の相インスタンスとラベルが正しく詰まっている。
- **入力値**: 各 `CELL_PHASE_PRESETS[k]`。
  - **入力データの意味**: `FixedPhaseSpec(phase, label)` の各フィールドが実体を持つことの確認。
- **期待される結果**: `isinstance(spec.phase, PhaseInstance)` かつ `isinstance(spec.label, str)` かつ `spec.label != ""`。
  `spec.phase.phase_ref` が非空 (相参照が設定されている)。
  - **期待結果の理由**: interfaces.py L240-241 (phase: PhaseInstance / label: str)。
- **テストの目的**: プリセットのフィールド実体性。
  - **確認ポイント**: label が None や空でない、phase が正しい型。
- 🔵 信頼性: TC-203-01 / interfaces.py L240-241 に直接依拠。

### TC-N06: 固定相込み合成データで活物質相が正しく同定される 🔵 (対応: TC-203-03 / REQ-009)

- **テスト名**: `test_active_phase_refines_with_fixed_cell_phase`
  - **何をテストするか**: 固定相 (プリセット) + 活物質相の合成データで、固定相の scale のみ解放しつつ活物質相を精密化すると
    活物質相の scale が真値へ収束する。
  - **期待される動作**: セル材料ピークが重畳しても活物質相が正しく同定 (scale 収束) される。
- **入力値**:
  - 真値: `truth = (CELL_PHASE_PRESETS["Al"].phase.with_updates(scale=2.0), active_truth)`。
    `active_truth = PhaseInstance("LFP", LatticeParams(5.0, 5.0, 5.0), scale=3.0)`。
  - `y = backend.simulate(truth, tt)` (`tt = np.arange(15.0, 80.0, 0.02)`)。
  - 初期: `start = (CELL_PHASE_PRESETS["Al"].phase.with_updates(scale=1.0), active_start(scale=1.0))`。
  - `free_params = {param_name(0, s) for s in fixed_free_suffixes(spec_al)} | {param_name(1, "scale")}`
    (= `{"phase0.scale", "phase1.scale"}`)。
  - **入力データの意味**: 「固定相=scale のみ解放」で活物質相と共存する REQ-009 / dataflow.md L18-19 の中核シナリオ。
- **期待される結果**: `result.converged` が真。`result.phases[1].scale == pytest.approx(3.0, rel=0.05)`
  (活物質相 scale が真値へ)。`result.phases[0].scale > 0` (固定相 scale も追随)。
  - **期待結果の理由**: 固定相の構造を固定し scale のみ動かすと、活物質相の scale が正しく分離同定できる
    (SimulatedBackend の scale 精密化・`test_refine_scale_converges_to_truth` の範)。
- **テストの目的**: 固定相込みの活物質相同定 (合成検証)。
  - **確認ポイント**: セル材料ピーク重畳下でも活物質 scale が真値へ収束する。
- 🔵 信頼性: TC-203-03 / REQ-009 / `tests/test_simulated_backend.py` (scale 収束) に依拠。

### TC-N07: 決定論 — プリセットの 2 回参照が等価 🔵 (対応: NFR-102 / REQ-402)

- **テスト名**: `test_cell_phase_presets_deterministic`
  - **何をテストするか**: `CELL_PHASE_PRESETS` を 2 回参照して同一プリセットが得られる。
  - **期待される動作**: 実行のたびに揺れない不変定数。
- **入力値**: `CELL_PHASE_PRESETS["Be"]` を 2 回。
  - **入力データの意味**: 再現性 (NFR-102) の検証。
- **期待される結果**: `CELL_PHASE_PRESETS["Be"] == CELL_PHASE_PRESETS["Be"]` が真 (同一オブジェクトまたは等価)。
  - **期待結果の理由**: モジュール定数・乱数不使用のため決定論 (CLAUDE.md 不変条件)。
- **テストの目的**: 再現性保証。
  - **確認ポイント**: 環境・時刻・乱数に依存しないこと。
- 🔵 信頼性: NFR-102 / REQ-402 / CLAUDE.md 不変条件に直接依拠。

---

## 2. 異常系テストケース（エラーハンドリング）

### TC-A01: FixedPhaseSpec は frozen — フィールド再代入で FrozenInstanceError 🔵 (対応: §4 不変性)

- **テスト名**: `test_fixed_phase_spec_is_frozen`
  - **エラーケースの概要**: frozen dataclass のフィールドへ再代入を試みる。
  - **エラー処理の重要性**: 値オブジェクトの不変性を破る変更を型レベルで阻止し、プリセット汚染を防ぐ。
- **入力値**: `spec = CELL_PHASE_PRESETS["Be"]` に対し `spec.label = "x"`。
  - **不正な理由**: frozen dataclass はフィールド再代入不可 (P2 非破壊規約)。
  - **実際の発生シナリオ**: 呼び側が誤ってプリセットを直接書き換えようとする。
- **期待される結果**: `with pytest.raises(dataclasses.FrozenInstanceError):`。
  - **エラーメッセージの内容**: frozen インスタンスへの代入である旨。
  - **システムの安全性**: プリセット定数が実行時に破壊されない。
- **テストの目的**: 不変性の担保 (frozen)。
  - **品質保証の観点**: 共有される定数の安全性を保証。
- 🔵 信頼性: interfaces.py L236 (frozen=True) / CLAUDE.md 非破壊規約に直接依拠。

### TC-A02: 未知プリセットキーは KeyError 🟡 (対応: Mapping 契約)

- **テスト名**: `test_cell_phase_presets_unknown_key_raises_keyerror`
  - **エラーケースの概要**: `CELL_PHASE_PRESETS` に存在しないキーを参照。
  - **エラー処理の重要性**: 未定義のセル材料を誤指定した際に沈黙せず明示的に失敗する。
- **入力値**: `CELL_PHASE_PRESETS["Cu"]` (未定義キー)。
  - **不正な理由**: プリセットは Be/Al/graphite の 3 種のみ (器の範囲)。
  - **実際の発生シナリオ**: 未対応材料をプリセット名で要求する。
- **期待される結果**: `with pytest.raises(KeyError):`。
  - **エラーメッセージの内容**: 存在しないキーである旨 (標準 Mapping 挙動)。
  - **システムの安全性**: 未定義プリセットを捏造せず例外で停止。
- **テストの目的**: Mapping 契約の標準挙動確認 (未定義キーの明示失敗)。
  - **品質保証の観点**: プリセット集合の閉性を担保。
- 🟡 信頼性: interfaces.py L244 (Mapping 型) からの標準挙動 (妥当推測)。

---

## 3. 境界値テストケース（最小値、最大値、null等）

### TC-BV01: 六方晶プリセットの orthohexagonal 近似 b == a·√3 🟡 (対応: 直方近似の核心 / 完了条件3)

- **テスト名**: `test_hexagonal_presets_orthohexagonal_b_equals_a_sqrt3`
  - **境界値の意味**: 六方晶 (Be/graphite) を直方近似する際の b 軸の決定式 `b = a·√3` の境界的正しさ。
  - **境界値での動作保証**: SimulatedBackend の直方 `_d_spacing` に整合する近似が正しく適用される。
- **入力値**: `CELL_PHASE_PRESETS["Be"]` と `["graphite"]` の `phase.lattice`。
  - **境界値選択の根拠**: 六方→直方近似の関係式 `b = a·√3` (要件定義 §2.2 / note.md の直方近似方針)。
  - **実際の使用場面**: 六方晶セル材料を SimulatedBackend が縮退なく扱えるかの分岐。
- **期待される結果**:
  - Be: `lattice.b == pytest.approx(lattice.a * math.sqrt(3.0))` (≈ 3.9591)
  - graphite: `lattice.b == pytest.approx(lattice.a * math.sqrt(3.0))` (≈ 4.2678)
  - **境界での正確性**: b が a と縮退せず √3 倍で分離される。
  - **一貫した動作**: 立方晶 (Al) とは異なる六方近似が両六方プリセットに一貫適用。
- **テストの目的**: 六方→直方近似の代数的正しさ (docstring 明記の近似)。
  - **堅牢性の確認**: a=b 縮退による b 方向反射消失を回避。
- 🟡 信頼性: 要件定義 §2.2 (orthohexagonal `b=a·√3`) / SimulatedBackend 直方近似に依拠 (近似方針は 🟡)。

### TC-BV02: 立方晶 Al は a==b==c (直方近似の歪みなし境界) 🟡 (対応: 完了条件3)

- **テスト名**: `test_al_preset_is_cubic_isotropic`
  - **境界値の意味**: 立方晶 (fcc Al) は直方近似で歪みが生じない等方境界 (a=b=c)。
  - **境界値での動作保証**: 六方近似のような軸変換を Al には適用しない。
- **入力値**: `CELL_PHASE_PRESETS["Al"].phase.lattice`。
  - **境界値選択の根拠**: 立方晶は直方系の特殊ケース (三軸等長)。近似歪みゼロの境界。
  - **実際の使用場面**: 集電体 Al の等方格子を正しく保持できるか。
- **期待される結果**: `lattice.a == lattice.b == lattice.c == pytest.approx(4.0495)`。角は既定 90°。
  - **境界での正確性**: 三軸が完全一致 (異方近似を誤適用しない)。
  - **一貫した動作**: 六方プリセット (b=a√3) と非対称に、立方は等長。
- **テストの目的**: 立方晶の等方性保持 (近似の場合分けの正しさ)。
  - **堅牢性の確認**: Al に六方近似を誤適用しないこと。
- 🟡 信頼性: 要件定義 §2.2 (Al fcc a=b=c) / 文献値に依拠 (格子値は 🟡)。

### TC-BV03: 固定相は scale のみ解放 — 精密化後も格子が不変 🟡 (対応: TC-203-02 / REQ-009)

- **テスト名**: `test_fixed_phase_lattice_unchanged_after_scale_only_refine`
  - **境界値の意味**: 「構造固定」を backend レベルで担保する境界 — scale のみ解放したとき lattice が 1 つも動かない。
  - **境界値での動作保証**: `fixed_free_suffixes` の `("scale",)` を free_params に使うと lattice は精密化対象外。
- **入力値**:
  - `fixed = CELL_PHASE_PRESETS["graphite"].phase.with_updates(scale=1.5)`。
  - `truth = (fixed,)`、`y = backend.simulate(truth, tt)`。
  - 初期 scale をずらした `start = (fixed.with_updates(scale=0.5),)`。
  - `free_params = {param_name(0, s) for s in fixed_free_suffixes(spec_graphite)}` (= `{"phase0.scale"}`)。
  - **境界値選択の根拠**: scale のみ解放 = lattice 解放パラメータ 0 個の境界 (構造完全固定)。
  - **実際の使用場面**: 固定相が探索に常駐しつつ格子が動かないこと (REQ-009)。
- **期待される結果**: 精密化後 `result.phases[0].lattice.a/b/c` が入力の `fixed.lattice.a/b/c` と一致
  (`== pytest.approx(...)` で不変)。`result.phases[0].scale` は真値 1.5 へ収束。
  - **境界での正確性**: 解放していない lattice が 1 つも変化しない。
  - **一貫した動作**: scale だけが動き構造は固定。
- **テストの目的**: 「構造固定・scale のみ解放」の backend レベル担保 (TC-203-02)。
  - **堅牢性の確認**: lattice が free_params に無ければ `_recognized` が認識せず不変 (simulated.py L137-143)。
- 🟡 信頼性: TC-203-02 / REQ-009 / SimulatedBackend `_recognized` 挙動に依拠 (シナリオ構成は妥当推測)。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **言語選択の理由**: プロジェクト標準 (uv 管理 / src layout + hatchling / CLAUDE.md)。実装対象が Python。
  - **テストに適した機能**: `dataclasses.FrozenInstanceError` による不変性検証、`math.sqrt` による近似関係検証、
    `pytest.approx` による格子値近似照合、`SimulatedBackend` による合成データ精密化。
- **テストフレームワーク**: pytest (>= 8) + pytest-cov 🔵
  - **フレームワーク選択の理由**: 既存全テストが pytest。`pytest.raises`／`pytest.approx` が本タスク
    (frozen 例外・格子近似・scale 収束) に最適。CSV 等の外部 I/O が無いため `tmp_path` 不要。
  - **テスト実行環境**: `uv run pytest tests/test_cell_phases.py` (単体) / `uv run pytest` (全体回帰)。
    GSAS-II 非依存 (`gsas` マーカー不要)。**依存導入は `uv sync --extra gsas`**。
- 🔵 信頼性: `pyproject.toml` / 既存 `tests/test_simulated_backend.py` / note.md §5 に直接依拠。

---

## 5. テストケース実装時の日本語コメント指針 (代表例)

```python
def test_fixed_free_suffixes_returns_scale_only():
    # 【テスト目的】: 固定相の解放パラメータが scale のみ (構造固定) であることを確認 (TC-203-02)
    # 【テスト内容】: 全プリセットの spec に対し fixed_free_suffixes が ("scale",) を返す
    # 【期待される動作】: lattice/occupancy suffix を含まず scale のみが解放対象
    # 🟡 信頼性: TC-203-02 / REQ-009 / interfaces.py L238 に依拠

    # 【テストデータ準備】: Be/Al/graphite の 3 プリセットを走査対象にする (構造固定は材料非依存のため)
    for key in ("Be", "Al", "graphite"):
        spec = CELL_PHASE_PRESETS[key]

        # 【実際の処理実行】: 固定相の解放 suffix 展開ヘルパを呼ぶ
        # 【処理内容】: 構造固定・scale のみ解放の契約を単一の真実源から取得
        suffixes = fixed_free_suffixes(spec)

        # 【結果検証】: 戻り値が ("scale",) であること
        # 【期待値確認】: 構造 (lattice/occ) を解放しない REQ-009 字義
        assert suffixes == ("scale",)  # 【検証項目】: scale のみ解放 🟡


def test_active_phase_refines_with_fixed_cell_phase():
    # 【テスト目的】: 固定相込みの合成データで活物質相の scale が真値へ収束することを確認 (TC-203-03)
    # 【テスト内容】: 固定相 Al (scale のみ解放) + 活物質相を合成し scale を精密化
    # 【期待される動作】: セル材料ピーク重畳下でも活物質相 scale が真値へ
    # 🔵 信頼性: TC-203-03 / REQ-009 / test_simulated_backend の scale 収束に依拠

    # 【テストデータ準備】: 固定相 (真 scale 2.0) と活物質相 (真 scale 3.0) の合成パターン
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = np.arange(15.0, 80.0, 0.02)
    spec_al = CELL_PHASE_PRESETS["Al"]
    fixed_truth = spec_al.phase.with_updates(scale=2.0)
    active_truth = PhaseInstance("LFP", LatticeParams(5.0, 5.0, 5.0), scale=3.0)
    y = backend.simulate((fixed_truth, active_truth), tt)

    # 【初期条件設定】: scale をずらした初期相。固定相 scale + 活物質 scale のみ解放
    start_fixed = spec_al.phase.with_updates(scale=1.0)
    start_active = PhaseInstance("LFP", LatticeParams(5.0, 5.0, 5.0), scale=1.0)
    free = {param_name(0, s) for s in fixed_free_suffixes(spec_al)} | {param_name(1, "scale")}
    model = RefinementModel(
        phases=(start_fixed, start_active), free_params=frozenset(free), two_theta=tt, intensity=y
    )

    # 【実際の処理実行】: scale のみ解放で精密化
    result = backend.refine(model)

    # 【結果検証】: 活物質相 scale が真値 3.0 へ収束
    assert result.converged  # 【検証項目】: 収束 🔵
    assert result.phases[1].scale == pytest.approx(3.0, rel=0.05)  # 【検証項目】: 活物質相同定 🔵
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `cell-phase-presets-requirements.md` §1 (セル固定相プリセット層 / 構造固定・scale のみ解放・探索常駐)
- **参照した入力・出力仕様**: 同 §2 (FixedPhaseSpec / CELL_PHASE_PRESETS / fixed_free_suffixes)
- **参照した制約条件**: 同 §3 (直方近似・docstring 注意明記・決定論・非破壊・コア依存 numpy)
- **参照した使用例**: 同 §4 (プリセット取得 / 格子値検証 / scale のみ解放 / 固定相込み合成精密化 / frozen 不変性)
- **参照した受け入れ基準**: `docs/spec/m3-operando/acceptance-criteria.md` TC-203-01〜03
- **参照した設計文書**: `docs/design/m3-operando/interfaces.py` L232-244, `docs/design/m3-operando/dataflow.md` L18-19,
  `docs/design/m3-operando/architecture.md` L38/L114/L121, `src/tsumugin/backends/simulated.py` L67-75/L137-143 (直方近似・scale 認識)

---

## テストケース数内訳

| 区分 | 件数 | テスト ID |
|---|---|---|
| 正常系 | 7 | TC-N01〜TC-N07 |
| 異常系 | 2 | TC-A01〜TC-A02 |
| 境界値 | 3 | TC-BV01〜TC-BV03 |
| **合計** | **12** | — |

**AC 対応**: TC-203-01 → TC-N01・TC-N05 / TC-203-02 → TC-N03・TC-BV03 / TC-203-03 → TC-N06。
補助 (器の健全性): TC-N02 (格子値)・TC-N04/TC-A01 (frozen)・TC-N07 (決定論)・TC-A02 (Mapping)・TC-BV01/BV02 (直方近似)。

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 7 / 異常系 2 / 境界値 3 を網羅 (TC-203-01〜03 を全被覆)
- 期待値定義: 各ケースに具体的な期待値 (格子値・戻り値・例外型・scale 収束 rel) を明記
- 技術選択: Python 3.12 + pytest (pytest.raises/approx, SimulatedBackend, math.sqrt) で確定
- 実装可能性: 依存は stdlib (dataclasses/math) + 既存 SimulatedBackend/PhaseInstance のみで確実
- 信頼性レベル: 🔵 6 / 🟡 6 — 🟡 は格子定数値 (文献) と直方近似方針・固定粒度 (scale のみ) の設計裁量に集中 (要件へ遡及可能)
```

**次のお勧めステップ**: `/tsumiki:tdd-red m3-operando TASK-0030` で Red フェーズ (失敗テスト作成) を開始します。
