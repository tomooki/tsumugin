"""動的スコア閾値 — 変曲点検出 (仕様 §5 / Dara find_optimal_score_threshold 準拠)。

候補相のマッチスコア分布を「良い相」と「無関係な相」に分ける閾値を、固定件数 (top-k) でなく
**スコア分布の変曲点** で動的に決める。パーセンタイル曲線を平滑化し、2階微分が最大 (スコアが最も
急に良→悪へ変わる位置) となる点を境界とする。良い相を件数に依らず残すため、正解を取りこぼしにくい。

numpy のみで実装 (scipy 非依存)。Savitzky-Golay (polyorder=1) は等価な中心移動平均で代替する。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = ["inflection_threshold"]


def _smooth5(y: np.ndarray) -> np.ndarray:
    """幅 5 の中心移動平均 (Savitzky-Golay polyorder=1 window=5 と等価)。端は窓縮小。🔵"""
    n = y.size
    out = np.empty_like(y)
    for i in range(n):
        lo = max(0, i - 2)
        hi = min(n, i + 3)
        out[i] = y[lo:hi].mean()
    return out


def inflection_threshold(scores: Sequence[float], *, tolerance: float = 0.01) -> float:
    """スコア分布の変曲点を動的閾値として返す (Dara find_optimal_score_threshold)。🔵

    Args:
        scores: 候補相のマッチスコア列。
        tolerance: 閾値からわずかに引く余裕 (既定 0.01, 境界の相を落とさないため)。

    Returns:
        動的閾値。空入力は 0.0。単一/極少数は最小値付近 - tolerance へ縮退する。
    """
    arr = np.asarray(list(scores), dtype=float)
    if arr.size == 0:
        return 0.0
    if arr.size == 1:
        return float(arr[0]) - tolerance

    # 【パーセンタイル曲線】: 0..100 パーセンタイル (常に 101 点) を取り分布形状を正規化する 🔵
    pct = np.percentile(arr, np.arange(0, 101))
    pct = _smooth5(pct)

    # 【変曲点】: 2階微分 (99 点) が最大 = スコアが最も急に良→悪へ変わる位置。
    #   ``np.diff(pct, n=2)[k]`` は ``pct[k+1]`` 中心の曲率なので、変曲点 (膝) の percentile index は
    #   ``idx+1``。ここでは ``pct[idx]`` (膝の 1 つ下) を採る: Dara 公開実装
    #   (find_optimal_score_threshold: ``score_percentile[argmax(second_derivative)]``) と一致し、かつ
    #   閾値をわずかに低め=包摂的にして境界付近の正解相を落とさない (過剰包摂の junk は木探索の
    #   Rwp/BIC + 強 extra 罰が落とす)。``-tolerance`` でさらに包摂側へ寄せる。🔵
    second_derivative = np.diff(pct, n=2)
    idx = int(np.argmax(second_derivative))
    return float(pct[idx]) - tolerance
