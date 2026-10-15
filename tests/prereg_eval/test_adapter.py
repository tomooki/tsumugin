"""engine の結果 → `ArmOutcome` (P0 §1.2–§1.5 の材料)。"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.claims.model import Check
from tsumugin.prereg_eval.adapter import (
    fail_count,
    fit_values,
    observation_set_hash,
    outcome_from_result,
    result_chi2,
)

_PHASES = (PhaseSpec("p.cif", "P"),)


def _result(**kw) -> AutoRietveldResult:
    base = dict(
        stage_results=(StageResult("S0", 10.0, 2.0, 5, True), StageResult("S1", 9.0, 1.5, 8, True)),
        final_rwp=9.0, final_gof=1.5, n_obs=1008,
        refined_cells={"P": (5.0, 5.0, 6.0, 90.0, 90.0, 120.0)},
        cell_esd={"P": (0.001, None, 0.002, 0.0, 0.0, 0.0)},
        validity=ValidityReport(passed=True, checks=(("lattice_P_a", True, ""),)),
        atom_coords={"P": {"Zn1": (1 / 3, 2 / 3, 0.0), "O1": (1 / 3, 2 / 3, 0.38)}},
        atom_coord_esd={"P": {"Zn1": (0.0, 0.0, None), "O1": (0.0, 0.0, 0.002)}},
        atom_occupancy={"P": {"Zn1": 1.0, "O1": 0.97}},
        atom_occupancy_esd={"P": {"Zn1": None, "O1": 0.01}},
    )
    base.update(kw)
    return AutoRietveldResult(**base)


def _hist(path, **kw):
    return HistogramSpec(data_path=str(path), instrument_path="i.instprm", radiation=Radiation.XRAY_LAB,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE", **kw)


# --- χ² ---------------------------------------------------------------------------------------


def test_chi2_comes_from_the_last_accepted_stage():
    assert result_chi2(_result()) == pytest.approx(1.5**2 * (1008 - 8))
    reverted = _result(stage_results=(StageResult("S0", 10.0, 2.0, 5, True),
                                      StageResult("S1", 9.0, 1.5, 8, True, reverted=True)))
    assert result_chi2(reverted) == pytest.approx(2.0**2 * (1008 - 5))


def test_chi2_is_none_without_observation_count():
    assert result_chi2(_result(n_obs=0)) is None


# --- 観測集合のハッシュ (§1.5) ----------------------------------------------------------------


def test_observation_hash_follows_data_limits_and_exclusions(tmp_path):
    data = tmp_path / "d.xye"
    data.write_text("10 1 1\n20 2 1\n", encoding="utf-8")
    h0 = observation_set_hash([_hist(data)])
    assert h0 == observation_set_hash([_hist(data)])
    assert h0 != observation_set_hash([_hist(data, two_theta_limits=(10.0, 15.0))])
    assert h0 != observation_set_hash([_hist(data, excluded_regions=((12.0, 13.0),))])
    other = tmp_path / "e.xye"
    other.write_text("10 1 1\n20 3 1\n", encoding="utf-8")
    assert h0 != observation_set_hash([_hist(other)])


def test_observation_hash_is_none_when_data_cannot_be_read(tmp_path):
    assert observation_set_hash([_hist(tmp_path / "missing.xye")]) is None


# --- 比較集合の値 -----------------------------------------------------------------------------


def test_fit_values_carry_esd_and_refinement_state():
    vals = {v.key: v for v in fit_values(_result(), include_cell=False)}
    o1 = vals["coord:P.O1"]
    assert o1.kind == "coord" and o1.refined and o1.sigma == (0.0, 0.0, 0.002)
    assert vals["coord:P.Zn1"].refined is False  # どの軸も精密化していない (esd が None か 0)
    assert vals["occ:P.O1"].sigma == 0.01 and vals["occ:P.O1"].refined
    assert vals["occ:P.Zn1"].refined is False
    assert not any(v.kind == "cell" for v in vals.values())  # scope = relative の事例は格子を入れない


def test_cell_values_only_when_absolute():
    vals = {v.key: v for v in fit_values(_result(), include_cell=True)}
    assert vals["cell:P.a"].value == 5.0 and vals["cell:P.a"].refined
    assert vals["cell:P.b"].refined is False  # esd None = 決まっていない


# --- fail 件数 (§1.4) ------------------------------------------------------------------------


def test_fail_count_adds_validity_and_chemistry_per_check_and_phase():
    res = _result(validity=ValidityReport(passed=False, checks=(
        ("lattice_P_a", True, ""), ("uiso_P_0", False, "negative"), ("occupancy_P_1", False, ">1"))))

    def checker(phase, path, result):
        return {"short_contact": (Check.FAIL, None), "bvs_gii": (Check.UNEVALUATED, None),
                "charge_neutrality": (Check.PASS, None), "crystal_chemistry": (Check.FAIL, None)}

    # validity 2 件 + 結晶化学 1 件 (crystal_chemistry は最悪のまとめなので二重に数えない)
    assert fail_count(res, _PHASES, checker=checker) == 3


# --- まとめ (§1.2 の失敗) --------------------------------------------------------------------


def _quiet(phase, path, result):
    return {"short_contact": (Check.PASS, None)}


def _no_bonds(phase, path, result):
    return 0, {}


def test_outcome_from_a_good_result(tmp_path):
    data = tmp_path / "d.xye"
    data.write_text("1 1 1\n", encoding="utf-8")
    o = outcome_from_result(_result(), histograms=[_hist(data)], phases=_PHASES,
                            checker=_quiet, bond_counter=_no_bonds)
    assert not o.failed and o.chi2 == pytest.approx(2250.0) and o.obs_hash
    assert o.fail_count == 0 and o.short_bonds == 0


@pytest.mark.parametrize(
    ("kw", "reason"),
    [
        ({"result": None, "error": "boom"}, "boom"),
        ({"result": _result(stage_results=(StageResult("S0", 10.0, math.nan, 5, True),))}, "chi2"),
        ({"result": _result(stage_results=(StageResult("S0", 10.0, 1.0, 5, False),))}, "converge"),
        ({"result": _result(), "posthoc_converged": False}, "post-hoc"),
    ],
)
def test_failures_are_failures(tmp_path, kw, reason):
    data = tmp_path / "d.xye"
    data.write_text("1 1 1\n", encoding="utf-8")
    o = outcome_from_result(histograms=[_hist(data)], phases=_PHASES, checker=_quiet, bond_counter=_no_bonds, **kw)
    assert o.failed and reason in o.failure_reason


def test_short_bonds_none_if_any_phase_cannot_be_counted(tmp_path):
    data = tmp_path / "d.xye"
    data.write_text("1 1 1\n", encoding="utf-8")
    o = outcome_from_result(_result(), histograms=[_hist(data)], phases=_PHASES,
                            checker=_quiet, bond_counter=lambda *a: (None, {"reason": "x"}))
    assert o.short_bonds is None


def test_posthoc_threshold_matches_the_engines_convergence_gate():
    from tsumugin.autorietveld.model import StabilityOptions
    from tsumugin.prereg_eval.adapter import POSTHOC_MAX_SHIFT_ESD, posthoc_converged

    assert POSTHOC_MAX_SHIFT_ESD == StabilityOptions().max_shift_esd == 1.0
    assert posthoc_converged(0.7) is True and posthoc_converged(1.0) is True
    assert posthoc_converged(1.01) is False
    assert posthoc_converged(None) is None  # 共分散が無い = 判定できない (失敗にも成功にもしない)
