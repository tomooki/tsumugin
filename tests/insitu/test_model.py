"""M9 insitu.model の純テスト (numpy-only, GSAS/MP 非依存)。"""

from __future__ import annotations

import pytest

from tsumugin.insitu.model import (
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


def test_phaseid_config_enabled():
    assert not PhaseIdConfig().enabled
    assert PhaseIdConfig(elements=("Ca", "Te", "O")).enabled


def test_phaseid_config_pawley_defaults():
    """Issue #20: 新相の異方セル補正は既定 ON、波長は Cu Kα1 既定。"""
    pid = PhaseIdConfig()
    assert pid.refine_new_phase_cell is True
    assert abs(pid.wavelength - 1.5406) < 1e-9


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


def test_phase_appearance_fields():
    ap = PhaseAppearance(
        phase_name="delta", frame_index=2, axis_value=340.0,
        structure_path="/tmp/delta.cif", source="materials_project",
        rwp_before=15.0, rwp_after=9.5, evidence={"dara_score": 0.42},
    )
    assert ap.rwp_after < ap.rwp_before
    assert ap.evidence["dara_score"] == 0.42
