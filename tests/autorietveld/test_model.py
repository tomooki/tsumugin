"""TASK-0701: autorietveld.model の純データ dataclass 群 (GSAS 非依存)。"""

from __future__ import annotations

import dataclasses
import re

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


def _param_entry(doc: str, name: str) -> str:
    """docstring の ``:param <name>:`` 項目 (次の ``:param`` か末尾まで) を返す。"""
    m = re.search(rf":param {name}:(.*?)(?=\n\s*:param |\Z)", doc, re.S)
    assert m, f":param {name}: が docstring に無い"
    return m.group(1)


def test_phase_spec_temperature_is_documented_as_metadata_that_no_engine_reads():
    """★`PhaseSpec.temperature` の docstring は「どのエンジンも読まない」と言い、温度の置き場所を指す。

    旧 docstring は「ヒストグラム間温度差の吸収判定に用いる」と書いていたが、判定
    (`recipe.has_temperature_difference`、TOPAS 経路も同じ関数) が読むのは
    `HistogramSpec.temperature` だけで、相の値はどこからも読まれていなかった — 文書を信じて
    相に温度を入れると**呼べるが黙って効かない**。読まれないことの実証は
    `test_recipe.py` / `topas/test_recipe.py` の `test_phase_temperature_is_not_read_*`。
    """
    entry = _param_entry(PhaseSpec.__doc__ or "", "temperature")
    assert "読まない" in entry, "相の temperature が効かないことを docstring が言っていない"
    assert "HistogramSpec.temperature" in entry, "温度の置き場所を docstring が指していない"
    assert "吸収判定に用いる" not in entry, "効くかのような旧記述が残っている"


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
