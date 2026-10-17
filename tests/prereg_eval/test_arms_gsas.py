"""P0 §1.1 の全アームを実 GSAS で 1 事例回し、評価の入力 (`ArmOutcome`) と W_i まで通す。

合成 `S-dev` (wurtzite ZnO, 計数雑音付き) だけを使う — (準) hold-out に触れない。
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gsas


def _zno(tmp_path):
    src = Path(__file__).resolve().parents[1] / "autorietveld" / "test_engine_polar_origin.py"
    spec = importlib.util.spec_from_file_location("_zno_synthetic_arms", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    xye, instprm, start = mod._synthetic_zno(tmp_path)
    x, y, _ = np.loadtxt(xye, unpack=True)
    noisy = np.random.default_rng(0).poisson(y).astype(float)
    np.savetxt(xye, np.column_stack([x, noisy, np.sqrt(np.maximum(noisy, 1.0))]), fmt="%.6f")
    return xye, instprm, start


def test_all_arms_run_on_a_synthetic_case_and_feed_the_judgment(tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.prereg_eval.adapter import outcome_from_result
    from tsumugin.prereg_eval.arms import PERMUTATIONS, run_arms
    from tsumugin.prereg_eval.case import CaseInput, judge
    from tsumugin.template.declarations import TemplateDeclarations

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _zno(tmp_path)
    hist = HistogramSpec(data_path=str(xye), instrument_path=str(instprm), radiation=Radiation.XRAY_LAB,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    phases = [PhaseSpec(str(start), "ZnO")]
    decl = TemplateDeclarations.from_dict({"target_phase": "ZnO"})

    arms = run_arms([hist], phases, decl, n_starts=3)

    expected = {"B-single", "B-AB", "T-single", "T-AB", "T-single/bkg", "T-AB/bkg", "X-transplant",
                *(f"T-perm:{p}" for p in PERMUTATIONS)}
    assert set(arms) == expected
    for name in ("B-single", "B-AB", "T-single", "T-AB", "X-transplant"):
        run = arms[name]
        assert run is not None and run.result is not None, (name, run and run.error)
        assert run.posthoc_shift_esd is not None, name  # 事後検査は全アームに同じものが掛かる
    assert arms["B-AB"].multistart is not None and arms["T-AB"].multistart is not None
    # DS 幾何に選択配向の段は無い → その置換は回さない (None)。格子と幅の入れ替えは回る
    assert arms["T-perm:T8_before_T5"] is None
    assert arms["T-perm:swap_T1_T2"] is not None and arms["T-perm:swap_T1_T2"].result is not None

    outcomes = {
        name: outcome_from_result(run.result, histograms=run.histograms, phases=run.phases, error=run.error)
        for name, run in arms.items() if run is not None
    }
    assert outcomes["B-single"].chi2 and outcomes["B-single"].obs_hash
    case = CaseInput("zno", reference=None, lattice=None, arms=outcomes)
    j = judge(case, template="T-single", comparator="B-single", template_fit="T-single/bkg")
    assert j.status in {"degraded", "not_degraded"} and "d" in j.evaluated
