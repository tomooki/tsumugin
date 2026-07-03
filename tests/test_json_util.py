"""TASK-0023 `_json.finite_or_none` 統合 (Issue #5) の TDD Red フェーズテスト。

対象実装 (未実装):
- ``src/tsumugin/_json.py``: 無依存の葉モジュールに公開関数
  ``finite_or_none(value: float | None) -> float | None`` を単一実装として新設する。
  非有限 (inf/-inf/NaN) と None は None へ、有限値は float へ写像する純関数。
- ``search/tree.py`` / ``webui/app.py`` / ``store/serialization.py`` の 3 重複実装を
  ``_json.finite_or_none`` への**委譲**へ統合する (tree のセンチネル閾値判定は tree 内に残す)。

現時点で ``tsumugin._json`` モジュールが存在しないため、本ファイル冒頭の
``from tsumugin._json import finite_or_none`` が collection 時に ModuleNotFoundError となり、
本ファイルの全テストがエラー (= 失敗) になる想定 (tests/test_serialization.py と同一の Red 方針)。

テストケース定義 (json-finite-or-none-testcases.md, 16 件) との対応:
- 正常系   TC-J-N01〜N03  … 有限値の透過性 (test_finite_values_pass_through)
- 異常系   TC-J-E01〜E03  … 非有限 → None (test_non_finite_becomes_none)
- 境界値   TC-J-B01〜B05  … None / 0.0 / センチネル近傍 / 極値 / 純関数性
- 統合回帰 TC-J-R01〜R03  … tree/webui/serialization が共有関数へ委譲 (Green 後に通る)
- 統合回帰 TC-J-R05       … _json.py が無依存の葉モジュール (レイヤ制約)
  (TC-J-R04 の総合回帰 = 既存 433 テストの無改変 green は本ファイルではなく全体実行で担保)
"""

from __future__ import annotations

import math

import pytest

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定 (Red)。
from tsumugin._json import finite_or_none

# ---------------------------------------------------------------------------
# 1. 正常系テストケース（有限値の透過性）+ 3. 境界値の一部（0.0 / センチネル未満 / 極値）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value, expected",
    [
        pytest.param(1.5, 1.5, id="TC-J-N01_finite_positive"),
        pytest.param(5, 5.0, id="TC-J-N02_int_to_float"),
        pytest.param(-3.5, -3.5, id="TC-J-N03_finite_negative"),
        pytest.param(0.0, 0.0, id="TC-J-B02_falsy_zero_kept"),
        pytest.param(1e17, 1e17, id="TC-J-B03_below_sentinel_passthrough"),
        pytest.param(1e-300, 1e-300, id="TC-J-B04_tiny_finite"),
        pytest.param(1e308, 1e308, id="TC-J-B04_huge_finite"),
    ],
)
def test_finite_values_pass_through(value, expected):
    # 【テスト目的】: 有限値 (0.0 や極小/極大、センチネル未満の 1e17 を含む) が純化されず
    #                同値かつ float 型で返ることを確認 (N01/N02/N03/B02/B03/B04)
    # 【テスト内容】: finite_or_none(value) が float(value) を返す
    # 【期待される動作】: math.isfinite が True の値は None 化されず透過する
    # 🔵 信頼性レベル: 要件定義 §2 真理値表 / 既存 3 実装の現行挙動に一致

    # 【実際の処理実行】: 純化対象を finite_or_none へ渡す
    result = finite_or_none(value)

    # 【結果検証】: 値の等価性と、int 入力を含め float へ正規化されること
    assert result == expected  # 【確認内容】: 有限値が同値で返る 🔵
    assert isinstance(result, float)  # 【確認内容】: 戻り値が float へ正規化される 🔵
    assert result is not None  # 【確認内容】: 0.0 等の falsy 有限値を None に潰さない 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース（非有限値の純化）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(float("inf"), id="TC-J-E01_positive_inf"),
        pytest.param(float("-inf"), id="TC-J-E02_negative_inf"),
        pytest.param(float("nan"), id="TC-J-E03_nan"),
    ],
)
def test_non_finite_becomes_none(value):
    # 【テスト目的】: +inf / -inf / NaN が例外を投げず None へ純化されること (E01/E02/E03)
    # 【テスト内容】: 非有限値は JSON 非対応のため配信前に None へ縮退させる (EDGE-004)
    # 【期待される動作】: math.isfinite が False の値は None を返す
    # 🔵 信頼性レベル: 要件定義 §2 / tree.py L190 / serialization.py L32 の現行挙動に一致

    # 【結果検証】: 非有限は None へ写像される (符号非依存)
    assert finite_or_none(value) is None  # 【確認内容】: 非有限 → None 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース（None 受理 / 純関数性）
# ---------------------------------------------------------------------------


def test_none_input_returns_none():
    # 【テスト目的】: None 入力を受理し None を返す (TC-J-B01, serialization の None 経路を保存)
    # 【テスト内容】: float(None) を呼ぶ前に None 分岐で早期 return し TypeError を出さない
    # 【期待される動作】: finite_or_none(None) が None
    # 🔵 信頼性レベル: store/serialization.py L28-29 の現行挙動 / 要件定義 §2 真理値表に一致

    # 【結果検証】: None を数値変換しようとして例外化しないこと
    assert finite_or_none(None) is None  # 【確認内容】: None 受理・TypeError を出さない 🔵


