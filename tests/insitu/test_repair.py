"""M-later insitu.repair の純テスト (fake runner, GSAS 非依存)。

不連続点検出 (`detect_discontinuities`)・連続長区分 (`classify`, 参考情報のみ)・近傍 warm-start
修復 (`repair_isolated`) の決定論的な制御ロジックを検証する (Issue #81)。fake runner のパターンは
tests/insitu/test_engine.py に倣う。

**修復の分類は経験的**: 全フラグフレームに warm-start を試し、改善しなければ第3層送り。連続長は
ゲートしない (実測 f160-172 は連続だが修復可能・f12 は単独だがモデル欠陥、両方向に反証済)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameRietveldResult, FrameSpec, SequentialRietveldResult
from tsumugin.insitu.repair import (
    Discontinuity,
    classify,
    detect_discontinuities,
    discontinuities_from_frames,
    repair_isolated,
)
from tsumugin.store.ledger import Ledger


def _frame(
    i,
    rwp,
    fractions,
    *,
    cells=None,
    axis=None,
    phase_names=None,
    refine_failed=False,
):
    cells = cells or {name: (5.0 + 0.01 * i, 5.0, 5.0, 90.0, 90.0, 90.0) for name in fractions}
    names = phase_names if phase_names is not None else tuple(fractions)
    return FrameRietveldResult(
        frame_index=i,
        axis_value=axis if axis is not None else float(i),
        data_path=f"f{i}.xrdml",
        rwp=rwp,
        gof=1.0,
        refined_cells=cells,
        phase_fractions=fractions,
        phase_names=names,
        refine_failed=refine_failed,
    )


def _result(*, rwp, cells, fractions, gof=1.0, valid=True):
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=rwp,
        final_gof=gof,
        refined_cells=cells,
        validity=ValidityReport(passed=valid),
        phase_fractions=fractions,
    )


# ---------------------------------------------------------------------------
# detect_discontinuities
# ---------------------------------------------------------------------------


def test_detect_clean_series_no_flags():
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(6))
    result = SequentialRietveldResult(frames=frames)
    assert detect_discontinuities(result) == ()


def test_detect_rwp_spike_flags_that_frame_only():
    rwps = [8.0, 8.1, 15.0, 8.0, 7.9, 8.2]
    frames = tuple(_frame(i, r, {"alpha": 1.0}) for i, r in enumerate(rwps))
    result = SequentialRietveldResult(frames=frames)
    found = detect_discontinuities(result, rwp_delta=1.8)
    assert [d.frame_index for d in found] == [2]
    assert "rwp_local_median" in found[0].reasons


def test_detect_rwp_abs_threshold():
    rwps = [5.0, 5.0, 9.5, 5.0, 5.0]
    frames = tuple(_frame(i, r, {"alpha": 1.0}) for i, r in enumerate(rwps))
    result = SequentialRietveldResult(frames=frames)
    found = detect_discontinuities(result, rwp_abs=9.0, rwp_delta=100.0)
    assert [d.frame_index for d in found] == [2]
    assert "rwp_abs" in found[0].reasons


def test_detect_fraction_spike():
    # 相分率が滑らかに推移する中、フレーム3だけ両隣補間から大きく外れる。
    fracs = [
        {"alpha": 1.0, "beta": 0.0},
        {"alpha": 0.9, "beta": 0.1},
        {"alpha": 0.8, "beta": 0.2},
        {"alpha": 0.43, "beta": 0.57},  # 本来 ~0.7/0.3 付近のはずが飛ぶ
        {"alpha": 0.6, "beta": 0.4},
        {"alpha": 0.5, "beta": 0.5},
    ]
    frames = tuple(_frame(i, 8.0, f) for i, f in enumerate(fracs))
    result = SequentialRietveldResult(frames=frames)
    found = detect_discontinuities(result, rwp_delta=100.0, frac_delta=0.15)
    assert [d.frame_index for d in found] == [3]
    assert "fraction_deviation" in found[0].reasons


def test_detect_first_and_last_frame_only_use_rwp_criteria():
    # 先頭/末尾は両隣が揃わないため fraction_deviation は適用されない。rwp 基準のみ有効。
    # frame0/frame3 (境界) は隣接補間からの見かけ上の乖離があっても検出対象外、内部 (1,2) は滑らか。
    fracs = [
        {"alpha": 0.95, "beta": 0.05},  # frame0 (先頭): 両隣なし
        {"alpha": 0.70, "beta": 0.30},
        {"alpha": 0.50, "beta": 0.50},
        {"alpha": 0.05, "beta": 0.95},  # frame3 (末尾): 両隣なし
    ]
    frames = tuple(_frame(i, 8.0, f) for i, f in enumerate(fracs))
    result = SequentialRietveldResult(frames=frames)
    found = detect_discontinuities(result, rwp_delta=100.0, frac_delta=0.15)
    assert found == ()


# ---------------------------------------------------------------------------
# classify
# ---------------------------------------------------------------------------


def _disc(i, rwp=10.0):
    return Discontinuity(frame_index=i, axis_value=float(i), rwp=rwp, reasons=("rwp_abs",))


def test_classify_single_flagged_is_singleton():
    singles, runs = classify((_disc(3),), n_frames=10)
    assert [d.frame_index for d in singles] == [3]
    assert runs == ()


def test_classify_three_consecutive_is_one_run():
    discs = (_disc(4), _disc(5), _disc(6))
    singles, runs = classify(discs, n_frames=10)
    assert singles == ()
    assert len(runs) == 1
    assert [d.frame_index for d in runs[0]] == [4, 5, 6]


def test_classify_mixture_of_singletons_and_runs():
    discs = (_disc(1), _disc(5), _disc(6), _disc(10))
    singles, runs = classify(discs, n_frames=15)
    assert [d.frame_index for d in singles] == [1, 10]
    assert len(runs) == 1
    assert [d.frame_index for d in runs[0]] == [5, 6]


def test_classify_min_block_override():
    # min_block=3 なら 2 連続はまだ単発扱い。
    discs = (_disc(5), _disc(6))
    singles, runs = classify(discs, n_frames=15, min_block=3)
    assert [d.frame_index for d in singles] == [5, 6]
    assert runs == ()


# ---------------------------------------------------------------------------
# repair_isolated
# ---------------------------------------------------------------------------


ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
GOOD_CELL = {"alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)}


def _base_frames(n=5):
    return [FrameSpec(data_path=f"f{i}.xrdml", axis_value=float(i)) for i in range(n)]


def test_repair_adopts_when_runner_improves_rwp():
    frames = _base_frames(5)
    # frame2 だけ Rwp が飛んでいる孤立スパイク。隣接 (1,3) は良好。
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)
    assert [d.frame_index for d in disc] == [2]

    calls = []

    def runner(frame, phases, initial_cells):
        calls.append((frame.data_path, tuple(p.phase_name for p in phases), initial_cells))
        return _result(rwp=7.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    assert len(report.repairs) == 1
    rep = report.repairs[0]
    assert rep.frame_index == 2
    assert rep.rwp_before == 15.0
    assert rep.rwp_after == 7.0
    assert rep.rwp_after < rep.rwp_before
    assert rep.source in ("L", "R")
    assert report.needs_model_revision == ()
    # runner はフレーム2 のみに対して呼ばれる (左右2回まで試す)。
    assert all(c[0] == "f2.xrdml" for c in calls)
    assert len(calls) == 2  # 左右両方を試す


def test_repair_passes_neighbour_refined_cells_as_initial_cells():
    frames = _base_frames(5)
    left_cell = {"alpha": (5.11, 5.0, 5.0, 90.0, 90.0, 90.0)}
    right_cell = {"alpha": (5.22, 5.0, 5.0, 90.0, 90.0, 90.0)}
    fr_results = (
        _frame(0, 8.0, {"alpha": 1.0}, cells=left_cell),
        _frame(1, 8.0, {"alpha": 1.0}, cells=left_cell),
        _frame(2, 15.0, {"alpha": 1.0}, cells=GOOD_CELL),
        _frame(3, 8.0, {"alpha": 1.0}, cells=right_cell),
        _frame(4, 8.0, {"alpha": 1.0}, cells=right_cell),
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)

    seen_initial = []

    def runner(frame, phases, initial_cells):
        seen_initial.append(initial_cells)
        return _result(rwp=7.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    repair_isolated(frames, result, [ALPHA], runner, disc)

    assert left_cell in seen_initial
    assert right_cell in seen_initial


def test_repair_not_improved_escalates_to_needs_model_revision():
    """warm-start に機会を与えたが改善しない = モデル欠陥の経験的証拠 → 第3層送り (実測 f12 型)。"""
    frames = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)

    def runner(frame, phases, initial_cells):
        # 改善しない (むしろ悪化) = 近傍が同じ欠陥を共有している
        return _result(rwp=16.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    assert report.repairs == ()
    assert report.needs_model_revision == (2,)
    # 元の結果は変更されない (非破壊)
    assert result.frames[2].rwp == 15.0


def test_repair_rwp_tol_gate():
    frames = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)

    def runner(frame, phases, initial_cells):
        # わずかな改善のみ (rwp_tol=0.1 未満) → 採用しない
        return _result(rwp=14.95, cells=GOOD_CELL, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc, rwp_tol=0.1)
    assert report.repairs == ()
    assert report.needs_model_revision == (2,)


# ---------------------------------------------------------------------------
# 出版値 (重量分率 ± esd・格子 esd) の引き継ぎ (Issue #96 レビュー 第2巡 HIGH)
# ---------------------------------------------------------------------------


def test_repair_carries_publication_values_from_the_trial_result():
    """★修復したフレームの**出版値**が `FrameRepair` に載ること。

    **修復対象のフレームこそ出版値が要る**: ③ は `check_phase_set` の seed_pinned/frozen から
    `target_frames` を組んで修復する — 実測では**転移ドーム頂点の直前 6 フレーム (125-130)**、
    つまり論文の主要値そのものである。修復後に Scale (`phase_fractions`) しか持たなければ、
    ③ は「1.39-1.62 倍誤る値を報告する」か「直したばかりのフレームの出版値が無い」の二択に
    追い込まれる。
    """
    frames = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)

    def runner(frame, phases, initial_cells):
        return AutoRietveldResult(
            stage_results=(),
            final_rwp=7.0,
            final_gof=1.0,
            refined_cells=GOOD_CELL,
            validity=ValidityReport(passed=True),
            phase_fractions={"cubic": 0.656, "tetra": 0.344},
            phase_weight_fractions={"cubic": 0.472, "tetra": 0.528},
            phase_weight_fraction_esd={"cubic": 0.006, "tetra": 0.006},
            cell_esd={"alpha": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
        )

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    rep = report.repairs[0]
    assert rep.phase_fractions == {"cubic": 0.656, "tetra": 0.344}  # Scale は従来通り
    assert rep.phase_weight_fractions == {"cubic": 0.472, "tetra": 0.528}
    assert rep.phase_weight_fraction_esd == {"cubic": 0.006, "tetra": 0.006}
    assert rep.cell_esd == {"alpha": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)}


def test_repair_publication_values_degrade_to_empty_when_the_trial_has_none():
    """出版値を持たない runner (スタブ/共分散なし) では空 dict へ縮退する (後方互換)。

    **0.0 で埋めない**: 重量分率は GSAS が全相まとめて算出した比であり、欠測を 0.0 で埋めると
    「その相は 0 wt%」という**測定していない主張**になる (`engine._publication_of` と同一規律)。
    """
    frames = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)

    def runner(frame, phases, initial_cells):
        return _result(rwp=7.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    rep = repair_isolated(frames, result, [ALPHA], runner, disc).repairs[0]

    assert rep.phase_weight_fractions == {}
    assert rep.phase_weight_fraction_esd == {}
    assert rep.cell_esd == {}


def test_consecutive_run_is_still_attempted_and_repaired():
    """連続フラグ区間も run の外側の良好フレームから修復を試みる (実測 f160-172 の回帰テスト)。

    run-length で「系統ブロック → 修復不可」と門前払いしていた旧実装が、実データで
    f160/f164/f168/f172 (連続) を f156/f176 から修復できた事実に反証されたことによる (Issue #81)。
    """
    frames = _base_frames(6)
    # 連続 3 フレーム (2,3,4) がフラグ。良好な近傍は run の外側 (1 と 5) にある。
    rwps = [8.0, 8.0, 15.0, 16.0, 15.5, 8.0]
    outer_cell = {"alpha": (5.44, 5.0, 5.0, 90.0, 90.0, 90.0)}
    fr_results = tuple(
        _frame(i, r, {"alpha": 1.0}, cells=(outer_cell if i in (0, 1, 5) else GOOD_CELL))
        for i, r in enumerate(rwps)
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_abs=9.0)
    assert [d.frame_index for d in disc] == [2, 3, 4]

    calls = []

    def runner(frame, phases, initial_cells):
        calls.append((frame.data_path, initial_cells))
        return _result(rwp=7.5, cells=outer_cell, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    # 連続でも全フレームが試され、改善したので全て修復される。
    assert [r.frame_index for r in report.repairs] == [2, 3, 4]
    assert report.needs_model_revision == ()
    # runner は 3 フレーム × 左右 2 方向 = 6 回呼ばれ、常に run の外側の良好セルで warm-start する。
    assert [c[0] for c in calls] == ["f2.xrdml"] * 2 + ["f3.xrdml"] * 2 + ["f4.xrdml"] * 2
    assert all(c[1] == outer_cell for c in calls)
    # 連続長は参考情報としてのみ報告される (ゲートには使わない)。
    assert report.systematic_hint == ((2, 3, 4),)


def test_consecutive_run_that_does_not_improve_is_escalated():
    """連続区間でも「試して改善しなければ」第3層送り — 判定は連続長でなく経験的結果による。"""
    frames = _base_frames(6)
    rwps = [8.0, 8.0, 15.0, 16.0, 15.5, 8.0]
    fr_results = tuple(_frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate(rwps))
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_abs=9.0)

    calls = []

    def runner(frame, phases, initial_cells):
        calls.append(frame.data_path)
        return _result(rwp=17.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    assert report.repairs == ()
    assert report.needs_model_revision == (2, 3, 4)
    assert calls  # 門前払いせず、必ず機会を与えた上でのエスカレーション
    assert report.systematic_hint == ((2, 3, 4),)


def test_mixed_repairable_and_model_defect_classified_empirically():
    """単発でも改善しなければ第3層送り、連続でも改善すれば修復 — 両方向で連続長と一致しない。"""
    frames = _base_frames(8)
    rwps = [8.0, 15.0, 8.0, 8.0, 15.0, 16.0, 15.5, 8.0]
    fr_results = tuple(_frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate(rwps))
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_abs=9.0)
    assert [d.frame_index for d in disc] == [1, 4, 5, 6]

    def runner(frame, phases, initial_cells):
        # 単発の f1 (実測 f12 型のモデル欠陥) は改善せず、連続の f4-6 (実測 f160-172 型) は改善する。
        if frame.data_path == "f1.xrdml":
            return _result(rwp=15.5, cells=GOOD_CELL, fractions={"alpha": 1.0})
        return _result(rwp=8.2, cells=GOOD_CELL, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    # run-length ベースの旧実装なら真逆の結論 (1=修復対象 / 4,5,6=修復不可) を出していた。
    assert [r.frame_index for r in report.repairs] == [4, 5, 6]
    assert report.needs_model_revision == (1,)
    assert report.systematic_hint == ((4, 5, 6),)


def test_no_good_neighbour_escalated_without_runner_call():
    """良好な近傍が左右どちらにも無ければ試せない → runner を呼ばずに第3層送り。"""
    frames = _base_frames(3)
    # 全フレームがフラグ → どの方向にも「フラグなし」のフレームが存在しない。
    fr_results = tuple(_frame(i, 15.0, {"alpha": 1.0}, cells=GOOD_CELL) for i in range(3))
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_abs=9.0)
    assert [d.frame_index for d in disc] == [0, 1, 2]

    calls = []

    def runner(frame, phases, initial_cells):
        calls.append(frame.data_path)
        return _result(rwp=7.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    assert report.repairs == ()
    assert report.needs_model_revision == (0, 1, 2)
    assert calls == []  # 起点にできる良好フレームが無いので試行そのものが成立しない


def test_ledger_entries_appended_on_adopt_and_reject():
    frames = _base_frames(6)
    rwps = [8.0, 15.0, 8.0, 8.0, 15.0, 16.0]
    fr_results = tuple(_frame(i, r, {"alpha": 1.0}, cells=GOOD_CELL) for i, r in enumerate(rwps))
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_abs=9.0)
    assert [d.frame_index for d in disc] == [1, 4, 5]

    ledger = Ledger()

    def runner(frame, phases, initial_cells):
        # f1 は改善、f4/f5 は改善しない → adopted と rejected が両方出る
        if frame.data_path == "f1.xrdml":
            return _result(rwp=7.0, cells=GOOD_CELL, fractions={"alpha": 1.0})
        return _result(rwp=17.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    repair_isolated(frames, result, [ALPHA], runner, disc, ledger=ledger)

    kinds = [e.kind for e in ledger.entries]
    assert "insitu_repair_adopted" in kinds
    assert "insitu_repair_rejected" in kinds
    assert ledger.verify()


def test_ledger_records_no_neighbour_escalation():
    frames = _base_frames(2)
    fr_results = tuple(_frame(i, 15.0, {"alpha": 1.0}, cells=GOOD_CELL) for i in range(2))
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_abs=9.0)

    ledger = Ledger()

    def runner(frame, phases, initial_cells):
        raise AssertionError("良好近傍が無いので runner は呼ばれないはず")

    report = repair_isolated(frames, result, [ALPHA], runner, disc, ledger=ledger)

    assert report.needs_model_revision == (0, 1)
    assert [e.kind for e in ledger.entries] == ["insitu_repair_no_neighbour"] * 2
    assert ledger.verify()


def test_first_frame_has_no_left_neighbour_uses_right_only():
    # フレーム0 は不連続だが左隣が存在しない (境界)。右隣 (1, フラグなし) から warm-start する。
    frames = _base_frames(3)
    right_cell = {"alpha": (5.33, 5.0, 5.0, 90.0, 90.0, 90.0)}
    fr_results = (
        _frame(0, 15.0, {"alpha": 1.0}, cells=GOOD_CELL),
        _frame(1, 8.0, {"alpha": 1.0}, cells=right_cell),
        _frame(2, 8.0, {"alpha": 1.0}, cells=right_cell),
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = (Discontinuity(frame_index=0, axis_value=0.0, rwp=15.0, reasons=("rwp_abs",)),)

    seen_initial = []

    def runner(frame, phases, initial_cells):
        seen_initial.append(initial_cells)
        return _result(rwp=7.0, cells=right_cell, fractions={"alpha": 1.0})

    report = repair_isolated(frames, result, [ALPHA], runner, disc)

    assert len(report.repairs) == 1
    assert report.repairs[0].source == "R"
    assert seen_initial == [right_cell]  # 左隣がないので右隣のみ 1 回試す


# ---------------------------------------------------------------------------
# 相分率ウォームスタート (Issue #96)
# ---------------------------------------------------------------------------

BETA = PhaseSpec(structure_path="beta.cif", phase_name="beta")
TWO_PHASE_CELL = {
    "alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0),
    "beta": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0),
}


def test_repair_passes_neighbour_fractions_as_initial_fractions():
    """近傍の相分率を `initial_fractions` として渡す (Issue #96)。

    セルだけを warm-start しても分率は毎回 GSAS の等分 seed (2 相なら 0.50/0.50) から
    再出発するため、修復試行が seed に張り付いて Rwp が改善せず採用されない。
    """
    frames = _base_frames(5)
    left_fracs = {"alpha": 0.7, "beta": 0.3}
    right_fracs = {"alpha": 0.6, "beta": 0.4}
    fr_results = (
        _frame(0, 8.0, left_fracs, cells=TWO_PHASE_CELL),
        _frame(1, 8.0, left_fracs, cells=TWO_PHASE_CELL),
        _frame(2, 15.0, {"alpha": 0.5, "beta": 0.5}, cells=TWO_PHASE_CELL),
        _frame(3, 8.0, right_fracs, cells=TWO_PHASE_CELL),
        _frame(4, 8.0, right_fracs, cells=TWO_PHASE_CELL),
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)
    assert [d.frame_index for d in disc] == [2]

    seen = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        seen.append(initial_fractions)
        return _result(rwp=7.0, cells=TWO_PHASE_CELL, fractions={"alpha": 0.65, "beta": 0.35})

    repair_isolated(frames, result, [ALPHA, BETA], runner, disc)

    assert left_fracs in seen  # 左隣 (frame1) の分率
    assert right_fracs in seen  # 右隣 (frame3) の分率


def test_repair_fractions_restricted_to_neighbour_phase_set():
    """渡す分率は実際に渡す相集合の分だけ (相名の取り違えを持ち込まない)。"""
    frames = _base_frames(3)
    fr_results = (
        _frame(0, 15.0, {"alpha": 0.5, "beta": 0.5}, cells=TWO_PHASE_CELL),
        _frame(1, 8.0, {"alpha": 1.0}, cells=GOOD_CELL, phase_names=("alpha",)),
        _frame(2, 8.0, {"alpha": 1.0}, cells=GOOD_CELL, phase_names=("alpha",)),
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = (Discontinuity(frame_index=0, axis_value=0.0, rwp=15.0, reasons=("rwp_abs",)),)

    seen = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        seen.append((tuple(p.phase_name for p in phases), initial_fractions))
        return _result(rwp=7.0, cells=GOOD_CELL, fractions={"alpha": 1.0})

    repair_isolated(frames, result, [ALPHA, BETA], runner, disc)

    assert seen == [(("alpha",), {"alpha": 1.0})]


def test_repair_three_arg_runner_still_works():
    """3 引数 runner は従来通り (TypeError を起こさない = 非破壊)。"""
    frames = _base_frames(5)
    fr_results = tuple(
        _frame(i, r, {"alpha": 0.5, "beta": 0.5}, cells=TWO_PHASE_CELL)
        for i, r in enumerate([8.0, 8.0, 15.0, 8.0, 8.0])
    )
    result = SequentialRietveldResult(frames=fr_results)
    disc = detect_discontinuities(result, rwp_delta=1.8)
    arities = []

    def runner(frame, phases, initial_cells):  # 3 引数のみ
        arities.append(3)
        return _result(rwp=7.0, cells=TWO_PHASE_CELL, fractions={"alpha": 0.6, "beta": 0.4})

    report = repair_isolated(frames, result, [ALPHA, BETA], runner, disc)

    assert arities == [3, 3]  # 左右 2 回
    assert len(report.repairs) == 1


# ---------------------------------------------------------------------------
# discontinuities_from_frames (明示ターゲット指定, Issue #96 レビュー HIGH-1)
# ---------------------------------------------------------------------------


def test_discontinuities_from_frames_builds_records_from_indices():
    """フレーム番号から `Discontinuity` を組める (seed 張り付きは検出統計に映らないため)。

    `detect_discontinuities` は Rwp ジャンプ/分率ジャンプでしか発火せず、**seed 張り付きは
    定義上「平坦」**なのでどの閾値でも拾えない。③ が `check_phase_set` の
    `seed_pinned_frames[].frame` を直接ターゲットにできる経路が要る。
    """
    frames = tuple(_frame(i, 8.0, {"alpha": 0.5, "beta": 0.5}) for i in range(5))
    result = SequentialRietveldResult(frames=frames)

    disc = discontinuities_from_frames(result, [3, 1])

    assert [d.frame_index for d in disc] == [1, 3]  # 昇順に正規化
    assert all(d.reasons == ("targeted",) for d in disc)
    assert [d.rwp for d in disc] == [8.0, 8.0]
    assert [d.axis_value for d in disc] == [1.0, 3.0]


def test_discontinuities_from_frames_dedupes():
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(4))
    result = SequentialRietveldResult(frames=frames)

    disc = discontinuities_from_frames(result, [2, 2, 2])

    assert [d.frame_index for d in disc] == [2]


def test_discontinuities_from_frames_custom_reason():
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(3))
    result = SequentialRietveldResult(frames=frames)

    disc = discontinuities_from_frames(result, [1], reason="seed_pinned")

    assert disc[0].reasons == ("seed_pinned",)


def test_discontinuities_from_frames_rejects_out_of_range():
    """範囲外は例外 (② が error dict へ縮退する)。黙って無視すると「修復対象なし」に化ける。"""
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(3))
    result = SequentialRietveldResult(frames=frames)

    with pytest.raises(ValueError, match="範囲外"):
        discontinuities_from_frames(result, [0, 7])


def test_discontinuities_from_frames_rejects_empty():
    """空リストは「対象なし」= 呼ぶ意味がない。黙って repairs=[] を返さない。"""
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(3))
    result = SequentialRietveldResult(frames=frames)

    with pytest.raises(ValueError, match="空"):
        discontinuities_from_frames(result, [])


def test_discontinuities_from_frames_rejects_non_integer():
    frames = tuple(_frame(i, 8.0, {"alpha": 1.0}) for i in range(3))
    result = SequentialRietveldResult(frames=frames)

    with pytest.raises(ValueError, match="整数"):
        discontinuities_from_frames(result, ["1"])  # type: ignore[list-item]


def test_repair_targeted_frames_are_not_warm_start_sources():
    """★両隣も同欠陥の罠: ターゲット指定したフレーム同士は warm-start 元にならない。

    seed 張り付きは連続することがある (実測 125-130 の 6 連続)。張り付いたフレームから
    warm-start すると欠陥をそのまま引き継ぐため、`repair_isolated` の `flagged` 集合
    (= 渡した `Discontinuity` のフレーム番号) が warm-start 元から除外することを担保する。
    """
    frames = _base_frames(6)
    # f2,f3,f4 が 3 連続で張り付き (Rwp は平凡 8.0 — 検出統計には映らない)。
    # 健全な両外側 (f0,f1 / f5) は張り付き値と**区別できる**分率を持たせる。
    pinned = {"alpha": 0.5, "beta": 0.5}
    healthy_l = {"alpha": 0.42, "beta": 0.58}
    healthy_r = {"alpha": 0.61, "beta": 0.39}
    fr_results = tuple(
        _frame(i, 8.0, fr, cells=TWO_PHASE_CELL)
        for i, fr in enumerate([healthy_l, healthy_l, pinned, pinned, pinned, healthy_r])
    )
    result = SequentialRietveldResult(frames=fr_results)
    sources = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        sources.append((frame.data_path, initial_fractions))
        return _result(rwp=6.0, cells=TWO_PHASE_CELL, fractions={"alpha": 0.7, "beta": 0.3})

    disc = discontinuities_from_frames(result, [2, 3, 4])
    report = repair_isolated(frames, result, [ALPHA, BETA], runner, disc)

    # 3 フレームすべて修復された (Rwp 8.0 → 6.0)
    assert [r.frame_index for r in report.repairs] == [2, 3, 4]
    # warm-start 元は **必ず** 健全な f1/f5 の分率であり、張り付き 0.5/0.5 ではない
    assert sources, "runner が呼ばれていない"
    for _path, fracs in sources:
        assert fracs != pinned, f"張り付きフレームから warm-start している: {fracs}"
        assert fracs in (healthy_l, healthy_r), f"想定外の warm-start 元: {fracs}"


def test_repair_trials_share_one_run_dir(tmp_path):
    """★修復試行の成果物が **1 つの run ディレクトリ**に集まる (セルフレビュー #3)。

    ambient が無い実運用経路 (② `repair_frames`) で試行ごとに run が割れると、
    設計 §3 の「1 実行 = 1 run ディレクトリ」に反し索引も 1 行ずつに分散する
    (「どの修復がどれか」を辿るのに全 run を開く羽目になる)。
    """
    from tsumugin.gpxstore import active_context

    seen: list[tuple[str, int | None, str]] = []

    def runner(frame, phases, initial_cells):
        ctx = active_context()
        seen.append((ctx.role, ctx.index, ctx.run_dir) if ctx else ("", None, ""))
        return _result(
            rwp=5.0, cells={"alpha": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
            fractions={"alpha": 1.0},
        )

    # 中央 2 フレームだけ Rwp が跳ねた系列 (両隣は良好 → 近傍 warm-start が使える)
    rwps = [8.0, 8.0, 20.0, 21.0, 8.0, 8.0]
    result = SequentialRietveldResult(
        frames=tuple(_frame(i, r, {"alpha": 1.0}) for i, r in enumerate(rwps))
    )
    frames = [FrameSpec(data_path=f"f{i}.xye", axis_value=float(i)) for i in range(len(rwps))]
    phases = [PhaseSpec(structure_path="alpha.cif", phase_name="alpha")]
    discs = detect_discontinuities(result, rwp_abs=15.0)
    assert discs, "テストの前提: 不連続が検出されること"

    repair_isolated(frames, result, phases, runner, discs)

    assert seen, "修復試行が 1 回も走っていない"
    assert {r for r, _, _ in seen} == {"repair"}
    assert len({d for _, _, d in seen}) == 1, f"run ディレクトリが割れている: {seen}"
