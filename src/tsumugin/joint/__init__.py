"""joint 精密化サブパッケージ (M4 / REQ-004〜009/301)。

型・重み解決 (TASK-0038) に加え、joint 精密化エンジン (TASK-0039) を提供する。
トップレベル ``tsumugin`` __all__ への統合は TASK-0046。
"""

from __future__ import annotations

from .engine import refine_joint, refine_joint_detailed
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
    "refine_joint",
    "refine_joint_detailed",
]
