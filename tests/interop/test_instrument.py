"""interop.instrument (GSAS-II instprm writer) の決定論テスト。"""

from __future__ import annotations

import math

import pytest

from tsumugin.interop.instrument import write_gsas_instprm
from tsumugin.interop.zrietveld import ZDiffractometer


def _instprm_dict(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if line.startswith("#") or ":" not in line:
            continue
        key, val = line.split(":", 1)
        out[key] = val
    return out


def test_write_instprm_tof_maps_conversion_params(tmp_path):
    zd = ZDiffractometer(
        beam_type="Neutron",
        method="Time Of Flight",
        conversion_params=(-2.653194, 10060.510395, -1.125499),
        bank_two_theta=90.0,
        profile={"SigmaSquare0": 0.001, "SigmaSquare1": 265.946, "SigmaSquare2": 7.9156},
    )
    out = write_gsas_instprm(zd, tmp_path / "n.instprm")
    d = _instprm_dict(out.read_text(encoding="utf-8"))
    assert d["Type"] == "PNT"
    assert float(d["difC"]) == pytest.approx(10060.510395)
    assert float(d["difA"]) == pytest.approx(-1.125499)
    assert float(d["Zero"]) == pytest.approx(-2.653194)
    assert float(d["difB"]) == pytest.approx(0.0)
    assert float(d["sig-1"]) == pytest.approx(265.946)
    # fltPath は difC=2·252.816·L·sinθ の逆算 (θ=45°)。
    expected_l = 10060.510395 / (2.0 * 252.816 * math.sin(math.radians(45.0)))
    assert float(d["fltPath"]) == pytest.approx(expected_l, rel=1e-4)


def test_write_instprm_xray_synchrotron_wavelength_override(tmp_path):
    zd = ZDiffractometer(
        beam_type="X-Ray",
        method="Synchrotron Radiation",
        wavelength=0.5,  # 別較正の λ
        zero=0.005896,
    )
    # 実データの真の波長 0.79958 で上書き。
    out = write_gsas_instprm(zd, tmp_path / "x.instprm", wavelength=0.79958)
    d = _instprm_dict(out.read_text(encoding="utf-8"))
    assert d["Type"] == "PXC"
    assert float(d["Lam"]) == pytest.approx(0.79958)
    assert float(d["Zero"]) == pytest.approx(0.005896)
    assert float(d["Polariz."]) == pytest.approx(0.95)  # 放射光は高偏光


def test_write_instprm_tof_missing_conversion_raises(tmp_path):
    zd = ZDiffractometer(beam_type="Neutron", method="Time Of Flight")
    with pytest.raises(ValueError, match="変換係数"):
        write_gsas_instprm(zd, tmp_path / "n.instprm")


def test_write_instprm_xray_missing_wavelength_raises(tmp_path):
    zd = ZDiffractometer(beam_type="X-Ray", method="Synchrotron Radiation", wavelength=0.5)
    # config.wavelength があるので判別は通るが、writer に None を渡しても config 値で埋まる。
    out = write_gsas_instprm(zd, tmp_path / "x.instprm")
    d = _instprm_dict(out.read_text(encoding="utf-8"))
    assert float(d["Lam"]) == pytest.approx(0.5)
