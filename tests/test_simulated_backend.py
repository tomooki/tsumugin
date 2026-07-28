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


def _observed_with_noise(backend, phases, tt, *, seed: int = 0, rel: float = 1e-3):
    """合成観測に**決定論ノイズ**を載せて返す (σ を浮動小数残差に依存させない)。

    【なぜ必要か (2026-07-28, CI 初回で判明)】: ノイズなしの合成データを近傍から精密化すると
    **完全フィット**に到達し χ² ≈ 0 になる。この開発機では χ² = 1.12e-25 (正の残差) なので
    ``cov = pinv(JᵀJ) · χ²/dof`` が 2.0e-17 という「正だが無意味な」σ を返し、
    ``assert sigma["a"] > 0.0`` が通っていた。**Linux (別 BLAS) では χ² が厳密に 0.0 になり**、
    ``var > 0`` ガードが発火して σ が丸ごと空へ縮退し 3 件が fail した。

    つまりこれらのテストは σ ではなく**浮動小数の残りかす**を検証していた。ノイズを載せれば
    χ² が実質的に非ゼロになり、σ は「共分散由来の意味のある正値」になる — 主張どおりのものを
    検証する形に戻す (実装側の ``var > 0`` ガードは緩めない: 負/非有限は依然として異常)。

    ノイズ**配列そのもの**は ``default_rng(seed)`` 固定なので実行間・プラットフォーム間で
    ビット同一 (numpy が Generator の再現性を保証する)。⚠ **下流まで含めてビット同一とは主張
    しない** — χ² や σ は BLAS 実装に依存し、それがまさに本ヘルパーを作った理由である
    (プラットフォーム間の一致を検証しているテストは存在しない; NFR-102 の「乱数種固定で
    ビット同一」は同一環境内の再現性として確認している)。
    """
    y = backend.simulate(tuple(phases), tt)
    rng = np.random.default_rng(seed)
    return y + rng.normal(0.0, rel * float(np.max(y)), size=y.shape)


def test_refine_lattice_populates_covariance_sigma():
    # 【テスト目的】: 格子 a を解放すると JᵀJ 漸近共分散由来の σ が LatticeParams.sigma["a"] に
    #   populate され、sigma_source="covariance" になることを確認 (Issue #66 / FR-306 / NFR-107)。
    # 【新セマンティクス】: sigma は当該 refine() で解放した格子属性のみからなる (持ち越しなし)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)
    y = _observed_with_noise(backend, (truth,), tt)

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
    y = _observed_with_noise(backend, (truth,), tt)
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
    y = _observed_with_noise(backend, (truth,), tt)

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
    y = _observed_with_noise(backend, (truth0, truth1), tt)

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


def test_refine_lattice_sigma_excludes_non_identifiable_angle():
    # 【テスト目的】: orthorhombic 近似の前方モデルは alpha に無寄与 (Jacobian 列が恒等 0) なので、
    #   a/b/c と同時解放しても alpha は非識別として σ から除外され、識別可能な a/b/c は
    #   丸ごと {} に巻き添えにされず正の有限 σ を保持することを確認 (Issue #66 レビュー対応)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=1.0)  # a=b=c=5.0, alpha=beta=gamma=90 (既定)
    y = _observed_with_noise(backend, (truth,), tt)

    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.03, 4.97, 5.02), scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset(
            {
                param_name(0, "lattice.a"),
                param_name(0, "lattice.b"),
                param_name(0, "lattice.c"),
                param_name(0, "lattice.alpha"),
            }
        ),
        two_theta=tt,
        intensity=y,
    )
    r1 = backend.refine(model)
    r2 = backend.refine(model)  # 【決定論】: 2 回実行でビット同一 (NFR-102) 🔵

    lattice1 = r1.phases[0].lattice
    assert lattice1.sigma_source == "covariance"
    # 【確認内容】: 非識別な alpha は含まれず、識別可能な a/b/c のみが σ を持つ 🔵
    assert set(lattice1.sigma) == {"a", "b", "c"}
    for key in ("a", "b", "c"):
        assert math.isfinite(lattice1.sigma[key])
        assert lattice1.sigma[key] > 0.0

    lattice2 = r2.phases[0].lattice
    assert lattice1.sigma == lattice2.sigma  # 【確認内容】: ビット同一 🔵


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


