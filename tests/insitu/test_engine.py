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


def _result(rwp, cells, fracs, *, valid=True, gof=1.0, residual=None, n_obs=0):
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
        n_obs=n_obs,
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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


def test_max_new_phases_caps_phase_search():
    """max_new_phases=1: 1 相追加後は探索を打ち切る (無駄な相探索の抑制)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    other = PhaseSpec(structure_path="other.cif", phase_name="new_CaTe2O7")
    call = {"n": 0}

    def runner(frame, phases, initial_cells):
        names = [p.phase_name for p in phases]
        if len(names) > 1:  # 追加相ありは常に改善 (受理される)
            frac = {n: (0.4 if n.startswith("new_") else 0.6) for n in names}
            cells = {n: (13.3, 6.5, 8.1, 90, 90, 90) if n.startswith("new_")
                     else (14.8, 6.8, 8.0, 90, 90, 90) for n in names}
            return _result(8.0, cells, frac)
        i = call["n"]
        call["n"] += 1
        return _result(9.0 if i < 1 else 25.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    finder_calls = {"n": 0}

    def finder(frame, elements, exclude, workdir, known_phases=()):
        finder_calls["n"] += 1
        cand = other if "new_CaTeO3" in exclude else delta
        return [(cand, {"source": "mp", "formula": cand.phase_name})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.05, max_new_phases=1)
    res = run_sequential_rietveld(
        _frames(4), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(phase_id=pid, backward_propagation=False),
    )
    # 1 相 (delta) のみ採用、2 相目 (CaTe2O7) は上限で探索されない
    assert len(res.appearances) == 1
    assert res.appearances[0].phase_name == "new_CaTeO3"
    assert "new_CaTe2O7" not in res.phase_names


def test_consolidation_rerefines_poisoned_forward_frames():
    """globally-best セルで前方フレームを再精密化: 少数 onset の誤セル (高 Rwp) を良いセルで下げる。

    delta は onset (少数, 誤セル, Rwp 25) で受理され誤セルが前進 → 支配フレーム (axis 400) で良いセルに
    確立。consolidation が支配フレームの良いセルを onset 域の poison フレームへ配り Rwp を 25→10 に下げる。
    """
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    GOOD = (13.3, 6.5, 8.1, 90, 90, 90)
    BAD = (14.0, 6.9, 8.5, 90, 90, 90)
    ALPHA_C = (14.8, 6.8, 8.0, 90, 90, 90)

    def runner(frame, phases, initial_cells):
        ax = frame.axis_value
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            dcell = (initial_cells or {}).get("new_CaTeO3")
            warm_good = dcell is not None and abs(dcell[0] - 13.3) < 0.05
            if ax == 400.0:  # 支配フレーム: 良いセルに確立 (最大分率)
                return _result(8.0, {"alpha": ALPHA_C, "new_CaTeO3": GOOD},
                               {"alpha": 0.4, "new_CaTeO3": 0.6})
            if warm_good:  # 良いセルで再精密化 (consolidation) → Rwp 低
                return _result(10.0, {"alpha": ALPHA_C, "new_CaTeO3": GOOD},
                               {"alpha": 0.7, "new_CaTeO3": 0.3})
            # 少数 + 誤セル (forward warm-start): alpha 単相 (30) より改善するが高止まり
            return _result(25.0, {"alpha": ALPHA_C, "new_CaTeO3": BAD},
                           {"alpha": 0.8, "new_CaTeO3": 0.2})
        # alpha 単相: Rwp は delta 成長で上昇 (300/320=9, 以降=30)
        rwp = {300.0: 9.0, 320.0: 9.0}.get(ax, 30.0)
        return _result(rwp, {"alpha": ALPHA_C}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir, known_phases=()):
        # 採用後 (CaTeO3 が exclude) は再探索しない (既知相の再同定防止)
        if "CaTeO3" in exclude or "new_CaTeO3" in exclude:
            return []
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    frames = [FrameSpec(data_path=f"f{i}.xrdml", axis_value=300.0 + i * 20.0) for i in range(9)]
    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.05, min_rwp_gain=0.01)
    res = run_sequential_rietveld(frames, [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid, backward_propagation=True))
    minority = [f for f in res.frames if "new_CaTeO3" in f.phase_names and f.axis_value != 400.0]
    assert minority, "delta を含む少数フレームが無い"
    # consolidation で onset 域 poison (誤セル BAD, Rwp 25) が良いセル (a≈13.3) + Rwp≤10 に更新される
    assert all(f.refined_cells["new_CaTeO3"][0] == pytest.approx(13.3) for f in minority)
    assert all(f.rwp <= 10.0 + 1e-9 for f in minority)


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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
        calls["finder"] += 1
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    # trigger_rwp_ratio を大きくして Rwp ジャンプは無効化 → S/N トリガのみで発火することを見る
    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, min_rwp_gain=0.01,
                        trigger_rwp_ratio=100.0, snr_trigger=8.0)
    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid, changepoint_window=99))
    assert calls["finder"] > 0  # S/N トリガで探索が発火した
    assert len(res.appearances) == 1  # delta 受理


def _snr_trigger_setup():
    """S/N トリガで finder を確実に発火させる runner/frames/pid を作る (warm-start 配線テスト共通)。"""
    import numpy as np

    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    delta = PhaseSpec(structure_path="delta.cif", phase_name="new_CaTeO3")
    tt = np.linspace(12.0, 70.0, 2000)
    sigma = np.full(tt.size, 10.0)
    resid_peak = 400.0 * np.exp(-0.5 * ((tt - 40.0) / 0.15) ** 2)
    flat = np.zeros(tt.size)

    def runner(frame, phases, initial_cells):
        if "new_CaTeO3" in [p.phase_name for p in phases]:
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_CaTeO3": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_CaTeO3": 0.4}, residual=(tt, flat, sigma))
        return _result(12.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0},
                       residual=(tt, resid_peak, sigma))

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, min_rwp_gain=0.01,
                        trigger_rwp_ratio=100.0, snr_trigger=8.0)
    return alpha, delta, runner, pid


def test_warm_start_passes_converted_known_phases_to_finder(monkeypatch):
    """warm_start: 現行相が phasespec_to_reference で変換され finder の known_phases に届く (一本化 B 配線)。"""
    from tsumugin.reference.model import ReferencePhase
    from tsumugin.search.peaks import Peak

    alpha, delta, runner, pid = _snr_trigger_setup()
    fake_ref = ReferencePhase(phase_id="alpha", formula="CaH2O4Te",
                              element_system=("Ca", "H", "O", "Te"),
                              peaks=(Peak(position=20.0, height=100.0),), energy_above_hull=None)
    seen_cells: dict[str, object] = {}

    def fake_convert(phase_spec, *, refined_cell=None, wavelength=1.5406, **_):
        seen_cells["cell"] = refined_cell  # base_result の精密化格子が渡ること
        return fake_ref if phase_spec.phase_name == "alpha" else None

    monkeypatch.setattr("tsumugin.insitu.engine.phasespec_to_reference", fake_convert)

    received: dict[str, object] = {}

    def finder(frame, elements, exclude, workdir, known_phases=()):
        received["known"] = list(known_phases)
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                            config=SequentialConfig(phase_id=pid, changepoint_window=99))
    assert received["known"] == [fake_ref]  # 変換された現行相が finder へ届いた
    # 精密化格子 (14.8,...) が変換器へ渡ったこと (CIF 素でなく現フレーム格子で減算)
    assert seen_cells["cell"] == (14.8, 6.8, 8.0, 90.0, 90.0, 90.0)


def test_warm_start_disabled_passes_empty_known_phases(monkeypatch):
    """warm_start_known_phases=False なら変換せず known_phases=() を渡す (静的同定へ縮退)。"""
    alpha, delta, runner, pid = _snr_trigger_setup()
    pid = replace_pid(pid, warm_start_known_phases=False)

    def boom(*a, **k):  # 呼ばれてはいけない
        raise AssertionError("phasespec_to_reference は warm_start 無効時に呼ばれない")

    monkeypatch.setattr("tsumugin.insitu.engine.phasespec_to_reference", boom)
    received: dict[str, object] = {}

    def finder(frame, elements, exclude, workdir, known_phases=()):
        received["known"] = list(known_phases)
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                            config=SequentialConfig(phase_id=pid, changepoint_window=99))
    assert received["known"] == []


def test_warm_start_unconvertible_phase_falls_back_to_empty(monkeypatch):
    """変換不能 (None) な現行相は除かれ known_phases=() へ縮退する (安全側フォールバック・非回帰)。"""
    alpha, delta, runner, pid = _snr_trigger_setup()
    monkeypatch.setattr(
        "tsumugin.insitu.engine.phasespec_to_reference", lambda *a, **k: None
    )
    received: dict[str, object] = {}

    def finder(frame, elements, exclude, workdir, known_phases=()):
        received["known"] = list(known_phases)
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid, changepoint_window=99))
    assert received["known"] == []  # 変換不能は空集合へ縮退
    assert len(res.appearances) == 1  # 静的同定として delta は受理される (非回帰)


def replace_pid(pid, **changes):
    from dataclasses import replace

    return replace(pid, **changes)


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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
        return [(delta, {"source": "mp", "formula": "CaTeO3"})]

    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), frac_min=0.03, require_validity=True)
    res = run_sequential_rietveld(_frames(3), [alpha], runner=runner, phase_finder=finder,
                                  config=SequentialConfig(phase_id=pid))
    assert res.appearances == ()  # validity fail で棄却


def test_bic_acceptance_opt_in_accepts_real_phase():
    """bic_acceptance=True (opt-in): 実相 (大きな gof 改善) を bic で採用する。"""
    from tsumugin.insitu.engine import _accept_new_phase

    base = _result(40.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0},
                   gof=4.0, n_obs=2000)
    trial = _result(33.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                           "new_delta": (13.3, 6.5, 8.1, 90, 90, 90)},
                    {"alpha": 0.9, "new_delta": 0.1}, gof=3.3, n_obs=2000)
    pid = PhaseIdConfig(elements=("Ca", "Te", "O"), bic_acceptance=True, frac_min=0.03)
    assert _accept_new_phase(trial, "new_delta", 40.0, 33.0, 0.1, pid, base) is True


def test_bic_acceptance_permissive_vs_min_rwp_gain():
    """ベンチマーク知見: 大 n_obs では bic は min_rwp_gain より寛容 (罰が chi2 スケールに対し微小)。

    0.3% しか Rwp が下がらない相を、min_rwp_gain=1% は棄却するが bic は採用する (罰 91 << chi2 改善 213)。
    → forward-pass の既定は相対 Rwp (過剰適合ガード)、bic は opt-in。
    """
    from tsumugin.insitu.engine import _accept_new_phase

    base = _result(30.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0},
                   gof=3.0, n_obs=2000)
    trial = _result(29.91, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                            "new_junk": (5.0, 5.0, 5.0, 90, 90, 90)},
                    {"alpha": 0.6, "new_junk": 0.4}, gof=2.991, n_obs=2000)
    rwp_pid = PhaseIdConfig(elements=("Ca", "Te", "O"), bic_acceptance=False,
                            min_rwp_gain=0.01, frac_min=0.03)
    bic_pid = PhaseIdConfig(elements=("Ca", "Te", "O"), bic_acceptance=True, frac_min=0.03)
    # 相対 Rwp (既定): 0.3% < 1% で棄却
    assert _accept_new_phase(trial, "new_junk", 30.0, 29.91, 0.4, rwp_pid, base) is False
    # bic (opt-in): 罰より chi2 改善が大きく採用 (寛容 = forward-pass の既定にしない理由)
    assert _accept_new_phase(trial, "new_junk", 30.0, 29.91, 0.4, bic_pid, base) is True


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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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

    def finder(frame, elements, exclude, workdir, known_phases=()):
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


# --- Issue #52: make_gsas_runner recipe injection ---------------------------------------------


def test_make_gsas_runner_custom_recipe_passthrough(monkeypatch):
    """recipe= を注入すると build_recipe を呼ばずそのまま run_auto_rietveld に渡る。"""
    from tsumugin.autorietveld.model import Geometry, RefinementStage, Radiation
    from tsumugin.insitu.engine import make_gsas_runner

    captured: dict[str, object] = {}

    def fake_run(histograms, phases, *, recipe=None, max_cyc=12, initial_cells=None, **kwargs):
        captured["recipe"] = recipe
        captured["max_cyc"] = max_cyc
        captured["initial_cells"] = initial_cells
        return object()  # sentinel: run_auto_rietveld の戻り値をそのまま返す

    def boom_build_recipe(*a, **k):
        raise AssertionError("recipe= 指定時は build_recipe を呼んではいけない")

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_run)
    monkeypatch.setattr("tsumugin.autorietveld.recipe.build_recipe", boom_build_recipe)

    custom_recipe = (
        RefinementStage(label="scale+bg", flags={"scale": True, "background": {"coeffs": 8}},
                        note=""),
    )
    frame = FrameSpec(data_path="dummy.xye", data_format="XYE", axis_value=300.0)
    phase = PhaseSpec(structure_path="dummy.cif", phase_name="alpha")
    initial_cells = {"alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)}

    runner = make_gsas_runner(
        instrument_path="dummy.instprm",
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        recipe=custom_recipe,
    )
    result = runner(frame, [phase], initial_cells)

    assert captured["recipe"] is custom_recipe
    assert result is not None
    assert captured["max_cyc"] == 12
    assert captured["initial_cells"] == initial_cells


def test_make_gsas_runner_default_recipe_unchanged(monkeypatch):
    """recipe 未指定なら従来通り build_recipe で組み立てた既定レシピが渡る (非回帰)。"""
    from tsumugin.autorietveld.model import Geometry, RefinementStage, Radiation
    from tsumugin.autorietveld.recipe import build_recipe
    from tsumugin.insitu.engine import make_gsas_runner

    captured: dict[str, object] = {}

    def fake_run(histograms, phases, *, recipe=None, max_cyc=12, initial_cells=None, **kwargs):
        captured["recipe"] = recipe
        captured["histograms"] = list(histograms)
        captured["phases"] = list(phases)
        return object()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_run)

    frame = FrameSpec(data_path="dummy.xye", data_format="XYE", axis_value=300.0)
    phase = PhaseSpec(structure_path="dummy.cif", phase_name="alpha")

    runner = make_gsas_runner(
        instrument_path="dummy.instprm",
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
    )
    runner(frame, [phase], None)

    recipe = captured["recipe"]
    assert recipe is not None
    assert isinstance(recipe, tuple)
    assert len(recipe) > 0
    assert all(isinstance(stage, RefinementStage) for stage in recipe)
    expected = build_recipe(captured["histograms"], captured["phases"], background_coeffs=6)
    assert recipe == expected


def test_make_gsas_runner_max_cyc_and_initial_cells_passthrough(monkeypatch):
    """max_cyc/initial_cells は recipe 注入の有無に関係なく従来通り run_auto_rietveld に渡る。"""
    from tsumugin.autorietveld.model import Geometry, Radiation
    from tsumugin.insitu.engine import make_gsas_runner

    captured: dict[str, object] = {}

    def fake_run(histograms, phases, *, recipe=None, max_cyc=12, initial_cells=None, **kwargs):
        captured["max_cyc"] = max_cyc
        captured["initial_cells"] = initial_cells
        return object()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_run)

    frame = FrameSpec(data_path="dummy.xye", data_format="XYE", axis_value=300.0)
    phase = PhaseSpec(structure_path="dummy.cif", phase_name="alpha")
    initial_cells = {"alpha": (6.0, 6.0, 6.0, 90.0, 90.0, 90.0)}

    runner = make_gsas_runner(
        instrument_path="dummy.instprm",
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        max_cyc=5,
    )
    runner(frame, [phase], initial_cells)

    assert captured["max_cyc"] == 5
    assert captured["initial_cells"] == initial_cells


# --- Issue #93: make_gsas_runner → run_auto_rietveld の auto_freeze_minor_cells 配線 (#80) ------


def test_make_gsas_runner_auto_freeze_minor_cells_passthrough(monkeypatch):
    """auto_freeze_minor_cells= を注入すると run_auto_rietveld へそのまま転送される (Issue #80/#93)。"""
    from tsumugin.autorietveld.model import Geometry, Radiation
    from tsumugin.insitu.engine import make_gsas_runner

    captured: dict[str, object] = {}

    def fake_run(histograms, phases, *, auto_freeze_minor_cells=None, **kwargs):
        captured["auto_freeze_minor_cells"] = auto_freeze_minor_cells
        return object()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_run)

    frame = FrameSpec(data_path="dummy.xye", data_format="XYE", axis_value=300.0)
    phase = PhaseSpec(structure_path="dummy.cif", phase_name="alpha")

    runner = make_gsas_runner(
        instrument_path="dummy.instprm",
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        auto_freeze_minor_cells=0.2,
    )
    runner(frame, [phase], None)

    assert captured["auto_freeze_minor_cells"] == pytest.approx(0.2)


