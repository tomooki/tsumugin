# TASK-0018 TDD テストケース定義書 — thermal (熱膨張ベースライン + 転移温度推定)

**機能名**: thermal / **タスクID**: TASK-0018 / **要件名**: m2-sequential
**対象実装**: `src/tsumugin/sequential/thermal.py` / **テスト**: `tests/test_thermal.py`
**作成日**: 2026-07-03

**【信頼性レベル凡例】**: 🔵 元資料に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測

> 対象純関数は 2 本: `fit_thermal_baseline(temperatures, values, *, degree=1) -> ThermalBaseline`
> と `estimate_transition(temperatures, fractions, *, phase_ref) -> TransitionEstimate | None`。
> 書式は `tests/test_changepoint.py` (TASK-0015) を範とし、決定論は `==` (pytest.approx 禁止)、
> 係数/温度近似は `pytest.approx`、非有限漏洩は `math.isfinite`、frozen は `FrozenInstanceError`。
> 対象モジュール未実装のため import が collection 時に失敗し全テストが Red になる想定。

---

## 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **言語選択の理由**: 既存 `tsumugin` は Python 3.12 (uv + src layout)。numpy による多項式フィット
    (`numpy.polyfit`) とロバスト統計が容易。🔵 (`CLAUDE.md`, `pyproject.toml`)
  - **テストに適した機能**: dataclass の構造的 `==` で決定論のビット同一検証が簡潔。
- **テストフレームワーク**: pytest 🔵
  - **フレームワーク選択の理由**: `[tool.pytest.ini_options]` 済み、既存テストが全て pytest。
    `pytest.approx` (近似)、`pytest.raises(FrozenInstanceError)` (frozen)、`parametrize` (境界)。
  - **テスト実行環境**: `uv run pytest tests/test_thermal.py`。GSAS-II 非依存で `@pytest.mark.gsas` 不要。
- 🔵 信頼性レベル: `CLAUDE.md` / `pyproject.toml` / `tests/test_changepoint.py` に依拠。

---

## テストケース一覧 (18 件)

| 分類 | fit_thermal_baseline | estimate_transition | 小計 |
|---|---|---|---|
| 正常系 | TB-N01〜N04 (4) | TE-N01〜N03 (3) | 7 |
| 異常系/縮退 | TB-E01〜E03 (3) | TE-E01〜E03 (3) | 6 |
| 境界値 | TB-B01〜B02 (2) | TE-B01〜B03 (3) | 5 |
| **合計** | **9** | **9** | **18** |

受け入れ基準対応: **TC-105-03** → TB-N01 / **TC-105-04** → TE-N01 / **TC-105-05** (決定論) → TB-B02 + TE-B03。

---

# 1. 正常系テストケース（基本的な動作）

## TB-N01: 線形熱膨張 + 転移ジャンプで係数真値近傍・逸脱フレーム分離 (TC-105-03)

- **何をテストするか**: `fit_thermal_baseline` が 1 次ベースラインをフィットし、ジャンプフレームを
  `outlier_frames` として分離すること。
- **期待される動作**: 1 次係数 (傾き・切片) が真値近傍、ジャンプを与えたフレーム index が `outlier_frames` に含まれる。
- **入力値**: `temperatures = [300, 310, ..., 490]` (20 点, 10 K 刻み)、
  `values[i] = 5.0 + 1e-4*(T-300)` にフレーム 12〜19 へ +0.05 のジャンプを加えた合成格子列。
  - **入力データの意味**: 線形熱膨張 + 途中の構造相転移 (格子不連続) の代表。TC-105-03 の合成データ。
- **期待される結果**: `coefficients[1] == pytest.approx(1e-4, rel=0.3)` 近傍、`12 in outlier_frames`、
  ジャンプ前の滑らかフレーム (例 0〜5) は `outlier_frames` に含まれない。
  - **期待結果の理由**: ロバスト回帰的発想 (残差ロバスト z 超過) でジャンプ領域のみ逸脱判定されるため。
- **テストの目的**: ベースライン係数推定 + 逸脱分離の中核動作。
  - **確認ポイント**: 逸脱フレームが正しく分離され、正常フレームを誤検出しない (false-positive 抑制)。
- 🔵 信頼性レベル: 受け入れ基準 TC-105-03 / requirements REQ-007 に直接依拠 (合成値は Red 較正)。

## TB-N02: 係数が低次から順に格納される (polyfit 反転)

