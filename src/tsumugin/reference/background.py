"""背景推定・減算 (SNIP 法) — 相同定の観測前処理 (仕様 §5)。

実測粉末パターンの遅変化バックグラウンド (蛍光・空気散乱・非晶質ハロー等) を SNIP
(Statistics-sensitive Non-linear Iterative Peak-clipping) で推定し減算する。numpy のみに依存し
乱数を使わず同一入力に同一出力を返す (NFR-102 決定論)。ピーク検出 (``find_peaks``) と
マッチ被覆率の前段で背景を除くことで、実データでのスコアと未マッチ判定を改善する。
"""

from __future__ import annotations

import numpy as np

__all__ = ["estimate_snip_background", "subtract_background"]


def _lls(y: np.ndarray) -> np.ndarray:
    """LLS 演算子 ln(ln(sqrt(y+1)+1)+1) — SNIP のダイナミクス圧縮。🔵"""
    return np.log(np.log(np.sqrt(np.maximum(y, 0.0) + 1.0) + 1.0) + 1.0)


def _inverse_lls(v: np.ndarray) -> np.ndarray:
    """LLS の逆変換 — 圧縮空間の背景を強度空間へ戻す。🔵"""
    return (np.exp(np.exp(v) - 1.0) - 1.0) ** 2 - 1.0


def estimate_snip_background(
    intensity: np.ndarray, *, max_window: int = 50
) -> np.ndarray:
    """SNIP 法で遅変化背景を推定する (FR-100 系・観測前処理)。🔵

    【アルゴリズム】: LLS 圧縮空間で窓幅 p を 1→max_window と増やしながら各点を
      ``min(v[i], (v[i-p]+v[i+p])/2)`` でクリップし、ピークを削り落として背景を残す。

    Args:
        intensity: 観測強度 (1 次元, 非負を想定)。
        max_window: 最大クリップ窓幅 (点数, キーワード専用)。広いピークほど大きく取る。

    Returns:
        推定背景 (``intensity`` と同形・非負)。
    """
    y = np.asarray(intensity, dtype=float)
    n = y.size
    if n == 0:
        return y.copy()
    v = _lls(y)
    m = max(1, min(int(max_window), (n - 1) // 2))
    # 【窓幅増加クリップ】: p=1..m で対称平均クリップを反復し背景を残す 🔵
    for p in range(1, m + 1):
        left = v[: n - 2 * p]
        right = v[2 * p:]
        clipped = np.minimum(v[p : n - p], 0.5 * (left + right))
        v = v.copy()
        v[p : n - p] = clipped
    background = _inverse_lls(v)
    return np.maximum(background, 0.0)


def subtract_background(
    intensity: np.ndarray, *, max_window: int = 50
) -> np.ndarray:
    """背景を推定し減算して非負へフロアした強度を返す (FR-100 系)。🔵

    Args:
        intensity: 観測強度 (1 次元)。
        max_window: SNIP の最大クリップ窓幅 (点数)。

    Returns:
        背景減算後の強度 (``intensity`` と同形・非負)。
    """
    y = np.asarray(intensity, dtype=float)
    background = estimate_snip_background(y, max_window=max_window)
    return np.maximum(y - background, 0.0)
