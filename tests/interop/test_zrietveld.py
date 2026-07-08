"""interop.zrietveld (Igor TOF + zDiffractometer パーサ) の決定論テスト。"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.interop.zrietveld import (
    convert_igor_tof,
    parse_igor_tof,
    parse_zdiffractometer,
)
from tsumugin.reference.io import load_pattern

_SAMPLE_IGOR = """IGOR
WAVES tof, yint, yerr, nc
BEGIN
  1501       0.186482       0.028728    1
  1503       0.201653       0.028602    1
  1505       0.166359       0.028582    1
  72982      0.233937       0.062053   14
END
"""

_SAMPLE_TOF_DIFF = """[File format version] 1
[Diffracto meter format version] 2

[Beam type] Neutron
[Measurement method] Time Of Flight

[Global fitting range]
	[Peak position]
		[Min] 5142
		[Max] 70900
	[End]
[End]

[Intensity correction parameters]
	[Diffraction angle] 90
[End]

[Conversion parameters]
	[Value] -2.653194
	[ID] Fix
[Conversion parameters]
	[Value] 10060.510395
	[ID] Fix
[Conversion parameters]
	[Value] -1.125499
	[ID] Fix
[End]

[Default profile model function identifier] Type0m

[Profile function]
	[Identifier] Type0m
	[SigmaSquare0]
		[Value] 0.001
		[ID] Phase
	[End]
	[SigmaSquare1]
		[Value] 265.946124
		[ID] Phase
	[End]
	[SigmaSquare2]
		[Value] 7.915588
		[ID] Phase
	[End]
	[h] 1
	[k] 1
	[l] 1
[End]

[Profile function initial value]
	[Identifier] Type2
	[Sigma01]
		[Value] 999.0
		[ID] Phase
	[End]
[End]
"""

_SAMPLE_XRAY_DIFF = """[File format version] 1
[Diffracto meter format version] 1

[Beam type] X-Ray
[Measurement method] Synchrotron Radiation

[Global fitting range]
	[Peak position]
		[Min] 0.1
		[Max] 78.14
	[End]
[End]

[Diffracto meter parameter]
	[Wave length]
		[Value] 0.5
	[End]
	[Z]
		[Value] 0.005896
		[ID] Vary
	[End]
[End]

[Background parameters]
	[Value] 942.0
	[ID] Vary
[Background parameters]
	[Value] -407.7
	[ID] Vary
[End]
"""


def test_parse_igor_tof_columns_and_variable_step():
    tof, yint, yerr = parse_igor_tof(_SAMPLE_IGOR)
    assert tof.shape == (4,)
    assert tof[0] == pytest.approx(1501.0)
    assert tof[-1] == pytest.approx(72982.0)
    assert yint[0] == pytest.approx(0.186482)
    assert yerr[0] == pytest.approx(0.028728)


def test_parse_igor_tof_missing_begin_raises():
    with pytest.raises(ValueError, match="BEGIN"):
        parse_igor_tof("IGOR\nWAVES tof\n1501 0.1 0.02 1\n")


def test_convert_igor_tof_writes_fxye_x_times_100(tmp_path):
    src = tmp_path / "d.histogramIgor"
    src.write_text(_SAMPLE_IGOR, encoding="utf-8")
    out = convert_igor_tof(src, tmp_path / "out.fxye")
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[1].startswith("BANK 1 4 4 FXYE")
    # X 列は TOF[μs] そのまま。Y/ESD はビン幅 (前方差分 step) を掛ける (GSAS の /step で真強度へ戻す)。
    step0 = 1503.0 - 1501.0  # = 2
    x0, y0, e0 = (float(v) for v in lines[2].split())
    assert x0 == pytest.approx(1501.0)
    assert y0 == pytest.approx(0.186482 * step0)
    assert e0 == pytest.approx(0.028728 * step0)


def test_parse_zdiffractometer_tof_conversion_and_range():
    zd = parse_zdiffractometer(_SAMPLE_TOF_DIFF)
    assert zd.is_tof
    assert zd.is_neutron
    assert zd.conversion_params == pytest.approx((-2.653194, 10060.510395, -1.125499))
    assert zd.zero == pytest.approx(-2.653194)  # TOF は c0 をゼロに採る
    assert zd.fitting_range == pytest.approx((5142.0, 70900.0))
    assert zd.bank_two_theta == pytest.approx(90.0)
    # 既定プロファイル (Type0m) の SigmaSquare のみ採り、初期値テンプレートは混ぜない。
    assert zd.profile["SigmaSquare1"] == pytest.approx(265.946124)
    assert "Sigma01" not in zd.profile


def test_parse_zdiffractometer_xray_wavelength_and_background():
    zd = parse_zdiffractometer(_SAMPLE_XRAY_DIFF)
    assert not zd.is_tof
    assert not zd.is_neutron
    assert zd.wavelength == pytest.approx(0.5)
    assert zd.zero == pytest.approx(0.005896)
    assert zd.background == pytest.approx((942.0, -407.7))


def test_parse_zdiffractometer_missing_beamtype_raises():
    with pytest.raises(ValueError, match="Beam type"):
        parse_zdiffractometer("[File format version] 1\n")


def test_load_pattern_dispatches_igor(tmp_path):
    src = tmp_path / "d.histogramIgor"
    src.write_text(_SAMPLE_IGOR, encoding="utf-8")
    tof, inten = load_pattern(src, "IGOR")
    assert isinstance(tof, np.ndarray)
    assert tof.shape == (4,)
    assert tof[0] == pytest.approx(1501.0)
