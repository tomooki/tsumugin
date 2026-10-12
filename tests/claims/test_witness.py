"""fit-then-judge P1-1A タスク 5: 相集合の完全性の証人 (REQ-FTJ-1A-402)。

最終 fit の計算反射から離れた窓の残差 S/N で、モデルに無い相のピーク (= 説明されていない強度) を拾う。
計算できないときは pass ではなく unevaluated。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.claims.model import Check
from tsumugin.claims.witness import cw_fwhm_deg, residual_window_witness

_TT = np.arange(10.0, 80.0, 0.01)
_REFL = (15.0, 22.5, 31.0, 44.0, 52.5, 61.0, 73.0)
#: W=100 centideg² → σ=0.1° → FWHM ≈ 0.235° (GSAS の CW の単位)
_PROFILE = {"U": 0.0, "V": 0.0, "W": 100.0, "X": 0.0, "Y": 0.0}


def _noise(seed=0):
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, _TT.size), np.ones(_TT.size)


def _peak(center, amp, fwhm=0.235):
    s = fwhm / 2.3548
    return amp * np.exp(-0.5 * ((_TT - center) / s) ** 2)


def _run(resid, sigma, refl=_REFL, profile=_PROFILE, **kw):
    return residual_window_witness(_TT, resid, sigma, refl, profile, **kw)


def test_fwhm_follows_the_gsas_cw_profile_units():
    assert cw_fwhm_deg(40.0, _PROFILE) == pytest.approx(0.2355, rel=1e-3)
    # Lorentz 幅が足されると広がる
    assert cw_fwhm_deg(40.0, {**_PROFILE, "X": 20.0}) > cw_fwhm_deg(40.0, _PROFILE)


def test_noise_only_residual_passes():
    resid, sigma = _noise()
    check, witness = _run(resid, sigma)
    assert check is Check.PASS
    assert witness.kind == "residual_window_snr"
    assert witness.detail["max_snr"] < 5.0


def test_an_unexplained_peak_away_from_the_reflections_fails():
    """モデルに無い相のピーク: 計算反射のどこからも離れた位置に正の残差。"""
    resid, sigma = _noise()
    check, witness = _run(resid + _peak(37.0, 8.0), sigma)
    assert check is Check.FAIL
    lo, hi = witness.detail["window_two_theta"]
    assert lo <= 37.0 <= hi


def test_a_misfit_at_a_calculated_reflection_is_not_counted():
    """計算反射の上の残差は「既知の相の合わなさ」— 欠落相の証拠ではない (反射の周りは除外)。"""
    resid, sigma = _noise()
    check, _ = _run(resid + _peak(31.0, 8.0), sigma)
    assert check is Check.PASS


def test_a_slow_background_misfit_is_not_mistaken_for_a_phase():
    resid, sigma = _noise()
    check, _ = _run(resid + 0.5 * (_TT - 10.0) / 70.0, sigma)
    assert check is Check.PASS


@pytest.mark.parametrize(
    "change",
    [
        {"refl": None},  # 反射位置を計測していない
        {"profile": {}},  # 幅を決められない
    ],
)
def test_what_cannot_be_computed_is_unevaluated_not_pass(change):
    resid, sigma = _noise()
    check, witness = _run(resid, sigma, **change)
    assert check is Check.UNEVALUATED
    assert witness.detail["reason"]


def test_an_empty_residual_is_unevaluated():
    check, _ = residual_window_witness((), (), (), _REFL, _PROFILE)
    assert check is Check.UNEVALUATED


def test_when_reflections_cover_everything_it_is_unevaluated():
    """反射が全域を覆って窓が残らない — 「欠落相が無い」とは言えない。"""
    dense = tuple(np.arange(10.0, 80.0, 0.2))
    resid, sigma = _noise()
    check, _ = _run(resid, sigma, refl=dense)
    assert check is Check.UNEVALUATED


def test_infinite_sigma_points_are_ignored():
    """重み 0 の点 (σ=inf) は情報を持たない — S/N の分母を壊さない。"""
    resid, sigma = _noise()
    sigma = sigma.copy()
    sigma[::7] = np.inf
    check, _ = _run(resid + _peak(37.0, 8.0), sigma)
    assert check is Check.FAIL


def test_underestimated_sigma_does_not_make_noise_look_like_a_phase():
    """Rietveld の σ は計数統計だけで GOF > 1 が普通 — 雑音が σ の 1.8 倍でも fail にしない。"""
    resid, sigma = _noise()
    check, witness = _run(1.8 * resid, sigma)
    assert check is Check.PASS
    assert witness.detail["noise_scale"] > 1.5


def test_an_unexplained_peak_is_still_found_with_underestimated_sigma():
    resid, sigma = _noise()
    check, _ = _run(1.8 * resid + _peak(37.0, 8.0), sigma)
    assert check is Check.FAIL


def test_data_too_coarse_for_a_peak_sized_window_is_unevaluated():
    """ステップが FWHM より粗く窓が 3 点を持てない — 何も検査していないのに pass と答えない。"""
    tt = np.arange(10.0, 80.0, 0.3)
    rng = np.random.default_rng(0)
    check, witness = residual_window_witness(
        tt, rng.normal(0.0, 1.0, tt.size), np.ones(tt.size), (), _PROFILE,
    )
    assert check is Check.UNEVALUATED
    assert witness.detail["reason"] == "no_window"


def test_the_tail_of_a_known_peak_just_outside_the_exclusion_is_not_a_phase():
    """既知相のピークの裾 (非対称・形の合わなさ) は除外域の外まで単調に伸びる — 実データ (T2
    garnet, 50.77° の強い反射の手前) で偽の fail になった形。坂は山ではない。"""
    resid, sigma = _noise()
    ramp = np.where((_TT > 29.2) & (_TT < 30.29), 8.0 * np.exp((_TT - 30.29) / 0.4), 0.0)
    check, witness = _run(resid + ramp, sigma)
    assert check is Check.PASS, witness.detail
