# TASK-0011 model 拡張 TDDテストケース定義書

**機能名**: model 拡張 (PhaseLifecycle / ExternalChannel / frame_range)
**タスクID**: TASK-0011 / **要件名**: m2-sequential
**作成日**: 2026-07-03
**要件定義**: `docs/implements/m2-sequential/TASK-0011/model-extension-requirements.md`
**出力ファイル**: `docs/implements/m2-sequential/TASK-0011/model-extension-testcases.md`
**テスト対象実装**: `src/tsumugin/model/{phase,hypothesis,channel,__init__}.py`
**テストファイル**: `tests/test_model_m2.py` (新規。既存 `tests/test_model.py` は無改変)

**【信頼性レベル凡例】**:
- 🔵 **青信号**: 要件定義・既存実装・設計文書を参考にしてほぼ推測していない
- 🟡 **黄信号**: 元の資料から妥当な推測
- 🔴 **赤信号**: 元の資料にない推測

---

## テストケース一覧サマリー

| 分類 | 件数 | テストID |
|---|---|---|
| 正常系 | 7 | N-01〜N-07 |
| 異常系 | 3 | E-01〜E-03 |
| 境界値 | 5 | B-01〜B-05 |
| **合計** | **15** | |

**信頼性分布**: 🔵 13 / 🟡 2 / 🔴 0 — 品質評価: 高品質

---

## 1. 正常系テストケース（基本的な動作）

### N-01: PhaseLifecycle の明示値生成と属性取得
- **何をテストするか**: `PhaseLifecycle(birth_frame, death_frame, confidence)` が指定値で生成でき各属性を読み出せる。
- **期待される動作**: frozen dataclass として生成され属性が指定どおり保持される。
- **入力値**: `PhaseLifecycle(birth_frame=10, death_frame=15, confidence=0.8)`
  - **入力データの意味**: 相 B が frame 10 出現・frame 15 消滅・確信度 0.8 という代表的なライフサイクル。
- **期待される結果**: `.birth_frame == 10`、`.death_frame == 15`、`.confidence == 0.8`
  - **期待結果の理由**: interfaces.py L31-37 のフィールド定義に一致。
- **テストの目的**: 新設値オブジェクトの基本生成を確認。
  - **確認ポイント**: 3 フィールドが独立に保持されること。
- 🔵 (要件定義 2.1 / interfaces.py L31-37)

### N-02: PhaseLifecycle の等価比較
- **何をテストするか**: 同一フィールド値の 2 インスタンスが `==`、異なる値は `!=`。
- **期待される動作**: frozen dataclass の自動生成 `__eq__` が値比較する。
- **入力値**: `PhaseLifecycle(birth_frame=3) == PhaseLifecycle(birth_frame=3)` / `!= PhaseLifecycle(birth_frame=4)`
  - **入力データの意味**: 値オブジェクトとしての等価性 (M0/M1 の不変値オブジェクト規約) を代表。
- **期待される結果**: 前者 True、後者 True (不等)。
  - **期待結果の理由**: dataclass eq=True (既定) による構造的等価。
- **テストの目的**: 値等価の保証。
  - **確認ポイント**: birth_frame 以外の既定 (death_frame=None, confidence=1.0) も比較に含まれること。
- 🔵 (要件定義 2.1)

### N-03: ExternalChannel 生成と value_for（存在フレーム→値）
- **何をテストするか**: `ExternalChannel` を生成し `value_for(存在する frame_index)` が対応値を返す。
- **期待される動作**: `sync_map` に存在するキーで float 値を返す (TC-105-01)。
- **入力値**: `ExternalChannel(kind="temperature", sync_map={0: 300.0, 1: 310.0}).value_for(1)`
  - **入力データの意味**: 温度チャネルの frame→T 同期 (高温モードの中核) を代表。
- **期待される結果**: `310.0` (float)。`kind == "temperature"`、`label is None`。
  - **期待結果の理由**: interfaces.py L44-54 の `value_for` 契約 (`sync_map.get`) に一致。
- **テストの目的**: チャネル同期の基本参照を確認。
  - **確認ポイント**: 位置必須引数 kind/sync_map で生成でき、label が既定 None。
