"""MEM (Maximum Entropy Method) サブパッケージ (M5 / REQ-018/027〜031 / FR-601〜606)。

MEM ソルバの交換可能境界 (``MEMBackend`` Protocol) と結果型 (``MEMDensityMap`` /
``DensityCrossSection`` / ``BondPathDensity`` / ``MEMResult``) を提供する。実密度グリッドは
ファイル参照でメモリには要約統計のみ持ち、適用ガード警告は積むが仮説除外はしない
(Dara 教訓, REQ-031)。トップレベル ``tsumugin`` __all__ への統合は TASK-0058。
"""

from __future__ import annotations

from .base import (
    BondPathDensity,
    DensityCrossSection,
    MEMBackend,
    MEMDensityMap,
    MEMResult,
)

__all__ = [
    "BondPathDensity",
    "DensityCrossSection",
    "MEMBackend",
    "MEMDensityMap",
    "MEMResult",
]
