"""選択配向 + 幅個別 の診断規則 (REQ-102/103) の決定論テスト。"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions


def _ok_result() -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0,
        final_gof=1.3,
        refined_cells={"P1": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
    )


def _by_signal(props, sig):
    return [p for p in props if p.evidence.get("signal") == sig]


def test_width_mismatch_emits_three_separate_candidates():
    # 幅ずれ → U,V,W / X,Y / size の3別提案 (現行 size のみを置換)。
    feats = [ResidualFeatures(hist_id=0, fwhm_ratio=1.3)]
    props = _by_signal(propose_next_actions(_ok_result(), feats), "fwhm")
    labels = [p.action.label for p in props]
    assert labels == ["profile_uvw", "profile_xy", "size_strain"]
    flags = {p.action.label: dict(p.action.flags) for p in props}
    assert flags["profile_uvw"] == {"profile": ["U", "V", "W"]}
    assert flags["profile_xy"] == {"profile_lorentzian": True}
    assert flags["size_strain"] == {"size_strain": True}
    assert all(p.safe for p in props)


def test_intensity_bias_emits_preferred_orientation():
    feats = [ResidualFeatures(hist_id=0, intensity_bias=0.2)]
    props = _by_signal(propose_next_actions(_ok_result(), feats), "intensity_bias")
    assert len(props) == 1
    assert props[0].action.label == "preferred_orientation"
    assert dict(props[0].action.flags) == {"preferred_orientation": 4}
    assert props[0].safe


def test_no_width_no_bias_no_proposal():
    feats = [ResidualFeatures(hist_id=0, fwhm_ratio=1.0, intensity_bias=0.0)]
    props = propose_next_actions(_ok_result(), feats)
    assert _by_signal(props, "fwhm") == []
    assert _by_signal(props, "intensity_bias") == []
