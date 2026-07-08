"""背景 overfit 減項の診断規則 (REQ-104) の決定論テスト。増項(非回帰)と両立を確認。"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.refine_loop.action import AdjustBackground
from tsumugin.refine_loop.diagnostics import ResidualFeatures, propose_next_actions


def _ok_result() -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0,
        final_gof=1.3,
        refined_cells={"P1": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
    )


def _overfit(props):
    return [p for p in props if p.evidence.get("signal") == "background_overfit"]


def test_bg_overfit_proposes_decrement():
    # 背景極値が過多 → 減項提案。
    feats = [ResidualFeatures(hist_id=0, bg_extrema_count=15, n_background_coeffs=24)]
    props = _overfit(propose_next_actions(_ok_result(), feats))
    assert len(props) == 1
    act = props[0].action
    assert isinstance(act, AdjustBackground)
    assert act.n_coeffs == 21  # 24 - background_step(3)
    assert props[0].safe


def test_bg_overfit_respects_lower_bound():
    # 減項は background_min(6) を下回らない。
    feats = [ResidualFeatures(hist_id=0, bg_extrema_count=20, n_background_coeffs=7)]
    props = _overfit(propose_next_actions(_ok_result(), feats))
    assert props and props[0].action.n_coeffs == 6


def test_bg_overfit_not_proposed_at_min():
    # 既に下限なら減項提案しない。
    feats = [ResidualFeatures(hist_id=0, bg_extrema_count=20, n_background_coeffs=6)]
    assert _overfit(propose_next_actions(_ok_result(), feats)) == []


def test_bg_increment_still_works_non_regression():
    # 背景不足(低周波残差)では従来どおり増項提案 (非回帰)。
    feats = [ResidualFeatures(hist_id=0, low_freq_bg_residual=0.5, n_background_coeffs=6)]
    props = propose_next_actions(_ok_result(), feats)
    inc = [p for p in props if p.evidence.get("signal") == "background"]
    assert inc and inc[0].action.n_coeffs == 9  # 6 + step(3)
