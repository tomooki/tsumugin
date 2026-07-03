# TASK-0012 store/serialization TDDテストケース定義書

**機能名**: store/serialization — PhaseInstance の dict 相互変換 (`phase_to_dict` / `phase_from_dict`)
**タスクID**: TASK-0012 / **要件名**: m2-sequential
**作成日**: 2026-07-03
**要件定義**: `docs/implements/m2-sequential/TASK-0012/serialization-requirements.md`
**出力ファイル**: `docs/implements/m2-sequential/TASK-0012/serialization-testcases.md`
**テスト対象実装**: `src/tsumugin/store/serialization.py` (新規)
**テストファイル**: `tests/test_serialization.py` (新規)

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義・既存実装・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: 元の資料から妥当な推測
- 🔴 **赤信号**: 元の資料にない推測

---

## テストケース一覧サマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 | 6 | N-01〜N-06 |
| 異常系 (非有限 → None) | 3 | E-01〜E-03 |
| 境界値 | 6 | B-01〜B-06 |
| **合計** | **15** | |

**信頼性分布**: 🔵 9 / 🟡 6 / 🔴 0 — 品質評価: 高品質

**完了条件との対応**:
- 完了条件① 全フィールド roundtrip 等価 → **N-01**
- 完了条件② lifecycle=None / sigma 空 / occupancies 空の縮退 roundtrip → **B-01**
- 完了条件③ `json.dumps(allow_nan=False)` 可能 (非有限 → None) → **N-03 / E-01 / E-02 / E-03**
- 完了条件④ 未知キー無視で前方互換 → **B-03**

---

## 1. 正常系テストケース（基本的な動作）

### N-01: 全フィールド入り PhaseInstance の完全 roundtrip 等価
- **何をテストするか**: phase_ref / lattice(sigma 付き) / scale / wt_frac / occupancies / lifecycle をすべて持つ相が `phase_from_dict(phase_to_dict(p)) == p`。
- **期待される動作**: dict を経由しても frozen dataclass の構造的 `==` で完全一致する。
- **入力値**:
  ```python
  p = PhaseInstance(
      "A",
      LatticeParams(5.01, 5.02, 5.03, 91.0, 92.0, 93.0, sigma={"a": 0.002, "c": 0.003}),
      scale=1.25, wt_frac=0.35, occupancies={"Fe": 0.98, "O": 1.0},
      lifecycle=PhaseLifecycle(birth_frame=10, death_frame=18, confidence=0.87),
  )
  ```
  - **入力データの意味**: 逐次精密化で全属性が確定した代表的な「フルスペック相」。永続化の主対象。
- **期待される結果**: `phase_from_dict(phase_to_dict(p)) == p` が True。
  - **期待結果の理由**: 完了条件① (`==` 比較)。全フィールドが lossless に往復する契約 (要件定義 2.1/2.2, interfaces.py L261-262)。
- **テストの目的**: 完全 roundtrip の保証 (機能の中核)。
  - **確認ポイント**: sigma / occupancies (Mapping)、lifecycle (ネスト dataclass)、angles すべてが保存されること。
- 🔵 (要件定義 §3 完了条件① / interfaces.py L261-262)

### N-02: phase_to_dict の出力 dict 構造・キー・ネスト
- **何をテストするか**: `phase_to_dict` の返り値が期待するキー集合とネスト構造 (lattice / lifecycle) を持つ。
- **期待される動作**: top-level に `phase_ref/lattice/scale/wt_frac/occupancies/lifecycle`、lattice に `a/b/c/alpha/beta/gamma/sigma`、lifecycle に `birth_frame/death_frame/confidence`。
- **入力値**: `phase_to_dict(PhaseInstance("A", LatticeParams(5,5,5), lifecycle=PhaseLifecycle(birth_frame=3)))`
  - **入力データの意味**: 後続 TASK-0014 が依存する dict スキーマを固定するための代表入力。
