"""Issue #64 / FR-123 レビュー対応 (1): noise_scale 写像の全経路配線検証。

``RefinementResult.noise_scale`` (backend が EM 推定したノイズスケール s) が、各所の
``RefinementMetrics`` 構築箇所へ確実に伝播することを確認する。写像が抜けていると、backend が
どれだけ正確に s を推定しても BIC/AIC (``evidence/ic.py``) に一切反映されず FR-123 が
dead code になる (PR #77 レビュー最重要指摘)。

主要 3 経路 (末端まで ``estimate_noise=True`` の ``SimulatedBackend`` を使った end-to-end):
    1. staged エンジン経由 pipeline (``refinement.staged.StagedRefinementEngine``)
    2. search tree の仮説 metrics (``search.tree.HypothesisTreeSearch``)
    3. multistart の basin 昇格 (``multistart.engine.MultistartEngine._promote``)

残りの写像箇所 (private ヘルパ) は、``RefinementResult.noise_scale`` を明示的に設定した
最小入力を直接渡す軽量ユニットテストで検証する (フル e2e より低コストで同じ配線契約を保証)。
"""

from __future__ import annotations

import math

import numpy as np

from tsumugin.backends.base import RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.multistart.basin import BasinInfo, cluster_basins
from tsumugin.multistart.engine import MultistartEngine, MultistartResult
from tsumugin.operando.discrimination import _metrics_with_multistart, _model_bic
from tsumugin.operando.segmentation import _frame_bic
from tsumugin.refinement.staged import StagedRefinementEngine
from tsumugin.search.tree import HypothesisTreeSearch
from tsumugin.sequential.engine import SequentialEngine
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

from tsumugin.joint.verification import _metrics_from_aggregate  # isort:skip


GRID = np.arange(15.0, 60.0, 0.02)


def _phase(a: float, ref: str = "A", scale: float = 1.0) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _result(chi2: float = 10.0, noise_scale: float | None = 3.0, **overrides) -> RefinementResult:
    base = dict(
        phases=(_phase(5.0),),
        chi2=chi2,
        rwp=5.0,
        n_obs=100,
        n_params=4,
        converged=True,
        n_cycles=1,
        noise_scale=noise_scale,
    )
    base.update(overrides)
    return RefinementResult(**base)


# ---------------------------------------------------------------------------
# 主要 3 経路: estimate_noise=True の SimulatedBackend を使った end-to-end
# ---------------------------------------------------------------------------


def test_staged_engine_pipeline_propagates_noise_scale():
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
    tt = np.arange(15.0, 80.0, 0.02)
    truth = _phase(5.0, "P", scale=2.0)
    y = backend.simulate((truth,), tt)
    start = _phase(5.02, "P", scale=1.0)

    engine = StagedRefinementEngine(backend, SnapshotStore(Ledger()), Ledger())
    report = engine.run((start,), tt, y)

    assert report.metrics.noise_scale is not None
    assert math.isfinite(report.metrics.noise_scale)
    assert report.metrics.noise_scale > 0.0


def test_search_tree_hypothesis_metrics_propagate_noise_scale():
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
    phase_a = _phase(5.0, "A")
    y = backend.simulate([phase_a], GRID)

    result = HypothesisTreeSearch(backend).search(GRID, y, [phase_a])

    assert result.hypotheses  # 探索が少なくとも 1 ノードを評価した
    noise_scales = [h.metrics.noise_scale for h in result.hypotheses.values() if h.metrics]
    assert noise_scales  # metrics 付きノードが存在する
    assert all(ns is not None for ns in noise_scales)


def test_multistart_promote_propagates_noise_scale():
    # 【単一 basin では _promote が呼ばれないため】: 実 SimulatedBackend の収束解を代表として
    #   直接 BasinInfo に詰め、_promote (private) を直呼びして写像を検証する (route 3)。
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
    tt = np.arange(15.0, 80.0, 0.02)
    truth = _phase(5.0, "P", scale=2.0)
    y = backend.simulate((truth,), tt)
    from tsumugin.backends.base import RefinementModel, param_name

    start = (_phase(5.02, "P", scale=1.0),)
    free = frozenset(
        param_name(0, key) for key in ("scale", "lattice.a", "lattice.b", "lattice.c")
    )
    model = RefinementModel(phases=start, free_params=free, two_theta=tt, intensity=y)
    real_result = backend.refine(model)
    assert real_result.noise_scale is not None  # 前提: backend が実際に推定した

    basin = BasinInfo(
        representative=real_result, member_starts=(0,), chi2=real_result.chi2, evidence=0.0
    )
    engine = MultistartEngine(backend)
    hypothesis = engine._promote(basin, order=0, n_starts=2, n_basins=2, n_diverged=0)

    assert hypothesis.metrics is not None
    assert hypothesis.metrics.noise_scale == real_result.noise_scale


# ---------------------------------------------------------------------------
# 残りの写像箇所: RefinementResult.noise_scale を明示指定した直接ユニットテスト
# ---------------------------------------------------------------------------


def test_multistart_basin_evidence_of_reflects_noise_scale():
    # evidence (BIC) は noise_scale の有無で値が変わるはず (chi2/s² + n·ln(s²) の補正項)。
    with_scale = _result(chi2=90.0, noise_scale=2.0)
    without_scale = _result(chi2=90.0, noise_scale=None)

    basin_with = cluster_basins([with_scale], basin_rel_tol=1e-2)[0]
    basin_without = cluster_basins([without_scale], basin_rel_tol=1e-2)[0]

    assert basin_with.evidence != basin_without.evidence


def test_discrimination_model_bic_propagates_noise_scale():
    result = _result(chi2=90.0, noise_scale=2.0, n_obs=200)
    bic_with = _model_bic(result, active_count=1, model_suffixes=("scale", "lattice.a"))
    bic_without = _model_bic(
        _result(chi2=90.0, noise_scale=None, n_obs=200),
        active_count=1,
        model_suffixes=("scale", "lattice.a"),
    )
    assert bic_with != bic_without


def test_discrimination_metrics_with_multistart_propagates_noise_scale():
    result = _result(chi2=50.0, noise_scale=1.5)
    multistart = MultistartResult(
        basins=(), n_starts=4, n_diverged=0, promoted=(), is_global_corroborated=True
    )
    metrics = _metrics_with_multistart(result, multistart)
    assert metrics.noise_scale == 1.5


def test_segmentation_frame_bic_propagates_noise_scale():
    result_a = _result(chi2=40.0, noise_scale=2.0)
    result_b = _result(chi2=40.0, noise_scale=None)
    assert _frame_bic(result_a) != _frame_bic(result_b)


def test_joint_verification_metrics_from_aggregate_propagates_noise_scale():
    aggregate = _result(chi2=70.0, noise_scale=1.8)
    metrics = _metrics_from_aggregate(aggregate, evidence=None, prior=None)
    assert metrics.noise_scale == 1.8


def test_sequential_engine_metrics_from_result_propagates_noise_scale():
    result = _result(chi2=30.0, noise_scale=0.9)
    metrics = SequentialEngine._metrics_from_result(result)
    assert metrics.noise_scale == 0.9
