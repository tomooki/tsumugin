"""M10 anchor/extract.py — 信頼度合成 + 2 段ゲートのアンカー抽出テスト (stub runner/identifier)。"""

from __future__ import annotations

from types import SimpleNamespace

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.anchor.extract import anchor_confidence, extract_anchors
from tsumugin.insitu.anchor.model import AnchorConfig
from tsumugin.insitu.model import FrameSpec


def _ident(scores, *, strain=0.0, has_unknown=False):
    """合成信頼度テスト用の軽量 PhaseIdentification もどき (duck-typed)。"""
    matches = [SimpleNamespace(score=s, strain=strain) for s in scores]
    return SimpleNamespace(matches=matches, unmatched=SimpleNamespace(has_unknown=has_unknown))


def _result(rwp, cells, fracs, *, valid=True, gof=1.0, wfracs=None, wfrac_esd=None, cesd=None):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=gof, refined_cells=cells,
        validity=ValidityReport(passed=valid), phase_fractions=fracs,
        phase_weight_fractions=wfracs or {}, phase_weight_fraction_esd=wfrac_esd or {},
        cell_esd=cesd or {},
    )


def _frames(n):
    return [FrameSpec(data_path=f"f{i}.xye", axis_value=float(300 + i * 30)) for i in range(n)]


ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
DELTA = PhaseSpec(structure_path="delta.cif", phase_name="new_delta")


# --- anchor_confidence ---

def test_confidence_empty_matches_zero():
    cfg = AnchorConfig()
    assert anchor_confidence(_ident([]), cfg) == 0.0


def test_confidence_high_score_wide_margin():
    cfg = AnchorConfig(w_score=1.0, w_margin=1.0, w_strain=2.0, margin_cap=0.5)
    # 首位 0.9, 次点 0.2 → margin 0.7 は cap 0.5 で飽和 → 0.9 + 0.5 = 1.4
    assert anchor_confidence(_ident([0.9, 0.2]), cfg) == 1.4


def test_confidence_penalizes_strain_and_unknown():
    cfg = AnchorConfig(w_score=1.0, w_margin=0.0, w_strain=2.0, w_unknown=0.5)
    base = anchor_confidence(_ident([0.8]), cfg)          # 0.8
    strained = anchor_confidence(_ident([0.8], strain=0.1), cfg)   # 0.8 - 0.2
    unknown = anchor_confidence(_ident([0.8], has_unknown=True), cfg)  # 0.8 - 0.5
    assert base == 0.8
    assert strained < base
    assert unknown < base


# --- extract_anchors ---

