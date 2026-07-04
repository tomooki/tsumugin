# TASK-0025 model 拡張 TDDテストケース定義書

**機能名**: model 拡張 (CellConfig / CellLayer / BeamConfig / channel kind / metrics.multistart / MuCalculator)
**タスクID**: TASK-0025 / **要件名**: m3-operando
**作成日**: 2026-07-04
**要件定義**: `docs/implements/m3-operando/TASK-0025/model-cell-extension-requirements.md`
**出力ファイル**: `docs/implements/m3-operando/TASK-0025/model-cell-extension-testcases.md`
**テスト対象実装**: `src/tsumugin/model/{cell,channel,hypothesis,__init__}.py`
**テストファイル**: `tests/test_model_m3.py` (新規。既存 `tests/test_model.py` / `tests/test_model_m2.py` は無改変)

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義・既存実装・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: 元の資料から妥当な推測
- 🔴 **赤信号**: 元の資料にない推測

---

## テストケース一覧サマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 | 10 | N-01〜N-10 |
| 異常系 | 4 | E-01〜E-04 |
| 境界値 | 7 | B-01〜B-07 |
| **合計** | **21** | |

**信頼性分布**: 🔵 17 / 🟡 4 / 🔴 0 — 品質評価: 高品質

### 完了条件との対応

| 完了条件 | 対応テストID |
|---|---|
| ① CellConfig/CellLayer/BeamConfig が frozen で生成・シリアライズ可能 (TC-207-01) | N-01〜N-06 / E-01〜E-03 / B-01〜B-03 / B-06 |
| ② channel kind 拡張が後方互換 | N-07 / B-04 / B-07 |
| ③ metrics.multistart 既定 None・非破壊 (REQ-006) | N-08 / B-05 |
| ④ XraylibMuCalculator が NotImplementedError (TC-207-07) | E-04 / N-09 |
| (公開面) re-export | N-10 |

---

## 1. 正常系テストケース（基本的な動作）

### N-01: CellLayer の明示値生成と属性取得
- **何をテストするか**: `CellLayer(role, material, thickness_mm, density)` が指定値で生成でき各属性を読み出せる。
  - **期待される動作**: frozen dataclass として生成され属性が指定どおり保持される。
- **入力値**: `CellLayer(role="window", material="Be", thickness_mm=0.5, density=1.85)`
  - **入力データの意味**: Be 窓 (層厚 0.5mm・密度 1.85) という代表的な operando セル層。
- **期待される結果**: `.role == "window"`、`.material == "Be"`、`.thickness_mm == 0.5`、`.density == 1.85`
  - **期待結果の理由**: interfaces.py L40-48 のフィールド定義に一致。
- **テストの目的**: 新設値オブジェクトの基本生成を確認。
  - **確認ポイント**: 4 フィールドが独立に保持されること。
- 🔵 (要件定義 2.1 / interfaces.py L40-48)

### N-02: CellLayer の等価比較
- **何をテストするか**: 同一フィールド値の 2 インスタンスが `==`、異なる値は `!=`。
  - **期待される動作**: frozen dataclass の自動生成 `__eq__` が値比較する。
- **入力値**: `CellLayer("window","Be",0.5) == CellLayer("window","Be",0.5)` / `!= CellLayer("window","Be",0.6)`
  - **入力データの意味**: 値オブジェクトとしての等価性 (M0〜M2 の不変値オブジェクト規約) を代表。
- **期待される結果**: 前者 True、後者 True (不等)。
  - **期待結果の理由**: dataclass eq=True (既定) による構造的等価。既定 `density=None` も比較に含まれる。
- **テストの目的**: 値等価の保証。
  - **確認ポイント**: density 既定 None も等価判定に寄与すること。
- 🔵 (要件定義 2.1)

### N-03: BeamConfig の生成と属性取得（wavelength / energy 両系）
- **何をテストするか**: `BeamConfig(wavelength=...)` と `BeamConfig(energy_kev=..., size_mm=...)` が生成でき属性を読み出せる。
  - **期待される動作**: 全フィールド既定値付きのため部分指定でも生成でき、指定値が保持される。
- **入力値**: `BeamConfig(wavelength=0.7)` / `BeamConfig(energy_kev=20.0, size_mm=(0.5, 0.5))`
  - **入力データの意味**: 波長系 (実験室系) とエネルギー系 (放射光) の 2 通りのビーム条件を代表。
