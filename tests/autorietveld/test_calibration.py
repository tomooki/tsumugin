"""波長・ゼロ点較正 (calibrate_instrument_from_standard, Issue #61) の決定論テスト。

較正は runner 注入で GSAS 非依存。実 CeO2 較正は test_calibration_gsas.py (gated)。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    CalibrationResult,
    Geometry,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.resolution import (
    STANDARD_CELL_A,
    build_calibration_recipe,
    calibrate_instrument_from_standard,
)


# --- CalibrationResult ---

def test_calibration_result_roundtrip():
    c = CalibrationResult(
        wavelength=0.4964005, wavelength_init=0.4962537, zero=-0.015,
        profile={"U": 0.0, "V": 2.66, "W": 0.0, "X": 0.70, "Y": 0.0},
        reference_cell=(5.41165,) * 3 + (90.0,) * 3, source_rwp=11.98,
    )
    d = CalibrationResult.from_dict(c.to_dict())
    assert d.wavelength == c.wavelength and d.zero == c.zero
    assert d.reference_cell == c.reference_cell
    assert d.profile == c.profile


def test_ppm_shift():
    c = CalibrationResult(0.4964005, 0.4962537, -0.015, {}, (5.41165,) * 3 + (90.0,) * 3)
    assert math.isclose(c.ppm_shift, 1e6 * (0.4964005 - 0.4962537) / 0.4962537, rel_tol=1e-9)


def test_ppm_shift_zero_init():
    assert math.isnan(CalibrationResult(0.5, 0.0, 0.0, {}, (5.4,) * 3 + (90.0,) * 3).ppm_shift)


def test_to_instrument_profile_carries_zero_and_wavelength():
    c = CalibrationResult(0.49640, 0.49625, -0.015, {"V": 2.66, "X": 0.70},
                          (5.41165,) * 3 + (90.0,) * 3, source_rwp=12.0)
    ip = c.to_instrument_profile()
    assert ip.values["Zero"] == -0.015
    assert ip.values["V"] == 2.66 and ip.values["X"] == 0.70
    assert ip.wavelength == 0.49640


# --- build_calibration_recipe ---

def test_calibration_recipe_default_no_wavelength():
    # 既定は波長 (Lam) を解放しない (低角縮退のため)
    r = build_calibration_recipe(geometry=Geometry.DEBYE_SCHERRER)
    flags = [dict(s.flags) for s in r]
    assert "background" in flags[0] and flags[0]["scale"] is True
    assert flags[1]["profile"] == ["Zero"] and 0 in flags[1]["displacement"]
    assert flags[2]["profile"] == ["W"]
    assert flags[3]["profile"] == ["U", "V", "W", "X", "Y", "Zero"]
    assert len(r) == 4
    assert all("Lam" not in s.flags.get("profile", []) for s in r)


def test_calibration_recipe_refine_wavelength_adds_lam_stage():
    r = build_calibration_recipe(refine_wavelength=True)
    assert len(r) == 5
    lam_stages = [s for s in r if "Lam" in s.flags.get("profile", [])]
    assert len(lam_stages) == 1
    # Lam は変位・プロファイル (U..Y) と同段で解放しない (縮退・発散回避)
    prof = list(lam_stages[0].flags["profile"])
    assert "displacement" not in lam_stages[0].flags
    assert not ({"U", "V", "W", "X", "Y"} & set(prof))


def test_calibration_recipe_no_shl():
    for s in build_calibration_recipe(refine_wavelength=True):
        assert "SH/L" not in s.flags.get("profile", [])


def test_calibration_recipe_no_cell_flag():
    # 格子は refine_cell=False で固定するため recipe に cell 段は無い
    for s in build_calibration_recipe():
        assert "cell" not in s.flags


def test_calibration_recipe_geometry_displacement():
    bb = build_calibration_recipe(geometry=Geometry.BRAGG_BRENTANO)
    assert bb[1].flags["displacement"][0] == ["Shift"]


# --- calibrate_instrument_from_standard (stub runner) ---

def _xy_file(tmp_path):
    p = tmp_path / "raw.xy"
    p.write_text("\n".join(f"{2.0 + 0.1 * i:.3f} {100 + i}" for i in range(40)), encoding="utf-8")
    return str(p)


def _stub_result(lam, zero):
    prof = {"Lam": lam, "U": 0.0, "V": 2.66, "W": 0.0, "X": 0.70, "Y": 0.0,
            "SH/L": 0.002, "Zero": zero}
    return AutoRietveldResult(
        stage_results=(StageResult("cal UVWXY+Zero", rwp=12.0, gof=6.0, n_params=6, converged=True),),
        final_rwp=12.0, final_gof=6.0, refined_cells={"CeO2": (5.41165,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True), hist_profile=(prof,),
    )


def test_calibrate_fixes_cell_and_keeps_wavelength(tmp_path):
    captured = {}

    def stub(hists, phases, *, recipe=None, initial_cells=None, **kw):
        captured["phase_refine_cell"] = phases[0].refine_cell
        captured["initial_cells"] = initial_cells
        captured["recipe_labels"] = [s.label for s in recipe]
        return _stub_result(lam=0.4964005, zero=-0.015)  # runner が Lam を返しても既定は無視

    res = calibrate_instrument_from_standard(
        _xy_file(tmp_path), wavelength_init=0.4962537, standard="CeO2",
        work_dir=str(tmp_path / "wd"), runner=stub,
    )
    # 格子固定 (refine_cell=False) + 認証セルを initial_cells で設定
    assert captured["phase_refine_cell"] is False
    assert captured["initial_cells"]["CeO2"][0] == STANDARD_CELL_A["CeO2"]
    assert captured["initial_cells"]["CeO2"][3:] == (90.0, 90.0, 90.0)
    # 既定は波長を解放しない → 入力値をそのまま採る (縮退のため), ppm_shift=0
    assert res.wavelength == 0.4962537
    assert res.ppm_shift == 0.0
    assert res.zero == -0.015
    assert res.profile["V"] == 2.66 and "Lam" not in res.profile


def test_calibrate_refine_wavelength_uses_refined_lam(tmp_path):
    def stub(hists, phases, *, recipe=None, initial_cells=None, **kw):
        return _stub_result(lam=0.4964005, zero=-0.015)

    res = calibrate_instrument_from_standard(
        _xy_file(tmp_path), wavelength_init=0.4962537, standard="CeO2",
        work_dir=str(tmp_path / "wd"), refine_wavelength=True, runner=stub,
    )
    assert res.wavelength == 0.4964005  # refine_wavelength=True で精密化値を採用
    assert res.ppm_shift > 0


def test_calibrate_cell_a_override(tmp_path):
    captured = {}

    def stub(hists, phases, *, recipe=None, initial_cells=None, **kw):
        captured["a"] = initial_cells["CeO2"][0]
        return _stub_result(0.4964, -0.01)

    calibrate_instrument_from_standard(
        _xy_file(tmp_path), wavelength_init=0.4962537, standard="CeO2",
        cell_a=5.4110, work_dir=str(tmp_path / "wd"), runner=stub,
    )
    assert captured["a"] == 5.4110


def test_calibrate_unknown_standard_raises(tmp_path):
    with pytest.raises(KeyError):
        calibrate_instrument_from_standard(
            _xy_file(tmp_path), wavelength_init=0.5, standard="NaCl",
            work_dir=str(tmp_path / "wd"), runner=lambda *a, **k: _stub_result(0.5, 0.0),
        )
