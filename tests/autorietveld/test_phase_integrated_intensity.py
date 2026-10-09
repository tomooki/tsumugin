"""fit-then-judge P1a タスク 5: 相ごとの積分計算強度 Σ Fc²·Icorr (`phase_integrated_intensity`)。

テンプレートは「構造を精密化する対象相」を、段 0 の相分率 (潰れうる) ではなく幅の段の後の
**散乱寄与**で決める。GSAS-II の反射リストは列 9 が Fc²、列 11 が Icorr (スケール・多重度・
偏光・選択配向・吸収・Lorentz・1/V² を含む強度補正) なので、Σ Fc²·Icorr が相の積分強度になる
(超空間群は列が 1 つずれる)。観測のみ — フィットには使わない。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.autorietveld.engine import _integrated_intensity


def _reflist(fc2, icorr, super_=False):
    width = 17 + (1 if super_ else 0)
    rows = np.zeros((len(fc2), width))
    im = 1 if super_ else 0
    rows[:, 9 + im] = fc2
    rows[:, 11 + im] = icorr
    return rows


def test_sum_of_fc2_times_icorr():
    assert _integrated_intensity(_reflist([4.0, 1.0], [2.0, 3.0])) == 11.0


def test_superspace_lists_are_offset_by_one_column():
    assert _integrated_intensity(_reflist([4.0, 1.0], [2.0, 3.0], super_=True), super_=True) == 11.0


def test_empty_list_is_zero_not_an_error():
    assert _integrated_intensity(np.zeros((0, 17))) == 0.0


@pytest.mark.gsas
def test_ratio_matches_gsas_phase_fractions_on_a_simulated_two_phase_pattern(tmp_path):
    """GSAS 自身の計算と照合する: 同じ構造の 2 相を相分率 0.7/0.3 で計算させると、
    抽出した積分強度の比はちょうど 0.7/0.3 になる (Icorr がスケールを含むことの確認)。"""
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld.engine import _phase_integrated_intensity
    from tsumugin.autorietveld.model import Radiation
    from tsumugin.instprm import build_instprm_text

    from .test_engine_polar_origin import _ZNO_CIF

    instprm = tmp_path / "cuka1.instprm"
    instprm.write_text(
        build_instprm_text(radiation=Radiation.XRAY_LAB, wavelength=1.5405980), encoding="utf-8"
    )
    cif = tmp_path / "zno.cif"
    cif.write_text(_ZNO_CIF.format(oz=0.382), encoding="utf-8")
    sim = G2sc.G2Project(newgpx=str(tmp_path / "two.gpx"))
    a = sim.add_phase(str(cif), phasename="A", fmthint="CIF")
    b = sim.add_phase(str(cif), phasename="B", fmthint="CIF")
    sim.add_simulated_powder_histogram("sim", str(instprm), 20.0, 120.0, Tstep=0.02,
                                       phases=sim.phases())
    a.HAPvalue("Scale", 0.7)
    b.HAPvalue("Scale", 0.3)
    sim.do_refinements([{}])

    out = _phase_integrated_intensity(sim.phases(), sim.histograms())
    (ia,), (ib,) = out["A"], out["B"]
    assert ia > 0 and ib > 0
    assert math.isclose(ia / ib, 0.7 / 0.3, rel_tol=1e-9), (ia, ib)


class _Hist:
    def __init__(self, refl):
        self._refl = refl

    def reflections(self):
        return self._refl


class _Ph:
    def __init__(self, name):
        self.name = name


def test_empty_or_malformed_reflection_lists_are_unknown_not_zero():
    """空の反射リストは「未計算」、想定外の形は読めない — どちらも 0.0 を捏造しない (L2)。"""
    from tsumugin.autorietveld.engine import _phase_integrated_intensity

    hists = [_Hist({"A": {"RefList": []}, "B": {"RefList": [[1, 2, 3]]}})]
    out = _phase_integrated_intensity([_Ph("A"), _Ph("B"), _Ph("C")], hists)
    assert out == {"A": (None,), "B": (None,), "C": (None,)}


def test_unexpected_entry_shapes_are_unknown_not_errors():
    """反射リストの項目が dict でない・RefList がスカラーでも既定経路の最後で落とさない (L2)。"""
    from tsumugin.autorietveld.engine import _phase_integrated_intensity

    hists = [_Hist({"A": "not-a-dict", "B": {"RefList": 3.0}})]
    assert _phase_integrated_intensity([_Ph("A"), _Ph("B")], hists) == {"A": (None,), "B": (None,)}
