"""v1 最小の化学的妥当性ルール (M4 / REQ-017 / FR-412)。

``AlkaliMetalInAirRule``: 酸化性雰囲気 (air/O2 等) 下での単体アルカリ金属 (Li/Na/K/Rb/Cs)
を降格する。非該当は score=1.0 (降格なし)。``ChemPlausibility`` Protocol に構造的に適合する。
"""

from __future__ import annotations

from ..model.phase import PhaseRef
from .base import PlausibilityResult, SynthesisContext

# 【単体判定対象】: アルカリ金属の元素記号 🔵 REQ-017
_ALKALI_METALS: frozenset[str] = frozenset({"Li", "Na", "K", "Rb", "Cs"})

# 【酸化性雰囲気】: 大文字小文字を無視して照合するキーワード (完全一致) 🔵
_OXIDIZING_ATMOSPHERES: frozenset[str] = frozenset({"air", "o2", "o₂", "oxygen"})

# 【降格スコア】: 大気下単体アルカリ金属は強く降格する (0 でなく低スコア=完全除外しない) 🔵
_DEMOTED_SCORE: float = 0.1


def _is_oxidizing(atmosphere: str | None) -> bool:
    """雰囲気が酸化性 (air/O2 等) かを判定する。None/未知は非酸化性扱い。🔵"""
    if atmosphere is None:
        return False
    return atmosphere.strip().lower() in _OXIDIZING_ATMOSPHERES


def _elemental_alkali_symbol(phase: PhaseRef) -> str | None:
    """phase が単体アルカリ金属なら元素記号を、そうでなければ None を返す。🔵

    判定は決定論的に PhaseRef の以下から行う (formula 優先):
    - ``formula``: 記号 1 つ (例 "Li")。単一のアルカリ金属記号なら単体とみなす。
    - ``element_system``: formula が単体判定に使えないとき、要素 1 つでアルカリ金属なら単体。
    化合物 (複数元素) は単体でないので None を返す。
    """
    # formula が単一のアルカリ金属記号なら単体 (例 "Li"、"Na")
    formula = (phase.formula or "").strip()
    if formula in _ALKALI_METALS:
        return formula

    # formula が単体判定に使えない場合のみ element_system で補完する。
    # formula が非空 (=何らかの組成が示されている) なら単体でないと判断し降格しない。
    if not formula and len(phase.element_system) == 1:
        # 【trim (F10)】: element_system 要素も formula 同様に前後空白を除去してから照合し、
        #   " Li" のような空白混じり記号でも単体判定を成立させる (照合の一貫性) 🔵
        symbol = phase.element_system[0].strip()
        if symbol in _ALKALI_METALS:
            return symbol
    return None


class AlkaliMetalInAirRule:
    """v1 最小ルール: 大気下での単体アルカリ金属を降格する。🔵 REQ-017/FR-412

    context.atmosphere が酸化性 (air/O2) かつ phase が単体アルカリ金属 (Li/Na/K/Rb/Cs) のとき
    低スコアを返す。非該当は score=1.0 (降格なし)。name="alkali_metal_in_air"。
    ``ChemPlausibility`` Protocol に構造的に適合する。
    """

    name: str = "alkali_metal_in_air"

    def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult:
        """大気下単体アルカリ金属を降格。非該当は score=1.0。🔵 REQ-017"""
        symbol = _elemental_alkali_symbol(phase)
        if symbol is not None and _is_oxidizing(context.atmosphere):
            return PlausibilityResult(
                score=_DEMOTED_SCORE,
                rationale=(
                    f"単体アルカリ金属 {symbol} は酸化性雰囲気 "
                    f"({context.atmosphere}) 下で不安定 (酸化・水和しやすい) のため降格"
                ),
                source=self.name,
            )
        return PlausibilityResult(
            score=1.0,
            rationale="大気下単体アルカリ金属の条件に非該当 (降格なし)",
            source=self.name,
        )
