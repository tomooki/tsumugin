"""HistogramSpec.excluded_regions (Issue #53) の GSAS-II 実データ end-to-end 検証。

GSAS-II 必須 (@pytest.mark.gsas)。実測 KMnFeCN (scratchpad) データ未取得時は自動 skip。
gpx.data['Limits'] が [(orig_min,orig_max), [used_lo,used_hi], *excluded_pairs] の構造で、
excluded_regions で与えた区間が追加の除外ペアとして append されていることを確認する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

pytestmark = pytest.mark.gsas

_SCRATCH = Path(
    r"C:\Users\tomoo\AppData\Local\Temp\claude\C--Users-tomoo-Documents-programming-tsumugin"
    r"\42d5114f-8527-4de8-a07f-d7e22f4e413a\scratchpad\kmnfe"
)
_DATA_PATH = _SCRATCH / "frames_xye" / "frame_0000.xye"
_INSTR_PATH = _SCRATCH / "staged" / "kmnfe.instprm"
_CIF_PATH = _SCRATCH / "manual" / "0001" / "0001.cif"


def _data_present() -> bool:
    return _DATA_PATH.exists() and _INSTR_PATH.exists() and _CIF_PATH.exists()


@pytest.mark.skipif(not _data_present(), reason="scratchpad KMnFeCN データ未取得")
def test_excluded_region_appended_to_gsas_limits(tmp_path):
    from tsumugin.autorietveld.engine import _g2sc, run_auto_rietveld

    hist = HistogramSpec(
        data_path=str(_DATA_PATH),
        instrument_path=str(_INSTR_PATH),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=(2.4, 18.0),
        excluded_regions=((7.9, 8.3),),
    )
    phase = PhaseSpec(structure_path=str(_CIF_PATH), phase_name="kmnfe", format_hint="CIF")

    keep_gpx = str(tmp_path / "excluded_regions.gpx")
    result = run_auto_rietveld([hist], [phase], max_cyc=1, keep_gpx=keep_gpx)

    assert result.gpx_path == keep_gpx

    project = _g2sc().G2Project(keep_gpx)
    g2hist = project.histograms()[0]
    limits = g2hist.data["Limits"]

    # index0=原範囲(タプル), index1=使用域, index2+=除外ペア
    assert len(limits) >= 3, f"excluded region が append されていない: {limits}"
    excluded_pairs = [tuple(pair) for pair in limits[2:]]
    assert any(
        abs(lo - 7.9) < 1e-6 and abs(hi - 8.3) < 1e-6 for lo, hi in excluded_pairs
    ), f"[7.9, 8.3] が Limits に見つからない: {excluded_pairs}"