- **何をテストするか**: `ThermalBaseline.coefficients` が **低次→高次** の順であること。
- **期待される動作**: numpy.polyfit の高次→低次を反転して格納。1 次では `coefficients = (切片, 傾き)`。
- **入力値**: 傾き既知の純線形 `values[i] = 2.0 + 0.5*temperatures[i]`、`temperatures = [0,1,2,3,4]`。
  - **入力データの意味**: 係数順序を明確に判別できる (切片 2.0 ≠ 傾き 0.5) 単純入力。
- **期待される結果**: `coefficients[0] == pytest.approx(2.0)` (切片), `coefficients[1] == pytest.approx(0.5)` (傾き)。
  - **期待結果の理由**: interfaces.py の「低次から」契約。polyfit をそのまま格納すると逆順になるバグを検出。
- **テストの目的**: 係数順序契約の遵守 (off-by-order バグ検出)。
  - **確認ポイント**: polyfit の返り順を鵜呑みにしていないこと。
- 🟡 信頼性レベル: interfaces.py L177 「低次から」注記 (🟡) に依拠。

## TB-N03: residuals が実測−フィット値で values と同長・同順

- **何をテストするか**: `residuals` が各フレームの `values[i] - 予測[i]` で、`values` と同長・同順であること。
- **期待される動作**: 完全線形入力なら残差はほぼ全て 0 近傍。
- **入力値**: TB-N02 と同じ純線形入力。
  - **入力データの意味**: 残差の定義 (SSR ではなく点毎残差) を明確に検証。
- **期待される結果**: `len(residuals) == len(values)`、全 `abs(r) < 1e-9`、`all(math.isfinite(r))`。
  - **期待結果の理由**: 逸脱判定は点毎残差列に対して行うため点毎の残差が必要。非有限漏洩なし。
- **テストの目的**: residuals の定義・長さ・有限性。
  - **確認ポイント**: SSR (単一値) や polyfit の `residuals` 出力ではなく点毎残差であること。
- 🔵 信頼性レベル: interfaces.py L179 residuals 契約 + CLAUDE.md 非有限漏洩に依拠。

## TB-N04: degree=2 の二次多項式フィット

- **何をテストするか**: `degree=2` 指定で 2 次多項式がフィットされ `coefficients` が 3 要素になること。
- **期待される動作**: 2 次曲線入力で係数が真値近傍、残差ほぼ 0。
- **入力値**: `values[i] = 1.0 + 0.2*T + 0.01*T**2`、`temperatures=[0..5]`、`degree=2`。
  - **入力データの意味**: 高次熱膨張 (非線形) のフィット可能性。
- **期待される結果**: `len(coefficients) == 3`、`coefficients == pytest.approx((1.0, 0.2, 0.01), rel=1e-3)`。
  - **期待結果の理由**: degree=n で係数 n+1 個、低次から。
- **テストの目的**: degree パラメータの汎用性。
  - **確認ポイント**: degree 既定 1 に固定していないこと。
- 🟡 信頼性レベル: interfaces.py の `degree` 引数から妥当な推測。

## TE-N01: シグモイド遷移で midpoint±1 間隔・onset<midpoint・σ>0 (TC-105-04)

- **何をテストするか**: `estimate_transition` が相分率シグモイド遷移から onset/midpoint/σ を推定すること。
- **期待される動作**: `midpoint` が真の 50% 交差温度の ±1 フレーム間隔以内、`onset < midpoint`、`sigma > 0`、
  `direction == "appearing"`。
- **入力値**: `temperatures = [300..490]` (20 点, 10 K 刻み)、
  `fractions[i] = 1/(1+exp(-(T-400)/15))` (中心 400 K のシグモイド, 0→1)。
  - **入力データの意味**: 相が昇温で出現するシグモイド遷移の代表。TC-105-04 の合成データ。
- **期待される結果**: `abs(est.midpoint - 400) <= 10` (±1 間隔=10 K)、`est.onset < est.midpoint`、
  `est.sigma > 0`、`est.direction == "appearing"`、`math.isfinite(est.midpoint)`。
  - **期待結果の理由**: 50% 交差の線形補間で midpoint≈400 K、10% 交差 (onset) は低温側、σ は遷移幅で正。
- **テストの目的**: 転移温度推定の中核動作。
  - **確認ポイント**: onset<midpoint の順序、σ が正、方向が appearing。
- 🔵 信頼性レベル: 受け入れ基準 TC-105-04 / requirements REQ-008 に直接依拠 (合成値は Red 較正)。

