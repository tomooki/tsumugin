from __future__ import annotations

import numpy as np

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.pipeline import analyze_single_pattern


def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


def _phase(a: float, scale: float, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def test_ranks_two_candidate_sets():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = (_phase(5.0, 2.0),)
    y = backend.simulate(truth, tt)

    good = (_phase(5.02, 1.0),)  # correct structure, off initial values
    bad = (_phase(4.5, 1.0),)  # wrong lattice, cannot fit
    result = analyze_single_pattern(tt, y, [good, bad], backend=backend)

    assert len(result.ranked) == 2
    probs = [r.probability for r in result.ranked]
    assert probs == sorted(probs, reverse=True)  # descending


def test_true_model_ranks_first():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = (_phase(5.0, 2.0),)
    y = backend.simulate(truth, tt)

    good = (_phase(5.02, 1.0),)
    bad = (_phase(6.0, 1.0),)  # lattice far outside capture range, cannot fit
    result = analyze_single_pattern(tt, y, [good, bad], backend=backend)
    top = result.ranked[0]
    assert top.hypothesis.phases[0].lattice.a < 5.1  # the "good" candidate won


def test_ids_consistent_between_reports_and_ranked():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    y = backend.simulate((_phase(5.0, 1.0),), tt)
    result = analyze_single_pattern(
        tt, y, [(_phase(5.0, 1.0),), (_phase(5.0, 1.5),)], backend=backend
    )
    ranked_ids = {r.hypothesis.id for r in result.ranked}
    assert ranked_ids == set(result.reports.keys())
    assert all(rid.startswith("hyp-") for rid in ranked_ids)


def test_ledger_verifies_and_revertible():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    y = backend.simulate((_phase(5.0, 2.0),), tt)
    result = analyze_single_pattern(tt, y, [(_phase(5.02, 1.0),)], backend=backend)
    assert result.ledger.verify()
    assert len(result.snapshots.snapshots) > 0
    first = result.snapshots.snapshots[0]
    reverted = result.snapshots.revert(first.id)
    assert reverted == first.phases


def test_deterministic():
    tt = _grid()

    def once():
        backend = SimulatedBackend(peak_fwhm=0.2)
        y = backend.simulate((_phase(5.0, 2.0),), tt)
        res = analyze_single_pattern(tt, y, [(_phase(5.02, 1.0),)], backend=backend)
        return [(r.hypothesis.id, r.evidence.value, r.probability) for r in res.ranked]

    assert once() == once()


def test_empty_candidates_returns_empty_ranked():
    backend = SimulatedBackend()
    tt = _grid()
    y = np.zeros_like(tt)
    result = analyze_single_pattern(tt, y, [], backend=backend)
    assert result.ranked == ()
