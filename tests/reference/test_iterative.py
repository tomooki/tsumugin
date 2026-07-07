"""M11 reference/iterative.py — 逐次減算同定 identify_pattern の numpy 決定論テスト (stub 供給元)。

単相縮退 (k=1 停止)・多相受理・decoy 棄却 (残差支持)・known_phases 起点・注入 refiner の多形裁定・
決定論を、GSAS/MP なしに検証する。
"""

from __future__ import annotations

import numpy as np

from tsumugin.reference.iterative import (
    AcceptedPhase,
    IdentifyConfig,
    identify_pattern,
    refine_polymorphs,
)
from tsumugin.reference.model import PhaseMatch, ReferencePhase
from tsumugin.reference.scale import render_phase
from tsumugin.search.peaks import Peak
from tsumugin.store.ledger import Ledger

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


# 多ピーク相 (≥8): 減算時の格子整合 (_MIN_ALIGN_MATCHES=8) を活性化させ、系統的格子ずれの
# 吸収 (異方/等方整合) を実データ同様に働かせる。strain 伝播テストに使う。
_M_TRUE = [18.0, 22.0, 26.0, 31.0, 36.0, 41.0, 47.0, 53.0, 60.0]
M = _phase("mp-M", _M_TRUE, formula="M")


def test_accepted_strain_zero_without_refine():
    """refine_lattice=False では受理相の strain は 0 (格子整合しないので歪みなし)。"""
    obs = _observed((M, 2.0))
    cfg = IdentifyConfig(snr_stop=8.0, refine_lattice=False, rerank_top_k=0)
    res = identify_pattern(_TT, obs, _Prov([M, B]), elements=["Ca", "C", "O"], cfg=cfg)
    assert res.phase_ids == ("mp-M",)
    assert res.accepted[0].strain == 0.0


def test_polymorph_swap_resets_strain():
    """深段の多形 swap は別格子の相へ差し替えるため、旧相で求めた等方 strain を引き継がず 0 にリセット。

    strain は「提案相の計算ピークを観測へ整合した等方歪み」で、swap 先の多形は別格子ゆえ別の歪みに
    なる (swap は真 Rwp で決まり peak 整合を経ない)。旧 strain を新相へ流用すると materialize が
    誤った格子補正を掛けるため 0.0 にリセットする。未 swap の相は元の strain を保つ。
    """
    a1 = _phase("caco3-1", [20.0, 30.0, 45.0], formula="CaCO3")
    a2 = _phase("caco3-2", [20.0, 30.0, 45.0], formula="CaCO3")  # 同組成別多形
    accepted = (AcceptedPhase(reference=a1, scale=1.0, score=0.90, strain=0.007),)
    seen = (
        PhaseMatch(reference=a1, score=0.90, matched_observed=(), extra_calculated=()),
        PhaseMatch(reference=a2, score=0.88, matched_observed=(), extra_calculated=()),
    )

    def refiner(refs):
        return 10.0 if any(r.phase_id == "caco3-2" for r in refs) else 30.0

    new, refined = refine_polymorphs(
        accepted, seen, refiner, IdentifyConfig(polymorph_margin=0.5), Ledger()
    )
    assert refined is True
    assert new[0].phase_id == "caco3-2"  # aragonite 相当へ swap
    assert new[0].strain == 0.0  # swap 先は別格子 → strain リセット


def test_accepted_carries_nonzero_strain_with_refine():
    """候補ピークが観測より系統的にずれると refine_lattice が非零 strain を求め AcceptedPhase に載る。

    観測は真位置 M。供給する候補相のピークを一律 (1+ε) 倍で高角側へずらす (=格子がやや小さい系統ズレ)。
    ≥8 ピークで減算整合 (_MIN_ALIGN_MATCHES) が活性化し整合版が joint fit で採用され、提案時
    (identify_phases refine_lattice) が求めた非零 strain が受理相へ伝播する。
    """
    shifted_pos = [p * 1.010 for p in _M_TRUE]  # 一律 +1.0% 高角シフト (等方歪み相当)
    shifted = _phase("mp-M", shifted_pos, formula="M")
    obs = _observed((M, 2.0))  # 観測は真位置 (M)
    cfg = IdentifyConfig(snr_stop=8.0, refine_lattice=True, max_strain=0.05, rerank_top_k=0)
    res = identify_pattern(_TT, obs, _Prov([shifted, B]), elements=["Ca", "C", "O"], cfg=cfg)
    assert res.phase_ids == ("mp-M",)
    assert abs(res.accepted[0].strain) > 1e-4