## TE-N02: 減少方向 (1→0) で direction="disappearing"

- **何をテストするか**: 分率が減少するシグモイドで `direction == "disappearing"` になること。
- **期待される動作**: 1→0 の遷移で消滅方向判定、midpoint は 50% 交差で推定される。
- **入力値**: `fractions[i] = 1/(1+exp((T-400)/15))` (1→0 の減少シグモイド)、`temperatures=[300..490]`。
  - **入力データの意味**: 相が昇温で消滅する遷移の代表。方向判定 (🟡 完了条件) の検証。
- **期待される結果**: `est.direction == "disappearing"`、`est.midpoint == pytest.approx(400, abs=10)`、`est.sigma > 0`。
  - **期待結果の理由**: 分率が減少基調 → disappearing。midpoint は 50% 交差で方向非依存に推定。
- **テストの目的**: 方向判定ロジックの分岐。
  - **確認ポイント**: 増加/減少で direction が切り替わること。
- 🟡 信頼性レベル: interfaces.py L191 direction (🟡) / タスク完了条件「方向判定 🟡」に依拠。

## TE-N03: phase_ref が結果に保持される

- **何をテストするか**: 入力 `phase_ref` が `TransitionEstimate.phase_ref` にそのまま保持されること。
- **期待される動作**: 任意識別子が透過的に保持される。
- **入力値**: TE-N01 と同じシグモイド、`phase_ref="phase_B"`。
  - **入力データの意味**: 複数相の推定結果を区別する識別子の透過性。
- **期待される結果**: `est.phase_ref == "phase_B"`。
  - **期待結果の理由**: interfaces.py の TransitionEstimate.phase_ref フィールド契約。
- **テストの目的**: 識別子の透過保持。
  - **確認ポイント**: 加工・上書きせずそのまま格納。
- 🔵 信頼性レベル: interfaces.py L187 phase_ref に直接依拠。

---

# 2. 異常系テストケース（縮退の非例外化・非破壊契約）

## TB-E01: 完全フィット (残差 MAD=0) で outlier_frames=() ・非有限漏洩なし

- **エラーケースの概要**: 残差がすべて 0 (完全線形入力) → 残差 MAD=0 でロバスト z が 0 除算になる境界。
- **エラー処理の重要性**: 0 除算で `inf`/`nan` を下流に漏らさない (M1 教訓 / CLAUDE.md)。
- **入力値**: TB-N02 の純線形入力 (残差全 0)。
  - **不正な理由**: 不正ではなく縮退。散布度ゼロで z が定義できない。
  - **実際の発生シナリオ**: 熱膨張が完全に線形で逸脱が一切ない安定加熱区間。
- **期待される結果**: `outlier_frames == ()`、例外なし、`all(math.isfinite(r) for r in residuals)`。
  - **エラーメッセージの内容**: なし (例外化しない。安全側の空タプル縮退)。
  - **システムの安全性**: MAD=0 ガードで発火せず、非有限を漏らさない。
- **テストの目的**: MAD=0 縮退 (changepoint.py `_robust_z` パターン踏襲) の確認。
  - **品質保証の観点**: 定数残差入力でクラッシュ・誤検出しない堅牢性。
- 🔵 信頼性レベル: CLAUDE.md 非有限漏洩禁止 / changepoint.py MAD=0 縮退パターンに依拠。

## TB-E02: 点数不足 (len < degree+1) で例外化せず縮退

- **エラーケースの概要**: フィットに必要な点数未満 (例 degree=1 で 1 点)。polyfit が解けない。
- **エラー処理の重要性**: 短いトラジェクトリ末端等で発生。例外でなく安全側縮退が下流に優しい。
- **入力値**: `temperatures=[300.0]`, `values=[5.0]`, `degree=1` (2 点必要に対し 1 点)。
  - **不正な理由**: degree+1 未満で最小二乗解が一意でない。
  - **実際の発生シナリオ**: 単一フレーム区間・欠損後の断片。
- **期待される結果**: 例外を送出しない。`ThermalBaseline` を返し `outlier_frames == ()`、
  residuals/coefficients に非有限を含まない (縮退方針は Red で確定: 空係数 or 定数フィット)。
  - **システムの安全性**: 母数不足を例外化せず縮退値へ一元化 (changepoint warm-up と同思想)。
- **テストの目的**: 点数不足の安全側縮退。
  - **品質保証の観点**: 短い入力でクラッシュしない。
- 🟡 信頼性レベル: changepoint.py warm-up 縮退思想からの妥当な推測 (具体縮退値は Red で確定)。