- **期待される結果**: 前者 `.wavelength == 0.7`・`.energy_kev is None`・`.size_mm is None`。後者 `.energy_kev == 20.0`・`.size_mm == (0.5, 0.5)`・`.wavelength is None`。
  - **期待結果の理由**: interfaces.py L50-57 のフィールド定義に一致。energy/wavelength 一方必須の検証はしない (器のみ)。
- **テストの目的**: ビーム条件の基本生成と部分指定を確認。
  - **確認ポイント**: 指定しなかったフィールドが既定 None に縮退すること。
- 🔵 (要件定義 2.2 / interfaces.py L50-57)

### N-04: CellConfig の明示値生成と属性取得
- **何をテストするか**: `CellConfig(geometry, layers, beam, mu_t_calc)` が生成でき各属性を読み出せる。
  - **期待される動作**: frozen dataclass として生成され、ネスト値オブジェクト (layers/beam) を保持する。
- **入力値**: `CellConfig(geometry="transmission", layers=(CellLayer("window","Be",0.5),), beam=BeamConfig(wavelength=0.7), mu_t_calc=1.2)`
  - **入力データの意味**: 透過セル (Be 窓 1 層・μt=1.2) という吸収補正 v1 の代表入力。
- **期待される結果**: `.geometry == "transmission"`、`.layers == (CellLayer("window","Be",0.5),)`、`.beam == BeamConfig(wavelength=0.7)`、`.mu_t_calc == 1.2`
  - **期待結果の理由**: interfaces.py L59-67 のフィールド定義に一致。
- **テストの目的**: セル構成の基本生成を確認。
  - **確認ポイント**: layers が tuple、beam がネスト値オブジェクトとして保持されること。
- 🔵 (要件定義 2.3 / interfaces.py L59-67)

### N-05: CellConfig の等価比較（ネスト込み）
- **何をテストするか**: 同一 geometry/layers/beam/mu_t_calc の 2 インスタンスが `==`。
  - **期待される動作**: frozen dataclass の値比較がネスト tuple/dataclass 込みで成立。
- **入力値**: `CellConfig("capillary", layers=(CellLayer("window","Be",0.5),)) == CellConfig("capillary", layers=(CellLayer("window","Be",0.5),))`
  - **入力データの意味**: tuple 内 dataclass を持つ frozen 値オブジェクトの構造的等価性を代表。
- **期待される結果**: True。
  - **期待結果の理由**: tuple と CellLayer の `==` が再帰的に要素比較するため。
- **テストの目的**: ネストを含む等価比較の成立確認。
  - **確認ポイント**: tuple 要素の CellLayer も値比較されること。
- 🔵 (要件定義 2.3)

### N-06: CellConfig の dataclasses.asdict シリアライズ（ネスト展開）
- **何をテストするか**: `dataclasses.asdict(cell_config)` が JSON 互換型のネスト dict へ再帰展開される。
  - **期待される動作**: layers が tuple[dict]、beam が dict へ展開され、素の dict/tuple/str/float/None のみになる (TC-207-01)。
- **入力値**: `dataclasses.asdict(CellConfig("transmission", layers=(CellLayer("window","Be",0.5),), beam=BeamConfig(wavelength=0.7), mu_t_calc=1.2))`
  - **入力データの意味**: 永続化・エクスポート時の直列化経路を代表。
- **期待される結果**: `{"geometry": "transmission", "layers": ({"role":"window","material":"Be","thickness_mm":0.5,"density":None},), "beam": {"wavelength":0.7,"energy_kev":None,"size_mm":None}, "mu_t_calc": 1.2}`
  - **期待結果の理由**: `dataclasses.asdict` はネスト dataclass を dict へ再帰変換するが、**tuple 型は Python 仕様上保持する** (list へは変換しない。`_asdict_inner` が `type(obj)(...)` で同型を再生成)。よって layers/size_mm は tuple のまま。json モジュールが最終直列化時に tuple を配列化するため round-trip 可能。
- **テストの目的**: シリアライズ可能性の確認 (TC-207-01「生成・シリアライズできる」)。
  - **確認ポイント**: 専用 to_dict/from_dict なしで `asdict` が JSON 互換の素 dict を返すこと。tuple/list を同一視する equality ハックは設けない (== の対称性を守る)。
- 🔵 (要件定義 2.3/3 / TC-207-01。asdict の tuple 保持は CPython 標準ライブラリの確定挙動)

