"""TASK-0049 nested/base の契約テスト (PriorSpec / EvidenceProblem / ProblemAwareEvidenceBackend)。

検証:
- PriorSpec.transform が [0,1] を各 kind の物理量へ写す (REQ-008/FR-125)
- EvidenceProblem のフィールド保持
- ProblemAwareEvidenceBackend が runtime_checkable で score+score_problem を要求する (REQ-004/D1)
- 既存 EvidenceBackend / EvidenceResult が無改変 (D1)
- コア (numpy) のみで import できる
"""

from __future__ import annotations

import math

import numpy as np
import pytest


def test_import_core_only():
    # numpy のみで import 成功 (scipy 非依存)
    import tsumugin.nested.base as base  # noqa: F401


def test_priorspec_uniform_transform_endpoints_and_midpoint():
    from tsumugin.nested.base import PriorSpec

    spec = PriorSpec(param_name="phase0.lattice.a", kind="uniform", low=2.0, high=6.0)
    assert spec.transform(0.0) == pytest.approx(2.0)
    assert spec.transform(1.0) == pytest.approx(6.0)
    assert spec.transform(0.5) == pytest.approx(4.0)


def test_priorspec_normal_median_is_loc():
    from tsumugin.nested.base import PriorSpec

    spec = PriorSpec(param_name="global.x", kind="normal", loc=3.0, scale=2.0)
    # 正規分布の中央値 (u=0.5) は loc
    assert spec.transform(0.5) == pytest.approx(3.0, abs=1e-9)
    # 対称性: u と 1-u が loc について対称
    lo = spec.transform(0.1)
    hi = spec.transform(0.9)
    assert (lo + hi) / 2.0 == pytest.approx(3.0, abs=1e-6)
    # scale が幅に効く (約 ±1σ 近辺で単調増加)
    assert spec.transform(0.2) < spec.transform(0.8)


def test_priorspec_normal_one_sigma():
    from tsumugin.nested.base import PriorSpec

    spec = PriorSpec(param_name="global.x", kind="normal", loc=0.0, scale=1.0)
    # 標準正規の 0.8413... 分位点 ≈ +1σ
    q = spec.transform(0.8413447460685429)
    assert q == pytest.approx(1.0, abs=1e-3)


def test_priorspec_normal_boundaries_are_finite():
    from tsumugin.nested.base import PriorSpec

    spec = PriorSpec(param_name="global.x", kind="normal", loc=0.0, scale=1.0)
    lo = spec.transform(0.0)
    hi = spec.transform(1.0)
    assert math.isfinite(lo)
    assert math.isfinite(hi)
    assert lo < spec.transform(0.5) < hi


def test_priorspec_truncated_normal_stays_within_bounds():
    from tsumugin.nested.base import PriorSpec

    spec = PriorSpec(
        param_name="global.occ",
        kind="truncated_normal",
        low=0.0,
        high=1.0,
        loc=0.5,
        scale=0.3,
    )
    for u in (0.0, 0.01, 0.25, 0.5, 0.75, 0.99, 1.0):
        v = spec.transform(u)
        assert 0.0 <= v <= 1.0, (u, v)
    # 単調増加
    assert spec.transform(0.2) < spec.transform(0.8)
    # 端点は境界に一致
    assert spec.transform(0.0) == pytest.approx(0.0, abs=1e-9)
    assert spec.transform(1.0) == pytest.approx(1.0, abs=1e-9)


def test_priorspec_is_frozen():
    from tsumugin.nested.base import PriorSpec

    spec = PriorSpec(param_name="p")
    with pytest.raises(Exception):
        spec.low = 5.0  # type: ignore[misc]


def test_evidence_problem_holds_fields():
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.model import RefinementMetrics

    metrics = RefinementMetrics(rwp=1.0, gof=1.0, chi2=10.0, n_obs=100, n_params=3)

    def loglike(theta: np.ndarray) -> float:
        return -0.5 * float(np.dot(theta, theta))

    priors = (PriorSpec(param_name="a"), PriorSpec(param_name="b"))
    map_point = np.array([0.1, 0.2])
    hessian = np.eye(2)
    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=loglike,
        priors=priors,
        map_point=map_point,
        hessian=hessian,
        label="hyp-1",
    )
    assert problem.metrics is metrics
    assert problem.log_likelihood(np.array([1.0, 0.0])) == pytest.approx(-0.5)
    assert problem.priors == priors
    assert np.allclose(problem.map_point, map_point)
    assert np.allclose(problem.hessian, hessian)
    assert problem.label == "hyp-1"


def test_evidence_problem_defaults():
    from tsumugin.nested.base import EvidenceProblem
    from tsumugin.model import RefinementMetrics

    metrics = RefinementMetrics(rwp=1.0, gof=1.0, chi2=10.0, n_obs=100, n_params=3)
    problem = EvidenceProblem(
        metrics=metrics, log_likelihood=lambda t: 0.0, priors=()
    )
    assert problem.map_point is None
    assert problem.hessian is None
    assert problem.label == ""


def test_problem_aware_backend_runtime_checkable_true():
    from tsumugin.nested.base import (
        EvidenceProblem,
        ProblemAwareEvidenceBackend,
    )
    from tsumugin.evidence.base import EvidenceResult
    from tsumugin.model import RefinementMetrics

    class DummyProblemAware:
        name = "dummy"

        def score(self, metrics: RefinementMetrics) -> EvidenceResult:
            return EvidenceResult(backend=self.name, value=0.0)

        def score_problem(self, problem: EvidenceProblem) -> EvidenceResult:
            return EvidenceResult(backend=self.name, value=1.0)

    assert isinstance(DummyProblemAware(), ProblemAwareEvidenceBackend)


def test_bic_backend_is_not_problem_aware():
    # 既存 BICBackend は score のみで score_problem を欠くため False
    from tsumugin.nested.base import ProblemAwareEvidenceBackend
    from tsumugin.evidence.ic import AICBackend, BICBackend

    assert not isinstance(BICBackend(), ProblemAwareEvidenceBackend)
    assert not isinstance(AICBackend(), ProblemAwareEvidenceBackend)


def test_existing_evidence_backend_unchanged():
    # D1: 既存 EvidenceBackend / EvidenceResult は無改変 (フィールド・シグネチャ確認)
    from tsumugin.evidence.base import EvidenceBackend, EvidenceResult

    r = EvidenceResult(backend="bic", value=1.0)
    assert r.logz_err is None
    assert r.backend == "bic"
    assert r.value == 1.0
    # EvidenceBackend Protocol は name + score(metrics) のみ (score_problem を含まない)
    from tsumugin.evidence.ic import BICBackend

    assert isinstance(BICBackend(), EvidenceBackend)
