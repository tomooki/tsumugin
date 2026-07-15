"""残差の構造分解 (第2層 → 第3層への入力, Issue #83)。

実解析 (K₂Mn[Fe(CN)₆] operando 等) で次の一手を決めるのに有効だった残差分解を、決定論の
numpy ルーチンとして提供する。**診断・提案のみを行い、精密化状態を一切変更しない** (非破壊;
CLAUDE.md 不変条件)。

- **baseline/peak 分子寄与比**: Rwp の分子 (Σw(yo-yc)²) のうちどれだけが baseline (背景減算後の
  ノイズ底) 由来かを見る。実測: 「Rwp 26% の分子の 53% は背景減算ノイズで不可避」= モデルでは
  下げられないと確定でき、Rwp を追うのをやめてデータ (背景減算前データの使用) に着手できた。
- **角度ビン別 Rwp**: misfit がブラッグ域 (例 6-12°) に集中していれば、背景でなくその域の
  ピークモデル (プロファイル/相) の問題と判定できる。
- **上位 |obs-calc| 特徴 (2θ, 符号)**: 未説明ピーク位置 (符号が正 = calc 不足) は欠落相の同定に
  直結する (実測: 5.7°/10.9° の未説明特徴から cubic 相の追加が判明)。

numpy のみで完結する (CLAUDE.md 不変条件: コア import は numpy のみ)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Sequence

import numpy as np

if TYPE_CHECKING:
    from .model import AutoRietveldResult


@dataclass(frozen=True)
class ResidualFeature:
    """上位 |obs-calc| 特徴 1 件 (不変)。

    :param two_theta: 特徴の位置 (2θ または TOF; `x` と同じ単位)
    :param residual: obs - calc (符号付き)。正 = calc 不足 = 未説明強度 (欠落相の疑い)
    :param obs: その点の観測強度
    """

    two_theta: float
    residual: float
    obs: float


@dataclass(frozen=True)
class ResidualReport:
    """`residual_report` の分解結果 (不変)。

    :param rwp: 全域 Rwp (%)
    :param peak_only_rwp: ピーク域点のみの Rwp (%)。ピーク域点が 1 点もない退化ケース
        (データが完全にフラット等) は 0.0 (定義不能の意で 0)。
    :param baseline_numerator_fraction: Rwp 分子 (Σw(yo-yc)²) に占める baseline 点の寄与比
        (0-1)。高い場合、Rwp はモデルでなく背景減算ノイズに律速されており、モデル改善では
        下げられないことを示す。分子が全域で 0 (完全一致) の場合は 0.0 に縮退する。
    :param peak_numerator_fraction: 1 - baseline_numerator_fraction
    :param angular_rwp: `(下限, 上限, Rwp)` のビン別列 (`n_bins` 等分割)。点が 0 または重み付き
        分母が 0 のビンはスキップする。misfit が特定域に集中していれば、そこがピークモデルの
        問題箇所であって背景の問題ではないと判定できる。
    :param top_features: 上位 |obs-calc| 特徴 (`feature_min_separation` で近接統合済み・降順、
        最大 `n_features` 件)
    """

    rwp: float
    peak_only_rwp: float
    baseline_numerator_fraction: float
    peak_numerator_fraction: float
    angular_rwp: tuple[tuple[float, float, float], ...]
    top_features: tuple[ResidualFeature, ...]


def _rwp(w: np.ndarray, yo: np.ndarray, yc: np.ndarray) -> float:
    """Rwp(%) = 100·sqrt(Σw(yo-yc)² / Σw·yo²)。分母が 0 以下 (無強度) は 0.0 に縮退する。"""
    denom = float(np.sum(w * yo * yo))
    if denom <= 0.0:
        return 0.0
    numer = float(np.sum(w * (yo - yc) ** 2))
    return 100.0 * float(np.sqrt(numer / denom))


def residual_report(
    x: "Sequence[float] | np.ndarray",
    yobs: "Sequence[float] | np.ndarray",
    ycalc: "Sequence[float] | np.ndarray",
    weight: "Sequence[float] | np.ndarray | None" = None,
    *,
    baseline_cut: float | None = None,
    baseline_k: float = 3.0,
    n_bins: int = 5,
    n_features: int = 6,
    feature_min_separation: float = 0.15,
) -> ResidualReport:
    """残差 (obs-calc) を baseline/peak 寄与・角度ビン・上位特徴に機械的に分解する。

    :param x: 2θ (または TOF) 配列
    :param yobs: 観測強度
    :param ycalc: 計算強度
    :param weight: Rwp の重み。None (既定) なら計数統計慣習 `w = 1/max(yobs, 1)` (esd=√I) を
        自動導出する (`tsumugin.autorietveld.dataquality` の esd 慣習と同一)
    :param baseline_cut: `yobs < baseline_cut` を満たす点を baseline とみなす閾値。None (既定)
        なら `median(yobs) + baseline_k * 1.4826·MAD(yobs)` から自動決定する。XRD パターンは
        大半の点が背景 (フラット/なだらか) でピークは疎という典型構造を前提に、ロバスト分散
        (MAD ベース) から明確に外れる点のみを "peak" とみなすヒューリスティックである。
        データが完全にフラット (MAD=0, ピークなし) の場合は `max(yobs)+1` を用いて全点を
        baseline とみなす (縮退)。
    :param baseline_k: 上記自動閾値の MAD 倍率 (既定 3.0)
    :param n_bins: 角度ビン別 Rwp の等分割数
    :param n_features: 上位特徴の最大件数
    :param feature_min_separation: 上位特徴の近接統合の距離閾値 (`x` と同じ単位)。この距離未満で
        隣接する特徴は |obs-calc| が大きい方のみを残す
    :returns: `ResidualReport`
    :raises ValueError: `x`/`yobs`/`ycalc`/`weight` の長さが一致しない場合。空配列自体は
        エラーとせず、全フィールドが空/0 の `ResidualReport` に縮退する。
    """
    x_arr = np.asarray(x, dtype=float)
    yo_arr = np.asarray(yobs, dtype=float)
    yc_arr = np.asarray(ycalc, dtype=float)

    if not (x_arr.size == yo_arr.size == yc_arr.size):
        raise ValueError(
            "x/yobs/ycalc の長さが一致しません: "
            f"{x_arr.size}/{yo_arr.size}/{yc_arr.size}"
        )

    if weight is not None:
        w_arr = np.asarray(weight, dtype=float)
        if w_arr.size != x_arr.size:
            raise ValueError(f"weight の長さが x と一致しません: {w_arr.size} != {x_arr.size}")
    else:
        w_arr = 1.0 / np.maximum(yo_arr, 1.0)

    if x_arr.size == 0:
        return ResidualReport(
            rwp=0.0,
            peak_only_rwp=0.0,
            baseline_numerator_fraction=0.0,
            peak_numerator_fraction=0.0,
            angular_rwp=(),
            top_features=(),
        )

    rwp = _rwp(w_arr, yo_arr, yc_arr)

    if baseline_cut is None:
        med = float(np.median(yo_arr))
        mad = float(np.median(np.abs(yo_arr - med)))
        robust_std = 1.4826 * mad
        if robust_std > 0.0:
            baseline_cut = med + baseline_k * robust_std
        else:
            baseline_cut = float(np.max(yo_arr)) + 1.0  # フラット (ピークなし): 全点 baseline

    baseline_mask = yo_arr < baseline_cut
    peak_mask = ~baseline_mask

    numerator_total = float(np.sum(w_arr * (yo_arr - yc_arr) ** 2))
    if numerator_total > 0.0:
        baseline_numer = float(
            np.sum(w_arr[baseline_mask] * (yo_arr[baseline_mask] - yc_arr[baseline_mask]) ** 2)
        )
        baseline_fraction = baseline_numer / numerator_total
    else:
        baseline_fraction = 0.0  # 全域完全一致: 寄与比は定義不能なので 0 に縮退
    peak_fraction = 1.0 - baseline_fraction

    if np.any(peak_mask):
        peak_only_rwp = _rwp(w_arr[peak_mask], yo_arr[peak_mask], yc_arr[peak_mask])
    else:
        peak_only_rwp = 0.0  # ピーク域点が 1 点もない (定義不能)

    # --- 角度ビン別 Rwp ---
    bins: list[tuple[float, float, float]] = []
    x_min, x_max = float(np.min(x_arr)), float(np.max(x_arr))
    if x_max > x_min and n_bins > 0:
        edges = np.linspace(x_min, x_max, n_bins + 1)
        for i in range(n_bins):
            lo, hi = float(edges[i]), float(edges[i + 1])
            if i == n_bins - 1:
                in_bin = (x_arr >= lo) & (x_arr <= hi)
            else:
                in_bin = (x_arr >= lo) & (x_arr < hi)
            if not np.any(in_bin):
                continue
            bin_denom = float(np.sum(w_arr[in_bin] * yo_arr[in_bin] ** 2))
            if bin_denom <= 0.0:
                continue
            bins.append((lo, hi, _rwp(w_arr[in_bin], yo_arr[in_bin], yc_arr[in_bin])))
    angular_rwp = tuple(bins)

    # --- 上位特徴 (降順・近接統合) ---
    resid = yo_arr - yc_arr
    order = np.argsort(-np.abs(resid))
    selected: list[int] = []
    selected_x: list[float] = []
    for idx in order:
        xi = float(x_arr[idx])
        if any(abs(xi - sx) < feature_min_separation for sx in selected_x):
            continue
        selected.append(int(idx))
        selected_x.append(xi)
        if len(selected) >= n_features:
            break

    top_features = tuple(
        ResidualFeature(two_theta=float(x_arr[i]), residual=float(resid[i]), obs=float(yo_arr[i]))
        for i in selected
    )

    return ResidualReport(
        rwp=rwp,
        peak_only_rwp=peak_only_rwp,
        baseline_numerator_fraction=baseline_fraction,
        peak_numerator_fraction=peak_fraction,
        angular_rwp=angular_rwp,
        top_features=top_features,
    )


def residual_report_from_result(
    result: "AutoRietveldResult", **kwargs: object
) -> "ResidualReport | None":
    """`AutoRietveldResult` から `residual_report` を組み立てる薄いアダプタ。

    `AutoRietveldResult.residual_intensity` は **obs-calc (残差そのもの)** であり、
    `residual_sigma` は計数統計 σ (`= 1/√yweight`) である。ycalc・yobs 単体は保持されて
    いない (`autorietveld.engine._extract_residual` 参照: `getdata('Residual')`=obs-calc,
    `getdata('yweight')`=1/σ² を計数統計の重みとして詰めている)。GSAS の yweight は計数統計
    慣習 (w=1/yobs, すなわち σ²≈yobs) に基づくため、`yobs ≈ residual_sigma**2` として近似
    復元する — これは `residual_report` 自身の既定重み `w=1/max(yobs,1)` と同じ慣習であり、
    整合的な近似である。`ycalc = yobs - residual` として逆算する。

    **この復元は近似である** (GSAS 内部の重みに床/クランプ等の別処理が入っている場合は
    誤差が乗る)。真の yobs/ycalc の記録ではなく、σ からの逆算値である点に注意すること。

    `residual_sigma` が非有限 (inf; `yweight=0` = 精密化から除外された点) または 0 以下の
    点は復元不能として除外する。有効点が 1 点も残らない、またはフィールドが空/長さ不一致
    (後方互換の既定空タプル等) の場合は復元不能として `None` を返す。

    :param result: `AutoRietveldResult` (先頭ヒストグラムの残差フィールドを使用)
    :param kwargs: `residual_report` へ渡す追加キーワード引数 (`baseline_cut` 等)
    :returns: `ResidualReport`。復元不能なら `None`
    """
    x = np.asarray(result.residual_two_theta, dtype=float)
    resid = np.asarray(result.residual_intensity, dtype=float)
    sigma = np.asarray(result.residual_sigma, dtype=float)

    if x.size == 0 or resid.size != x.size or sigma.size != x.size:
        return None

    finite = np.isfinite(sigma) & (sigma > 0.0)
    if not np.any(finite):
        return None

    x = x[finite]
    resid = resid[finite]
    sigma = sigma[finite]

    yobs = sigma**2
    ycalc = yobs - resid

    return residual_report(x, yobs, ycalc, **kwargs)
