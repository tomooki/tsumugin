"""Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム (PoC / M0 + M1)."""

from __future__ import annotations

from .backends.base import RefinementBackend, RefinementModel, RefinementResult
from .backends.simulated import SimulatedBackend
from .evidence.ic import AICBackend, BICBackend
from .evidence.ranking import RankedHypothesis, rank
from .export import export_gpx
from .model import (
    Hypothesis,
    LatticeParams,
    PhaseInstance,
    Project,
    RefinementMetrics,
)
from .pipeline import AnalysisResult, analyze_single_pattern
from .refinement.staged import RefinementReport, StagedRefinementEngine
from .search import (
    HypothesisTreeSearch,
    Peak,
    PhaseCandidate,
    SearchConfig,
    SearchResult,
    UnmatchedPeakReport,
)
from .store.ledger import Ledger
from .store.snapshot import SnapshotStore

__version__ = "0.1.0"

# アルファベット昇順を維持する (公開面の一貫性。test_m1_symbols_in_dunder_all_and_sorted が固定)。
__all__ = [
    "AICBackend",
    "AnalysisResult",
    "BICBackend",
    "Hypothesis",
    "HypothesisTreeSearch",
    "LatticeParams",
    "Ledger",
    "Peak",
    "PhaseCandidate",
    "PhaseInstance",
    "Project",
    "RankedHypothesis",
    "RefinementBackend",
    "RefinementMetrics",
    "RefinementModel",
    "RefinementReport",
    "RefinementResult",
    "SearchConfig",
    "SearchResult",
    "SimulatedBackend",
    "SnapshotStore",
    "StagedRefinementEngine",
    "UnmatchedPeakReport",
    "analyze_single_pattern",
    "export_gpx",
    "rank",
]
