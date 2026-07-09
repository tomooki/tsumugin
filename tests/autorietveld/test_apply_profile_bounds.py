"""_apply_profile_bounds (装置パラメータ parmMin/parmMax 登録, TASK-0002) のテスト。

GSAS 非依存モック (set_Controls 記録) で変数名 `:{i}:{key}` と片側拘束を検証。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _apply_profile_bounds
from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation


def _hist(bounds=None):
    return HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
                         profile_bounds=bounds)


class _MockGpx:
    def __init__(self):
        self.calls = []

    def set_Controls(self, which, value, variable=None):
        self.calls.append((which, value, variable))


def test_registers_min_and_max():
    g = _MockGpx()
    _apply_profile_bounds(g, [_hist({"X": (0.0, None), "Y": (0.0, 10.0)})])
    assert ("parmMin", 0.0, ":0:X") in g.calls
    assert ("parmMin", 0.0, ":0:Y") in g.calls
    assert ("parmMax", 10.0, ":0:Y") in g.calls
    # X は max 無し → parmMax 呼ばない
    assert not any(c[0] == "parmMax" and c[2] == ":0:X" for c in g.calls)


def test_none_side_skipped():
    g = _MockGpx()
    _apply_profile_bounds(g, [_hist({"W": (None, 5.0)})])
    assert ("parmMax", 5.0, ":0:W") in g.calls
    assert not any(c[0] == "parmMin" for c in g.calls)


def test_per_hist_variable_index():
    g = _MockGpx()
    _apply_profile_bounds(g, [_hist(None), _hist({"U": (0.0, None)})])
    # 2 本目 (index 1) の変数名
    assert ("parmMin", 0.0, ":1:U") in g.calls


def test_no_bounds_no_calls():
    g = _MockGpx()
    _apply_profile_bounds(g, [_hist(None), _hist(None)])
    assert g.calls == []


def test_set_controls_failure_swallowed():
    class _Boom:
        def set_Controls(self, *a, **k):
            raise RuntimeError("old GSAS")

    # 例外は握って継続 (REQ-403)
    _apply_profile_bounds(_Boom(), [_hist({"X": (0.0, None)})])
