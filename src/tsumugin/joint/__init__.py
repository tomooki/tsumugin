"""joint 精密化サブパッケージ (M4 / REQ-004〜012/301)。

型・重み解決 (TASK-0038)、joint 精密化エンジン (TASK-0039) に加え、コントラスト駆動の
占有率解放推奨 (TASK-0040) を提供する。トップレベル ``tsumugin`` __all__ への統合は TASK-0046。
"""

from __future__ import annotations

from .contrast import (
    NEUTRON_B_TABLE,
    XRAY_Z_TABLE,
    ContrastConfig,
    OccupancyReleaseRecommendation,
    recommend_occupancy_release,
)
from .engine import refine_joint, refine_joint_detailed
from .model import (
    JointHistogram,
    JointRefinementModel,
    JointRefinementResult,
    PerHistogramMetrics,
)
from .verification import JointVerificationResult, verify_survivors
from .weights import HistogramWeighting

__all__ = [
    "NEUTRON_B_TABLE",
    "XRAY_Z_TABLE",
    "ContrastConfig",
    "HistogramWeighting",
    "JointHistogram",
    "JointRefinementModel",
    "JointRefinementResult",
    "JointVerificationResult",
    "OccupancyReleaseRecommendation",
    "PerHistogramMetrics",
    "recommend_occupancy_release",
    "refine_joint",
    "refine_joint_detailed",
    "verify_survivors",
]
