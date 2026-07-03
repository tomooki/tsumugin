from __future__ import annotations

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, param_name
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance


def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


def _count_local_maxima(y: np.ndarray, *, min_height: float) -> int:
    interior = (y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)
    return int(np.count_nonzero(interior))


def test_simulate_produces_one_maximum_per_in_range_reflection():
    backend = SimulatedBackend(peak_fwhm=0.2)
    phase = _phase(a=5.0)
    tt = _grid()
    y = backend.simulate((phase,), tt)
    positions = backend.peak_positions(phase, tt)
    assert len(positions) > 0
    peaks = _count_local_maxima(y, min_height=0.1 * y.max())
    assert peaks == len(positions)


def test_refine_scale_converges_to_truth():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=3.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert result.converged
    assert result.phases[0].scale == pytest.approx(3.0, rel=0.01)


def test_refine_lattice_reduces_chi2():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = backend.simulate((truth,), tt)

    # perturb only `a` (b, c already correct) so the true a is unambiguous
    start = PhaseInstance(
        phase_ref="P", lattice=LatticeParams(5.03, 5.0, 5.0), scale=1.0
    )
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    # chi2 before refinement
    before = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    ).chi2
    after = backend.refine(model)
    assert after.chi2 < before * 0.5
    assert after.phases[0].lattice.a == pytest.approx(5.0, abs=0.02)


def test_no_free_params_is_noop_converged():
    backend = SimulatedBackend()
    tt = _grid()
    phase = _phase()
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.converged
    assert result.n_cycles == 1
    assert result.n_params == 0


def test_unrecognized_free_params_are_ignored_in_param_count():
    backend = SimulatedBackend()
    tt = _grid()
    phase = _phase()
    y = backend.simulate((phase,), tt)
    # "profile" is not a physical parameter of the simulated model
    model = RefinementModel(
        phases=(phase,),
        free_params=frozenset({param_name(0, "scale"), param_name(0, "profile")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert result.n_params == 1  # only "scale" is recognized/optimized


def test_deterministic():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=2.5)
    y = backend.simulate((truth,), tt)
    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    r1 = backend.refine(model)
    r2 = backend.refine(model)
    assert r1.chi2 == r2.chi2
    assert r1.phases[0].scale == r2.phases[0].scale


def test_metrics_non_negative():
    backend = SimulatedBackend()
    tt = _grid()
    phase = _phase(scale=2.0)
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.rwp >= 0.0
    assert result.chi2 >= 0.0
