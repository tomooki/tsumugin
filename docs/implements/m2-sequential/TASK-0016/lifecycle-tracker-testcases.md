# TASK-0016 テストケース定義: LifecycleTracker (ヒステリシス付き birth/death)

**機能名**: LifecycleTracker / **要件名**: m2-sequential / **タスクID**: TASK-0016
**テストファイル**: `tests/test_lifecycle.py` (新規) / **実装**: `src/tsumugin/sequential/lifecycle.py` (新規)
**テスト件数**: 正常系 6 / 異常系 3 / 境界値 4 = **計 13**

> パスはプロジェクトルートからの相対パス。信頼性: 🔵 資料準拠 / 🟡 妥当な推測 / 🔴 資料外推測。

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12 🔵
  - **選択理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout)。model/sequential 層も Python。
  - **テストに適した機能**: dataclass の等価比較・`pytest.raises(FrozenInstanceError)` による frozen 検証。
- **テストフレームワーク**: pytest >= 8 (+ pytest-cov) 🔵
  - **選択理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済。既存 24 テストファイルと統一。
  - **テスト実行環境**: `uv run pytest tests/test_lifecycle.py` (本タスク単体) / `uv run pytest` (全体回帰)。
    GSAS-II 非依存のため `gsas` マーカー不要。
- 🔵 信頼性: `pyproject.toml`, `CLAUDE.md`, `docs/dev/context.md` に準拠。

---

## 1. 正常系テストケース

### N-01: birth 確定 (連続 N フレーム出現)
- **何をテストするか**: frame 10 から相 B が連続出現 → `birth_frame == 10`。
- **期待される動作**: 連続 hysteresis(=3) フレーム到達で birth 確定、値は連続の**最初のフレーム** (10)。
- **入力値**: `hysteresis=3`。frame 0..9 は present_refs=() (B 不在)、frame 10,11,12,... で present_refs=("B",)。
  - **入力データの意味**: 明確な連続出現開始点 (frame 10) を持たせ、ヒステリシス確定後の birth_frame を検証。
- **期待される結果**: `finalize()["B"].birth_frame == 10`, `death_frame is None`。
  - **理由**: 連続 3 フレーム (10,11,12) で birth 成立、記録は連続開始フレーム 10 (完了条件① / TC-103-01)。
- **確認ポイント**: birth 確定フレームが「N フレーム目 (12)」でなく「連続開始 (10)」であること。
- 🔵 (完了条件① / TC-103-01 / interfaces.py L118-133)

### N-02: death 確定 (連続 N フレーム不在)
- **何をテストするか**: 相 A が frame 15 から連続不在 → `death_frame == 15`。
- **期待される動作**: birth 済みの A が連続 hysteresis フレーム不在で death 確定、値は**不在連続の最初のフレーム** (15)。
- **入力値**: frame 0..14 で present_refs=("A",)、frame 15,16,17,... で present_refs=() (A 不在)。
  - **入力データの意味**: A は十分長く存在して birth 確定済み、その後 frame 15 から明確に不在化。
- **期待される結果**: `finalize()["A"].death_frame == 15` (birth_frame は 0)。
  - **理由**: 連続 3 フレーム不在 (15,16,17) で death 成立、記録は不在開始 15 (完了条件② / TC-103-02)。
- **確認ポイント**: death_frame が不在連続の**先頭** (15) であること。
- 🔵 (完了条件② / TC-103-02)

### N-03: death 取り消し (窓内再出現) — REQ-201
- **何をテストするか**: death 判定に至る前 (ヒステリシス窓内) に A が再出現 → death 取り消し・連続扱い。
- **期待される動作**: 不在ランが hysteresis 未満のうちに present へ戻ると不在ランをリセット、death_frame は None のまま。
- **入力値**: frame 0..14 present("A")、frame 15,16 不在 ()、frame 17 で再び present("A")、以降 present。
  - **入力データの意味**: 2 フレームだけの不在 (< N=3) の後に再出現 = 点滅的欠落。
- **期待される結果**: `finalize()["A"].death_frame is None` (A は連続存続扱い)。
  - **理由**: 窓内再出現で death 取り消し (完了条件④ / TC-103-04 / REQ-201)。
- **確認ポイント**: 窓 (2 < 3) を満たさない不在で death が立たないこと。
- 🔵 (完了条件④ / TC-103-04 / REQ-201)