- **期待される結果**: `d["phase_ref"]=="A"`、`set(d["lattice"]) == {"a","b","c","alpha","beta","gamma","sigma"}`、`d["lattice"]["a"]==5.0`、`d["lattice"]["alpha"]==90.0`、`d["lifecycle"]["birth_frame"]==3`、`d["occupancies"]=={}`、`d["wt_frac"] is None`。
  - **期待結果の理由**: 要件定義 2.1 の dict スキーマ確定。TASK-0014 がキー名/ネストに直接依存するため固定が必要。
- **テストの目的**: dict スキーマ (キー名・ネスト) の凍結。
  - **確認ポイント**: lattice/lifecycle がフラットでなくネスト dict であること。
- 🟡 (要件定義 2.1 の dict スキーマは 🟡 JSON 可換から具体化)

### N-03: 全有限フル相の dict が json.dumps(allow_nan=False) 可能
- **何をテストするか**: 有限値のみの相の `phase_to_dict` 出力が `json.dumps(d, allow_nan=False)` で例外なく直列化できる。
- **期待される動作**: 出力が JSON ネイティブ型のみで構成され、inf/NaN を含まない。
- **入力値**: `json.dumps(phase_to_dict(N-01 相), allow_nan=False)`
  - **入力データの意味**: 永続化 (JSONL) の前提となる JSON 純度を、正常データで確認。
- **期待される結果**: 例外を送出せず文字列を返す。往復として `json.loads` → `phase_from_dict` が N-01 相と `==`。
  - **期待結果の理由**: 完了条件③ の前提 (allow_nan=False が inf/NaN で `ValueError` を出す性質を利用)。素の型のみ (tuple/dataclass を残さない) の担保。
- **テストの目的**: 出力の JSON ネイティブ純度の確認。
  - **確認ポイント**: `occupancies`/`sigma` が素の dict であること (tuple や dataclass が混ざらない)。
- 🔵 (要件定義 §3 JSON 安全性 / TC-104-03)

### N-04: lifecycle (birth/death/confidence) の roundtrip 保持
- **何をテストするか**: `PhaseLifecycle` を持つ相の lifecycle が dict 往復で完全一致する。
- **期待される動作**: ネストされた lifecycle が `PhaseLifecycle` として復元される。
- **入力値**: `p = PhaseInstance("A", LatticeParams(5,5,5), lifecycle=PhaseLifecycle(birth_frame=7, death_frame=None, confidence=0.5))`
  - **入力データの意味**: FR-305 相ライフサイクルの永続化 (birth のみ確定・death 未確定という実状況)。
- **期待される結果**: `phase_from_dict(phase_to_dict(p)).lifecycle == PhaseLifecycle(birth_frame=7, death_frame=None, confidence=0.5)`。
  - **期待結果の理由**: 要件定義 2.2 (lifecycle ネスト復元)。death_frame の None も保存される。
- **テストの目的**: ネスト dataclass (lifecycle) 復元の確認。
  - **確認ポイント**: `phase_from_dict` が dict の lifecycle を `PhaseLifecycle` インスタンスへ戻すこと (dict のままにしない)。
- 🔵 (要件定義 2.1/2.2 / phase.py PhaseLifecycle)

### N-05: sigma / occupancies (非空 Mapping) の roundtrip 保持
- **何をテストするか**: `LatticeParams.sigma` と `PhaseInstance.occupancies` の非空 Mapping が dict 往復で保存される。
- **期待される動作**: Mapping フィールドが素の dict にコピーされ、復元時に等価な dict として戻る。
- **入力値**: `p = PhaseInstance("A", LatticeParams(5,5,5, sigma={"a": 0.01, "b": 0.02}), occupancies={"Na": 0.9})`
  - **入力データの意味**: ±σ・占有率という定量情報を持つ相の永続化 (NFR-107 σ 由来明示の素材)。
- **期待される結果**: `q = phase_from_dict(phase_to_dict(p))` に対し `q.lattice.sigma == {"a": 0.01, "b": 0.02}`、`q.occupancies == {"Na": 0.9}`、`q == p`。
  - **期待結果の理由**: 要件定義 2.1 (Mapping を dict(mapping) でコピー)。dict の `==` が要素比較する。