- 🔵 (要件定義 2.4 / TC-105-01 / interfaces.py L44-54)

### N-04: ExternalChannel の等価比較
- **何をテストするか**: 同一 kind/sync_map/label の 2 インスタンスが `==`。
- **期待される動作**: frozen dataclass の値比較が Mapping フィールド込みで成立。
- **入力値**: `ExternalChannel("time", {0: 0.0}) == ExternalChannel("time", {0: 0.0})`
  - **入力データの意味**: Mapping を持つ frozen 値オブジェクト (既存 `LatticeParams.sigma` と同扱い) の等価性を代表。
- **期待される結果**: True。
  - **期待結果の理由**: dict の `==` が要素比較するため。
- **テストの目的**: Mapping フィールドを含む等価比較の成立確認 (ハッシュ化はしない)。
  - **確認ポイント**: set/dict キー化はテストしない (非ハッシュ化型のため。要件定義 3 制約)。
- 🔵 (要件定義 2.4 / 3)

### N-05: PhaseInstance.lifecycle を with_updates で非破壊付与
- **何をテストするか**: 既存 `PhaseInstance` に `with_updates(lifecycle=...)` で lifecycle を差し替え、元インスタンスは不変。
- **期待される動作**: `replace` により新インスタンスが返り、元は `lifecycle is None` のまま (完了条件④)。
- **入力値**: `p = PhaseInstance("A", LatticeParams(5,5,5)); q = p.with_updates(lifecycle=PhaseLifecycle(birth_frame=3))`
  - **入力データの意味**: 逐次精密化で確定した lifecycle を相へ紐付ける実運用フロー。
- **期待される結果**: `q.lifecycle == PhaseLifecycle(birth_frame=3)`、`p.lifecycle is None`、`q is not p`。
  - **期待結果の理由**: `with_updates` が `dataclasses.replace` 実装のため追加フィールドで自動対応。
- **テストの目的**: 非破壊更新が新フィールドで機能することを確認。
  - **確認ポイント**: 元インスタンスの不変性 (P2)。
- 🔵 (要件定義 2.2 / 完了条件④ / phase.py L43-45)

### N-06: Hypothesis.frame_range の明示付与生成
- **何をテストするか**: `Hypothesis(..., frame_range=(10,20))` が生成でき値を保持し比較できる。
- **期待される動作**: frozen 維持で frame_range が tuple として保持される。
- **入力値**: `Hypothesis(id="h", phases=(), frame_range=(10, 20))`
  - **入力データの意味**: changepoint 後に採択された仮説の有効フレーム区間を代表。
- **期待される結果**: `.frame_range == (10, 20)`。既存フィールド (status="candidate" 等) は既定を維持。
  - **期待結果の理由**: interfaces.py L41 の追加フィールド定義に一致。
- **テストの目的**: 仮説の区間付与を確認。
  - **確認ポイント**: 既存フィールドの既定値が変わっていないこと。
- 🔵 (要件定義 2.3 / interfaces.py L41)

### N-07: model パッケージからの re-export と __all__ 収載
- **何をテストするか**: `from tsumugin.model import PhaseLifecycle, ExternalChannel` が解決し、両名が `tsumugin.model.__all__` に含まれる。
- **期待される動作**: `model/__init__.py` で import + `__all__` 追加済み。
- **入力値**: `import tsumugin.model as m` → `m.PhaseLifecycle`, `m.ExternalChannel`, `"PhaseLifecycle" in m.__all__`, `"ExternalChannel" in m.__all__`
  - **入力データの意味**: 後続タスクが公開 API 経由で参照する経路を代表。
- **期待される結果**: 両シンボルが解決可能かつ `__all__` に収載。
  - **期待結果の理由**: 要件定義 2.5 の re-export スコープ。
- **テストの目的**: 公開面の整備を確認。
  - **確認ポイント**: top-level `tsumugin.__init__` 昇格は本タスク必須スコープ外 (テストしない)。
- 🔵 (要件定義 2.5 / __init__.py)

---

## 2. 異常系テストケース（エラーハンドリング）