### N-04: 全フレーム存在 → confidence=1.0
- **何をテストするか**: 相が全フレーム present → birth=最初の frame / death=None / confidence=1.0。
- **期待される動作**: 一度も不在にならない相は birth が最初のフレーム、death は None、存在フレーム率 1.0。
- **入力値**: frame 0..9 すべて present_refs=("C",)。
  - **入力データの意味**: 常在相 (背景相など) を代表。
- **期待される結果**: `lc = finalize()["C"]; lc.birth_frame == 0 and lc.death_frame is None and lc.confidence == pytest.approx(1.0)`。
  - **理由**: 完了条件⑤ (🟡)。存在フレーム率 = 10/10 = 1.0。
- **確認ポイント**: confidence の分母/分子の定義 (存在フレーム率) を固定し 1.0 を確認。
- 🟡 (完了条件⑤ / confidence 算出式は実装時確定)

### N-05: 複数相の同時追跡
- **何をテストするか**: A (存在→消滅) と B (途中出現) を同一トラッカーで並行追跡し、それぞれ独立に確定。
- **期待される動作**: 相ごとに独立した present/absent ランを保持し、finalize で相数分の `PhaseLifecycle` を返す。
- **入力値**: frame 0..14 present("A")、frame 10..N present に "B" 追加、frame 15.. で A を外す。
  - **入力データの意味**: 相の入れ替わり (operando の相転移) を代表。
- **期待される結果**: `result = finalize(); set(result.keys()) == {"A","B"}`、
  `result["A"].birth_frame == 0`, `result["B"].birth_frame == 10`, `result["A"].death_frame == 15`。
  - **理由**: 相ごとの独立性 (辞書 key = phase_ref)。
- **確認ポイント**: 相間で状態が干渉しないこと・戻り値 key の網羅。
- 🔵 (interfaces.py 契約 `Mapping[str, PhaseLifecycle]` / 複数相はシーケンシャルの基本)

### N-06: LifecycleConfig 既定値・frozen・re-export
- **何をテストするか**: `LifecycleConfig()` の既定値と不変性、`sequential` パッケージからの公開。
- **期待される動作**: `hysteresis == 3`, `presence_wt_frac == 1e-3`。再代入で `FrozenInstanceError`。
  `from tsumugin.sequential import LifecycleConfig, LifecycleTracker` が解決。
- **入力値**: `cfg = LifecycleConfig()`。
- **期待される結果**: `cfg.hysteresis == 3 and cfg.presence_wt_frac == pytest.approx(1e-3)`。
  `with pytest.raises(dataclasses.FrozenInstanceError): cfg.hysteresis = 5`。import が成功し `__all__` に含まれる。
  - **理由**: interfaces.py L119-121 の既定値固定、CLAUDE.md の frozen dataclass 規約、`__init__.py` 公開。
- **確認ポイント**: 既定値のズレ防止・後続 TASK-0019 が import できる公開面。
- 🔵 (interfaces.py L118-121 / CLAUDE.md / `sequential/__init__.py` 様式)

---

## 2. 異常系テストケース

### E-01: 点滅 (1 フレームのみ出現) は birth 非認定 — TC-103-03
- **エラーケースの概要**: 相が 1 フレームだけ (< N=3) present になる偽出現 (精密化ノイズ)。
- **エラー処理の重要性**: ヒステリシスの本来目的 = 点滅抑制。偽 birth を出すと相図が汚れる。
- **入力値**: `hysteresis=3`。frame 5 のみ present("X")、他フレームは不在。
  - **不正な理由**: 連続 1 フレーム < N のため birth 条件を満たさない。
  - **発生シナリオ**: フレーム間ノイズで wt_frac が一瞬だけ閾値を超える。
- **期待される結果**: `finalize().get("X")` は `None`、または `X` が返っても `birth_frame is None`
  (実装の意味論をテストで固定。基本線は「birth 未確定の相はキーに含めない」)。
  - **システムの安全性**: 偽出現を無視し、確定した相のみ返す。
- **品質保証の観点**: ヒステリシスの中核 (完了条件③)。
- 🔵 (完了条件③ / TC-103-03)

