"""ノイズ標準偏差の EM 推定 (FR-123)。

観測–計算残差 ``ε_i = y_obs_i − y_calc_i`` と既存の統計重み ``w_i`` から、
    ``ε_i ~ N(0, s² / w_i)``
の下でグローバルなノイズスケール ``s`` を推定する。単純な閉形式 ``s² = χ²/n``
(``χ² = Σ w_i ε_i²``) は 1 反復で確定し「EM 反復」にならない上、未モデルピーク・
不良点 (bad point) が紛れ込むとそのまま推定値を汚染する。そこで本モジュールは
**2 成分の外れ値混合モデル**として EM を実装する:

    z_i = sqrt(w_i) · ε_i                              (統計重みで正規化した残差)
    z_i ~ π · N(0, s²) + (1 − π) · N(0, v_out)          (混合比 π, 外れ値成分の分散 v_out)

inlier 成分 (責任 ``π``) は既存の重みモデルに従う「素直な」観測点、outlier 成分
(責任 ``1 − π``) は「重みモデルから外れた」観測点 (未モデルピーク・スパイク・検出器不良等)
を表す。

**外れ値成分の分散 v_out は s に紐付けず凍結する** (旧実装の設計不備の是正)。凍結しない場合、
外れ値の残差二乗が M-step の分母 (Σw_eff) へ ``1/κ`` の床を通じて線形に混入し、単発の巨大スパイク
1 点だけでも s を大きく汚染しうる (実測: spike=2000 相当で s が真値の約 33 倍に汚染)。これを防ぐため、
反復開始前に一度だけ**ロバストな初期スケール** s₀ を weighted MAD (中央絶対偏差)
``s₀ = median(|z|) / 0.6745`` (0.6745 は正規分布の一貫性定数 Φ⁻¹(0.75)) で求め、
``v_out = κ·s₀²`` (κ > 1: 既定 25, 標準偏差比 5 倍) を **反復中ずっと固定**する。中央値は外れ値の
混入率が 50% 未満なら頑健 (breakdown point 0.5) なため、s₀ 自体は汚染にほぼ影響されない。

E-step (responsibility, 各点が inlier である事後確率。対数領域で安定に計算する):
    γ_i = π·N(z_i;0,s²) / (π·N(z_i;0,s²) + (1−π)·N(z_i;0,v_out))

M-step (**inlier-only** の標準的な混合ガウス成分分散 MLE。outlier 成分のパラメータは更新しない):
    s²_new  = Σ γ_i·z_i² / Σ γ_i
    π_new   = mean(γ_i)

(旧実装は外れ値分散を ``κ·s²`` として s と連動させ、M-step の分母を ``Σw_eff`` (w_eff = γ + (1−γ)/κ)
としていたが、これは正しい混合ガウス MLE ではなく (a) 分母が有効点数 n を系統的に下回り s² を
過大評価する (実測: 30% 外れ値で naive 推定に対し ±10% 以内の想定に反し約 27% 過大)、(b) 外れ値
1 点でも ``w_eff`` の ``1/κ`` 床を通じて s² が線形に汚染される、という 2 つの欠陥を持っていた。
本モデルは v_out を凍結し M-step を inlier-only にすることでこの両方を解消する。)

収束判定は ``s`` の相対変化 ``|s_new − s_old| / max(s_old, eps) < rtol`` が
``max_iterations`` 以内に成立するかで行う。乱数は一切使わず初期値も固定
(``s²_0 = s₀²`` (weighted MAD 由来), ``π_0 = initial_inlier_fraction``) のため、同一入力に対し
常にビット同一の結果を返す (NFR-102)。

**不変条件 (degenerate フォールバック)**: ``NoiseEstimate.scale`` は常に有限かつ正である。
以下のいずれかに該当し構造的に推定不能な場合は、``scale=1.0`` (「補正なし」に中立) +
``converged=False`` + ``degenerate_reason`` 非 None のフォールバック値を返す (例外を投げない):

- 空入力、または全点が非有限/非正重み (有効点 0 件)。
- z² (= 重み付き残差二乗) がオーバーフロー等で非有限になる点をフィルタした結果、有効点が 0 件。
- 残差が厳密に全ゼロ (分散推定不能)。
- 初期スケール s₀² または M-step 中の s² が下限フロア ``_FLOOR_S2`` (1e-150) を割る
  (``degenerate_reason`` に ``"scale_underflow"`` タグを含める)。極小残差 (subnormal 相当) が
  下流の 1/s² 計算で数値破綻するのを未然に防ぐ。
- 反復終了後の最終 s が非有限または非正 (上記いずれのガードもすり抜けた場合の最終防衛線)。

🟡 信頼性レベル: FR-123 は「EM 反復」を要求するのみで具体的な混合モデルは指定しないため、
外れ値ロバスト性を EM で意味づけるための設計判断 (混合モデル・κ 既定値・v_out 凍結・floor 値等)
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
# 【weighted MAD の一貫性定数】: 正規分布で MAD を標準偏差に換算する Φ⁻¹(0.75) 🔵
_MAD_CONSISTENCY = 0.6745
# 【s² 下限フロア】: これを割ったら「subnormal 相当」とみなし degenerate へ縮退する (Issue #64
#   レビュー対応)。1/s² を使う下流計算 (BIC 等) が数値破綻する前に明示的に諦める 🟡 設計裁量。
_FLOOR_S2 = 1e-150


@dataclass(frozen=True)
class NoiseEstimate:
    """EM 推定によるノイズスケール ``s`` の結果 (FR-123)。

    ``scale`` は統計重み ``w_i`` を分散モデル ``Var(ε_i) = s²/w_i`` の下で解釈した
    ときのグローバルなスケール因子。``scale=1.0`` は「既存の重みがそのまま分散を
    表す」既定仮定 (現行 BIC/AIC の暗黙の前提) に一致する。

    Attributes:
        scale: 推定されたノイズスケール s。常に有限かつ ``> 0`` (不変条件、モジュール
            docstring 参照)。構造的に推定不能なときは ``1.0`` (補正なしに中立)。
        n_iterations: 実行した EM 反復回数 (収束判定を満たした回・打ち切りとも含む)。
        converged: 収束判定 (相対変化 < rtol) を反復上限内に満たしたか。
        inlier_fraction: 収束時点の混合比 π (inlier とみなされた点の推定割合)。
        degenerate_reason: 入力が構造的に推定不能だった理由 (NFR-107 の由来明示)。
            通常の「反復上限到達で未収束」は ``converged=False`` かつ
            ``degenerate_reason=None`` で表す (再試行/反復数増で改善しうる)。
            空入力・全点非有限/非正重み・z² オーバーフロー・残差が厳密に全ゼロ・
            s² 下限フロア割れ (``"scale_underflow"`` タグ付き)、のように EM の実行
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
      z² (重み付き残差二乗) がオーバーフロー等で非有限になる点も同様に除外する。除外後に
      有効点が 0 件、または残差が厳密に全ゼロ (分散推定不能)、または初期/中間の s² が
      下限フロアを割る場合は、明示的な縮退値 (``scale=1.0``, ``converged=False`` + 理由)
      を返す (モジュール docstring の不変条件を参照)。
    🟡 信頼性レベル: 混合モデルの定式化はモジュール docstring 参照 (設計裁量)。

    Args:
        residuals: 観測–計算残差 ``y_obs - y_calc`` (生の値、重み適用前)。
        weights: 各点の統計重み ``w_i`` (分散モデル ``Var(ε_i) = s²/w_i``)。
        outlier_inflation: 外れ値成分の分散膨張率 κ (> 1)。既定 25 (標準偏差 5 倍)。
            ``v_out = κ·s₀²`` (s₀ は初期ロバストスケール, weighted MAD) として反復中固定する。
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
    # 【効率 (Issue #64 レビュー対応)】: 全点有効ならフィルタ用の配列コピーを省く 🟡
    finite_mask = np.isfinite(residuals_arr) & np.isfinite(weights_arr) & (weights_arr > 0.0)
    if np.all(finite_mask):
        r, w = residuals_arr, weights_arr
    else:
        r = residuals_arr[finite_mask]
        w = weights_arr[finite_mask]
    if r.size == 0:
        return _degenerate(
            "有効な点が存在しません (空入力、または全点が非有限/非正重み)。",
            inlier_fraction=0.0,
        )

    # 【z² の巻き上げ (Issue #64 レビュー対応・効率)】: EM ループの外で 1 回だけ計算する。
    #   極端な入力 (残差 1e200 等) は二乗でオーバーフローしうるが、これは後続で非有限として
    #   明示的に除外するため、numpy の RuntimeWarning は意図的に抑制する 🟡
    with np.errstate(over="ignore", invalid="ignore"):
        z = np.sqrt(w) * r
        z2 = z * z

    # 【オーバーフロー点の除外】: z² が非有限 (例: 残差 1e200 の二乗はオーバーフローで inf) な点は
    #   推定不能なので除外する。除外後に点が残らなければ縮退する (Issue #64 レビュー対応) 🟡
    finite_z2 = np.isfinite(z2)
    if not np.all(finite_z2):
        z = z[finite_z2]
        z2 = z2[finite_z2]
    n_eff = int(z2.size)
    if n_eff == 0:
        return _degenerate(
            "全点の z² (重み付き残差二乗) が非有限 (オーバーフロー) のため推定できません。",
            inlier_fraction=0.0,
        )

    sum_sq = float(np.sum(z2))
    if sum_sq <= 0.0:
        # 【全ゼロ残差】: 分散 0 は Gaussian 対数密度が定義できない (log(0)) ため推定を諦める 🔵
        return _degenerate(
            "残差が全てゼロで分散を推定できません (退化した入力)。",
            inlier_fraction=1.0,
        )

    kappa = max(float(outlier_inflation), 1.0 + 1e-9)  # 【下限】: 2 成分が退化しない保証 🔵

    # 【初期ロバストスケール s₀ (weighted MAD)】: 中央値は外れ値混入率 50% 未満で頑健なため、
    #   naive な mean(z²) よりも汚染に強い初期値になる 🟡 設計裁量 (モジュール docstring 参照)。
    mad = float(np.median(np.abs(z)))
    s0 = mad / _MAD_CONSISTENCY
    if not math.isfinite(s0) or s0 <= 0.0:
        # 【MAD 退化】: 過半数の点が厳密ゼロ等で MAD=0 になる稀なケースは naive scale へ縮退する 🟡
        s0 = math.sqrt(sum_sq / n_eff)

    s2 = s0 * s0
    if not math.isfinite(s2) or s2 <= _FLOOR_S2:
        return _degenerate(
            f"scale_underflow: 初期スケール s0²={s2!r} が下限フロア {_FLOOR_S2:.1e} を"
            " 下回りました (残差が subnormal 相当)。",
            inlier_fraction=1.0,
        )

    # 【外れ値分散の凍結】: v_out = κ·s0² を反復中ずっと固定する (モジュール docstring 参照) 🔵
    v_out = kappa * s2
    if not math.isfinite(v_out):
        return _degenerate(
            "scale_underflow: 外れ値分散 v_out=κ·s0² が非有限 (オーバーフロー) です。",
            inlier_fraction=1.0,
        )

    pi = min(max(float(initial_inlier_fraction), 1e-6), 1.0 - 1e-6)

    converged = False
    n_iterations = 0
    for iteration in range(1, max_iterations + 1):
        n_iterations = iteration
        # --- E-step: 責任 γ_i (inlier 事後確率) を対数領域で安定に計算する (v_out は固定) ---
        log_n1 = -0.5 * np.log(_TWO_PI * s2) - z2 / (2.0 * s2)
        log_n2 = -0.5 * np.log(_TWO_PI * v_out) - z2 / (2.0 * v_out)
        log_p1 = math.log(max(pi, _LOG_EPS)) + log_n1
        log_p2 = math.log(max(1.0 - pi, _LOG_EPS)) + log_n2
        diff = np.clip(log_p1 - log_p2, -_EXP_CLIP, _EXP_CLIP)
        gamma = 1.0 / (1.0 + np.exp(-diff))  # 【シグモイド】: logistic(log_p1 - log_p2) 🔵

        # --- M-step: inlier-only の標準的な混合ガウス成分分散 MLE (v_out/outlier は更新しない) ---
        sum_gamma = float(np.sum(gamma))
        if sum_gamma <= 0.0:
            # 【全点が外れ値責任】: 分母 0 は定義不能なため、直前の有効な s2 を保持して打ち切る
            #   (構造的な推定不能 = degenerate ではなく、極端な責任分布による早期停止) 🟡
            break
        s2_new = float(np.sum(gamma * z2) / sum_gamma)
        pi_new = float(np.mean(gamma))

        if not math.isfinite(s2_new) or s2_new <= _FLOOR_S2:
            return _degenerate(
                f"scale_underflow: M-step の s²={s2_new!r} が下限フロア {_FLOOR_S2:.1e}"
                " を下回りました。",
                inlier_fraction=pi_new,
            )

        s_old = math.sqrt(s2)
        s_new = math.sqrt(s2_new)
        rel_change = abs(s_new - s_old) / max(s_old, 1e-12)
        s2, pi = s2_new, pi_new
        if rel_change < rtol:
            converged = True
            break

    # 【最終防衛線 (Issue #64 レビュー対応)】: 上記いずれのガードもすり抜けた場合でも、最終 s の
    #   isfinite/>0 を検証してから返す。違反時は degenerate フォールバックで応答する 🟡
    s_final = math.sqrt(s2) if s2 > 0.0 else float("nan")
    if not math.isfinite(s_final) or s_final <= 0.0:
        return _degenerate(
            f"scale_underflow: 最終スケール s={s_final!r} が非有限または非正です。",
            inlier_fraction=pi,
        )

    return NoiseEstimate(
        scale=s_final,
        n_iterations=n_iterations,
        converged=converged,
        inlier_fraction=pi,
        degenerate_reason=None,
    )


