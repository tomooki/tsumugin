"""FrameSpec.excluded_regions フィールド (Issue #53) のテスト。"""

from __future__ import annotations

from tsumugin.insitu.model import FrameSpec


def test_framespec_excluded_regions_default_empty():
    assert FrameSpec(data_path="x.xrdml").excluded_regions == ()


def test_framespec_dict_roundtrip_with_excluded_regions():
    fs = FrameSpec(
        data_path="x.xrdml",
        axis_value=300.0,
        two_theta_limits=(10.0, 80.0),
        excluded_regions=((7.9, 8.3), (30.0, 31.0)),
        label="f0",
    )
    d = fs.to_dict()
    assert d["excluded_regions"] == [[7.9, 8.3], [30.0, 31.0]]
    fs2 = FrameSpec.from_dict(d)
    assert fs2 == fs


def test_framespec_dict_roundtrip_without_excluded_regions():
    fs = FrameSpec(data_path="x.fxye", data_format="FXYE")
    d = fs.to_dict()
    assert d["excluded_regions"] == []
    assert FrameSpec.from_dict(d) == fs
