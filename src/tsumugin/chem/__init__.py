"""化学的妥当性評価サブパッケージ (M4 / REQ-015〜018/105 / EDGE-007)。

型・Protocol 境界 (``base``)、v1 最小ルール (``rules``)、複数スコアの合成 (``compose``) を
提供する。トップレベル ``tsumugin`` __all__ への統合は TASK-0046。
"""

from __future__ import annotations

from .base import ChemPlausibility, PlausibilityResult, SynthesisContext
from .compose import combine_plausibility
from .rules import AlkaliMetalInAirRule

__all__ = [
    "AlkaliMetalInAirRule",
    "ChemPlausibility",
    "PlausibilityResult",
    "SynthesisContext",
    "combine_plausibility",
]
