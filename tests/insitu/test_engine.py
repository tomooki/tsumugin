"""M9 insitu.engine の純テスト (stub runner + stub phase_finder, GSAS/MP 非依存)。

逐次エンジンの制御ロジック — ウォームスタート (initial_cells 伝播)・変化点トリガ・自動相追加の
受理基準 (相分率有意 ∧ Rwp 改善 ∧ 妥当性)・可逆性 (棄却時据え置き)・ledger 追記 — を検証する。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    PhaseSpec,
    ValidityReport,
)
from tsumugin.insitu.engine import run_sequential_rietveld
from tsumugin.insitu.model import FrameSpec, PhaseIdConfig, SequentialConfig
from tsumugin.store.ledger import Ledger


def _result(rwp, cells, fracs, *, valid=True, gof=1.0):
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=rwp,
        final_gof=gof,
        refined_cells=cells,
        validity=ValidityReport(passed=valid),
        phase_fractions=fracs,
    )


def _frames(n, start=300.0, step=20.0):
    return [FrameSpec(data_path=f"f{i}.xrdml", axis_value=start + i * step) for i in range(n)]


def test_single_phase_series_no_phaseid():
    """相同定無効なら各フレームを単一相で精密化し結果を積む。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner)
    assert len(res.frames) == 3
    assert res.phase_names == ("alpha",)
    assert res.appearances == ()
    assert all(f.rwp == 9.0 for f in res.frames)
    assert res.frames[0].phase_fractions == {"alpha": 1.0}


def test_warm_start_propagates_previous_cells():
    """warm_start=True で 直前フレームの refined_cells が次フレームの initial_cells に渡る。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    seen_initial = []

    def runner(frame, phases, initial_cells):
        seen_initial.append(initial_cells)
        # 各フレームで少しずつ膨張したセルを返す
        i = len(seen_initial) - 1
        a = 14.8 + 0.01 * i
        return _result(9.0, {"alpha": (a, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    run_sequential_rietveld(_frames(3), [alpha], runner=runner,
                            config=SequentialConfig(warm_start=True))
    assert seen_initial[0] is None  # フレーム0 はウォームスタートなし
    assert seen_initial[1] == {"alpha": (14.8, 6.8, 8.0, 90.0, 90.0, 90.0)}
    assert seen_initial[2]["alpha"][0] == pytest.approx(14.81)


def test_warm_start_disabled_passes_none():
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    seen = []

    def runner(frame, phases, initial_cells):
        seen.append(initial_cells)
        return _result(9.0, {"alpha": (5, 5, 5, 90, 90, 90)}, {"alpha": 1.0})

    run_sequential_rietveld(_frames(2), [alpha], runner=runner,
                            config=SequentialConfig(warm_start=False))
    assert seen == [None, None]


def test_auto_add_phase_accepted_on_rwp_jump():
    """Rwp がジャンプしたフレームで新相を同定・追加し、改善すれば採用する。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")

    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        names = [p.phase_name for p in phases]
        if "new_CaTeO3" in names:
            # 二相 (alpha+delta) で再精密化 → Rwp 大幅改善・delta 相分率 0.3
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.7, "new_CaTeO3": 0.3})
        # 単一相: フレーム0,1 は良好、フレーム2 で delta 出現し Rwp ジャンプ
        i = call["n"]
        call["n"] += 1
        rwp = 9.0 if i < 2 else 20.0
        return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        assert "alpha" in exclude
        return [(delta, {"source": "materials_project", "dara_score": 0.5})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.02, trigger_rwp_ratio=1.25)
    res = run_sequential_rietveld(
        _frames(3), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(phase_id=pid),
    )
    assert len(res.appearances) == 1
    ap = res.appearances[0]
    assert ap.phase_name == "new_CaTeO3"
    assert ap.frame_index == 2
    assert ap.rwp_after < ap.rwp_before
    assert "new_CaTeO3" in res.phase_names
    # フレーム2 は二相結果 (改善後 9.0)
    assert res.frames[2].rwp == 9.0
    assert set(res.frames[2].phase_names) == {"alpha", "new_CaTeO3"}


