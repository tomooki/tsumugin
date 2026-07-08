"""RestrictUiso SafeAction + 診断規則 (REQ-004/105) の決定論テスト。"""

from __future__ import annotations

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.action import AnalysisInput, RestrictUiso
from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions


def _inp(*phase_names: str) -> AnalysisInput:
    hist = HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    phases = tuple(PhaseSpec(f"{n}.cif", n) for n in phase_names)
    return AnalysisInput((hist,), phases)


def test_restrict_uiso_sets_free_uiso_labels():
    out = RestrictUiso(("Cu", "Ow")).apply(_inp("P1"))
    assert out.phases[0].free_uiso_labels == ("Cu", "Ow")


def test_restrict_uiso_phase_specific():
    out = RestrictUiso(("Cu",), phase="P2").apply(_inp("P1", "P2"))
    assert out.phases[0].free_uiso_labels == ()      # P1 は不変
    assert out.phases[1].free_uiso_labels == ("Cu",)  # P2 のみ設定


def test_restrict_uiso_is_safe():
    assert RestrictUiso(("Cu",)).is_safe


def test_diverged_uiso_proposes_restrict_to_complement():
    # 発散原子 (C1,O2A) を除いた残り (Cu,Ow) に限定する提案。
    result = AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0, final_gof=1.3, refined_cells={"P1": (5.0,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True),
        atom_uiso={"P1": {"Cu": 0.01, "Ow": 0.05, "C1": -0.3, "O2A": 5e6}},
    )
    feats = [ResidualFeatures(hist_id=0, diverged_uiso_labels=("C1", "O2A"))]
    props = [p for p in propose_next_actions(result, feats)
             if p.evidence.get("signal") == "uiso_diverged"]
    assert len(props) == 1
    act = props[0].action
    assert isinstance(act, RestrictUiso)
    assert act.labels == ("Cu", "Ow")  # 決定論 (昇順)
    assert props[0].safe
