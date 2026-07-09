"""分解能プロファイル物理候補探索 (TASK-0001/0002/0003) の決定論テスト。

getFWHM 港・候補生成・探索オーケストレータを runner 注入で GSAS 非依存に検証。
"""

from __future__ import annotations

import math

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    InstrumentProfile,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.resolution import (
    candidate_profiles,
    profile_fwhm_min,
    profile_total_fwhm,
    search_instrument_profile,
)


def _standard():
    return HistogramSpec("ceo2.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")


def _structure():
    return PhaseSpec("ceo2.cif", "CeO2", format_hint="CIF")


# --- TASK-0001: profile_total_fwhm / profile_fwhm_min ---

def test_total_fwhm_physical_positive():
    # 物理値 (W>0, X>0, Y=0) は全域 FWHM 正
    vals = {"U": 0.0, "V": 1.8, "W": 0.96, "X": 0.41, "Y": 0.0}
    fw = profile_total_fwhm(vals, [10.0, 40.0, 80.0])
    assert all(f > 0 for f in fw)
    assert profile_fwhm_min(vals, 5.0, 110.0) > 0.0


def test_total_fwhm_nonphysical_negative_Y():
    # 強い負 Y は高角で総 FWHM 負 → fwhm_min が非正
    vals = {"U": 3.7, "V": -0.66, "W": 1.28, "X": 0.43, "Y": -5.32}
    assert profile_fwhm_min(vals, 5.0, 110.0) <= 0.0


def test_total_fwhm_deterministic():
    vals = {"W": 1.0, "X": 0.5, "Y": 0.0}
    assert profile_fwhm_min(vals) == profile_fwhm_min(vals)


# --- TASK-0002: candidate_profiles ---

def test_candidate_grid_count_and_anchor_included():
    anchor = {"U": 0.0, "V": 1.8, "W": 0.96, "X": 0.41, "Y": 0.0, "SH/L": 0.002}
    cands = candidate_profiles(anchor, x_factors=(0.8, 1.0, 1.2), w_factors=(1.0,),
                               y_offsets=(0.0,))
    assert len(cands) == 3
    # factor 1.0 の候補はアンカーの X,W を保つ
    mid = [c for c in cands if abs(c["X"] - 0.41) < 1e-9]
    assert mid and abs(mid[0]["W"] - 0.96) < 1e-9
    # U,V,SH/L は据え置き
    assert all(abs(c["V"] - 1.8) < 1e-9 and abs(c["SH/L"] - 0.002) < 1e-9 for c in cands)


def test_candidate_grid_perturbs_x_and_w():
    anchor = {"W": 1.0, "X": 0.5, "Y": 0.0}
    cands = candidate_profiles(anchor, x_factors=(0.5, 2.0), w_factors=(0.5, 2.0),
                               y_offsets=(0.0,))
    xs = sorted({round(c["X"], 3) for c in cands})
    ws = sorted({round(c["W"], 3) for c in cands})
    assert xs == [0.25, 1.0] and ws == [0.5, 2.0]
    assert len(cands) == 4


def test_candidate_grid_deterministic():
    a = candidate_profiles({"W": 1.0, "X": 0.5, "Y": 0.0})
    b = candidate_profiles({"W": 1.0, "X": 0.5, "Y": 0.0})
    assert a == b


# --- TASK-0003: search_instrument_profile ---

def _result(rwp):
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=rwp, gof=1.0, n_params=6, converged=True),),
        final_rwp=rwp, final_gof=1.0, refined_cells={"CeO2": (5.41,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True),
    )


def test_search_selects_min_rwp_among_physical():
    anchor = InstrumentProfile(values={"U": 0.0, "V": 1.8, "W": 0.96, "X": 0.41, "Y": 0.0},
                               source_rwp=9.06, wavelength=0.8)
    # 固定した候補の X で Rwp を作る (X=0.41 付近が最小になるよう)
    def runner(hists, phases, *, recipe=None, **kw):
        x = hists[0].instrument_profile.values["X"]
        return _result(9.0 + abs(x - 0.5) * 10)  # X=0.5 で最小

    out = search_instrument_profile(
        _standard(), _structure(), anchor=anchor, runner=runner,
        candidates=[{"U": 0.0, "V": 1.8, "W": 0.96, "X": xx, "Y": 0.0}
                    for xx in (0.3, 0.5, 0.7)],
    )
    assert abs(out.values["X"] - 0.5) < 1e-9  # 最小 Rwp の候補
    assert out.wavelength == 0.8               # アンカーから継承


def test_search_filters_nonphysical_candidates():
    anchor = InstrumentProfile(values={"W": 1.0, "X": 0.5, "Y": 0.0}, source_rwp=9.0)
    # 非物理候補 (Y 大負) は Rwp が低くても除外される
    cands = [
        {"U": 3.7, "V": -0.66, "W": 1.28, "X": 0.43, "Y": -5.32},  # 非物理・Rwp 最小狙い
        {"U": 0.0, "V": 1.8, "W": 0.96, "X": 0.41, "Y": 0.0},       # 物理
    ]

    def runner(hists, phases, *, recipe=None, **kw):
        y = hists[0].instrument_profile.values["Y"]
        return _result(8.0 if y < 0 else 9.0)  # 非物理の方が低 Rwp

    out = search_instrument_profile(_standard(), _structure(), anchor=anchor,
                                    runner=runner, candidates=cands)
    assert out.values["Y"] == 0.0  # 非物理は除外され物理候補が選ばれる


def test_search_fallback_to_anchor_when_no_physical():
    anchor = InstrumentProfile(values={"W": 1.0, "X": 0.5, "Y": 0.0}, source_rwp=9.06)

    def runner(hists, phases, *, recipe=None, **kw):
        return _result(8.0)

    # 全候補が非物理 → アンカーを返す
    out = search_instrument_profile(
        _standard(), _structure(), anchor=anchor, runner=runner,
        candidates=[{"U": 3.7, "V": -0.66, "W": 1.28, "X": 0.43, "Y": -5.32}],
    )
    assert out is anchor or dict(out.values) == dict(anchor.values)


def test_search_deterministic():
    anchor = InstrumentProfile(values={"W": 1.0, "X": 0.5, "Y": 0.0}, source_rwp=9.0)

    def runner(hists, phases, *, recipe=None, **kw):
        return _result(9.0 + hists[0].instrument_profile.values["X"])

    cands = [{"W": 1.0, "X": xx, "Y": 0.0} for xx in (0.3, 0.5)]
    a = search_instrument_profile(_standard(), _structure(), anchor=anchor, runner=runner,
                                  candidates=cands)
    b = search_instrument_profile(_standard(), _structure(), anchor=anchor, runner=runner,
                                  candidates=cands)
    assert dict(a.values) == dict(b.values)
    assert math.isfinite(a.source_rwp)