- **テストの目的**: Mapping フィールドの lossless 往復を確認。
  - **確認ポイント**: キー型が str、値が float で保存されること。
- 🔵 (要件定義 2.1 / phase.py sigma/occupancies)

### N-06: 決定論 — phase_to_dict 2 回の等価 dict + canonical JSON 一致
- **何をテストするか**: 同一相に `phase_to_dict` を 2 回適用した dict が等価で、`_canonical_json` に通した文字列が一致する。
- **期待される動作**: 純関数・辞書順非依存 (sort_keys) により決定論的。
- **入力値**: `p = N-01 相` → `d1 = phase_to_dict(p)`、`d2 = phase_to_dict(p)`、`_canonical_json(d1)`, `_canonical_json(d2)`
  - **入力データの意味**: NFR-102 / REQ-402 ビット同一・ハッシュチェーン (TASK-0014) の前提を確認。
- **期待される結果**: `d1 == d2` が True。`_canonical_json(d1) == _canonical_json(d2)` が True。
  - **期待結果の理由**: 要件定義 §3 決定論。`ledger.py::_canonical_json(sort_keys=True)` に素の dict を渡せる契約 (D-Q5)。
- **テストの目的**: 決定論と `_canonical_json` 互換性の確認。
  - **確認ポイント**: `phase_to_dict` 出力が `_canonical_json` (私的関数 import) で例外なく直列化できること = 素の型のみである証跡。
- 🟡 (要件定義 §3 / D-Q5。`_canonical_json` を私的 import する点が 🟡)

---

## 2. 異常系テストケース（非有限 → None、M1 レビュー教訓）

### E-01: 非有限 scale (inf) → dict で None、json.dumps(allow_nan=False) 成功
- **エラーケースの概要**: 精密化失敗などで `scale=inf` を持つ相を直列化する。
- **エラー処理の重要性**: JSON には inf が存在しない。非有限が漏れると永続化 (json.dumps) が `ValueError` で失敗する (M1 レビュー教訓)。
- **入力値**: `phase_to_dict(PhaseInstance("A", LatticeParams(5,5,5), scale=math.inf))`
  - **不正な理由**: `scale=inf` は物理的に無意味な発散状態で JSON 化不能。
  - **実際の発生シナリオ**: バックエンド境界で精密化失敗を chi2=inf の結果へ変換する経路の副産物。
- **期待される結果**: `d["scale"] is None`。`json.dumps(d, allow_nan=False)` が例外を出さず成功する。
  - **エラーメッセージの内容**: 例外ではなく None へ縮退 (P5 縮退規約)。上位は None を欠損として扱う。
  - **システムの安全性**: 非有限で永続化全体を止めない。
- **テストの目的**: 非有限 scale の None 化と JSON 安全性を確認 (完了条件③ の中核)。
  - **品質保証の観点**: M1 で顕在化した「inf が JSON 層へ漏れる」欠陥の再発防止。
- 🔵 (要件定義 §3 JSON 安全性 / search/tree.py `_finite_or_none` / M1 教訓)

### E-02: 非有限 lattice / sigma 値 (NaN・inf) → None、json.dumps 成功
- **エラーケースの概要**: `lattice.a=nan` および `sigma` の値に `inf` を持つ相を直列化する。
- **エラー処理の重要性**: lattice・sigma の非有限も JSON へ漏らさない (ネスト dict 内も純化対象)。
- **入力値**: `phase_to_dict(PhaseInstance("A", LatticeParams(math.nan, 5, 5, sigma={"a": math.inf})))`
  - **不正な理由**: `a=nan` / `sigma["a"]=inf` は数値解として無効で JSON 化不能。
  - **実際の発生シナリオ**: 発散した格子精密化・σ 推定不能フレーム。
- **期待される結果**: `d["lattice"]["a"] is None`、`d["lattice"]["sigma"]["a"] is None`。`json.dumps(d, allow_nan=False)` 成功。
  - **エラーメッセージの内容**: ネスト・Mapping 内でも None へ縮退。
  - **システムの安全性**: ネスト構造の隅々まで非有限を漏らさない。
