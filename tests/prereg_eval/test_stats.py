"""P0 付録 B: c(N) (劣化の Clopper–Pearson 片側 95% 上限 < M = 0.25 を満たす最大の件数)。"""

from __future__ import annotations

import pytest

from tsumugin.prereg_eval.stats import allowed_failures, binomial_cdf, upper_bound


@pytest.mark.parametrize(
    ("n", "c", "bound"),
    [(15, 0, 0.181), (20, 1, 0.216), (24, 2, 0.240), (30, 3, 0.239), (40, 5, 0.245)],
)
def test_matches_appendix_b(n, c, bound):
    assert allowed_failures(n) == c
    assert upper_bound(c, n) == pytest.approx(bound, abs=6e-4)


@pytest.mark.parametrize("n", [0, 1, 5, 10])
def test_small_n_allows_nothing(n):
    # 0 件でも上限が 0.25 以上 → 何も言えない (None)。0 を返すと「0 件なら通る」と読める
    assert allowed_failures(n) is None


def test_upper_bound_is_monotone_and_inverts_the_cdf():
    for n in (11, 24, 57):
        bounds = [upper_bound(c, n) for c in range(n)]
        assert bounds == sorted(bounds)
        for c in (0, 2):
            assert binomial_cdf(c, n, upper_bound(c, n)) == pytest.approx(0.05, abs=1e-9)


def test_all_failures_has_bound_one():
    assert upper_bound(7, 7) == 1.0


def test_rejects_nonsense():
    with pytest.raises(ValueError):
        upper_bound(5, 4)
    with pytest.raises(ValueError):
        allowed_failures(-1)
