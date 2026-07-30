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


# ---------------- 相ごとの解放 (多相) ----------------


def _document_for(free_params, n_phases=2):
    """`_document` は純関数 (tc.exe 不要) — 生成される INP を直接見る。"""
    import numpy as _np

    backend = TopasBackend.__new__(TopasBackend)  # __init__ の可用性検査を迂回
    backend.wavelength = 1.5406
    phases = tuple(_phase(a=4.0 + i, ref=f"P{i}") for i in range(n_phases))
    scale_free, cell_free = TopasBackend._recognized(frozenset(free_params), n_phases)
    import tempfile as _tempfile
    from pathlib import Path as _Path

    with _tempfile.TemporaryDirectory() as tmp:
        work = _Path(tmp)
        grid = _np.arange(20.0, 30.0, 0.05)
        from tsumugin.topas.instrument import write_xye

        write_xye(work / "obs.xye", grid, _np.ones_like(grid))
        doc = backend._document(
            phases, work, cell_free=cell_free, scale_free=tuple(scale_free), max_cyc=5
        )
        return doc.render(), scale_free, cell_free


def test_lattice_is_released_only_for_the_requested_phase():
    """**相ごとの指定が潰れない**こと。

    `free_params={"phase1.lattice.a"}` で相 0 の格子まで解放すると、要求していない相が
    黙って動いて相 1 のフィットと相関する。しかも `_read_back` は要求分しか読み戻さないので
    **TOPAS が実際に動かした値と結果が食い違う**。
    """
    text, _, cell_free = _document_for({param_name(1, "lattice.a")})
    assert cell_free == {1}
    assert "a !phase0_a" in text, "相 0 の格子が解放されている"
    assert "a phase1_a" in text, "相 1 の格子が解放されていない"


def test_n_params_counts_what_is_actually_free():
    """**BIC 比較の一貫性**が壊れないこと (母数を過少申告しない)。

    `n_params` が実際に解放した数と食い違うと、仮説間の BIC/AIC が意味を失う。
    """
    text, scale_free, cell_free = _document_for({param_name(1, "lattice.a")})
    declared = 3 * len(cell_free) + len(scale_free)
    # 生成された INP で実際に解放されている格子パラメータ数と一致すること。
    released = sum(
        1 for line in text.splitlines() for axis in ("a ", "b ", "c ")
        if line.strip().startswith(axis) and not line.strip().startswith(f"{axis}!")
        and "=" not in line
    )
    assert released == 3 * len(cell_free) == declared - len(scale_free)


def test_scale_is_also_per_phase():
    """スケールも同様に相ごと (既に集合で渡っているが回帰ガードとして固定する)。"""
    text, _, _ = _document_for({param_name(0, "scale")})
    assert "scale !P1_scale" in text or "scale !phase1_scale" in text


# ---------------- 実 CIF (structure_ref) 非対応を黙らせない ----------------


def test_structure_ref_is_refused_rather_than_silently_replaced():
    """**実 CIF を渡されたら黙って簡約構造で代替しない**。

    `GSASIIBackend` は `structure_ref` があれば実 CIF を読む (`gsasii.py` の実 CIF 分岐)。
    TOPAS 版は簡約モデル (P m m m・Ni 1 原子) しか持たないので、同じ入力を受けて黙って
    代替すると **③ から見て「実構造で判別した」ことになる**。実構造判別 (`discriminate`)
    はまさにこの経路なので、捏造構造で走った結果が実データの結論として返る。

    これが `TopasBackend` を ② に露出していない理由でもある (下の非露出宣言を参照)。
    """
    backend = TopasBackend.__new__(TopasBackend)  # tc.exe 不要 (入力検証だけを見る)
    backend.wavelength = 1.5406
    phase = PhaseInstance(
        phase_ref="P", lattice=LatticeParams(4.0, 4.0, 4.0), scale=1.0,
        structure_ref="some.cif",
    )
    with pytest.raises(NotImplementedError, match="structure_ref"):
        backend.refine(
            RefinementModel(
                phases=(phase,), free_params=frozenset(),
                two_theta=_grid(), intensity=np.ones_like(_grid()),
            )
        )
    with pytest.raises(NotImplementedError, match="structure_ref"):
        backend.simulate((phase,), _grid())


def test_phases_without_structure_ref_are_accepted():
    """回帰: 簡約モデルの相 (structure_ref なし) は従来どおり通ること。"""
    backend = TopasBackend.__new__(TopasBackend)
    backend.wavelength = 1.5406
    backend._require_simplified_phases((_phase(),))  # 例外を出さない
