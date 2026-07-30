"""M12 T4: 装置パラメータ + 観測データの TOPAS 向け変換 (純関数)。

GSAS の ``.instprm`` (新形式 ``Key:value``) と ``.PRM`` (旧形式 固定桁) を読み分け、
観測データは `reference.io.load_pattern` 経由で ``.xye`` へ落として入力形式差を TOPAS へ
持ち込まない。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation
from tsumugin.topas.instrument import (
    histogram_to_topas,
    read_instrument,
    tchz_line,
    write_xye,
)

_INSTPRM_XRAY = (
    "#GSAS-II instrument parameter file\n"
    "Type:PXC\nBank:1.0\nLam1:1.540500\nLam2:1.544300\nI(L2)/I(L1):0.5\n"
    "Zero:0.0125\nU:2.0\nV:-2.0\nW:5.0\nX:0.0\nY:0.5\n"
)
_INSTPRM_TOF = (
    "#GSAS-II instrument parameter file\n"
    "Type:PNT\ndifC:22600.25\ndifA:-1.5\nZero:-8.5\nsig-1:-167.4\n"
)
_PRM_XRAY = (
    "            123456789012345678901234567890\n"
    "INS   BANK      1\n"
    "INS   HTYPE   PXCR\n"
    "INS  1 ICONS  1.540500  1.544300       0.0         0       0.7    0       0.5\n"
)
_PRM_NEUTRON = (
    "INS   BANK      1\n"
    "INS   HTYPE   PNCR\n"
    "INS  1 ICONS  1.909000  0.000000       0.0         0       0.0    0       0.0\n"
)


# ---------------- .instprm ----------------


def test_instprm_xray_wavelengths_and_zero(tmp_path):
    path = tmp_path / "x.instprm"
    path.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.lam1 == pytest.approx(1.5405)
    assert spec.lam2 == pytest.approx(1.5443)
    assert spec.zero == pytest.approx(0.0125)
    assert not spec.is_tof and not spec.is_neutron


def test_instprm_keeps_gsas_profile_for_optional_seeding(tmp_path):
    """**既定では種付けしない** (係数スケール等価が未検証) が、値自体は保持する。"""
    path = tmp_path / "x.instprm"
    path.write_text(_INSTPRM_XRAY, encoding="utf-8")
    assert read_instrument(path).profile == {"U": 2.0, "V": -2.0, "W": 5.0, "X": 0.0, "Y": 0.5}


def test_instprm_tof_maps_difc_difa_zero(tmp_path):
    """TOF は GSAS の difC/difA/Zero と TOPAS の TOF_x_axis_calibration が直写像。"""
    path = tmp_path / "t.instprm"
    path.write_text(_INSTPRM_TOF, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.is_tof and spec.is_neutron
    assert (spec.difc, spec.difa, spec.tof_zero) == (
        pytest.approx(22600.25), pytest.approx(-1.5), pytest.approx(-8.5)
    )
    assert spec.zero == 0.0  # TOF では 2θ ゼロ点ではない


# ---------------- 旧 .PRM ----------------


def test_prm_reads_icons_wavelengths(tmp_path):
    path = tmp_path / "i.PRM"
    path.write_text(_PRM_XRAY, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.lam1 == pytest.approx(1.5405)
    assert spec.lam2 == pytest.approx(1.5443)
    assert not spec.is_neutron


def test_prm_zero_second_wavelength_means_monochromatic(tmp_path):
    """λ2 = 0 は「Kα2 なし」であって「波長 0」ではない。"""
    path = tmp_path / "n.PRM"
    path.write_text(_PRM_NEUTRON, encoding="utf-8")
    spec = read_instrument(path)
    assert spec.lam1 == pytest.approx(1.909)
    assert spec.lam2 is None
    assert spec.is_neutron


# ---------------- .xye 書き出し ----------------


def test_write_xye_is_three_columns_with_counting_sigma(tmp_path):
    out = write_xye(tmp_path / "d.xye", np.array([10.0, 10.02]), np.array([100.0, 0.0]))
    rows = [line.split() for line in out.read_text().splitlines()]
    assert [len(r) for r in rows] == [3, 3]
    assert float(rows[0][2]) == pytest.approx(10.0)  # √100
    assert float(rows[1][2]) == pytest.approx(1.0)  # √max(y,1) — 0 計数で σ=0 にしない


def test_write_xye_is_deterministic(tmp_path):
    x, y = np.array([10.0, 20.0]), np.array([5.0, 7.0])
    a = write_xye(tmp_path / "a.xye", x, y).read_text()
    b = write_xye(tmp_path / "b.xye", x, y).read_text()
    assert a == b


# ---------------- HistogramSpec → TopasHistogram ----------------


def _xye_source(tmp_path):
    src = tmp_path / "src.xye"
    src.write_text("\n".join(f"{10 + 0.02 * i:.4f} {100 + i} 1.0" for i in range(50)), "utf-8")
    return src


def test_histogram_conversion_writes_data_and_builds_emission(tmp_path):
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    hist = histogram_to_topas(spec, workdir=tmp_path, index=0)
    assert hist.data_path == "hist0.xye"
    assert (tmp_path / "hist0.xye").is_file()
    joined = "\n".join(hist.preamble)
    assert "lam" in joined and "1.5405" in joined
    assert "1.5443" in joined  # Kα2 も出す
    assert "LP_Factor" in joined


def test_missing_wavelength_raises_rather_than_defaulting_to_cu(tmp_path):
    """**Cu Kα で埋めない** — 誤った波長はピーク位置をずらし格子がそれを吸収する。"""
    prm = tmp_path / "bad.instprm"
    prm.write_text("Type:PXC\nBank:1.0\n", encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    with pytest.raises(ValueError, match="波長"):
        histogram_to_topas(spec, workdir=tmp_path)


def test_neutron_omits_the_xray_lp_factor(tmp_path):
    prm = tmp_path / "n.PRM"
    prm.write_text(_PRM_NEUTRON, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    hist = histogram_to_topas(spec, workdir=tmp_path)
    assert not any("LP_Factor" in line for line in hist.preamble)
    assert hist.is_neutron


def test_range_and_exclusions_are_carried_through(tmp_path):
    prm = tmp_path / "i.instprm"
    prm.write_text(_INSTPRM_XRAY, encoding="utf-8")
    spec = HistogramSpec(
        data_path=str(_xye_source(tmp_path)), instrument_path=str(prm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
        two_theta_limits=(10.2, 10.8), excluded_regions=((10.4, 10.5),), weight=2.0,
    )
    hist = histogram_to_topas(spec, workdir=tmp_path)
    assert hist.two_theta_limits == (10.2, 10.8)
    assert hist.excluded_regions == ((10.4, 10.5),)
    assert hist.weight == 2.0


# ---------------- TCHZ 行 ----------------


def test_tchz_defaults_are_frozen():
    """解放は段階フラグの責務。初期状態では全部 `!` 付き。"""
    line = tchz_line(0)
    assert line.startswith("TCHZ_Peak_Type(")
    assert line.count("!pk") == 6


def test_tchz_names_include_the_phase_so_they_do_not_collide():
    """**TOPAS のパラメータ名は大域** — 多相で同名を複数の str に宣言すると衝突する。"""
    a = tchz_line(0, phase_key="alpha")
    b = tchz_line(0, phase_key="beta")
    assert "pku0_alpha" in a and "pku0_beta" in b
    assert a != b


def test_tchz_without_phase_key_keeps_the_plain_name():
    assert "!pku0," in tchz_line(0)


def test_tchz_seeds_from_gsas_keys_when_asked():
    line = tchz_line(0, {"W": 0.004, "Y": 0.06})
    assert "0.004" in line and "0.06" in line