### E-01: PhaseLifecycle の frozen 再代入禁止
- **エラーケースの概要**: frozen dataclass のフィールドへ再代入を試みる。
- **エラー処理の重要性**: 不変値オブジェクト (P2) の不変性保証。誤った in-place 変更を防ぐ。
- **入力値**: `lc = PhaseLifecycle(); lc.confidence = 0.5`
  - **不正な理由**: frozen=True では属性再代入が禁止。
  - **実際の発生シナリオ**: 実装者が誤って直接代入した場合の防御。
- **期待される結果**: `dataclasses.FrozenInstanceError` が送出される (`with pytest.raises(dataclasses.FrozenInstanceError):`)。
  - **システムの安全性**: 変更は必ず新インスタンス生成経由に強制される。
- **テストの目的**: frozen 制約の確認。
  - **品質保証の観点**: 不変性違反の混入を CI で検出。
- 🔵 (要件定義 3 frozen 制約 / test_model.py の frozen 検証パターン)

### E-02: ExternalChannel の frozen 再代入禁止
- **エラーケースの概要**: `ExternalChannel` のフィールドへ再代入を試みる。
- **エラー処理の重要性**: 新設値オブジェクトの不変性保証。
- **入力値**: `ch = ExternalChannel("temperature", {0: 300.0}); ch.label = "x"`
  - **不正な理由**: frozen=True のため再代入不可。
  - **実際の発生シナリオ**: チャネル設定を後から書き換える誤用の防御。
- **期待される結果**: `dataclasses.FrozenInstanceError`。
  - **システムの安全性**: sync_map 同期の一貫性を破壊しない。
- **テストの目的**: frozen 制約の確認。
  - **品質保証の観点**: 不変性の担保。
- 🔵 (要件定義 3 frozen 制約)

### E-03: value_for が欠損 frame_index で None を返す（例外を出さない）
- **エラーケースの概要**: `sync_map` に存在しない frame_index を `value_for` に渡す。
- **エラー処理の重要性**: EDGE-102。チャネル欠損フレームで解析全体を止めないための縮退規約。
- **入力値**: `ExternalChannel("temperature", {0: 300.0}).value_for(5)`
  - **不正な理由**: frame_index=5 は sync_map に存在しない (温度データ欠損)。
  - **実際の発生シナリオ**: 温度ログとフレーム数の不一致 (EDGE-102 / TC-105-02)。
- **期待される結果**: `None` を返す。**例外 (KeyError 等) を送出しない**。
  - **エラーメッセージの内容**: 例外ではなく None を返し、上位が軸値 None + 警告として扱う。
  - **システムの安全性**: 欠損で処理継続 (P5 縮退規約)。
- **テストの目的**: 欠損時の非例外・None 返却を確認 (EDGE-102 の中核)。
  - **品質保証の観点**: 逐次解析のロバスト性を担保。
- 🔵 (要件定義 2.4/4.3 / EDGE-102 / TC-105-02 / interfaces.py L52-54)

---

## 3. 境界値テストケース（最小値、最大値、null等）

### B-01: PhaseLifecycle の全既定値生成
- **境界値の意味**: 引数なし生成 `PhaseLifecycle()` が既定 (None/None/1.0) で成立する縮退ケース。
- **境界値での動作保証**: すべて既定値でも frozen 値オブジェクトとして生成可能。
- **入力値**: `PhaseLifecycle()`
  - **境界値選択の根拠**: 全フィールド既定値付き (REQ-404 非破壊追加の前提) を検証。
  - **実際の使用場面**: 未追跡・未確定の相に付与される初期状態。
- **期待される結果**: `.birth_frame is None`、`.death_frame is None`、`.confidence == 1.0`。
  - **境界での正確性**: 既定値が interfaces.py の定義どおり。
  - **一貫した動作**: 明示生成 (N-01) と同一クラスで挙動一貫。
- **テストの目的**: 既定値縮退の確認。
  - **堅牢性の確認**: 引数省略でも安全に生成。
- 🔵 (要件定義 2.1/4.3 / interfaces.py L35-37)

### B-02: PhaseInstance の位置引数生成で lifecycle 既定 None（後方互換 smoke）
- **境界値の意味**: 既存の位置引数生成が新フィールド追加後も無改変で通る後方互換境界。
- **境界値での動作保証**: 追加フィールドが末尾・既定 None のため既存呼び出しを壊さない。
- **入力値**: `PhaseInstance("x", LatticeParams(5, 5, 5))`
  - **境界値選択の根拠**: REQ-404 の非破壊性を最小構成で検証 (既存テスト同型の呼び出し)。
  - **実際の使用場面**: M0/M1 コードが従来どおり PhaseInstance を構築する経路。
