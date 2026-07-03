"""多仮説木探索 (FR-110〜117)。"""

from __future__ import annotations

from .clustering import (
    ClusterResult,
    PhaseCandidate,
    jaccard_clusters,
    jenks_breaks,
)
from .matcher import (
    MatchResult,
    UnmatchedPeakReport,
    match_score,
    unmatched_peaks,
)
from .peaks import Peak, find_peaks
from .pruning import dynamic_threshold
from .tree import HypothesisTreeSearch, SearchConfig, SearchResult

__all__: list[str] = [
    "ClusterResult",
    "HypothesisTreeSearch",
    "MatchResult",
    "Peak",
    "PhaseCandidate",
    "SearchConfig",
    "SearchResult",
    "UnmatchedPeakReport",
    "dynamic_threshold",
    "find_peaks",
    "jaccard_clusters",
    "jenks_breaks",
    "match_score",
    "unmatched_peaks",
]
