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
class PhaseLifecycle:
    """相ライフサイクル値オブジェクト (REQ-004 / interfaces.py L31-37)。

    【機能概要】: 相がいつ出現(birth)/消滅(death)したかと存在確信度を保持する不変値オブジェクト。
    【実装方針】: 全フィールド既定値付きの frozen dataclass とし、器のみを提供 (算出は後続 LifecycleTracker スコープ)。
    【テスト対応】: N-01/N-02/E-01/B-01/B-05 を通す。
    🔵 信頼性レベル: 要件定義 2.1 / interfaces.py L31-37 に依拠。
    """

    birth_frame: int | None = None  # 【出現フレーム】: 相が現れた frame index。未確定/未追跡は None
    death_frame: int | None = None  # 【消滅フレーム】: 相が消えた frame index。未消滅/未追跡は None
    confidence: float = 1.0  # 【存在確信度】: [0,1]。本タスクは既定 1.0 保持のみ (範囲検証は非スコープ)


@dataclass(frozen=True)
class PhaseInstance:
    """1 つの相インスタンス。更新は with_updates による非破壊生成のみ (P2)。"""

    phase_ref: str
    lattice: LatticeParams
    scale: float = 1.0  # 相スケール因子
    wt_frac: float | None = None
    occupancies: Mapping[str, float] = field(default_factory=dict)
    # 【追加フィールド】: 相ライフサイクル。末尾・既定 None で後方互換を保証 (REQ-404 非破壊追加) 🔵
    lifecycle: PhaseLifecycle | None = None

    def with_updates(self, **changes) -> "PhaseInstance":
        """変更を適用した新インスタンスを返す。自身は不変。"""
        return replace(self, **changes)
