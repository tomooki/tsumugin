from __future__ import annotations

import numpy as np

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.refinement.staged import (
    DEFAULT_STAGE_TEMPLATE,
    StagedRefinementEngine,
)
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore


def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


def _engine(backend, **kw) -> StagedRefinementEngine:
    return StagedRefinementEngine(backend, SnapshotStore(Ledger()), Ledger(), **kw)


# --- test doubles -----------------------------------------------------------


class RecordingBackend:
    """呼び出しごとに free_params を記録し、解放数に応じて rwp を下げるダブル。"""

    name = "recording"

    def __init__(self):
        self.calls: list[frozenset[str]] = []

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        self.calls.append(frozenset(model.free_params))
        n = len(model.free_params)
        return RefinementResult(
            phases=model.phases,
            chi2=100.0 - n,
            rwp=max(10.0 - n, 0.0),
            n_obs=100,
            n_params=n,
            converged=True,
            n_cycles=1,
            free_params=frozenset(model.free_params),
        )


class WorseningBackend:
    """指定した解放数の段でだけ rwp を悪化させるダブル (chi2 は発散させない)。"""

    name = "worsening"

    def __init__(self, worsen_stage_size: int):
        self.worsen_stage_size = worsen_stage_size

    def refine(self, model, *, max_cycles=20):
        n = len(model.free_params)
        rwp = 20.0 if n == self.worsen_stage_size else max(10.0 - n, 0.1)
        return RefinementResult(
            phases=model.phases, chi2=5.0, rwp=rwp, n_obs=100, n_params=n,
            converged=True, n_cycles=1, free_params=frozenset(model.free_params),
        )


class DivergingBackend:
    """初回のみ良好、以降は chi2 を発散させて guard を必ず発動させるダブル。"""

    name = "diverging"

    def __init__(self):
        self.first = True

    def refine(self, model, *, max_cycles=20):
        if self.first:
            self.first = False
            return RefinementResult(
                phases=model.phases, chi2=10.0, rwp=5.0, n_obs=100,
                n_params=len(model.free_params), converged=True, n_cycles=1,
                free_params=frozenset(model.free_params),
            )
        return RefinementResult(
            phases=model.phases, chi2=1000.0, rwp=50.0, n_obs=100,
            n_params=len(model.free_params), converged=True, n_cycles=1,
            free_params=frozenset(model.free_params),
        )


# --- tests ------------------------------------------------------------------


def test_clean_synthetic_all_stages_accepted():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = PhaseInstance("P", LatticeParams(5.0, 5.0, 5.0), 2.0)
    y = backend.simulate((truth,), tt)
    start = PhaseInstance("P", LatticeParams(5.02, 5.0, 5.0), 1.0)

    initial_rwp = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    ).rwp

    report = _engine(backend).run((start,), tt, y)
    assert report.escalated is False
    assert all(o.accepted for o in report.stage_outcomes)
    assert report.metrics.rwp < initial_rwp


def test_free_params_accumulate_across_stages():
    backend = RecordingBackend()
    tt = _grid()
    start = PhaseInstance("P", LatticeParams(5.0, 5.0, 5.0), 1.0)
    _engine(backend).run((start,), tt, np.zeros_like(tt))
    # by the lattice stage, scale must still be free (accumulation)
    lattice_call = next(c for c in backend.calls if "phase0.lattice.a" in c)
    assert "phase0.scale" in lattice_call


def test_worsening_stage_is_fixed_back():
    # scale_bg frees 1 param; make that stage worsen -> fixed back
    # after scale_bg (1) + lattice_zero (a,b,c) the free count is 4
    backend = WorseningBackend(worsen_stage_size=4)
    tt = _grid()
    start = PhaseInstance("P", LatticeParams(5.0, 5.0, 5.0), 1.0)
    report = _engine(backend).run((start,), tt, np.zeros_like(tt))
    lattice_outcome = next(
        o for o in report.stage_outcomes if o.stage == "lattice_zero"
    )
    assert lattice_outcome.accepted is False


def test_guard_violation_triggers_rollback_and_escalation():
    backend = DivergingBackend()
    tt = _grid()
    start = PhaseInstance("P", LatticeParams(5.0, 5.0, 5.0), 1.0)
    ledger = Ledger()
    engine = StagedRefinementEngine(
        backend, SnapshotStore(ledger), ledger, max_retries=3
    )
    report = engine.run((start,), tt, np.zeros_like(tt))
    kinds = [e.kind for e in ledger.entries]
    assert report.escalated is True
    assert "guard_violation" in kinds
    assert "rollback" in kinds
    assert "escalate" in kinds


def test_snapshots_and_ledger_recorded_per_stage():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = PhaseInstance("P", LatticeParams(5.0, 5.0, 5.0), 2.0)
    y = backend.simulate((truth,), tt)
    start = PhaseInstance("P", LatticeParams(5.02, 5.0, 5.0), 1.0)
    store = SnapshotStore(Ledger())
    ledger = Ledger()
    engine = StagedRefinementEngine(backend, store, ledger)
    engine.run((start,), tt, y)
    assert len(store.snapshots) >= len(DEFAULT_STAGE_TEMPLATE)
    assert "stage_refine" in [e.kind for e in ledger.entries]
    assert ledger.verify()


def test_deterministic_report():
    tt = _grid()
    truth = PhaseInstance("P", LatticeParams(5.0, 5.0, 5.0), 2.0)
    start = PhaseInstance("P", LatticeParams(5.02, 5.0, 5.0), 1.0)

    def once():
        backend = SimulatedBackend(peak_fwhm=0.2)
        y = backend.simulate((truth,), tt)
        return _engine(backend).run((start,), tt, y)

    r1, r2 = once(), once()
    assert r1.metrics == r2.metrics
    assert r1.final_phases == r2.final_phases
    assert [o.accepted for o in r1.stage_outcomes] == [o.accepted for o in r2.stage_outcomes]