- **テストの目的**: ネスト dict / Mapping 内の非有限純化を確認。
  - **品質保証の観点**: トップレベルだけでなく lattice/sigma まで純化が及ぶこと。
- 🔵 (要件定義 4.3 EDGE / TC-104-03)

### E-03: 非有限 wt_frac / occupancy 値 / confidence → None、json.dumps 成功
- **エラーケースの概要**: `wt_frac=inf`、`occupancies` の値に `nan`、`lifecycle.confidence=nan` を持つ相を直列化する。
- **エラー処理の重要性**: 残る全 float フィールド (wt_frac / occupancy 値 / confidence) も純化対象であることを網羅。
- **入力値**: `phase_to_dict(PhaseInstance("A", LatticeParams(5,5,5), wt_frac=math.inf, occupancies={"Fe": math.nan}, lifecycle=PhaseLifecycle(confidence=math.nan)))`
  - **不正な理由**: いずれも非有限で JSON 化不能。
  - **実際の発生シナリオ**: 相分率発散・占有率推定不能・確信度未算出の縮退。
- **期待される結果**: `d["wt_frac"] is None`、`d["occupancies"]["Fe"] is None`、`d["lifecycle"]["confidence"] is None`。`json.dumps(d, allow_nan=False)` 成功。
  - **エラーメッセージの内容**: 例外なく全 float フィールドが None へ縮退。
  - **システムの安全性**: 純化の網羅性 (どの float フィールドも漏れない)。
- **テストの目的**: 全 float フィールドの非有限純化を網羅確認。
  - **品質保証の観点**: 純化漏れフィールドがないことの保証。
- 🟡 (要件定義 4.3/4.4 からの網羅化。wt_frac の None は既存の None と縮退が一致)

---

## 3. 境界値テストケース（最小値、null、既定値等）

### B-01: 縮退 roundtrip — lifecycle=None / sigma 空 / occupancies 空 (最小相)
- **境界値の意味**: 全 optional が既定 (None / {} / {}) という最小構成の相の roundtrip 等価。
- **境界値での動作保証**: 空 Mapping・None lifecycle でも lossless 往復する。
- **入力値**: `p = PhaseInstance("x", LatticeParams(5, 5, 5))`
  - **境界値選択の根拠**: 完了条件② の縮退ケース。M0/M1 が最も多用する最小相。
  - **実際の使用場面**: sigma/occupancies/lifecycle 未確定の初期相の永続化。
- **期待される結果**: `phase_from_dict(phase_to_dict(p)) == p`。`q.lifecycle is None`、`q.occupancies == {}`、`q.lattice.sigma == {}`、`q.wt_frac is None`。
  - **境界での正確性**: 空 dict / None が既定として正しく往復。
  - **一貫した動作**: フル相 (N-01) と同じ経路で縮退相も通る。
- **テストの目的**: 縮退 roundtrip の保証 (完了条件②)。
  - **堅牢性の確認**: 空・None 入力で破綻しない。
- 🔵 (要件定義 §3 完了条件② / phase.py 既定値)

### B-02: wt_frac=None が None として roundtrip (0.0 と混同しない)
- **境界値の意味**: `None` (未定) と `0.0` (ゼロ相分率) を区別する境界。
- **境界値での動作保証**: None は None のまま往復し、0.0 に落ちない。
- **入力値**: `p_none = PhaseInstance("A", LatticeParams(5,5,5), wt_frac=None)` / `p_zero = PhaseInstance("A", LatticeParams(5,5,5), wt_frac=0.0)`
  - **境界値選択の根拠**: None と 0.0 の意味差 (未定 vs ゼロ) は解析上重要。
  - **実際の使用場面**: 相分率が未計算 (None) か消失 (0.0) かの区別。
- **期待される結果**: `phase_from_dict(phase_to_dict(p_none)).wt_frac is None`、`phase_from_dict(phase_to_dict(p_zero)).wt_frac == 0.0`。両者は `!=`。
  - **境界での正確性**: None と 0.0 が保存され混同されない。
  - **一貫した動作**: 有限 0.0 は純化対象外 (math.isfinite(0.0) is True)。
