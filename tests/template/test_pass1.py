"""fit-then-judge P1-1B タスク 6: pass 1 の判断 (REQ-FTJ-1B-301〜304)。注入 runner で GSAS 非依存。"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    InstrumentProfile,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.store import Ledger
from tsumugin.template.declarations import TemplateDeclarations
from tsumugin.template.pass1 import Pass1Config, Pass1Error, run_template_pass1

N_OBS = 2000


def _hist(geometry=Geometry.BRAGG_BRENTANO, **kw) -> HistogramSpec:
    return HistogramSpec(
        data_path="d.xye", instrument_path="i.instprm",
        radiation=Radiation.XRAY_LAB, geometry=geometry, **kw,
    )


A = PhaseSpec("a.cif", "A")
B = PhaseSpec("b.cif", "B")


def _chi2_gof(chi2: float, n_params: int) -> float:
    return float(np.sqrt(chi2 / (N_OBS - n_params)))


class FakeRunner:
    """段のラベルの接頭辞ごとに (Δχ², 足す母数, revert) を返す偽の runner。

    χ² は段ごとに累積で下がり、母数は累積で増える。revert した段は直前の状態のまま。
    """

    def __init__(self, *, drops=None, reverts=None, intensity=None, fail=(), residual=None,
                 intensity_by_trial=None):
        self.intensity_by_trial = intensity_by_trial or {}
        self.drops = {"T0": 5000.0, "T1": 3000.0, "T2": 1500.0, "T3": 500.0, "T4": 100.0}
        self.drops.update(drops or {})
        self.adds = {"T0": 7, "T1": 4, "T2": 3, "T3": 2, "T4": 1, "TZ": 1}
        self.reverts = reverts or {}
        self.intensity = intensity or {"A": (100.0,), "B": (20.0,)}
        self.fail = set(fail)
        self.residual = residual
        self.calls: list[tuple[str, tuple[str, ...], list]] = []

    def __call__(self, trial, histograms, phases, stages):
        self.calls.append((trial, tuple(s.label for s in stages), [dict(s.flags) for s in stages]))
        if trial in self.fail:
            raise RuntimeError("GSAS failed")
        chi2, n_params, out = 20000.0, 0, []
        bg_prev = None
        for st in stages:
            key = st.label.split(" ", 1)[0]
            reverted = self.reverts.get((trial, key), self.reverts.get(key, False))
            if callable(reverted):
                reverted = reverted(st)
            add = self.adds.get(key, 0)
            if key.startswith("TB"):
                n = int(key[2:])
                add = n - (bg_prev or 6)
            if not reverted:
                chi2 -= self.drops.get(key, 0.0)
                n_params += add
                if key.startswith("TB"):
                    bg_prev = int(key[2:])
            out.append(
                StageResult(st.label, 10.0 * chi2 / 20000.0, _chi2_gof(chi2, n_params),
                            n_params, True, reverted=bool(reverted))
            )
        resid = self.residual if self.residual is not None else np.random.default_rng(0).standard_normal(500)
        return AutoRietveldResult(
            stage_results=tuple(out), final_rwp=out[-1].rwp, final_gof=out[-1].gof,
            refined_cells={}, validity=ValidityReport(passed=True), n_obs=N_OBS,
            residual_intensity=tuple(float(x) for x in resid),
            residual_sigma=tuple(1.0 for _ in resid),
            residual_two_theta=tuple(float(i) for i in range(len(resid))),
            atom_uiso={p.phase_name: {f"{p.phase_name}1": 0.01, f"{p.phase_name}2": 0.01} for p in phases},
            phase_integrated_intensity={
                p.phase_name: self.intensity_by_trial.get(trial, self.intensity)[p.phase_name]
                for p in phases
            },
        )


def _run(phases=(A,), hist=None, decl=None, **kw):
    runner = kw.pop("runner", None) or FakeRunner(**kw.pop("fake", {}))
    out = run_template_pass1(
        [hist or _hist()], list(phases), decl or TemplateDeclarations(), runner=runner, **kw
    )
    return out, runner


# --- 格子 -----------------------------------------------------------------------


def test_no_cell_is_frozen_when_stage_one_is_accepted():
    out, runner = _run(phases=(A, B))
    assert out.decisions.frozen_cell_phases == ()
    assert [c[0] for c in runner.calls] == ["A", "B"]


def test_single_phase_with_a_rejected_lattice_stage_freezes_that_phase():
    out, runner = _run(fake={"reverts": {("A", "T1"): True}})
    assert out.decisions.frozen_cell_phases == ("A",)
    assert out.evidence["cell"]["basis"] == "single_phase_stage1_reverted"
    # 凍結を決めたら段 0 からやり直す — 段 1 の格子を外して (オフセットだけ)
    redo = next(c for c in runner.calls if c[0] == "A-refrozen")
    assert "cell" not in redo[2][1]


def test_the_violation_is_attributed_by_leaving_one_lattice_out():
    def stage1(st):  # B の格子を一緒に解放すると壊れる
        return "B" in st.flags.get("cell_phases", ["A", "B"])

    out, runner = _run(phases=(A, B), fake={"reverts": {"T1": stage1}})
    assert out.decisions.frozen_cell_phases == ("B",)
    trials = out.evidence["cell"]["trials"]
    assert [t["without"] for t in trials] == ["A", "B"]
    assert [t["stage1_accepted"] for t in trials] == [False, True]
    redo = next(c for c in runner.calls if c[0] == "A-refrozen")
    assert redo[2][1]["cell_phases"] == ["A"]


def test_decisions_after_refreezing_come_from_the_refrozen_fit():
    """凍結してやり直した fit の状態で対象相を決める (壊れた段 1 の fit から決めない)。"""
    def stage1(st):
        return "B" in st.flags.get("cell_phases", ["A", "B"])

    out, _ = _run(
        phases=(A, B),
        fake={"reverts": {"T1": stage1},
              "intensity_by_trial": {"A": {"A": (100.0,), "B": (1.0,)},
                                     "A-refrozen": {"A": (1.0,), "B": (100.0,)}}},
    )
    assert out.decisions.target_phase == "B"


def test_when_no_single_phase_explains_it_every_lattice_is_frozen():
    out, _ = _run(phases=(A, B), fake={"reverts": {"T1": True}})
    assert out.decisions.frozen_cell_phases == ("A", "B")
    assert out.evidence["cell"]["basis"] == "no_single_phase_explains"


def test_a_failed_base_fit_raises():
    with pytest.raises(Pass1Error):
        _run(fake={"fail": {"A"}})


# --- 対象相 ---------------------------------------------------------------------


def test_the_target_is_the_phase_with_the_largest_integrated_intensity():
    out, _ = _run(phases=(A, B), fake={"intensity": {"A": (10.0,), "B": (100.0,)}})
    assert out.decisions.target_phase == "B" and not out.target_phase_ambiguous


def test_a_close_second_phase_is_ambiguous():
    out, _ = _run(phases=(A, B), fake={"intensity": {"A": (100.0,), "B": (85.0,)}})
    assert out.target_phase_ambiguous
    assert out.evidence["target_phase"]["ratio"] == pytest.approx(0.85)


def test_a_declaration_sets_the_target_but_does_not_silence_the_detector():
    decl = TemplateDeclarations(target_phase="B")
    out, _ = _run(phases=(A, B), decl=decl, fake={"intensity": {"A": (100.0,), "B": (20.0,)}})
    assert out.decisions.target_phase == "B"
    assert out.target_phase_ambiguous  # データは A を推す — 宣言で判断要求を閉じない
    assert out.evidence["target_phase"]["largest"] == "A"


def test_unmeasured_intensity_is_unevaluated_and_ambiguous():
    out, _ = _run(phases=(A, B), fake={"intensity": {"A": (None,), "B": (10.0,)}})
    assert out.evidence["target_phase"]["status"] == "unevaluated"
    assert out.target_phase_ambiguous


# --- 背景 -----------------------------------------------------------------------


def test_the_ladder_stops_at_the_first_insignificant_step():
    # 12 項で大きく下がり、18 項ではほとんど下がらない
    out, runner = _run(fake={"drops": {"TB12": 800.0, "TB18": 1.0, "TB24": 500.0}})
    assert out.decisions.background_coeffs == 12
    tests = out.evidence["background"]["tests"]
    assert [(t["from"], t["to"], t["significant"]) for t in tests] == [(6, 12, True), (12, 18, False)]
    b = next(c for c in runner.calls if c[0] == "B")
    assert [lab.split(" ")[0] for lab in b[1]][-4:] == ["TB12", "TB18", "TB24", "TZ"]


def test_a_rejected_ladder_stage_is_not_significant():
    out, _ = _run(fake={"drops": {"TB12": 800.0}, "reverts": {"TB12": True}})
    assert out.decisions.background_coeffs == 6
    first = out.evidence["background"]["tests"][0]
    assert first["reverted"] is True and first["significant"] is False
    assert out.evidence["background"]["status"] == "pass"  # 棄却は「判定できない」ではない


def test_correlated_residuals_make_the_ladder_more_conservative():
    rng = np.random.default_rng(3)
    e = np.empty(5000)
    e[0] = 0.0
    for i in range(1, e.size):
        e[i] = 0.95 * e[i - 1] + rng.standard_normal()
    drops = {"TB12": 100.0, "TB18": 1.0}
    white, _ = _run(fake={"drops": drops})
    red, _ = _run(fake={"drops": drops, "residual": e})
    assert white.decisions.background_coeffs == 12
    assert red.decisions.background_coeffs == 6
    assert red.evidence["effective_dof"]["dof_ratio"] < 0.1


def test_a_failed_test_fit_falls_back_to_the_default_as_unevaluated():
    out, _ = _run(fake={"fail": {"B"}})
    assert out.decisions.background_coeffs == 6
    assert out.evidence["background"]["status"] == "unevaluated"
    assert out.zero_offset_significant is None
    assert out.evidence["zero_offset"]["status"] == "unevaluated"


# --- Zero -----------------------------------------------------------------------


def test_a_significant_zero_is_reported_but_not_released():
    out, _ = _run(fake={"drops": {"TZ": 300.0}})
    assert out.zero_offset_significant is True
    assert out.evidence["zero_offset"]["decision"] == "instrument_value"


def test_a_rejected_zero_stage_is_not_significant():
    out, _ = _run(fake={"drops": {"TZ": 300.0}, "reverts": {"TZ": True}})
    assert out.zero_offset_significant is False


def test_an_insignificant_zero():
    out, _ = _run(fake={"drops": {"TZ": 0.5}})
    assert out.zero_offset_significant is False


def test_debye_scherrer_has_no_zero_test():
    out, runner = _run(hist=_hist(Geometry.DEBYE_SCHERRER))
    assert out.zero_offset_significant is None
    assert out.evidence["zero_offset"]["status"] == "not_applicable"
    b = next(c for c in runner.calls if c[0] == "B")
    assert not any(lab.startswith("TZ") for lab in b[1])


# --- 較正・Uiso・記録・決定論 ---------------------------------------------------------


def test_calibration_comes_from_the_declaration_or_the_instrument_profile():
    out, _ = _run(decl=TemplateDeclarations(instrument_calibrated=True))
    assert out.decisions.calibrated and out.evidence["calibrated"]["basis"].startswith("declared")
    prof = InstrumentProfile(values={"U": 1.0, "V": -1.0, "W": 2.0})
    out, runner = _run(hist=_hist(instrument_profile=prof))
    assert out.decisions.calibrated and out.evidence["calibrated"]["basis"] == "instrument_profile"
    assert runner.calls[0][2][2] == {"size_strain": "isotropic"}


def test_unreadable_structures_give_an_unevaluated_uiso_rule():
    out, _ = _run()
    assert out.evidence["uiso"]["status"] == "unevaluated"
    assert out.decisions.uiso_groups == ()


def test_labels_come_from_the_base_fit():
    out, _ = _run(phases=(A, B))
    assert out.decisions.phase_labels == {"A": ("A1", "A2"), "B": ("B1", "B2")}


def test_the_evidence_is_json_safe_and_recorded():
    ledger = Ledger()
    out, _ = _run(phases=(A, B), ledger=ledger)
    json.dumps(out.evidence)
    kinds = [e.kind for e in ledger.entries]
    assert kinds.count("template_pass1_trial") == 2 and kinds[-1] == "template_pass1"


def test_pass1_is_deterministic():
    a, _ = _run(phases=(A, B), fake={"drops": {"TB12": 800.0}})
    b, _ = _run(phases=(A, B), fake={"drops": {"TB12": 800.0}})
    assert a.decisions == b.decisions and a.evidence == b.evidence


def test_declared_phase_names_are_checked_first():
    with pytest.raises(ValueError):
        _run(decl=TemplateDeclarations(target_phase="Z"))


def test_the_config_ladder_is_used():
    out, runner = _run(config=Pass1Config(background_ladder=(9,)), fake={"drops": {"TB9": 900.0}})
    assert out.decisions.background_coeffs == 9
