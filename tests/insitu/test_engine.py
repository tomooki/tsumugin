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


def _result(rwp, cells, fracs, *, valid=True, gof=1.0, residual=None):
    kw = {}
    if residual is not None:
        tt, ri, sg = residual
        kw = dict(residual_two_theta=tuple(tt), residual_intensity=tuple(ri),
                  residual_sigma=tuple(sg))
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=rwp,
        final_gof=gof,
        refined_cells=cells,
        validity=ValidityReport(passed=valid),
        phase_fractions=fracs,
        **kw,
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


def test_refined_cell_flows_into_appearance_evidence():
    """finder が meta に refined_cell (異方セル) を載せると PhaseAppearance.evidence に伝わる。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    aniso = [6.53, 8.17, 13.32, 90.0, 90.0, 90.0]
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.7, "new_CaTeO3": 0.3})
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 2 else 20.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        return [(delta, {"source": "materials_project", "dara_score": 0.5, "refined_cell": aniso})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.02)
    res = run_sequential_rietveld(
        _frames(3), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(phase_id=pid),
    )
    assert len(res.appearances) == 1
    assert res.appearances[0].evidence["refined_cell"] == aniso


def test_backward_propagation_captures_onset():
    """(2) 逆方向伝播: 順方向で支配フレームに採用した新相を、良いセルで前フレームへ逆伝播し onset を捕捉。

    delta は frame3 で順方向採用 (支配)。逆伝播で frame2/1 も delta 有意+Rwp改善→採用、frame0 は不在で停止。
    onset が frame3→frame1 に前進する。
    """
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    delta_cell = (13.3, 6.5, 8.1, 90, 90, 90)
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        has_delta = "new_CaTeO3" in [p.phase_name for p in phases]
        if has_delta:
            # frame(axis)ごとに delta 分率/Rwp を変える (逆伝播の停止点を作る)
            table = {
                360.0: (0.40, 8.0),   # frame3 順方向採用 (支配)
                340.0: (0.30, 7.0),   # frame2 逆伝播 → 採用
                320.0: (0.20, 8.0),   # frame1 逆伝播 → 採用 (base 9.0 より改善)
                300.0: (0.00, 9.6),   # frame0 逆伝播 → 不在/改善なし → 停止 (onset=frame1)
            }
            frac, rwp = table.get(frame.axis_value, (0.3, 8.0))
            return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90), "new_CaTeO3": delta_cell},
                           {"alpha": 1 - frac, "new_CaTeO3": frac})
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 3 else 20.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.05, min_rwp_gain=0.01)
    res = run_sequential_rietveld(
        _frames(4), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(phase_id=pid, backward_propagation=True),
    )
    # delta が frame1/2/3 に存在し、frame0 には無い (onset=frame1)
    by_axis = {f.axis_value: f for f in res.frames}
    assert "new_CaTeO3" in by_axis[320.0].phase_names  # frame1 逆伝播で捕捉
    assert "new_CaTeO3" in by_axis[340.0].phase_names  # frame2 逆伝播で捕捉
    assert "new_CaTeO3" not in by_axis[300.0].phase_names  # frame0 不在 (停止)
    # appearance の onset が前進
    ap = next(a for a in res.appearances if a.phase_name == "new_CaTeO3")
    assert ap.frame_index == 1
    assert ap.evidence.get("backward_onset") is True


def test_backward_propagation_disabled_keeps_forward_onset():
    """backward_propagation=False なら順方向の onset のまま (逆伝播しない)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            return _result(8.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_CaTeO3": 0.4})
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 3 else 20.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.05)
    res = run_sequential_rietveld(
        _frames(4), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(phase_id=pid, backward_propagation=False),
    )
    ap = next(a for a in res.appearances if a.phase_name == "new_CaTeO3")
    assert ap.frame_index == 3  # 逆伝播なし → 順方向 onset のまま
    by_axis = {f.axis_value: f for f in res.frames}
    assert "new_CaTeO3" not in by_axis[320.0].phase_names  # frame1 は逆伝播されない