def noise_extras(
    residuals: np.ndarray,
    weights: np.ndarray,
    *,
    enabled: bool,
    outlier_inflation: float = 25.0,
    initial_inlier_fraction: float = 0.9,
    max_iterations: int = 50,
    rtol: float = 1e-6,
) -> tuple[float | None, dict[str, float], tuple[str, ...]]:
    """opt-in の EM ノイズ推定を backend 非依存に実行するオーケストレーション共有関数 (Issue #64
    レビュー対応)。

    【機能概要】: ``RefinementResult.noise_scale``/``globals``/``warnings`` へそのまま代入できる
      3 つ組 ``(noise_scale, globals へ追加する dict, warnings へ追加する tuple)`` を返す。
      従来 ``SimulatedBackend._noise_estimate_extras``/``_noise_provenance_warning`` に実装が
      あったが、backend 実装から EM 推定のオーケストレーション (呼ぶか否かの判定・
      NoiseEstimate → globals/warnings への変換) を切り離し、将来の GSAS-II backend 配線が
      同一実装をそのまま再利用できるようにする (backend 固有の重複実装を避ける単一情報源化)。
    【enabled=False (既定と同じ後方互換経路)】: EM を一切呼ばず即座に ``(None, {}, ())`` を返す。
      呼び出し元はこの結果をそのまま ``globals``/``warnings``/``noise_scale`` へマージするだけで
      よく、無効時はビット同一の追加計算なし経路を保つ (REQ-404)。
    【noise_scale と globals["noise_scale"] の二重格納の正当化】: 両者は本関数を単一情報源として
      同じ ``estimate.scale`` から同時に組み立てられるため常に一致する (ドリフトしない)。
      ``RefinementResult.noise_scale`` は evidence/ic.py が直接読む型付き第一級フィールド、
      ``globals["noise_scale"]`` は webui 等が ``RefinementResult.globals`` を汎用的に走査する
      経路向けの汎用キー値ストアで、それぞれ異なる消費者に向けた表現である。
    【σ の由来明示 (NFR-107)】: 推定結果 (反復回数・収束可否・inlier 比率・縮退理由) を
      人間可読な警告文として記録し、ledger/レポートで追跡できるようにする。
    🟡 信頼性レベル: NFR-107 の要求 (由来明示) を既存の warnings/globals 様式へ最小追加すると
      いう設計裁量 (SimulatedBackend から抽出した既存実装の踏襲)。

    Args:
        residuals: 観測–計算残差 ``y_obs - y_calc``。
        weights: 各点の統計重み ``w_i`` (``estimate_noise_em`` が期待する分散モデルの重み)。
        enabled: EM 推定を実行するか (False なら即座に無効値を返す)。
        outlier_inflation: ``estimate_noise_em`` へそのまま渡す設定 (既定 25.0)。
        initial_inlier_fraction: 同上 (既定 0.9)。
        max_iterations: 同上 (既定 50)。
        rtol: 同上 (既定 1e-6)。

    Returns:
        ``enabled=False`` なら ``(None, {}, ())``。``True`` なら
        ``(estimate.scale, {"noise_scale": estimate.scale}, (由来文字列,))``。
    """
    if not enabled:
        return None, {}, ()
    estimate = estimate_noise_em(
        residuals,
        weights,
        outlier_inflation=outlier_inflation,
        initial_inlier_fraction=initial_inlier_fraction,
        max_iterations=max_iterations,
        rtol=rtol,
    )
    return (
        estimate.scale,
        {"noise_scale": estimate.scale},
        (_noise_provenance_warning(estimate),),
    )


def _noise_provenance_warning(estimate: NoiseEstimate) -> str:
    """``NoiseEstimate`` の由来を人間可読な警告文へ変換する (NFR-107 σ の由来明示)。"""
    text = (
        f"ノイズスケール EM 推定 (FR-123): s={estimate.scale:.4g}"
        f" (n_iterations={estimate.n_iterations}, converged={estimate.converged},"
        f" inlier_fraction={estimate.inlier_fraction:.4g})"
    )
    if estimate.degenerate_reason is not None:
        text += f"; 縮退: {estimate.degenerate_reason}"
    return text
