# TASK-0023 テストケース: `_json.finite_or_none` 統合 (Issue #5)

**機能名**: json-finite-or-none / **タスクID**: TASK-0023 / **要件名**: m3-operando
**対象**: `src/tsumugin/_json.py::finite_or_none(value: float | None) -> float | None`
**新規テストファイル**: `tests/test_json.py` / **信頼性**: 🔵 (要件定義 §2 真理値表 / 既存 3 実装の現行挙動)

> すべてのパスはプロジェクトルートからの相対パス。

## テストケース総括

| 分類 | 件数 | ケースID |
|---|---|---|
| 1. 正常系 | 3 | TC-J-N01〜N03 |
| 2. 異常系 | 3 | TC-J-E01〜E03 |
| 3. 境界値 | 5 | TC-J-B01〜B05 |
| 4. 統合・回帰 | 5 | TC-J-R01〜R05 |
| **合計** | **16** | |

**新規単体テスト (`tests/test_json.py` に追加)**: TC-J-N01〜N03 / E01〜E03 / B01〜B05 / R05 = **12 件**。
**回帰確認 (既存テスト無改変 green で担保)**: TC-J-R01〜R04 = **4 件** (新規コードは書かず既存 433 件の green で検証)。

---

## 1. 正常系テストケース（基本的な動作）

### TC-J-N01: 有限な正の float はそのまま返す
- **何をテストするか**: 有限な正の浮動小数点数が純化されず同値で返ること。
- **期待される動作**: `finite_or_none(1.5)` が `1.5` を返す。
- **入力値**: `1.5`
  - **入力データの意味**: 最も基本的な「純化不要な有限値」の代表。rwp/gof/evidence など通常の数値を代表。
- **期待される結果**: `1.5` (型 `float`)
  - **期待結果の理由**: 有限値は `math.isfinite` が True のため None 化されず `float(value)` がそのまま返る (要件 §2)。
- **テストの目的**: 有限値の透過性を確認。
  - **確認ポイント**: 値の等価性と `float` 型であること。
- 🔵 信頼性: 要件定義 §2 真理値表 / 既存 3 実装の現行挙動に一致。

### TC-J-N02: int 入力は float へ変換して返す
- **何をテストするか**: `int` を渡すと `float` 化されて返ること。
- **期待される動作**: `finite_or_none(5)` が `5.0` を返し、`isinstance(result, float)` が True。
- **入力値**: `5` (int)
  - **入力データの意味**: serialization の `birth_frame` 隣接値など整数由来の数値が混入しうる経路を代表。
- **期待される結果**: `5.0` (型 `float`)
  - **期待結果の理由**: 実装が `float(value)` を経由するため int も float 化される (要件 §2 出力仕様)。
- **テストの目的**: 型正規化 (float 統一) の確認。
  - **確認ポイント**: 戻り値の型が `float` であること (`5 == 5.0` は True だが型を明示検証)。
- 🔵 信頼性: 要件定義 §2 (`float(value)` を返す) に一致。

### TC-J-N03: 負の有限 float はそのまま返す
- **何をテストするか**: 負値も純化対象でなくそのまま返ること。
- **期待される動作**: `finite_or_none(-3.5)` が `-3.5` を返す。
- **入力値**: `-3.5`
  - **入力データの意味**: 符号に依存せず有限性のみで判定することの確認 (evidence 値は負を取りうる)。
- **期待される結果**: `-3.5`
  - **期待結果の理由**: 有限性判定は符号非依存。負の有限値は保持される (要件 §2 真理値表)。
- **テストの目的**: 符号非依存性の確認。
  - **確認ポイント**: 負値が誤って None 化されないこと。
- 🔵 信頼性: 要件定義 §2 真理値表に一致。

---

## 2. 異常系テストケース（非有限値の純化）

> 「異常系」といっても本関数では非有限入力は**正常経路** (EDGE-004: chi2=inf は仕様上の正常経路)。
> 例外は投げず `None` へ写像するのが正しい挙動。

### TC-J-E01: 正の無限大は None を返す
- **エラーケースの概要**: 精密化発散などで `+inf` が数値フィールドに入る状況。
- **エラー処理の重要性**: JSON には `inf` が存在しないため、配信/直列化前に `None` へ落とさないと
  `json.dumps(allow_nan=False)` が ValueError になる (M1 教訓)。