- **テストの目的**: None と 0.0 の区別保持を確認。
  - **堅牢性の確認**: 純化ロジックが 0.0 を誤って None にしない。
- 🟡 (要件定義 2.2 からの妥当な推測。None/0.0 区別を明示化)

### B-03: 未知キー無視で前方互換 (from_dict)
- **境界値の意味**: 将来スキーマで追加されたキーを含む dict を、旧実装が壊れず読む前方互換境界。
- **境界値での動作保証**: 定義外キーを無視し既知フィールドのみで復元。
- **入力値**:
  ```python
  base = phase_to_dict(PhaseInstance("A", LatticeParams(5,5,5)))
  data = {**base, "future_field": 123, "lattice": {**base["lattice"], "gamma_star": 88.0}}
  phase_from_dict(data)
  ```
  - **境界値選択の根拠**: 完了条件④ の前方互換。スキーマ進化に対する堅牢性。
  - **実際の使用場面**: 新バージョンが書いた JSONL を旧バージョンが読む / 逆。
- **期待される結果**: 例外なし。`phase_from_dict(data) == PhaseInstance("A", LatticeParams(5,5,5))`。
  - **境界での正確性**: `future_field` / `gamma_star` が無視される (`**data` 展開ではなく明示キー取り出し)。
  - **一貫した動作**: 未知キーの有無で復元結果が変わらない。
- **テストの目的**: 未知キー無視の前方互換を確認 (完了条件④)。
  - **堅牢性の確認**: 定義外キーで `TypeError`/`KeyError` を出さない。
- 🟡 (要件定義 2.2/§3 前方互換 / 完了条件④。実装方式は 🟡)

### B-04: 欠損 optional キー補完で後方互換 (from_dict)
- **境界値の意味**: 旧スキーマ由来で optional キーを欠く dict を既定で補完する後方互換境界。
- **境界値での動作保証**: `lifecycle`/`occupancies`/`wt_frac`/`sigma`/`scale`/角 の欠落を既定で埋める。
- **入力値**: `phase_from_dict({"phase_ref": "A", "lattice": {"a": 5.0, "b": 5.0, "c": 5.0}})`
  - **境界値選択の根拠**: 最小限のキーのみを持つ旧スキーマ dict。
  - **実際の使用場面**: `lifecycle` 導入前 (TASK-0011 以前) に書かれた永続データの読み戻し。
- **期待される結果**: `PhaseInstance("A", LatticeParams(5,5,5))` と `==`。`scale==1.0`、`wt_frac is None`、`occupancies=={}`、`lifecycle is None`、`lattice.alpha==90.0`、`lattice.sigma=={}`。
  - **境界での正確性**: 欠損キーが `data.get(key, 既定)` で補完される。
  - **一貫した動作**: 欠損 dict と明示既定 dict が同じ相へ復元。
- **テストの目的**: 欠損 optional キーの既定補完を確認 (後方互換)。
  - **堅牢性の確認**: 必須外キー欠落で `KeyError` を出さない。
- 🟡 (要件定義 2.2 欠損補完 / §4.3。後方互換は 🟡)

### B-05: lattice 既定角 (90.0) の roundtrip 保持
- **境界値の意味**: 角度が省略時の既定 90.0 を持つ相が、往復後も 90.0 のまま保たれる境界。
- **境界値での動作保証**: 既定角が dict へ明示出力され、復元時に 90.0 で戻る。
- **入力値**: `p = PhaseInstance("A", LatticeParams(4.0, 5.0, 6.0))` (角は既定 90.0)
  - **境界値選択の根拠**: 直方晶などで頻出する既定角。to_dict が既定値を明示出力するか検証。
  - **実際の使用場面**: 立方/正方/斜方晶の相 (角固定 90°) の永続化。
- **期待される結果**: `d["lattice"]["alpha"]==90.0` かつ `beta==gamma==90.0`。`phase_from_dict(d) == p`。
  - **境界での正確性**: 既定値も dict に含まれ往復する (既定省略で欠落させない)。
  - **一貫した動作**: 明示角 (N-01: 91/92/93) と既定角で経路が一貫。
