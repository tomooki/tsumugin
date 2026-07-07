"""M10 anchor/select.py — crossover 選定 (bic) テスト。

核心の設計判断①「相集合が違う前方/後方は Rwp でなく bic で比較」を回帰で固定する:
Rwp 毎フレーム最小なら全域で多相 (偽相) を選ぶが、bic なら転移後のみ多相を選ぶ。
"""

from __future__ import annotations

from tsumugin.insitu.anchor.model import Anchor, AnchorConfig, Segment, SegmentPass
from tsumugin.insitu.anchor.select import assemble_path, frame_bic, select_crossover
from tsumugin.insitu.model import FrameRietveldResult
from tsumugin.autorietveld.model import PhaseSpec

ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
DELTA = PhaseSpec(structure_path="delta.cif", phase_name="new_delta")


def _fr(j, rwp, gof, fracs, names, n_obs=2000):
    return FrameRietveldResult(frame_index=j, axis_value=float(j), data_path=f"f{j}.xye",
                               rwp=rwp, gof=gof, refined_cells={}, phase_fractions=fracs,
                               phase_names=tuple(names), n_obs=n_obs)


def _anchor(frame, phases):
    specs = tuple(ALPHA if p == "alpha" else DELTA for p in phases)
    return Anchor(frame_index=frame, axis_value=float(frame), phase_specs=specs,
                  refined_cells={}, rwp=9.0, gof=1.0)


def _seg(inner, left_phases, right_phases):
    return Segment(left=_anchor(min(inner) - 1, left_phases),
                   right=_anchor(max(inner) + 1, right_phases), frame_indices=tuple(inner))


# --- frame_bic ---

def test_frame_bic_penalizes_more_phases():
    """同じ gof でも相数が多い方が bic 大 (パラメータ罰)。"""
    cfg = AnchorConfig(base_params=30, per_phase_params=12)
    one = _fr(0, 10.0, 1.0, {"alpha": 1.0}, ("alpha",))
    two = _fr(0, 10.0, 1.0, {"alpha": 0.5, "new_delta": 0.5}, ("alpha", "new_delta"))
    assert frame_bic(two, cfg) > frame_bic(one, cfg)


def test_frame_bic_infinite_for_failed():
    cfg = AnchorConfig()
    bad = FrameRietveldResult(frame_index=0, axis_value=0.0, data_path="f", rwp=float("inf"),
                              gof=float("inf"), refined_cells={}, phase_fractions={},
                              phase_names=("alpha",), refine_failed=True)
    assert frame_bic(bad, cfg) == float("inf")


# --- select_crossover: 核心の bic vs Rwp ---

def test_bic_crossover_locates_transition_not_frame0():
    """異相集合区間で bic crossover が真の転移点に一致 (Rwp なら全域多相になる所)。

    inner=(2,3,4,5): frame2,3 は delta 不在 (前方 alpha が同等), frame4,5 は delta 存在
    (前方 alpha が破綻)。後方 (alpha+delta) は全フレームで Rwp が僅かに低い (パラメータ増) ため、
    Rwp 毎フレーム最小なら全 4 フレームで多相を選ぶ。bic はパラメータ罰で frame2,3 を前方に残す。
    """
    cfg = AnchorConfig(base_params=30, per_phase_params=12, bic_tie=2.0)
    inner = [2, 3, 4, 5]
    seg = _seg(inner, ["alpha"], ["alpha", "new_delta"])
    # 前方 (alpha only): 転移後は破綻 (gof 3.0+)
    fwd = SegmentPass("forward", {
        2: _fr(2, 10.0, 1.00, {"alpha": 1.0}, ("alpha",)),
        3: _fr(3, 10.0, 1.00, {"alpha": 1.0}, ("alpha",)),
        4: _fr(4, 30.0, 3.00, {"alpha": 1.0}, ("alpha",)),
        5: _fr(5, 35.0, 3.50, {"alpha": 1.0}, ("alpha",)),
    })
    # 後方 (alpha+delta): 全フレームで Rwp 僅かに低い。delta 分率は R へ向け単調増
    bwd = SegmentPass("backward", {
        2: _fr(2, 9.9, 0.99, {"alpha": 0.98, "new_delta": 0.02}, ("alpha", "new_delta")),
        3: _fr(3, 9.9, 0.99, {"alpha": 0.97, "new_delta": 0.03}, ("alpha", "new_delta")),
        4: _fr(4, 10.0, 1.00, {"alpha": 0.70, "new_delta": 0.30}, ("alpha", "new_delta")),
        5: _fr(5, 10.0, 1.00, {"alpha": 0.50, "new_delta": 0.50}, ("alpha", "new_delta")),
    })
    choice = select_crossover(seg, fwd, bwd, cfg)
    assert choice.reason == "bic_crossover"
    # s=2: frame2,3 前方 / frame4,5 後方 → crossover_frame=3, onset=4
    assert choice.crossover_frame == 3
    assert choice.onset_frame == 4
    assert choice.monotonic is True

    # 対比: Rwp 毎フレーム最小なら全 4 フレームで後方 (多相) を選ぶ (偽相を全域へ)
    rwp_pick = [(fwd.results[j].rwp <= bwd.results[j].rwp) for j in inner]
    assert rwp_pick == [False, False, False, False]  # 全て後方が Rwp 低 → bic と不一致


