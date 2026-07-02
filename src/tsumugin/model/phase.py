"""相・格子データモデル (仕様 §4 PhaseInstance / LatticeParams)。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Mapping


@dataclass(frozen=True)
class LatticeParams:
    """格子定数 (±σ)。角はすべて度。"""

    a: float
    b: float
    c: float
    alpha: float = 90.0
    beta: float = 90.0
    gamma: float = 90.0
    sigma: Mapping[str, float] = field(default_factory=dict)

    def volume(self) -> float:
        """一般三斜格子の単位胞体積 (Å³)。"""
        ca = math.cos(math.radians(self.alpha))
        cb = math.cos(math.radians(self.beta))
        cg = math.cos(math.radians(self.gamma))
        factor = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
        # 数値誤差で僅かに負へ落ちる縮退ケースを 0 にクランプ
        factor = max(factor, 0.0)
        return self.a * self.b * self.c * math.sqrt(factor)


@dataclass(frozen=True)
class PhaseInstance:
    """1 つの相インスタンス。更新は with_updates による非破壊生成のみ (P2)。"""

    phase_ref: str
    lattice: LatticeParams
    scale: float
    wt_frac: float | None = None
    occupancies: Mapping[str, float] = field(default_factory=dict)

    def with_updates(self, **changes) -> "PhaseInstance":
        """変更を適用した新インスタンスを返す。自身は不変。"""
        return replace(self, **changes)
