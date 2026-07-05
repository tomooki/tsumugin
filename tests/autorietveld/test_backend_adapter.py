"""TASK-0808: AutoRietveldBackend — 実構造を RefinementBackend Protocol に配線 (M8 要素4)。

RefinementModel(相 + 観測) を PhaseSpec/HistogramSpec へ写像し run_auto_rietveld へ委譲、
final_rwp/gof を RefinementResult(chi2/rwp) へ写像する。chi2 は既存 GSASIIBackend と整合する
weighted-SSR (= gof^2·(n_obs-n_params)) で BIC 比較可能。失敗は chi2=inf (既存規約)。純テスト。
"""

from __future__ import annotations

import math

import numpy as np

from tsumugin.autorietveld import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.backend_adapter import AutoRietveldBackend
from tsumugin.backends.base import RefinementBackend, RefinementModel, RefinementResult
from tsumugin.evidence.ic import BICBackend
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.model.hypothesis import RefinementMetrics


def _histogram() -> HistogramSpec:
    return HistogramSpec(
        data_path="d.xra",
        instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )


def _phase(ref: str) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(9.37, 9.37, 6.89, 90.0, 90.0, 120.0))


def _resolver(ref: str) -> PhaseSpec:
    return PhaseSpec(structure_path=f"{ref}.cif", phase_name=ref)


def _model(*refs: str) -> RefinementModel:
    tt = np.linspace(10.0, 90.0, 200)
    yo = np.ones_like(tt)
    return RefinementModel(
        phases=tuple(_phase(r) for r in refs),
        free_params=frozenset(),
        two_theta=tt,
        intensity=yo,
    )


def _stub_result(rwp: float, gof: float, n_params: int, *, passed: bool = True, n_obs: int = 0):
    return AutoRietveldResult(
        stage_results=(
            StageResult(label="S0", rwp=rwp, gof=gof, n_params=n_params, converged=True),
        ),
        final_rwp=rwp,
        final_gof=gof,
        refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=passed),
        n_obs=n_obs,
    )


def test_satisfies_refinement_backend_protocol():
    be = AutoRietveldBackend(resolver=_resolver, histograms=(_histogram(),))
    assert isinstance(be, RefinementBackend)
    assert be.name


def test_refine_maps_rwp_and_reconstructs_chi2():
    def runner(inp):
        return _stub_result(rwp=12.0, gof=2.0, n_params=10)

    be = AutoRietveldBackend(resolver=_resolver, histograms=(_histogram(),), runner=runner)
    model = _model("fap")
    res = be.refine(model)
    assert res.rwp == 12.0  # パーセント値をそのまま (GSASIIBackend 整合)
    # chi2 = gof^2 * (n_obs - n_params) = 4 * (200 - 10)
    assert abs(res.chi2 - 4.0 * (200 - 10)) < 1e-6
    assert res.n_obs == 200 and res.n_params == 10 and res.converged


def test_uses_result_nobs_when_present():
    # Issue #16: 結果が実観測点数 (n_obs) を持つならそれを dof/n_obs に使う
    # (レンジ制限で model.intensity 長 200 と異なる 150 を優先)
    def runner(inp):
        return _stub_result(rwp=10.0, gof=2.0, n_params=10, n_obs=150)

    be = AutoRietveldBackend(resolver=_resolver, histograms=(_histogram(),), runner=runner)
    res = be.refine(_model("fap"))  # model.intensity は 200 点
    assert res.n_obs == 150  # model.intensity 長でなく実 Nobs
    assert abs(res.chi2 - 4.0 * (150 - 10)) < 1e-6  # dof も実 Nobs 基準


def test_falls_back_to_model_intensity_when_nobs_absent():
    # n_obs=0 (未設定) なら従来どおり model.intensity 長にフォールバック
    def runner(inp):
        return _stub_result(rwp=10.0, gof=2.0, n_params=10, n_obs=0)

    be = AutoRietveldBackend(resolver=_resolver, histograms=(_histogram(),), runner=runner)
    res = be.refine(_model("fap"))
    assert res.n_obs == 200


def test_resolver_is_called_per_phase():
    seen = []

    def spy_resolver(ref):
        seen.append(ref)
        return _resolver(ref)

    def runner(inp):
        assert [p.phase_name for p in inp.phases] == ["a", "b"]
        return _stub_result(10.0, 1.5, 8)

    be = AutoRietveldBackend(resolver=spy_resolver, histograms=(_histogram(),), runner=runner)
    be.refine(_model("a", "b"))
    assert seen == ["a", "b"]


def test_failure_maps_to_chi2_inf():
    def boom_runner(inp):
        raise RuntimeError("GSAS 収束失敗")

    be = AutoRietveldBackend(resolver=_resolver, histograms=(_histogram(),), runner=boom_runner)
    res = be.refine(_model("fap"))
    assert math.isinf(res.chi2) and math.isinf(res.rwp)
    assert not res.converged  # 失敗はガードレールへ (例外にしない)


def test_ranks_lower_chi2_hypothesis_higher_via_bic():
    # 実構造多仮説: rwp が低い仮説ほど chi2 が小さく BIC で上位になる (evidence 接続)
    def runner_factory(rwp, gof):
        return lambda inp: _stub_result(rwp, gof, 10)

    good = AutoRietveldBackend(
        resolver=_resolver, histograms=(_histogram(),), runner=runner_factory(8.0, 1.2)
    )
    poor = AutoRietveldBackend(
        resolver=_resolver, histograms=(_histogram(),), runner=runner_factory(25.0, 3.5)
    )
    bic = BICBackend()
    good_res = good.refine(_model("fap"))
    poor_res = poor.refine(_model("other"))

    def _metrics(r: RefinementResult) -> RefinementMetrics:
        return RefinementMetrics(
            rwp=r.rwp, gof=math.sqrt(max(r.chi2 / max(r.n_obs - r.n_params, 1), 0.0)),
            chi2=r.chi2, n_obs=r.n_obs, n_params=r.n_params,
        )

    assert bic.score(_metrics(good_res)).value < bic.score(_metrics(poor_res)).value
