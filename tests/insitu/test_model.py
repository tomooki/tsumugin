"""M9 insitu.model の純テスト (numpy-only, GSAS/MP 非依存)。"""

from __future__ import annotations

import json

import pytest

from tsumugin.insitu.model import (
    FractionBasisUnavailableError,
    FrameRietveldResult,
    FrameSpec,
    PhaseAppearance,
    PhaseIdConfig,
    SequentialRietveldResult,
)


def _frame(i, axis, cells, fracs, names, failed=False):
    return FrameRietveldResult(
        frame_index=i,
        axis_value=axis,
        data_path=f"f{i}.xrdml",
        rwp=9.0 + i * 0.1,
        gof=1.0,
        refined_cells=cells,
        phase_fractions=fracs,
        phase_names=names,
        refine_failed=failed,
    )


def _result():
    a = "alpha"
    d = "delta"
    frames = (
        _frame(0, 300.0, {a: (14.8, 6.79, 8.06, 90, 90, 90)}, {a: 1.0}, (a,)),
        _frame(1, 320.0, {a: (14.82, 6.80, 8.07, 90, 90, 90)}, {a: 1.0}, (a,)),
        _frame(
            2, 340.0,
            {a: (14.85, 6.81, 8.08, 90, 90, 90), d: (13.32, 6.53, 8.17, 90, 90, 90)},
            {a: 0.7, d: 0.3}, (a, d),
        ),
        _frame(
            3, 360.0,
            {d: (13.35, 6.54, 8.18, 90, 90, 90)},
            {d: 1.0}, (d,),
        ),
    )
    return SequentialRietveldResult(
        frames=frames, phase_names=("alpha", "delta")
    )


def test_framespec_dict_roundtrip():
    fs = FrameSpec(data_path="x.xrdml", axis_value=300.0, two_theta_limits=(10.0, 80.0), label="f0")
    assert FrameSpec.from_dict(fs.to_dict()) == fs


def test_framespec_dict_roundtrip_none_limits():
    fs = FrameSpec(data_path="x.fxye", data_format="FXYE")
    d = fs.to_dict()
    assert d["two_theta_limits"] is None
    assert FrameSpec.from_dict(d) == fs


def test_framespec_target_composition_roundtrip():
    """FR-318 T5: per-frame 組成目標は FrameSpec に載せて JSON 境界を往復する。"""
    from tsumugin.insitu.model import TargetComposition

    tc = TargetComposition(
        total=1.25, per_phase={"mono": 1.944, "cubic": 0.7}, mode="lock_fractions", esd=0.03,
    )
    fs = FrameSpec(data_path="x.xye", data_format="XYE", target_composition=tc)
    d = fs.to_dict()
    assert json.dumps(d)  # JSON 直列化可能 (② 境界)
    restored = FrameSpec.from_dict(d)
    assert restored.target_composition is not None
    assert restored.target_composition.total == pytest.approx(1.25)
    assert restored.target_composition.per_phase["mono"] == pytest.approx(1.944)
    assert restored.target_composition.mode == "lock_fractions"


def test_framespec_target_composition_default_none_roundtrip():
    """target_composition 無指定 (既定 None) でも往復同一 (後方互換)。"""
    fs = FrameSpec(data_path="x.xye", data_format="XYE")
    assert fs.target_composition is None
    assert FrameSpec.from_dict(fs.to_dict()) == fs


def test_target_composition_invalid_mode_raises():
    from tsumugin.insitu.model import TargetComposition

    with pytest.raises(ValueError, match="mode"):
        TargetComposition(total=1.0, per_phase={}, mode="bogus")


def test_target_composition_default_mode_is_diagnose():
    """既定モードは diagnose (ユーザー確定判断: lock は明示 opt-in)。"""
    from tsumugin.insitu.model import TargetComposition

    assert TargetComposition(total=1.0, per_phase={}).mode == "diagnose"