def test_identifier_none_gives_frame0_fallback():
    """相同定無効 → frame0 単一 fallback アンカー (M9 相当, REQ-1004)。"""
    def runner(frame, phases, cells):
        return _result(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    anchors = extract_anchors(_frames(4), [ALPHA], runner=runner, identifier=None)
    assert len(anchors) == 1
    assert anchors[0].frame_index == 0
    assert anchors[0].fallback is True
    assert anchors[0].phase_names == ("alpha",)


def test_two_stage_gate_confirms_low_rwp_confident_frames():
    """段階A 高信頼 ∧ 段階B Rwp低+valid のフレームのみ確定 (REQ-1001/1002)。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)
    # frame0,3 高信頼; frame1,2 低信頼 (転移域相当)
    conf = {0: 0.9, 1: 0.2, 2: 0.1, 3: 0.8}

    def identifier(frame):
        i = int((frame.axis_value - 300) / 30)
        return (conf[i], (ALPHA,))

    def runner(frame, phases, cells):
        return _result(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    anchors = extract_anchors(_frames(4), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert [a.frame_index for a in anchors] == [0, 3]  # 高信頼のみ, フレーム順


def test_stage_b_rejects_high_rwp_despite_confidence():
    """段階A 高信頼でも段階B Rwp が閾値超なら棄却 (peak-rich 誤マッチ対策, REQ-1002)。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)

    def identifier(frame):
        return (0.9, (ALPHA,))  # 全フレーム高信頼

    def runner(frame, phases, cells):
        i = int((frame.axis_value - 300) / 30)
        rwp = 9.0 if i == 2 else 40.0  # frame2 のみ低 Rwp
        return _result(rwp, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    anchors = extract_anchors(_frames(4), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert [a.frame_index for a in anchors] == [2]  # Rwp ゲートを通ったのは frame2 のみ


def test_validity_not_required_by_default():
    """既定 (require_anchor_validity=False): validity fail でも Rwp+信頼度でアンカー確定。

    高温系列は室温 CIF 基準の validity を軒並み fail するため (M9 H1 同根)、既定で validity を課さない。
    """
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)  # require_anchor_validity 既定 False

    def identifier(frame):
        return (0.9, (ALPHA,))

    def runner(frame, phases, cells):
        return _result(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0}, valid=False)

    anchors = extract_anchors(_frames(3), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert [a.frame_index for a in anchors] == [0, 1, 2]  # validity False でも全て確定
    assert all(not a.validity_passed for a in anchors)


def test_validity_gate_opt_in():
    """require_anchor_validity=True なら validity fail フレームをアンカーから除外。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0, require_anchor_validity=True)

    def identifier(frame):
        return (0.9, (ALPHA,))

    def runner(frame, phases, cells):
        i = int((frame.axis_value - 300) / 30)
        return _result(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0}, valid=(i == 1))

    anchors = extract_anchors(_frames(3), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert [a.frame_index for a in anchors] == [1]  # validity pass は frame1 のみ


def test_fallback_when_no_confident_anchor():
    """確定 0 個 → 最高信頼フレームを 1 個 fallback アンカーに (REQ-1003)。"""
    cfg = AnchorConfig(anchor_confidence_min=0.9)  # 誰も満たさない

    def identifier(frame):
        i = int((frame.axis_value - 300) / 30)
        return ({0: 0.3, 1: 0.6, 2: 0.2}[i], (ALPHA,))

    def runner(frame, phases, cells):
        return _result(12.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    anchors = extract_anchors(_frames(3), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert len(anchors) == 1
    assert anchors[0].frame_index == 1  # 最高信頼 (0.6)
    assert anchors[0].fallback is True


def test_multiphase_anchor_carries_phase_set():
    """delta 支配域は delta を含む相集合でアンカー化 (多相アンカー)。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)

    def identifier(frame):
        return (0.8, (ALPHA, DELTA))

    def runner(frame, phases, cells):
        names = [p.phase_name for p in phases]
        return _result(9.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
                       {"alpha": 0.3, "new_delta": 0.7})

    anchors = extract_anchors(_frames(1), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert anchors[0].phase_names == ("alpha", "new_delta")


def test_anchor_carries_weight_fractions_and_esd():
    """段階 B の重量分率 + esd + 格子 esd が Anchor へ貫通する (出力フレームへ運ぶための中継)。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)

    def identifier(frame):
        return (0.8, (ALPHA, DELTA))

    def runner(frame, phases, cells):
        names = [p.phase_name for p in phases]
        return _result(
            9.0, {n: (5.0, 5.0, 5.0, 90, 90, 90) for n in names},
            {"alpha": 0.3, "new_delta": 0.7},
            wfracs={"alpha": 0.42, "new_delta": 0.58},
            wfrac_esd={"alpha": 0.007, "new_delta": 0.007},
            cesd={"alpha": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0),
                  "new_delta": (0.002, 0.002, 0.002, 0.0, 0.0, 0.0)},
        )

    anchors = extract_anchors(_frames(1), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    a = anchors[0]
    assert a.phase_weight_fractions == {"alpha": 0.42, "new_delta": 0.58}
    assert a.phase_weight_fraction_esd == {"alpha": 0.007, "new_delta": 0.007}
    assert a.cell_esd["new_delta"] == (0.002, 0.002, 0.002, 0.0, 0.0, 0.0)


def test_anchor_esd_empty_when_runner_omits():
    """重量分率/esd を返さない runner では Anchor の該当フィールドは空 dict。"""
    cfg = AnchorConfig(anchor_confidence_min=0.5, anchor_rwp_max=15.0)

    def identifier(frame):
        return (0.9, (ALPHA,))

    def runner(frame, phases, cells):
        return _result(9.0, {"alpha": (5.0, 5.0, 5.0, 90, 90, 90)}, {"alpha": 1.0})

    anchors = extract_anchors(_frames(1), [ALPHA], runner=runner, identifier=identifier, cfg=cfg)
    assert anchors[0].phase_weight_fractions == {}
    assert anchors[0].cell_esd == {}


def test_empty_frames():
    assert extract_anchors([], [ALPHA], runner=lambda *a: None, identifier=None) == ()
