"""化学的妥当性評価の抽象境界 (M4 / REQ-015/016 / FR-412)。

合成文脈 (``SynthesisContext``)・評価結果 (``PlausibilityResult``) と、外部モジュール
(reaction network / 熱力学 / LLM 判断) が将来準拠する ``ChemPlausibility`` Protocol を提供する。
スコアは [0,1] で小さいほど非妥当。降格のみに使い候補除外はしない (Dara 教訓)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..model.phase import PhaseRef


@dataclass(frozen=True)
class SynthesisContext:
    """合成文脈: 元素系/前駆体/雰囲気/温度履歴/電気化学窓。🔵 REQ-016/FR-412"""

    element_system: tuple[str, ...] = ()  # 【元素系】 🔵
    precursors: tuple[str, ...] = ()  # 【前駆体】 🔵
    atmosphere: str | None = None  # 【雰囲気】: 例 "air"/"Ar"/"N2" 🔵
    temperature_history_c: tuple[float, ...] = ()  # 【温度履歴 (℃)】 🔵
    electrochemical_window_v: tuple[float, float] | None = None  # 【電気化学窓 (V)】 🔵


@dataclass(frozen=True)
class PlausibilityResult:
    """化学的妥当性の評価結果。🔵 REQ-015/FR-412

    score は [0,1]・小さいほど非妥当。source は評価モジュール識別 (module id) で
    合成順の決定論キーにも使う (REQ-402)。
    """

    score: float  # 【妥当性スコア [0,1]・小さいほど非妥当】 🔵 REQ-015
    rationale: str  # 【判断根拠】 🔵
    source: str  # 【評価モジュール識別 (module id)】 🔵 REQ-015/402


@runtime_checkable
class ChemPlausibility(Protocol):
    """化学的妥当性評価の Protocol 境界。🔵 REQ-015/FR-412

    外部モジュール (reaction network / 熱力学 / LLM 判断) は本 IF に準拠して将来接続する。
    """

    name: str  # 【module id (合成順の決定論キー)】 🔵 REQ-402

    def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult:
        ...
