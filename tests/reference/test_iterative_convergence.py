"""M11 identify_pattern の収束/現実性/refiner 深段のストレステスト (numpy-only, 決定論)。

対象:
- 多相 (3-4相) 収束: 全相を安定順序で回復し、正しい相数で停止するか。
- 現実的パターン: 残差バックグラウンドの盛り上がり + ノイズがあっても誤同定/無限反復しないか。
- FWHM 不一致: フィットの固定 fwhm と異なる実 FWHM の相でも受理が頑健か。
- refiner 深段: 複数の同組成多形グループそれぞれで、ピーク探索が誤った多形を選んでも
  注入 refiner が正しい多形へ swap するか。refiner が例外を送出したら peak-space 結果へ
  安全にフォールバックするか。
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


def _observed(*phase_scales, fwhm=_FWHM, noise=0.0, seed=0, background=None):
    y = np.zeros_like(_TT)
    for ph, s in phase_scales:
        y += s * render_phase(_TT, [(p.position, p.height) for p in ph.peaks], fwhm)
    if background is not None:
        y = y + background
    if noise:
        y = np.clip(y + np.random.default_rng(seed).normal(0, noise, _TT.size), 0, None)
    return y


CFG = IdentifyConfig(snr_stop=8.0, eps_gain=0.02, max_phases=5)


# ---------------------------------------------------------------------------
# 1. 多相 (3-4相) 収束
# ---------------------------------------------------------------------------

P1 = _phase("mp-P1", [15.0, 25.0, 38.0], formula="P1")
P2 = _phase("mp-P2", [18.0, 33.0, 50.0], formula="P2")
P3 = _phase("mp-P3", [22.0, 41.0, 58.0], formula="P3")
P4 = _phase("mp-P4", [29.0, 47.0, 66.0], formula="P4")


def test_three_phase_mixture_recovers_all_and_stops():
    """3 相混合を正しい相数 (3) で回復・停止する (相数を事前指定しない)。"""
    obs = _observed((P1, 2.0), (P2, 1.5), (P3, 1.0))
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res.phase_ids) == {"mp-P1", "mp-P2", "mp-P3"}
    assert "mp-P4" not in res.phase_ids
    assert len(res.iterations) == 3


def test_four_phase_mixture_recovers_all_and_stops():
    """4 相混合 (max_phases=5 の安全網内) も全相回復し 4 で停止する。"""
    obs = _observed((P1, 2.0), (P2, 1.5), (P3, 1.0), (P4, 1.2))
    cfg = IdentifyConfig(snr_stop=8.0, eps_gain=0.02, max_phases=6)
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=cfg
    )
    assert set(res.phase_ids) == {"mp-P1", "mp-P2", "mp-P3", "mp-P4"}
    assert len(res.iterations) == 4


def test_four_phase_mixture_deterministic_order():
    """反復順序 (accepted_id の並び) は入力プール順に関わらず決定論・再現可能。"""
    obs = _observed((P1, 2.0), (P2, 1.5), (P3, 1.0), (P4, 1.2))
    cfg = IdentifyConfig(snr_stop=8.0, eps_gain=0.02, max_phases=6)
    r1 = identify_pattern(_TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=cfg)
    r2 = identify_pattern(_TT, obs, _Prov([P4, P3, P2, P1]), elements=["Ca", "C", "O"], cfg=cfg)
    order1 = [it.accepted_id for it in r1.iterations]
    order2 = [it.accepted_id for it in r2.iterations]
    assert order1 == order2, f"provider order should not change acceptance order: {order1} vs {order2}"
    assert set(r1.phase_ids) == set(r2.phase_ids)


def test_max_phases_safety_net_caps_iterations():
    """max_phases はスケールの小さい追加相を無限に拾おうとする暴走を止める安全網。"""
    obs = _observed((P1, 2.0), (P2, 1.5), (P3, 1.0), (P4, 1.2))
    cfg = IdentifyConfig(snr_stop=8.0, eps_gain=0.02, max_phases=2)
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=cfg
    )
    assert len(res.iterations) <= 2


# ---------------------------------------------------------------------------
# 2. 現実的パターン: 残差バックグラウンド + ノイズ
# ---------------------------------------------------------------------------

def test_background_bump_plus_noise_still_recovers_phases():
    """緩やかな背景の盛り上がり (broad hump) + ノイズがあっても実在相のみ回復する。

    subtract_bg=True (既定) の SNIP 背景減算が broad hump を地の背景として吸収できる
    範囲で、decoy を作らず本来の相集合だけを受理することを確認する。
    """
    broad_hump = 15.0 * np.exp(-0.5 * ((_TT - 45.0) / 20.0) ** 2)
    obs = _observed(
        (P1, 2.0), (P2, 1.5),
        background=broad_hump,
        noise=0.8, seed=1,
    )
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res.phase_ids) == {"mp-P1", "mp-P2"}


def test_noisy_two_phase_deterministic_given_fixed_observation():
    """同一 (固定) ノイズ付き観測を 2 回投入すれば出力は完全一致 (乱数は同定側で使わない)。"""
    obs = _observed((P1, 2.0), (P2, 1.5), noise=0.5, seed=7)
    r1 = identify_pattern(_TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG)
    r2 = identify_pattern(_TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG)
    assert r1.phase_ids == r2.phase_ids
    assert [a.scale for a in r1.accepted] == [a.scale for a in r2.accepted]


def test_pure_noise_with_background_slope_accepts_nothing():
    """相の実体がなく背景の緩勾配+ノイズだけなら 0 相 (decoy を作らない)。"""
    slope = 0.05 * (_TT - _TT.min())
    rng = np.random.default_rng(3)
    obs = np.clip(rng.normal(20.0, 3.0, _TT.size) + slope, 0, None)
    res = identify_pattern(_TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG)
    assert res.phase_ids == ()


# ---------------------------------------------------------------------------
# 3. FWHM 不一致 (プロファイル形状のミスマッチ)
# ---------------------------------------------------------------------------

def test_broader_actual_fwhm_still_accepted():
    """観測相の実 FWHM がフィット固定 fwhm (0.15) より広くても (mild mismatch) 受理される。"""
    obs = _observed((P1, 2.0), (P2, 1.5), fwhm=0.28)
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res.phase_ids) == {"mp-P1", "mp-P2"}


def test_narrower_actual_fwhm_still_accepted():
    """観測相の実 FWHM がフィット固定 fwhm より狭くても受理される。"""
    obs = _observed((P1, 2.0), (P2, 1.5), fwhm=0.08)
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res.phase_ids) == {"mp-P1", "mp-P2"}


def test_severe_fwhm_mismatch_does_not_crash_and_is_conservative():
    """極端な FWHM 不一致 (フィット比の 4 倍超) では受理が保守的になってもよいが、
    クラッシュせず decoy を作らない (余分な相を誤って受理しない) ことを保証する。
    """
    obs = _observed((P1, 2.0), (P2, 1.5), fwhm=0.6)
    res = identify_pattern(
        _TT, obs, _Prov([P1, P2, P3, P4]), elements=["Ca", "C", "O"], cfg=CFG
    )
    assert set(res.phase_ids).issubset({"mp-P1", "mp-P2"})
    assert "mp-P3" not in res.phase_ids
    assert "mp-P4" not in res.phase_ids


# ---------------------------------------------------------------------------
# 4. refiner 深段: 複数多形グループの判別 + フォールバック
# ---------------------------------------------------------------------------

# グループ1: CaCO3 多形 (peak-search で同一ピーク = 判別不可)。
# 同点タイブレークは phase_id 昇順 (engine.py) なので、"peak-space が誤って先に選ぶ" 側の
# id を辞書順で先に来るよう "a"-prefix にし、正解側は "z"-prefix にする (命名で結果を作らない)。
CACO3_WRONG = _phase("caco3-a-decoy", [20.0, 30.0, 45.0], formula="CaCO3")
CACO3_RIGHT = _phase("caco3-z-true", [20.0, 30.0, 45.0], formula="CaCO3")

# グループ2: TiO2 多形 (別ピーク位置帯・同一組成で同じ状況を再現)
TIO2_WRONG = _phase("tio2-a-decoy", [26.0, 37.0, 55.0], formula="TiO2")
TIO2_RIGHT = _phase("tio2-z-true", [26.0, 37.0, 55.0], formula="TiO2")


def _multi_group_refiner(refs):
    """caco3-z-true と tio2-z-true の両方が入っている組合せのみ低 Rwp を返すスタブ。"""
    ids = {r.phase_id for r in refs}
    rwp = 10.0
    if "caco3-a-decoy" in ids:
        rwp += 15.0
    if "tio2-a-decoy" in ids:
        rwp += 15.0
    return rwp


def test_refiner_discriminates_polymorphs_across_multiple_groups():
    """CaCO3 と TiO2、2 つの多形グループそれぞれで peak-search が誤った側を選んでも、
    注入 refiner が両グループ独立に正しい多形へ swap する。
    """
    obs = _observed((CACO3_WRONG, 2.0), (TIO2_WRONG, 1.5))
    provider = _Prov([CACO3_WRONG, CACO3_RIGHT, TIO2_WRONG, TIO2_RIGHT])
    cfg = IdentifyConfig(polymorph_margin=0.5, snr_stop=8.0, eps_gain=0.02, max_phases=5)
    res = identify_pattern(
        _TT, obs, provider, elements=["Ca", "C", "O", "Ti"],
        refiner=_multi_group_refiner, cfg=cfg,
    )
    assert res.refined is True
    assert "caco3-z-true" in res.phase_ids
    assert "tio2-z-true" in res.phase_ids
    assert "caco3-a-decoy" not in res.phase_ids
    assert "tio2-a-decoy" not in res.phase_ids


def test_refiner_only_swaps_the_group_that_needs_it():
    """一方のグループ (TiO2) が既に正しい多形で受理されている場合、
    そちらは swap されず、誤った CaCO3 のみが訂正される。
    """
    obs = _observed((CACO3_WRONG, 2.0), (TIO2_RIGHT, 1.5))
    provider = _Prov([CACO3_WRONG, CACO3_RIGHT, TIO2_WRONG, TIO2_RIGHT])
    cfg = IdentifyConfig(polymorph_margin=0.5, snr_stop=8.0, eps_gain=0.02, max_phases=5)
    res = identify_pattern(
        _TT, obs, provider, elements=["Ca", "C", "O", "Ti"],
        refiner=_multi_group_refiner, cfg=cfg,
    )
    assert "caco3-z-true" in res.phase_ids
    assert "tio2-z-true" in res.phase_ids
    assert "caco3-a-decoy" not in res.phase_ids


def test_failing_refiner_falls_back_to_peak_space_result():
    """refiner が例外を送出する場合、深段裁定は安全にフォールバックし、
    peak-space (高速段) の受理結果をそのまま返す (クラッシュしない・提案≠適用)。
    """

    def _raising_refiner(refs):
        raise RuntimeError("GSAS backend unavailable")

    obs = _observed((CACO3_WRONG, 2.0), (TIO2_WRONG, 1.5))
    provider = _Prov([CACO3_WRONG, CACO3_RIGHT, TIO2_WRONG, TIO2_RIGHT])
    cfg = IdentifyConfig(polymorph_margin=0.5, snr_stop=8.0, eps_gain=0.02, max_phases=5)
    res = identify_pattern(
        _TT, obs, provider, elements=["Ca", "C", "O", "Ti"],
        refiner=_raising_refiner, cfg=cfg,
    )
    # フォールバック: refined=False (何も改善できなかった) だが結果は返る。
    assert res.refined is False
    assert len(res.accepted) >= 1
    assert res.ledger is not None and res.ledger.verify()


def test_partially_failing_refiner_still_applies_successful_swaps():
    """refiner が特定の相集合でのみ例外を送出しても、他の (成功する) swap 判定は活きる。"""

    def _flaky_refiner(refs):
        ids = {r.phase_id for r in refs}
        if "tio2-a-decoy" in ids and "tio2-z-true" not in ids:
            raise RuntimeError("boom on this combination")
        return _multi_group_refiner(refs)

    obs = _observed((CACO3_WRONG, 2.0), (TIO2_WRONG, 1.5))
    provider = _Prov([CACO3_WRONG, CACO3_RIGHT, TIO2_WRONG, TIO2_RIGHT])
    cfg = IdentifyConfig(polymorph_margin=0.5, snr_stop=8.0, eps_gain=0.02, max_phases=5)
    res = identify_pattern(
        _TT, obs, provider, elements=["Ca", "C", "O", "Ti"],
        refiner=_flaky_refiner, cfg=cfg,
    )
    # CaCO3 は refiner が正常評価できるので訂正されるはず。
    assert "caco3-z-true" in res.phase_ids
    assert res.ledger is not None and res.ledger.verify()


def test_refiner_swap_is_deterministic():
    """多形 swap 判定も決定論 (同一入力→同一出力)。"""
    obs = _observed((CACO3_WRONG, 2.0), (TIO2_WRONG, 1.5))
    provider = _Prov([CACO3_WRONG, CACO3_RIGHT, TIO2_WRONG, TIO2_RIGHT])
    cfg = IdentifyConfig(polymorph_margin=0.5, snr_stop=8.0, eps_gain=0.02, max_phases=5)
    r1 = identify_pattern(
        _TT, obs, provider, elements=["Ca", "C", "O", "Ti"],
        refiner=_multi_group_refiner, cfg=cfg,
    )
    r2 = identify_pattern(
        _TT, obs, provider, elements=["Ca", "C", "O", "Ti"],
        refiner=_multi_group_refiner, cfg=cfg,
    )
    assert r1.phase_ids == r2.phase_ids