## TB-E03: ThermalBaseline が frozen で再代入不可

- **エラーケースの概要**: 結果オブジェクトの事後改変 (誤用)。
- **エラー処理の重要性**: frozen による不変性は決定論・非破壊契約の前提。
- **入力値**: TB-N02 で得た `ThermalBaseline` に `baseline.coefficients = (...)` を代入。
  - **不正な理由**: frozen dataclass は属性再代入禁止。
  - **実際の発生シナリオ**: 実行中の誤った書き換え。
- **期待される結果**: `pytest.raises(FrozenInstanceError)`。
  - **システムの安全性**: 状態改変を型レベルで禁止。
- **テストの目的**: frozen 契約の確認。
  - **品質保証の観点**: 不変性 = 再現性の担保。
- 🔵 信頼性レベル: interfaces.py L173 `@dataclass(frozen=True)` / CLAUDE.md frozen 規約に依拠。

## TE-E01: 定数分率 (遷移なし) で None を返す

- **エラーケースの概要**: 分率が全フレーム定数 (相構成が変化しない) → 転移が存在しない。
- **エラー処理の重要性**: 「遷移なし」を誤って数値化しない (偽の転移温度を出さない)。
- **入力値**: `fractions = [0.5]*20` (定数)、`temperatures=[300..490]`、`phase_ref="A"`。
  - **不正な理由**: 不正ではなく「転移なし」の正当な入力。50% 交差の遷移が起きない。
  - **実際の発生シナリオ**: 相が全区間で安定 (等温セグメント)。
- **期待される結果**: `estimate_transition(...) is None`。
  - **システムの安全性**: 交差なしを None で表現し、偽の onset/midpoint を返さない。
- **テストの目的**: 遷移なし → None (完了条件)。
  - **品質保証の観点**: false-positive の転移温度を出さない。
- 🔵 信頼性レベル: interfaces.py L201「遷移が無い場合は None」/ タスク完了条件「定数分率で None 🔵」に依拠。

## TE-E02: 単一フレーム / 空入力で None を返す

- **エラーケースの概要**: 補間に必要な隣接フレーム対が作れない (点数 < 2)。
- **エラー処理の重要性**: 線形補間は 2 点必要。母数不足で例外化しない。
- **入力値**: (a) `temperatures=[]`, `fractions=[]` / (b) `temperatures=[400.0]`, `fractions=[0.5]`。
  - **不正な理由**: 交差を評価する隣接対が存在しない。
  - **実際の発生シナリオ**: 空トラジェクトリ・単一フレーム区間。
- **期待される結果**: 両ケースとも `estimate_transition(...) is None`、例外なし。
  - **システムの安全性**: 母数不足を None へ一元化 (EDGE-001/101 と同思想)。
- **テストの目的**: 空・単一入力の安全側縮退。
  - **品質保証の観点**: 端末フレームでクラッシュしない。
- 🟡 信頼性レベル: 受け入れ基準 EDGE-001/101 (空・単一) の思想からの妥当な推測。

## TE-E03: TransitionEstimate が frozen で再代入不可

- **エラーケースの概要**: 推定結果オブジェクトの事後改変。
- **エラー処理の重要性**: frozen は決定論・非破壊契約の前提。
- **入力値**: TE-N01 で得た `TransitionEstimate` に `est.midpoint = 0.0` を代入。
  - **不正な理由**: frozen dataclass は再代入禁止。
  - **実際の発生シナリオ**: 実行中の誤った書き換え。
- **期待される結果**: `pytest.raises(FrozenInstanceError)`。
  - **システムの安全性**: 状態改変を型レベルで禁止。
- **テストの目的**: frozen 契約の確認。
  - **品質保証の観点**: 不変性 = 再現性の担保。
- 🔵 信頼性レベル: interfaces.py L183 `@dataclass(frozen=True)` に依拠。

---

# 3. 境界値テストケース（最小点数・交差境界・決定論）

## TB-B01: 最小点数 (len == degree+1) でフィット可能

- **境界値の意味**: フィットに必要な最小点数ちょうど (TB-E02 の点数不足と対称)。
- **境界値での動作保証**: 最小二乗が一意に解ける下限境界。
- **入力値**: `temperatures=[300.0, 310.0]`, `values=[5.0, 5.001]`, `degree=1` (2 点 == degree+1)。
  - **境界値選択の根拠**: `len == degree+1` が縮退でなくフィット実行される境界。
  - **実際の使用場面**: 最短の有効トラジェクトリ。
