"""TASK-0050: nested/sampler (NestedBackend/NestedConfig/NestedOutcome) のテスト。

通常 pytest (非依存) では未導入経路・縮退・Laplace 代替・時間上限フォールバックを網羅する。
実サンプラ依存 (@pytest.mark.nested) は dynesty/ultranest 導入環境でのみ実行する
(未導入環境では conftest の auto-skip)。
"""

from __future__ import annotations

import dataclasses
import importlib

import numpy as np
import pytest

from tsumugin.errors import NestedUnavailableError
from tsumugin.evidence.base import EvidenceResult
from tsumugin.model import RefinementMetrics
from tsumugin.nested.base import EvidenceProblem, PriorSpec
from tsumugin.nested.laplace import LaplaceBackend
from tsumugin.nested.sampler import NestedBackend, NestedConfig, NestedOutcome
from tsumugin.store.ledger import Ledger


def _metrics() -> RefinementMetrics:
    return RefinementMetrics(rwp=5.0, gof=1.2, chi2=100.0, n_obs=1000, n_params=8)


def _problem() -> EvidenceProblem:
    """尤度関数 + 事前分布を持つ最小の EvidenceProblem (map/hessian なし → BIC 縮退可)。"""
    priors = (
        PriorSpec(param_name="phase0.lattice.a", kind="uniform", low=4.0, high=6.0),
        PriorSpec(param_name="phase0.occ.site", kind="uniform", low=0.0, high=1.0),
    )

    def log_likelihood(theta: np.ndarray) -> float:
        # 2 次元ガウス尤度 (中心 [5.0, 0.5])
        center = np.array([5.0, 0.5])
        return float(-0.5 * np.sum((np.asarray(theta) - center) ** 2))

    return EvidenceProblem(
        metrics=_metrics(),
        log_likelihood=log_likelihood,
        priors=priors,
        label="test-problem",
    )


# ---------------------------------------------------------------------------
# 通常 pytest (実サンプラ非依存)
# ---------------------------------------------------------------------------


def test_import_core_only():
    """import tsumugin.nested.sampler がコア (numpy) のみで成功する (TC-502-02)。"""
    mod = importlib.import_module("tsumugin.nested.sampler")
    assert hasattr(mod, "NestedBackend")


def test_backend_name_and_defaults():
    """NestedBackend が name='nested'、config/laplace の既定を持つ。"""
    backend = NestedBackend()
    assert backend.name == "nested"
    assert isinstance(backend.config, NestedConfig)
    assert isinstance(backend.laplace, LaplaceBackend)
    assert backend.config.sampler == "dynesty"
    assert backend.config.seed == 0
    assert backend.config.n_live == 400
    assert backend.config.time_limit_sec == 1800.0
    assert backend.config.max_calls is None


