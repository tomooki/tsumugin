"""Evidence Engine (FR-120)。"""

from __future__ import annotations

from .base import EvidenceBackend, EvidenceResult
from .ic import AICBackend, BICBackend
from .ranking import RankedHypothesis, rank

__all__ = [
    "AICBackend",
    "BICBackend",
    "EvidenceBackend",
    "EvidenceResult",
    "RankedHypothesis",
    "rank",
]