# ---------------------------------------------------------------------------
# Issue #64 / FR-123: opt-in estimate_noise の SimulatedBackend 配線
# ---------------------------------------------------------------------------


def test_estimate_noise_defaults_off_and_leaves_noise_scale_none():
    # 【テスト目的】: estimate_noise 未指定 (既定 False) では EM を一切呼ばず noise_scale=None・
    #   warnings/globals も変化しないことを確認 (既存呼び出しとビット同一, REQ-404)。
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
    assert result.noise_scale is None
    assert result.globals == {}
    assert result.warnings == ()


def test_estimate_noise_opt_in_populates_noise_scale():
    # 【テスト目的】: estimate_noise=True のとき最終残差から EM 推定した noise_scale が
    #   RefinementResult に populate されることを確認。
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
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
    assert result.noise_scale is not None
    assert math.isfinite(result.noise_scale)
    assert result.noise_scale > 0.0
    assert result.globals["noise_scale"] == pytest.approx(result.noise_scale)


def test_estimate_noise_opt_in_records_provenance_warning():
    # 【テスト目的】: opt-in 時に σ の由来 (NFR-107: 反復回数・収束可否・inlier 比率) が
    #   warnings へ記録されることを確認。
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
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
    assert len(result.warnings) >= 1
    assert any("ノイズスケール" in w and "FR-123" in w for w in result.warnings)


def test_estimate_noise_opt_in_is_deterministic():
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
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
    assert r1.noise_scale == r2.noise_scale
    assert r1.warnings == r2.warnings


def test_estimate_noise_opt_in_populates_on_no_free_params_path():
    # 【テスト目的】: 早期リターン経路 (解放パラメータ皆無) でも estimate_noise=True なら
    #   noise_scale が populate されることを確認 (2 経路とも配線されていることの回帰保証)。
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
    tt = _grid()
    phase = _phase(a=5.0, scale=2.0)
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.noise_scale is not None
    assert math.isfinite(result.noise_scale)


# ---------------------------------------------------------------------------
# Curvature 公開 (Issue #76 T1): 最終受理パラメータの JᵀJ を RefinementResult へ
# ---------------------------------------------------------------------------


def test_refine_populates_curvature_with_sorted_param_order():
    # 【テスト目的】: 解放パラメータありの refine が curvature (param_names/point/hessian) を
    #   充填し、列順が names (sorted free_params) と一致・point が精密化済み値と一致すること。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = backend.simulate((truth,), tt)
    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.02, 5.0, 5.0), scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale"), param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    curv = result.curvature
    assert curv is not None
    # 【確認内容】: 列順は sorted free_params (lattice.a < scale) 🔵
    assert curv.param_names == (param_name(0, "lattice.a"), param_name(0, "scale"))
    # 【確認内容】: point は精密化後の実値 (phases から読める値と一致) 🔵
    assert curv.point[0] == pytest.approx(result.phases[0].lattice.a)
    assert curv.point[1] == pytest.approx(result.phases[0].scale)
    # 【確認内容】: hessian は対称・有限・正定値 (識別可能な 2 パラメータ) 🔵
    h = np.asarray(curv.hessian)
    assert h.shape == (2, 2)
    assert np.all(np.isfinite(h))
    assert np.allclose(h, h.T)
    assert np.all(np.linalg.eigvalsh(0.5 * (h + h.T)) > 0.0)


def test_curvature_hessian_matches_analytic_jtj_for_scale_only():
    # 【テスト目的】: scale のみ解放の残差 r(s)=sqrt(w)·(y−s·y_unit) は dr/ds=−sqrt(w)·y_unit で
    #   H=JᵀJ=Σ w·y_unit² が解析的に既知。数値前進差分の JᵀJ がこれと一致することを確認
    #   (H が -logL=χ²/2 の Hessian [JᵀJ 近似] のスケールで公開されている契約の検証)。
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
    curv = result.curvature
    assert curv is not None and curv.param_names == (param_name(0, "scale"),)
    y_unit = backend.simulate((_phase(a=5.0, scale=1.0),), tt)
    weights = 1.0 / np.maximum(y, 1.0)
    expected = float(np.sum(weights * y_unit**2))
    assert float(curv.hessian[0, 0]) == pytest.approx(expected, rel=1e-3)


