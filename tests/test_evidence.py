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


def test_bic_with_zero_observations_does_not_raise():
    # n_obs=0 (空パターンの縮退) でも math domain error にせず log(1)=0 として扱う
    r = BICBackend().score(_metrics(5.0, 3, n=0))
    assert r.value == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# Issue #64 / FR-123: noise_scale の BIC/AIC への反映
# ---------------------------------------------------------------------------


def _metrics_ns(chi2: float, k: int, n: int, noise_scale: float | None) -> RefinementMetrics:
    return RefinementMetrics(rwp=0.0, gof=1.0, chi2=chi2, n_obs=n, n_params=k, noise_scale=noise_scale)


def test_noise_scale_defaults_to_none_and_matches_legacy_formula_bitwise():
    # (e) noise_scale 未指定 (既定 None) は現行式と厳密一致 (後方互換)。
    m = _metrics(100.0, 5, 1000)
    assert m.noise_scale is None
    legacy = 100.0 + 5 * math.log(1000)
    assert BICBackend().score(m).value == legacy  # 近似でなく厳密一致
    assert AICBackend().score(m).value == 100.0 + 2.0 * 5


def test_noise_scale_one_is_bitwise_identical_to_none():
    # s=1.0 を明示しても None と厳密に同じ値になる (ln(1)=0, chi2/1=chi2 が正確)。
    none_metrics = _metrics_ns(123.0, 4, 500, None)
    unit_metrics = _metrics_ns(123.0, 4, 500, 1.0)
    assert BICBackend().score(none_metrics).value == BICBackend().score(unit_metrics).value
    assert AICBackend().score(none_metrics).value == AICBackend().score(unit_metrics).value


def test_bic_noise_scale_formula():
    # BIC = chi2/s² + n·ln(s²) + k·ln(n)
    m = _metrics_ns(90.0, 3, 200, 2.0)
    expected = 90.0 / 4.0 + 200 * math.log(4.0) + 3 * math.log(200)
    assert BICBackend().score(m).value == pytest.approx(expected)


def test_aic_noise_scale_formula():
    # AIC = chi2/s² + n·ln(s²) + 2k
    m = _metrics_ns(90.0, 3, 200, 2.0)
    expected = 90.0 / 4.0 + 200 * math.log(4.0) + 2.0 * 3
    assert AICBackend().score(m).value == pytest.approx(expected)


@pytest.mark.parametrize("invalid_scale", [0.0, -1.0, float("nan"), float("inf")])
def test_invalid_noise_scale_falls_back_to_unscaled_chi2(invalid_scale: float):
    # 数学的に無効な s (<=0 / 非有限) は補正を諦め従来式へ防御的にフォールバックする。
    m = _metrics_ns(50.0, 2, 100, invalid_scale)
    legacy = 50.0 + 2 * math.log(100)
    assert BICBackend().score(m).value == legacy


def test_extreme_small_noise_scale_does_not_raise_zero_division():
    # Issue #64 レビュー対応: noise_scale=1e-200 は s 自体は有限かつ正だが、s*s が float64 の
    # 下限を割ってちょうど 0.0 にアンダーフローする。旧ガード (s<=0 判定) はこれを見逃し
    # chi2/s2 が ZeroDivisionError を送出していた (実測)。s² を判定基準にすることで
    # ZeroDivisionError を送出せず現行式 (noise_scale 無効時と同じ) へ縮退することを確認する。
    m = _metrics_ns(50.0, 2, 100, 1e-200)
    legacy = 50.0 + 2 * math.log(100)
    assert BICBackend().score(m).value == legacy  # 例外を投げず縮退
    assert AICBackend().score(m).value == 50.0 + 2 * 2


def test_bic_ranking_flip_with_differing_noise_scale():
    # (f) 回帰ケース: 生の chi2 だけならチ B (chi2=95) が A (chi2=100) より良く見えるが、
    # B のノイズスケールが大きい (自己無矛盾でない重みだった) と分かると評価が逆転する。
    n, k = 50, 5
    hyp_a = _metrics_ns(chi2=100.0, k=k, n=n, noise_scale=1.0)
    hyp_b = _metrics_ns(chi2=95.0, k=k, n=n, noise_scale=2.5)

    bic_a = BICBackend().score(hyp_a).value
    bic_b = BICBackend().score(hyp_b).value

    # 素の chi2 (= noise_scale=1 相当) では B が勝つ (95 < 100)。
    naive_a = 100.0 + k * math.log(n)
    naive_b = 95.0 + k * math.log(n)
    assert naive_b < naive_a

    # だが noise_scale 補正後は A が勝つ (序列が反転する)。
    assert bic_a < bic_b
