# TASK-0026 TDD テストケース定義 — backends 拡張 (global パラメータ文法 + 吸収補正 v1)

**機能名**: backends-absorption / **タスクID**: TASK-0026 / **要件名**: m3-operando
**フェーズ**: Phase 2 / **作成日**: 2026-07-04
**テスト先**: `tests/test_absorption.py` (新規)。既存 `tests/test_backend_interface.py` /
`tests/test_simulated_backend.py` は**無改変**で回帰維持 (新規正常系は test_absorption.py 側に書く)。

> 全パスはプロジェクトルート相対。**【信頼性凡例】** 🔵 資料依拠ほぼ推測なし / 🟡 妥当な推測 / 🔴 根拠なし推測

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 (uv 管理, src layout)。
  - **選択理由**: 既存コードベースが Python。前方モデル・LM 精密化は numpy ベクトル演算で表現。🔵
  - **テストに適した機能**: `pytest.approx` による浮動小数近似、`dataclasses.FrozenInstanceError` による
    不変性検証、numpy の `allclose` / ビット一致 (`==`) による決定論検証。
- **テストフレームワーク**: pytest (>=8) + pytest-cov。
  - **選択理由**: 既存 `tests/` が全て pytest。設定は `pyproject.toml [tool.pytest.ini_options]`。🔵
  - **テスト実行環境**: `uv run pytest tests/test_absorption.py` (単体) / `uv run pytest` (全体回帰) /
    `uv run pytest --cov=tsumugin`。依存導入は `uv sync --extra gsas`。本タスクのコアは GSAS-II 非依存
    (`gsas` マーカー不要)。GSASIIBackend docstring の検証は import のみで実 GSAS-II 不要。🔵
- 🔵 信頼性: `pyproject.toml` / `tests/test_simulated_backend.py` / `CLAUDE.md` に依拠。

---

## 1. 正常系テストケース（基本的な動作）

### T-N01: transmission_factor が μt>0 で exp(−μt/cosθ) を返し低角ほど小
- **何をテストするか**: `transmission_factor(2θ配列, μt>0)` が理論式 A(θ;μt)=exp(−μt/cosθ) と一致し、
  2θ 増加に対し単調増加 (=吸収減) すること。
- **入力値**: `tt = np.arange(15.0, 80.0, 0.02)`, `mu_t = 0.5`
  - **入力の意味**: 合成グリッド (既存 `_grid()` と同域)。μt=0.5 は現実的な中程度吸収。
- **期待される結果**: `np.allclose(factor, np.exp(-0.5 / np.cos(np.radians(tt/2))))` が True。
  `factor[0] < factor[-1]` (低角ほど小) かつ全域 `0 < factor < 1`。
- **確認ポイント**: θ = radians(2θ/2) の半角変換が正しいこと。形状が入力と同一。
- 🔵 信頼性: requirements 2.3 / architecture.md D8 L96 / interfaces.py L112-114 に依拠。

### T-N02: transmission_factor の特定角での数値一致
- **何をテストするか**: 2θ=0°近傍 (θ→0, cosθ→1) で factor≈exp(−μt)、既知点の数値正確性。
- **入力値**: `tt = np.array([0.0, 60.0])`, `mu_t = 1.0` → θ=[0°,30°]
- **期待される結果**: `factor[0] == pytest.approx(exp(-1.0))`,
  `factor[1] == pytest.approx(exp(-1.0/cos(radians(30))))`。
- **確認ポイント**: cosθ の分母計算が正しい。
- 🔵 信頼性: 式 A(θ;μt)=exp(−μt/cosθ) の直接評価。

### T-N03: parse_param("global.mu_t") が (-1, "mu_t") を返す
- **何をテストするか**: パラメータ文法拡張。head=="global" で相インデックス −1 を返す。
- **入力値**: `"global.mu_t"`
- **期待される結果**: `parse_param("global.mu_t") == (-1, "mu_t")`。
- **確認ポイント**: −1 が「大域」の標識。tail の抽出 (`"mu_t"`)。
- 🔵 信頼性: interfaces.py L93 / architecture.md D8 L94 に依拠。