def test_curvature_is_none_without_free_params():
    # 【テスト目的】: 解放パラメータ皆無の早期リターン経路では curvature を提供しない (None)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    phase = _phase(a=5.0, scale=2.0)
    y = backend.simulate((phase,), tt)
    result = backend.refine(
        RefinementModel(phases=(phase,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.curvature is None


def test_curvature_is_none_for_nonfinite_data():
    # 【テスト目的】: NaN 強度で chi2/J が非有限のとき curvature を書かない (NaN を漏らさない)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    y = np.full_like(tt, np.nan)
    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
    )
    result = backend.refine(model)
    assert result.curvature is None


def test_curvature_includes_mu_t_column_when_fit():
    # 【テスト目的】: absorption + global.mu_t 解放時、curvature の末尾列が global.mu_t で
    #   restraint 行込みの JᵀJ になっていること (列順契約: names 順 + 末尾 μt)。
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
    curv = result.curvature
    assert curv is not None
    assert curv.param_names == (param_name(0, "lattice.a"), "global.mu_t")
    assert curv.point[1] == pytest.approx(result.globals["mu_t"])


def test_curvature_is_deterministic_bitwise():
    # 【テスト目的】: 同一入力 2 回で curvature がビット同一 (NFR-102)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=2.5)
    y = backend.simulate((truth,), tt)
    start = _phase(a=5.0, scale=1.0)
    model = RefinementModel(
        phases=(start,),
        free_params=frozenset({param_name(0, "scale"), param_name(0, "lattice.a")}),
        two_theta=tt,
        intensity=y,
    )
    r1 = backend.refine(model)
    r2 = backend.refine(model)
    assert r1.curvature is not None and r2.curvature is not None
    assert r1.curvature.param_names == r2.curvature.param_names
    assert np.array_equal(r1.curvature.point, r2.curvature.point)
    assert np.array_equal(r1.curvature.hessian, r2.curvature.hessian)


def test_curvature_value_equality_supports_result_comparison():
    # 【テスト目的】: Curvature を内包する RefinementResult の == 比較 (決定論テストの基盤) が
    #   ndarray truth-value ambiguity で壊れないこと (T1 レグレッション: eq=False + 値等価)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
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
    assert r1.curvature == r2.curvature  # 値等価
    assert r1 == r2  # RefinementResult 全体の等価比較が例外なく成立する
    # 異なる曲率は不等 (値等価が恒真でないこと)
    assert r1.curvature is not None
    from tsumugin.backends.base import Curvature

    other = Curvature(
        param_names=r1.curvature.param_names,
        point=r1.curvature.point,
        hessian=r1.curvature.hessian * 2.0,
    )
    assert r1.curvature != other


def test_structure_ref_is_ignored_by_simulated_backend():
    # 【Issue #130 L1】: SimulatedBackend は PhaseInstance.structure_ref を無視する
    #   (hkl_table を phase_ref で引くため影響なし = 後方互換)。structure_ref の有無で
    #   refine 結果がビット同一であることを確認 (変異: 万一参照したら chi2/phases が変わる)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = backend.simulate((truth,), tt)
    start = _phase(a=5.0, scale=1.0)
    start_with_ref = start.with_updates(structure_ref="/nonexistent/phantom.cif")
    free = frozenset({param_name(0, "scale"), param_name(0, "lattice.a")})
    r_plain = backend.refine(
        RefinementModel(phases=(start,), free_params=free, two_theta=tt, intensity=y)
    )
    r_ref = backend.refine(
        RefinementModel(phases=(start_with_ref,), free_params=free, two_theta=tt, intensity=y)
    )
    assert r_ref.chi2 == r_plain.chi2
    assert r_ref.rwp == r_plain.rwp
    assert r_ref.phases[0].scale == r_plain.phases[0].scale
    assert r_ref.phases[0].lattice.a == r_plain.phases[0].lattice.a
