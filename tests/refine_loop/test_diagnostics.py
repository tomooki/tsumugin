"""TASK-0802: refine_loop.diagnostics — 残差診断→ActionProposal + 保守的初期リミット。

残差シグネチャから次手候補を決定論・安定順で提案する (architecture.md §5)。適用はしない。
純 numpy で GSAS 非依存。safe フラグ (規則が実行可か) を各提案に付す。
"""

from __future__ import annotations

import numpy as np

from tsumugin.autorietveld import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.refine_loop.action import (
    AddPhase,
    AdjustBackground,
    ReleaseParams,
    ReviseStructure,
    SetLimits,
)
from tsumugin.refine_loop.diagnostics import (
    ActionProposal,
    ResidualFeatures,
    propose_initial_limits,
    propose_next_actions,
)


def _result(*, rwp=15.0, passed=True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=rwp, gof=2.0, n_params=8, converged=True),),
        final_rwp=rwp,
        final_gof=2.0,
        refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=passed),
    )


def _feat(**kw) -> ResidualFeatures:
    base = dict(
        hist_id=0,
        low_freq_bg_residual=0.0,
        fwhm_ratio=1.0,
        unindexed_peak_frac=0.0,
        edge_low_snr=False,
        n_background_coeffs=6,
    )
    base.update(kw)
    return ResidualFeatures(**base)


# ---- 個別シグネチャ → 提案 ----

def test_low_freq_background_residual_proposes_adjust_background_safe():
    props = propose_next_actions(_result(), [_feat(low_freq_bg_residual=0.5)])
    bg = [p for p in props if isinstance(p.action, AdjustBackground)]
    assert bg, "低周波系統残差で背景増項を提案"
    assert bg[0].safe and bg[0].action.is_safe
    assert bg[0].action.n_coeffs == 9  # 6 → +3
    assert "background" in bg[0].evidence or bg[0].rationale


def test_background_not_proposed_when_at_cap():
    props = propose_next_actions(
        _result(), [_feat(low_freq_bg_residual=0.9, n_background_coeffs=12)], background_max=12
    )
    assert not [p for p in props if isinstance(p.action, AdjustBackground)]


def test_fwhm_ratio_mismatch_proposes_release_size_strain_safe():
    props = propose_next_actions(_result(), [_feat(fwhm_ratio=1.4)])
    rp = [p for p in props if isinstance(p.action, ReleaseParams)]
    assert rp and rp[0].safe
    assert "size_strain" in rp[0].action.flags


def test_unindexed_peaks_propose_addphase_unsafe():
    props = propose_next_actions(_result(), [_feat(unindexed_peak_frac=0.2)])
    ap = [p for p in props if isinstance(p.action, AddPhase)]
    assert ap, "未指数ピークで相追加を提案"
    assert not ap[0].safe  # ModelAction — 規則は実行不可、③ が判断


def test_edge_low_snr_proposes_setlimits_unsafe():
    props = propose_next_actions(_result(), [_feat(edge_low_snr=True)])
    sl = [p for p in props if isinstance(p.action, SetLimits)]
    assert sl and not sl[0].safe
    # H1 回帰: プレースホルダは NaN でなく None (json.dumps allow_nan=False 安全)
    import json

    from tsumugin.refine_loop.serialization import proposal_to_dict

    assert sl[0].action.low is None and sl[0].action.high is None
    json.dumps(proposal_to_dict(sl[0]), allow_nan=False)


def test_validity_fail_proposes_revise_structure_unsafe():
    props = propose_next_actions(_result(passed=False), [_feat()])
    rs = [p for p in props if isinstance(p.action, ReviseStructure)]
    assert rs and not rs[0].safe


def test_revise_structure_target_is_order_independent():
    # M3 回帰: ReviseStructure の相選択は refined_cells の反復順でなく相名でソート (決定論)
    r1 = AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=20.0, gof=2.0, n_params=8, converged=True),),
        final_rwp=20.0, final_gof=2.0,
        refined_cells={"beta": (1,) * 6, "alpha": (1,) * 6},  # 挿入順 beta→alpha
        validity=ValidityReport(passed=False),
    )
    r2 = AutoRietveldResult(
        stage_results=r1.stage_results, final_rwp=20.0, final_gof=2.0,
        refined_cells={"alpha": (1,) * 6, "beta": (1,) * 6},  # 逆順
        validity=ValidityReport(passed=False),
    )
    t1 = [p.action.phase for p in propose_next_actions(r1, [_feat()]) if isinstance(p.action, ReviseStructure)]
    t2 = [p.action.phase for p in propose_next_actions(r2, [_feat()]) if isinstance(p.action, ReviseStructure)]
    assert t1 == t2 == ["alpha"]  # 反復順に依らず最小相名


def test_clean_fit_yields_no_actionable_proposals():
    props = propose_next_actions(_result(passed=True), [_feat()])
    # きれいなフィットでは何も提案しない (Stop はポリシー側の判断)
    assert props == ()


# ---- 決定論・安定順 ----

def test_proposals_are_safe_first_then_priority_desc_deterministic():
    feats = [_feat(low_freq_bg_residual=0.3, unindexed_peak_frac=0.5, fwhm_ratio=1.5)]
    props = propose_next_actions(_result(), feats)
    # safe 提案がすべて unsafe より前
    safes = [p.safe for p in props]
    assert safes == sorted(safes, reverse=True)
    # 同じ入力で 2 回呼ぶとビット同一 (決定論)
    props2 = propose_next_actions(_result(), feats)
    assert [type(p.action).__name__ for p in props] == [type(p.action).__name__ for p in props2]


def test_action_proposal_is_frozen_and_carries_metadata():
    p = ActionProposal(
        action=AdjustBackground(9), rationale="bg", priority=0.5, evidence={"k": 1}, safe=True
    )
    assert p.priority == 0.5 and p.evidence["k"] == 1
    import dataclasses

    import pytest

    with pytest.raises(dataclasses.FrozenInstanceError):
        p.priority = 0.9  # type: ignore[misc]


# ---- 保守的初期リミット (setup 用, §4.3) ----

def test_propose_initial_limits_trims_low_snr_edges():
    # 中央にピーク列、両端はノイズのみ → 端が切られる
    x = np.linspace(0.0, 100.0, 1001)
    y = np.full_like(x, 5.0)  # ノイズ床
    # 30–70 に信号
    mask = (x >= 30.0) & (x <= 70.0)
    y = y.copy()
    y[mask] += 100.0
    limits = propose_initial_limits([0], {0: (x, y)})
    low, high = limits[0]
    assert low >= 20.0 and low <= 32.0
    assert high >= 68.0 and high <= 80.0


def test_propose_initial_limits_full_range_when_uniform_signal():
    x = np.linspace(0.0, 50.0, 501)
    y = np.full_like(x, 100.0)  # 全域信号
    limits = propose_initial_limits([0], {0: (x, y)})
    low, high = limits[0]
    assert low <= x[1] and high >= x[-2]