### T-N04: RefinementResult が globals / warnings を明示値で保持
- **何をテストするか**: 新規末尾フィールドに値を渡すと保持されること。
- **入力値**: `RefinementResult(phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=1, converged=True,
  n_cycles=3, free_params=frozenset({"global.mu_t"}), globals={"mu_t": 0.42}, warnings=("w1",))`
- **期待される結果**: `.globals == {"mu_t": 0.42}` かつ `.warnings == ("w1",)`。
- **確認ポイント**: Mapping / tuple フィールドの保持。
- 🔵 信頼性: interfaces.py L95 / requirements 2.2 に依拠。

### T-N05: AbsorptionConfig の生成とフィールド保持
- **何をテストするか**: frozen dataclass が既定値・明示値で生成できフィールドを保持する。
- **入力値**: 既定 `AbsorptionConfig()` / 明示
  `AbsorptionConfig(mu_t_initial=0.3, mu_t_calc=0.5, restraint_weight=50.0, empirical_mode=False)`
- **期待される結果**: 既定 → `mu_t_initial==0.0`, `mu_t_calc is None`, `restraint_weight==100.0`,
  `empirical_mode is False`。明示 → 各値を保持。
- **確認ポイント**: 既定値が interfaces.py L101-104 と一致。
- 🔵 信頼性: interfaces.py L97-104 / requirements 2.3 に依拠。

### T-N06: from_cell_config(mu_t_calc あり) が強 restraint 構成を返す
- **何をテストするか**: `CellConfig.mu_t_calc` を restraint 中心 + 初期値に採り、強 restraint・
  非経験モードにすること。
- **入力値**: `CellConfig(geometry="transmission", mu_t_calc=0.6)`
- **期待される結果**: `cfg = AbsorptionConfig.from_cell_config(...)` →
  `cfg.mu_t_calc == 0.6`, `cfg.mu_t_initial == 0.6`, `cfg.restraint_weight == 100.0`,
  `cfg.empirical_mode is False`。
- **確認ポイント**: MuCalculator/xraylib を呼ばず `mu_t_calc` を読むだけ (REQ-019/403)。
- 🔵 信頼性: requirements 2.3 / REQ-017/019 / architecture.md D8 L99 に依拠。

### T-N07: empirical() が弱 restraint + 経験モードを返す
- **何をテストするか**: CellConfig 未提供ファクトリが弱 restraint・empirical_mode=True を返す。
- **入力値**: `AbsorptionConfig.empirical()`
- **期待される結果**: `mu_t_calc is None`, `restraint_weight == 1.0` (弱), `empirical_mode is True`。
- **確認ポイント**: 弱 w_r=1.0 (interfaces.py L103 注記)。強 (100.0) との差。
- 🔵 信頼性: interfaces.py L103/109 / REQ-018 に依拠 (w_r=1.0 は 🟡 既定値)。

### T-N08: simulate が μt>0 で透過因子を乗算する
- **何をテストするか**: absorption 設定時、simulate 出力が無補正出力に透過因子を掛けた値になること。
- **入力値**: `backend0 = SimulatedBackend(peak_fwhm=0.2)` (無補正),
  `backend1 = SimulatedBackend(peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5))`,
  同一 `phase`, `tt=_grid()`。
- **期待される結果**: `y1 ≈ y0 * transmission_factor(tt, 0.5)` (`np.allclose`)。低角ピークほど相対的に減衰。
- **確認ポイント**: 乗算が全 2θ に一様適用され、ピーク位置は不変 (吸収は強度のみ変える)。
- 🔵 信頼性: requirements 2.4 / architecture.md D8 L95-96 / REQ-020 に依拠。