def test_charge_constraint_config_roundtrip_and_enabled():
    """FR-318 T6: 系列レベル設定。mobile_sites が無ければ disabled。"""
    from tsumugin.insitu.model import ChargeConstraintConfig
    from tsumugin.operando.coulometry import MobileSiteSpec

    assert not ChargeConstraintConfig().enabled
    cfg = ChargeConstraintConfig(
        mobile_sites=(
            MobileSiteSpec(phase_name="mono", site_labels=("K",), multiplicities=(4.0,)),
        ),
        z_formula={"mono": 2.0},
        formula_weights={"mono": 678.8},
        mode="diagnose",
        esd=0.05,
        anchor_ab_threshold=1.0,
    )
    assert cfg.enabled
    d = cfg.to_dict()
    assert json.dumps(d)
    restored = ChargeConstraintConfig.from_dict(d)
    assert restored == cfg


def test_charge_constraint_config_invalid_mode_raises():
    from tsumugin.insitu.model import ChargeConstraintConfig

    with pytest.raises(ValueError, match="mode"):
        ChargeConstraintConfig(mode="hard")  # 旧称 hard は存在しない (lock_fractions)


def test_sequential_config_accepts_charge_constraint():
    from tsumugin.insitu.model import ChargeConstraintConfig, SequentialConfig

    cfg = SequentialConfig(charge_constraint=ChargeConstraintConfig())
    assert cfg.charge_constraint is not None
    assert SequentialConfig().charge_constraint is None


def test_phaseid_config_enabled():
    assert not PhaseIdConfig().enabled
    assert PhaseIdConfig(elements=("Ca", "Te", "O")).enabled


def test_phaseid_config_cell_refine_defaults():
    """Issue #20: 新相の異方セル補正は既定 ON、波長は Cu Kα1 既定、異方 re-score top-5 既定。"""
    pid = PhaseIdConfig()
    assert pid.refine_new_phase_cell is True
    assert abs(pid.wavelength - 1.5406) < 1e-9
    assert pid.rerank_top_k == 5


def test_axis_values():
    r = _result()
    assert r.axis_values() == (300.0, 320.0, 340.0, 360.0)


def test_cell_series_only_present_frames():
    r = _result()
    axes, a_vals = r.cell_series("alpha", "a")
    # alpha は frame 0,1,2 に存在 (frame3 は delta のみ)
    assert axes == (300.0, 320.0, 340.0)
    assert a_vals == pytest.approx((14.8, 14.82, 14.85))
    d_axes, d_c = r.cell_series("delta", "c")
    assert d_axes == (340.0, 360.0)
    assert d_c == pytest.approx((8.17, 8.18))


def test_cell_series_skips_failed_frame():
    frames = (
        _frame(0, 300.0, {"a": (5.0, 5.0, 5.0, 90, 90, 90)}, {"a": 1.0}, ("a",)),
        _frame(1, 310.0, {"a": (9.9, 9.9, 9.9, 90, 90, 90)}, {"a": 1.0}, ("a",), failed=True),
        _frame(2, 320.0, {"a": (5.1, 5.1, 5.1, 90, 90, 90)}, {"a": 1.0}, ("a",)),
    )
    r = SequentialRietveldResult(frames=frames)
    axes, vals = r.cell_series("a", "a")
    assert axes == (300.0, 320.0)  # failed frame 1 除外
    assert vals == pytest.approx((5.0, 5.1))


def test_fraction_series_zero_when_absent():
    r = _result()
    axes, fracs = r.fraction_series("delta")
    # delta は frame0,1 で不在 → 0.0
    assert axes == (300.0, 320.0, 340.0, 360.0)
    assert fracs == pytest.approx((0.0, 0.0, 0.3, 1.0))


# ===========================================================================
# `fraction_series` の basis (Issue #96 レビュー第4巡 HIGH)
# ---------------------------------------------------------------------------
# `transition_from_fractions` → `estimate_transition` は **絶対レベル 0.50/0.10 の交差**を
# 報告するため、y 軸を Scale から wt% に替えると答えが動く (= Scale は「相対比較のみ」では
# 済まない)。実測 K2Mn[Fe(CN)6]: Scale は 0.50 を横切り midpoint 9.515 h を出すが、同じ fit の
# wt% は 0.472 までしか上がらず**転移なし**。Scale=0.50 の点は実際には 34.0 wt% である。
# ===========================================================================


