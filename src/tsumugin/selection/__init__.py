"""最終選択エンジン (M2)。

エスカレーション検出 (detect_escalations) と Review Queue (ReviewQueue/ReviewItem) を提供する。
🔵 REQ-015 / FR-403
"""

from __future__ import annotations

from .engine import detect_escalations
from .review_queue import EscalationReason, ReviewItem, ReviewQueue

__all__ = [
    "EscalationReason",
    "ReviewItem",
    "ReviewQueue",
    "detect_escalations",
]