### E-02: 空観測 → 空 Mapping (EDGE-001)
- **エラーケースの概要**: `observe()` を一度も呼ばずに `finalize()` を呼ぶ (空フレーム列)。
- **エラー処理の重要性**: M0/M1 の縮退規約 (空入力 → 空出力・例外なし) を踏襲。
- **入力値**: `tracker = LifecycleTracker()` 直後に `finalize()`。
  - **発生シナリオ**: フレーム 0 件のデータセット (EDGE-001)。
- **期待される結果**: `finalize() == {}` (空 Mapping)、例外を送出しない。
  - **システムの安全性**: 上位エンジンが空トラジェクトリを安全に構築できる。
- **品質保証の観点**: 縮退安全性 (EDGE-001)。
- 🟡 (EDGE-001 の踏襲 / 要件定義 4 章)

### E-03: 不在が窓を超える → death 取り消しされず death 確定 (取り消し境界の外)
- **エラーケースの概要**: N-03 の対偶。不在が hysteresis 以上続いた後に再出現しても、その前に death は確定する。
- **エラー処理の重要性**: 「窓内再出現のみ取り消す」意味論の外側を保証し、REQ-201 の過剰適用を防ぐ。
- **入力値**: frame 0..14 present("A")、frame 15,16,17 不在 (= N フレーム)、frame 18 で再出現。
  - **発生シナリオ**: 真に消滅した相が後で別要因で再出現。
- **期待される結果**: `finalize()["A"].death_frame == 15` (窓を満たした時点で death 確定)。
  - **システムの安全性**: 窓を超えた不在は取り消さない = 真の消滅を検出。
- **品質保証の観点**: REQ-201 の適用範囲を上下から挟む (N-03 と対)。
- 🔵 (REQ-201 の境界 / TC-103-02 と整合)

---

## 3. 境界値テストケース

### B-01: ちょうど N フレームで birth 確定 (N-1 では未確定)
- **境界値の意味**: birth 確定条件は「連続フレーム数 >= hysteresis」。N-1 と N の境目が最重要境界。
- **入力値**: `hysteresis=3`。(a) frame 10,11 のみ present("B") で以降不在 → N-1=2 フレーム。
  (b) frame 10,11,12 present("B") → N=3 フレーム。
  - **選択根拠**: 確定閾値の直前 (2) と直後 (3)。
- **期待される結果**: (a) `birth_frame is None` (未確定 → キーなし or None)。(b) `birth_frame == 10`。
  - **境界での正確性**: N-1 で確定してはならず、N で確定する (off-by-one 防止)。
- **堅牢性の確認**: ヒステリシス判定の等号境界。
- 🔵 (完了条件① / TC-103-01/03 の境界)

### B-02: 不在 N-1 フレームで再出現 → death 未確定 (窓内境界)
- **境界値の意味**: death 取り消し窓の境界。不在ランがちょうど hysteresis-1 のとき再出現すれば取り消す。
- **入力値**: frame 0..14 present("A")、frame 15,16 不在 (=N-1=2)、frame 17 present("A")。
  - **選択根拠**: 取り消し可能な最大の不在長 (N-1)。
- **期待される結果**: `finalize()["A"].death_frame is None` (窓内なので取り消し)。
  - **一貫性**: E-03 (不在=N で death 確定) と連続し、N-1 と N の境目を挟む。
- **堅牢性の確認**: death 窓の等号境界 (N-1 は取り消し / N は確定)。
- 🔵 (REQ-201 / TC-103-04 の境界、E-03 と対)

### B-03: 単一フレーム観測 (EDGE-101)
- **境界値の意味**: 最小の非空観測 (フレーム 1 件)。単発解析と等価。
- **入力値**: frame 0 のみ present("A")、以降 observe なしで finalize。`hysteresis=3`。
  - **選択根拠**: 観測列長の下限 (1)。EDGE-101。
- **期待される結果**: hysteresis(3) 未達のため birth 未確定 (`A` はキーなし or `birth_frame is None`)、例外なし。
  - **一貫性**: 空 (E-02) と複数フレームの中間で破綻しない。
- **堅牢性の確認**: 1 フレームでの縮退安全性。
- 🟡 (EDGE-101 / 要件定義 4 章)