### N-07: ExternalChannel の新 kind（voltage）生成と value_for
- **何をテストするか**: 拡張した kind `"voltage"` で `ExternalChannel` を生成し `value_for` が従来どおり動く。
  - **期待される動作**: kind に electrochemistry 値を渡して生成でき、存在フレーム→値・欠損→None を返す (REQ-007)。
- **入力値**: `ExternalChannel(kind="voltage", sync_map={0: 3.2, 1: 3.5}).value_for(1)` / `.value_for(9)`
  - **入力データの意味**: 充放電電圧のフレーム同期という operando の中核チャネル。
- **期待される結果**: `value_for(1) == 3.5`、`value_for(9) is None`、`.kind == "voltage"`。
  - **期待結果の理由**: `ExternalChannel` 本体・`value_for` は無改変 (`sync_map.get`)。kind Literal 拡張のみで新 kind が合法値。
- **テストの目的**: kind 拡張後も既存の同期挙動が保たれることを確認。
  - **確認ポイント**: 新 kind でも `value_for` の縮退挙動 (欠損→None) が不変。
- 🔵 (要件定義 2.4 / REQ-007 / channel.py value_for)

### N-08: RefinementMetrics.multistart の明示付与生成
- **何をテストするか**: `RefinementMetrics(..., multistart={"n":8,"n_basins":1,"n_diverged":0})` が生成でき値を保持する。
  - **期待される動作**: 末尾追加フィールドに Mapping を渡して生成でき、保持される。
- **入力値**: `RefinementMetrics(rwp=1.0, gof=1.1, chi2=1.2, n_obs=100, n_params=5, multistart={"n":8,"n_basins":1,"n_diverged":0})`
  - **入力データの意味**: マルチスタート精密化 (N=8・単一 basin・発散なし) の記録を代表 (REQ-006 / TC-201-06)。
- **期待される結果**: `.multistart == {"n":8,"n_basins":1,"n_diverged":0}`。既存フィールド (`.rwp==1.0` 等) も保持。
  - **期待結果の理由**: interfaces.py L84-87 の追加フィールド定義に一致。
- **テストの目的**: multistart メタ情報の記録を確認。
  - **確認ポイント**: 既存フィールドの既定・保持が崩れないこと。
- 🔵 (要件定義 2.5 / REQ-006 / TC-201-06 / interfaces.py L84-87)

### N-09: XraylibMuCalculator が MuCalculator Protocol を構造的に満たす
- **何をテストするか**: `XraylibMuCalculator` インスタンスが `mu_t(config)` メソッドを持ち、`MuCalculator` の構造的契約を満たす。
  - **期待される動作**: `hasattr(x, "mu_t")` かつ `callable(x.mu_t)`。静的境界として MuCalculator に代入可能。
- **入力値**: `x = XraylibMuCalculator()` → `hasattr(x, "mu_t")` / `calc: MuCalculator = x`
  - **入力データの意味**: μt 計算の交換境界 (Protocol) が確立していることを代表 (REQ-019)。
- **期待される結果**: `hasattr(x, "mu_t") is True`、`callable(x.mu_t) is True`。MuCalculator への代入が型エラーにならない。
  - **期待結果の理由**: interfaces.py L69-76 の Protocol + スタブ定義。構造的部分型 (duck typing) を満たす。
- **テストの目的**: Protocol 境界の確立を確認 (実装は未提供だがシグネチャは存在)。
  - **確認ポイント**: `mu_t` の呼び出し可能性 (実行結果は E-04 で検証)。`@runtime_checkable` を課さない場合は `isinstance` ではなく `hasattr`/呼出可能性で確認。
- 🟡 (要件定義 2.6 / REQ-019 / interfaces.py L69-76。構造的適合の検証手段は妥当な推測)

### N-10: model パッケージからの re-export と __all__ 収載
- **何をテストするか**: `from tsumugin.model import CellLayer, BeamConfig, CellConfig, MuCalculator, XraylibMuCalculator` が解決し、各名が `tsumugin.model.__all__` に含まれる。
  - **期待される動作**: `model/__init__.py` で import + `__all__` 追加済み。
- **入力値**: `import tsumugin.model as m` → `m.CellLayer`, `m.BeamConfig`, `m.CellConfig`, `m.MuCalculator`, `m.XraylibMuCalculator` と各名の `in m.__all__`
  - **入力データの意味**: 後続タスク (TASK-0026/0027/0029) が公開 API 経由で参照する経路を代表。