- **期待される結果**: 生成成功かつ `.lifecycle is None`。既存フィールド (`scale==1.0` 等) は不変。
  - **境界での正確性**: 位置引数の並びが変わっていない。
  - **一貫した動作**: 既存 226 テストと同じ生成が通る。
- **テストの目的**: 後方互換 (非破壊追加) の確認。
  - **堅牢性の確認**: 既存 API 破壊がないこと。
- 🔵 (要件定義 2.2/4.3 / REQ-404 / phase.py L34-41)

### B-03: Hypothesis の最小生成で frame_range 既定 None（後方互換 smoke）
- **境界値の意味**: 既存キーワード生成が新フィールド追加後も無改変で通る後方互換境界。
- **境界値での動作保証**: 追加フィールドが末尾・既定 None のため既存呼び出しを壊さない。
- **入力値**: `Hypothesis(id="h", phases=())`
  - **境界値選択の根拠**: REQ-404 の非破壊性を最小構成で検証 (既存 `test_defaults` 同型)。
  - **実際の使用場面**: 木探索・裁定が Hypothesis を構築する既存経路。
- **期待される結果**: 生成成功かつ `.frame_range is None`。`status == "candidate"`、`accepted_by is None` を維持。
  - **境界での正確性**: 既存の既定値が変わっていない。
  - **一貫した動作**: 既存生成と挙動一貫。
- **テストの目的**: 後方互換 (非破壊追加) の確認。
  - **堅牢性の確認**: 既存 API 破壊がないこと。
- 🔵 (要件定義 2.3/4.3 / REQ-404 / hypothesis.py L25-34)

### B-04: 空 sync_map の ExternalChannel は value_for が常に None
- **境界値の意味**: sync_map が空 (`{}`) という最小データ境界。
- **境界値での動作保証**: 空写像でも例外なく None を返す。
- **入力値**: `ExternalChannel("custom", {}).value_for(0)`
  - **境界値選択の根拠**: 全フレーム欠損という極端条件 (EDGE-102 の下限)。
  - **実際の使用場面**: チャネルは定義されたが同期データが未投入のケース。
- **期待される結果**: `None`。例外なし。
  - **境界での正確性**: `dict.get` の空辞書挙動と一致。
  - **一貫した動作**: E-03 (部分欠損) と同じ縮退挙動。
- **テストの目的**: 空写像境界での安全動作を確認。
  - **堅牢性の確認**: 空入力でクラッシュしない。
- 🟡 (要件定義 3/4.3 からの妥当な推測。EDGE-102 の下限ケースを明示化)

### B-05: PhaseLifecycle の confidence 境界値 [0.0, 1.0] を保持
- **境界値の意味**: 確信度レンジ [0,1] の下限 0.0・上限 1.0 を保持できる境界。
- **境界値での動作保証**: 本タスクは器のみのため範囲バリデーションはせず、渡した値をそのまま保持する。
- **入力値**: `PhaseLifecycle(confidence=0.0)` / `PhaseLifecycle(confidence=1.0)`
  - **境界値選択の根拠**: interfaces.py L37 が confidence を [0,1] と注記。境界端点を検証。
  - **実際の使用場面**: 後続 LifecycleTracker が算出した確信度 (0〜1) を保持。
- **期待される結果**: `.confidence == 0.0` / `.confidence == 1.0` をそのまま保持 (例外なし)。
  - **境界での正確性**: 値の丸め・クランプをしない (算出は後続スコープ)。
  - **一貫した動作**: 範囲外バリデーションは本タスクでは行わない (要件定義 4.4 注意)。
- **テストの目的**: 境界端点の保持を確認。
  - **堅牢性の確認**: 器としての値保持の一貫性。
- 🟡 (要件定義 4.4 / interfaces.py L37 の [0,1] 注記からの妥当な推測)

---

## 4. 開発言語・フレームワーク

