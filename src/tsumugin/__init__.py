"""Tsumugin — 多仮説・全自動 Rietveld 解析プラットフォーム (PoC / M0 + M1 + M2)."""

from __future__ import annotations

from .backends.base import RefinementBackend, RefinementModel, RefinementResult
from .backends.simulated import SimulatedBackend
from .evidence.ic import AICBackend, BICBackend
from .evidence.ranking import RankedHypothesis, rank
from .export import export_gpx
from .model import (
    ExternalChannel,
    Hypothesis,
    LatticeParams,
    PhaseInstance,
    PhaseLifecycle,
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
from .selection import (
    Decision,
    FinalSelectionEngine,
    ReviewItem,
    ReviewQueue,
    detect_escalations,
)
from .sequential import (
    ChangepointConfig,
    ChangepointSignal,
    FrameRecord,
    FrameSeries,
    LifecycleConfig,
    LifecycleTracker,
    SequentialConfig,
    SequentialEngine,
    SequentialResult,
    ThermalBaseline,
    Trajectory,
    TransitionEstimate,
    detect_changepoint,
    estimate_transition,
    fit_thermal_baseline,
)
from .store import (
    Ledger,
    PersistentLedger,
    PersistentSnapshotStore,
    SnapshotStore,
    phase_from_dict,
    phase_to_dict,
)

__version__ = "0.1.0"

# アルファベット昇順を維持する (公開面の一貫性。test_m1/m2_symbols_in_dunder_all_and_sorted が固定)。
__all__ = [
    "AICBackend",
    "AnalysisResult",
    "BICBackend",
    "ChangepointConfig",
    "ChangepointSignal",
    "Decision",
    "ExternalChannel",
    "FinalSelectionEngine",
    "FrameRecord",
    "FrameSeries",
    "Hypothesis",
    "HypothesisTreeSearch",
    "LatticeParams",
    "Ledger",
    "LifecycleConfig",
    "LifecycleTracker",
    "Peak",
    "PersistentLedger",
    "PersistentSnapshotStore",
    "PhaseCandidate",
    "PhaseInstance",
    "PhaseLifecycle",
    "Project",
    "RankedHypothesis",
    "RefinementBackend",
    "RefinementMetrics",
    "RefinementModel",
    "RefinementReport",
    "RefinementResult",
    "ReviewItem",
    "ReviewQueue",
    "SearchConfig",
    "SearchResult",
    "SequentialConfig",
    "SequentialEngine",
    "SequentialResult",
    "SimulatedBackend",
    "SnapshotStore",
    "StagedRefinementEngine",
    "ThermalBaseline",
    "Trajectory",
    "TransitionEstimate",
    "UnmatchedPeakReport",
    "analyze_single_pattern",
    "detect_changepoint",
    "detect_escalations",
    "estimate_transition",
    "export_gpx",
    "fit_thermal_baseline",
    "phase_from_dict",
    "phase_to_dict",
    "rank",
]
