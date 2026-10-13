"""fit-then-judge P1-1B タスク 1: 統計の規約 (proposal §5, REQ-FTJ-1B-101〜105)。"""

from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pytest

from tsumugin.evidence.fitstats import (
    chi2_from_stage,
    effective_dof_ratio,
    hamilton_test,
    same_dof_comparison,
)

# ---------------------------------------------------------------------------
# Hamilton の R 比検定 (入れ子のモデル)
# ---------------------------------------------------------------------------


def test_a_large_drop_in_chi2_is_significant():
    r = hamilton_test(1100.0, 1000.0, 1.0, 1, alpha=0.01)
    assert r is not None and r.significant
    assert r.lr == pytest.approx(100.0)
    assert r.critical == pytest.approx(6.6349, abs=1e-3)  # χ²₁ の 0.99 分位点


def test_the_statistic_is_scaled_by_the_gof_of_the_larger_model():
    """Δχ²/GOF²_big — GOF² で割らないと点数の多いデータで何でも有意になる。"""
    r = hamilton_test(1100.0, 1000.0, 25.0, 1, alpha=0.01)
    assert r is not None and r.lr == pytest.approx(4.0) and not r.significant


def test_more_added_parameters_need_a_larger_drop():
    r1 = hamilton_test(1010.0, 1000.0, 1.0, 1, alpha=0.01)
    r6 = hamilton_test(1010.0, 1000.0, 1.0, 6, alpha=0.01)
    assert r1.significant and not r6.significant
    assert r6.critical == pytest.approx(16.8119, abs=1e-3)


def test_correlated_residuals_shrink_the_statistic():
    r = hamilton_test(1100.0, 1000.0, 1.0, 1, alpha=0.01, dof_ratio=0.05)
    assert r.lr == pytest.approx(5.0) and not r.significant
    assert r.dof_ratio == 0.05


def test_a_worse_bigger_model_is_not_significant():
    r = hamilton_test(1000.0, 1100.0, 1.0, 1, alpha=0.01)
    assert r is not None and not r.significant and r.lr < 0


@pytest.mark.parametrize(
    "args",
    [
        (math.inf, 1000.0, 1.0, 1),
        (1100.0, math.nan, 1.0, 1),
        (1100.0, 1000.0, 0.0, 1),
        (1100.0, 1000.0, -1.0, 1),
        (1100.0, 1000.0, 1.0, 0),
    ],
)
def test_undecidable_inputs_return_none_not_a_verdict(args):
    """判定できないものを「有意でない」と答えない (None = unevaluated)。"""
    assert hamilton_test(*args, alpha=0.01) is None


@pytest.mark.parametrize("ratio", [0.0, -0.5, math.nan, 1.5])
def test_an_invalid_dof_ratio_is_refused(ratio):
    assert hamilton_test(1100.0, 1000.0, 1.0, 1, alpha=0.01, dof_ratio=ratio) is None


def test_the_result_is_json_safe():
    import json

    json.dumps(hamilton_test(1100.0, 1000.0, 1.0, 2, alpha=0.05).to_dict(), allow_nan=False)


def test_chi2_is_recovered_from_gsas_stage_values():
    """GSAS の GOF = sqrt(χ²/(N−P)) なので χ² = GOF²·(N−P)。"""
    assert chi2_from_stage(gof=1.5, n_obs=1000, n_params=10) == pytest.approx(2.25 * 990)
    assert chi2_from_stage(gof=math.inf, n_obs=1000, n_params=10) is None
    assert chi2_from_stage(gof=1.0, n_obs=10, n_params=10) is None


# ---------------------------------------------------------------------------
# 母数の数が同じ 2 解
# ---------------------------------------------------------------------------


def test_two_fits_with_nearly_identical_curves_are_indistinguishable():
    m = np.linspace(10.0, 20.0, 200)
    sigma = np.ones_like(m)
    r = same_dof_comparison(m, m + 0.01, sigma, 500.0, 499.0, 1.0, alpha=0.01)
    assert r is not None and not r.distinguishable and r.z is None
    assert r.s == pytest.approx(200 * 1e-4)


def test_distinguishable_fits_report_a_z_score():
    m = np.zeros(100)
    sigma = np.ones(100)
    r = same_dof_comparison(m, m + 1.0, sigma, 600.0, 500.0, 1.0, alpha=0.01)
    assert r.distinguishable
    assert r.z == pytest.approx(100.0 / (2.0 * 1.0 * math.sqrt(100.0)))


def test_same_dof_comparison_refuses_mismatched_or_bad_inputs():
    m = np.zeros(10)
    assert same_dof_comparison(m, np.zeros(9), np.ones(10), 1.0, 1.0, 1.0, alpha=0.01) is None
    assert same_dof_comparison(m, m, np.zeros(10), 1.0, 1.0, 1.0, alpha=0.01) is None
    assert same_dof_comparison(m, m, np.ones(10), 1.0, 1.0, 0.0, alpha=0.01) is None