def test_pure_and_deterministic():
    # 【テスト目的】: 純関数・決定論 (TC-J-B05, NFR-102) — 副作用なし・同一入力で同一出力
    # 【テスト内容】: 同一入力を複数回呼んでも同値、隠れ状態を持たない
    # 【期待される動作】: 有限値は毎回同値、NaN は毎回 None
    # 🔵 信頼性レベル: 要件定義 §3 (決定論 / 純関数 NFR-102) に一致

    # 【結果検証】: 有限値は毎回同値で返る (グローバル状態なし)
    assert finite_or_none(1.5) == finite_or_none(1.5) == 1.5  # 【確認内容】: 決定論 (有限) 🔵
    # 【結果検証】: NaN は毎回 None (2 回連続で確認)
    assert finite_or_none(float("nan")) is None  # 【確認内容】: 決定論 (NaN 1 回目) 🔵
    assert finite_or_none(float("nan")) is None  # 【確認内容】: 決定論 (NaN 2 回目) 🔵


# ---------------------------------------------------------------------------
# 4. 統合・回帰テストケース（委譲の検証 / レイヤ制約） — Green 後に通る
# ---------------------------------------------------------------------------


def test_serialization_delegates_to_shared_finite_or_none():
    # 【テスト目的】: store/serialization がローカル _finite_or_none を廃し共有関数へ委譲 (TC-J-R01)
    # 【テスト内容】: serialization モジュールの finite_or_none が _json の同一オブジェクトであること
    # 【期待される動作】: `from .._json import finite_or_none` により同一関数を参照する
    # 🔵 信頼性レベル: 要件定義 §2 委譲後の期待 / D-Q9 に一致

    import tsumugin.store.serialization as ser

    # 【結果検証】: serialization が単一情報源 _json.finite_or_none を参照している
    assert ser.finite_or_none is finite_or_none  # 【確認内容】: 重複定義の廃止・委譲 🔵


def test_webui_delegates_to_shared_finite_or_none():
    # 【テスト目的】: webui/app.py が search/tree の私的横断 import を廃し共有関数へ委譲 (TC-J-R02)
    # 【テスト内容】: app モジュールの finite_or_none が _json の同一オブジェクトであること
    # 【期待される動作】: `from ..search.tree import _finite_or_none` を `from .._json import
    #                    finite_or_none` へ置換 → レイヤ逆依存 (webui→search) を解消する
    # 🔵 信頼性レベル: 要件定義 §1/§2 / D-Q9 (レイヤ制約) に一致

    # 【前提】: webui モジュール import 自体は web extra 未導入でも成功する契約 (app.py docstring)
    import tsumugin.webui.app as app_mod

    # 【結果検証】: webui が search 内部シンボルではなく単一情報源 _json を参照している
    assert app_mod.finite_or_none is finite_or_none  # 【確認内容】: 私的横断 import の解消 🔵


def test_tree_delegates_but_retains_sentinel():
    # 【テスト目的】: search/tree が非有限判定を共有関数へ委譲しつつ、探索固有のセンチネル閾値
    #                判定 (>= _EVIDENCE_SENTINEL) は tree 内に残すこと (TC-J-R03, D-Q9)
    # 【テスト内容】: tree.finite_or_none は共有関数と同一、一方 tree._finite_or_none ラッパは
    #                センチネル以上を None 化する (共有関数単体はセンチネル非関与で透過)
    # 【期待される動作】: 委譲 + センチネル局所性の両立
    # 🔵 信頼性レベル: 要件定義 §3 (センチネルの局所性) / D-Q9 / tree.py L190 の構造に一致

    import tsumugin.search.tree as tree

    # 【結果検証】: tree が非有限判定を単一情報源 _json.finite_or_none へ委譲している
    assert tree.finite_or_none is finite_or_none  # 【確認内容】: tree の委譲 🔵
    # 【結果検証】: センチネル定数は探索固有契約として tree 内に維持される
    assert tree._EVIDENCE_SENTINEL == 1e18  # 【確認内容】: センチネル定数の tree 残置 🔵
    # 【結果検証】: 共有関数はセンチネルを知らず有限なら透過する (葉に探索固有ロジックを持ち込まない)
    assert finite_or_none(tree._EVIDENCE_SENTINEL) == 1e18  # 【確認内容】: 共有関数はセンチネル非関与 🔵
    # 【結果検証】: tree のラッパはセンチネル以上を None 化する (残置された >= 判定)
    assert tree._finite_or_none(tree._EVIDENCE_SENTINEL) is None  # 【確認内容】: tree でセンチネル→None 🔵
    # 【結果検証】: センチネル未満の大きな有限値は tree でも透過する
    assert tree._finite_or_none(1e17) == 1e17  # 【確認内容】: センチネル未満は透過 🔵


def test_json_module_is_dependency_free_leaf():
    # 【テスト目的】: _json.py が標準ライブラリ (math) のみに依存する無依存の葉であること (TC-J-R05)
    # 【テスト内容】: モジュールソースに上位レイヤ / numpy の import を含まない (静的検査)
    # 【期待される動作】: import tsumugin._json が単独成功し、逆依存を将来にわたり混入させない
    # 🔵 信頼性レベル: 要件定義 §3 (レイヤ制約) / D-Q9 に一致

    import inspect

    import tsumugin._json as json_mod

    # 【結果検証】: 葉モジュールが上位レイヤ・numpy を import しないこと (回帰ガード)
    src = inspect.getsource(json_mod)
    for forbidden in ("tsumugin.search", "tsumugin.webui", "tsumugin.store", "import numpy"):
        assert forbidden not in src  # 【確認内容】: 下向き依存のみの葉モジュール 🔵

    # 【補助検証】: 純化ロジックが math.isfinite の仕様と整合すること (実装存在の最小確認)
    assert finite_or_none(math.pi) == math.pi  # 【確認内容】: 有限値の透過 (実装の存在確認) 🔵
