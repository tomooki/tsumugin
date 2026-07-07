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


def _anchor(frame, phases=("alpha",), cell=(5.0, 5.0, 5.0, 90, 90, 90)):
    specs = tuple(ALPHA if p == "alpha" else DELTA for p in phases)
    return Anchor(frame_index=frame, axis_value=float(frame), phase_specs=specs,
                  refined_cells={p: cell for p in phases}, rwp=9.0, gof=1.0)


def _result(rwp, cells, fracs):
    return AutoRietveldResult(stage_results=(), final_rwp=rwp, final_gof=1.0, refined_cells=cells,
                              validity=ValidityReport(passed=True), phase_fractions=fracs)


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