- **テストの目的**: 既定角の明示出力と保持を確認。
  - **堅牢性の確認**: 既定値の消失がないこと。
- 🔵 (要件定義 2.1 dict スキーマ / phase.py LatticeParams 既定角)

### B-06: confidence 境界端点 (0.0 / 1.0) の roundtrip 保持
- **境界値の意味**: 確信度レンジ [0,1] の下限 0.0・上限 1.0 (有限端点) が純化されず保持される境界。
- **境界値での動作保証**: 0.0/1.0 は有限のため None 化されず、そのまま往復する。
- **入力値**: `p0 = PhaseInstance("A", LatticeParams(5,5,5), lifecycle=PhaseLifecycle(confidence=0.0))` / `p1 = ...(confidence=1.0)`
  - **境界値選択の根拠**: interfaces.py L37 が confidence を [0,1] と注記。端点で純化が誤発火しないか検証。
  - **実際の使用場面**: LifecycleTracker が算出した確信度 0.0〜1.0 の永続化。
- **期待される結果**: `phase_from_dict(phase_to_dict(p0)).lifecycle.confidence == 0.0`、`...(p1)...confidence == 1.0`。
  - **境界での正確性**: 0.0 が `math.isfinite(0.0) is True` により None 化されない。
  - **一貫した動作**: 端点でもクランプ・丸めをしない (器の直列化のみ)。
- **テストの目的**: 有限端点の非純化・保持を確認。
  - **堅牢性の確認**: 0.0 を偽陽性で None にしないこと (E 系の裏返し検証)。
- 🟡 (要件定義 §4.3 境界値保持 / interfaces.py L37 の [0,1] 注記)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout + hatchling)。本タスクは標準ライブラリ (`json`/`math`/`dataclasses`) のみで完結。
  - **テストに適した機能**: frozen dataclass の構造的 `==`、`json.dumps(allow_nan=False)` の `ValueError`、`math.inf`/`math.nan`。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済み。既存 `tests/test_model.py` が pytest 準拠。
  - **テスト実行環境**: `uv run pytest tests/test_serialization.py` (単体) / `uv run pytest` (全体回帰 = 223 passed / 3 skipped 維持)。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- 🔵 (note.md §5 テスト関連情報 / pyproject.toml)

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下の形式で日本語コメントを付す (既存 M1 テスト test_clustering.py / test_m1_e2e.py の慣習に準拠)。

### roundtrip の標準形

```python
import math
import json
from tsumugin.model import PhaseInstance, LatticeParams, PhaseLifecycle
from tsumugin.store.serialization import phase_to_dict, phase_from_dict

# 【テスト目的】: 全フィールド入り相が dict 往復で完全一致することを確認 (完了条件①)
# 【テスト内容】: フルスペック相を phase_to_dict → phase_from_dict し == 比較
# 【期待される動作】: frozen dataclass の構造的 == で一致
# 🔵 信頼性: 完了条件① / interfaces.py L261-262
def test_full_phase_roundtrip_equal():
    # 【テストデータ準備】: sigma/occupancies/lifecycle を含むフルスペック相を用意
    # 【初期条件設定】: 逐次精密化で全属性が確定した実状況を再現
    p = PhaseInstance(
        "A",
        LatticeParams(5.01, 5.02, 5.03, 91.0, 92.0, 93.0, sigma={"a": 0.002, "c": 0.003}),
        scale=1.25, wt_frac=0.35, occupancies={"Fe": 0.98, "O": 1.0},
        lifecycle=PhaseLifecycle(birth_frame=10, death_frame=18, confidence=0.87),
    )

    # 【実際の処理実行】: dict へ直列化して再構築
    # 【処理内容】: phase_to_dict → phase_from_dict の往復
    restored = phase_from_dict(phase_to_dict(p))

    # 【結果検証】: 復元相が元と等価
    # 【検証項目】: 全フィールド lossless 往復
    # 🔵 信頼性: 完了条件①
    assert restored == p  # 【確認内容】: 構造的 == で完全一致
```