- **期待される結果**: 5 シンボルすべて解決可能かつ `__all__` に収載。
  - **期待結果の理由**: 要件定義 2.7 の re-export スコープ。
- **テストの目的**: 公開面の整備を確認。
  - **確認ポイント**: top-level `tsumugin.__init__` 昇格は本タスク必須スコープ外 (テストしない)。
- 🔵 (要件定義 2.7 / __init__.py)

---

## 2. 異常系テストケース（エラーハンドリング）

### E-01: CellLayer の frozen 再代入禁止
- **エラーケースの概要**: frozen dataclass のフィールドへ再代入を試みる。
  - **エラー処理の重要性**: 不変値オブジェクト (P2) の不変性保証。
- **入力値**: `cl = CellLayer("window","Be",0.5); cl.thickness_mm = 0.6`
  - **不正な理由**: frozen=True では属性再代入が禁止。
  - **実際の発生シナリオ**: セル層設定を後から書き換える誤用の防御。
- **期待される結果**: `dataclasses.FrozenInstanceError` (`with pytest.raises(dataclasses.FrozenInstanceError):`)。
  - **システムの安全性**: 変更は必ず新インスタンス生成経由に強制される。
- **テストの目的**: frozen 制約の確認。
  - **品質保証の観点**: 不変性違反の混入を CI で検出。
- 🔵 (要件定義 3 frozen 制約 / test_model.py の frozen 検証パターン)

### E-02: BeamConfig の frozen 再代入禁止
- **エラーケースの概要**: `BeamConfig` のフィールドへ再代入を試みる。
  - **エラー処理の重要性**: 新設値オブジェクトの不変性保証。
- **入力値**: `bc = BeamConfig(wavelength=0.7); bc.wavelength = 0.8`
  - **不正な理由**: frozen=True のため再代入不可。
  - **実際の発生シナリオ**: ビーム条件を後から書き換える誤用の防御。
- **期待される結果**: `dataclasses.FrozenInstanceError`。
  - **システムの安全性**: ビーム条件の一貫性を破壊しない。
- **テストの目的**: frozen 制約の確認。
  - **品質保証の観点**: 不変性の担保。
- 🔵 (要件定義 3 frozen 制約)

### E-03: CellConfig の frozen 再代入禁止
- **エラーケースの概要**: `CellConfig` のフィールドへ再代入を試みる。
  - **エラー処理の重要性**: セル構成値オブジェクトの不変性保証。
- **入力値**: `cc = CellConfig("transmission"); cc.mu_t_calc = 1.5`
  - **不正な理由**: frozen=True のため再代入不可。
  - **実際の発生シナリオ**: μt を後から直接代入する誤用の防御 (更新は新インスタンス生成へ強制)。
- **期待される結果**: `dataclasses.FrozenInstanceError`。
  - **システムの安全性**: 吸収補正入力の一貫性を破壊しない。
- **テストの目的**: frozen 制約の確認。
  - **品質保証の観点**: 不変性の担保。
- 🔵 (要件定義 3 frozen 制約)

### E-04: XraylibMuCalculator.mu_t が NotImplementedError
- **エラーケースの概要**: M3 未実装のスタブ `XraylibMuCalculator.mu_t` を呼び出す。
  - **エラー処理の重要性**: REQ-019 — 組成→μt 計算は M3 では Protocol のみで実体を持たず、誤呼び出しを明示エラーで拒否する。
- **入力値**: `XraylibMuCalculator().mu_t(CellConfig(geometry="transmission"))`
  - **不正な理由**: M3 では xraylib 連携が未実装 (REQ-403 コア依存 numpy のみ維持)。
  - **実際の発生シナリオ**: xraylib 未導入で μt 自動計算を呼び出したケース。
- **期待される結果**: `NotImplementedError` を送出 (`with pytest.raises(NotImplementedError):`)。
  - **エラーメッセージの内容**: xraylib 未実装である旨を示す (M3 スコープ外)。
  - **システムの安全性**: 沈黙した誤値でなく明示エラーで停止 (fail-loud)。
- **テストの目的**: 未実装スタブが確実に例外化することを確認 (TC-207-07)。
  - **品質保証の観点**: 未実装機能の誤用を CI で検出。
- 🔵 (要件定義 2.6/4.4 / REQ-019 / TC-207-07 / interfaces.py L75-76)