- **入力値**: `float("inf")`
  - **不正な理由**: `math.isfinite` が False。
  - **実際の発生シナリオ**: 探索モード精密化の発散、evidence 計算の桁あふれ。
- **期待される結果**: `None`
  - **システムの安全性**: 非有限を下流の JSON に漏らさず、安全に欠測表現へ縮退する。
- **テストの目的**: `+inf → None` 写像の確認。
  - **品質保証の観点**: JSON 純化契約の中核。
- 🔵 信頼性: 要件定義 §2 / `search/tree.py` L190 / `store/serialization.py` L32 の現行挙動に一致。

### TC-J-E02: 負の無限大は None を返す
- **エラーケースの概要**: `-inf` (下方発散) が入る状況。
- **エラー処理の重要性**: `+inf` と同様に JSON 非対応値。符号に関わらず None 化が必要。
- **入力値**: `float("-inf")`
  - **不正な理由**: `math.isfinite` が False。
  - **実際の発生シナリオ**: 対数尤度・BIC の下方発散など。
- **期待される結果**: `None`
  - **システムの安全性**: 非有限を欠測へ縮退。
- **テストの目的**: `-inf → None` 写像の確認 (符号非依存)。
  - **品質保証の観点**: 非有限判定が両符号の無限大を捕捉することの保証。
- 🔵 信頼性: 要件定義 §2 真理値表 / `math.isfinite` の仕様に一致。

### TC-J-E03: NaN は None を返す
- **エラーケースの概要**: `NaN` (0/0 や未定義演算) が入る状況。
- **エラー処理の重要性**: `NaN` は比較不能で下流の全処理を汚染する。早期に `None` 化が必須。
- **入力値**: `float("nan")`
  - **不正な理由**: `math.isfinite` が False (`NaN != NaN`)。
  - **実際の発生シナリオ**: softmax の 0/0、共分散未定義、occupancy 欠損計算。
- **期待される結果**: `None`
  - **システムの安全性**: NaN を欠測へ縮退し JSON 直列化を保証。
- **テストの目的**: `NaN → None` 写像の確認。
  - **品質保証の観点**: 最も危険な非有限値の封じ込め。
- 🔵 信頼性: 要件定義 §2 / `search/tree.py` L190 / `store/serialization.py` L32 の現行挙動に一致。

---

## 3. 境界値テストケース（None・0.0・センチネル近傍等）

### TC-J-B01: None 入力は None を返す
- **境界値の意味**: `None` (未定値) は「非数値だが正当な入力」。serialization が `None` を渡すため必須の受理経路。
- **入力値**: `None`
  - **境界値選択の根拠**: `store/serialization.py` 版 (L28-29) は `if value is None: return None` を持ち、
    `wt_frac=None` 等を渡す。統合先 `finite_or_none` は `float | None` を受理せねばならない (要件 §2/§3)。
- **期待される結果**: `None`
  - **境界での正確性**: `float(None)` を呼ぶ前に `None` 分岐で早期 return し TypeError を出さないこと。
- **テストの目的**: `None` 受理と `None` 返却の確認 (旧 serialization 挙動の保存)。
  - **堅牢性の確認**: `None` を数値変換しようとして例外化しないこと。
- 🔵 信頼性: `store/serialization.py` L28-29 の現行挙動 / 要件定義 §2 真理値表に一致。

### TC-J-B02: 有限ゼロ 0.0 はそのまま 0.0 を返す（falsy 有限値の保持）
- **境界値の意味**: `0.0` は falsy だが有限の正当値。`None` と混同して潰してはならない。
- **入力値**: `0.0`
  - **境界値選択の根拠**: `if not value` のような誤実装だと `0.0` を弾く。`is None` / `isfinite` で正しく分岐することの検証
    (`tests/test_serialization.py` B-06 の思想)。
- **期待される結果**: `0.0` (`result == 0.0` かつ `result is not None`)
  - **境界での正確性**: 有限ゼロは保持され None 化されない。