def test_frozen_dataclasses():
    """3 型とも frozen である。"""
    backend = NestedBackend()
    with pytest.raises(dataclasses.FrozenInstanceError):
        backend.name = "x"  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        NestedConfig().seed = 1  # type: ignore[misc]
    outcome = NestedOutcome(result=EvidenceResult(backend="nested", value=1.0), logz=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.truncated = True  # type: ignore[misc]


def test_score_delegates_to_laplace():
    """score(metrics) が尤度関数を欠くため Laplace 代替へ委譲する (REQ-007/101)。"""
    backend = NestedBackend()
    metrics = _metrics()
    got = backend.score(metrics)
    expected = LaplaceBackend().score(metrics)
    assert got.value == expected.value
    assert got.backend == expected.backend


def test_score_problem_raises_when_sampler_unavailable():
    """dynesty/ultranest 未導入で score_problem が NestedUnavailableError を送出する (TC-502-01)。"""
    if importlib.util.find_spec("dynesty") is not None or (
        importlib.util.find_spec("ultranest") is not None
    ):
        pytest.skip("実サンプラ導入環境: 未導入経路テストは対象外")
    backend = NestedBackend()
    with pytest.raises(NestedUnavailableError) as exc:
        backend.score_problem(_problem())
    # extra 導入手順を案内する
    assert "nested" in str(exc.value)


def test_run_with_fallback_degrades_on_unavailable():
    """未導入時 run_with_fallback が truncated=True + Laplace 代替 + 警告で返り例外化しない (TC-504-01)。"""
    if importlib.util.find_spec("dynesty") is not None or (
        importlib.util.find_spec("ultranest") is not None
    ):
        pytest.skip("実サンプラ導入環境: 未導入経路テストは対象外")
    backend = NestedBackend()
    problem = _problem()
    outcome = backend.run_with_fallback(problem)
    assert isinstance(outcome, NestedOutcome)
    assert outcome.truncated is True
    assert outcome.logz is None
    assert outcome.warnings  # 非空
    # Laplace 代替値と一致する
    expected = LaplaceBackend().score_problem(problem)
    assert outcome.result.value == expected.value


def test_run_with_fallback_ledger_records_and_verifies():
    """打ち切り時 ledger へ理由付き append され verify() が True (TC-504-02/REQ-013)。"""
    backend = NestedBackend()
    ledger = Ledger()
    backend.run_with_fallback(_problem(), ledger=ledger)
    assert ledger.verify() is True
    assert len(ledger.entries) >= 1


def test_run_with_fallback_deterministic():
    """未導入フォールバックが決定論 (2 回同値)。"""
    backend = NestedBackend()
    problem = _problem()
    o1 = backend.run_with_fallback(problem)
    o2 = backend.run_with_fallback(problem)
    assert o1.result.value == o2.result.value
    assert o1.truncated == o2.truncated


def test_run_with_fallback_time_limit_truncation():
    """時間上限超過を模した経路で truncated=True + Laplace 代替を返す (時間上限テスト可能性)。

    実サンプラ非依存にするため、内部実行フック ``_run_nested`` を注入クロックで超過扱いにする。
    ここでは score_problem を「超過を示す TimeoutError」で差し替えて run_with_fallback の縮退を検証する。
    """
    backend = NestedBackend()
    problem = _problem()

    def _timeout(_problem: EvidenceProblem) -> EvidenceResult:
        raise TimeoutError("time_limit_sec exceeded (simulated)")

    # frozen dataclass のため object.__setattr__ で内部フックを差し替える
    outcome = backend._run_with_fallback_using(problem, run=_timeout, ledger=None)
    assert outcome.truncated is True
    assert outcome.logz is None
    assert any("time" in w.lower() or "上限" in w for w in outcome.warnings)
    expected = LaplaceBackend().score_problem(problem)
    assert outcome.result.value == expected.value


# ---------------------------------------------------------------------------
# 実サンプラ依存 (@pytest.mark.nested) — 未導入環境では auto-skip
# ---------------------------------------------------------------------------


@pytest.mark.nested
def test_score_problem_returns_logz_and_err():
    """nested が value=-logZ + logz_err を返す (TC-502-03/REQ-006/007)。"""
    backend = NestedBackend(config=NestedConfig(n_live=100, seed=0))
    result = backend.score_problem(_problem())
    assert result.backend == "nested"
    assert np.isfinite(result.value)
    assert result.logz_err is not None
    assert result.logz_err >= 0.0


@pytest.mark.nested
def test_score_problem_seed_reproducible_within_err():
    """seed 固定 2 回で logZ が logz_err 範囲内一致 (TC-502-04/REQ-009/EDGE-014)。"""
    backend = NestedBackend(config=NestedConfig(n_live=100, seed=42))
    problem = _problem()
    r1 = backend.score_problem(problem)
    r2 = backend.score_problem(problem)
    # value = -logZ。誤差の合算範囲内で一致
    tol = 3.0 * ((r1.logz_err or 0.0) + (r2.logz_err or 0.0) + 1e-9)
    assert abs(r1.value - r2.value) <= tol
