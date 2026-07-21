"""M10 anchor/engine.py — run_anchored_sequential のエンドツーエンドテスト (stub runner, numpy)。

アンカー抽出→双方向区間→bic crossover→組立→ledger の統合。決定論・単相縮退・onset 記録を検証する。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.anchor import run_anchored_sequential
from tsumugin.insitu.anchor.model import AnchorConfig
from tsumugin.insitu.model import FrameSpec, SequentialRietveldResult

ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
DELTA = PhaseSpec(structure_path="delta.cif", phase_name="new_delta")


def _res(rwp, cells, fracs, *, gof=1.0, valid=True, n_obs=2000,
         wfracs=None, wfrac_esd=None, cesd=None):
    return AutoRietveldResult(stage_results=(), final_rwp=rwp, final_gof=gof, refined_cells=cells,
                              validity=ValidityReport(passed=valid), phase_fractions=fracs,
                              n_obs=n_obs, phase_weight_fractions=wfracs or {},
                              phase_weight_fraction_esd=wfrac_esd or {}, cell_esd=cesd or {})


def _frames(n):
    return [FrameSpec(data_path=f"f{i}.xye", axis_value=float(300 + i * 30)) for i in range(n)]


def _idx(frame):
    return int((frame.axis_value - 300) / 30)


def test_single_phase_series_degenerates_to_anchors():
    """単相系列: 全フレーム高信頼 → 全アンカー、内側なし → M9 相当 (各 1 回精密化)。"""
    def identifier(frame):
        return (0.9, (ALPHA,))

    def runner(frame, phases, cells):
        return _res(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    res = run_anchored_sequential(_frames(4), [ALPHA], runner=runner, identifier=identifier)
    assert isinstance(res, SequentialRietveldResult)
    assert len(res.frames) == 4
    assert res.phase_names == ("alpha",)
    assert res.appearances == ()
    assert all(f.rwp == 9.0 and not f.refine_failed for f in res.frames)


def test_identifier_none_is_m9_forward_pass():
    """相同定無効 → frame0 単一アンカー + 末尾端点前方パスで全フレーム被覆。"""
    def runner(frame, phases, cells):
        return _res(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    res = run_anchored_sequential(_frames(3), [ALPHA], runner=runner, identifier=None)
    assert len(res.frames) == 3
    assert all(not f.refine_failed for f in res.frames)
    assert any("fallback_anchor" in w for w in res.warnings)


def test_transition_crossover_locates_onset():
    """alpha 単相域 (0,1) と delta 支配域 (4,5) がアンカー、転移 (2,3) を双方向で詰め onset 確定。

    後方 (alpha+delta) は転移フレームでも Rwp が僅かに低いが、bic は delta が真に効くフレームのみ
    後方採用 → onset が物理的な転移点になる。
    """
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0,
                       base_params=30, per_phase_params=12)
    # frame0,1: alpha 高信頼; frame4,5: alpha+delta 高信頼; frame2,3: 低信頼 (転移)
    conf = {0: 0.9, 1: 0.9, 2: 0.2, 3: 0.2, 4: 0.85, 5: 0.9}
    specs = {0: (ALPHA,), 1: (ALPHA,), 2: (ALPHA,), 3: (ALPHA,),
             4: (ALPHA, DELTA), 5: (ALPHA, DELTA)}

    def identifier(frame):
        i = _idx(frame)
        return (conf[i], specs[i])

    def runner(frame, phases, cells):
        i = _idx(frame)
        names = [p.phase_name for p in phases]
        if names == ["alpha"]:
            # alpha 単相: 転移後 (i>=3) は破綻
            gof = 1.0 if i <= 2 else 3.0
            rwp = 9.0 if i <= 2 else 30.0
            return _res(rwp, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0}, gof=gof)
        # alpha+delta: delta 分率は i で増加、転移前 (i<=2) は僅少
        dfrac = {0: 0.01, 1: 0.02, 2: 0.05, 3: 0.30, 4: 0.55, 5: 0.75}.get(i, 0.3)
        gof = 1.4 if i <= 2 else 1.0  # 転移前は 2 相でも大して良くならない
        return _res(9.5 if i <= 2 else 9.0,
                    {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
                    {"alpha": 1 - dfrac, "new_delta": dfrac}, gof=gof)

    res = run_anchored_sequential(_frames(6), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert len(res.frames) == 6
    # delta が appearance として記録される
    ap = [a for a in res.appearances if a.phase_name == "new_delta"]
    assert ap, "delta の appearance が無い"
    onset = ap[0].frame_index
    assert 2 <= onset <= 4, f"onset={onset} が転移域外"
    # delta 分率が単調非減少 (物理的な転移)
    _, dvals = res.fraction_series("new_delta")
    assert dvals == tuple(sorted(dvals))
    # ledger 追記 + verify
    assert res.ledger is not None and res.ledger.verify()


def test_deterministic_bit_identical():
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)

    def identifier(frame):
        i = _idx(frame)
        return ((0.9 if i in (0, 3) else 0.2), (ALPHA,) if i < 2 else (ALPHA, DELTA))

    def runner(frame, phases, cells):
        names = [p.phase_name for p in phases]
        return _res(9.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
                    {names[0]: 1.0} if len(names) == 1 else {"alpha": 0.5, "new_delta": 0.5})

    a = run_anchored_sequential(_frames(4), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    b = run_anchored_sequential(_frames(4), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert [f.rwp for f in a.frames] == [f.rwp for f in b.frames]
    assert [f.phase_names for f in a.frames] == [f.phase_names for f in b.frames]
    assert [ap.frame_index for ap in a.appearances] == [ap.frame_index for ap in b.appearances]


def test_anchor_frames_carry_weight_fraction_esd_end_to_end():
    """アンカーフレームの出力に重量分率 + esd + 格子 esd が届く (段階B→Anchor→出力フレーム)。"""
    def identifier(frame):
        return (0.9, (ALPHA,))

    def runner(frame, phases, cells):
        return _res(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0},
                    wfracs={"alpha": 1.0}, wfrac_esd={"alpha": 0.0},
                    cesd={"alpha": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)})

    res = run_anchored_sequential(_frames(3), [ALPHA], runner=runner, identifier=identifier)
    # 全フレームがアンカー (単相高信頼) → 各フレームに esd が乗る
    for f in res.frames:
        assert f.phase_weight_fractions == {"alpha": 1.0}
        assert f.phase_weight_fraction_esd == {"alpha": 0.0}
        assert f.cell_esd["alpha"] == (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)


def test_failed_frame_has_empty_esd():
    """欠測フレーム (どのパスにも現れない) は esd なしで構築される。"""
    from tsumugin.insitu.anchor.engine import _failed_frame

    fr = _failed_frame(FrameSpec(data_path="x.xye", axis_value=1.0), 3)
    assert fr.refine_failed
    assert fr.phase_weight_fractions == {}
    assert fr.phase_weight_fraction_esd == {}
    assert fr.cell_esd == {}


def test_empty_frames_returns_empty():
    res = run_anchored_sequential([], [ALPHA], runner=lambda *a: None, identifier=None)
    assert res.frames == ()


def test_bond_gate_result_surfaces_in_warnings_and_ledger(monkeypatch):
    """FR-335 ゲートの結果が engine の warnings + ledger に出ること。

    select.py の判定ロジック自体は test_select.py が押さえているが、**その結果が ③ に
    届くか**は engine の責務。結合ゲートが「僅差帯に妥当な経路が無い」と判断したのに
    黙って採用すると、③ は相集合を疑う手掛かりを失う。

    select.py は `check_bond_validity` を呼び出し時に遅延 import するため、モジュール属性の
    差し替えが実行時に効く (実 CIF なしで警告経路を通せる)。
    """
    import tsumugin.autorietveld.validity as validity_mod

    def fake_check(structure_path, refined_cell=None, *, bond_tol_lo=0.7,
                   bond_tol_hi=1.3, expected_coordination=None):
        # delta を常に結合不当 (崩壊セル) とみなす
        return ValidityReport(passed="delta" not in structure_path)

    monkeypatch.setattr(validity_mod, "check_bond_validity", fake_check)

    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0,
                       base_params=30, per_phase_params=12, require_bond_validity=True)
    conf = {0: 0.9, 1: 0.9, 2: 0.2, 3: 0.2, 4: 0.85, 5: 0.9}
    specs = {0: (ALPHA,), 1: (ALPHA,), 2: (ALPHA,), 3: (ALPHA,),
             4: (ALPHA, DELTA), 5: (ALPHA, DELTA)}

    def identifier(frame):
        i = _idx(frame)
        return (conf[i], specs[i])

    def runner(frame, phases, cells):
        i = _idx(frame)
        names = [p.phase_name for p in phases]
        if names == ["alpha"]:
            gof = 1.0 if i <= 2 else 3.0
            rwp = 9.0 if i <= 2 else 30.0
            return _res(rwp, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0}, gof=gof)
        dfrac = {0: 0.01, 1: 0.02, 2: 0.05, 3: 0.30, 4: 0.55, 5: 0.75}.get(i, 0.3)
        gof = 1.4 if i <= 2 else 1.0
        return _res(9.5 if i <= 2 else 9.0,
                    {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
                    {"alpha": 1 - dfrac, "new_delta": dfrac}, gof=gof)

    res = run_anchored_sequential(_frames(6), [ALPHA], runner=runner,
                                  identifier=identifier, cfg=cfg)

    gates = [e.payload.get("bond_gate") for e in res.ledger.entries
             if e.kind == "m10_segment_choice"]
    assert gates, "m10_segment_choice が ledger に無い"
    assert any(g == "no_valid_candidate" for g in gates), (
        f"delta を全て結合不当にしたのにゲートが発火していない: {gates}"
    )
    assert any("FR-335" in w for w in res.warnings), (
        f"ゲート結果が warnings に出ていない (③ から不可視): {res.warnings}"
    )
    assert res.ledger.verify()