- **テストの目的**: falsy な有限値を None に潰さないことの確認。
  - **堅牢性の確認**: `0.0` と `None` の区別。
- 🔵 信頼性: 要件定義 §2 真理値表 / `tests/test_serialization.py` B-06 に一致。

### TC-J-B03: センチネル未満の大きな有限値はそのまま返す（finite_or_none 単体はセンチネル非関与）
- **境界値の意味**: `_EVIDENCE_SENTINEL = 1e18` は**探索固有**でありセンチネル未満 (例 `1e17`) は普通の有限値。
  `_json.finite_or_none` は**センチネルを知らない**ため大きな有限値もそのまま返す (センチネル判定は tree 側に残る)。
- **入力値**: `1e17`
  - **境界値選択の根拠**: D-Q9 の「センチネル判定は tree 側に残す」を単体レベルで裏付ける。`finite_or_none` に
    センチネル閾値が混入していない (1e17 も 1e18 も有限なら透過) ことの確認。
- **期待される結果**: `1e17` (そのまま)
  - **境界での正確性**: `finite_or_none` はセンチネル閾値による None 化を**行わない**。
- **テストの目的**: センチネル局所性 (tree 残置) の確認。
  - **堅牢性の確認**: 葉モジュールに探索固有ロジックが漏れていないこと。
- 🔵 信頼性: 要件定義 §3 (センチネルの局所性) / D-Q9 / `search/tree.py` L190 の構造に一致。

### TC-J-B04: 極小・極大の有限値はそのまま返す
- **境界値の意味**: `float` 表現の端 (最小正規化数近傍 `1e-300`、有限最大近傍 `1e308`) でも有限なら保持。
- **入力値**: `1e-300`、`1e308` (パラメータ化)
  - **境界値選択の根拠**: `math.isfinite` は極端でも有限なら True。オーバーフロー直前の有限値の透過を確認。
- **期待される結果**: 各々そのまま (`1e-300`、`1e308`)
  - **境界での正確性**: 有限性のみで判定し、大きさで誤って None 化しない。
- **テストの目的**: 有限範囲全域での透過性。
  - **堅牢性の確認**: 極端な有限値でも一貫動作。
- 🔵 信頼性: `math.isfinite` の仕様 / 要件定義 §2 に一致。

### TC-J-B05: 純関数性・決定論（副作用なし・同一入力で同一出力）
- **境界値の意味**: 純関数契約 (NFR-102) の境界検証。入力を破壊せず、複数回呼んでも同値。
- **入力値**: `1.5` を 2 回、および `float("nan")` を 2 回
  - **境界値選択の根拠**: 決定論・副作用なしを最小コストで確認。
- **期待される結果**: `finite_or_none(1.5) == finite_or_none(1.5) == 1.5`、`finite_or_none(nan) is None` を 2 回とも満たす。
  - **境界での正確性**: グローバル状態を持たない純関数であること。
- **テストの目的**: 決定論・非破壊性の確認。
  - **堅牢性の確認**: 隠れ状態がないこと。
- 🔵 信頼性: 要件定義 §3 (決定論 / 純関数 NFR-102) に一致。

---

## 4. 統合・回帰テストケース（挙動不変・単一情報源化の担保）

> TC-J-R01〜R04 は**新規コードを書かず既存 433 テストの無改変 green** で担保する (挙動不変の証明)。
> TC-J-R05 は `tests/test_json.py` に追加するレイヤ制約の単体テスト。

### TC-J-R01: serialization が共有 finite_or_none へ委譲しても挙動不変
- **何をテストするか**: `store/serialization.py` のローカル `_finite_or_none` 廃止・共有関数委譲後も直列化挙動が不変。
- **期待される結果**: `tests/test_serialization.py` の 15 件 (特に E-01 scale=inf→None、E-02 lattice.a=nan/sigma inf→None、
  E-03 wt_frac=inf/occupancy=nan/confidence=nan→None、B-06 有限端点保持、N-03 `json.dumps(allow_nan=False)` 成功) が**無改変で全 green**。
- **テストの目的**: serialization 側委譲の非退行確認。
  - **確認ポイント**: `None` 入力経路 (wt_frac=None 等) も含め挙動一致。
