"""M10 anchor/segment.py — 区間構成 + 双方向 warm-start 逐次精密化テスト (stub runner)。"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.anchor.model import Anchor
from tsumugin.insitu.anchor.segment import (
    build_segments,
    refine_segment_backward,
    refine_segment_forward,
)
from tsumugin.insitu.model import FrameSpec

ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
DELTA = PhaseSpec(structure_path="delta.cif", phase_name="new_delta")


def _frames(n):
    return [FrameSpec(data_path=f"f{i}.xye", axis_value=float(i)) for i in range(n)]


def _anchor(frame, phases=("alpha",), cell=(5.0, 5.0, 5.0, 90, 90, 90), fractions=None):
    specs = tuple(ALPHA if p == "alpha" else DELTA for p in phases)
    return Anchor(frame_index=frame, axis_value=float(frame), phase_specs=specs,
                  refined_cells={p: cell for p in phases}, rwp=9.0, gof=1.0,
                  phase_fractions=fractions if fractions is not None else {})


def _result(rwp, cells, fracs, *, wfracs=None, wfrac_esd=None, cesd=None):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0, refined_cells=cells,
        validity=ValidityReport(passed=True), phase_fractions=fracs,
        phase_weight_fractions=wfracs or {}, phase_weight_fraction_esd=wfrac_esd or {},
        cell_esd=cesd or {},
    )


# --- build_segments ---

def test_build_segments_between_anchors():
    anchors = (_anchor(1), _anchor(5))
    segs = build_segments(anchors, n_frames=7)
    # 先頭端点 (0), 中間 (2,3,4), 末尾端点 (6)
    assert [s.frame_indices for s in segs] == [(0,), (2, 3, 4), (6,)]
    assert segs[0].left is None and segs[0].one_sided
    assert segs[1].left.frame_index == 1 and segs[1].right.frame_index == 5
    assert segs[2].right is None and segs[2].one_sided


def test_build_segments_skips_adjacent_anchors():
    """隣接アンカー (内側なし) は区間を作らない。"""
    anchors = (_anchor(2), _anchor(3))
    segs = build_segments(anchors, n_frames=4)
    # frame0-1 (先頭端点), frame2-3 は隣接で内側なし → 中間区間なし
    assert [s.frame_indices for s in segs] == [(0, 1)]


def test_build_segments_single_anchor_both_endpoints():
    anchors = (_anchor(2),)
    segs = build_segments(anchors, n_frames=5)
    assert [s.frame_indices for s in segs] == [(0, 1), (3, 4)]
    assert segs[0].right.frame_index == 2 and segs[0].left is None
    assert segs[1].left.frame_index == 2 and segs[1].right is None


def test_build_segments_all_anchors_no_inner():
    anchors = tuple(_anchor(i) for i in range(3))
    assert build_segments(anchors, n_frames=3) == ()


# --- refine_segment_forward / backward ---

def test_forward_warm_starts_from_left_anchor():
    """前方パスは左アンカーの相集合/セルで昇順に warm-start。"""
    left = _anchor(1, cell=(5.0, 5.0, 5.0, 90, 90, 90))
    right = _anchor(5, phases=("alpha", "new_delta"))
    seg = build_segments((left, right), 7)[1]  # 中間 (2,3,4)
    seen = []

    def runner(frame, phases, cells):
        idx = int(frame.axis_value)
        seen.append((idx, tuple(p.phase_name for p in phases), cells["alpha"][0]))
        # セルを少しずつ動かして warm-start 伝播を確認
        new = 5.0 + 0.1 * idx
        return _result(8.0, {"alpha": (new, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    sp = refine_segment_forward(seg, _frames(7), runner)
    assert sp.direction == "forward"
    assert sorted(sp.results) == [2, 3, 4]
    # 昇順・左アンカー相集合 (alpha) で実行
    assert [s[0] for s in seen] == [2, 3, 4]
    assert all(s[1] == ("alpha",) for s in seen)
    # frame2 は左アンカーセル 5.0、frame3 は frame2 の精密化セル 5.2 を引き継ぐ
    assert seen[0][2] == 5.0
    assert abs(seen[1][2] - 5.2) < 1e-9


def test_backward_warm_starts_from_right_anchor_descending():
    """後方パスは右アンカーの相集合 (delta 含む) で降順 warm-start。"""
    left = _anchor(1)
    right = _anchor(5, phases=("alpha", "new_delta"))
    seg = build_segments((left, right), 7)[1]
    seen = []

    def runner(frame, phases, cells):
        seen.append((int(frame.axis_value), tuple(p.phase_name for p in phases)))
        names = [p.phase_name for p in phases]
        return _result(8.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
                       {"alpha": 0.4, "new_delta": 0.6})

    sp = refine_segment_backward(seg, _frames(7), runner)
    assert sp.direction == "backward"
    assert [s[0] for s in seen] == [4, 3, 2]  # 降順
    assert all(s[1] == ("alpha", "new_delta") for s in seen)  # 右アンカー相集合
    assert "new_delta" in sp.results[4].phase_fractions


def test_forward_empty_when_no_left_anchor():
    """先頭端点区間 (左アンカーなし) は前方パス空。"""
    seg = build_segments((_anchor(3),), 5)[0]  # 先頭端点 (0,1,2), left=None

    def runner(frame, phases, cells):
        raise AssertionError("前方パスは呼ばれないはず")

    assert refine_segment_forward(seg, _frames(5), runner).results == {}


def test_backward_empty_when_no_right_anchor():
    """末尾端点区間 (右アンカーなし) は後方パス空。"""
    seg = build_segments((_anchor(1),), 5)[1]  # 末尾端点 (2,3,4), right=None
    assert refine_segment_backward(seg, _frames(5), lambda *a: None).results == {}


# --- 相分率ウォームスタート (Issue #96) ---

def test_forward_carries_phase_fractions_like_cells():
    """前方パスは**セルと同様に相分率も**引き継ぐ (Issue #96)。

    Issue #82 の分率ウォームスタートは M9 逐次経路にしか配線されておらず、M10 双方向パスは
    セルしか運んでいなかった。実測 (K2Mn[Fe(CN)6] 247 フレーム) で 9 フレームが seed 値
    (2 相の 50/50) に厳密に張り付き、うち 6 連続がドーム頂点直前にあった。
    """
    left = _anchor(1, phases=("alpha", "new_delta"), fractions={"alpha": 0.7, "new_delta": 0.3})
    right = _anchor(5, phases=("alpha", "new_delta"))
    seg = build_segments((left, right), 7)[1]  # 中間 (2,3,4)
    seen = []
    call = {"n": 0}

    def runner(frame, phases, cells, initial_fractions=None):
        seen.append((int(frame.axis_value), initial_fractions))
        i = call["n"]
        call["n"] += 1
        frac = 0.4 + 0.1 * i  # 0.4, 0.5, 0.6
        return _result(8.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in ("alpha", "new_delta")},
                       {"alpha": 1.0 - frac, "new_delta": frac})

    refine_segment_forward(seg, _frames(7), runner)
    # frame2 は左アンカーの分率を種にする
    assert seen[0] == (2, {"alpha": 0.7, "new_delta": 0.3})
    # frame3 以降は直前フレームの精密化分率を引き継ぐ (セルと同時進行)
    assert seen[1] == (3, {"alpha": 0.6, "new_delta": 0.4})
    assert seen[2] == (4, {"alpha": 0.5, "new_delta": 0.5})


def test_backward_carries_phase_fractions_from_right_anchor():
    """後方パスも右アンカーの分率を種に降順で引き継ぐ (Issue #96)。"""
    left = _anchor(1)
    right = _anchor(5, phases=("alpha", "new_delta"), fractions={"alpha": 0.2, "new_delta": 0.8})
    seg = build_segments((left, right), 7)[1]
    seen = []

    def runner(frame, phases, cells, initial_fractions=None):
        seen.append((int(frame.axis_value), initial_fractions))
        return _result(8.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in ("alpha", "new_delta")},
                       {"alpha": 0.3, "new_delta": 0.7})

    refine_segment_backward(seg, _frames(7), runner)
    assert seen[0] == (4, {"alpha": 0.2, "new_delta": 0.8})  # 右アンカーの分率
    assert seen[1] == (3, {"alpha": 0.3, "new_delta": 0.7})  # frame4 の精密化分率
    assert seen[2] == (2, {"alpha": 0.3, "new_delta": 0.7})


def test_anchor_without_fractions_seeds_nothing():
    """分率を持たないアンカー (単相 GSAS 結果は phase_fractions 空) は種を渡さない。"""
    left = _anchor(1)  # phase_fractions={}
    right = _anchor(5)
    seg = build_segments((left, right), 7)[1]
    seen = []

    def runner(frame, phases, cells, initial_fractions="UNSET"):
        seen.append(initial_fractions)
        return _result(8.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {})

    refine_segment_forward(seg, _frames(7), runner)
    assert seen == ["UNSET", "UNSET", "UNSET"]


# --- 重量分率 + esd 貫通 (M10 出版値) ---

def test_forward_pass_carries_weight_fractions_and_esd():
    """前方パスは AutoRietveldResult の重量分率 + esd + 格子 esd を FrameRietveldResult へ運ぶ。"""
    left = _anchor(1, phases=("alpha", "new_delta"))
    right = _anchor(5, phases=("alpha", "new_delta"))
    seg = build_segments((left, right), 7)[1]  # 中間 (2,3,4)

    def runner(frame, phases, cells):
        names = [p.phase_name for p in phases]
        return _result(
            8.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
            {"alpha": 0.4, "new_delta": 0.6},
            wfracs={"alpha": 0.55, "new_delta": 0.45},
            wfrac_esd={"alpha": 0.006, "new_delta": 0.006},
            cesd={"alpha": (0.001, 0.001, 0.002, 0.0, 0.0, 0.0),
                  "new_delta": (0.003, 0.003, 0.004, 0.0, 0.0, 0.0)},
        )

    sp = refine_segment_forward(seg, _frames(7), runner)
    fr = sp.results[2]
    assert fr.phase_weight_fractions == {"alpha": 0.55, "new_delta": 0.45}
    assert fr.phase_weight_fraction_esd == {"alpha": 0.006, "new_delta": 0.006}
    assert fr.cell_esd["new_delta"] == (0.003, 0.003, 0.004, 0.0, 0.0, 0.0)


def test_frame_result_weight_fractions_empty_when_runner_omits():
    """重量分率を返さない runner (present-guard) では空 dict に縮退する (0.0 の偽値を捏造しない)。"""
    left = _anchor(1)
    right = _anchor(5)
    seg = build_segments((left, right), 7)[1]

    def runner(frame, phases, cells):
        return _result(8.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    sp = refine_segment_forward(seg, _frames(7), runner)
    fr = sp.results[2]
    assert fr.phase_weight_fractions == {}
    assert fr.cell_esd == {}


def test_three_arg_runner_still_works_in_directional_pass():
    """3 引数 runner (既存スタブ/カスタム) は TypeError なく従来通り動く (非破壊)。"""
    left = _anchor(1, phases=("alpha", "new_delta"), fractions={"alpha": 0.7, "new_delta": 0.3})
    right = _anchor(5, phases=("alpha", "new_delta"))
    seg = build_segments((left, right), 7)[1]
    arities = []

    def runner(frame, phases, cells):  # 3 引数のみ
        arities.append(3)
        return _result(8.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in ("alpha", "new_delta")},
                       {"alpha": 0.5, "new_delta": 0.5})

    sp = refine_segment_forward(seg, _frames(7), runner)
    assert arities == [3, 3, 3]
    assert sorted(sp.results) == [2, 3, 4]