- **期待される結果**: 例外なし、`len(coefficients) == 2`、残差ほぼ 0 (2 点直線は完全フィット)、`outlier_frames == ()`。
  - **境界での正確性**: 2 点直線を正しく通す。
  - **一貫した動作**: `len==degree+1` は実行、`len<degree+1` (TB-E02) は縮退。
- **テストの目的**: 最小フィット点数の off-by-one 境界。
  - **堅牢性の確認**: 最小入力で安定フィット。
- 🟡 信頼性レベル: polyfit の数学的要件からの妥当な推測。

## TB-B02: 決定論 — fit_thermal_baseline が 2 回でビット同一 (TC-105-05)

- **境界値の意味**: 再解析・監査での再現性 (「ほぼ同じ」不可)。
- **境界値での動作保証**: 純関数で乱数・順序依存なし。
- **入力値**: TB-N01 の合成データで `fit_thermal_baseline` を 2 回独立に呼ぶ。
  - **境界値選択の根拠**: 逸脱分離を含む複雑な入力で丸め揺らぎゼロを検証。
  - **実際の使用場面**: 監査・再現。
- **期待される結果**: `baseline1 == baseline2` (coefficients/residuals/outlier_frames 全一致)。
  - **境界での正確性**: float フィールド含め構造的等価。
  - **一貫した動作**: `pytest.approx` 禁止、`==` で厳密比較。
- **テストの目的**: 決定論ビット同一 (TC-105-05 の baseline 側)。
  - **堅牢性の確認**: 2 回呼び出しがビット同一。
- 🔵 信頼性レベル: 受け入れ基準 TC-105-05 / NFR-102 / REQ-402 に直接依拠。

## TE-B01: 50% 交差がフレーム端点ちょうどに一致する補間境界

- **境界値の意味**: あるフレームの分率がちょうど 0.5 (補間の端点)。
- **境界値での動作保証**: 交差点がグリッド上にある場合に補間が破綻しない。
- **入力値**: `fractions = [0.0, 0.25, 0.5, 0.75, 1.0]`, `temperatures=[300, 350, 400, 450, 500]`。
  - **境界値選択の根拠**: index 2 の分率が正確に 0.5。補間の端点一致は 0 除算・重複補間の罠。
  - **実際の使用場面**: 分率がグリッド上で丁度 50% になるフレーム。
- **期待される結果**: `est.midpoint == pytest.approx(400)`、例外なし、`math.isfinite(est.midpoint)`。
  - **境界での正確性**: 端点一致でも一意な温度を返す。
  - **一貫した動作**: 補間区間の内側/端点で結果が連続。
- **テストの目的**: 交差点グリッド一致の補間境界。
  - **堅牢性の確認**: 端点一致でクラッシュ・重複しない。
- 🟡 信頼性レベル: 線形補間 (interfaces.py midpoint 契約) からの妥当な推測。

## TE-B02: onset<midpoint の順序と σ が隣接フレーム間隔ベースで正

- **境界値の意味**: onset (10%) と midpoint (50%) の順序不変条件、σ の定義。
- **境界値での動作保証**: onset は必ず midpoint より遷移前側、σ は正の間隔ベース値。
- **入力値**: TE-N01 のシグモイド (0→1)。
  - **境界値選択の根拠**: 10% 交差と 50% 交差の相対位置・σ 定義を明示検証。
  - **実際の使用場面**: 転移の立ち上がり幅を評価する解析。
- **期待される結果**: `est.onset < est.midpoint`、`est.sigma > 0`、`math.isfinite(est.sigma)`、
  σ が隣接フレーム温度間隔 (例 10 K) のオーダー。
  - **境界での正確性**: onset≈10% 交差 < midpoint≈50% 交差。
  - **一貫した動作**: σ は隣接間隔ベースで有限・正。
- **テストの目的**: onset/midpoint 順序 + σ 定義 (🟡 推定式)。
  - **堅牢性の確認**: σ に 0・負・非有限を返さない。
- 🟡 信頼性レベル: interfaces.py onset=10%/σ=隣接間隔 (🟡 interview Q6) に依拠。

## TE-B03: 決定論 — estimate_transition が 2 回でビット同一 (TC-105-05)

- **境界値の意味**: 転移温度推定の再現性 (「ほぼ同じ」不可)。
- **境界値での動作保証**: 純関数で乱数・順序依存なし。
- **入力値**: TE-N01 のシグモイドで `estimate_transition` を 2 回独立に呼ぶ。
  - **境界値選択の根拠**: 補間・方向判定を含む推定で丸め揺らぎゼロを検証。
  - **実際の使用場面**: 監査・再現。