- 🔵 信頼性: `tests/test_serialization.py` (既存) / 要件定義 §2 に一致。

### TC-J-R02: webui が `_json.finite_or_none` を import しても配信挙動不変
- **何をテストするか**: `webui/app.py` L27 の `from ..search.tree import _finite_or_none` を
  `from .._json import finite_or_none` へ置換後も API 配信が不変 (私的横断 import の解消)。
- **期待される結果**: `tests/test_webui.py` (特に `test_summary_with_infinite_metrics_is_strict_json`、
  `test_api_result_with_infinite_metrics_returns_null`、`test_detail_and_summary_evidence_representation_is_consistent`) が**無改変で全 green**。
- **テストの目的**: webui 側 import 差し替えの非退行 + レイヤ逆依存解消の確認。
  - **確認ポイント**: webui が search 内部シンボルへ依存しなくなること。
- 🔵 信頼性: `tests/test_webui.py` (既存) / D-Q9 / 要件定義 §1 に一致。

### TC-J-R03: tree のセンチネル判定残置により detail と summary の evidence 表現が一致
- **何をテストするか**: `search/tree.py` が非有限判定を `finite_or_none` へ委譲しつつ**センチネル判定 (`>= _EVIDENCE_SENTINEL`) を残す**ことで、
  全 inf ガード (`_FiniteGuardedEvidence`) 経由のセンチネル値が引き続き `None` 表現されること。
- **期待される結果**: `tests/test_webui.py::test_detail_and_summary_evidence_representation_is_consistent` および
  `tests/test_tree_search.py` の to_summary/ランキング関連が**無改変で全 green**。
- **テストの目的**: センチネル局所性 (tree 残置) が壊れていないことの確認。
  - **確認ポイント**: `_EVIDENCE_SENTINEL` と `>=` 判定が tree 内に維持され、evidence.value が None になること。
- 🔵 信頼性: `tests/test_webui.py` / `tests/test_tree_search.py` (既存) / D-Q9 に一致。

### TC-J-R04: 既存 433 テスト全体が無改変で green（総合回帰）
- **何をテストするか**: `uv run pytest` (gsas extra 導入環境) が **430 passed / 3 skipped** を維持。
- **期待される結果**: 統合後もベースラインと同一 (430 passed / 3 skipped)。テストコードは 1 件も改変しない。
- **テストの目的**: 挙動不変リファクタの最終保証 (完了の絶対条件・TC-208-03)。
  - **確認ポイント**: 新規 `tests/test_json.py` を足した後の総数は増えるが、**既存 433 件は無改変で全 pass/skip**。
- 🔵 信頼性: `docs/spec/m3-operando/note.md` ベースライン / TC-208-03 / タスク完了条件に一致。

### TC-J-R05: `_json.py` は無依存の葉モジュール（レイヤ制約）
- **何をテストするか**: `src/tsumugin/_json.py` が標準ライブラリ (`math`) のみに依存し、上位レイヤ
  (`tsumugin.search` / `tsumugin.webui` / `tsumugin.store` / numpy / GSAS-II) を import しないこと。
- **期待される結果**: `import tsumugin._json` が単独成功し、`finite_or_none` が呼べる。モジュールソースに
  `tsumugin.search`/`tsumugin.webui`/`tsumugin.store`/`import numpy` を含まない (静的検査 or `inspect.getsource` で確認)。
- **入力値**: モジュール `tsumugin._json` 自体
  - **境界値選択の根拠**: D-Q9 の「無依存の葉モジュール」制約を機械的に固定し、将来の逆依存混入を防ぐ回帰ガード。
- **テストの目的**: レイヤ逆依存解消の恒久的担保。
  - **確認ポイント**: 下向き依存のみ (葉) であること。
- 🔵 信頼性: 要件定義 §3 (レイヤ制約) / D-Q9 に一致。

---

## 開発言語・フレームワーク

- **プログラミング言語**: Python 3.12
  - **言語選択の理由**: プロジェクト全体が Python >= 3.12 (uv 管理, src layout)。対象 `_json.py` も Python。
  - **テストに適した機能**: `math.isfinite` / `float("inf")` / `float("nan")` で非有限値を直接生成でき、
    `pytest.mark.parametrize` で真理値表を簡潔に網羅できる。