# ---------------------------------------------------------------------------
# 実効自由度
# ---------------------------------------------------------------------------


def test_white_noise_keeps_nearly_all_degrees_of_freedom():
    e = np.random.default_rng(0).standard_normal(20000)
    assert effective_dof_ratio(e) == pytest.approx(1.0, abs=0.03)


def test_positively_correlated_residuals_lose_degrees_of_freedom():
    rng = np.random.default_rng(1)
    rho = 0.8
    e = np.empty(50000)
    e[0] = rng.standard_normal()
    for i in range(1, e.size):
        e[i] = rho * e[i - 1] + rng.standard_normal()
    assert effective_dof_ratio(e) == pytest.approx((1 - rho) / (1 + rho), rel=0.05)


def test_negative_correlation_never_inflates_the_count():
    e = np.tile([1.0, -1.0], 500)
    assert effective_dof_ratio(e) == 1.0


@pytest.mark.parametrize("e", [[1.0, 2.0], [0.0] * 50, [1.0, math.nan, 2.0, 3.0]])
def test_undecidable_residuals_return_none(e):
    assert effective_dof_ratio(np.asarray(e)) is None


def test_perfectly_smooth_residuals_have_a_positive_floor():
    """ρ→1 でも 0 を返さない (0 で割る検定を作らない)。"""
    r = effective_dof_ratio(np.linspace(1.0, 2.0, 1000))
    assert r is not None and 0.0 < r < 0.01


# ---------------------------------------------------------------------------
# BIC の opt-in 項目
# ---------------------------------------------------------------------------


def test_bic_is_bit_identical_without_the_ratio():
    from tsumugin.evidence.ic import AICBackend, BICBackend
    from tsumugin.model.hypothesis import RefinementMetrics

    m = RefinementMetrics(rwp=10.0, gof=1.2, chi2=1234.5, n_obs=1000, n_params=12)
    assert BICBackend().score(m).value == 1234.5 + 12 * math.log(1000)
    assert AICBackend().score(m).value == 1234.5 + 24.0


def test_bic_uses_the_effective_count():
    from tsumugin.evidence.ic import AICBackend, BICBackend
    from tsumugin.model.hypothesis import RefinementMetrics

    m = RefinementMetrics(
        rwp=10.0, gof=1.2, chi2=1000.0, n_obs=1000, n_params=12, effective_dof_ratio=0.25
    )
    assert BICBackend().score(m).value == pytest.approx(250.0 + 12 * math.log(250.0))
    assert AICBackend().score(m).value == pytest.approx(250.0 + 24.0)


def test_noise_scale_and_effective_dof_cannot_be_combined():
    from tsumugin.model.hypothesis import RefinementMetrics

    with pytest.raises(ValueError, match="noise_scale"):
        RefinementMetrics(
            rwp=1.0, gof=1.0, chi2=1.0, n_obs=10, n_params=1,
            noise_scale=1.1, effective_dof_ratio=0.5,
        )


@pytest.mark.parametrize("ratio", [0.0, 1.5, math.nan])
def test_an_invalid_effective_dof_ratio_is_refused(ratio):
    from tsumugin.model.hypothesis import RefinementMetrics

    with pytest.raises(ValueError):
        RefinementMetrics(
            rwp=1.0, gof=1.0, chi2=1.0, n_obs=10, n_params=1, effective_dof_ratio=ratio
        )


# ---------------------------------------------------------------------------
# σ(χ²)=√(2·dof) を同一データ上の比較に使わない (REQ-FTJ-1B-104)
# ---------------------------------------------------------------------------

_SRC = Path(__file__).resolve().parents[2] / "src" / "tsumugin"
_FORBIDDEN = re.compile(
    r"(?:sqrt\(\s*2(?:\.0)?\s*\*\s*\(?\s*[\w.]*(?:dof|n_obs|nobs|n_points|npts|n\b)"
    r"|\(\s*2(?:\.0)?\s*\*\s*[\w.]*(?:dof|n_obs|nobs|n_points|npts)[^)]*\)\s*\*\*\s*0?\.5)",
    re.I,
)


def test_sigma_chi2_from_the_degrees_of_freedom_is_not_used():
    offenders = [
        f"{p.relative_to(_SRC)}:{i}"
        for p in _SRC.rglob("*.py")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if _FORBIDDEN.search(line)
    ]
    assert not offenders, offenders


def test_the_forbidden_pattern_detects_the_idiom():
    """ガード自身の検査 — 典型的な書き方を検出できること。"""
    for line in ("s = math.sqrt(2 * dof)", "np.sqrt(2.0*(n_obs - p))", "sqrt(2 * self.dof)",
                 "(2 * dof) ** 0.5", "math.sqrt(2*n_points)", "(2.0*n_obs - k)**.5"):
        assert _FORBIDDEN.search(line), line
    assert not _FORBIDDEN.search("math.sqrt(2.0 * math.log(2.0))")
