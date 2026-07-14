"""``tsumugin.evidence.noise`` (Issue #64 / FR-123 EM ノイズスケール推定) のテスト。

観測–計算残差と統計重みから外れ値混合 EM でグローバルなノイズスケール s を推定する
``estimate_noise_em`` / ``NoiseEstimate`` を検証する。乱数は使わず決定論的な疑似ノイズ列
(np.sin の重ね合わせ) で「既知の分散」を構成し、EM がそれを回復できることを確認する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.evidence.noise import NoiseEstimate, estimate_noise_em


def _deterministic_pseudo_noise(n: int) -> np.ndarray:
    """乱数 API を使わない決定論的な疑似ノイズ列 (複数周波数の sin 重ね合わせ)。

    振幅・周波数は無理数的な位相 (0.7, 1.37 rad) で選び、有限区間でも自己相関の
    強い周期性を避ける。分散は実測 (np.mean(eps**2)) で厳密に「既知」になる。
    """
    idx = np.arange(n, dtype=float)
    return 0.7 * np.sin((idx + 1.0) * 0.7) + 0.3 * np.sin((idx + 1.0) * 1.37)


# ---------------------------------------------------------------------------
# (a) 既知 s の回復 (全点 inlier、w=1)
# ---------------------------------------------------------------------------


def test_recovers_known_scale_from_deterministic_pseudo_noise():
    eps = _deterministic_pseudo_noise(400)
    weights = np.ones_like(eps)
    true_scale = math.sqrt(float(np.mean(eps**2)))  # w=1 のとき z=eps なので厳密な既知値

    result = estimate_noise_em(eps, weights)

    assert isinstance(result, NoiseEstimate)
    assert result.converged
    assert result.degenerate_reason is None
    # 【±数%で回復】: 外れ値なしの純粋な inlier 集団は EM でもほぼ naive 平均に一致する 🔵
    assert result.scale == pytest.approx(true_scale, rel=0.03)
    assert result.inlier_fraction > 0.95  # 外れ値なしなので π はほぼ 1 に収束


def test_recovers_known_scale_under_nonuniform_weights():
    # 【重み非一様】: w_i が一様でなくても z_i = sqrt(w_i)*eps_i の分散として s を回復する 🔵
    eps = _deterministic_pseudo_noise(300)
    idx = np.arange(300, dtype=float)
    weights = 1.0 + 0.5 * np.sin(idx * 0.31) ** 2  # 常に正の決定論的重み
    z = np.sqrt(weights) * eps
    true_scale = math.sqrt(float(np.mean(z**2)))

    result = estimate_noise_em(eps, weights)
    assert result.scale == pytest.approx(true_scale, rel=0.03)


# ---------------------------------------------------------------------------
# (b) 外れ値混入時のロバスト性 (naive s と比較)
# ---------------------------------------------------------------------------


def test_robust_to_outlier_contamination():
    eps = _deterministic_pseudo_noise(400)
    weights = np.ones_like(eps)
    true_scale = math.sqrt(float(np.mean(eps**2)))

    contaminated = eps.copy()
    outlier_idx = np.array([5, 123, 250, 301, 390])
    contaminated[outlier_idx] = contaminated[outlier_idx] + 8.0  # 少数の大残差 (未モデルピーク等)

    naive_scale = math.sqrt(float(np.mean(contaminated**2)))
    em_result = estimate_noise_em(contaminated, weights)

    # 【単純推定との差】: naive (混合なし) は外れ値に強く汚染されるが、EM の inlier scale は
    #   汚染前の真値へより近い (ロバスト性の検証、Issue #64 要件 (b)) 🔵
    naive_error = abs(naive_scale - true_scale)
    em_error = abs(em_result.scale - true_scale)
    assert em_error < naive_error
    assert em_error < 0.5 * naive_error  # 明確に汚染が抑えられていることを要求
    # 汚染点 (5/400=1.25%) 相当以上は outlier とみなされているはず
    assert em_result.inlier_fraction < 0.99


def test_more_outliers_lower_inlier_fraction_monotonically():
    # 【単調性】: 外れ値点を増やすほど推定 inlier_fraction は単調に下がる (責任の妥当性) 🔵
    eps = _deterministic_pseudo_noise(400)
    weights = np.ones_like(eps)

    def contaminate(n_outliers: int) -> np.ndarray:
        out = eps.copy()
        out[:n_outliers] = out[:n_outliers] + 10.0
        return out

    frac_few = estimate_noise_em(contaminate(2), weights).inlier_fraction
    frac_many = estimate_noise_em(contaminate(40), weights).inlier_fraction
    assert frac_many < frac_few


# ---------------------------------------------------------------------------
# (c) 決定論 (NFR-102)
# ---------------------------------------------------------------------------


def test_deterministic_bit_identical():
    eps = _deterministic_pseudo_noise(200)
    eps[3] += 5.0  # 外れ値も混ぜて EM 反復を経由させる
    weights = np.ones_like(eps)

    r1 = estimate_noise_em(eps, weights)
    r2 = estimate_noise_em(eps, weights)

    assert r1 == r2
    assert r1.scale == r2.scale  # 明示: float のビット同一 (dataclass == は内包するが明記)
    assert r1.n_iterations == r2.n_iterations
    assert r1.inlier_fraction == r2.inlier_fraction


# ---------------------------------------------------------------------------
# (d) 縮退入力
# ---------------------------------------------------------------------------


def test_empty_input_is_degenerate():
    result = estimate_noise_em(np.array([]), np.array([]))
    assert result.scale == 1.0
    assert result.converged is False
    assert result.n_iterations == 0
    assert result.degenerate_reason is not None


def test_all_zero_residuals_is_degenerate():
    result = estimate_noise_em(np.zeros(10), np.ones(10))
    assert result.scale == 1.0
    assert result.converged is False
    assert result.degenerate_reason is not None
    assert result.inlier_fraction == 1.0


def test_all_nonfinite_residuals_is_degenerate():
    residuals = np.array([np.nan, np.inf, -np.inf])
    weights = np.array([1.0, 1.0, 1.0])
    result = estimate_noise_em(residuals, weights)
    assert result.scale == 1.0
    assert result.converged is False
    assert result.degenerate_reason is not None


def test_all_nonpositive_weights_is_degenerate():
    residuals = np.array([1.0, 2.0, 3.0])
    weights = np.array([0.0, -1.0, 0.0])
    result = estimate_noise_em(residuals, weights)
    assert result.scale == 1.0
    assert result.converged is False
    assert result.degenerate_reason is not None


def test_partial_nonfinite_points_are_filtered_not_degenerate():
    # 【部分混入】: 一部の点のみ非有限/非正重みでも、残りの有効点だけで推定を続行する 🔵
    eps = _deterministic_pseudo_noise(200)
    weights = np.ones_like(eps)
    eps_bad = eps.copy()
    eps_bad[7] = np.nan
    weights_bad = weights.copy()
    weights_bad[42] = -1.0

    result = estimate_noise_em(eps_bad, weights_bad)
    assert result.degenerate_reason is None
    assert result.converged
    assert math.isfinite(result.scale)
    assert result.scale > 0.0


# ---------------------------------------------------------------------------
# 契約違反 (プログラミングエラー) は ValueError で fail-loud
# ---------------------------------------------------------------------------


def test_mismatched_shapes_raise_value_error():
    with pytest.raises(ValueError):
        estimate_noise_em(np.ones(5), np.ones(3))


def test_non_positive_max_iterations_raises_value_error():
    with pytest.raises(ValueError):
        estimate_noise_em(np.ones(5), np.ones(5), max_iterations=0)


# ---------------------------------------------------------------------------
# 基本的な健全性
# ---------------------------------------------------------------------------


def test_result_scale_is_positive_and_finite_for_normal_input():
    eps = _deterministic_pseudo_noise(50)
    weights = np.ones_like(eps)
    result = estimate_noise_em(eps, weights)
    assert math.isfinite(result.scale)
    assert result.scale > 0.0
    assert 0.0 <= result.inlier_fraction <= 1.0


def test_hyperparameters_are_configurable():
    eps = _deterministic_pseudo_noise(100)
    weights = np.ones_like(eps)
    result = estimate_noise_em(
        eps,
        weights,
        outlier_inflation=9.0,
        initial_inlier_fraction=0.5,
        max_iterations=5,
        rtol=1e-3,
    )
    assert result.n_iterations <= 5
    assert math.isfinite(result.scale)
