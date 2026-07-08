"""autorietveld.compare (BIC モデル比較) の決定論テスト (runner スタブ注入)。"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.compare import (
    ModelVariant,
    compare_models,
    metrics_from_result,
)
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    StageResult,
    ValidityReport,
)


def _result(*, gof: float, n_params: int, n_obs: int, passed: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=0.0, gof=gof, n_params=n_params, converged=True),),
        final_rwp=gof * 0.5,
        final_gof=gof,
        refined_cells={},
        validity=ValidityReport(passed=passed),
        n_obs=n_obs,
        phase_fractions={"NaCuHCF": 1.0},
    )


def _phase(name: str) -> PhaseSpec:
    return PhaseSpec(structure_path=f"{name}.cif", phase_name=name)


def test_metrics_from_result_reconstructs_chi2():
    res = _result(gof=2.0, n_params=10, n_obs=1010)
    m = metrics_from_result(res)
    # chi2 = GOF^2 * (n_obs - k) = 4 * 1000 = 4000
    assert m.chi2 == pytest.approx(4000.0)
    assert m.n_params == 10
    assert m.n_obs == 1010


def test_compare_models_ranks_by_bic_and_sets_delta():
    # model6: 僅かに低 GOF (良フィット) だが +2 params。BIC で有利かを判定。
    results = {
        "model5": _result(gof=1.50, n_params=20, n_obs=20000),
        "model6": _result(gof=1.40, n_params=22, n_obs=20000),
    }

    def stub_runner(hists, phases, **kw):
        name = phases[0].phase_name
        return results[name]

    variants = (
        ModelVariant("model5", (_phase("model5"),)),
        ModelVariant("model6", (_phase("model6"),)),
    )
    hist = HistogramSpec("d.xye", "i.instprm", radiation=_rad(), geometry=_geo(), data_format="XYE")
    cmp = compare_models([hist], variants, runner=stub_runner)

    # BIC(model5) = 1.5^2*(19980) + 20*ln(20000)
    bic5 = 1.5**2 * (20000 - 20) + 20 * math.log(20000)
    bic6 = 1.4**2 * (20000 - 22) + 22 * math.log(20000)
    assert cmp.best == ("model6" if bic6 < bic5 else "model5")
    # scores は BIC 昇順。
    assert cmp.scores[0].bic <= cmp.scores[1].bic
    assert cmp.scores[0].delta_bic == pytest.approx(0.0)
    assert cmp.scores[1].delta_bic == pytest.approx(abs(bic6 - bic5), rel=1e-6)


def test_compare_models_best_prefers_valid_over_lower_bic():
    # 低 BIC だが物理妥当性 fail のモデルより、高 BIC でも妥当なモデルを best に選ぶ
    # (CLAUDE.md「BIC + 妥当性」)。delta_bic は全体最小 BIC 基準のため不妥当モデルが 0。
    results = {
        "bad": _result(gof=1.20, n_params=20, n_obs=20000, passed=False),  # 最小 BIC だが不妥当
        "good": _result(gof=1.45, n_params=20, n_obs=20000, passed=True),
    }

    def stub_runner(hists, phases, **kw):
        return results[phases[0].phase_name]

    variants = (ModelVariant("bad", (_phase("bad"),)), ModelVariant("good", (_phase("good"),)))
    hist = HistogramSpec("d.xye", "i.instprm", radiation=_rad(), geometry=_geo(), data_format="XYE")
    cmp = compare_models([hist], variants, runner=stub_runner)

    assert cmp.best == "good"          # 妥当なモデルを選定
    assert cmp.best_is_valid is True
    assert cmp.scores[0].name == "bad"  # 序列自体は BIC 昇順 (不妥当が先頭)
    assert cmp.scores[0].delta_bic == pytest.approx(0.0)


def test_compare_models_best_falls_back_when_none_valid():
    # 全モデル不妥当なら全体最小 BIC にフォールバックし best_is_valid=False。
    results = {
        "m1": _result(gof=1.20, n_params=20, n_obs=20000, passed=False),
        "m2": _result(gof=1.45, n_params=20, n_obs=20000, passed=False),
    }

    def stub_runner(hists, phases, **kw):
        return results[phases[0].phase_name]

    variants = (ModelVariant("m1", (_phase("m1"),)), ModelVariant("m2", (_phase("m2"),)))
    hist = HistogramSpec("d.xye", "i.instprm", radiation=_rad(), geometry=_geo(), data_format="XYE")
    cmp = compare_models([hist], variants, runner=stub_runner)

    assert cmp.best == "m1"  # 全体最小 BIC (低 GOF)
    assert cmp.best_is_valid is False


def test_compare_models_empty_variants_raises():
    with pytest.raises(ValueError, match="1 つ以上"):
        compare_models([], [], runner=lambda *a, **k: None)


def _rad():
    from tsumugin.autorietveld.model import Radiation

    return Radiation.XRAY_SYNCHROTRON


def _geo():
    from tsumugin.autorietveld.model import Geometry

    return Geometry.DEBYE_SCHERRER