- **プログラミング言語**: Python >= 3.12 🔵
  - **言語選択の理由**: プロジェクト全体が Python 3.12 (uv 管理, src layout + hatchling)。本タスクは model 拡張のため既存言語に一致。
  - **テストに適した機能**: `@dataclass(frozen=True)` の `FrozenInstanceError`、型注釈、`dataclasses.replace`。
- **テストフレームワーク**: pytest >= 8 + pytest-cov 🔵
  - **フレームワーク選択の理由**: `pyproject.toml [tool.pytest.ini_options]` で設定済み。既存 `tests/test_model.py` が pytest 準拠。
  - **テスト実行環境**: `uv run pytest tests/test_model_m2.py` (単体) / `uv run pytest` (全体回帰)。依存導入は `uv sync --extra gsas` (プレーン `uv sync` は禁止)。本タスクは GSAS-II 非依存のため `gsas` マーカー不要。
- 🔵 (note.md §5 テスト関連情報 / pyproject.toml)

---

## 5. テストケース実装時の日本語コメント指針

各テストに以下の形式で日本語コメントを付す (既存 M1 テスト test_clustering.py / test_m1_e2e.py の慣習に準拠)。

```python
# 【テスト目的】: value_for が欠損フレームで None を返し例外を出さないことを確認 (EDGE-102)
# 【テスト内容】: sync_map に無い frame_index を value_for に渡す
# 【期待される動作】: None を返し KeyError 等を送出しない
# 🔵 信頼性: EDGE-102 / TC-105-02 に依拠
def test_value_for_missing_frame_returns_none():
    # 【テストデータ準備】: frame 0 のみ持つ温度チャネルを用意 (frame 5 は欠損)
    # 【初期条件設定】: 部分的にしか同期データが無い実運用状況を再現
    channel = ExternalChannel(kind="temperature", sync_map={0: 300.0})

    # 【実際の処理実行】: 欠損フレーム 5 の値を要求
    # 【処理内容】: sync_map.get(5) 相当
    result = channel.value_for(5)

    # 【結果検証】: None が返り例外が出ないこと
    # 【検証項目】: 欠損フレームの縮退挙動
    # 🔵 信頼性: EDGE-102
    assert result is None  # 【確認内容】: 欠損フレームは None (例外なし)
```

frozen 検証の標準形:

```python
import dataclasses
import pytest

def test_phase_lifecycle_is_frozen():
    lc = PhaseLifecycle()
    with pytest.raises(dataclasses.FrozenInstanceError):
        lc.confidence = 0.5  # 【確認内容】: frozen のため再代入不可
```

---

## 6. 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (PhaseLifecycle / PhaseInstance.lifecycle / Hypothesis.frame_range / ExternalChannel の非破壊追加)
- **参照した入力・出力仕様**: 要件定義 §2.1〜2.5 (各フィールド・value_for・re-export)
- **参照した制約条件**: 要件定義 §3 (後方互換 / frozen / 例外を出さない / ハッシュ非対象 / 決定論)
- **参照した使用例**: 要件定義 §4 (基本パターン・データフロー・EDGE-102・後方互換 smoke)
- **参照した受け入れ基準**: TC-103 系 (ライフサイクル器)、TC-105-01 (温度同期)、TC-105-02 / EDGE-102 (欠損→None)
- **参照した完了条件**: TASK-0011 完了条件① frozen 生成/比較 → N-01〜N-04・E-01/E-02、② value_for 欠損 None → E-03・B-04、③ 新フィールド既定 None 後方互換 → B-02/B-03、④ with_updates(lifecycle=...) → N-05
- **回帰ゲート (テスト外)**: `uv run pytest` 全体で既存 226 テスト (223 passed / 3 skipped) を無改変で維持すること。既存テストファイルは 1 行も変更しない。

---

## 品質判定結果

- **テストケース分類**: 正常系 7 / 異常系 3 / 境界値 5 を網羅 ✅
- **期待値定義**: 各ケースに具体的期待値を明記 ✅
- **技術選択**: Python 3.12 + pytest で確定 ✅
- **実装可能性**: 純データモデルのため現行スタックで確実に実現可能 ✅
- **信頼性レベル**: 🔵 13 / 🟡 2 / 🔴 0 — **✅ 高品質**
