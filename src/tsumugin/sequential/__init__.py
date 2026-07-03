"""sequential/ パッケージ (時系列逐次解析基盤)。

TASK-0015 では時系列フレーム列を保持する ``FrameSeries`` と、複合指標 changepoint を判定する
純関数 ``detect_changepoint`` (と設定/結果の値オブジェクト) を提供する。
"""

from __future__ import annotations

from .changepoint import ChangepointConfig, ChangepointSignal, detect_changepoint
from .engine import SequentialConfig, SequentialEngine, SequentialResult
from .lifecycle import LifecycleConfig, LifecycleTracker
from .series import FrameSeries
from .thermal import (
    ThermalBaseline,
    TransitionEstimate,
    estimate_transition,
    fit_thermal_baseline,
)
from .trajectory import FrameRecord, Trajectory

__all__ = [
    "ChangepointConfig",
    "ChangepointSignal",
    "FrameRecord",
    "FrameSeries",
    "LifecycleConfig",
    "LifecycleTracker",
    "SequentialConfig",
    "SequentialEngine",
    "SequentialResult",
    "ThermalBaseline",
    "Trajectory",
    "TransitionEstimate",
    "detect_changepoint",
    "estimate_transition",
    "fit_thermal_baseline",
]