def test_snr_trigger_fires_on_significant_residual():
    """残差 S/N トリガ: Rwp ジャンプがなくても、残差に有意な未説明ピークがあれば新相探索を発火する。"""
    import numpy as np

    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    tt = np.linspace(12.0, 70.0, 2000)
    sigma = np.full(tt.size, 10.0)
    # 有意な未説明ピーク (S/N ~20) を持つ残差 (Rwp は一定=ジャンプなし)
    resid_peak = 400.0 * np.exp(-0.5 * ((tt - 40.0) / 0.15) ** 2)
    flat_resid = np.zeros(tt.size)

    def runner(frame, phases, initial_cells):
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            # delta 追加で残差平坦化 + Rwp 改善
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_CaTeO3": 0.4},
                           residual=(tt, flat_resid, sigma))
        # 単相: Rwp は一定 (12.0) だが残差に未説明ピーク → S/N トリガ
        return _result(12.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0},
                       residual=(tt, resid_peak, sigma))

    calls = {"finder": 0}

    def finder(frame, elements, exclude, workdir):
        calls["finder"] += 1
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    # trigger_rwp_ratio を大きくして Rwp ジャンプは無効化 → S/N トリガのみで発火することを見る
    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, min_rwp_gain=0.01,
                        trigger_rwp_ratio=100.0, snr_trigger=8.0)
    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid, changepoint_window=99))
    assert calls["finder"] > 0  # S/N トリガで探索が発火した
    assert len(res.appearances) == 1  # delta 受理


def test_accept_new_phase_despite_old_phase_validity_fail():
    """③ 受理閾値: 旧相ドリフトで trial.validity=False でも、新相の Rwp 改善+分率+セル健全なら受理。

    転移域で alpha のセルが急変し全相 validity が fail するが、それで delta を巻き添え棄却しない。
    """
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            # delta 追加で Rwp 改善するが validity は False (旧相 alpha のドリフト)
            return _result(24.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                  "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_CaTeO3": 0.4}, valid=False)
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 2 else 30.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)},
                       {"alpha": 1.0}, valid=False)

    def finder(frame, elements, exclude, workdir):
        return [(delta, {"source": "materials_project", "formula": "CaTeO3", "dara_score": 0.01})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, min_rwp_gain=0.01)
    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid))
    assert len(res.appearances) == 1  # delta 受理 (旧相 validity fail に巻き添えされない)
    assert res.appearances[0].phase_name == "new_CaTeO3"


def test_require_validity_restores_strict_rejection():
    """require_validity=True なら従来通り trial.validity=False で棄却 (後方互換の厳格モード)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            return _result(24.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                  "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_CaTeO3": 0.4}, valid=False)
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 2 else 30.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)},
                       {"alpha": 1.0}, valid=True)

    def finder(frame, elements, exclude, workdir):
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, require_validity=True)
    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid))
    assert res.appearances == ()  # validity fail で棄却


def test_reject_new_phase_when_rwp_gain_below_threshold():
    """相対 Rwp 改善が min_rwp_gain 未満なら棄却 (過剰適合ガード)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    junk = PhaseSpec(structure_path="junk.cif", phase_name="new_junk")
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        if "new_junk" in [p.phase_name for p in phases]:
            # 分率・セルは OK だが Rwp がほぼ下がらない (0.3% < 1%)
            return _result(29.91, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                   "new_junk": (5.0, 5.0, 5.0, 90, 90, 90)},
                           {"alpha": 0.6, "new_junk": 0.4})
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 2 else 30.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        return [(junk, {"source": "mp", "formula": "JUNK"})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, min_rwp_gain=0.01)
    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid))
    assert res.appearances == ()  # Rwp 改善不足で棄却


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
            # 二相の Rwp は軸とともに上昇 (相がさらに成長=Rwp が動くと再探索がかかる)。
            rwp = 7.0 + 0.1 * (frame.axis_value - 340)
            return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_delta": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_delta": 0.4})
        # 単相: 0,1 良好 (9.0)、frame2 (340) でジャンプ (22.0)
        rwp = 9.0 if frame.axis_value < 340 else 22.0
        return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir):
        excludes_seen.append((frame.axis_value, tuple(exclude)))
        # formula が exclude 済みなら空を返す (再追加を防ぐ = 既知相除外の効果)。
        if "CaTeO3" in exclude:
            return []
        return [(delta, {"source": "materials_project", "formula": "CaTeO3", "dara_score": 0.5})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.02)
    res = run_sequential_rietveld(_frames(6), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid))
    assert len(res.appearances) == 1  # delta は 1 回だけ採用 (再探索では除外され再追加なし)
    # 採用後 (axis>340) の再探索で exclude に採用相 formula "CaTeO3" が入る
    later = [ex for axis, ex in excludes_seen if axis > 340.0]
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
