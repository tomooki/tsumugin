"""非対称/位置を別々の候補として提案する診断規則 (REQ-101/003/405) の決定論テスト。"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.refine_loop.action import ReleaseParams
from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions


def _ok_result() -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0,
        final_gof=1.3,
        refined_cells={"P1": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
    )


def _asym_proposals(props):
    return [p for p in props if p.evidence.get("signal") == "asymmetry"]


def test_asymmetry_emits_two_separate_candidates_xray():
    # X線: シフト(profile_lorentzian) と 非対称(profile_asymmetry SH/L) の2提案。
    feats = [ResidualFeatures(hist_id=0, asymmetry_residual=0.3, radiation_is_tof=False)]
    props = _asym_proposals(propose_next_actions(_ok_result(), feats))
    assert len(props) == 2
    labels = [p.action.label for p in props]
    assert labels == ["xray_zero", "xray_asymmetry"]  # 決定論順 (Zero → 非対称)
    flags = {p.action.label: dict(p.action.flags) for p in props}
    assert flags["xray_zero"] == {"profile_lorentzian": True}
    assert flags["xray_asymmetry"] == {"profile_asymmetry": True}
    assert all(p.safe and p.action.is_safe for p in props)
    assert all(isinstance(p.action, ReleaseParams) for p in props)


def test_asymmetry_emits_alpha_beta_for_tof():
    # TOF: 非対称は alpha/beta、位置は tof_profile の Zero。
    feats = [ResidualFeatures(hist_id=1, asymmetry_residual=0.2, radiation_is_tof=True)]
    props = _asym_proposals(propose_next_actions(_ok_result(), feats))
    assert [p.action.label for p in props] == ["tof_zero", "tof_asymmetry"]
    flags = {p.action.label: dict(p.action.flags) for p in props}
    assert "alpha" in flags["tof_asymmetry"]["tof_profile"]
    assert "Zero" in flags["tof_zero"]["tof_profile"]


def test_no_asymmetry_no_proposal():
    # 非対称なし → 提案なし (false positive を出さない)。
    feats = [ResidualFeatures(hist_id=0, asymmetry_residual=0.0)]
    assert _asym_proposals(propose_next_actions(_ok_result(), feats)) == []


def test_asymmetry_proposals_deterministic():
    feats = [ResidualFeatures(hist_id=0, asymmetry_residual=0.3, radiation_is_tof=False)]
    a = [p.action.label for p in _asym_proposals(propose_next_actions(_ok_result(), feats))]
    b = [p.action.label for p in _asym_proposals(propose_next_actions(_ok_result(), feats))]
    assert a == b
