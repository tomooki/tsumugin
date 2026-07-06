"""観測ピーク検出 (FR-111)。

観測回折パターン ``(two_theta, intensity)`` から、局所極大かつ高さ閾値以上の点を
観測ピークとして抽出する純関数を提供する。numpy のみで実装し (scipy 非依存)、
乱数を使わず同一入力に同一出力を返す (NFR-102 決定論)。ドメイン的失敗 (ピークなし) は
例外化せず空タプルに縮退する (EDGE-003 / M0 規約)。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Peak:
    """観測 or 計算ピーク。FR-111 のマッチング単位。🔵"""

    position: float  # 2θ 位置 (度) 🔵
    height: float  # ピーク位置の観測強度 🔵
    # 計算ピークの Miller 指数 (h,k,l)。観測ピークや hkl 不明の供給元では None。異方格子整合
    # (Issue #20 hybrid: reference の top-K 異方 re-score) が使う。末尾・既定 None で後方互換。
    hkl: tuple[int, int, int] | None = None


def find_peaks(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    min_height_frac: float = 0.05,
) -> tuple[Peak, ...]:
    """局所極大 + 高さ閾値による観測ピーク検出。

    【機能概要】: 内部点 (端点を除く) のうち両隣より厳密に高く、かつ
      「最大強度 × min_height_frac」を厳密に超える点を観測ピークとして返す。
    【実装方針】: numpy のベクトル比較で局所極大マスクを作る。マスク式は
      tests/test_simulated_backend.py::_count_local_maxima と同一だが、あちらは
      simulate 出力を独立検証する count 専用オラクル (絶対 min_height を取る) のため、
      本関数への共通化はテストの独立性を損なうと判断し意図的に別実装のまま残す。🔵
    🔵 信頼性レベル: 局所極大式・EDGE-003 の空タプル縮退は要件定義に依拠 (順序昇順は 🟡)。

    Args:
        two_theta: 2θ 軸 (度)。1 次元・昇順・``intensity`` と同長。
        intensity: 各 2θ での観測強度。1 次元・``two_theta`` と同長。
        min_height_frac: 最大強度に対する検出下限比率 (キーワード専用, 既定 0.05)。

    Returns:
        ``position`` 昇順の不変タプル ``tuple[Peak, ...]``。検出ゼロなら空タプル ``()``。
    """
    # 【入力正規化】: float 配列へ揃え、以降の比較・除算を安定させる 🟡
    x = np.asarray(two_theta, dtype=float)
    y = np.asarray(intensity, dtype=float)

    # 【極小入力の縮退】: 長さ<3 は内部点が無く極大を定義できないため空を返す (例外化しない) 🟡
    if y.size < 3:
        return ()

    # 【高さ閾値】: max<=0 (全ゼロ/全負) は閾値計算が無意味なため安全に空へ縮退 (EDGE-003) 🔵
    max_height = float(y.max())
    if max_height <= 0.0:
        return ()
    min_height = min_height_frac * max_height

    # 【局所極大マスク】: 両隣より厳密に高く、かつ閾値を厳密超過する内部点のみ採用 (端点除外) 🔵
    interior = (y[1:-1] > y[:-2]) & (y[1:-1] > y[2:]) & (y[1:-1] > min_height)

    # 【ピーク生成】: 内部スライス基準の index を +1 で元配列へ復元し position 昇順の不変タプルを返す 🟡
    # flatnonzero は 1 次元の非ゼロ位置を昇順で直接返す (nonzero(...)[0] のタプル添字を省ける)
    indices = np.flatnonzero(interior) + 1
    return tuple(Peak(position=float(x[i]), height=float(y[i])) for i in indices)
