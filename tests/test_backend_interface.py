from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.base import (
    RefinementBackend,
    RefinementModel,
    RefinementResult,
    param_name,
    parse_param,
)
from tsumugin.model import LatticeParams, PhaseInstance


def test_param_name_roundtrip():
    assert param_name(0, "scale") == "phase0.scale"
    assert parse_param("phase0.scale") == (0, "scale")


def test_parse_param_multi_dot():
    assert parse_param("phase2.lattice.a") == (2, "lattice.a")
    assert param_name(2, "lattice.a") == "phase2.lattice.a"


def test_model_and_result_are_frozen():
    m = RefinementModel(
        phases=(),
        free_params=frozenset(),
        two_theta=np.array([1.0, 2.0]),
        intensity=np.array([0.0, 0.0]),
    )
    with pytest.raises(FrozenInstanceError):
        m.free_params = frozenset({"x"})  # type: ignore[misc]

    r = RefinementResult(
        phases=(), chi2=1.0, rwp=2.0, n_obs=2, n_params=0, converged=True, n_cycles=1
    )
    with pytest.raises(FrozenInstanceError):
        r.chi2 = 5.0  # type: ignore[misc]


def test_protocol_is_runtime_checkable():
    class Dummy:
        name = "dummy"

        def refine(self, model, *, max_cycles=20):
            return RefinementResult(
                phases=model.phases,
                chi2=0.0,
                rwp=0.0,
                n_obs=len(model.intensity),
                n_params=len(model.free_params),
                converged=True,
                n_cycles=1,
            )

    assert isinstance(Dummy(), RefinementBackend)

    class NotABackend:
        pass

    assert not isinstance(NotABackend(), RefinementBackend)


def test_model_carries_phases():
    ph = PhaseInstance(phase_ref="a", lattice=LatticeParams(5, 5, 5), scale=1.0)
    m = RefinementModel(
        phases=(ph,),
        free_params=frozenset({"phase0.scale"}),
        two_theta=np.linspace(10, 20, 5),
        intensity=np.zeros(5),
    )
    assert m.phases[0].phase_ref == "a"