### T-N09: refine が μt 真値を restraint 内で回収する (TC-207-02)
- **何をテストするか**: μt>0 で生成した合成データを μt=0 初期から精密化し `globals["mu_t"]` が真値回収。
- **入力値**: 真値 `mu_t_true=0.5` で `backend_true.simulate` した `y`。
  精密化は `absorption=AbsorptionConfig.from_cell_config(CellConfig("transmission", mu_t_calc=0.5))`
  だが `mu_t_initial` を敢えて 0.0 に上書き or 別途初期 0 の config。
  `free_params={"global.mu_t", "phase0.scale"}`。
- **期待される結果**: `result.converged`, `result.globals["mu_t"] == pytest.approx(0.5, abs=0.05)`
  (restraint 内で真値回収)。
- **確認ポイント**: μt=0 初期からでも restraint 中心 (0.5) 側へ収束。scale との相関で破綻しない。
- 🔵 信頼性: acceptance-criteria TC-207-02 / REQ-017 に依拠 (許容幅 abs=0.05 は 🟡)。

### T-N10: restraint が遠い解を抑制する (TC-207-03)
- **何をテストするか**: restraint 中心から遠ざかる方向のデータ/初期に対し、w_r 大で μt が中心へ引き戻される。
- **入力値**: restraint 中心 `mu_t_calc=0.3`・強 w_r=100.0 と、弱 w_r=1.0 の 2 構成で同一データを refine。
- **期待される結果**: 強 w_r の `globals["mu_t"]` の方が中心 0.3 に近い (`|強−0.3| < |弱−0.3|`)。
- **確認ポイント**: ペナルティ w_r·(μt−μt_calc)² が目的関数に効いている。
- 🔵 信頼性: acceptance-criteria TC-207-03 / requirements 2.4 に依拠。

### T-N11: 経験推定モードが警告 + 逆算 μt を出す (TC-207-04)
- **何をテストするか**: `AbsorptionConfig.empirical()` で refine すると弱 restraint で μt を精密化し、
  warnings に経験推定モード明示 + 逆算 μt 提示が入る。
- **入力値**: `absorption=AbsorptionConfig.empirical()`, `free_params={"global.mu_t","phase0.scale"}`,
  μt>0 合成データ。
- **期待される結果**: `result.globals` に `"mu_t"` あり、`result.warnings` が非空で「経験推定」相当の語 +
  逆算 μt 値を含む (`any("経験" in w or "empirical" in w for w in result.warnings)`)。
- **確認ポイント**: 弱 restraint でも μt が動く。警告が必ず出る (REQ-018)。
- 🔵 信頼性: acceptance-criteria TC-207-04 / REQ-018 に依拠 (警告文面は 🟡)。

### T-N12: refine 結果の free_params と globals の整合
- **何をテストするか**: `"global.mu_t"` を解放すると `result.free_params` に含まれ `result.globals` に
  記録される (相パラメータと大域パラメータの両立)。
- **入力値**: `free_params={"global.mu_t","phase0.scale"}`, absorption 設定。
- **期待される結果**: `"global.mu_t" in result.free_params`, `"mu_t" in result.globals`,
  `"phase0.scale" in result.free_params`。相 scale も従来どおり精密化される。
- **確認ポイント**: 大域と相のパラメータが同一 refine で共存 (parse_param −1 分岐と phase 分岐の共存)。
- 🔵 信頼性: architecture.md D8 / requirements 2.4 に依拠。

### T-N13: GSASIIBackend の docstring が scale 畳み込み近似を明記 (REQ-020)
- **何をテストするか**: v1 の GSAS-II 吸収は scale への畳み込み近似である旨が docstring に明記されている。
- **入力値**: `GSASIIBackend.__doc__` (import のみ、実 GSAS-II 不要)。
- **期待される結果**: docstring に「吸収」/「absorption」かつ「scale」/「畳み込み」相当の語を含む。
- **確認ポイント**: 実装追加でなくドキュメント制約 (@gsas テスト増やさない)。
- 🟡 信頼性: architecture.md D8 L101 / REQ-020 に依拠 (docstring 文面は裁量)。

