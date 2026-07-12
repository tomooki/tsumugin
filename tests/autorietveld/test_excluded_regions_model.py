"""HistogramSpec.excluded_regions フィールド (Issue #53) のテスト。"""

from __future__ import annotations

from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation


def _hist(**kw):
    return HistogramSpec(
        "d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER, data_format="XYE", **kw
    )


def test_excluded_regions_default_empty():
    assert _hist().excluded_regions == ()


def test_excluded_regions_set():
    h = _hist(excluded_regions=((7.9, 8.3), (12.0, 12.5)))
    assert h.excluded_regions == ((7.9, 8.3), (12.0, 12.5))


def test_to_dict_from_dict_roundtrip_with_excluded_regions():
    h = _hist(two_theta_limits=(2.4, 18.0), excluded_regions=((7.9, 8.3), (12.0, 12.5)))
    d = h.to_dict()
    assert d["excluded_regions"] == [[7.9, 8.3], [12.0, 12.5]]
    h2 = HistogramSpec.from_dict(d)
    assert h2.excluded_regions == ((7.9, 8.3), (12.0, 12.5))
    assert h2.two_theta_limits == (2.4, 18.0)


def test_to_dict_from_dict_roundtrip_without_excluded_regions():
    h = _hist()
    d = h.to_dict()
    assert d["excluded_regions"] == []
    h2 = HistogramSpec.from_dict(d)
    assert h2.excluded_regions == ()
