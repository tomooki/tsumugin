"""HistogramSpec.profile_bounds フィールド (TASK-0001) のテスト。"""

from __future__ import annotations

from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation


def _hist(**kw):
    return HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE", **kw)


def test_profile_bounds_default_none():
    assert _hist().instrument_profile is None
    assert _hist().profile_bounds is None


def test_profile_bounds_set():
    b = {"U": (0.0, None), "X": (0.0, None), "Y": (0.0, 10.0)}
    h = _hist(profile_bounds=b)
    assert h.profile_bounds["X"] == (0.0, None)
    assert h.profile_bounds["Y"] == (0.0, 10.0)


def test_to_dict_from_dict_roundtrip_with_bounds():
    b = {"U": (0.0, None), "W": (0.0, None), "Y": (None, 5.0)}
    h = _hist(profile_bounds=b)
    h2 = HistogramSpec.from_dict(h.to_dict())
    assert h2.profile_bounds == {"U": (0.0, None), "W": (0.0, None), "Y": (None, 5.0)}


def test_to_dict_from_dict_roundtrip_without_bounds():
    h2 = HistogramSpec.from_dict(_hist().to_dict())
    assert h2.profile_bounds is None
