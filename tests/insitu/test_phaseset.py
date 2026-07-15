"""相集合の完全性チェック (Issue #84) の numpy-only 決定論テスト。

計量が近い相 (mono/cubic/tetra 等 cubic 派生) は互いの強度を吸収し合う。相集合から 1 相を
外すと残った相が肩代わりし、**Rwp 上は良好なまま物理的に誤った描像**を生む。この回帰は
K₂Mn[Fe(CN)₆] operando 実データで実測された tetra 分率の振動 (0.42→0.17→0.70→0.04→0.63,
Rwp は終始 ~8% で良好) で、`suggest_phase_set_completion`/`flag_nonmonotonic_fraction` が
拾うべき対象。fake `FrameRietveldResult` の構築パターンは tests/insitu/test_repair.py に倣う。
"""

from __future__ import annotations

from tsumugin.insitu.model import FrameRietveldResult, SequentialRietveldResult
from tsumugin.insitu.phaseset import (
    flag_nonmonotonic_fraction,
    suggest_phase_set_completion,
)


def _frame(i, fractions, *, phase_names=None, rwp=8.0):
    names = phase_names if phase_names is not None else tuple(fractions)
    return FrameRietveldResult(
        frame_index=i,
        axis_value=float(i),
        data_path=f"f{i}.xrdml",
        rwp=rwp,
        gof=1.0,
        refined_cells={},
        phase_fractions=fractions,
        phase_names=names,
    )


# ---------------------------------------------------------------------------
# suggest_phase_set_completion
# ---------------------------------------------------------------------------


def test_completeness_all_frames_same_set_is_complete():
    frames = tuple(
        _frame(i, {"mono": 0.5, "cubic": 0.5}, phase_names=("mono", "cubic")) for i in range(4)
    )
    result = SequentialRietveldResult(frames=frames)
    report = suggest_phase_set_completion(result)
    assert report.is_complete is True
    assert report.frames_with_missing == ()
    assert set(report.union) == {"mono", "cubic"}


def test_completeness_some_frames_missing_a_phase():
    frames = (
        _frame(0, {"mono": 1.0}, phase_names=("mono",)),
        _frame(1, {"cubic": 0.6, "tetra": 0.4}, phase_names=("cubic", "tetra")),
        _frame(2, {"cubic": 1.0}, phase_names=("cubic",)),
    )
    result = SequentialRietveldResult(frames=frames)
    report = suggest_phase_set_completion(result)
    assert report.is_complete is False
    assert set(report.union) == {"mono", "cubic", "tetra"}
    missing_by_frame = dict(report.frames_with_missing)
    assert set(missing_by_frame[0]) == {"cubic", "tetra"}
    assert set(missing_by_frame[1]) == {"mono"}
    assert set(missing_by_frame[2]) == {"mono", "tetra"}
    assert "Rwp" in report.recommendation


# ---------------------------------------------------------------------------
# flag_nonmonotonic_fraction
# ---------------------------------------------------------------------------


def test_real_regression_oscillation_is_flagged():
    # 実測 K2Mn[Fe(CN)6] 充電域: mono を外した cubic+tetra 限定フィットで tetra が振動した。
    tetra_fracs = [0.42, 0.17, 0.70, 0.04, 0.63]
    frames = tuple(
        _frame(i, {"cubic": 1.0 - t, "tetra": t}, phase_names=("cubic", "tetra"))
        for i, t in enumerate(tetra_fracs)
    )
    result = SequentialRietveldResult(frames=frames)
    report = flag_nonmonotonic_fraction(result, "tetra")
    assert report.turning_points > 2
    assert report.flagged is True
    assert report.fractions == tuple(tetra_fracs)


def test_correct_single_dome_is_not_flagged():
    # 全3相投入後の正しい描像: 単一ドーム (0 -> 0.58 -> 0)。
    dome_fracs = [0.0, 0.2, 0.58, 0.2, 0.0]
    frames = tuple(
        _frame(i, {"tetra": t, "mono": 1.0 - t}, phase_names=("mono", "tetra"))
        for i, t in enumerate(dome_fracs)
    )
    result = SequentialRietveldResult(frames=frames)
    report = flag_nonmonotonic_fraction(result, "tetra")
    assert report.turning_points == 1
    assert report.flagged is False


def test_monotonic_rise_is_not_flagged():
    fracs = [0.0, 0.3, 0.6, 0.9]
    frames = tuple(_frame(i, {"alpha": f}, phase_names=("alpha",)) for i, f in enumerate(fracs))
    result = SequentialRietveldResult(frames=frames)
    report = flag_nonmonotonic_fraction(result, "alpha")
    assert report.turning_points == 0
    assert report.flagged is False


def test_noise_suppression_small_wiggles_do_not_flag():
    # 滑らかなドームに ±0.02 の小刻みなノイズが乗っても振幅フィルタで無視される。
    fracs = [0.0, 0.3, 0.6, 0.58, 0.6, 0.62, 0.3, 0.0]
    frames = tuple(_frame(i, {"alpha": f}, phase_names=("alpha",)) for i, f in enumerate(fracs))
    result = SequentialRietveldResult(frames=frames)
    report = flag_nonmonotonic_fraction(result, "alpha", min_amplitude=0.1)
    assert report.turning_points == 1
    assert report.flagged is False


def test_fewer_than_three_frames_not_flagged():
    frames = tuple(_frame(i, {"alpha": 0.5 + 0.1 * i}, phase_names=("alpha",)) for i in range(2))
    result = SequentialRietveldResult(frames=frames)
    report = flag_nonmonotonic_fraction(result, "alpha")
    assert report.flagged is False
    assert report.turning_points == 0


def test_missing_phase_treated_as_zero_fraction():
    frames = (
        _frame(0, {"alpha": 1.0}, phase_names=("alpha",)),
        _frame(1, {"alpha": 0.5, "beta": 0.5}, phase_names=("alpha", "beta")),
        _frame(2, {"alpha": 1.0}, phase_names=("alpha",)),
    )
    result = SequentialRietveldResult(frames=frames)
    report = flag_nonmonotonic_fraction(result, "beta")
    assert report.fractions == (0.0, 0.5, 0.0)
