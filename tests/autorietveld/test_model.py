"""TASK-0701: autorietveld.model の純データ dataclass 群 (GSAS 非依存)。"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.autorietveld import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)


def test_radiation_and_geometry_enums_have_expected_members():
    assert {r.name for r in Radiation} >= {
        "XRAY_LAB",
        "XRAY_SYNCHROTRON",
        "NEUTRON_CW",
        "NEUTRON_TOF",
    }
    assert {g.name for g in Geometry} >= {"BRAGG_BRENTANO", "DEBYE_SCHERRER"}


def test_histogram_spec_is_frozen_and_holds_paths():
    h = HistogramSpec(
        data_path="a/FAP.XRA",
        instrument_path="a/INST_XRY.PRM",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    assert h.data_path == "a/FAP.XRA"
    assert h.data_format == "GSAS"  # 既定
    with pytest.raises(dataclasses.FrozenInstanceError):
        h.data_path = "x"  # type: ignore[misc]


def test_phase_spec_defaults():
    p = PhaseSpec(structure_path="a/FAP.EXP", phase_name="fap", format_hint="EXP")
    assert p.mixed_occupancy_groups == ()
    assert p.temperature is None


def test_refinement_stage_flags_immutable():
    s = RefinementStage(label="S0", flags={"Background": {"refine": True}})
    assert s.label == "S0"
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.label = "x"  # type: ignore[misc]


def test_stage_result_records_metrics():
    r = StageResult(
        label="S1", rwp=13.7, gof=2.4, n_params=10, converged=True, reverted=False
    )
    assert r.rwp == pytest.approx(13.7)
    assert not r.reverted


def test_auto_rietveld_result_aggregates():
    sr = (
        StageResult(label="S0", rwp=45.0, gof=8.0, n_params=7, converged=True, reverted=False),
        StageResult(label="S1", rwp=13.7, gof=2.4, n_params=10, converged=True, reverted=False),
    )
    validity = ValidityReport(passed=True, checks=(), warnings=())
    res = AutoRietveldResult(
        stage_results=sr,
        final_rwp=13.7,
        final_gof=2.4,
        refined_cells={"fap": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=validity,
        gpx_path="x.gpx",
    )
    assert res.final_rwp == pytest.approx(13.7)
    assert res.stage_results[-1].label == "S1"
    assert res.validity.passed


def test_validity_report_holds_check_items():
    rep = ValidityReport(
        passed=False,
        checks=(("lattice_a", True, "9.37 within tol"), ("uiso", False, "Uiso<0")),
        warnings=("non-converged",),
    )
    assert not rep.passed
    assert rep.checks[1][1] is False
    assert "non-converged" in rep.warnings


def test_stage_result_revert_reason_defaults_keep_old_constructors_valid():
    """fit-then-judge P1a タスク 1: 新フィールドは末尾追加・既定値で後方互換。

    既定の ``revert_reason=None`` は「受理」か「理由を記録しない経路」を意味する
    (``reverted`` と組で読む)。``is_noop=False`` は既存の no-op 検出 (ledger) と同じ判定を
    結果側にも載せるためのもので、既定は「検出していない」。
    """
    from tsumugin.autorietveld.model import StageResult

    s = StageResult(label="cell", rwp=10.0, gof=1.0, n_params=3, converged=True)
    assert s.revert_reason is None
    assert s.is_noop is False


def test_phase_spec_uiso_equiv_groups_round_trip_and_default():
    """fit-then-judge P1a タスク 2: Uiso の等値の組。既定は空 (= 張らない) で後方互換。"""
    from tsumugin.autorietveld.model import PhaseSpec

    assert PhaseSpec("x.cif", "x").uiso_equiv_groups == ()
    spec = PhaseSpec("x.cif", "x", uiso_equiv_groups=(("O1", "O2"), ("Y1", "Y2")))
    d = spec.to_dict()
    assert d["uiso_equiv_groups"] == [["O1", "O2"], ["Y1", "Y2"]]
    assert PhaseSpec.from_dict(d) == spec
    # キーが無い古い JSON も読める
    legacy = {k: v for k, v in d.items() if k != "uiso_equiv_groups"}
    assert PhaseSpec.from_dict(legacy).uiso_equiv_groups == ()
