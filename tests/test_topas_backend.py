"""M12 T9: `TopasBackend` — `RefinementBackend` Protocol の TOPAS 実装。

`tests/test_gsasii_backend.py` と**対の並行スイート**。両バックエンドが同じ契約を満たすことを
別々に検証する (共有 contract test を持たないのが既存の作法)。

**なぜ必要か**: 実構造の多仮説探索は `AutoRietveldBackend(runner=…)` に TOPAS runner を渡せば
既に成立するが、`search.tree` / `sequential.engine` は `simulate()` を要求する。そこだけが
TOPAS で塞がっていた (#175)。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.backends.base import RefinementBackend, RefinementModel, param_name
from tsumugin.backends.topas import TopasBackend
from tsumugin.errors import TopasUnavailableError
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.topas.availability import topas_available


def _phase(a: float = 4.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(20.0, 80.0, 0.05)


# ---------------- 可用性 / 契約 (TOPAS 非依存) ----------------


def test_backend_raises_when_unavailable(monkeypatch):
    """未導入環境では構築時に落とす (GSAS 側と同じ縮退)。"""
    monkeypatch.setenv("TSUMUGIN_TOPAS_PATH", "none")
    with pytest.raises(TopasUnavailableError):
        TopasBackend()


def test_backend_satisfies_the_protocol():
    """`RefinementBackend` は runtime_checkable な構造的 Protocol。"""
    assert isinstance(TopasBackend, type)
    assert hasattr(TopasBackend, "refine") and hasattr(TopasBackend, "simulate")


def test_backend_name_identifies_the_engine():
    """**Rwp/BIC を跨いで比較するときの前提**なので名前が要る。"""
    assert TopasBackend.name == "topas"


# ---------------- 実 tc.exe ----------------


@pytest.mark.topas
def test_instance_is_a_refinement_backend():
    assert isinstance(TopasBackend(), RefinementBackend)


@pytest.mark.topas
def test_simulate_produces_nontrivial_pattern():
    backend = TopasBackend()
    tt = _grid()
    y = backend.simulate((_phase(a=4.0, scale=1.0),), tt)
    assert y.shape == tt.shape
    assert np.all(np.isfinite(y))
    # 回折ピークが平坦な背景から十分に立ち上がっていること
    assert y.max() > 5 * max(float(np.median(y)), 1e-9)


@pytest.mark.topas
def test_simulate_is_deterministic():
    """NFR-102: 同じ入力からビット同一 (Ycalc を使い観測ノイズを混ぜない)。"""
    backend = TopasBackend()
    tt = _grid()
    a = backend.simulate((_phase(),), tt)
    b = backend.simulate((_phase(),), tt)
    assert np.array_equal(a, b)


@pytest.mark.topas
def test_simulate_tracks_the_lattice():
    """格子を変えるとピーク位置が動くこと (格子が前方計算に効いている証拠)。"""
    backend = TopasBackend()
    tt = _grid()
    small = backend.simulate((_phase(a=4.0),), tt)
    large = backend.simulate((_phase(a=4.2),), tt)
    assert int(np.argmax(small)) != int(np.argmax(large))


@pytest.mark.topas
def test_refine_with_nothing_free_reports_zero_params():
    backend = TopasBackend()
    tt = _grid()
    truth = _phase()
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(phases=(truth,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.n_params == 0
    assert result.n_obs == tt.size
    assert result.rwp >= 0.0


@pytest.mark.topas
def test_refine_scale_improves_fit():
    """スケールを解放すると、ずらした初期値から真値へ戻ること。"""
    backend = TopasBackend()
    tt = _grid()
    truth = _phase(scale=1.0)
    y = backend.simulate((truth,), tt)
    start = _phase(scale=0.5)
    before = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    after = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "scale")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert after.rwp < before.rwp
    assert after.n_params >= 1


@pytest.mark.topas
def test_rwp_is_on_the_same_scale_as_the_gsas_backend():
    """**バックエンド間で rwp/chi2 の意味を揃える** (不変条件: BIC 比較の一貫性)。

    ``rwp = 100·√(Σw(yo−yc)² / Σw·yo²)``。TOPAS の ``r_wp_dash`` は背景差引きで非互換なので
    使わない — ここでは残差から自前で計算し、定義のずれを持ち込まない。
    """
    backend = TopasBackend()
    tt = _grid()
    truth = _phase()
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(phases=(truth,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    expected = 100.0 * np.sqrt(result.chi2 / float(np.sum(y**2)))
    assert result.rwp == pytest.approx(expected, rel=1e-6)


@pytest.mark.topas
def test_backend_failure_becomes_infinite_chi2_not_an_exception():
    """**不変条件**: バックエンドの失敗は例外でなく chi2=inf に変換する。"""
    backend = TopasBackend()
    tt = _grid()
    # 格子 0 は INP としては書けるが物理的に成立しない → tc.exe が落ちる。
    broken = PhaseInstance(phase_ref="P", lattice=LatticeParams(0.0, 0.0, 0.0), scale=1.0)
    result = backend.refine(
        RefinementModel(
            phases=(broken,), free_params=frozenset(), two_theta=tt, intensity=np.ones_like(tt)
        )
    )
    assert np.isinf(result.chi2) and np.isinf(result.rwp)
    assert result.converged is False


@pytest.mark.topas
def test_failure_strips_stale_lattice_sigma():
    """失敗結果に**古い σ を残さない** — chi2=inf の仮説に σ が付いて見えるため (GSAS 側と同じ)。"""
    backend = TopasBackend()
    tt = _grid()
    lattice = LatticeParams(
        0.0, 0.0, 0.0, sigma={"a": 0.01}, sigma_source="covariance"
    )
    broken = PhaseInstance(phase_ref="P", lattice=lattice, scale=1.0)
    result = backend.refine(
        RefinementModel(
            phases=(broken,), free_params=frozenset(), two_theta=tt, intensity=np.ones_like(tt)
        )
    )
    assert result.phases[0].lattice.sigma == {}
    assert result.phases[0].lattice.sigma_source == ""


@pytest.mark.topas
def test_unknown_parameter_suffixes_are_ignored():
    """未対応 suffix は黙って無視する (GSAS 版と同挙動 — 探索側が広い語彙を投げてくる)。"""
    backend = TopasBackend()
    tt = _grid()
    truth = _phase()
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(
            phases=(truth,),
            free_params=frozenset({param_name(0, "texture.march")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert result.n_params == 0


def test_availability_helper_is_consistent_with_the_module():
    """`topas_available()` と構築可否が食い違わないこと。"""
    if topas_available():
        TopasBackend()  # 例外を出さない
    else:
        with pytest.raises(TopasUnavailableError):
            TopasBackend()