---

## 2. 異常系テストケース（エラーハンドリング）

### T-E01: parse_param の不正名が ValueError を送出する (非干渉維持)
- **エラーケースの概要**: global 分岐追加後も、phase/global いずれでもない名前・tail 空は従来どおり拒否。
- **入力値**: `"foo.bar"`, `"global"` (tail 空), `""`, `"globalmu_t"` (ドットなし)
- **不正な理由**: 正準文法 (`phase{i}.*` / `global.*`) に合致しない。
- **期待される結果**: いずれも `pytest.raises(ValueError)`。
- **システムの安全性**: 不正パラメータ名を沈黙採用せず fail-loud。
- **品質保証の観点**: global 分岐が既存の厳格性を緩めていないこと。
- 🔵 信頼性: `src/tsumugin/backends/base.py` L60-61 の既存挙動 + 追加分岐の境界に依拠。

### T-E02: RefinementResult が frozen (再代入で FrozenInstanceError)
- **エラーケースの概要**: 不変値オブジェクトへの再代入拒否 (新フィールド追加後も frozen 維持)。
- **入力値**: `r.globals = {...}` / `r.warnings = (...)` への代入
- **期待される結果**: `pytest.raises(dataclasses.FrozenInstanceError)`。
- **システムの安全性**: 状態の不変性 (P2) を保つ。
- 🔵 信頼性: `tests/test_backend_interface.py` L41-42 の frozen 検証パターンに依拠。

### T-E03: AbsorptionConfig が frozen (再代入で FrozenInstanceError)
- **エラーケースの概要**: 吸収設定の不変性。
- **入力値**: `cfg.mu_t_initial = 1.0` への代入
- **期待される結果**: `pytest.raises(dataclasses.FrozenInstanceError)`。
- 🔵 信頼性: frozen dataclass 規約 (CLAUDE.md) / interfaces.py L97 に依拠。

### T-E04: restraint 幅超逸脱で相関疑い警告 (TC-207-06 / REQ-103)
- **エラーケースの概要**: fitted μt が restraint 中心から許容幅を超えて逸脱 → 相関疑い警告。
- **入力値**: restraint 中心 `mu_t_calc=0.2` に対し、μt が大きく逸脱する合成データ (例: 真 μt≈1.0) +
  弱め restraint で refine (中心から離れた解に収束させる)。
- **期待される結果**: `result.warnings` が非空で「相関」/「restraint」/「逸脱」相当の警告を含む
  (`any("相関" in w or "restraint" in w for w in result.warnings)`)。
- **システムの安全性**: 誤収束の可能性 (§14 相関リスク) をユーザー/エージェントに通知。
- **品質保証の観点**: 沈黙した誤 μt を返さず警告付きで返す。
- 🔵 信頼性: acceptance-criteria TC-207-06 / REQ-103 / §14 に依拠 (許容幅定義は 🟡 設計裁量)。

### T-E05: XraylibMuCalculator.mu_t が NotImplementedError (回帰 TC-207-07)
- **エラーケースの概要**: 組成→μt 計算は M3 未実装 (TASK-0025 で確立、本タスクは回帰確認)。
- **入力値**: `XraylibMuCalculator().mu_t(CellConfig("transmission"))`
- **期待される結果**: `pytest.raises(NotImplementedError)`。
- **品質保証の観点**: 本タスクが xraylib へ実依存を持ち込んでいないこと (REQ-403)。
- 🔵 信頼性: acceptance-criteria TC-207-07 / `src/tsumugin/model/cell.py` L90-97 に依拠。

---

## 3. 境界値テストケース（最小値・境界・null・回帰）

