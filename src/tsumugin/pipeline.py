"""単一パターン自動多相精密化パイプライン (M0 受け入れ機能)。

複数の候補相組合せを段階エンジンで精密化し、Evidence Engine でランキングして返す。
全過程は単一の追記専用 Ledger / SnapshotStore に記録され、任意時点へ revert できる。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping, Sequence

import numpy as np

from .backends.base import RefinementBackend
from .backends.simulated import SimulatedBackend
from .evidence.base import EvidenceBackend
from .evidence.ic import BICBackend
from .evidence.ranking import RankedHypothesis, rank
from .model import Hypothesis, PhaseInstance
from .refinement.staged import RefinementReport, StagedRefinementEngine
from .store.ledger import Ledger
from .store.snapshot import SnapshotStore


@dataclass(frozen=True)
class AnalysisResult:
    ranked: tuple[RankedHypothesis, ...]
    reports: Mapping[str, RefinementReport]
    ledger: Ledger
    snapshots: SnapshotStore


def analyze_single_pattern(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    candidate_phase_sets: Sequence[Sequence[PhaseInstance]],
    *,
    backend: RefinementBackend | None = None,
    evidence: EvidenceBackend | None = None,
    weights: np.ndarray | None = None,
) -> AnalysisResult:
    """候補ごとに段階精密化 → evidence 評価 → ランキング。"""
    backend = backend or SimulatedBackend()
    evidence = evidence or BICBackend()
    ledger = Ledger()
    store = SnapshotStore(ledger)

    reports: dict[str, RefinementReport] = {}
    hypotheses: list[Hypothesis] = []

    for i, phase_set in enumerate(candidate_phase_sets):
        hid = f"hyp-{i:04d}"
        engine = StagedRefinementEngine(backend, store, ledger)
        report = engine.run(tuple(phase_set), two_theta, intensity, weights=weights)
        reports[hid] = report

        ev = evidence.score(report.metrics)
        metrics = replace(report.metrics, evidence={ev.backend: ev.value})
        hypotheses.append(
            Hypothesis(
                id=hid,
                phases=report.final_phases,
                metrics=metrics,
                status="refined",
            )
        )
        ledger.append(
            "hypothesis_evaluated",
            {"id": hid, "backend": ev.backend, "evidence": ev.value, "rwp": metrics.rwp},
        )

    ranked = rank(hypotheses, evidence)
    ledger.append(
        "ranking",
        {"order": [r.hypothesis.id for r in ranked],
         "probabilities": [r.probability for r in ranked]},
    )
    return AnalysisResult(
        ranked=ranked, reports=reports, ledger=ledger, snapshots=store
    )
