"""Kα2 二重線サテライトモデル — 参照ピークの実線源整合 (仕様 §5 FR-105)。

実験室 X線 (Cu/Mo 等) は Kα1/Kα2 の二重線で、各反射が 2 本のピークとして観測される。
``XRDCalculator`` は単一波長 (Kα1) でピークを生成するため、参照ピークに Kα2 サテライトを付加して
観測の二重線に整合させる。Bragg 則 λ=2d·sinθ より Kα2 (λ2>λ1) は高角側に、分裂は角度とともに拡大。
numpy 非依存・決定論的な純関数。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..search.peaks import Peak

__all__ = ["KAlpha2", "add_kalpha2_satellites"]

# Cu Kα の既定波長 (Å)。wavelength_ratio = λ2/λ1。
_CU_KA1 = 1.540562
_CU_KA2 = 1.544398


@dataclass(frozen=True)
class KAlpha2:
    """Kα2 サテライトの設定 (二重線モデル)。🔵 FR-105

    Attributes:
        intensity_ratio: Kα2/Kα1 の強度比 (既定 0.5, Cu の典型値)。
        wavelength_ratio: λ(Kα2)/λ(Kα1) (既定 Cu)。他線源はこの比を差し替える。
    """

    intensity_ratio: float = 0.5
    wavelength_ratio: float = _CU_KA2 / _CU_KA1


def add_kalpha2_satellites(
    peaks: Sequence[Peak], config: KAlpha2 = KAlpha2()
) -> tuple[Peak, ...]:
    """各ピークに Kα2 サテライト (高角側・強度比倍) を付加する (FR-105)。🔵

    【物理】: θ1 = (2θ1)/2, sinθ2 = (λ2/λ1)·sinθ1。sinθ2 ≤ 1 のときのみ 2θ2 = 2·asin(sinθ2)
      に強度 ``height × intensity_ratio`` のサテライトを足す。元の Kα1 ピークは保持する。

    Args:
        peaks: Kα1 参照ピーク列。
        config: Kα2 設定 (強度比・波長比)。

    Returns:
        Kα1 + Kα2 を含むピーク列 (位置昇順、元ピークは全保持)。空入力は空タプル。
    """
    out: list[Peak] = []
    ratio_l = config.wavelength_ratio
    ratio_i = config.intensity_ratio
    for peak in peaks:
        out.append(peak)
        theta1 = math.radians(peak.position / 2.0)
        sin_theta2 = ratio_l * math.sin(theta1)
        if 0.0 < sin_theta2 < 1.0:  # sinθ2≥1 は非物理 (極端高角) → サテライト無し 🔵
            two_theta2 = 2.0 * math.degrees(math.asin(sin_theta2))
            out.append(Peak(position=two_theta2, height=peak.height * ratio_i))
    return tuple(sorted(out, key=lambda p: p.position))