def test_make_gsas_runner_auto_freeze_minor_cells_default_none(monkeypatch):
    """未指定なら None が渡る (= run_auto_rietveld の従来動作, 非回帰)。"""
    from tsumugin.autorietveld.model import Geometry, Radiation
    from tsumugin.insitu.engine import make_gsas_runner

    captured: dict[str, object] = {}

    def fake_run(histograms, phases, *, auto_freeze_minor_cells=None, **kwargs):
        captured["auto_freeze_minor_cells"] = auto_freeze_minor_cells
        return object()

    monkeypatch.setattr("tsumugin.autorietveld.engine.run_auto_rietveld", fake_run)

    frame = FrameSpec(data_path="dummy.xye", data_format="XYE", axis_value=300.0)
    phase = PhaseSpec(structure_path="dummy.cif", phase_name="alpha")

    runner = make_gsas_runner(
        instrument_path="dummy.instprm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    runner(frame, [phase], None)

    assert captured["auto_freeze_minor_cells"] is None


# --- G1: 残差レポートのフレームへの引き回し (§4.5 到達可能性) ------------------------------


def _synthetic_residual(n=64):
    """(two_theta, residual, sigma) — 1 点だけ大きな未説明ピークを持つ合成残差。"""
    tt = [10.0 + 0.05 * i for i in range(n)]
    resid = [0.0] * n
    resid[32] = 500.0  # 未説明ピーク (calc 不足)
    sigma = [10.0] * n
    return tt, resid, sigma


def test_frame_result_carries_residual_report():
    """runner の残差配列からフレーム毎の ResidualReport が組み立てられる (③ の J2/J3 入力)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    tt, resid, sigma = _synthetic_residual()

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0},
                       residual=(tt, resid, sigma))

    res = run_sequential_rietveld(_frames(2), [alpha], runner=runner)
    for f in res.frames:
        assert f.residual_report is not None
        assert f.residual_report.top_features[0].two_theta == pytest.approx(10.0 + 0.05 * 32)
        assert f.residual_report.top_features[0].residual == pytest.approx(500.0)


def test_frame_result_residual_report_none_without_residual_arrays():
    """残差フィールドが空 (スタブ runner/旧構築) なら None (後方互換・キーは常に存在)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    res = run_sequential_rietveld(_frames(2), [alpha], runner=runner)
    assert all(f.residual_report is None for f in res.frames)


def test_rebuilt_frame_recomputes_residual_report():
    """_consolidate_phase_cells の再精密化フレームも再計算した残差レポートを持つ (古い報告を残さない)。"""
    from tsumugin.insitu.engine import _rebuild_frame

    tt, resid, sigma = _synthetic_residual()
    fr_before = run_sequential_rietveld(
        _frames(1), [PhaseSpec("alpha.cif", "alpha")],
        runner=lambda f, p, c: _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)},
                                       {"alpha": 1.0}),
    ).frames[0]
    assert fr_before.residual_report is None

    res = _result(7.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0},
                  residual=(tt, resid, sigma))
    rebuilt = _rebuild_frame(res, fr_before, ("alpha",))
    assert rebuilt.residual_report is not None
    assert rebuilt.residual_report.top_features[0].residual == pytest.approx(500.0)


