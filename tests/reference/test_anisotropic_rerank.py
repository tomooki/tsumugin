"""相同定 top-K 異方 re-score (Issue #20 hybrid) の numpy 決定論テスト (pymatgen/GSAS 非依存)。

align_peaks_anisotropic の単体 (異方セル回復) と、identify_phases(rerank_top_k=) が DFT 相当の
異方誤差を持つ正解相の識別マージンを改善することを検証する。参照相は hkl 付きピーク + cell +
crystal_system を直接構築 (供給元をフェイクで注入)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np

from tsumugin.autorietveld.lattice import two_theta_of_hkls
from tsumugin.reference.engine import identify_phases
from tsumugin.reference.model import ReferencePhase
from tsumugin.reference.rietveld import align_peaks_anisotropic
from tsumugin.search.peaks import Peak

_WL = 1.5406
_RANGE = (10.0, 80.0)
_HKLS = [
    (h, k, ll)
    for h in range(3) for k in range(3) for ll in range(6)
    if (h, k, ll) != (0, 0, 0)
]


def _peaks_at(cell, *, height=100.0):
    """cell の各 hkl の (2θ, height, hkl) を範囲内で返す (計算ピーク)。"""
    tth = two_theta_of_hkls(cell, _HKLS, _WL)
    out = []
    for hkl, t in zip(_HKLS, tth):
        if math.isfinite(t) and _RANGE[0] <= t <= _RANGE[1]:
            out.append(Peak(position=float(t), height=height, hkl=hkl))
    return tuple(out)


def _pattern_from_peaks(peaks, *, width=0.06):
    """計算ピーク列から合成観測パターン (two_theta, intensity) を作る。"""
    tt = np.linspace(_RANGE[0], _RANGE[1], 8000)
    inten = np.zeros_like(tt)
    for p in peaks:
        inten += p.height * np.exp(-0.5 * ((tt - p.position) / width) ** 2)
    return tt, inten


_TRUE = (6.527, 8.171, 13.322, 90.0, 90.0, 90.0)
# MP-DFT 相当の異方誤差 (a+0.4% b+0.8% c+3.4%)
_DFT = (6.527 * 1.004, 8.171 * 1.008, 13.322 * 1.034, 90.0, 90.0, 90.0)


def _ref_phase(phase_id, cell, *, elements=("Ca", "O", "Te")):
    return ReferencePhase(
        phase_id=phase_id, formula="CaTeO3", element_system=tuple(sorted(elements)),
        peaks=_peaks_at(cell), energy_above_hull=0.0,
        cell=cell, crystal_system="orthorhombic",
    )


class _FakeProvider:
    def __init__(self, phases: Sequence[ReferencePhase]) -> None:
        self._phases = tuple(phases)

    def fetch(self, elements: Sequence[str]) -> Sequence[ReferencePhase]:
        return self._phases


# --- align_peaks_anisotropic 単体 ---


def test_align_anisotropic_recovers_cell_and_positions():
    """DFT 摂動セルの参照相を真ピーク観測へ整合し、セルと位置を回復する。"""
    observed = _peaks_at(_TRUE)  # 真ピーク (観測相当)
    phase = _ref_phase("mp-delta", _DFT)
    al = align_peaks_anisotropic(phase, observed, wavelength=_WL, two_theta_range=_RANGE)
    assert al is not None
    assert abs(al.cell[2] - 13.322) < 0.03  # c を +3.4% から回復
    assert al.strain > 0.0  # 何らかの格子調整をした
    # 整合ピークが観測位置と概ね一致 (最寄り観測との差 < 0.2°)
    obs_pos = np.array([p.position for p in observed])
    for p in al.aligned_peaks[:10]:
        assert float(np.abs(obs_pos - p.position).min()) < 0.2


def test_align_anisotropic_none_without_cell():
    """cell/crystal_system が無い相 (等方供給元) は None (等方版へ縮退)。"""
    phase = ReferencePhase(
        phase_id="x", formula="X", element_system=("X",),
        peaks=_peaks_at(_DFT),  # hkl はあるが cell/system 無し
    )
    assert align_peaks_anisotropic(phase, _peaks_at(_TRUE)) is None


def test_align_anisotropic_none_without_hkl():
    """hkl 無しピーク (観測由来) の相は None。"""
    peaks = tuple(Peak(p.position, p.height) for p in _peaks_at(_DFT))  # hkl 落とす
    phase = ReferencePhase(
        phase_id="x", formula="X", element_system=("X",), peaks=peaks,
        cell=_DFT, crystal_system="orthorhombic",
    )
    assert align_peaks_anisotropic(phase, _peaks_at(_TRUE)) is None


# --- identify_phases(rerank_top_k=) の識別改善 ---


def test_rerank_improves_correct_phase_score():
    """DFT 摂動の正解相を、等方では負スコアだが異方 re-score で高スコア・首位にする。"""
    observed_tt, observed_int = _pattern_from_peaks(_peaks_at(_TRUE))
    # 正解 (DFT 摂動) + 不正解 (別セル = 別相)
    wrong = _ref_phase("mp-wrong", (5.0, 7.0, 11.0, 90.0, 90.0, 90.0))
    prov = _FakeProvider([_ref_phase("mp-delta", _DFT), wrong])

    common = dict(
        provider=prov, elements=["Ca", "Te", "O"], hull_cutoff_ev=None,
        scoring="dara", refine_lattice=True, max_strain=0.05,
    )
    iso = identify_phases(observed_tt, observed_int, **common)
    hyb = identify_phases(observed_tt, observed_int, rerank_top_k=2, rerank_wavelength=_WL, **common)

    iso_delta = next(m for m in iso.matches if m.reference.phase_id == "mp-delta")
    hyb_delta = next(m for m in hyb.matches if m.reference.phase_id == "mp-delta")

    # 異方 re-score で正解相のスコアが大きく上がる
    assert hyb_delta.score > iso_delta.score + 0.3
    # 異方 re-score 後は正解相が首位
    assert hyb.matches[0].reference.phase_id == "mp-delta"


def test_rerank_deterministic():
    observed_tt, observed_int = _pattern_from_peaks(_peaks_at(_TRUE))
    prov = _FakeProvider([_ref_phase("mp-delta", _DFT),
                          _ref_phase("mp-wrong", (5.0, 7.0, 11.0, 90.0, 90.0, 90.0))])
    kw = dict(provider=prov, elements=["Ca", "Te", "O"], hull_cutoff_ev=None,
              refine_lattice=True, max_strain=0.05, rerank_top_k=2, rerank_wavelength=_WL)
    r1 = identify_phases(observed_tt, observed_int, **kw)
    r2 = identify_phases(observed_tt, observed_int, **kw)
    assert [m.reference.phase_id for m in r1.matches] == [m.reference.phase_id for m in r2.matches]
    assert [m.score for m in r1.matches] == [m.score for m in r2.matches]


def test_rerank_zero_is_noop():
    """rerank_top_k=0 (既定) は従来 (等方のみ) と同一結果 (後方互換)。"""
    observed_tt, observed_int = _pattern_from_peaks(_peaks_at(_TRUE))
    prov = _FakeProvider([_ref_phase("mp-delta", _DFT)])
    kw = dict(provider=prov, elements=["Ca", "Te", "O"], hull_cutoff_ev=None,
              refine_lattice=True, max_strain=0.05)
    base = identify_phases(observed_tt, observed_int, **kw)
    rk0 = identify_phases(observed_tt, observed_int, rerank_top_k=0, **kw)
    assert [m.score for m in base.matches] == [m.score for m in rk0.matches]
