"""_profile_ranges / _profiles_physical (engine アダプタ) の決定論テスト。

GSAS 非依存モック (getdata + .data) で検証。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _profile_ranges, _profiles_physical
from tsumugin.autorietveld.model import Radiation


class _MockHist:
    def __init__(self, xs, inst=None, x_raises=False):
        self._xs = xs
        self._x_raises = x_raises
        self.data = {"Instrument Parameters": (inst or {}, {})}

    def getdata(self, key):
        if self._x_raises:
            raise RuntimeError("getdata failed")
        if key == "x":
            return self._xs
        raise KeyError(key)


def _prof_cw():
    return {"U": (2.0, True), "V": (-2.0, True), "W": (5.0, True),
            "SH/L": (0.002, False)}


# --- _profile_ranges ---

def test_cw_range_is_two_theta_minmax():
    h = _MockHist([10.0, 55.0, 120.0], inst={"U": [2, 2, True]})
    prof = ({"U": (2.0, True)},)
    rng = _profile_ranges([h], [Radiation.XRAY_SYNCHROTRON], prof)
    assert rng == ((10.0, 120.0),)


def test_tof_range_converts_to_d():
    # x は μs。d=(t-Zero)/difC。difC=7476, Zero=0 → (1000/7476, 30000/7476)
    h = _MockHist([1000.0, 30000.0])
    prof = ({"difC": (7476.0, False), "Zero": (0.0, False)},)
    rng = _profile_ranges([h], [Radiation.NEUTRON_TOF], prof)
    (lo, hi), = rng
    assert abs(lo - 1000.0 / 7476.0) < 1e-9
    assert abs(hi - 30000.0 / 7476.0) < 1e-9


def test_tof_missing_difC_gives_none():
    h = _MockHist([1000.0, 30000.0])
    prof = ({"Zero": (0.0, False)},)  # difC 欠落 → 0 扱い
    assert _profile_ranges([h], [Radiation.NEUTRON_TOF], prof) == (None,)


def test_getdata_failure_gives_none():
    h = _MockHist([10.0, 120.0], x_raises=True)
    prof = ({"U": (2.0, True)},)
    assert _profile_ranges([h], [Radiation.XRAY_LAB], prof) == (None,)


def test_empty_x_gives_none():
    h = _MockHist([])
    prof = ({"U": (2.0, True)},)
    assert _profile_ranges([h], [Radiation.XRAY_LAB], prof) == (None,)


# --- _profiles_physical (統合ラッパ) ---

def test_physical_profile_passes():
    h = _MockHist([10.0, 120.0], inst={
        "U": [2, 2.0, True], "V": [-2, -2.0, True], "W": [5, 5.0, True],
    })
    assert _profiles_physical([h], [Radiation.XRAY_SYNCHROTRON]).passed is True


def test_nonphysical_refined_profile_fails():
    # W を大負に解放 → 低角で H_G²<0 → hard NG
    h = _MockHist([10.0, 120.0], inst={
        "U": [2, 2.0, True], "V": [-2, -2.0, True], "W": [5, -50.0, True],
    })
    assert _profiles_physical([h], [Radiation.XRAY_SYNCHROTRON]).passed is False


def test_all_empty_profiles_skip_passes():
    # Instrument Parameters 不在 → skip → passed=True
    h = _MockHist([10.0, 120.0], inst=None)
    h.data = {}
    assert _profiles_physical([h], [Radiation.XRAY_LAB]).passed is True


def test_profiles_physical_deterministic():
    h = _MockHist([10.0, 120.0], inst={
        "U": [2, 2.0, True], "V": [-2, -2.0, True], "W": [5, 5.0, True],
    })
    a = _profiles_physical([h], [Radiation.XRAY_SYNCHROTRON])
    b = _profiles_physical([h], [Radiation.XRAY_SYNCHROTRON])
    assert (a.passed, a.checks, a.warnings) == (b.passed, b.checks, b.warnings)
