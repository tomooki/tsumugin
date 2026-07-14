from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, param_name
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance


def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


def _count_local_maxima(y: np.ndarray, *, min_height: float) -> int:
    interior = (y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)
    return int(np.count_nonzero(interior))


def test_simulate_produces_one_maximum_per_in_range_reflection():
    backend = SimulatedBackend(peak_fwhm=0.2)
    phase = _phase(a=5.0)
    tt = _grid()
    y = backend.simulate((phase,), tt)
    positions = backend.peak_positions(phase, tt)
    assert len(positions) > 0
    peaks = _count_local_maxima(y, min_height=0.1 * y.max())
    assert peaks == len(positions)


def test_refine_scale_converges_to_truth():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=3.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert result.converged
    assert result.phases[0].scale == pytest.approx(3.0, rel=0.01)


def test_refine_lattice_reduces_chi2():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = backend.simulate((truth,), tt)

    # perturb only `a` (b, c already correct) so the true a is unambiguous
    start = PhaseInstance(
        phase_ref="P", lattice=LatticeParams(5.03, 5.0, 5.0), scale=1.0
    )
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    # chi2 before refinement
    before = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    ).chi2
    after = backend.refine(model)
    assert after.chi2 < before * 0.5
    assert after.phases[0].lattice.a == pytest.approx(5.0, abs=0.02)


def test_no_free_params_is_noop_converged():
    backend = SimulatedBackend()
    tt = _grid()
    phase = _phase()
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.converged
    assert result.n_cycles == 1
    assert result.n_params == 0


def test_unrecognized_free_params_are_ignored_in_param_count():
    backend = SimulatedBackend()
    tt = _grid()
    phase = _phase()
    y = backend.simulate((phase,), tt)
    # "profile" is not a physical parameter of the simulated model
    model = RefinementModel(
        phases=(phase,),
        free_params=frozenset({param_name(0, "scale"), param_name(0, "profile")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert result.n_params == 1  # only "scale" is recognized/optimized


def test_deterministic():
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=2.5)
    y = backend.simulate((truth,), tt)
    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    r1 = backend.refine(model)
    r2 = backend.refine(model)
    assert r1.chi2 == r2.chi2
    assert r1.phases[0].scale == r2.phases[0].scale


def test_refine_lattice_populates_covariance_sigma():
    # 【テスト目的】: 格子 a を解放すると JᵀJ 漸近共分散由来の σ が LatticeParams.sigma["a"] に
    #   populate され、sigma_source="covariance" になることを確認 (Issue #66 / FR-306 / NFR-107)。
    # 【新セマンティクス】: sigma は当該 refine() で解放した格子属性のみからなる (持ち越しなし)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = backend.simulate((truth,), tt)

    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.03, 5.0, 5.0), scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    lattice = result.phases[0].lattice
    assert lattice.sigma_source == "covariance"  # 【確認内容】: 真の漸近共分散の由来明示 🔵
    assert set(lattice.sigma) == {"a"}  # 【確認内容】: 解放した a のみからなる新 dict 🔵
    assert lattice.sigma["a"] > 0.0  # 【確認内容】: 正の有限値 🔵
    assert math.isfinite(lattice.sigma["a"])


def test_refine_without_lattice_free_leaves_sigma_empty():
    # 【テスト目的】: 格子を解放しない (scale のみ) 精密化では lattice.sigma が空 dict のまま
    #   (既存挙動を保持) であることを確認 (非回帰)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=3.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert result.phases[0].lattice.sigma == {}  # 【確認内容】: 格子非解放は空 dict 🔵
    assert result.phases[0].lattice.sigma_source == ""  # 【確認内容】: 由来も未設定 🔵


def test_refine_lattice_sigma_is_deterministic():
    # 【テスト目的】: 同一入力の 2 回精密化で共分散 σ がビット同一であることを確認 (NFR-102)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = backend.simulate((truth,), tt)
    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.03, 5.0, 5.0), scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    r1 = backend.refine(model)
    r2 = backend.refine(model)
    assert r1.phases[0].lattice.sigma["a"] == r2.phases[0].lattice.sigma["a"]


def test_refine_with_nan_intensity_leaves_sigma_empty():
    # 【テスト目的】: 観測強度に NaN が混入し chi2 が非有限になった場合、σ を書き込まず
    #   sigma={} / sigma_source="" に縮退することを確認 (NaN を絶対に伝播させないガード)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = backend.simulate((truth,), tt)
    y = y.copy()
    y[10] = float("nan")  # 【NaN 混入】: chi2 が NaN になる 🔵

    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.03, 5.0, 5.0), scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    lattice = result.phases[0].lattice
    assert lattice.sigma == {}  # 【確認内容】: NaN を書き込まず空 dict へ縮退 🔵
    assert lattice.sigma_source == ""  # 【確認内容】: 由来も未設定 🔵


