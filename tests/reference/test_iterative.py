"""M11 reference/iterative.py — 逐次減算同定 identify_pattern の numpy 決定論テスト (stub 供給元)。

単相縮退 (k=1 停止)・多相受理・decoy 棄却 (残差支持)・known_phases 起点・注入 refiner の多形裁定・
決定論を、GSAS/MP なしに検証する。
"""

from __future__ import annotations

import numpy as np

from tsumugin.reference.iterative import IdentifyConfig, identify_pattern
from tsumugin.reference.model import ReferencePhase
from tsumugin.reference.scale import render_phase
from tsumugin.search.peaks import Peak

_TT = np.linspace(10.0, 80.0, 3500)
_FWHM = 0.15


def _phase(pid, positions, *, formula=None, heights=None, elements=("Ca", "C", "O")):
    hs = heights or [100.0] * len(positions)
    peaks = tuple(Peak(position=float(p), height=float(h)) for p, h in zip(positions, hs))
    return ReferencePhase(phase_id=pid, formula=formula or pid,
                          element_system=tuple(sorted(elements)), peaks=peaks,
                          energy_above_hull=0.0)


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


A = _phase("mp-A", [20.0, 35.0, 52.0], formula="A")
B = _phase("mp-B", [27.0, 44.0, 61.0], formula="B")
CFG = IdentifyConfig(snr_stop=8.0, eps_gain=0.02, max_phases=5)


def test_single_phase_stops_at_k1():
    """単相パターンは 1 相受理して k=1 で自然停止 (相数を知らなくてよい)。"""
    obs = _observed((A, 2.0))
    res = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    assert res.phase_ids == ("mp-A",)
    assert len(res.iterations) == 1
    assert res.accepted[0].scale > 0.5


def test_two_phase_mixture():
    """A + B の混合を 2 相として同定する。"""
    obs = _observed((A, 2.0), (B, 3.0))
    res = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    assert set(res.phase_ids) == {"mp-A", "mp-B"}


def test_noise_only_accepts_nothing():
    """ノイズのみ (相の実体なし) は 0 相 (残差 S/N が最初から低い)。"""
    obs = np.clip(np.random.default_rng(0).normal(20.0, 3.0, _TT.size), 0, None)
    res = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    assert res.phase_ids == ()


def test_decoy_rejected_by_residual_support():
    """decoy (A のピーク部分集合) は A 減算後に説明対象を失い scale≈0 で棄却 (化学ガードなし)。"""
    decoy = _phase("mp-decoy", [20.0], formula="Cdecoy", elements=("C",))
    obs = _observed((A, 2.0), (B, 3.0))
    res = identify_pattern(_TT, obs, _Prov([A, B, decoy]), elements=["Ca", "C", "O"], cfg=CFG)
    assert "mp-decoy" not in res.phase_ids
    assert set(res.phase_ids) == {"mp-A", "mp-B"}


def test_known_phases_start():
    """known_phases=[A] 起点なら A を先に減算し B を追加同定する (operando 一本化の核)。"""
    obs = _observed((A, 2.0), (B, 3.0))
    res = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"],
                           known_phases=[A], cfg=CFG)
    assert set(res.phase_ids) == {"mp-A", "mp-B"}
    # B は反復で追加 (A は known)
    assert any(it.accepted_id == "mp-B" for it in res.iterations)


def test_refiner_discriminates_polymorph():
    """同組成多形 A1/A2 (peak-search で近接) を注入 refiner が真 Rwp で A2 に確定する。"""
    a1 = _phase("caco3-1", [20.0, 30.0, 45.0], formula="CaCO3")
    a2 = _phase("caco3-2", [20.0, 30.0, 45.0], formula="CaCO3")  # ピーク同一 = 探索で判別不可
    obs = _observed((a2, 2.0))

    def refiner(refs):
        return 10.0 if any(r.phase_id == "caco3-2" for r in refs) else 30.0

    res = identify_pattern(_TT, obs, _Prov([a1, a2]), elements=["Ca", "C", "O"],
                           refiner=refiner, cfg=IdentifyConfig(polymorph_margin=0.5))
    assert res.refined is True
    assert "caco3-2" in res.phase_ids


def test_refiner_none_no_refine():
    obs = _observed((A, 2.0))
    res = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    assert res.refined is False


def test_ledger_appended_and_verifies():
    obs = _observed((A, 2.0), (B, 3.0))
    res = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    assert res.ledger is not None and res.ledger.verify()


def test_deterministic():
    obs = _observed((A, 2.0), (B, 3.0))
    r1 = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    r2 = identify_pattern(_TT, obs, _Prov([A, B]), elements=["Ca", "C", "O"], cfg=CFG)
    assert r1.phase_ids == r2.phase_ids
    assert [a.scale for a in r1.accepted] == [a.scale for a in r2.accepted]