### B-04: confidence = 存在フレーム率 (部分存在で 0 < c < 1)
- **境界値の意味**: confidence の算出式検証。全存在 (=1.0, N-04) と対になる部分存在ケース。
- **入力値**: 全 10 フレームのうち相 D が (birth 確定するように) 一定数だけ present、残りは不在。
  例: frame 0..6 present("D") (7/10)、frame 7..9 不在。`hysteresis=3`。
  - **選択根拠**: confidence が 0 でも 1 でもない中間値になる代表ケース。
- **期待される結果**: `finalize()["D"].confidence == pytest.approx(存在フレーム率)`
  (分母の定義 = 総観測フレーム数か birth〜死区間かを実装で確定し、その定義通りの値。例: 7/10=0.7)。
  `0.0 < confidence < 1.0`。
  - **境界での正確性**: 存在フレーム率の分母/分子を固定し、浮動小数は `pytest.approx`。
- **堅牢性の確認**: confidence が [0,1] 範囲に収まり定義通り。
- 🟡 (完了条件⑤の裏 / confidence 算出式は実装時確定、docstring に根拠明記)

---

## 5. テストケース実装時の日本語コメント指針

各テストは Given/When/Then を日本語コメントで明示する (既存 `tests/test_changepoint.py` 準拠):

```python
def test_birth_confirmed_after_hysteresis():
    # 【テスト目的】: frame 10 からの連続出現で birth_frame=10 が確定することを確認 🔵
    # 【テスト内容】: hysteresis=3 で frame 10,11,12 と連続 present にする
    # 【期待される動作】: 連続開始フレーム 10 が birth_frame に記録される
    # 【テストデータ準備】: frame 0..9 を不在、10 以降を present("B") にして明確な出現点を作る
    tracker = LifecycleTracker(config=LifecycleConfig(hysteresis=3))
    # 【実際の処理実行】: フレーム列を昇順に observe し finalize で確定
    for f in range(10):
        tracker.observe(f, ())
    for f in range(10, 15):
        tracker.observe(f, ("B",))
    result = tracker.finalize()
    # 【結果検証】: birth は連続開始 (10)、death は未消滅 (None)
    assert result["B"].birth_frame == 10   # 【検証項目】: birth_frame が連続開始フレーム 🔵
    assert result["B"].death_frame is None  # 【検証項目】: 消滅していない 🔵
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: `lifecycle-tracker-requirements.md` 1 章 (ヒステリシス付き birth/death 追跡)
- **参照した入力・出力仕様**: 同 2 章 (`LifecycleConfig` / `observe` / `finalize` / `PhaseLifecycle`)
- **参照した制約条件**: 同 3 章 (決定論 REQ-402 / モデル非破壊 REQ-404 / 契約固定)
- **参照した使用例**: 同 4 章 (TC-103 系 / EDGE-001 / EDGE-101)
- **受け入れ基準対応**: `docs/spec/m2-sequential/acceptance-criteria.md` L37-42
  - TC-103-01 → N-01, B-01 / TC-103-02 → N-02, E-03 / TC-103-03 → E-01, B-01 /
    TC-103-04 (REQ-201) → N-03, B-02, E-03
- **完了条件対応** (`docs/tasks/m2-sequential/TASK-0016.md`):
  - ① birth (N-01, B-01) / ② death (N-02) / ③ 点滅非認定 (E-01) / ④ death 取り消し (N-03, B-02) /
    ⑤ 全フレーム存在 confidence=1.0 (N-04) + confidence 率 (B-04)

---

## テスト件数内訳サマリー

| 分類 | 件数 | テスト ID |
|---|---|---|
| 正常系 | 6 | N-01, N-02, N-03, N-04, N-05, N-06 |
| 異常系 | 3 | E-01, E-02, E-03 |
| 境界値 | 4 | B-01, B-02, B-03, B-04 |
| **合計** | **13** | |

## 品質判定

✅ **高品質**
- テストケース分類: 正常系・異常系・境界値を網羅 (birth/death/取り消し/点滅/confidence/縮退)
- 期待値定義: 各ケースで具体値・比較演算子・pytest.approx を明記
- 技術選択: Python 3.12 + pytest 確定 (既存構成と統一)
- 実装可能性: 標準ライブラリのみ、依存 TASK-0011 (`PhaseLifecycle`) 実装済で確実
- 信頼性レベル: 🔵 9 / 🟡 4 (🟡 は confidence 算出式・縮退規約で実装時に定義確定する項目)
