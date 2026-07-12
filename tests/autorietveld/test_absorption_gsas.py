"""Issue #54: 固定吸収体レイヤー補正の GSAS-II 実データ end-to-end テスト。

KMnFe frame0 (放射光 X 線) + AbsorberLayer を与えて run_auto_rietveld を実行し、保存した
.gpx を再オープンして、読み込まれた Yobs が高角ほど角度依存補正でブーストされていることを
確認する。GSAS-II 必須 (@pytest.mark.gsas)。データ未取得時は自動 skip。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gsas

_SCRATCH = Path(
    r"C:\Users\tomoo\AppData\Local\Temp\claude\C--Users-tomoo-Documents-programming-tsumugin"
    r"\42d5114f-8527-4de8-a07f-d7e22f4e413a\scratchpad"
)
_DATA_XYE = _SCRATCH / "kmnfe" / "frames_xye" / "frame_0000.xye"
_INSTPRM = _SCRATCH / "kmnfe" / "staged" / "kmnfe.instprm"
_CIF = _SCRATCH / "kmnfe" / "manual" / "0001" / "0001.cif"

_MU_CM = 0.394
_THICKNESS_CM = 0.2


def _data_present() -> bool:
    return _DATA_XYE.exists() and _INSTPRM.exists() and _CIF.exists()


@pytest.mark.skipif(not _data_present(), reason="Issue #54 KMnFe frame0 データ未取得")
def test_absorber_layer_boosts_high_angle_yobs(tmp_path):
    from tsumugin.autorietveld import (
        AbsorberLayer,
        Geometry,
        HistogramSpec,
        PhaseSpec,
        Radiation,
    )
    from tsumugin.autorietveld.engine import run_auto_rietveld

    raw = np.loadtxt(_DATA_XYE)
    raw_x, raw_y = raw[:, 0], raw[:, 1]

    def raw_y_near(target_two_theta: float) -> tuple[float, float]:
        idx = int(np.argmin(np.abs(raw_x - target_two_theta)))
        return float(raw_x[idx]), float(raw_y[idx])

    hist = HistogramSpec(
        data_path=str(_DATA_XYE),
        instrument_path=str(_INSTPRM),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=(2.4, 18.0),
        absorber_layers=(AbsorberLayer(thickness_cm=_THICKNESS_CM, mu_cm=_MU_CM),),
    )
    phase = PhaseSpec(structure_path=str(_CIF), phase_name="kmnfe", format_hint="CIF")

    gpx_path = tmp_path / "absorption_t.gpx"
    run_auto_rietveld([hist], [phase], keep_gpx=str(gpx_path), max_cyc=1)

    from GSASII import GSASIIscriptable as G2sc

    gpx = G2sc.G2Project(gpxfile=str(gpx_path))
    g2hist = gpx.histograms()[0]
    d = g2hist.data["data"][1]
    loaded_x = np.asarray(d[0])
    loaded_y = np.asarray(d[1])

    def loaded_y_near(target_two_theta: float) -> tuple[float, float]:
        idx = int(np.argmin(np.abs(loaded_x - target_two_theta)))
        return float(loaded_x[idx]), float(loaded_y[idx])

    # 高角 (~17 deg): 補正でブースト (ratio ≈ exp(mu*t*(1/cos(17°)-1)) ≈ 1.0036)
    hi_x_raw, hi_y_raw = raw_y_near(17.0)
    hi_x_loaded, hi_y_loaded = loaded_y_near(17.0)
    assert hi_x_loaded == pytest.approx(hi_x_raw, abs=0.02)
    hi_ratio = hi_y_loaded / hi_y_raw
    expected_hi = math.exp(_MU_CM * _THICKNESS_CM * (1.0 / math.cos(math.radians(hi_x_loaded)) - 1.0))
    assert hi_ratio > 1.0, f"高角 Yobs がブーストされていない: ratio={hi_ratio}"
    assert hi_ratio == pytest.approx(expected_hi, rel=0.05)

    # 低角 (~3 deg): ほぼ無補正 (ratio ≈ 1)
    lo_x_raw, lo_y_raw = raw_y_near(3.0)
    lo_x_loaded, lo_y_loaded = loaded_y_near(3.0)
    assert lo_x_loaded == pytest.approx(lo_x_raw, abs=0.02)
    lo_ratio = lo_y_loaded / lo_y_raw
    assert lo_ratio == pytest.approx(1.0, abs=0.0015)