def _wt_frame(i, axis, fracs, weights, names, failed=False):
    """Scale と重量分率を別々に持つフレーム (両者が食い違う実データの形)。"""
    return FrameRietveldResult(
        frame_index=i, axis_value=axis, data_path=f"f{i}.xrdml", rwp=8.0, gof=1.0,
        refined_cells={n: (10.0, 10.0, 10.0, 90, 90, 90) for n in names},
        phase_fractions=fracs, phase_names=names,
        phase_weight_fractions=weights, refine_failed=failed,
    )


def _divergent_result():
    """Scale は 0.50 を横切るが wt% は横切らない系列 (実測 tetra fr96-126 の縮図)。"""
    rows = [(0.0, 0.0, 0.0), (1.0, 0.30, 0.19), (2.0, 0.50, 0.34), (3.0, 0.656, 0.472)]
    frames = tuple(
        _wt_frame(i, ax, {"tetra": s, "cubic": 1.0 - s}, {"tetra": w, "cubic": 1.0 - w},
                  ("tetra", "cubic"))
        for i, (ax, s, w) in enumerate(rows)
    )
    return SequentialRietveldResult(frames=frames, phase_names=("tetra", "cubic"))


def test_fraction_series_default_basis_is_scale_backcompat():
    """既定 basis は Scale (既存の呼び出し側・テストの意味を変えない)。"""
    r = _divergent_result()
    axes, fracs = r.fraction_series("tetra")
    assert axes == (0.0, 1.0, 2.0, 3.0)
    assert fracs == pytest.approx((0.0, 0.30, 0.50, 0.656))
    assert r.fraction_series("tetra", basis="scale") == (axes, fracs)


def test_fraction_series_weight_basis_returns_weight_fractions():
    """basis="weight" は **Scale ではなく**重量分率の系列を返す (出版値の軸)。"""
    r = _divergent_result()
    axes, weights = r.fraction_series("tetra", basis="weight")
    assert axes == (0.0, 1.0, 2.0, 3.0)
    assert weights == pytest.approx((0.0, 0.19, 0.34, 0.472))


def test_fraction_series_weight_basis_raises_when_unavailable():
    """★重量分率が無いフレームで **Scale へ黙って落ちない** (落ちたらこのバグそのもの)。

    スタブ runner / 非 GSAS 経路は `phase_weight_fractions` が空。ここで Scale を返すと
    呼び出し側は「重量分率を要求して受け取った」と信じたまま Scale の数字を出版する。
    """
    r = SequentialRietveldResult(
        frames=(_wt_frame(0, 0.0, {"t": 0.5}, {}, ("t",)),
                _wt_frame(1, 1.0, {"t": 0.9}, {}, ("t",))),
    )
    with pytest.raises(FractionBasisUnavailableError) as exc:
        r.fraction_series("t", basis="weight")
    assert "0" in str(exc.value) and "1" in str(exc.value)  # 欠測フレームを名指しする
    # Scale なら同じ系列が問題なく取れる = 「データが無い」のではなく「重量分率が無い」
    assert r.fraction_series("t", basis="scale")[1] == pytest.approx((0.5, 0.9))


def test_fraction_series_weight_basis_partial_availability_raises():
    """一部フレームだけ重量分率が欠けている場合も**穴を無かったことにしない**。

    欠測フレームを黙って落とすと、交差の線形補間が別の隣接対で行われ midpoint が動く
    (= 静かに違う数字になる)。
    """
    r = SequentialRietveldResult(
        frames=(_wt_frame(0, 0.0, {"t": 0.0}, {"t": 0.0}, ("t",)),
                _wt_frame(1, 1.0, {"t": 0.5}, {}, ("t",)),
                _wt_frame(2, 2.0, {"t": 1.0}, {"t": 0.9}, ("t",))),
    )
    with pytest.raises(FractionBasisUnavailableError) as exc:
        r.fraction_series("t", basis="weight")
    assert "1" in str(exc.value)


