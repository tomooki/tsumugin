"""ノイズ標準偏差の EM 推定 (FR-123)。

観測–計算残差 ``ε_i = y_obs_i − y_calc_i`` と既存の統計重み ``w_i`` から、
    ``ε_i ~ N(0, s² / w_i)``
の下でグローバルなノイズスケール ``s`` を推定する。単純な閉形式 ``s² = χ²/n``
(``χ² = Σ w_i ε_i²``) は 1 反復で確定し「EM 反復」にならない上、未モデルピーク・
不良点 (bad point) が紛れ込むとそのまま推定値を汚染する。そこで本モジュールは
**2 成分の外れ値混合モデル**として EM を実装する:

    z_i = sqrt(w_i) · ε_i                    (統計重みで正規化した残差)
    z_i ~ π · N(0, s²) + (1 − π) · N(0, κ·s²)  (κ > 1: 外れ値成分の分散膨張率)

inlier 成分 (責任 ``π``) は既存の重みモデルに従う「素直な」観測点、outlier 成分
(責任 ``1 − π``) は分散が ``κ`` 倍に膨張した「重みモデルから外れた」観測点
(未モデルピーク・スパイク・検出器不良等) を表す。κ は既定 25 (外れ値の標準偏差が
inlier の 5 倍) で設定可能。

E-step (responsibility, 各点が inlier である事後確率):
    γ_i = π·N(z_i;0,s²) / (π·N(z_i;0,s²) + (1−π)·N(z_i;0,κs²))

M-step (両成分が共有する s² の解析解; κ は固定なので閉形式で解ける):
    w_eff_i = γ_i + (1 − γ_i)/κ
    s²_new  = Σ w_eff_i·z_i² / Σ w_eff_i
    π_new   = mean(γ_i)

収束判定は ``s`` の相対変化 ``|s_new − s_old| / max(s_old, eps) < rtol`` が
``max_iterations`` 以内に成立するかで行う。乱数は一切使わず初期値も固定
(``s²_0 = mean(z_i²)``, ``π_0 = initial_inlier_fraction``) のため、同一入力に対し
常にビット同一の結果を返す (NFR-102)。

🟡 信頼性レベル: FR-123 は「EM 反復」を要求するのみで具体的な混合モデルは指定しない
ため、外れ値ロバスト性を EM で意味づけるための設計判断 (混合モデル・κ 既定値等)
は本実装の裁量である。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_TWO_PI = 2.0 * math.pi
# 【log(0) 回避】: π/(1-π) が数値的に 0 に張り付いても math.log が例外を出さないための下限 🔵
_LOG_EPS = 1e-300
# 【指数オーバーフロー回避】: シグモイドの指数引数をこの範囲へクリップする (float64 で安全) 🔵
_EXP_CLIP = 700.0


@dataclass(frozen=True)
class NoiseEstimate:
    """EM 推定によるノイズスケール ``s`` の結果 (FR-123)。

    ``scale`` は統計重み ``w_i`` を分散モデル ``Var(ε_i) = s²/w_i`` の下で解釈した
    ときのグローバルなスケール因子。``scale=1.0`` は「既存の重みがそのまま分散を
    表す」既定仮定 (現行 BIC/AIC の暗黙の前提) に一致する。

    Attributes:
        scale: 推定されたノイズスケール s (> 0)。
        n_iterations: 実行した EM 反復回数 (収束判定を満たした回・打ち切りとも含む)。
        converged: 収束判定 (相対変化 < rtol) を反復上限内に満たしたか。
        inlier_fraction: 収束時点の混合比 π (inlier とみなされた点の推定割合)。
        degenerate_reason: 入力が構造的に推定不能だった理由 (NFR-107 の由来明示)。
            通常の「反復上限到達で未収束」は ``converged=False`` かつ
            ``degenerate_reason=None`` で表す (再試行/反復数増で改善しうる)。
            空入力・全点非有限/非正重み・残差が厳密に全ゼロ、のように EM の実行
            自体が意味を持たない場合のみ理由文字列を設定する。
    """

    scale: float
    n_iterations: int
    converged: bool
    inlier_fraction: float
    degenerate_reason: str | None = None


def _degenerate(reason: str, *, inlier_fraction: float) -> NoiseEstimate:
    """縮退入力向けの既定 NoiseEstimate を組み立てる (scale=1.0 は「補正なし」に中立)。"""
    return NoiseEstimate(
        scale=1.0,
        n_iterations=0,
        converged=False,
        inlier_fraction=inlier_fraction,
        degenerate_reason=reason,
    )


def estimate_noise_em(
    residuals: np.ndarray,
    weights: np.ndarray,
    *,
    outlier_inflation: float = 25.0,
    initial_inlier_fraction: float = 0.9,
    max_iterations: int = 50,
    rtol: float = 1e-6,
) -> NoiseEstimate:
    """観測–計算残差と統計重みから外れ値混合 EM でノイズスケール s を推定する。

    【機能概要】: モジュール docstring の E-step/M-step を反復し、``NoiseEstimate``
      を返す numpy-only の純関数。乱数不使用・初期値固定で決定論的 (NFR-102)。
    【入力の頑健化】: 非有限な残差/重み・非正重みの点は推定対象から除外する
      (1 点でも壊れていれば全体を諦めるのではなく、有効点のみで推定を続行する)。
      除外後に有効点が 0 件、または残差が厳密に全ゼロ (分散推定不能) の場合は
      明示的な縮退値 (``scale=1.0``, ``converged=False`` + 理由) を返す。
    🟡 信頼性レベル: 混合モデルの定式化はモジュール docstring 参照 (設計裁量)。

    Args:
        residuals: 観測–計算残差 ``y_obs - y_calc`` (生の値、重み適用前)。
        weights: 各点の統計重み ``w_i`` (分散モデル ``Var(ε_i) = s²/w_i``)。
        outlier_inflation: 外れ値成分の分散膨張率 κ (> 1)。既定 25 (標準偏差 5 倍)。
        initial_inlier_fraction: π の初期値。既定 0.9 (大半が inlier という弱い事前)。
        max_iterations: EM 反復回数の上限。既定 50。
        rtol: 収束判定の相対変化閾値 (s の変化率)。既定 1e-6。

    Returns:
        推定結果 ``NoiseEstimate``。

    Raises:
        ValueError: ``residuals``/``weights`` の形状が一致しない、または
            ``max_iterations < 1`` (呼び出し側の契約違反、データの縮退とは区別する)。
    """
    if max_iterations < 1:
        raise ValueError(f"max_iterations は 1 以上である必要があります: {max_iterations!r}")

    residuals_arr = np.asarray(residuals, dtype=float)
    weights_arr = np.asarray(weights, dtype=float)
    if residuals_arr.shape != weights_arr.shape:
        raise ValueError(
            "residuals と weights の形状が一致しません: "
            f"{residuals_arr.shape!r} vs {weights_arr.shape!r}"
        )

    # 【有効点フィルタ】: 非有限な残差/重み・非正重みの点を除外する (壊れた点の混入排除) 🔵
    finite_mask = np.isfinite(residuals_arr) & np.isfinite(weights_arr) & (weights_arr > 0.0)
    r = residuals_arr[finite_mask]
    w = weights_arr[finite_mask]
    n_eff = int(r.size)
    if n_eff == 0:
        return _degenerate(
            "有効な点が存在しません (空入力、または全点が非有限/非正重み)。",
            inlier_fraction=0.0,
        )

    z = np.sqrt(w) * r
    sum_sq = float(np.sum(z * z))
    if sum_sq <= 0.0:
        # 【全ゼロ残差】: 分散 0 は Gaussian 対数密度が定義できない (log(0)) ため推定を諦める 🔵
        return _degenerate(
            "残差が全てゼロで分散を推定できません (退化した入力)。",
            inlier_fraction=1.0,
        )

    kappa = max(float(outlier_inflation), 1.0 + 1e-9)  # 【下限】: 2 成分が退化しない保証 🔵
    s2 = sum_sq / n_eff  # 【初期値】: 素朴な平均二乗 (混合前の naive scale²)。固定・決定論 🔵
    pi = min(max(float(initial_inlier_fraction), 1e-6), 1.0 - 1e-6)

    converged = False
    n_iterations = 0
    for iteration in range(1, max_iterations + 1):
        n_iterations = iteration
        # --- E-step: 責任 γ_i (inlier 事後確率) を対数領域で安定に計算する ---
        log_n1 = -0.5 * np.log(_TWO_PI * s2) - z * z / (2.0 * s2)
        log_n2 = -0.5 * np.log(_TWO_PI * kappa * s2) - z * z / (2.0 * kappa * s2)
        log_p1 = math.log(max(pi, _LOG_EPS)) + log_n1
        log_p2 = math.log(max(1.0 - pi, _LOG_EPS)) + log_n2
        diff = np.clip(log_p1 - log_p2, -_EXP_CLIP, _EXP_CLIP)
        gamma1 = 1.0 / (1.0 + np.exp(-diff))  # 【シグモイド】: logistic(log_p1 - log_p2) 🔵

        # --- M-step: 共有スケール s² の解析解 + 混合比 π の更新 ---
        w_eff = gamma1 + (1.0 - gamma1) / kappa
        sum_w_eff = float(np.sum(w_eff))
        s2_new = float(np.sum(w_eff * z * z) / sum_w_eff)
        pi_new = float(np.mean(gamma1))

        s_old = math.sqrt(s2)
        s_new = math.sqrt(max(s2_new, 0.0))
        rel_change = abs(s_new - s_old) / max(s_old, 1e-12)
        s2, pi = s2_new, pi_new
        if rel_change < rtol:
            converged = True
            break

    return NoiseEstimate(
        scale=math.sqrt(max(s2, 0.0)),
        n_iterations=n_iterations,
        converged=converged,
        inlier_fraction=pi,
        degenerate_reason=None,
    )