---

## 3. 境界値テストケース（最小値、最大値、null等）

### B-01: BeamConfig の全既定値生成
- **境界値の意味**: 引数なし生成 `BeamConfig()` が既定 (None/None/None) で成立する縮退ケース。
  - **境界値での動作保証**: すべて既定値でも frozen 値オブジェクトとして生成可能。
- **入力値**: `BeamConfig()`
  - **境界値選択の根拠**: 全フィールド既定値付き (非破壊追加の前提) を検証。
  - **実際の使用場面**: ビーム条件未指定のセル構成。
- **期待される結果**: `.wavelength is None`、`.energy_kev is None`、`.size_mm is None`。
  - **境界での正確性**: 既定値が interfaces.py の定義どおり。
  - **一貫した動作**: 明示生成 (N-03) と同一クラスで挙動一貫。
- **テストの目的**: 既定値縮退の確認。
  - **堅牢性の確認**: 引数省略でも安全に生成。
- 🔵 (要件定義 2.2/4.3 / interfaces.py L54-56)

### B-02: CellConfig の最小生成（geometry のみ）
- **境界値の意味**: 位置必須 `geometry` のみ指定した最小生成が既定 (layers=()/beam=None/mu_t_calc=None) で成立する境界。
  - **境界値での動作保証**: 追加フィールドが既定値のため最小構成で生成できる。
- **入力値**: `CellConfig(geometry="capillary")`
  - **境界値選択の根拠**: 毛細管セル (層構成なし) という最小の器を検証。
  - **実際の使用場面**: 層情報・ビーム条件・μt を持たない単純セル。
- **期待される結果**: 生成成功かつ `.layers == ()`、`.beam is None`、`.mu_t_calc is None`、`.geometry == "capillary"`。
  - **境界での正確性**: 既定値が interfaces.py の定義どおり。
  - **一貫した動作**: 明示生成 (N-04) と挙動一貫。
- **テストの目的**: 既定値縮退の確認。
  - **堅牢性の確認**: 最小指定でも安全に生成。
- 🔵 (要件定義 2.3/4.3 / interfaces.py L63-66)

### B-03: CellLayer の density 既定 None
- **境界値の意味**: 任意フィールド `density` を省略した生成で既定 None に縮退する境界。
  - **境界値での動作保証**: 必須 3 フィールドのみで生成でき density は None。
- **入力値**: `CellLayer(role="electrode", material="LiFePO4", thickness_mm=0.1)`
  - **境界値選択の根拠**: 密度未指定 (計算しない/未知) の代表ケース。
  - **実際の使用場面**: 密度情報を持たない電極層の登録。
- **期待される結果**: 生成成功かつ `.density is None`。他フィールドは指定どおり。
  - **境界での正確性**: 既定 None が interfaces.py L47 どおり。
  - **一貫した動作**: 明示 density 付き (N-01) と同一クラスで挙動一貫。
- **テストの目的**: 任意フィールドの既定縮退を確認。
  - **堅牢性の確認**: density 省略でクラッシュしない。
- 🔵 (要件定義 2.1/4.3 / interfaces.py L47)

### B-04: 既存 kind（temperature）の ExternalChannel 後方互換 smoke
- **境界値の意味**: kind Literal 拡張後も既存 kind の生成が無改変で通る後方互換境界。
  - **境界値での動作保証**: Literal への末尾値追加が既存値の型・意味を狭めない。
- **入力値**: `ExternalChannel(kind="temperature", sync_map={0: 300.0}).value_for(0)`
  - **境界値選択の根拠**: REQ-404 の非破壊性を既存 kind で検証 (既存テスト同型の呼び出し)。
  - **実際の使用場面**: M2 の高温モードが従来どおり temperature チャネルを構築する経路。
- **期待される結果**: 生成成功かつ `value_for(0) == 300.0`、`.kind == "temperature"`。
  - **境界での正確性**: 既存 kind の合法性・value_for 挙動が不変。
  - **一貫した動作**: 既存 `tests/test_model_m2.py` の ExternalChannel テストと同じ生成が通る。
- **テストの目的**: 後方互換 (kind 拡張の非破壊性) の確認。
  - **堅牢性の確認**: 既存 kind の破壊がないこと。
- 🔵 (要件定義 2.4/4.3 / REQ-404 / channel.py)

