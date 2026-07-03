from __future__ import annotations

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, param_name
from tsumugin.backends.gsasii import GSASIIBackend, gsasii_available
from tsumugin.errors import GSASUnavailableError
from tsumugin.model import LatticeParams, PhaseInstance


def _phase(a: float = 4.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(20.0, 80.0, 0.05)


def test_gsasii_available_returns_bool_without_raising():
    result = gsasii_available()
    assert isinstance(result, bool)


def test_backend_raises_when_unavailable():
    if gsasii_available():
        pytest.skip("GSAS-II is installed; unavailable path not exercised")
    with pytest.raises(GSASUnavailableError):
        GSASIIBackend()


@pytest.mark.gsas
def test_simulate_produces_nontrivial_pattern():
    backend = GSASIIBackend()
    tt = _grid()
    y = backend.simulate((_phase(a=4.0, scale=1.0),), tt)
    assert y.shape == tt.shape
    assert np.all(np.isfinite(y))
    # diffraction peaks rise well above the flat background
    assert y.max() > 5 * max(np.median(y), 1e-9)


@pytest.mark.gsas
def test_refine_noop_returns_metrics():
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=1.0)
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(phases=(truth,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.n_params == 0
    assert result.rwp >= 0.0
    assert result.n_obs == tt.size


@pytest.mark.gsas
def test_refine_scale_improves_fit():
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=2.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.0, scale=0.5)
    noop = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    fitted = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "scale")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert fitted.rwp < noop.rwp
    assert fitted.n_params >= 1
    assert fitted.phases[0].scale != start.scale  # scale actually moved


@pytest.mark.gsas
def test_refine_lattice_recovers_cell():
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=1.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.01, scale=1.0)  # slightly off
    fitted = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "lattice.a")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert fitted.phases[0].lattice.a == pytest.approx(4.0, abs=0.005)


@pytest.mark.gsas
def test_pipeline_ranks_hypotheses_on_gsasii_backend():
    """M0 受け入れ機能 (多仮説ランキング) が実バックエンドで動くことの契約。"""
    from tsumugin.pipeline import analyze_single_pattern

    backend = GSASIIBackend()
    tt = _grid()
    truth = (_phase(a=4.0, scale=2.0),)
    y = backend.simulate(truth, tt)

    good = (_phase(a=4.01, scale=1.0),)   # 正しい構造、初期値ずれ
    bad = (_phase(a=5.3, scale=1.0),)     # 誤った格子
    result = analyze_single_pattern(tt, y, [good, bad], backend=backend)

    assert len(result.ranked) == 2
    top = result.ranked[0]
    assert top.hypothesis.phases[0].lattice.a == pytest.approx(4.0, abs=0.02)
    assert top.probability > result.ranked[1].probability
    assert result.ledger.verify()


@pytest.mark.gsas
def test_staged_engine_runs_on_gsasii_backend():
    """M0 パイプラインの中核 (段階解放+ガード) が実バックエンドでも回ることの契約。"""
    from tsumugin.refinement.staged import StagedRefinementEngine
    from tsumugin.store.ledger import Ledger
    from tsumugin.store.snapshot import SnapshotStore

    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=2.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.01, scale=1.0)
    ledger = Ledger()
    engine = StagedRefinementEngine(backend, SnapshotStore(ledger), ledger)
    report = engine.run((start,), tt, y)

    assert report.escalated is False
    assert report.metrics.rwp < 20.0
    assert report.final_phases[0].lattice.a == pytest.approx(4.0, abs=0.01)
    assert ledger.verify()
