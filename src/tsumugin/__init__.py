"""Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム (PoC / M0)."""

from __future__ import annotations

from .backends.base import RefinementBackend, RefinementModel, RefinementResult
from .backends.simulated import SimulatedBackend
from .evidence.ic import AICBackend, BICBackend
from .evidence.ranking import RankedHypothesis, rank
from .model import (
    Hypothesis,
    LatticeParams,
    PhaseInstance,
    Project,
    RefinementMetrics,
)
from .pipeline import AnalysisResult, analyze_single_pattern
from .refinement.staged import RefinementReport, StagedRefinementEngine
from .store.ledger import Ledger
from .store.snapshot import SnapshotStore

__version__ = "0.1.0"

__all__ = [
    "AICBackend",
    "AnalysisResult",
    "BICBackend",
    "Hypothesis",
    "LatticeParams",
    "Ledger",
    "PhaseInstance",
    "Project",
    "RankedHypothesis",
    "RefinementBackend",
    "RefinementMetrics",
    "RefinementModel",
    "RefinementReport",
    "RefinementResult",
    "SimulatedBackend",
    "SnapshotStore",
    "StagedRefinementEngine",
    "analyze_single_pattern",
    "rank",
]
