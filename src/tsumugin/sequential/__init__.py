"""sequential/ パッケージ (時系列逐次解析基盤)。

TASK-0015 では時系列フレーム列を保持する ``FrameSeries`` と、複合指標 changepoint を判定する
純関数 ``detect_changepoint`` (と設定/結果の値オブジェクト) を提供する。
"""

from __future__ import annotations

from .changepoint import ChangepointConfig, ChangepointSignal, detect_changepoint
from .lifecycle import LifecycleConfig, LifecycleTracker
from .series import FrameSeries
from .trajectory import FrameRecord, Trajectory

__all__ = [
    "ChangepointConfig",
    "ChangepointSignal",
    "FrameRecord",
    "FrameSeries",
    "LifecycleConfig",
    "LifecycleTracker",
    "Trajectory",
    "detect_changepoint",
]
