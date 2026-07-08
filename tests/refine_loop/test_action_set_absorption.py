"""SetAbsorption SafeAction + 診断規則 (REQ-004/106) の決定論テスト。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.action import AnalysisInput, SetAbsorption


def _inp(n_hist: int = 1) -> AnalysisInput:
    hists = tuple(
        HistogramSpec(f"d{i}.xye", "i.instprm", radiation=Radiation.NEUTRON_TOF,
                      geometry=Geometry.DEBYE_SCHERRER, data_format="FXYE")
        for i in range(n_hist)
    )
    return AnalysisInput(hists, ())


def test_set_absorption_fixes_value():
    out = SetAbsorption(0, 0.031, refine=False).apply(_inp())
    assert out.histograms[0].absorption == 0.031
    assert out.extra_stages == ()  # 固定なので段追加なし


def test_set_absorption_refine_adds_stage():
    out = SetAbsorption(0, 0.0, refine=True).apply(_inp())
    assert out.histograms[0].absorption == 0.0
    assert len(out.extra_stages) == 1
    assert out.extra_stages[0].flags == {"absorption": True}


def test_set_absorption_out_of_range_raises():
    with pytest.raises(IndexError):
        SetAbsorption(3, 0.1).apply(_inp(n_hist=1))


def test_set_absorption_is_safe():
    assert SetAbsorption(0, 0.0).is_safe


def test_absorption_uncertain_proposes_three_way():
    # 現吸収値 0.031 → free / 物理(現値固定) / 0 の3提案。
    from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions

    result = AutoRietveldResult(
        stage_results=(StageResult("final", rwp=15.0, gof=1.4, n_params=8, converged=True),),
        final_rwp=15.0, final_gof=1.4, refined_cells={"P1": (5.0,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True),
        hist_absorption=(0.031,),
    )
    feats = [ResidualFeatures(hist_id=0, absorption_uncertain=True)]
    props = [p for p in propose_next_actions(result, feats)
             if p.evidence.get("signal") == "absorption"]
    cands = [p.evidence["candidate"] for p in props]
    assert cands == ["abs_free", "abs_fixed", "abs_zero"]  # 決定論
    fixed = next(p for p in props if p.evidence["candidate"] == "abs_fixed")
    assert fixed.action.value == 0.031 and fixed.action.refine is False
    assert all(p.safe for p in props)


def test_absorption_uncertain_no_current_two_way():
    # 現値 0 (未設定) → free / 0 の2提案 (物理固定は重複回避で省く)。
    from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions

    result = AutoRietveldResult(
        stage_results=(StageResult("final", rwp=15.0, gof=1.4, n_params=8, converged=True),),
        final_rwp=15.0, final_gof=1.4, refined_cells={"P1": (5.0,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True),
    )
    feats = [ResidualFeatures(hist_id=0, absorption_uncertain=True)]
    props = [p for p in propose_next_actions(result, feats)
             if p.evidence.get("signal") == "absorption"]
    assert [p.evidence["candidate"] for p in props] == ["abs_free", "abs_zero"]
