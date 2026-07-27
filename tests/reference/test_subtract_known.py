"""`reference.iterative.subtract_known_phases` — 既知相を差し引いた残差パターン (Issue #20 続き)。

異方セルプリアラインの目的関数 (`lattice._peak_match_fom`) は**観測ピーク基準**のため、少数相の
セルを生パターンへ合わせると FoM が**支配相のピーク**に占められ、少数相の反射を支配相の位置へ
ばら撒くセルを選んでしまう (実測 CaTeO3 frame180: delta の最大軸誤差 3.42% → 4.21%)。
対策は「候補が支配的なパターン = 既知相を引いた残差」へ整合させること。本モジュールはその
残差を作る numpy コア。
"""

from __future__ import annotations

import numpy as np

from tsumugin.reference.iterative import IdentifyConfig, subtract_known_phases
from tsumugin.reference.model import ReferencePhase
from tsumugin.reference.scale import render_phase
from tsumugin.search.peaks import Peak

_TT = np.linspace(10.0, 80.0, 3500)
_FWHM = 0.15


def _phase(pid, positions, *, heights=None):
    hs = heights or [100.0] * len(positions)
    return ReferencePhase(
        phase_id=pid, formula=pid, element_system=("Ca", "O"),
        peaks=tuple(Peak(position=float(p), height=float(h)) for p, h in zip(positions, hs)),
        energy_above_hull=0.0,
    )


MAJOR = _phase("major", [15.0, 25.0, 40.0, 55.0, 70.0])
MINOR = _phase("minor", [30.0, 47.0, 63.0])
CFG = IdentifyConfig(subtract_bg=False, auto_fwhm=False, fwhm=_FWHM)


def _render(phase, scale):
    return scale * render_phase(_TT, [(p.position, p.height) for p in phase.peaks], _FWHM)


def _height_at(vec, position, half_width=0.4):
    sel = np.abs(_TT - position) <= half_width
    return float(vec[sel].max())


def test_removes_known_phase_and_keeps_unknown():
    """支配相を引いた残差では、支配相のピークが消え少数相のピークが残る。"""
    obs = _render(MAJOR, 10.0) + _render(MINOR, 1.0)
    resid = subtract_known_phases(_TT, obs, [MAJOR], cfg=CFG)

    minor_before = _height_at(obs, 30.0)
    minor_after = _height_at(resid, 30.0)
    for pos in (15.0, 25.0, 40.0, 55.0, 70.0):
        assert _height_at(resid, pos) < 0.05 * _height_at(obs, pos), f"{pos}° の支配相ピークが残存"
    assert minor_after > 0.8 * minor_before, "少数相のピークまで削られている"


def test_minority_peaks_dominate_the_residual():
    """残差では少数相が**支配的**になる (プリアラインの FoM が少数相に支配される前提条件)。"""
    obs = _render(MAJOR, 10.0) + _render(MINOR, 1.0)
    resid = subtract_known_phases(_TT, obs, [MAJOR], cfg=CFG)
    minor_mass = sum(_height_at(resid, p) for p in (30.0, 47.0, 63.0))
    major_mass = sum(_height_at(resid, p) for p in (15.0, 25.0, 40.0, 55.0, 70.0))
    assert minor_mass > 5.0 * major_mass


def test_no_known_phases_returns_preprocessed_pattern():
    """既知相ゼロなら前処理 (背景減算) だけを掛けて返す (静的同定と同一入力に縮退)。"""
    obs = _render(MAJOR, 10.0)
    resid = subtract_known_phases(_TT, obs, [], cfg=CFG)
    assert np.allclose(resid, obs)


def test_non_negative_and_deterministic():
    """残差は非負 (過剰減算を負のピークとして持ち込まない) かつ決定論 (NFR-102)。"""
    obs = _render(MAJOR, 10.0) + _render(MINOR, 1.0)
    first = subtract_known_phases(_TT, obs, [MAJOR], cfg=CFG)
    second = subtract_known_phases(_TT, obs, [MAJOR], cfg=CFG)
    assert np.array_equal(first, second)
    assert float(first.min()) >= 0.0


def test_subtracts_background_when_configured():
    """cfg.subtract_bg=True なら SNIP 背景も落ちる (プリアラインへ subtract_bg=False で渡すため)。"""
    obs = _render(MAJOR, 10.0) + _render(MINOR, 1.0) + 500.0
    resid = subtract_known_phases(_TT, obs, [MAJOR], cfg=IdentifyConfig(fwhm=_FWHM))
    baseline = float(np.median(resid))
    assert baseline < 50.0, f"背景が残っている (median={baseline:.1f})"
    assert _height_at(resid, 30.0) > 0.5 * _height_at(obs - 500.0, 30.0)