def test_fraction_series_weight_basis_zero_fills_absent_phase():
    """重量分率を持つフレームで当該相が**相集合に無い**なら 0.0 (Scale と同じ意味論)。

    「重量分率 dict が空」(= 測っていない) と「相が相集合に無い」(= 0 wt%) を区別する。
    """
    r = SequentialRietveldResult(
        frames=(_wt_frame(0, 0.0, {"a": 1.0}, {"a": 1.0}, ("a",)),
                _wt_frame(1, 1.0, {"a": 0.4, "b": 0.6}, {"a": 0.3, "b": 0.7}, ("a", "b"))),
    )
    axes, weights = r.fraction_series("b", basis="weight")
    assert axes == (0.0, 1.0)
    assert weights == pytest.approx((0.0, 0.7))  # frame0 は b 不在 → 0.0


def test_fraction_series_rejects_unknown_basis():
    """未知の basis は静かに Scale へ落ちず ValueError (② が error dict へ縮退できる)。"""
    with pytest.raises(ValueError, match="basis"):
        _divergent_result().fraction_series("tetra", basis="wt%")  # type: ignore[arg-type]


def test_frame_result_esd_fields_default_empty():
    """新設 esd/重量分率フィールドは既定空 dict (後方互換: 既存構築サイトは指定不要)。"""
    fr = _frame(0, 300.0, {"a": (5.0, 5.0, 5.0, 90, 90, 90)}, {"a": 1.0}, ("a",))
    assert fr.phase_weight_fractions == {}
    assert fr.phase_weight_fraction_esd == {}
    assert fr.cell_esd == {}


def test_frame_result_esd_fields_carry_values():
    """明示指定した重量分率/esd/格子 esd が保持される。"""
    fr = FrameRietveldResult(
        frame_index=0, axis_value=300.0, data_path="f0.xrdml", rwp=9.0, gof=1.0,
        refined_cells={"a": (5.0, 5.0, 5.0, 90, 90, 90)}, phase_fractions={"a": 1.0},
        phase_names=("a",),
        phase_weight_fractions={"a": 0.63}, phase_weight_fraction_esd={"a": 0.004},
        cell_esd={"a": (0.001, 0.001, 0.002, 0.0, 0.0, 0.0)},
    )
    assert fr.phase_weight_fractions["a"] == 0.63
    assert fr.phase_weight_fraction_esd["a"] == 0.004
    assert fr.cell_esd["a"][2] == 0.002


def test_frame_result_esd_fields_json_safe():
    """新フィールドは JSON シリアライズ可能 (② MCP 境界を越えられる)。"""
    fr = FrameRietveldResult(
        frame_index=1, axis_value=320.0, data_path="f1.xrdml", rwp=8.0, gof=1.1,
        refined_cells={"cubic": (10.0, 10.0, 10.0, 90, 90, 90)},
        phase_fractions={"cubic": 0.5, "tetra": 0.5}, phase_names=("cubic", "tetra"),
        phase_weight_fractions={"cubic": 0.68, "tetra": 0.32},
        phase_weight_fraction_esd={"cubic": 0.005, "tetra": 0.005},
        cell_esd={"cubic": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
    )
    payload = {
        "phase_weight_fractions": dict(fr.phase_weight_fractions),
        "phase_weight_fraction_esd": dict(fr.phase_weight_fraction_esd),
        "cell_esd": {k: list(v) for k, v in fr.cell_esd.items()},
    }
    round_trip = json.loads(json.dumps(payload))
    assert round_trip["phase_weight_fractions"]["cubic"] == 0.68
    assert round_trip["cell_esd"]["cubic"] == [0.001, 0.001, 0.001, 0.0, 0.0, 0.0]


def test_phase_appearance_fields():
    ap = PhaseAppearance(
        phase_name="delta", frame_index=2, axis_value=340.0,
        structure_path="/tmp/delta.cif", source="materials_project",
        rwp_before=15.0, rwp_after=9.5, evidence={"dara_score": 0.42},
    )
    assert ap.rwp_after < ap.rwp_before
    assert ap.evidence["dara_score"] == 0.42