### T-B01: transmission_factor(μt=0) が全域 1.0 (EDGE-006)
- **境界値の意味**: μt=0 (吸収なし) の境界。exp(0)=1。
- **入力値**: `transmission_factor(np.arange(15,80,0.02), 0.0)`
- **境界での正確性**: 全要素が厳密に 1.0 (`np.all(factor == 1.0)` または `np.allclose(factor, 1.0)`)。
- **一貫した動作**: μt→0 で滑らかに 1 へ (μt=1e-9 でも ≈1)。
- **堅牢性**: 補正因子 1 = 無補正の代数的保証。
- 🔵 信頼性: EDGE-006 / acceptance-criteria TC-207-05 / interfaces.py L113 に依拠。

### T-B02: simulate(absorption=None) が既存出力とビット一致
- **境界値の意味**: 吸収設定なし = 従来経路。乗算をスキップ。
- **入力値**: `SimulatedBackend(peak_fwhm=0.2)` (absorption 省略) の simulate 出力を、
  拡張前と同一入力で比較。
- **境界での正確性**: `np.array_equal(y_new, y_reference)` (ビット一致)。
- **一貫した動作**: 既存 `tests/test_simulated_backend.py` の全 simulate/refine テストが無改変 green。
- 🔵 信頼性: REQ-404 非破壊 / EDGE-006 / `tests/test_simulated_backend.py` に依拠。

### T-B03: μt=0 の absorption 設定でも補正因子 1 で既存一致 (TC-207-05)
- **境界値の意味**: absorption を渡すが μt=0 のケース (設定はあるが吸収ゼロ)。
- **入力値**: `SimulatedBackend(peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.0))`
- **境界での正確性**: simulate 出力が無補正 backend とビット一致。refine で `"global.mu_t"` を解放しない
  限り既存 chi2/phases と一致。
- 🔵 信頼性: acceptance-criteria TC-207-05 / EDGE-006 に依拠。

### T-B04: global.mu_t 未解放時は μt 精密化せず globals 空
- **境界値の意味**: absorption 設定ありでも `free_params` に `"global.mu_t"` が無ければ μt 固定。
- **入力値**: `absorption=AbsorptionConfig(mu_t_initial=0.4)`,
  `free_params={"phase0.scale"}` ("global.mu_t" 無し)。
- **期待される結果**: `result.globals == {}` (μt はフィット対象外)、scale のみ精密化。
  simulate は初期 μt=0.4 の固定補正で回る (吸収は掛かるが μt はフィットしない)。
- **一貫した動作**: フィット対象は free_params が唯一の制御。
- 🟡 信頼性: requirements 2.4 (globals 記録は解放時のみ) からの妥当推測。

### T-B05: refine の決定論 (2 回実行でビット同一) (NFR-102)
- **境界値の意味**: 再現性の境界。乱数不使用の保証。
- **入力値**: μt 解放込みの同一 `RefinementModel` を 2 回 refine。
- **期待される結果**: `r1.chi2 == r2.chi2`, `r1.globals["mu_t"] == r2.globals["mu_t"]`,
  `r1.warnings == r2.warnings`, `r1.phases == r2.phases`。
- **堅牢性**: μt フィット追加後も決定論を維持。
- 🔵 信頼性: NFR-102 / REQ-402 / `tests/test_simulated_backend.py::test_deterministic` に依拠。

### T-B06: RefinementResult 既定生成で globals={} / warnings=() (後方互換)
- **境界値の意味**: 新フィールドを省略した既存呼び出しの後方互換。
- **入力値**: `RefinementResult(phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=0, converged=True,
  n_cycles=1)` (7 引数、新フィールド省略)。
- **期待される結果**: 生成成功、`.globals == {}`, `.warnings == ()`。
- **一貫した動作**: 既存の RefinementResult 生成箇所 (simulated.py / gsasii.py / test) が無改変で通る。
- 🔵 信頼性: REQ-404 / `tests/test_backend_interface.py` L38-40 の既存生成に依拠。

### T-B07: from_cell_config(mu_t_calc=None) が経験推定へフォールバック
- **境界値の意味**: CellConfig はあるが μt 未算出 (mu_t_calc=None) の境界 → 経験推定相当。
- **入力値**: `AbsorptionConfig.from_cell_config(CellConfig("transmission"))` (mu_t_calc 既定 None)
- **期待される結果**: `empirical_mode is True`, `mu_t_calc is None`, `restraint_weight == 1.0` (弱)
  (= `empirical()` 相当)。