def test_bic_crossover_assembles_monotonic_path():
    cfg = AnchorConfig(base_params=30, per_phase_params=12)
    inner = [2, 3, 4, 5]
    seg = _seg(inner, ["alpha"], ["alpha", "new_delta"])
    fwd = SegmentPass("forward", {
        2: _fr(2, 10.0, 1.00, {"alpha": 1.0}, ("alpha",)),
        3: _fr(3, 10.0, 1.00, {"alpha": 1.0}, ("alpha",)),
        4: _fr(4, 30.0, 3.00, {"alpha": 1.0}, ("alpha",)),
        5: _fr(5, 35.0, 3.50, {"alpha": 1.0}, ("alpha",)),
    })
    bwd = SegmentPass("backward", {
        2: _fr(2, 9.9, 0.99, {"alpha": 0.98, "new_delta": 0.02}, ("alpha", "new_delta")),
        3: _fr(3, 9.9, 0.99, {"alpha": 0.97, "new_delta": 0.03}, ("alpha", "new_delta")),
        4: _fr(4, 10.0, 1.00, {"alpha": 0.70, "new_delta": 0.30}, ("alpha", "new_delta")),
        5: _fr(5, 10.0, 1.00, {"alpha": 0.50, "new_delta": 0.50}, ("alpha", "new_delta")),
    })
    choice = select_crossover(seg, fwd, bwd, cfg)
    path = assemble_path(seg, fwd, bwd, choice)
    # frame2,3 = 前方 (alpha only), frame4,5 = 後方 (delta あり)
    assert path[2].phase_names == ("alpha",)
    assert path[3].phase_names == ("alpha",)
    assert "new_delta" in path[4].phase_fractions
    dvals = [path[j].phase_fractions.get("new_delta", 0.0) for j in inner]
    assert dvals == sorted(dvals)  # 単調増


def test_same_phase_set_uses_rwp_per_frame():
    """相集合が同一なら bic でなく Rwp 毎フレーム最小 (パラメータ数同一で公平)。"""
    cfg = AnchorConfig()
    inner = [2, 3]
    seg = _seg(inner, ["alpha"], ["alpha"])  # 両アンカー同一相集合
    fwd = SegmentPass("forward", {2: _fr(2, 12.0, 1.2, {"alpha": 1.0}, ("alpha",)),
                                  3: _fr(3, 9.0, 1.0, {"alpha": 1.0}, ("alpha",))})
    bwd = SegmentPass("backward", {2: _fr(2, 10.0, 1.1, {"alpha": 1.0}, ("alpha",)),
                                   3: _fr(3, 11.0, 1.1, {"alpha": 1.0}, ("alpha",))})
    choice = select_crossover(seg, fwd, bwd, cfg)
    assert choice.reason == "rwp_per_frame"
    path = assemble_path(seg, fwd, bwd, choice)
    assert path[2].rwp == 10.0  # 後方が低い
    assert path[3].rwp == 9.0   # 前方が低い


def test_single_direction_uses_available_pass():
    """片パスのみ (端点区間) は存在する方を全採用。"""
    cfg = AnchorConfig()
    seg = Segment(left=None, right=_anchor(2, ["alpha", "new_delta"]),
                  frame_indices=(0, 1), one_sided=True)
    bwd = SegmentPass("backward", {
        0: _fr(0, 10.0, 1.0, {"alpha": 0.9, "new_delta": 0.1}, ("alpha", "new_delta")),
        1: _fr(1, 10.0, 1.0, {"alpha": 0.8, "new_delta": 0.2}, ("alpha", "new_delta")),
    })
    choice = select_crossover(seg, SegmentPass("forward", {}), bwd, cfg)
    assert choice.reason == "single_direction"
    path = assemble_path(seg, SegmentPass("forward", {}), bwd, choice)
    assert set(path) == {0, 1}
    assert path[0].phase_names == ("alpha", "new_delta")


def test_deterministic():
    cfg = AnchorConfig()
    inner = [2, 3, 4, 5]
    seg = _seg(inner, ["alpha"], ["alpha", "new_delta"])
    fwd = SegmentPass("forward", {j: _fr(j, 10.0 + j, 1.0 + 0.5 * (j >= 4),
                                         {"alpha": 1.0}, ("alpha",)) for j in inner})
    bwd = SegmentPass("backward", {j: _fr(j, 9.9, 0.99, {"alpha": 0.6, "new_delta": 0.4},
                                          ("alpha", "new_delta")) for j in inner})
    assert select_crossover(seg, fwd, bwd, cfg) == select_crossover(seg, fwd, bwd, cfg)
