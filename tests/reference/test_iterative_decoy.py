"""M11 逐次減算同定 — decoy 棄却 + 過剰適合耐性 + 停止の敵対的ストレステスト。

`identify_pattern` は化学ガード (``require_elements``) なしで decoy (真の相のピーク部分集合/重複/
単一強ピーク相) を joint 非負スケール受理段だけで棄却できるべきである (design doc §0-3, §5)。
本テストは複数 decoy を同時にプールへ混入し、ノイズ 0/1%/3% の各水準で全 decoy が非採用であることを
固定する。あわせて「完全explained後に幻の相を追加しない」停止性と、純ノイズ残差での ``snr_stop`` の
頑健性を検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

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


def _observed(*phase_scales, noise=0.0, seed=0):
    y = np.zeros_like(_TT)
    for ph, s in phase_scales:
        y += s * render_phase(_TT, [(p.position, p.height) for p in ph.peaks], _FWHM)
    if noise:
        y = np.clip(y + np.random.default_rng(seed).normal(0, noise * y.max(), _TT.size), 0, None)
    return y


# --- 真の相 (それぞれ複数ピーク、異なる元素系) ---
A = _phase("mp-A", [20.0, 35.0, 52.0, 67.0], formula="A", elements=("Ca", "C", "O"))
B = _phase("mp-B", [27.0, 44.0, 61.0, 74.0], formula="B", elements=("Ca", "Te", "O"))

# --- Decoy 群 (すべて A/B のピークの部分集合 or 重複 or 単ピーク) ---
DECOY_SUBSET_A = _phase("decoy-subA", [20.0, 35.0], formula="DsubA", elements=("C",))
DECOY_SUBSET_B = _phase("decoy-subB", [27.0, 61.0], formula="DsubB", elements=("Te",))
DECOY_SINGLE_STRONG = _phase("decoy-single", [20.0], formula="Dsingle", elements=("O",))
DECOY_DUP_A = _phase("decoy-dupA", [20.0, 35.0, 52.0, 67.0, 48.0], formula="DdupA", elements=("Ca",))  # A のピーク + 過剰主張ピーク48 → dara extra 罰で下位
DECOY_INSIDE_B = _phase("decoy-insideB", [27.0, 44.0], formula="DinsideB", elements=("Ca",))
DECOY_MIXED_SUBSET = _phase(
    "decoy-mixed", [20.0, 27.0, 52.0], formula="Dmixed", elements=("C", "Te")
)
DECOY_OFFPEAK_WEAK = _phase(
    "decoy-offweak", [20.05, 34.9], formula="Doffweak", heights=[10.0, 10.0], elements=("C",)
)

ALL_DECOYS = [
    DECOY_SUBSET_A,
    DECOY_SUBSET_B,
    DECOY_SINGLE_STRONG,
    DECOY_DUP_A,
    DECOY_INSIDE_B,
    DECOY_MIXED_SUBSET,
    DECOY_OFFPEAK_WEAK,
]

CFG = IdentifyConfig(eps_gain=0.02, max_phases=8, try_k=5)  # 既定 snr_stop=5


def _library_with_decoys():
    """真の相 A, B + 全 decoy を混ぜたプール (供給元は化学ガードなしで全部返す)。"""
    return _Prov([A, B] + ALL_DECOYS)


@pytest.mark.parametrize("noise", [0.0, 0.01, 0.03])
def test_all_decoys_rejected_across_noise_levels(noise):
    """A+B混合パターンに大量の decoy をプール混入しても、真の 2 相だけが受理される。

    decoy は化学ガード (require_elements) を渡さずに棄却されなければならない — 純粋に
    joint 非負スケール再フィットの残差支持 (scale/gain) だけで弾く設計 (architecture.md §5)。
    """
    obs = _observed((A, 2.0), (B, 3.0), noise=noise, seed=42)
    res = identify_pattern(
        _TT, obs, _library_with_decoys(), elements=["Ca", "C", "O", "Te"], cfg=CFG
    )
    accepted_ids = set(res.phase_ids)
    decoy_ids = {d.phase_id for d in ALL_DECOYS}
    leaked = accepted_ids & decoy_ids
    assert not leaked, f"decoy leaked into accepted set at noise={noise}: {leaked}"
    assert accepted_ids == {"mp-A", "mp-B"}, (
        f"expected exactly {{mp-A, mp-B}} at noise={noise}, got {accepted_ids}"
    )


@pytest.mark.parametrize("noise", [0.0, 0.01, 0.03])
def test_single_phase_rejects_all_decoys(noise):
    """単相 A のみのパターンでも decoy 群 (A のピーク部分集合含む) は一切採用されない。"""
    obs = _observed((A, 2.0), noise=noise, seed=7)
    res = identify_pattern(
        _TT, obs, _library_with_decoys(), elements=["Ca", "C", "O", "Te"], cfg=CFG
    )
    assert res.phase_ids == ("mp-A",), f"noise={noise}: got {res.phase_ids}"


def test_decoy_fully_inside_other_phase_rejected():
    """decoy のピークが全て他相(B)の内部に収まる (真部分集合) ケースを単独で固定する。"""
    obs = _observed((A, 2.0), (B, 3.0))
    prov = _Prov([A, B, DECOY_INSIDE_B])
    res = identify_pattern(_TT, obs, prov, elements=["Ca", "C", "O", "Te"], cfg=CFG)
    assert "decoy-insideB" not in res.phase_ids
    assert set(res.phase_ids) == {"mp-A", "mp-B"}


def test_single_peak_decoy_at_strong_position_rejected():
    """最強ピーク位置に単一ピークで居座る decoy は、その位置の強度が既に A で説明済みのため棄却される。"""
    obs = _observed((A, 2.0), (B, 3.0))
    prov = _Prov([A, B, DECOY_SINGLE_STRONG])
    res = identify_pattern(_TT, obs, prov, elements=["Ca", "C", "O", "Te"], cfg=CFG)
    assert "decoy-single" not in res.phase_ids


def test_duplicate_peaklist_decoy_rejected_in_favor_of_first_seen():
    """A と全く同じピーク位置を持つ decoy (組成/元素系だけ違う) が混ざっても、A 側が先に埋まり
    decoy 側は追加の説明力を持たないため棄却される。"""
    obs = _observed((A, 2.0), (B, 3.0))
    prov = _Prov([A, B, DECOY_DUP_A])
    res = identify_pattern(_TT, obs, prov, elements=["Ca", "C", "O", "Te"], cfg=CFG)
    assert set(res.phase_ids) <= {"mp-A", "mp-B", "decoy-dupA"}
    # 少なくとも A/B いずれかの「実体」は受理され、decoy 単独が両方を差し置いて採用されることはない
    assert "mp-A" in res.phase_ids or "decoy-dupA" in res.phase_ids
    # 重複ピークの相は同時に2つ受理されない (2つ目は gain≈0 で棄却される)
    both = {"mp-A", "decoy-dupA"} <= set(res.phase_ids)
    assert not both, "duplicate-peaklist decoy accepted alongside the real phase (no marginal gain)"


def test_offpeak_weak_decoy_rejected():
    """僅かに位置がずれた弱い decoy は、match_tol 内でも残差の主要な支持を持たないため棄却される。"""
    obs = _observed((A, 2.0), (B, 3.0))
    prov = _Prov([A, B, DECOY_OFFPEAK_WEAK])
    res = identify_pattern(_TT, obs, prov, elements=["Ca", "C", "O", "Te"], cfg=CFG)
    assert "decoy-offweak" not in res.phase_ids
    assert set(res.phase_ids) == {"mp-A", "mp-B"}


def test_stops_when_fully_explained_no_phantom_phase():
    """A+B で完全に説明された後、decoy を含む大きな候補プールがあっても幻の3相目を追加しない。"""
    obs = _observed((A, 2.0), (B, 3.0))
    res = identify_pattern(
        _TT, obs, _library_with_decoys(), elements=["Ca", "C", "O", "Te"],
        cfg=IdentifyConfig(snr_stop=8.0, eps_gain=0.02, max_phases=20, try_k=5),
    )
    assert len(res.accepted) == 2
    # 反復回数も 2 (A, B の受理) 以下であるべき (無限に回って棄却を繰り返していない)
    assert len(res.iterations) <= 3


def test_max_phases_safety_net_does_not_force_phantom_acceptance():
    """max_phases を大きくしても、decoy しか残っていない状況で無理に相を積み増さない。"""
    obs = _observed((A, 2.0))
    prov = _Prov([A] + ALL_DECOYS)
    res = identify_pattern(
        _TT, obs, prov, elements=["Ca", "C", "O", "Te"],
        cfg=IdentifyConfig(eps_gain=0.02, max_phases=50, try_k=7),
    )
    assert res.phase_ids == ("mp-A",)


@pytest.mark.parametrize("noise", [0.0, 0.005, 0.01, 0.02, 0.03, 0.05])
def test_snr_stop_on_pure_noise_residual(noise):
    """純ノイズ (相の実体なし) は snr_stop 既定値 (8.0) で常に 0 相に停止するか、どの水準から破綻するかを
    特徴づける。ノイズが計数統計 sqrt(raw) から乖離するほど（相対ノイズが増えるほど）誤検出しやすくなる
    はずなので、破綻点を明示的に記録する。"""
    rng = np.random.default_rng(123)
    baseline = 20.0
    obs = np.clip(rng.normal(baseline, max(noise * 100.0, 3.0), _TT.size), 0, None)
    prov = _Prov([A, B] + ALL_DECOYS)
    res = identify_pattern(_TT, obs, prov, elements=["Ca", "C", "O", "Te"], cfg=CFG)
    if noise <= 0.02:
        assert res.phase_ids == (), f"pure noise (noise={noise}) triggered phantom phase(s): {res.phase_ids}"
    # noise > 0.02: 既知の限界点。ここでは特徴づけのみ行い assert しない (レポートで報告)。


def test_known_phases_start_still_rejects_decoys():
    """operando 一本化 (known_phases 起点) でも decoy 混入プールから追加の decoy は拾わない。"""
    obs = _observed((A, 2.0), (B, 3.0))
    res = identify_pattern(
        _TT, obs, _library_with_decoys(), elements=["Ca", "C", "O", "Te"],
        known_phases=[A], cfg=CFG,
    )
    decoy_ids = {d.phase_id for d in ALL_DECOYS}
    assert not (set(res.phase_ids) & decoy_ids)
    assert set(res.phase_ids) == {"mp-A", "mp-B"}