- **一貫した動作**: 強/弱 restraint モードの分岐が mu_t_calc の有無で決まる。
- 🟡 信頼性: requirements 2.3 のフォールバック方針 (REQ-018 から妥当推測)。

### T-B08: 全体回帰 — 既存 477 collected を無退行維持
- **境界値の意味**: 拡張全体が既存資産を壊さないゲート。
- **入力値**: `uv run pytest` (全体)。
- **期待される結果**: ベースライン **477 collected** が維持 (474 passed + @gsas 3 skip)、既存テストファイル
  無改変。新規 `tests/test_absorption.py` 分だけ collected 数が増える。
- **堅牢性**: parse_param global 分岐 / RefinementResult 拡張 / SimulatedBackend absorption 追加が
  非破壊であることの最終確認。
- 🔵 信頼性: CLAUDE.md 不変条件 / REQ-404 / note.md ベースライン計測 (477) に依拠。

---

## テストケースサマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 (基本動作) | 13 | T-N01〜T-N13 |
| 異常系 (エラー処理) | 5 | T-E01〜T-E05 |
| 境界値 (境界・null・回帰) | 8 | T-B01〜T-B08 |
| **合計** | **26** | |

### 受け入れ基準 (TC-207 系) への対応

| AC | 内容 | 対応テスト |
|---|---|---|
| TC-207-02 | μt>0 データを μt=0 初期から精密化し真値回収 (restraint 内) | T-N09 |
| TC-207-03 | restraint がペナルティとして機能 (遠い解を抑制) | T-N10 |
| TC-207-04 | CellConfig 未提供 → 弱 restraint + 警告 + 逆算 μt | T-N11, T-N07, T-B07 |
| TC-207-05 | μt=0 境界で補正因子 1・既存一致 (無退行 / EDGE-006) | T-B01, T-B02, T-B03 |
| TC-207-06 | μt が restraint 幅超で逸脱 → 相関疑い警告 (REQ-103) | T-E04 |
| TC-207-01 | CellConfig 生成・シリアライズ (TASK-0025 充足) | 回帰のみ (既存 test_model_m3) |
| TC-207-07 | MuCalculator 未実装 NotImplementedError (TASK-0025 充足) | T-E05 (回帰) |

### 要件定義との対応関係
- **参照した機能概要**: requirements.md §1 (吸収補正 v1 / global パラメータ文法)
- **参照した入力・出力仕様**: requirements.md §2.1〜2.6 (parse_param / RefinementResult /
  AbsorptionConfig / transmission_factor / SimulatedBackend / GSASIIBackend)
- **参照した制約条件**: requirements.md §3 (非破壊 / 無退行 477 / 決定論 / numpy のみ / μt=0 一致)
- **参照した使用例**: requirements.md §4 (基本パターン / EDGE-006 / TC-207-04/06 / MuCalculator)

### 品質判定
```
✅ 高品質:
- テストケース分類: 正常系 13 / 異常系 5 / 境界値 8 で網羅 (機能・エラー・境界・回帰)
- 期待値定義: 各ケースで具体値・許容幅・比較演算子を明記 (approx / allclose / == / raises)
- 技術選択: Python 3.12 + pytest 確定 (既存資産準拠)
- 実装可能性: 既存 LM refine ループ拡張 + frozen dataclass + numpy で確実に実現
- 信頼性レベル: 🔵 が主 (受け入れ基準 TC-207 系と 1:1)。🟡 は w_r 既定値・許容幅・警告文面・
  フォールバック方針に限定
```
**信頼性分布**: 🔵 21 / 🟡 5 / 🔴 0。

**次のお勧めステップ**: `/tsumiki:tdd-red m3-operando TASK-0026` で Red フェーズ (失敗テスト作成) を開始します。
