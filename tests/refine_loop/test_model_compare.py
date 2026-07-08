"""model_compare (BIC+妥当性のモデル比較オーケストレータ, REQ-005/202) の決定論テスト。"""

from __future__ import annotations

import math

from tsumugin.autorietveld.compare import ModelVariant
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.model_compare import run_model_comparison
from tsumugin.store.ledger import Ledger


def _result(*, gof: float, k: int, n: int, passed: bool) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=gof * 0.5, gof=gof, n_params=k, converged=True),),
        final_rwp=gof * 0.5, final_gof=gof, refined_cells={},
        validity=ValidityReport(passed=passed), n_obs=n,
    )


def _phase(name: str) -> PhaseSpec:
    return PhaseSpec(f"{name}.cif", name)


def _hist() -> HistogramSpec:
    return HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                        geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")


def _variants():
    return (ModelVariant("model5", (_phase("model5"),)),
            ModelVariant("model6", (_phase("model6"),)))


def test_best_is_valid_min_bic_and_best_phases():
    results = {
        "model5": _result(gof=1.5, k=20, n=20000, passed=True),
        "model6": _result(gof=1.4, k=22, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    out = run_model_comparison([_hist()], _variants(), runner=stub)
    bic5 = 1.5**2 * (20000 - 20) + 20 * math.log(20000)
    bic6 = 1.4**2 * (20000 - 22) + 22 * math.log(20000)
    expected = "model6" if bic6 < bic5 else "model5"
    assert out.comparison.best == expected
    assert out.comparison.best_is_valid is True
    assert out.best_phases[0].phase_name == expected


def test_low_bic_but_invalid_not_best():
    results = {
        "model5": _result(gof=1.2, k=20, n=20000, passed=False),  # 最小BICだが非妥当
        "model6": _result(gof=1.45, k=20, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    out = run_model_comparison([_hist()], _variants(), runner=stub)
    assert out.comparison.best == "model6"
    assert out.comparison.best_is_valid is True
    assert out.best_phases[0].phase_name == "model6"


def test_all_invalid_fallback():
    results = {
        "model5": _result(gof=1.2, k=20, n=20000, passed=False),
        "model6": _result(gof=1.45, k=20, n=20000, passed=False),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    out = run_model_comparison([_hist()], _variants(), runner=stub)
    assert out.comparison.best == "model5"  # 全体最小BIC
    assert out.comparison.best_is_valid is False


def test_ledger_appended_and_verifies():
    results = {
        "model5": _result(gof=1.5, k=20, n=20000, passed=True),
        "model6": _result(gof=1.4, k=22, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    ledger = Ledger()
    out = run_model_comparison([_hist()], _variants(), runner=stub, ledger=ledger)
    assert out.ledger is ledger
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert kinds.count("model_compare_variant") == 2
    assert "model_compare_best" in kinds


def test_deterministic():
    results = {
        "model5": _result(gof=1.5, k=20, n=20000, passed=True),
        "model6": _result(gof=1.4, k=22, n=20000, passed=True),
    }

    def stub(hists, phases, **kw):
        return results[phases[0].phase_name]

    a = run_model_comparison([_hist()], _variants(), runner=stub)
    b = run_model_comparison([_hist()], _variants(), runner=stub)
    assert a.comparison.best == b.comparison.best
    assert [s.name for s in a.comparison.scores] == [s.name for s in b.comparison.scores]
