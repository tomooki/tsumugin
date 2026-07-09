"""InstrumentProfile 型 + HistogramSpec.instrument_profile フィールドのテスト (TASK-0001)。"""

from __future__ import annotations

import math

from tsumugin.autorietveld.model import (
    Geometry,
    HistogramSpec,
    InstrumentProfile,
    Radiation,
)


def _hist(**kw):
    return HistogramSpec(
        "d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER, data_format="XYE", **kw
    )


def test_instrument_profile_fields():
    ip = InstrumentProfile(values={"U": 2.7, "V": -0.2, "W": 1.2, "X": 0.4, "Y": -5.2, "SH/L": 0.002},
                           source_rwp=9.5, wavelength=0.79958)
    assert ip.values["U"] == 2.7
    assert ip.source_rwp == 9.5
    assert ip.wavelength == 0.79958


def test_instrument_profile_defaults():
    ip = InstrumentProfile(values={"W": 1.0})
    assert math.isnan(ip.source_rwp)
    assert ip.wavelength is None


def test_histogram_spec_instrument_profile_default_none():
    assert _hist().instrument_profile is None


def test_histogram_spec_with_instrument_profile():
    ip = InstrumentProfile(values={"U": 1.0, "V": -1.0, "W": 2.0})
    h = _hist(instrument_profile=ip)
    assert h.instrument_profile is ip


def test_to_dict_from_dict_roundtrip_with_profile():
    ip = InstrumentProfile(values={"U": 2.0, "W": 1.5}, source_rwp=9.6, wavelength=0.8)
    h = _hist(instrument_profile=ip)
    d = h.to_dict()
    h2 = HistogramSpec.from_dict(d)
    assert h2.instrument_profile is not None
    assert dict(h2.instrument_profile.values) == {"U": 2.0, "W": 1.5}
    assert h2.instrument_profile.source_rwp == 9.6
    assert h2.instrument_profile.wavelength == 0.8


def test_to_dict_from_dict_roundtrip_without_profile():
    h = _hist()
    h2 = HistogramSpec.from_dict(h.to_dict())
    assert h2.instrument_profile is None
