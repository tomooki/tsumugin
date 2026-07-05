"""M6 TASK-0105 多相同定 (HypothesisTreeSearch 接続) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/mixture.py`` (未実装)。
`ReferenceBackend` (RefinementBackend + simulate: 参照相ピーク供給) と
`identify_phase_mixtures(two_theta, intensity, provider, *, elements, ...)` を検証する。
コアは numpy のみ (既存 search.tree を再利用)。合成ピークで pymatgen 非依存に検証。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
import pytest

from tsumugin.backends.base import RefinementBackend, RefinementModel
from tsumugin.reference.mixture import ReferenceBackend, identify_phase_mixtures
from tsumugin.reference.model import ReferencePhase
from tsumugin.search.peaks import Peak
from tsumugin.search.tree import SearchConfig, SearchResult


class FakeProvider:
    def __init__(self, phases: Sequence[ReferencePhase]) -> None:
        self._phases = tuple(phases)

    def fetch(self, elements: Sequence[str]) -> Sequence[ReferencePhase]:
        return self._phases


def _ref(phase_id, positions, *, elements=("Fe", "O"), ehull=0.0):
    return ReferencePhase(
        phase_id=phase_id,
        formula="X",
        element_system=tuple(sorted(elements)),
        peaks=tuple(Peak(position=p, height=1.0) for p in positions),
        energy_above_hull=ehull,
    )


def _grid():
    return np.arange(15.0, 60.0, 0.02)


def _pattern(peak_specs, *, fwhm=0.15):
    """(2θ, 強度): 指定 (位置, 高さ) にガウシアンを重ねた合成パターン。"""
    tt = _grid()
    y = np.zeros_like(tt)
    sigma = fwhm / 2.3548
    for pos, h in peak_specs:
        y += h * np.exp(-0.5 * ((tt - pos) / sigma) ** 2)
    return tt, y


# --- ReferenceBackend ------------------------------------------------------


def test_reference_backend_conforms_to_protocol():
    backend = ReferenceBackend({"a": (Peak(20.0, 1.0),)})
    assert isinstance(backend, RefinementBackend)
    assert isinstance(backend.name, str)


def test_simulate_renders_peaks_as_gaussians():
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = ReferenceBackend({"a": (Peak(20.0, 1.0), Peak(30.0, 0.5))})
    phase = PhaseInstance(phase_ref="a", lattice=LatticeParams(1.0, 1.0, 1.0))
    tt = _grid()
    y = backend.simulate([phase], tt)
    assert y.shape == tt.shape
    # ピーク位置近傍で極大、height 比が反映される
    i20 = int(np.argmin(np.abs(tt - 20.0)))
    i30 = int(np.argmin(np.abs(tt - 30.0)))
    assert y[i20] > 0.5
    assert y[i20] > y[i30]  # height 1.0 > 0.5


def test_simulate_scales_by_phase_scale():
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = ReferenceBackend({"a": (Peak(20.0, 1.0),)})
    tt = _grid()
    p1 = PhaseInstance(phase_ref="a", lattice=LatticeParams(1.0, 1.0, 1.0), scale=1.0)
    p2 = PhaseInstance(phase_ref="a", lattice=LatticeParams(1.0, 1.0, 1.0), scale=2.0)
    y1 = backend.simulate([p1], tt)
    y2 = backend.simulate([p2], tt)
    assert np.allclose(y2, 2.0 * y1)


def test_refine_fits_scale_and_returns_finite_chi2():
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = ReferenceBackend({"a": (Peak(25.0, 1.0), Peak(45.0, 1.0))})
    tt, y = _pattern([(25.0, 3.0), (45.0, 3.0)])  # 真のスケール ≈ 3
    phase = PhaseInstance(phase_ref="a", lattice=LatticeParams(1.0, 1.0, 1.0), scale=1.0)
    model = RefinementModel(
        phases=(phase,),
        free_params=frozenset({"phase0.scale"}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert np.isfinite(result.chi2)
    assert result.n_params == 1
    assert result.phases[0].scale > 1.5  # スケールが真値方向へフィット


def test_refine_two_phase_better_than_one():
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = ReferenceBackend({
        "a": (Peak(20.0, 1.0), Peak(40.0, 1.0)),
        "b": (Peak(30.0, 1.0), Peak(50.0, 1.0)),
    })
    tt, y = _pattern([(20.0, 2.0), (40.0, 2.0), (30.0, 2.0), (50.0, 2.0)])
    lat = LatticeParams(1.0, 1.0, 1.0)
    pa = PhaseInstance(phase_ref="a", lattice=lat)
    pb = PhaseInstance(phase_ref="b", lattice=lat)
    model_one = RefinementModel(phases=(pa,), free_params=frozenset({"phase0.scale"}),
                                two_theta=tt, intensity=y)
    model_two = RefinementModel(phases=(pa, pb),
                                free_params=frozenset({"phase0.scale", "phase1.scale"}),
                                two_theta=tt, intensity=y)
    r_one = backend.refine(model_one)
    r_two = backend.refine(model_two)
    assert r_two.rwp < r_one.rwp  # 2 相の方が観測をよく説明


def test_refine_zero_phases_returns_full_residual():
    # 相なしは観測全体が残差。例外化せず n_params=0 の結果を返す (EDGE 縮退)
    backend = ReferenceBackend({})
    tt, y = _pattern([(25.0, 2.0)])
    model = RefinementModel(phases=(), free_params=frozenset(), two_theta=tt, intensity=y)
    result = backend.refine(model)
    assert result.n_params == 0
    assert result.phases == ()
    assert np.isfinite(result.chi2)
    assert result.rwp > 0.0  # 何も当てていないので残差大


def test_refine_flat_zero_pattern_rwp_zero():
    # 全ゼロ観測 (den<=0) は rwp=0.0 へ安全に縮退する
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = ReferenceBackend({"a": (Peak(25.0, 1.0),)})
    tt = _grid()
    y = np.zeros_like(tt)
    phase = PhaseInstance(phase_ref="a", lattice=LatticeParams(1.0, 1.0, 1.0))
    model = RefinementModel(phases=(phase,), free_params=frozenset({"phase0.scale"}),
                            two_theta=tt, intensity=y)
    result = backend.refine(model)
    assert result.rwp == 0.0


def test_refine_is_deterministic():
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = ReferenceBackend({"a": (Peak(25.0, 1.0),)})
    tt, y = _pattern([(25.0, 2.0)])
    phase = PhaseInstance(phase_ref="a", lattice=LatticeParams(1.0, 1.0, 1.0))
    model = RefinementModel(phases=(phase,), free_params=frozenset({"phase0.scale"}),
                            two_theta=tt, intensity=y)
    r1 = backend.refine(model)
    r2 = backend.refine(model)
    assert r1.chi2 == r2.chi2
    assert r1.rwp == r2.rwp


# --- identify_phase_mixtures -----------------------------------------------


def test_returns_search_result():
    tt, y = _pattern([(20.0, 1.0), (30.0, 1.0)])
    prov = FakeProvider([_ref("mp-1", [20.0, 30.0])])
    result = identify_phase_mixtures(tt, y, prov, elements=["Fe", "O"])
    assert isinstance(result, SearchResult)


def test_two_phase_mixture_identified():
    # 観測 = A(20,40) + B(30,50)。最良仮説は両相を含むべき
    tt, y = _pattern([(20.0, 1.0), (40.0, 1.0), (30.0, 1.0), (50.0, 1.0)])
    prov = FakeProvider([
        _ref("mp-A", [20.0, 40.0]),
        _ref("mp-B", [30.0, 50.0]),
    ])
    result = identify_phase_mixtures(tt, y, prov, elements=["Fe", "O"])
    top_phase_ids = {p.phase_ref for p in result.ranked[0].hypothesis.phases}
    assert top_phase_ids == {"mp-A", "mp-B"}


def test_single_phase_pattern_ranks_single_phase():
    tt, y = _pattern([(20.0, 1.0), (40.0, 1.0)])
    prov = FakeProvider([
        _ref("mp-A", [20.0, 40.0]),
        _ref("mp-B", [30.0, 50.0]),
    ])
    result = identify_phase_mixtures(tt, y, prov, elements=["Fe", "O"])
    top = result.ranked[0].hypothesis
    assert [p.phase_ref for p in top.phases] == ["mp-A"]


def test_element_and_hull_filter_applied():
    tt, y = _pattern([(20.0, 1.0)])
    prov = FakeProvider([
        _ref("mp-ok", [20.0], elements=("Fe", "O"), ehull=0.0),
        _ref("mp-foreign", [20.0], elements=("Fe", "O", "Ni"), ehull=0.0),
        _ref("mp-unstable", [20.0], elements=("Fe", "O"), ehull=0.5),
    ])
    result = identify_phase_mixtures(tt, y, prov, elements=["Fe", "O"], hull_cutoff_ev=0.1)
    all_ids = {p.phase_ref for rk in result.ranked for p in rk.hypothesis.phases}
    assert "mp-foreign" not in all_ids
    assert "mp-unstable" not in all_ids
    assert "mp-ok" in all_ids


def test_empty_candidates_returns_empty_result():
    tt, y = _pattern([(20.0, 1.0)])
    prov = FakeProvider([_ref("mp-x", [20.0], elements=("Ni",))])  # 元素系フィルタで全滅
    result = identify_phase_mixtures(tt, y, prov, elements=["Fe", "O"])
    assert result.ranked == ()


def test_empty_elements_raises():
    tt, y = _pattern([(20.0, 1.0)])
    prov = FakeProvider([])
    with pytest.raises(ValueError):
        identify_phase_mixtures(tt, y, prov, elements=[])


def test_mixtures_accepts_preprocessing_options():
    # subtract_bg + kalpha2 を渡しても SearchResult を返す (前処理配線の疎通)
    from tsumugin.reference.kalpha import KAlpha2

    tt, y = _pattern([(20.0, 1.0), (40.0, 1.0)])
    y = y + 30.0  # 一定背景を足す
    prov = FakeProvider([_ref("mp-A", [20.0, 40.0])])
    result = identify_phase_mixtures(
        tt, y, prov, elements=["Fe", "O"], subtract_bg=True, kalpha2=KAlpha2()
    )
    assert isinstance(result, SearchResult)
    assert result.ranked  # 背景減算後も相が同定される


def test_prefilter_top_k_limits_candidates():
    # Dara 事前フィルタ: 多数候補から上位 k のみ木探索へ。無関係相は除かれる
    tt, y = _pattern([(20.0, 1.0), (40.0, 1.0)])
    good = _ref("mp-good", [20.0, 40.0])
    junk1 = _ref("mp-junk1", [55.0, 58.0])
    junk2 = _ref("mp-junk2", [12.0, 15.0])
    prov = FakeProvider([junk1, good, junk2])
    result = identify_phase_mixtures(
        tt, y, prov, elements=["Fe", "O"], prefilter_top_k=1
    )
    all_ids = {p.phase_ref for rk in result.ranked for p in rk.hypothesis.phases}
    assert all_ids == {"mp-good"}  # 上位 1 = good のみが探索対象


def test_refine_lattice_absorbs_offset_in_mixture():
    # refine_lattice: DFT 格子ズレ相当の位置オフセットを吸収して混合を検出する
    from tsumugin.reference.rietveld import align_peaks  # noqa: F401 (整合ロジックの存在確認)

    # A(20,40), B(30,50) の混合。参照は 0.3° ずれた位置 (格子ズレ相当)
    tt, y = _pattern([(20.0, 1.0), (40.0, 1.0), (30.0, 1.0), (50.0, 1.0)])
    a = _ref("mp-A", [20.3, 40.3])   # +0.3° ずれ
    b = _ref("mp-B", [30.3, 50.3])
    prov = FakeProvider([a, b])
    # 整合なし: 0.3° ずれで木探索のマッチ許容 (0.15) を外れ検出が不安定
    with_align = identify_phase_mixtures(
        tt, y, prov, elements=["Fe", "O"], refine_lattice=True,
        config=SearchConfig(max_phases=2),
    )
    top_ids = {p.phase_ref for p in with_align.ranked[0].hypothesis.phases}
    assert top_ids == {"mp-A", "mp-B"}  # 格子整合で両相を同定


def test_max_phases_config_respected():
    tt, y = _pattern([(20.0, 1.0), (30.0, 1.0), (40.0, 1.0)])
    prov = FakeProvider([
        _ref("mp-A", [20.0]),
        _ref("mp-B", [30.0]),
        _ref("mp-C", [40.0]),
    ])
    result = identify_phase_mixtures(
        tt, y, prov, elements=["Fe", "O"], config=SearchConfig(max_phases=2)
    )
    for rk in result.ranked:
        assert len(rk.hypothesis.phases) <= 2