- **テストフレームワーク**: pytest >= 8 (+ pytest-cov)
  - **フレームワーク選択の理由**: 既存 29 テストファイルすべてが pytest。`tests/test_{module}.py` 命名に従い `tests/test_json.py` を新設。
  - **テスト実行環境**: `uv run pytest tests/test_json.py` (単体) / `uv run pytest` (全体回帰、`uv sync --extra gsas` 前提)。
- 🔵 信頼性: `pyproject.toml` / `docs/spec/m3-operando/note.md` テスト要件に一致。

## テストケース実装時の指針（Python / pytest）

```python
import math
import pytest
from tsumugin._json import finite_or_none


@pytest.mark.parametrize("value, expected", [
    (1.5, 1.5),        # TC-J-N01: 有限正 float はそのまま
    (5, 5.0),          # TC-J-N02: int → float
    (-3.5, -3.5),      # TC-J-N03: 負の有限もそのまま
    (0.0, 0.0),        # TC-J-B02: falsy な有限値を保持
    (1e17, 1e17),      # TC-J-B03: センチネル未満の大きな有限値は透過
    (1e-300, 1e-300),  # TC-J-B04: 極小有限
    (1e308, 1e308),    # TC-J-B04: 極大有限
])
def test_finite_values_pass_through(value, expected):
    # 【テスト目的】: 有限値・None 以外の正常値が純化されず同値(float)で返ること
    # 【期待される動作】: finite_or_none が float(value) を返す 🔵
    result = finite_or_none(value)
    assert result == expected            # 【検証項目】: 値の等価性 🔵
    assert isinstance(result, float)     # 【検証項目】: float へ正規化 🔵


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_becomes_none(value):
    # 【テスト目的】: inf/-inf/NaN が None へ純化されること (TC-J-E01/E02/E03) 🔵
    assert finite_or_none(value) is None  # 【検証項目】: 非有限 → None 🔵


def test_none_returns_none():
    # 【テスト目的】: None 入力を受理し None を返す (TC-J-B01, serialization 経路) 🔵
    assert finite_or_none(None) is None   # 【検証項目】: None 受理・TypeError を出さない 🔵


def test_pure_and_deterministic():
    # 【テスト目的】: 純関数・決定論 (TC-J-B05, NFR-102) 🔵
    assert finite_or_none(1.5) == finite_or_none(1.5) == 1.5
    assert finite_or_none(float("nan")) is None
    assert finite_or_none(float("nan")) is None


def test_json_module_is_leaf():
    # 【テスト目的】: _json.py が無依存の葉である (TC-J-R05, D-Q9) 🔵
    import inspect
    import tsumugin._json as j
    src = inspect.getsource(j)
    # 【検証項目】: 上位レイヤ・numpy を import しない 🔵
    for forbidden in ("tsumugin.search", "tsumugin.webui", "tsumugin.store", "import numpy"):
        assert forbidden not in src
```

## 要件定義との対応関係

- **参照した機能概要**: 要件定義 §1 (単一情報源化 / レイヤ逆依存解消 / センチネルは tree 残置)
- **参照した入力・出力仕様**: 要件定義 §2 (署名 `finite_or_none(value: float | None) -> float | None` / 真理値表)
- **参照した制約条件**: 要件定義 §3 (挙動不変 / レイヤ制約 / センチネル局所性 / 決定論 / 非破壊)
- **参照した使用例**: 要件定義 §4 (serialization / webui / tree の各委譲経路、None 入力、0.0 保持、センチネル、trajectory 対象外)

---

## 品質判定

```
✅ 高品質:
- テストケース分類: 正常系(3)・異常系(3)・境界値(5)・統合回帰(5) を網羅
- 期待値定義: 全ケース具体値で明確 (真理値表準拠)
- 技術選択: Python 3.12 + pytest (既存スタックと一致) で確定
- 実装可能性: 標準ライブラリのみの純関数 + 既存テスト無改変で実現確実
- 信頼性レベル: 🔵 16/16 (要件定義 §2 真理値表・既存 3 実装の現行挙動・D-Q9 に直接依拠)
```