### B-05: RefinementMetrics の最小生成で multistart 既定 None（後方互換 smoke）
- **境界値の意味**: 既存キーワード生成が multistart 追加後も無改変で通る後方互換境界。
  - **境界値での動作保証**: 追加フィールドが末尾・既定 None のため既存呼び出しを壊さない。
- **入力値**: `RefinementMetrics(rwp=1.0, gof=1.1, chi2=1.2, n_obs=100, n_params=5)`
  - **境界値選択の根拠**: REQ-404 の非破壊性を最小構成で検証 (既存 RefinementMetrics 生成と同型)。
  - **実際の使用場面**: マルチスタート非適用 (単発精密化) の既存経路。
- **期待される結果**: 生成成功かつ `.multistart is None`。`.evidence == {}` 等の既存既定を維持。
  - **境界での正確性**: 既存の既定値が変わっていない。
  - **一貫した動作**: 既存生成と挙動一貫。
- **テストの目的**: 後方互換 (非破壊追加) の確認。
  - **堅牢性の確認**: 既存 API 破壊がないこと。
- 🔵 (要件定義 2.5/4.3 / REQ-404 / hypothesis.py L14-22)

### B-06: 空 layers の CellConfig を asdict でシリアライズ
- **境界値の意味**: `layers=()` (空 tuple) という最小データ境界のシリアライズ。
  - **境界値での動作保証**: 空 tuple でも例外なく空 tuple へ展開される。
- **入力値**: `dataclasses.asdict(CellConfig(geometry="capillary"))`
  - **境界値選択の根拠**: 層なしセル (最小構成) のシリアライズ境界を検証。
  - **実際の使用場面**: 毛細管セルなど層情報を持たない構成の永続化。
- **期待される結果**: `{"geometry": "capillary", "layers": (), "beam": None, "mu_t_calc": None}`。
  - **境界での正確性**: 空 tuple → 空 tuple (Python 仕様: asdict は tuple 型を保持)、None フィールドはそのまま None。
  - **一貫した動作**: 非空 layers (N-06) と同じ展開規則で一貫。
- **テストの目的**: 空 layers 境界での安全なシリアライズを確認。
  - **堅牢性の確認**: 空入力でクラッシュしない・JSON 互換型のみ。
- 🔵 (要件定義 4.3 / TC-207-01。asdict の tuple 保持は CPython 標準ライブラリの確定挙動)

### B-07: 拡張した 4 kind すべてで ExternalChannel が生成可能
- **境界値の意味**: 追加した全 Literal 値 (voltage/current/capacity/composition) を網羅する境界。
  - **境界値での動作保証**: どの新 kind でも生成でき合法値として扱われる。
- **入力値**: `[ExternalChannel(kind=k, sync_map={0: 1.0}) for k in ("voltage","current","capacity","composition")]`
  - **境界値選択の根拠**: kind Literal 拡張の全端点 (4 値) を明示的に網羅 (漏れ検出)。
  - **実際の使用場面**: echem CSV マッパ (TASK-0029) が V/I/Q/x を各 kind で同期する経路。
- **期待される結果**: 4 インスタンスすべて生成成功、各 `.kind` が渡した値と一致、`value_for(0) == 1.0`。
  - **境界での正確性**: 4 新 kind すべてが Literal に含まれ生成可能。
  - **一貫した動作**: 既存 kind (B-04) と同じ生成・同期挙動。
- **テストの目的**: kind 拡張の網羅性を確認 (REQ-007 の 4 種)。
  - **堅牢性の確認**: 追加した全値が漏れなく利用可能。
- 🔵 (要件定義 2.4 / REQ-007 / interfaces.py L83-84)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout + hatchling)。本タスクは model 拡張のため既存言語に一致。
  - **テストに適した機能**: `@dataclass(frozen=True)` の `FrozenInstanceError`、`dataclasses.asdict`、`typing.Protocol` / `Literal`、型注釈。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済み。既存 `tests/test_model.py` / `test_model_m2.py` が pytest 準拠。
  - **テスト実行環境**: `uv run pytest tests/test_model_m3.py` (単体) / `uv run pytest` (全体回帰)。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- 🔵 (note.md §5 テスト関連情報 / pyproject.toml)

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下の形式で日本語コメントを付す (既存 M1/M2 テスト test_model.py / test_model_m2.py の慣習に準拠)。

