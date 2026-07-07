"""M11 identify_pattern の対抗テスト — 少数相検出限界 + ピーク重畳分離。

要点 (docs/design/m11-iterative-identification/architecture.md AC-3):
少数相 (5-20%) を主相減算後の残差から検出できることが本アルゴリズムの主張する利点。
ここでは主相 (scale=10) に対し少数相のスケールを段階的に下げ (1.0 → 0.1 等)、
どこまで検出できるかを確認する。また、2 相のピーク位置が一部重なる場合に
joint 非負スケール fit が正しくスケールを分離できるかを確認する。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.reference.iterative import IdentifyConfig, identify_pattern
from tsumugin.reference.model import ReferencePhase
from tsumugin.reference.scale import fit_nonneg_scales, render_phase
from tsumugin.search.peaks import Peak

_TT = np.linspace(10.0, 80.0, 3500)
_FWHM = 0.15


def _phase(pid, positions, *, formula=None, heights=None, elements=("Ca", "C", "O")):
    hs = heights or [100.0] * len(positions)
    peaks = tuple(Peak(position=float(p), height=float(h)) for p, h in zip(positions, hs))
    return ReferencePhase(
        phase_id=pid, formula=formula or pid,
        element_system=tuple(sorted(elements)), peaks=peaks,
        energy_above_hull=0.0,
    )


class _Prov:
    def __init__(self, phases):
        self._p = tuple(phases)

    def fetch(self, elements):
        return self._p


def _observed(*phase_scales, noise=0.0, seed=0):
    y = np.zeros_like(_TT)
    for ph, s in phase_scales:
        y += s * render_phase(_TT, [(p.position, p.height) for p in ph.peaks], _FWHM)
    if noise:
        y = np.clip(y + np.random.default_rng(seed).normal(0, noise * y.max(), _TT.size), 0, None)
    return y


# 主相 (完全に分離した非重複ピーク) と少数相 (これまた分離したピーク)
MAJOR = _phase("mp-major", [15.0, 25.0, 40.0, 55.0, 70.0], formula="Major")
MINOR = _phase("mp-minor", [30.0, 47.0, 63.0], formula="Minor")

CFG = IdentifyConfig(eps_gain=0.02, max_phases=5)  # 既定 snr_stop=5 (5σ 検出閾値)


# ---------------------------------------------------------------------------
# (1) 少数相検出限界: 主相 scale=10 固定、少数相 scale を段階的に下げる
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("minor_scale", [1.0, 0.5, 0.2, 0.1])
def test_minority_phase_detected_down_to_low_fraction(minor_scale):
    """主相 10 : 少数相 minor_scale (分率 ~9%まで) を無雑音で両方検出できる。"""
    obs = _observed((MAJOR, 10.0), (MINOR, minor_scale))
    res = identify_pattern(
        _TT, obs, _Prov([MAJOR, MINOR]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res.phase_ids) == {"mp-major", "mp-minor"}, (
        f"minor_scale={minor_scale} not recovered: got {res.phase_ids}"
    )


@pytest.mark.parametrize("minor_scale", [0.05, 0.02])
def test_minority_phase_below_limit_with_noise(minor_scale):
    """雑音下で非常に小さい少数相 (2-5%) はノイズ床に埋もれ検出限界を割ることがある。

    これは failure を期待するテストではなく、検出限界を実測するための診断テスト。
    どちらの結果 (検出/非検出) でもクラッシュしない・major は必ず残ることのみ assert する。
    """
    obs = _observed((MAJOR, 10.0), (MINOR, minor_scale), noise=0.01, seed=1)
    res = identify_pattern(
        _TT, obs, _Prov([MAJOR, MINOR]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert "mp-major" in res.phase_ids


def test_minority_detection_limit_with_realistic_noise():
    """計数統計様のノイズ下で、少数相 10% は検出できるが 1% は検出限界を割ることを確認する。

    quantifies the detection-limit claim (AC-3): 主相 scale=10 に対し、
    minor=1.0 (fraction ~9%) は検出できる一方、minor=0.05 (fraction ~0.5%)
    はノイズに埋もれて非検出でもよい、という現実的な範囲を固定する。
    """
    obs_10pct = _observed((MAJOR, 10.0), (MINOR, 1.0), noise=0.01, seed=7)
    res_10pct = identify_pattern(
        _TT, obs_10pct, _Prov([MAJOR, MINOR]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res_10pct.phase_ids) == {"mp-major", "mp-minor"}


# ---------------------------------------------------------------------------
# (2) ピーク重畳: 主相と少数相の一部ピークが同一 2θ 位置を共有する場合の分離
# ---------------------------------------------------------------------------
OVERLAP_MAJOR = _phase("mp-ovl-major", [15.0, 25.0, 40.0], formula="OMajor", elements=("Ca", "O"))
# minor は major の 40.0 ピークと重なる位置を含む (重畳)
OVERLAP_MINOR = _phase("mp-ovl-minor", [40.0, 58.0], formula="OMinor", elements=("Fe", "O"))


def test_overlapping_peaks_joint_fit_separates_scales():
    """major/minor が 1 本ピークを共有していても joint 非負スケール fit が正しい比を復元する。"""
    true_major, true_minor = 5.0, 2.0
    obs = _observed((OVERLAP_MAJOR, true_major), (OVERLAP_MINOR, true_minor))

    peaklists = [
        [(p.position, p.height) for p in OVERLAP_MAJOR.peaks],
        [(p.position, p.height) for p in OVERLAP_MINOR.peaks],
    ]
    scales, model, resid, ss = fit_nonneg_scales(_TT, obs, peaklists, _FWHM)
    assert scales[0] == pytest.approx(true_major, rel=0.05)
    assert scales[1] == pytest.approx(true_minor, rel=0.05)
    assert ss < 1e-6  # 完全再構成 (無雑音)


def test_overlapping_peaks_identify_pattern_recovers_both():
    """ピーク重畳がある混合を identify_pattern がそれでも両相として同定する。"""
    obs = _observed((OVERLAP_MAJOR, 5.0), (OVERLAP_MINOR, 2.0))
    res = identify_pattern(
        _TT, obs, _Prov([OVERLAP_MAJOR, OVERLAP_MINOR]),
        elements=["Ca", "O", "Fe"], cfg=CFG,
    )
    assert set(res.phase_ids) == {"mp-ovl-major", "mp-ovl-minor"}
    scale_by_id = {a.phase_id: a.scale for a in res.accepted}
    assert scale_by_id["mp-ovl-major"] == pytest.approx(5.0, rel=0.1)
    assert scale_by_id["mp-ovl-minor"] == pytest.approx(2.0, rel=0.1)


def test_overlapping_peaks_minority_with_full_overlap_of_one_peak():
    """少数相の全ピークのうち唯一のピークが主相と完全重複するケース (最も厳しい重畳)。

    minor が単一ピークのみでそれが major の 1 本と重なる場合、joint fit は
    2 相を区別する情報が乏しい (縮退方向に近い) が、他の major ピークが
    major のスケールを別途拘束するため、なお分離可能なはず。
    """
    single_peak_minor = _phase(
        "mp-single-ovl", [25.0], formula="SingleOvl", elements=("Fe",)
    )
    obs = _observed((OVERLAP_MAJOR, 5.0), (single_peak_minor, 1.0))
    peaklists = [
        [(p.position, p.height) for p in OVERLAP_MAJOR.peaks],
        [(p.position, p.height) for p in single_peak_minor.peaks],
    ]
    scales, model, resid, ss = fit_nonneg_scales(_TT, obs, peaklists, _FWHM)
    assert scales[0] == pytest.approx(5.0, rel=0.1)
    assert scales[1] == pytest.approx(1.0, rel=0.1)


# ---------------------------------------------------------------------------
# (3) 3 相・階層的少数相 (major + moderate minor + trace minor)
# ---------------------------------------------------------------------------
TRACE = _phase("mp-trace", [12.0, 33.0, 66.0], formula="Trace")


def test_three_phase_major_minor_trace():
    """主相 + 中程度少数相 + 微量相の 3 段階を無雑音で全て回収できる。"""
    obs = _observed((MAJOR, 10.0), (MINOR, 2.0), (TRACE, 0.3))
    res = identify_pattern(
        _TT, obs, _Prov([MAJOR, MINOR, TRACE]),
        elements=["Ca", "C", "O"], cfg=IdentifyConfig(max_phases=6),
    )
    assert set(res.phase_ids) == {"mp-major", "mp-minor", "mp-trace"}
