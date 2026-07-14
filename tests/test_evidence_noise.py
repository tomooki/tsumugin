"""``tsumugin.evidence.noise`` (Issue #64 / FR-123 EM ノイズスケール推定) のテスト。

観測–計算残差と統計重みから外れ値混合 EM でグローバルなノイズスケール s を推定する
``estimate_noise_em`` / ``NoiseEstimate`` を検証する。乱数は使わず決定論的な疑似ノイズ列
(np.sin の重ね合わせ) で「既知の分散」を構成し、EM がそれを回復できることを確認する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.evidence.noise import NoiseEstimate, estimate_noise_em, noise_extras


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
# (e) 新モデル (v_out 凍結 + inlier-only M-step) の実測アンカー — Issue #64 PR #77 レビュー対応
# ---------------------------------------------------------------------------


def test_thirty_percent_outliers_recovers_true_scale_within_10_percent():
    # 【機能概要】: 30% 外れ値 (σ×8 相当の乗算膨張) でも真の inlier スケールを ±10% 以内で
    #   回復する。旧モデル (外れ値分散を κs² で s に紐付け、M-step 分母を Σw_eff とする実装) は
    #   分母が有効点数 n を系統的に下回り約 27% 過大評価していた (実測、レビュー指摘)。
    #   新モデル (v_out 凍結 + inlier-only M-step) は実測で誤差 2% 未満まで改善する。
    n = 1000
    eps = _deterministic_pseudo_noise(n)
    weights = np.ones_like(eps)
    true_scale = math.sqrt(float(np.mean(eps**2)))

    n_out = int(0.3 * n)
    contaminated = eps.copy()
    idx_out = np.arange(0, n, max(1, n // n_out))[:n_out]
    contaminated[idx_out] = contaminated[idx_out] * 8.0  # 外れ値成分を約 8 倍に膨張

    result = estimate_noise_em(contaminated, weights)

    assert result.degenerate_reason is None
    rel_error = abs(result.scale - true_scale) / true_scale
    assert rel_error < 0.10  # 【実測アンカー】: ±10% 以内 (実測 ~1.8%) 🔵
    assert rel_error < 0.05  # 【引き締め】: 実測はさらに良好 (旧モデルの 27% 過大とは対照的) 🔵


def test_single_spike_does_not_linearly_contaminate_scale():
    # 【機能概要】: 単発の巨大スパイク (z≈2000 相当) が混入しても s は真値からほぼ動かない。
    #   旧モデルは外れ値分散が κs² で s に連動するため w_eff の 1/κ 床を通じてスパイク 1 点でも
    #   s が真値の約 33 倍に汚染された (実測、レビュー指摘)。新モデルは v_out を凍結するため
    #   スパイクの責任 γ が速やかに ~0 へ落ち、M-step (inlier-only) から実質的に排除される。
    eps = _deterministic_pseudo_noise(400)
    weights = np.ones_like(eps)
    true_scale = math.sqrt(float(np.mean(eps**2)))

    spiked = eps.copy()
    spiked[123] = 2000.0  # z = sqrt(1)*2000 = 2000 (inlier スケール ~0.5 に対し圧倒的な外れ値)

    result = estimate_noise_em(spiked, weights)

    assert result.degenerate_reason is None
    ratio = result.scale / true_scale
    # 【実測アンカー】: 汚染しない (真値比 0.9995、旧モデルの 33 倍汚染とは対照的) 🔵
    assert 0.95 < ratio < 1.05
    assert result.inlier_fraction > 0.99  # 【責任の妥当性】: 399/400 が inlier と判定される 🔵


def test_all_inlier_precision_preserved_by_new_model():
    # 【回帰確認】: 外れ値なし (全点 inlier) では旧モデルと同様に高精度で真値を回復する
    #   (v_out 凍結・inlier-only M-step が「正常系の精度」を犠牲にしていないことの確認)。
    eps = _deterministic_pseudo_noise(500)
    weights = np.ones_like(eps)
    true_scale = math.sqrt(float(np.mean(eps**2)))

    result = estimate_noise_em(eps, weights)

    assert result.degenerate_reason is None
    assert result.scale == pytest.approx(true_scale, rel=0.02)  # 【高精度】: ±2% 以内 🔵
    assert result.inlier_fraction > 0.95


# ---------------------------------------------------------------------------
# (f) 不変条件: scale は常に有限かつ正、満たせなければ scale=1.0 + degenerate_reason 明示
# ---------------------------------------------------------------------------


def test_overflow_residuals_degenerate_with_reason_and_unit_scale():
    # 【実測ケース】: 残差 1e200 は二乗でオーバーフロー (float64 上限 ~1.8e308 を超える) し、
    #   z² が非有限になる。全点がこれに該当すると推定不能なので明示的に縮退する。
    residuals = np.full(20, 1e200)
    weights = np.ones(20)

    result = estimate_noise_em(residuals, weights)

    assert result.scale == 1.0
    assert result.converged is False
    assert result.degenerate_reason is not None


def test_subnormal_residuals_degenerate_with_reason_and_unit_scale():
    # 【実測ケース】: 残差 1e-162 は二乗すると 1e-324 となり float64 の表現下限を割って厳密に
    #   0.0 へアンダーフローする (最小正規化 subnormal ~4.9e-324 を下回る)。分散推定不能として
    #   明示的に縮退する (scale=1.0 への中立フォールバック、NaN/0 を理由なく返さない)。
    residuals = np.full(20, 1e-162)
    weights = np.ones(20)

    result = estimate_noise_em(residuals, weights)

    assert result.scale == 1.0
    assert result.converged is False
    assert result.degenerate_reason is not None


def test_tiny_nonzero_scale_degenerates_via_floor_guard():
    # 【下限フロア】: z² がアンダーフローで厳密ゼロにはならないが下限フロア (1e-150) を割る
    #   極小残差は "scale_underflow" タグ付きで明示的に縮退する (全ゼロ経路とは別の分岐)。
    residuals = np.full(20, 1e-80)  # z² ~ 1e-160 (< floor だが exact 0 ではない)
    weights = np.ones(20)

    result = estimate_noise_em(residuals, weights)

    assert result.scale == 1.0
    assert result.converged is False
    assert result.degenerate_reason is not None
    assert "scale_underflow" in result.degenerate_reason


def test_overflow_point_filtered_when_mixed_with_normal_points():
    # 【部分混入】: 全点でなく 1 点だけが overflow するケースは、その点だけ除外して残りの
    #   有効点で推定を続行する (フィルタ後に点数が残っていれば degenerate にしない)。
    eps = _deterministic_pseudo_noise(50)
    eps_mixed = eps.copy()
    eps_mixed[0] = 1e200
    weights = np.ones_like(eps_mixed)

    result = estimate_noise_em(eps_mixed, weights)

    assert result.degenerate_reason is None
    assert math.isfinite(result.scale)
    assert result.scale > 0.0


# ---------------------------------------------------------------------------
# (g) noise_extras (Issue #64 レビュー対応: backend 非依存の共有オーケストレーション関数)
# ---------------------------------------------------------------------------


def test_noise_extras_disabled_returns_neutral_triple():
    # enabled=False は EM を一切呼ばず即座に (None, {}, ()) を返す (既定・後方互換経路)。
    eps = _deterministic_pseudo_noise(50)
    weights = np.ones_like(eps)

    noise_scale, globals_update, warnings = noise_extras(eps, weights, enabled=False)

    assert noise_scale is None
    assert globals_update == {}
    assert warnings == ()


def test_noise_extras_enabled_matches_estimate_noise_em():
    # enabled=True は estimate_noise_em と同一の推定を行い、noise_scale と
    # globals["noise_scale"] が単一情報源から同時に組み立てられるため常に一致する。
    eps = _deterministic_pseudo_noise(200)
    eps[3] += 5.0  # 外れ値も混ぜて EM 反復を経由させる
    weights = np.ones_like(eps)

    expected = estimate_noise_em(eps, weights)
    noise_scale, globals_update, warnings = noise_extras(eps, weights, enabled=True)

    assert noise_scale == expected.scale
    assert globals_update == {"noise_scale": expected.scale}
    assert globals_update["noise_scale"] == noise_scale  # 二重格納の一致 (ドリフトしない)
    assert len(warnings) == 1
    assert "FR-123" in warnings[0]  # 由来明示 (NFR-107)


def test_noise_extras_forwards_hyperparameters():
    # outlier_inflation 等のハイパーパラメータが estimate_noise_em へそのまま転送される。
    eps = _deterministic_pseudo_noise(100)
    weights = np.ones_like(eps)

    expected = estimate_noise_em(eps, weights, outlier_inflation=9.0, max_iterations=5)
    noise_scale, _, _ = noise_extras(
        eps, weights, enabled=True, outlier_inflation=9.0, max_iterations=5
    )
    assert noise_scale == expected.scale


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