```python
# 【テスト目的】: XraylibMuCalculator.mu_t が M3 未実装として NotImplementedError を出すことを確認 (TC-207-07)
# 【テスト内容】: スタブの mu_t を CellConfig 付きで呼び出す
# 【期待される動作】: NotImplementedError を送出する (沈黙した誤値を返さない)
# 🔵 信頼性: REQ-019 / TC-207-07 に依拠
def test_xraylib_mu_calculator_raises_not_implemented():
    # 【テストデータ準備】: 最小 CellConfig を用意 (geometry のみ)
    # 【初期条件設定】: M3 では xraylib 連携が未実装である状況を再現
    config = CellConfig(geometry="transmission")

    # 【実際の処理実行】: 未実装スタブの mu_t を呼び出す
    # 【処理内容】: XraylibMuCalculator().mu_t(config)
    # 【結果検証】: NotImplementedError が送出されること
    with pytest.raises(NotImplementedError):  # 【確認内容】: 未実装機能は明示エラーで拒否
        XraylibMuCalculator().mu_t(config)
```

シリアライズ検証の標準形:

```python
import dataclasses

def test_cell_config_asdict_serializes_nested():
    # 【テストデータ準備】: 層・ビーム・μt を持つ透過セルを用意
    cfg = CellConfig(
        geometry="transmission",
        layers=(CellLayer("window", "Be", 0.5),),
        beam=BeamConfig(wavelength=0.7),
        mu_t_calc=1.2,
    )
    # 【実際の処理実行】: dataclasses.asdict で素の dict へ再帰展開
    d = dataclasses.asdict(cfg)
    # 【結果検証】: ネスト dataclass は dict へ展開されるが tuple は Python 仕様上 tuple のまま保持される
    assert d["layers"] == (
        {"role": "window", "material": "Be", "thickness_mm": 0.5, "density": None},
    )  # 【確認内容】: layers が tuple[dict] へ展開 (asdict は tuple 型を保持)
    assert d["beam"] == {"wavelength": 0.7, "energy_kev": None, "size_mm": None}
```

frozen 検証の標準形:

```python
import dataclasses
import pytest

def test_cell_layer_is_frozen():
    cl = CellLayer("window", "Be", 0.5)
    with pytest.raises(dataclasses.FrozenInstanceError):
        cl.thickness_mm = 0.6  # 【確認内容】: frozen のため再代入不可
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (CellLayer/BeamConfig/CellConfig 新設 / channel kind 拡張 / metrics.multistart / MuCalculator Protocol の非破壊追加)
- **参照した入力・出力仕様**: 要件定義 §2.1〜2.7 (各フィールド・value_for・NotImplementedError・re-export)
- **参照した制約条件**: 要件定義 §3 (後方互換 / frozen / 未実装エラー / シリアライズ / ハッシュ非対象 / 決定論 / コア依存 numpy のみ)
- **参照した使用例**: 要件定義 §4 (基本パターン・データフロー・既定値縮退・後方互換 smoke・frozen 再代入・未実装エラー)
- **参照した受け入れ基準**:
  - TC-201-06 (metrics.multistart {n, n_basins} が仮説に記録される) → N-08 / B-05
  - TC-207-01 (CellConfig (transmission/layers/beam) が生成・シリアライズできる) → N-01〜N-06 / E-01〜E-03 / B-01〜B-03 / B-06
  - TC-207-07 (MuCalculator Protocol 未実装が NotImplementedError) → E-04 / N-09
- **参照した完了条件**: TASK-0025 完了条件① frozen 生成/シリアライズ → N-01〜N-06・E-01〜E-03・B-01〜B-03・B-06、② channel kind 後方互換 → N-07・B-04・B-07、③ metrics.multistart 既定 None 非破壊 → N-08・B-05、④ XraylibMuCalculator NotImplementedError → E-04・N-09
- **回帰ゲート (テスト外)**: `uv run pytest` 全体で既存テストを無改変で維持する。既存テストファイル (`tests/test_model.py` / `test_model_m2.py` 等) は 1 行も変更しない。

---

## 品質判定結果

- **テストケース分類**: 正常系 10 / 異常系 4 / 境界値 7 を網羅 ✅
- **期待値定義**: 各ケースに具体的期待値を明記 ✅
- **技術選択**: Python 3.12 + pytest で確定 ✅
- **実装可能性**: 純データモデル + Protocol のため現行スタックで確実に実現可能 ✅
- **信頼性レベル**: 🔵 17 / 🟡 4 / 🔴 0 — **✅ 高品質**