def test_auto_add_phase_rejected_when_not_improving():
    """新相を試しても Rwp が改善しなければ棄却し相集合は不変 (可逆・過剰適合ガード)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    junk = PhaseSpec(structure_path="junk.cif", phase_name="junk")

    def runner(frame, phases, initial_cells):
        names = [p.phase_name for p in phases]
        if "junk" in names:
            return _result(19.5, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                  "junk": (5, 5, 5, 90, 90, 90)},
                           {"alpha": 0.99, "junk": 0.01})  # 改善わずか・分率も小
        rwp = 9.0 if frame.axis_value < 340 else 20.0
        return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        return [(junk, {"source": "mp"})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.02)
    res = run_sequential_rietveld(
        _frames(3), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(phase_id=pid),
    )
    assert res.appearances == ()
    assert res.phase_names == ("alpha",)
    assert res.frames[2].rwp == 20.0  # 棄却なので base のまま


def test_accepted_phase_formula_excluded_next_frames():
    """採用した新相の組成式が以降フレームの finder exclude に入り再同定されない (既知相除外)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_delta")
    excludes_seen = []

    def runner(frame, phases, initial_cells):
        names = [p.phase_name for p in phases]
        if "new_delta" in names:
            # 二相は通常 7 (良好) だが axis>=380 で第 2 の事変 (22) → 再探索トリガ (min_rwp 更新後)。
            rwp = 22.0 if frame.axis_value >= 380 else 7.0
            return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_delta": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_delta": 0.4})
        # 単相: 0,1 良好 (9.0)、frame2 (340) でジャンプ (22.0)
        rwp = 9.0 if frame.axis_value < 340 else 22.0
        return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        excludes_seen.append((frame.axis_value, tuple(exclude)))
        # delta 候補を返すが、既に除外されていれば identify 側で弾かれる想定。ここでは呼ばれた
        # exclude を記録するのが目的。formula が exclude 済みなら空を返して再追加を防ぐ。
        if "CaTeO3" in exclude:
            return []
        return [(delta, {"source": "materials_project", "formula": "CaTeO3", "dara_score": 0.5})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.02)
    res = run_sequential_rietveld(_frames(6), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid))
    assert len(res.appearances) == 1  # delta は 1 回だけ採用 (再探索では除外され再追加なし)
    # 採用後 (axis 380) の再探索で exclude に採用相 formula "CaTeO3" が入る
    later = [ex for axis, ex in excludes_seen if axis >= 380.0]
    assert later, "採用後フレームで finder が再度呼ばれていない"
    assert all("CaTeO3" in ex for ex in later)


def test_ledger_records_and_verifies():
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    ledger = Ledger()

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (5, 5, 5, 90, 90, 90)}, {"alpha": 1.0})

    res = run_sequential_rietveld(_frames(2), [alpha], runner=runner, ledger=ledger)
    assert res.ledger is ledger
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert "m9_seq_start" in kinds
    assert kinds.count("m9_seq_frame") == 2
    assert "m9_seq_done" in kinds


def test_max_frames_limits():
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (5, 5, 5, 90, 90, 90)}, {"alpha": 1.0})

    res = run_sequential_rietveld(_frames(10), [alpha], runner=runner,
                                  config=SequentialConfig(max_frames=3))
    assert len(res.frames) == 3


def test_determinism_identical_runs():
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")

    def runner(frame, phases, initial_cells):
        return _result(9.0 + frame.frame_index if hasattr(frame, "frame_index") else 9.0,
                       {"alpha": (5, 5, 5, 90, 90, 90)}, {"alpha": 1.0})

    r1 = run_sequential_rietveld(_frames(4), [alpha], runner=runner)
    r2 = run_sequential_rietveld(_frames(4), [alpha], runner=runner)
    assert [f.rwp for f in r1.frames] == [f.rwp for f in r2.frames]
    assert r1.phase_names == r2.phase_names
