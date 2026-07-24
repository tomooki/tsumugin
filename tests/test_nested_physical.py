"""nested/physical.py (Issue #76 T3): 区間 joint 物理 EvidenceProblem 構築のテスト。

v1 サロゲート (定数尤度) との決定的な違い = 「θ を動かすと logL が動く」ことを
中心に検証する。決定論 (NFR-102)・priors 昇順/フレーム major・ブロック対角 Hessian・
MAP が事前分布の台内 (構成的保証) を確認する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, param_name
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance, RefinementMetrics
from tsumugin.nested.physical import (
    FrameState,
    PhysicalProblemConfig,
    build_physical_problem,
    restraints_from_state,
)


def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.05)


def _metrics() -> RefinementMetrics:
    return RefinementMetrics(rwp=5.0, gof=1.0, chi2=100.0, n_obs=1, n_params=0)


def _refined_frame(
    backend: SimulatedBackend,
    tt: np.ndarray,
    intensity: np.ndarray,
    start: PhaseInstance,
    free: frozenset[str],
    frame_index: int,
) -> FrameState:
    """backend.refine で MAP 状態 + curvature を得て FrameState を組むヘルパ。"""
    result = backend.refine(
        RefinementModel(phases=(start,), free_params=free, two_theta=tt, intensity=intensity)
    )
    return FrameState(
        frame_index=frame_index,
        phases=result.phases,
        free_params=free,
        two_theta=tt,
        intensity=intensity,
        curvature=result.curvature,
    )


# ---------------------------------------------------------------------------
# restraints_from_state
# ---------------------------------------------------------------------------


def test_restraints_from_state_lattice_margin_and_scale_bounds():
    phases = (_phase(a=4.0, scale=2.0),)
    free = frozenset({param_name(0, "lattice.a"), param_name(0, "scale")})
    restraints = restraints_from_state(phases, free, config=PhysicalProblemConfig())
    by_name = {r.param_name: r for r in restraints}
    lat = by_name[param_name(0, "lattice.a")]
    # 【確認内容】: 格子は精密化値中心 ±margin の有界区間 (MAP が台内に入る構成的保証) 🔵
    assert lat.lower == pytest.approx(4.0 * 0.98)
    assert lat.upper == pytest.approx(4.0 * 1.02)
    sc = by_name[param_name(0, "scale")]
    assert sc.lower == 0.0
    assert sc.upper == pytest.approx(2.0 * 4.0)


def test_restraints_from_state_rejects_unsupported_param():
    # 【テスト目的】: 相から値を読めないパラメータ (global.*) は黙って既定事前分布 (MAP が
    #   台外に出うる) に落とさず、大声で ValueError にする (呼び側がサロゲートへ縮退する契約)。
    phases = (_phase(),)
    with pytest.raises(ValueError):
        restraints_from_state(
            phases, frozenset({"global.mu_t"}), config=PhysicalProblemConfig()
        )


def test_restraints_from_state_map_always_inside_support():
    # 【テスト目的】: どの精密化値でも MAP (現在値) が事前分布の台 [lower, upper] に入る。
    for a, scale in [(3.2, 0.5), (5.0, 1.0), (11.7, 123.0)]:
        phases = (_phase(a=a, scale=scale),)
        free = frozenset(
            {param_name(0, "lattice.a"), param_name(0, "lattice.b"), param_name(0, "scale")}
        )
        for r in restraints_from_state(phases, free, config=PhysicalProblemConfig()):
            if "lattice" in r.param_name:
                v = a
            else:
                v = scale
            assert r.lower is not None and r.upper is not None
            assert r.lower <= v <= r.upper


def test_restraints_from_state_brackets_degenerate_negative_values():
    # 【テスト目的 (レビュー指摘)】: 負の scale/wt_frac/occ (SimulatedBackend はクリップするが
    #   本関数は backend 非依存の公開部品) でも台内保証が破れないこと。破れると log_pdf=-inf →
    #   Laplace が BIC へ静かに縮退し「実曲率で解消できない」と誤認させる (v1 欠陥の再導入)。
    phase = PhaseInstance(
        phase_ref="P",
        lattice=LatticeParams(5.0, 5.0, 5.0),
        scale=-0.5,
        wt_frac=-0.1,
        occupancies={"site": -0.2},
    )
    free = frozenset(
        {param_name(0, "scale"), param_name(0, "wt_frac"), param_name(0, "occ.site")}
    )
    values = {
        param_name(0, "scale"): -0.5,
        param_name(0, "wt_frac"): -0.1,
        param_name(0, "occ.site"): -0.2,
    }
    for r in restraints_from_state((phase,), free, config=PhysicalProblemConfig()):
        v = values[r.param_name]
        assert r.lower is not None and r.upper is not None
        assert r.lower <= v <= r.upper


# ---------------------------------------------------------------------------
# build_physical_problem
# ---------------------------------------------------------------------------


def _single_frame_problem(backend: SimulatedBackend):
    tt = _grid()
    truth = _phase(a=5.0, scale=2.0)
    y = backend.simulate((truth,), tt)
    start = _phase(a=5.02, scale=1.0)
    free = frozenset({param_name(0, "lattice.a"), param_name(0, "scale")})
    frame = _refined_frame(backend, tt, y, start, free, frame_index=3)
    problem = build_physical_problem(
        backend, (frame,), metrics=_metrics(), label="single", config=PhysicalProblemConfig()
    )
    return frame, problem


def test_build_single_frame_log_likelihood_matches_backend_chi2():
    # 【テスト目的】: logL(map_point) が backend の純評価 (free=∅ refine) の -χ²/2 と一致する
    #   (物理尤度の定義そのもの)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    frame, problem = _single_frame_problem(backend)
    eval_result = backend.refine(
        RefinementModel(
            phases=frame.phases,
            free_params=frozenset(),
            two_theta=frame.two_theta,
            intensity=frame.intensity,
        )
    )
    assert problem.map_point is not None
    logl = problem.log_likelihood(problem.map_point)
    assert logl == pytest.approx(-0.5 * eval_result.chi2)


def test_build_single_frame_likelihood_is_not_constant():
    # 【テスト目的】: v1 サロゲートの欠陥 (θ 非依存の定数尤度) が解消されていること。
    #   θ を動かすと logL が悪化する (MAP 近傍で最大)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    _, problem = _single_frame_problem(backend)
    assert problem.map_point is not None
    theta = np.array(problem.map_point, dtype=float)
    logl_map = problem.log_likelihood(theta)
    theta_pert = theta.copy()
    theta_pert[0] *= 1.01  # 格子を 1% ずらす
    logl_pert = problem.log_likelihood(theta_pert)
    assert logl_pert < logl_map


def test_build_single_frame_priors_sorted_and_frame_prefixed():
    backend = SimulatedBackend(peak_fwhm=0.2)
    frame, problem = _single_frame_problem(backend)
    names = [p.param_name for p in problem.priors]
    # 【確認内容】: frame{i:04d} 前置 + 昇順 (EvidenceProblem の決定論契約) 🔵
    assert names == sorted(names)
    assert names == [
        f"frame0003.{param_name(0, 'lattice.a')}",
        f"frame0003.{param_name(0, 'scale')}",
    ]


def test_build_single_frame_hessian_is_frame_curvature():
    backend = SimulatedBackend(peak_fwhm=0.2)
    frame, problem = _single_frame_problem(backend)
    assert frame.curvature is not None
    assert problem.hessian is not None
    np.testing.assert_array_equal(problem.hessian, frame.curvature.hessian)


def test_build_two_frames_concatenates_and_block_diagonalizes():
    # 【テスト目的】: 2 フレームで priors がフレーム major に連結され、logL が和になり、
    #   Hessian がブロック対角 (交差項 0) になること。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    y0 = backend.simulate((_phase(a=5.0, scale=2.0),), tt)
    y1 = backend.simulate((_phase(a=5.01, scale=2.1),), tt)
    free = frozenset({param_name(0, "lattice.a"), param_name(0, "scale")})
    f0 = _refined_frame(backend, tt, y0, _phase(a=5.02, scale=1.0), free, frame_index=0)
    f1 = _refined_frame(backend, tt, y1, _phase(a=5.02, scale=1.0), free, frame_index=1)
    problem = build_physical_problem(
        backend, (f0, f1), metrics=_metrics(), label="joint", config=PhysicalProblemConfig()
    )
    names = [p.param_name for p in problem.priors]
    assert len(names) == 4
    assert names == sorted(names)
    assert names[0].startswith("frame0000.") and names[2].startswith("frame0001.")

    # logL の分解: joint logL(map) = 各フレーム単独 problem の logL(map) の和
    p0 = build_physical_problem(
        backend, (f0,), metrics=_metrics(), label="f0", config=PhysicalProblemConfig()
    )
    p1 = build_physical_problem(
        backend, (f1,), metrics=_metrics(), label="f1", config=PhysicalProblemConfig()
    )
    assert problem.map_point is not None
    joint = problem.log_likelihood(problem.map_point)
    assert joint == pytest.approx(
        p0.log_likelihood(p0.map_point) + p1.log_likelihood(p1.map_point)
    )

    # ブロック対角: 交差ブロックは厳密 0
    assert problem.hessian is not None
    h = np.asarray(problem.hessian)
    assert h.shape == (4, 4)
    assert np.all(h[:2, 2:] == 0.0)
    assert np.all(h[2:, :2] == 0.0)
    np.testing.assert_array_equal(h[:2, :2], f0.curvature.hessian)  # type: ignore[union-attr]
    np.testing.assert_array_equal(h[2:, 2:], f1.curvature.hessian)  # type: ignore[union-attr]


def test_build_without_curvature_still_physical_but_no_hessian():
    # 【テスト目的】: curvature 欠如フレームがあると hessian は None (Laplace は BIC 縮退) だが、
    #   logL は物理のまま (nested 経路は生きる)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    y = backend.simulate((_phase(a=5.0, scale=2.0),), tt)
    free = frozenset({param_name(0, "scale")})
    frame = _refined_frame(backend, tt, y, _phase(a=5.0, scale=1.0), free, frame_index=0)
    frame_no_curv = FrameState(
        frame_index=0,
        phases=frame.phases,
        free_params=frame.free_params,
        two_theta=frame.two_theta,
        intensity=frame.intensity,
        curvature=None,
    )
    problem = build_physical_problem(
        backend,
        (frame_no_curv,),
        metrics=_metrics(),
        label="nc",
        config=PhysicalProblemConfig(),
    )
    assert problem.hessian is None
    assert problem.map_point is not None
    theta = np.array(problem.map_point, dtype=float)
    assert math.isfinite(problem.log_likelihood(theta))
    theta[0] *= 1.5
    assert problem.log_likelihood(theta) < problem.log_likelihood(problem.map_point)


def test_build_empty_frames_raises():
    backend = SimulatedBackend(peak_fwhm=0.2)
    with pytest.raises(ValueError):
        build_physical_problem(
            backend, (), metrics=_metrics(), label="empty", config=PhysicalProblemConfig()
        )


def test_build_is_deterministic_bitwise():
    backend = SimulatedBackend(peak_fwhm=0.2)
    _, problem1 = _single_frame_problem(backend)
    _, problem2 = _single_frame_problem(backend)
    assert [p.param_name for p in problem1.priors] == [p.param_name for p in problem2.priors]
    np.testing.assert_array_equal(problem1.map_point, problem2.map_point)
    np.testing.assert_array_equal(problem1.hessian, problem2.hessian)
    theta = np.array(problem1.map_point, dtype=float) * 1.003
    assert problem1.log_likelihood(theta) == problem2.log_likelihood(theta)


def test_nonfinite_backend_chi2_maps_to_neg_inf():
    # 【テスト目的】: backend 失敗 (chi2=inf/nan) は例外でなく logL=-inf へ写す
    #   (サンプラが zero-probability として処理できる形。nan を漏らさない)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    y = np.full_like(tt, np.nan)  # 全 NaN 強度 → 純評価 chi2 が非有限
    frame = FrameState(
        frame_index=0,
        phases=(_phase(),),
        free_params=frozenset({param_name(0, "scale")}),
        two_theta=tt,
        intensity=y,
        curvature=None,
    )
    problem = build_physical_problem(
        backend, (frame,), metrics=_metrics(), label="nan", config=PhysicalProblemConfig()
    )
    assert problem.map_point is not None
    logl = problem.log_likelihood(np.array(problem.map_point, dtype=float))
    assert logl == float("-inf")