- **期待される結果**: `est1 == est2` (onset/midpoint/sigma/direction/phase_ref 全一致)。
  - **境界での正確性**: float フィールド含め構造的等価。
  - **一貫した動作**: `pytest.approx` 禁止、`==` で厳密比較。
- **テストの目的**: 決定論ビット同一 (TC-105-05 の transition 側)。
  - **堅牢性の確認**: 2 回呼び出しがビット同一。
- 🔵 信頼性レベル: 受け入れ基準 TC-105-05 / NFR-102 / REQ-402 に直接依拠。

---

## 5. テストケース実装時の日本語コメント指針

`tests/test_changepoint.py` に倣い、各テスト関数の冒頭に以下ブロックを付す:

```python
def test_baseline_linear_with_jump_separates_outliers():
    # 【テスト目的】: 線形熱膨張+ジャンプで係数真値近傍・逸脱フレーム分離を確認 (TB-N01 / TC-105-03)
    # 【テスト内容】: 20 フレーム線形格子 + 途中ジャンプで fit_thermal_baseline を呼ぶ
    # 【期待される動作】: 1 次係数が真値近傍、ジャンプフレームが outlier_frames に入る
    # 🔵 信頼性レベル: 受け入れ基準 TC-105-03 / REQ-007 に直接依拠 (合成値は Red 較正)

    # 【テストデータ準備】: 線形熱膨張 (5.0+1e-4*ΔT) にフレーム 12〜19 で +0.05 ジャンプを付与
    # 【初期条件設定】: temperatures は 300..490 の 10 K 刻み、degree 既定 1
    baseline = fit_thermal_baseline(temperatures, values)

    # 【結果検証】: 係数が真値近傍かつ逸脱フレームが正しく分離されること
    assert 12 in baseline.outlier_frames  # 【確認内容】: ジャンプフレームが逸脱判定される 🔵
    assert 0 not in baseline.outlier_frames  # 【確認内容】: 正常フレームは誤検出しない 🔵
```

- 決定論テストは `==` (pytest.approx 禁止)、近似は `pytest.approx`、非有限は `math.isfinite`、
  frozen は `pytest.raises(FrozenInstanceError)`。
- 純関数のため合成データはモジュールレベルで一度だけ構築 (状態レス)。

## 6. 要件定義との対応関係

- **参照した機能概要**: `thermal-requirements.md` §1 (fit_thermal_baseline / estimate_transition の 2 純関数)
- **参照した入力・出力仕様**: `thermal-requirements.md` §2 (引数/戻り値型・縮退方針) /
  `docs/design/m2-sequential/interfaces.py` L169-203
- **参照した制約条件**: `thermal-requirements.md` §3 (決定論・非有限漏洩禁止・frozen・polyfit 係数順)
- **参照した使用例**: `thermal-requirements.md` §4 (TC-105-03/04/05・エッジケース)
- **参照した受け入れ基準**: `docs/spec/m2-sequential/acceptance-criteria.md` L54-58 (TC-105-03/04/05)
- **参照した参考実装**: `src/tsumugin/sequential/changepoint.py` (ロバスト z・MAD=0 縮退・決定論・コメント様式)

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系 7 / 異常系 6 / 境界値 5 = 18 件で網羅
  (2 関数 × 正常・縮退・境界・決定論・frozen を各々カバー)
- 期待値定義: 各ケースに具体的な入力・期待値・検証手段 (approx/==/isfinite/raises) を明記
- 技術選択: Python 3.12 + pytest 確定 (既存スタック・test_changepoint.py 手本)
- 実装可能性: numpy polyfit + ロバスト z + 線形補間で確実 (changepoint.py に実装手本)
- 信頼性レベル: 🔵 中核 (TC-105-03/04/05・決定論・frozen・契約) / 🟡 推定式詳細 (onset/σ/方向/縮退値)
```

**信頼性レベル分布**: 🔵 11 (中核契約・受け入れ基準・決定論・frozen) / 🟡 7 (推定式 onset=10%・
σ=隣接間隔・方向判定・点数縮退・係数順・二次フィット・補間境界) / 🔴 0。

**次のお勧めステップ**: `/tsumiki:tdd-red m2-sequential TASK-0018` で Red フェーズ (失敗テスト作成) を開始します。