# ---------------------------------------------------------------------------
# 出版値の引き継ぎ (Issue #96 レビュー HIGH-2)
# ---------------------------------------------------------------------------
# `AutoRietveldResult` は GSAS から重量分率 ± esd と格子 esd を持ち帰るが、フレームへ**引き継が
# なければ** `seq_result_to_dict` が幾ら serialize しても空 dict しか出ない (② に配線しても
# 中身が無ければ ③ にとって「無い」のと同じ)。operando の主要な報告値がここを通る。


def test_frame_carries_publication_values_from_result():
    """精密化結果の重量分率 ± esd / 格子 esd がフレームに引き継がれること。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    beta = PhaseSpec(structure_path="beta.cif", phase_name="beta")
    cells = {"alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0), "beta": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)}

    def runner(frame, phases, initial_cells):
        return AutoRietveldResult(
            stage_results=(), final_rwp=7.0, final_gof=1.1,
            refined_cells=cells, validity=ValidityReport(passed=True),
            phase_fractions={"alpha": 0.656, "beta": 0.344},
            phase_weight_fractions={"alpha": 0.472, "beta": 0.528},
            phase_weight_fraction_esd={"alpha": 0.006, "beta": 0.006},
            cell_esd={"alpha": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
        )

    out = run_sequential_rietveld(_frames(2), [alpha, beta], runner=runner)

    for fr in out.frames:
        assert fr.phase_weight_fractions == {"alpha": 0.472, "beta": 0.528}
        assert fr.phase_weight_fraction_esd == {"alpha": 0.006, "beta": 0.006}
        assert fr.cell_esd == {"alpha": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)}
        # Scale 値 (相対比較用) は従来通り別に持つ
        assert fr.phase_fractions == {"alpha": 0.656, "beta": 0.344}


def test_frame_publication_values_default_empty_for_stub_runner():
    """出版値を持たない runner (スタブ/旧構築) は空 dict へ縮退する (後方互換)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    cells = {"alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)}

    def runner(frame, phases, initial_cells):
        return _result(8.0, cells, {"alpha": 1.0})

    out = run_sequential_rietveld(_frames(2), [alpha], runner=runner)

    for fr in out.frames:
        assert fr.phase_weight_fractions == {}
        assert fr.phase_weight_fraction_esd == {}
        assert fr.cell_esd == {}
