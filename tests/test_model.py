from __future__ import annotations

import math

import pytest
from dataclasses import FrozenInstanceError

from tsumugin.errors import TsumuginError, GuardrailError, EscalationRequired
from tsumugin.model import (
    Dataset,
    Frame,
    HistogramRef,
    Hypothesis,
    LatticeParams,
    PhaseInstance,
    Project,
    RefinementMetrics,
)


def test_cubic_volume():
    lat = LatticeParams(a=5.0, b=5.0, c=5.0)
    assert lat.volume() == pytest.approx(125.0)


def test_triclinic_volume_matches_general_formula():
    a, b, c = 4.0, 5.0, 6.0
    alpha, beta, gamma = 80.0, 85.0, 95.0
    lat = LatticeParams(a=a, b=b, c=c, alpha=alpha, beta=beta, gamma=gamma)
    ca, cb, cg = (math.cos(math.radians(x)) for x in (alpha, beta, gamma))
    expected = a * b * c * math.sqrt(
        1 - ca**2 - cb**2 - cg**2 + 2 * ca * cb * cg
    )
    assert lat.volume() == pytest.approx(expected)


def test_phase_with_updates_is_nondestructive():
    p = PhaseInstance(phase_ref="Fe2O3", lattice=LatticeParams(5, 5, 5), scale=1.0)
    p2 = p.with_updates(scale=2.0)
    assert p2.scale == 2.0
    assert p.scale == 1.0  # original unchanged (P2)
    assert p2.phase_ref == "Fe2O3"


def test_frozen_assignment_raises():
    p = PhaseInstance(phase_ref="x", lattice=LatticeParams(5, 5, 5), scale=1.0)
    with pytest.raises(FrozenInstanceError):
        p.scale = 3.0  # type: ignore[misc]


def test_defaults():
    h = Hypothesis(id="h1", phases=())
    assert h.status == "candidate"
    proj = Project(id="p1")
    assert proj.final_selection_mode == "agent"


def test_exception_hierarchy():
    assert issubclass(GuardrailError, TsumuginError)
    assert issubclass(EscalationRequired, TsumuginError)


def test_metrics_and_containers_construct():
    m = RefinementMetrics(rwp=5.0, gof=1.2, chi2=100.0, n_obs=1000, n_params=5)
    assert m.evidence == {}
    hist = HistogramRef(probe="xray", data_ref="d.xy")
    frame = Frame(id="f0", index=0, histograms=(hist,))
    ds = Dataset(id="ds0", kind="single", frames=(frame,))
    proj = Project(id="p", datasets=(ds,))
    assert proj.datasets[0].frames[0].histograms[0].probe == "xray"