def test_refine_replaces_stale_sigma_with_current_release_only():
    # 【テスト目的】: 入力相に古い sigma ({"a": ...}, "covariance") が残っていても、出力 sigma は
    #   今回解放した属性 (b) のみからなる新 dict に置換され、持ち越しがないことを確認
    #   (σ セマンティクス統一: sigma は当該 refine() の推定不確かさのみを表す)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.0, 5.0, 5.0), scale=1.0)
    y = backend.simulate((truth,), tt)

    stale = LatticeParams(
        5.0, 5.03, 5.0, sigma={"a": 0.5}, sigma_source="covariance"
    )  # 【古い σ】: 前回精密化の残留を模擬 🔵
    start = PhaseInstance(phase_ref="P", lattice=stale, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.b")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    lattice = result.phases[0].lattice
    assert set(lattice.sigma) == {"b"}  # 【確認内容】: 今回解放した b のみ (a は持ち越さない) 🔵
    assert lattice.sigma_source == "covariance"
    assert lattice.sigma["b"] > 0.0
    assert math.isfinite(lattice.sigma["b"])


def test_refine_resets_sigma_of_phase_without_lattice_release():
    # 【テスト目的】: 格子を解放しなかった相に古い sigma が残っていても sigma={} /
    #   sigma_source="" にリセットされることを確認 (混入排除、GSASIIBackend _read_back と対称)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth0 = _phase(a=5.0, scale=1.0, ref="P0")
    truth1 = PhaseInstance(phase_ref="P1", lattice=LatticeParams(4.0, 4.0, 4.0), scale=1.0)
    y = backend.simulate((truth0, truth1), tt)

    start0 = PhaseInstance(phase_ref="P0", lattice=LatticeParams(5.03, 5.0, 5.0), scale=1.0)
    stale1 = LatticeParams(4.0, 4.0, 4.0, sigma={"c": 0.9}, sigma_source="proxy")
    start1 = PhaseInstance(phase_ref="P1", lattice=stale1, scale=1.0)
    model = RefinementModel(
        phases=(start0, start1),
        free_params=frozenset({param_name(0, "lattice.a"), param_name(1, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    # 【確認内容】: 格子解放した phase0 は covariance σ を持つ 🔵
    assert set(result.phases[0].lattice.sigma) == {"a"}
    assert result.phases[0].lattice.sigma_source == "covariance"
    # 【確認内容】: 格子非解放の phase1 は古い σ が消えて空にリセットされる 🔵
    assert result.phases[1].lattice.sigma == {}
    assert result.phases[1].lattice.sigma_source == ""


def test_refine_noop_resets_stale_sigma():
    # 【テスト目的】: 解放パラメータ皆無の早期リターン経路でも、入力の古い sigma が
    #   リセットされることを確認 (σ は当該 refine() の推定のみを表す統一セマンティクス)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    stale = LatticeParams(5.0, 5.0, 5.0, sigma={"a": 0.1}, sigma_source="covariance")
    phase = PhaseInstance(phase_ref="P", lattice=stale, scale=1.0)
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.phases[0].lattice.sigma == {}  # 【確認内容】: noop でも持ち越さない 🔵
    assert result.phases[0].lattice.sigma_source == ""


def test_refine_lattice_sigma_with_absorption_restraint_stays_finite():
    # 【テスト目的】: restraint (absorption fit_mu_t) 併用時も σ が有限・正で、膨張しない
    #   ことを確認 (reduced χ² の自由度は restraint 行を含む残差全長 n_res で数える)。
    from tsumugin.absorption.model import AbsorptionConfig

    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = SimulatedBackend(
        peak_fwhm=0.2, absorption=AbsorptionConfig(mu_t_initial=0.5)
    ).simulate((truth,), tt)

    backend = SimulatedBackend(
        peak_fwhm=0.2,
        absorption=AbsorptionConfig(mu_t_initial=0.0, mu_t_calc=0.5, restraint_weight=100.0),
    )
    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.02, 5.0, 5.0), scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "lattice.a"), "global.mu_t"}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    lattice = result.phases[0].lattice
    assert set(lattice.sigma) == {"a"}  # 【確認内容】: mu_t は sigma 対象外 (格子属性のみ) 🔵
    assert lattice.sigma_source == "covariance"
    assert math.isfinite(lattice.sigma["a"])
    assert lattice.sigma["a"] > 0.0
    # 【確認内容】: 良好適合では σ は初期摂動 (0.02 Å) より十分小さく、膨張しない 🟡
    assert lattice.sigma["a"] < 0.02


def test_metrics_non_negative():
    backend = SimulatedBackend()
    tt = _grid()
    phase = _phase(scale=2.0)
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.rwp >= 0.0
    assert result.chi2 >= 0.0
