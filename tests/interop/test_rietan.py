"""interop.rietan (RIETAN-FP .int パーサ + xye 変換) の決定論テスト。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.interop.rietan import convert_rietan_int, parse_rietan_int
from tsumugin.reference.io import load_pattern

_SAMPLE_INT = """GENERAL
5
0.800000 8838.000000
0.806000 8841.000000
0.812000 8981.000000
0.818000 9108.000000
0.824000 9013.000000
"""


def test_parse_rietan_int_shapes_and_axis():
    tt, inten = parse_rietan_int(_SAMPLE_INT)
    assert tt.shape == (5,)
    assert inten.shape == (5,)
    assert tt[0] == pytest.approx(0.8)
    assert tt[-1] == pytest.approx(0.824)
    assert inten[0] == pytest.approx(8838.0)


def test_parse_rietan_int_truncates_to_declared_count():
    # 宣言 3 点 + 余分 2 点 → 先頭 3 点のみ。
    text = "GENERAL\n3\n1.0 10\n1.1 20\n1.2 30\n1.3 40\n1.4 50\n"
    tt, inten = parse_rietan_int(text)
    assert tt.shape == (3,)
    assert inten[-1] == pytest.approx(30.0)


def test_parse_rietan_int_missing_header_raises():
    with pytest.raises(ValueError, match="GENERAL"):
        parse_rietan_int("2\n1.0 10\n1.1 20\n")


def test_parse_rietan_int_insufficient_points_raises():
    with pytest.raises(ValueError, match="不足"):
        parse_rietan_int("GENERAL\n5\n1.0 10\n1.1 20\n")


def test_convert_rietan_int_writes_xye_with_poisson_esd(tmp_path):
    src = tmp_path / "in.int"
    src.write_text(_SAMPLE_INT, encoding="utf-8")
    out = convert_rietan_int(src, tmp_path / "out.xye")
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5
    x0, y0, e0 = (float(v) for v in lines[0].split())
    assert x0 == pytest.approx(0.8)
    assert y0 == pytest.approx(8838.0)
    assert e0 == pytest.approx(math.sqrt(8838.0), rel=1e-4)


def test_convert_rietan_esd_floor_for_nonpositive_intensity(tmp_path):
    src = tmp_path / "in.int"
    src.write_text("GENERAL\n1\n1.0 0.0\n", encoding="utf-8")
    out = convert_rietan_int(src, tmp_path / "out.xye")
    _x, _y, e = (float(v) for v in out.read_text().strip().split())
    assert e == pytest.approx(1.0)  # sqrt(max(0,1)) = 1


def test_load_pattern_dispatches_int(tmp_path):
    src = tmp_path / "d.int"
    src.write_text(_SAMPLE_INT, encoding="utf-8")
    tt, inten = load_pattern(src, "INT")
    assert isinstance(tt, np.ndarray)
    assert tt.shape == (5,)
