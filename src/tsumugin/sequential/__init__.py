"""sequential/ パッケージ (時系列逐次解析基盤)。

TASK-0015 では時系列フレーム列を保持する ``FrameSeries`` と、複合指標 changepoint を判定する
純関数 ``detect_changepoint`` (と設定/結果の値オブジェクト) を提供する。
"""

from __future__ import annotations

from .changepoint import ChangepointConfig, ChangepointSignal, detect_changepoint
from .series import FrameSeries

__all__ = [
    "ChangepointConfig",
    "ChangepointSignal",
    "FrameSeries",
    "detect_changepoint",
]
