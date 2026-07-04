"""joint 精密化サブパッケージ (M4 / REQ-004〜009/301)。

型と重み解決のみを提供する段階 (engine はまだ実装しない, TASK-0038)。
トップレベル ``tsumugin`` __all__ への統合は TASK-0046。
"""

from __future__ import annotations

from .model import (
    JointHistogram,
    JointRefinementModel,
    JointRefinementResult,
    PerHistogramMetrics,
)
from .weights import HistogramWeighting

__all__ = [
    "HistogramWeighting",
    "JointHistogram",
    "JointRefinementModel",
    "JointRefinementResult",
    "PerHistogramMetrics",
]
