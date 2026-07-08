"""interop.prepare_histograms (SXRD+ND ヒストグラム仕様生成) の決定論テスト。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import Geometry, Radiation
from tsumugin.interop import prepare_histograms

_INT = "GENERAL\n3\n5.0 100\n5.006 110\n5.012 105\n"
_IGOR = "IGOR\nWAVES tof, yint, yerr, nc\nBEGIN\n  5200 0.1 0.02 1\n  5240 0.12 0.02 1\nEND\n"
_XDIFF = """[Beam type] X-Ray
[Measurement method] Synchrotron Radiation
[Diffracto meter parameter]
	[Wave length]
		[Value] 0.5
	[End]
[End]
"""
_NDIFF = """[Beam type] Neutron
[Measurement method] Time Of Flight
[Intensity correction parameters]
	[Diffraction angle] 90
[End]
[Global fitting range]
	[Peak position]
		[Min] 5142
		[Max] 70900
	[End]
[End]
[Conversion parameters]
	[Value] -2.653194
[Conversion parameters]
	[Value] 10060.510395
[Conversion parameters]
	[Value] -1.125499
[End]
"""


def _write(tmp_path):
    (tmp_path / "x.int").write_text(_INT, encoding="utf-8")
    (tmp_path / "x.zDiff").write_text(_XDIFF, encoding="utf-8")
    (tmp_path / "n.histogramIgor").write_text(_IGOR, encoding="utf-8")
    (tmp_path / "n.zDiff").write_text(_NDIFF, encoding="utf-8")


def test_prepare_histograms_builds_xray_and_nd_specs(tmp_path):
    _write(tmp_path)
    xray, nd = prepare_histograms(
        xray_int=tmp_path / "x.int",
        xray_diffractometer=tmp_path / "x.zDiff",
        nd_igor=tmp_path / "n.histogramIgor",
        nd_diffractometer=tmp_path / "n.zDiff",
        out_dir=tmp_path / "prep",
    )
    assert xray.radiation is Radiation.XRAY_SYNCHROTRON
    assert xray.geometry is Geometry.DEBYE_SCHERRER
    assert xray.data_format == "XYE"
    assert xray.two_theta_limits == (5.0, 78.0)

    assert nd.radiation is Radiation.NEUTRON_TOF
    assert nd.data_format == "GSAS"
    # ND の精密化範囲は回折計の fitting_range を採る。
    assert nd.two_theta_limits == pytest.approx((5142.0, 70900.0))


def test_prepare_histograms_writes_instprm_with_overridden_wavelength(tmp_path):
    _write(tmp_path)
    xray, nd = prepare_histograms(
        xray_int=tmp_path / "x.int",
        xray_diffractometer=tmp_path / "x.zDiff",
        nd_igor=tmp_path / "n.histogramIgor",
        nd_diffractometer=tmp_path / "n.zDiff",
        out_dir=tmp_path / "prep",
        xray_wavelength=0.79958,
    )
    x_prm = open(xray.instrument_path, encoding="utf-8").read()
    assert "Type:PXC" in x_prm
    assert "Lam:0.799580" in x_prm  # 0.5 でなく上書き波長
    n_prm = open(nd.instrument_path, encoding="utf-8").read()
    assert "Type:PNT" in n_prm
    assert "difC:10060.510395" in n_prm
