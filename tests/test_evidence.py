from __future__ import annotations

import math

import pytest

from tsumugin.evidence import (
    AICBackend,
    BICBackend,
    EvidenceBackend,
    rank,
)
from tsumugin.model import Hypothesis, PhaseInstance, LatticeParams, RefinementMetrics


def _metrics(chi2: float, k: int, n: int = 1000) -> RefinementMetrics:
    return RefinementMetrics(rwp=0.0, gof=1.0, chi2=chi2, n_obs=n, n_params=k)


def _hyp(hid: str, chi2: float, k: int) -> Hypothesis:
    ph = PhaseInstance(phase_ref=hid, lattice=LatticeParams(5, 5, 5), scale=1.0)
    return Hypothesis(id=hid, phases=(ph,), metrics=_metrics(chi2, k))


def test_bic_value():
    r = BICBackend().score(_metrics(100.0, 5, 1000))
    assert r.backend == "bic"
    assert r.value == pytest.approx(100.0 + 5 * math.log(1000))


def test_aic_value():
    r = AICBackend().score(_metrics(100.0, 5))
    assert r.backend == "aic"
    assert r.value == pytest.approx(110.0)


def test_backends_satisfy_protocol():
    assert isinstance(BICBackend(), EvidenceBackend)
    assert isinstance(AICBackend(), EvidenceBackend)


def test_rank_probabilities_sum_to_one_and_best_is_top():
    hyps = [_hyp("a", 100.0, 5), _hyp("b", 150.0, 5), _hyp("c", 300.0, 5)]
    ranked = rank(hyps, BICBackend())
    total = sum(r.probability for r in ranked)
    assert total == pytest.approx(1.0)
    assert ranked[0].hypothesis.id == "a"  # lowest chi2 -> best -> highest prob
    assert ranked[0].probability == max(r.probability for r in ranked)


def test_rank_sorted_ascending_by_value():
    hyps = [_hyp("c", 300.0, 5), _hyp("a", 100.0, 5), _hyp("b", 150.0, 5)]
    ranked = rank(hyps, BICBackend())
    values = [r.evidence.value for r in ranked]
    assert values == sorted(values)


def test_temperature_flattens_distribution():
    hyps = [_hyp("a", 100.0, 5), _hyp("b", 130.0, 5)]
    cold = rank(hyps, BICBackend(), temperature=1.0)
    hot = rank(hyps, BICBackend(), temperature=50.0)
    assert hot[0].probability < cold[0].probability


def test_close_competitor_flagging():
    # a and b within delta 10, c far away
    hyps = [_hyp("a", 100.0, 5), _hyp("b", 105.0, 5), _hyp("c", 400.0, 5)]
    ranked = rank(hyps, BICBackend(), close_threshold=10.0)
    by_id = {r.hypothesis.id: r for r in ranked}
    assert by_id["a"].close_competitor is True
    assert by_id["b"].close_competitor is True
    assert by_id["c"].close_competitor is False


def test_missing_metrics_raises():
    bad = Hypothesis(id="x", phases=())
    with pytest.raises(ValueError):
        rank([bad], BICBackend())


def test_empty_input_returns_empty():
    assert rank([], BICBackend()) == ()
