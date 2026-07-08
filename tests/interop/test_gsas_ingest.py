"""interop 変換物の GSAS-II 取り込み確認 (T5, gated)。

変換した .xye+PXC / TOF FXYE+PNT を GSAS-II が実際に読み込め、X 軸 (2θ / TOF[μs]) が正しく復元される
ことを確認する。特に TOF FXYE の X スケール規約 (μs をそのまま採る) を実 GSAS-II で固定する。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.interop.instrument import write_gsas_instprm
from tsumugin.interop.rietan import convert_rietan_int
from tsumugin.interop.zrietveld import convert_igor_tof, parse_zdiffractometer

pytestmark = pytest.mark.gsas


_XRAY_DIFF = """[Beam type] X-Ray
[Measurement method] Synchrotron Radiation
[Diffracto meter parameter]
	[Wave length]
		[Value] 0.5
	[End]
	[Z]
		[Value] 0.0
		[ID] Vary
	[End]
[End]
"""

_TOF_DIFF = """[Beam type] Neutron
[Measurement method] Time Of Flight
[Intensity correction parameters]
	[Diffraction angle] 90
[End]
[Conversion parameters]
	[Value] -2.653194
[Conversion parameters]
	[Value] 10060.510395
[Conversion parameters]
	[Value] -1.125499
[End]
"""


def _make_int(path, tt, inten):
    lines = ["GENERAL", str(len(tt))]
    lines += [f"{x:.6f} {y:.6f}" for x, y in zip(tt, inten)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _make_igor(path, tofs, ys):
    lines = ["IGOR", "WAVES tof, yint, yerr, nc", "BEGIN"]
    lines += [f"  {t}  {y:.6f}  0.02  1" for t, y in zip(tofs, ys)]
    lines += ["END"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_gsas_ingests_xray_xye_preserves_two_theta(tmp_path):
    from GSASII import GSASIIscriptable as G2sc

    tt = np.round(np.arange(5.0, 40.0, 0.02), 3)
    inten = 100.0 + 10.0 * np.sin(tt)
    _make_int(tmp_path / "x.int", tt, inten)
    xye = convert_rietan_int(tmp_path / "x.int", tmp_path / "x.xye")
    zx = parse_zdiffractometer(_XRAY_DIFF)
    prm = write_gsas_instprm(zx, tmp_path / "x.instprm", wavelength=0.79958)

    gpx = G2sc.G2Project(newgpx=str(tmp_path / "x.gpx"))
    hist = gpx.add_powder_histogram(str(xye), str(prm), fmthint="xye")
    x = np.array(hist.getdata("X"))
    assert x.shape[0] == tt.shape[0]
    assert x.min() == pytest.approx(tt.min(), abs=1e-3)
    assert x.max() == pytest.approx(tt.max(), abs=1e-3)


def test_gsas_ingests_tof_fxye_x_is_microseconds(tmp_path):
    from GSASII import GSASIIscriptable as G2sc

    # TOF μs → 既知の difC=10060.51 で d は 0.5〜7 Å 帯へ。
    tofs = list(range(5200, 70000, 40))
    ys = [0.1 + 0.05 * (i % 7) for i in range(len(tofs))]
    _make_igor(tmp_path / "n.histogramIgor", tofs, ys)
    fxye = convert_igor_tof(tmp_path / "n.histogramIgor", tmp_path / "n.fxye")
    zn = parse_zdiffractometer(_TOF_DIFF)
    prm = write_gsas_instprm(zn, tmp_path / "n.instprm")

    gpx = G2sc.G2Project(newgpx=str(tmp_path / "n.gpx"))
    hist = gpx.add_powder_histogram(str(fxye), str(prm), fmthint="GSAS")
    x = np.array(hist.getdata("X"))
    # X は TOF[μs] としてそのまま読まれる (×100 されない)。
    assert x.min() == pytest.approx(min(tofs), abs=50.0)
    assert x.max() == pytest.approx(max(tofs), abs=50.0)
    # difC で d 変換すると中性子 d 帯 (0.5〜7 Å) に収まる。
    difc, zero = 10060.510395, -2.653194
    d_min = (x.min() - zero) / difc
    d_max = (x.max() - zero) / difc
    assert 0.4 < d_min < 0.7
    assert 6.0 < d_max < 7.5
