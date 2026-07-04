"""TASK-0042 chem/base + chem/rules + chem/compose の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/chem/base.py``: ``SynthesisContext`` / ``PlausibilityResult`` (frozen
  dataclass) と ``ChemPlausibility`` runtime_checkable Protocol
  (``name`` + ``score(phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult``)
- ``src/tsumugin/chem/rules.py``: ``AlkaliMetalInAirRule`` (name="alkali_metal_in_air")
- ``src/tsumugin/chem/compose.py``: ``combine_plausibility(results, *, weights=None)``
- ``src/tsumugin/chem/__init__.py``: 上記 5 シンボルの re-export (__all__ 昇順)

契約は ``docs/design/m4-joint-mcp/interfaces.py`` の chem/base・chem/rules・chem/compose 節に依拠。
frozen 検証は ``FrozenInstanceError``、近似は ``pytest.approx``。

TASK-0042.md 完了条件・TC-406-01/02/03/06 系に 1:1 対応する。未実装のため import が
collection 時に失敗し、全テストがエラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from tsumugin.chem import (
    AlkaliMetalInAirRule,
    ChemPlausibility,
    PlausibilityResult,
    SynthesisContext,
    combine_plausibility,
)
from tsumugin.model.phase import PhaseRef


# ---------------------------------------------------------------------------
# 1. SynthesisContext — 生成 / 既定値 / frozen (TC-406-01)
# ---------------------------------------------------------------------------


def test_synthesis_context_defaults():
    # 【目的】: 全フィールド既定値で生成でき空/None を保持する (TC-406-01) 🔵
    ctx = SynthesisContext()
    assert ctx.element_system == ()  # 【確認】: 元素系 既定は空 tuple 🔵
    assert ctx.precursors == ()  # 【確認】: 前駆体 既定は空 tuple 🔵
    assert ctx.atmosphere is None  # 【確認】: 雰囲気 既定は None 🔵
    assert ctx.temperature_history_c == ()  # 【確認】: 温度履歴 既定は空 tuple 🔵
    assert ctx.electrochemical_window_v is None  # 【確認】: 電気化学窓 既定は None 🔵


def test_synthesis_context_explicit_fields():
    # 【目的】: 全フィールド明示指定が保持される 🔵
    ctx = SynthesisContext(
        element_system=("Li", "Fe", "P", "O"),
        precursors=("Li2CO3", "FePO4"),
        atmosphere="Ar",
        temperature_history_c=(25.0, 700.0, 25.0),
        electrochemical_window_v=(2.5, 4.2),
    )
    assert ctx.element_system == ("Li", "Fe", "P", "O")
    assert ctx.precursors == ("Li2CO3", "FePO4")
    assert ctx.atmosphere == "Ar"
    assert ctx.temperature_history_c == (25.0, 700.0, 25.0)
    assert ctx.electrochemical_window_v == (2.5, 4.2)


def test_synthesis_context_is_frozen():
    # 【目的】: frozen dataclass で属性再代入不可 🔵
    ctx = SynthesisContext()
    with pytest.raises(FrozenInstanceError):
        ctx.atmosphere = "air"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. PlausibilityResult — 生成 / frozen (TC-406-01)
# ---------------------------------------------------------------------------


def test_plausibility_result_construction():
    # 【目的】: PlausibilityResult が score/rationale/source を保持する (TC-406-01) 🔵
    r = PlausibilityResult(score=0.1, rationale="単体アルカリ金属は大気下で不安定", source="alkali_metal_in_air")
    assert r.score == pytest.approx(0.1)
    assert r.rationale == "単体アルカリ金属は大気下で不安定"
    assert r.source == "alkali_metal_in_air"


def test_plausibility_result_is_frozen():
    # 【目的】: frozen dataclass 🔵
    r = PlausibilityResult(score=1.0, rationale="", source="x")
    with pytest.raises(FrozenInstanceError):
        r.score = 0.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. ChemPlausibility Protocol — 構造的適合 (TC-406-01)
# ---------------------------------------------------------------------------


def test_alkali_rule_is_chem_plausibility_instance():
    # 【目的】: AlkaliMetalInAirRule が ChemPlausibility Protocol へ isinstance 適合 (TC-406-01) 🔵
    rule = AlkaliMetalInAirRule()
    assert isinstance(rule, ChemPlausibility)  # 【確認】: 構造的適合 (name + score) 🔵


def test_alkali_rule_name():
    # 【目的】: name が決定論キー "alkali_metal_in_air" (REQ-402) 🔵
    assert AlkaliMetalInAirRule().name == "alkali_metal_in_air"


# ---------------------------------------------------------------------------
# 4. AlkaliMetalInAirRule.score — 降格判定 (TC-406-02 / REQ-017)
# ---------------------------------------------------------------------------


def test_alkali_metal_in_air_demotes_by_formula():
    # 【目的】: 大気下の単体アルカリ金属 (formula) を降格 score<1 (TC-406-02/REQ-017) 🔵
    rule = AlkaliMetalInAirRule()
    phase = PhaseRef(id="li_metal", formula="Li")
    ctx = SynthesisContext(atmosphere="air")
    result = rule.score(phase, ctx)
    assert result.score < 1.0  # 【確認】: 降格 🔵
    assert result.source == "alkali_metal_in_air"
    assert result.rationale  # 【確認】: 理由が明示される 🔵


def test_alkali_metal_in_air_demotes_by_element_system():
    # 【目的】: formula None でも element_system 単体でアルカリ金属を降格 🔵
    rule = AlkaliMetalInAirRule()
    phase = PhaseRef(id="na_metal", element_system=("Na",))
    ctx = SynthesisContext(atmosphere="O2")
    assert rule.score(phase, ctx).score < 1.0


def test_alkali_metal_in_air_demotes_with_whitespace_element_system():
    # 【F10】: element_system 要素も formula 同様に strip してから照合し、" Li" でも降格する。
    rule = AlkaliMetalInAirRule()
    phase = PhaseRef(id="li_metal", element_system=(" Li",))
    ctx = SynthesisContext(atmosphere="air")
    assert rule.score(phase, ctx).score < 1.0


@pytest.mark.parametrize("metal", ["Li", "Na", "K", "Rb", "Cs"])
def test_alkali_metal_in_air_all_five_metals(metal):
    # 【目的】: Li/Na/K/Rb/Cs すべて大気下単体で降格 (REQ-017) 🔵
    rule = AlkaliMetalInAirRule()
    result = rule.score(PhaseRef(id=metal, formula=metal), SynthesisContext(atmosphere="air"))
    assert result.score < 1.0


def test_alkali_metal_inert_atmosphere_no_demotion():
    # 【目的】: 不活性雰囲気 (Ar) では単体アルカリ金属でも score=1.0 (降格なし) 🔵
    rule = AlkaliMetalInAirRule()
    phase = PhaseRef(id="li_metal", formula="Li")
    result = rule.score(phase, SynthesisContext(atmosphere="Ar"))
    assert result.score == pytest.approx(1.0)  # 【確認】: 降格なし 🔵


def test_alkali_metal_none_atmosphere_no_demotion():
    # 【目的】: atmosphere None では降格しない (酸化性でない) 🔵
    rule = AlkaliMetalInAirRule()
    result = rule.score(PhaseRef(id="li", formula="Li"), SynthesisContext())
    assert result.score == pytest.approx(1.0)


def test_non_alkali_compound_in_air_no_demotion():
    # 【目的】: 大気下でも非該当 (化合物/非アルカリ) は score=1.0 (TC-406-02) 🔵
    rule = AlkaliMetalInAirRule()
    # 化合物 (単体でない) は降格しない
    compound = PhaseRef(id="lfp", formula="LiFePO4", element_system=("Li", "Fe", "P", "O"))
    assert rule.score(compound, SynthesisContext(atmosphere="air")).score == pytest.approx(1.0)
    # 非アルカリ単体も降格しない
    fe = PhaseRef(id="fe", formula="Fe")
    assert rule.score(fe, SynthesisContext(atmosphere="air")).score == pytest.approx(1.0)


def test_alkali_rule_score_is_deterministic():
    # 【目的】: 同一入力で同一結果 (決定論・ビット同一) 🔵
    rule = AlkaliMetalInAirRule()
    phase = PhaseRef(id="li", formula="Li")
    ctx = SynthesisContext(atmosphere="air")
    assert rule.score(phase, ctx) == rule.score(phase, ctx)


# ---------------------------------------------------------------------------
# 5. combine_plausibility — 重み付き幾何平均 (TC-406-03 / REQ-018)
# ---------------------------------------------------------------------------


def test_combine_equal_weight_geometric_mean():
    # 【目的】: 等重み既定で幾何平均を計算する (TC-406-03/REQ-018) 🔵
    results = [
        PlausibilityResult(score=0.4, rationale="a", source="mod_a"),
        PlausibilityResult(score=0.9, rationale="b", source="mod_b"),
    ]
    combined = combine_plausibility(results)
    assert combined.score == pytest.approx(math.sqrt(0.4 * 0.9))  # 【確認】: 幾何平均 🔵


def test_combine_single_module_returns_its_score():
    # 【目的】: 単一モジュールは自身のスコアをそのまま返す 🔵
    combined = combine_plausibility([PlausibilityResult(score=0.3, rationale="a", source="mod_a")])
    assert combined.score == pytest.approx(0.3)


def test_combine_weighted_geometric_mean():
    # 【目的】: weights 指定で重み付き幾何平均 s=Π s_i^(w_i/Σw) (REQ-018) 🔵
    results = [
        PlausibilityResult(score=0.2, rationale="a", source="mod_a"),
        PlausibilityResult(score=0.8, rationale="b", source="mod_b"),
    ]
    weights = {"mod_a": 3.0, "mod_b": 1.0}
    combined = combine_plausibility(results, weights=weights)
    expected = (0.2 ** (3.0 / 4.0)) * (0.8 ** (1.0 / 4.0))
    assert combined.score == pytest.approx(expected)  # 【確認】: 重み付き幾何平均 🔵


def test_combine_unspecified_weight_defaults_to_equal():
    # 【目的】: weights で未指定の module は等重み (1.0) として扱う 🔵
    results = [
        PlausibilityResult(score=0.2, rationale="a", source="mod_a"),
        PlausibilityResult(score=0.8, rationale="b", source="mod_b"),
    ]
    # mod_b を未指定 → 1.0。mod_a=3.0 → 上と同じ結果
    combined = combine_plausibility(results, weights={"mod_a": 3.0})
    expected = (0.2 ** (3.0 / 4.0)) * (0.8 ** (1.0 / 4.0))
    assert combined.score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# 6. combine_plausibility — score=0 伝播 (TC-406-06 / EDGE-007)
# ---------------------------------------------------------------------------


def test_combine_zero_score_propagates_to_zero():
    # 【目的】: 1 モジュールが score=0 なら合成 0 へ伝播 (降格伝播・除外しない, EDGE-007) 🔵
    results = [
        PlausibilityResult(score=0.0, rationale="hard-fail", source="mod_a"),
        PlausibilityResult(score=0.9, rationale="ok", source="mod_b"),
    ]
    combined = combine_plausibility(results)
    assert combined.score == pytest.approx(0.0)  # 【確認】: 0 伝播 🔵
    # 【確認】: 除外はしない — 両モジュールが source に残る 🔵
    assert "mod_a" in combined.source
    assert "mod_b" in combined.source


def test_combine_zero_score_propagates_with_weights():
    # 【目的】: 重み付きでも score=0 は 0 へ伝播 (0^正の指数=0) 🔵
    results = [
        PlausibilityResult(score=0.0, rationale="a", source="mod_a"),
        PlausibilityResult(score=0.5, rationale="b", source="mod_b"),
    ]
    combined = combine_plausibility(results, weights={"mod_a": 0.1, "mod_b": 10.0})
    assert combined.score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# 7. combine_plausibility — 空入力 (REQ-105)
# ---------------------------------------------------------------------------


def test_combine_empty_returns_one():
    # 【目的】: results 空なら score=1.0 (降格なし, REQ-105 素通し) 🔵
    combined = combine_plausibility([])
    assert combined.score == pytest.approx(1.0)  # 【確認】: 素通し 🔵


# ---------------------------------------------------------------------------
# 8. combine_plausibility — source 昇順連結 / 決定論 (REQ-402)
# ---------------------------------------------------------------------------


def test_combine_source_is_ascending_join_deterministic():
    # 【目的】: source は寄与 module id を昇順連結し決定論 (REQ-402) 🔵
    # 入力順を逆にしても source は module id 昇順で同一
    forward = combine_plausibility(
        [
            PlausibilityResult(score=0.9, rationale="a", source="alpha"),
            PlausibilityResult(score=0.8, rationale="b", source="beta"),
            PlausibilityResult(score=0.7, rationale="c", source="gamma"),
        ]
    )
    reverse = combine_plausibility(
        [
            PlausibilityResult(score=0.7, rationale="c", source="gamma"),
            PlausibilityResult(score=0.8, rationale="b", source="beta"),
            PlausibilityResult(score=0.9, rationale="a", source="alpha"),
        ]
    )
    assert forward.source == reverse.source  # 【確認】: 入力順非依存 (決定論) 🔵
    # 昇順連結: source 中に alpha < beta < gamma の順で現れる
    assert forward.source.index("alpha") < forward.source.index("beta") < forward.source.index("gamma")
    # 【確認】: score も入力順非依存でビット同一 🔵
    assert forward.score == reverse.score


def test_combine_result_score_and_rationale_deterministic():
    # 【目的】: 同一入力で score/rationale/source すべてビット同一 🔵
    results = [
        PlausibilityResult(score=0.5, rationale="a", source="mod_a"),
        PlausibilityResult(score=0.6, rationale="b", source="mod_b"),
    ]
    assert combine_plausibility(results) == combine_plausibility(results)