### 非有限純化の標準形

```python
# 【テスト目的】: 非有限 scale が None 化され json.dumps(allow_nan=False) が通ることを確認 (M1 教訓)
# 【テスト内容】: scale=inf の相を phase_to_dict し None + JSON 直列化
# 【期待される動作】: d["scale"] is None、json.dumps 成功
# 🔵 信頼性: 完了条件③ / search/tree.py _finite_or_none
def test_non_finite_scale_becomes_none_and_json_safe():
    # 【テストデータ準備】: 精密化発散で scale=inf となった相を再現
    p = PhaseInstance("A", LatticeParams(5, 5, 5), scale=math.inf)

    # 【実際の処理実行】: dict 化
    d = phase_to_dict(p)

    # 【結果検証】: 非有限が None へ縮退し JSON 安全
    # 🔵 信頼性: 完了条件③
    assert d["scale"] is None            # 【確認内容】: inf → None
    json.dumps(d, allow_nan=False)       # 【確認内容】: 例外を出さず直列化できる
```

### 前方互換の標準形

```python
# 【テスト目的】: 未知キーを無視して復元することを確認 (前方互換, 完了条件④)
# 【テスト内容】: 定義外キー入り dict を phase_from_dict
# 【期待される動作】: 例外なし・既知フィールドのみで復元
# 🟡 信頼性: 完了条件④ (実装方式は妥当な推測)
def test_from_dict_ignores_unknown_keys():
    base = phase_to_dict(PhaseInstance("A", LatticeParams(5, 5, 5)))
    data = {**base, "future_field": 123}

    # 【実際の処理実行】: 未知キー入り dict を復元
    restored = phase_from_dict(data)

    # 【結果検証】: 未知キーは無視され baseline と等価
    # 🟡 信頼性: 完了条件④
    assert restored == PhaseInstance("A", LatticeParams(5, 5, 5))  # 【確認内容】: future_field 無視
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (phase_to_dict / phase_from_dict の完全 roundtrip・永続化基盤・store 最下層)
- **参照した入力・出力仕様**: 要件定義 §2.1 (phase_to_dict の dict スキーマ・非有限純化)、§2.2 (phase_from_dict の未知キー無視・欠損補完・roundtrip)
- **参照した制約条件**: 要件定義 §3 (JSON 安全性 / 完全・縮退 roundtrip / 前方互換 / 非破壊 / 決定論 / レイヤ制約)
- **参照した使用例**: 要件定義 §4 (直列化・復元データフロー / 非有限 EDGE / 縮退 / 未知キー・欠損キー / 境界値保持)
- **参照した受け入れ基準**: TC-104-03 (非有限が漏れない)、TC-106-01〜07 (永続化 roundtrip の土台)
- **参照した完了条件**: ① 全フィールド roundtrip → N-01、② 縮退 roundtrip → B-01、③ json.dumps(allow_nan=False) 可 (非有限 → None) → N-03 / E-01 / E-02 / E-03、④ 未知キー無視 → B-03
- **回帰ゲート (テスト外)**: `uv run pytest` 全体で既存 223 passed / 3 skipped を維持 (新規テストのみ増加)。既存テストファイルは無改変。

---

## 品質判定結果

- **テストケース分類**: 正常系 6 / 異常系 (非有限純化) 3 / 境界値 6 を網羅 ✅
- **期待値定義**: 各ケースに具体的期待値 (`==` / `is None` / json.dumps 成功) を明記 ✅
- **技術選択**: Python 3.12 + pytest で確定 ✅
- **実装可能性**: 標準ライブラリのみで確実に実現可能 ✅
- **信頼性レベル**: 🔵 9 / 🟡 6 / 🔴 0 — **✅ 高品質**
  - 🟡 が 6 件あるのは dict スキーマ詳細・前方/後方互換の実装方式・境界純化が設計文書の 🟡 (JSON 可換) に由来するため。いずれも要件へ遡及可能で曖昧さなし。
