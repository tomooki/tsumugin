"""格子ズレ吸収の Pawley-lite 精密化 (仕様 §5 / Dara フロー Phase A)。

DFT 緩和構造 (Materials Project 等) の格子定数は実測と数 % ずれ、参照計算ピークの 2θ が系統的に
ずれる。相同定でこのズレを吸収するため、参照ピーク列を観測へ整合させる **等方格子歪み ε**
(d → d(1+ε)) と **2θ ゼロシフト z** を最小二乗で求める (Dara の格子精密化に対応する軽量版)。

full 異方 Rietveld (原子/プロファイル精密化, GSAS-II) ではなく、位置整合に絞った numpy のみの
決定論的実装。等方歪みは DFT の系統的な体積膨張を主に捉える (異方歪みは将来 hkl ベースで拡張)。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from ..search.peaks import Peak

__all__ = [
    "LatticeAlignment",
    "align_peaks",
    "AnisotropicAlignment",
    "align_peaks_anisotropic",
]


@dataclass(frozen=True)
class LatticeAlignment:
    """格子整合の結果。🔵 Phase A"""

    strain: float  # 等方格子歪み ε (d→d(1+ε))。正で格子膨張 🔵
    zero_shift: float  # 2θ ゼロシフト z (度) 🔵
    aligned_peaks: tuple[Peak, ...]  # ε,z を適用した計算ピーク (高さ不変・位置整合) 🔵
    n_matched: int  # フィットに使った一致ピーク数 🔵
    rms_residual: float  # 整合後の一致ピーク位置残差 RMS (度) 🔵


def _transform(position: float, strain: float, zero: float) -> float | None:
    """ピーク 2θ に等方歪み ε とゼロシフト z を適用する。sinθ≥1 は None (非物理)。🔵"""
    sin_theta = math.sin(math.radians(position / 2.0)) / (1.0 + strain)
    if not -1.0 < sin_theta < 1.0:
        return None
    return 2.0 * math.degrees(math.asin(sin_theta)) + zero


def _transform_all(peaks: Sequence[Peak], strain: float, zero: float) -> list[tuple[int, float]]:
    """全ピークを変換し (元 index, 変換後位置) を返す (範囲外は除外)。🔵"""
    out: list[tuple[int, float]] = []
    for i, p in enumerate(peaks):
        tp = _transform(float(p.position), strain, zero)
        if tp is not None:
            out.append((i, tp))
    return out


def _match(
    transformed: list[tuple[int, float]], observed: Sequence[Peak], tol_deg: float
) -> list[tuple[int, float, float]]:
    """変換後計算ピークを観測へ貪欲 1:1 マッチ (元 index, calc位置, obs位置, obs高さ) を返す。🔵"""
    used = [False] * len(observed)
    obs_order = sorted(range(len(observed)), key=lambda k: observed[k].position)
    pairs: list[tuple[int, float, float, float]] = []
    for _ci, cpos in sorted(transformed, key=lambda t: t[1]):
        best_j = -1
        best_diff = tol_deg
        for j in obs_order:
            if used[j]:
                continue
            diff = abs(cpos - float(observed[j].position))
            if diff <= best_diff:
                best_diff = diff
                best_j = j
        if best_j >= 0:
            used[best_j] = True
            pairs.append((cpos, float(observed[best_j].position), float(observed[best_j].height)))
    return pairs


def align_peaks(
    calculated_peaks: Sequence[Peak],
    observed_peaks: Sequence[Peak],
    *,
    tol_deg: float = 0.5,
    max_strain: float = 0.01,
    max_zero_shift: float = 0.5,
    iterations: int = 12,
) -> LatticeAlignment:
    """参照計算ピークを観測へ整合させる ε, z を求め整合後ピークを返す (Phase A)。🔵

    【アルゴリズム】: 反復最近傍。現在の (ε,z) で計算ピークを変換 → 観測へ貪欲マッチ →
      一致ペアで強度重み付き最小二乗により (ε,z) を更新 (数値ヤコビアン, Gauss-Newton) →
      収束まで反復。ε は ±``max_strain`` (既定 1%, Dara 準拠)、z は ±``max_zero_shift`` にクリップ。

    Args:
        calculated_peaks: 参照相の計算ピーク列 (2θ・強度)。
        observed_peaks: 観測ピーク列。
        tol_deg: 整合中のマッチ許容差 (度)。DFT ズレを吸収できるよう広め (既定 0.5)。
        max_strain: 等方歪みの上限 (既定 0.01 = 1%)。
        max_zero_shift: ゼロシフトの上限 (度)。
        iterations: 最大反復数。

    Returns:
        ``LatticeAlignment``。一致 2 本未満なら恒等 (ε=z=0・元ピーク) に縮退する。
    """
    calc = list(calculated_peaks)
    if not calc or not observed_peaks:
        return LatticeAlignment(0.0, 0.0, tuple(calc), 0, 0.0)

    strain = 0.0
    zero = 0.0
    n_matched = 0
    for _ in range(iterations):
        transformed = _transform_all(calc, strain, zero)
        pairs = _match(transformed, observed_peaks, tol_deg)
        n_matched = len(pairs)
        if n_matched < 2:
            break
        # 【強度重み付き Gauss-Newton】: 残差 r=obs−calc'、数値ヤコビアン [∂/∂ε, ∂/∂z] で Δ を解く 🔵
        de = 1e-6
        a00 = a01 = a11 = b0 = b1 = 0.0
        for cpos, opos, oh in pairs:
            w = math.sqrt(max(oh, 1e-9))
            # 変換後位置 cpos に対応する元 2θ を逆算せず、ε,z 微小変化の感度を数値で近似する。
            # cpos = f(p0; ε,z)。p0 は tan 側で必要だが、ここでは cpos を基準に局所感度を取る:
            #   ∂cpos/∂z = 1、∂cpos/∂ε ≈ (f(p0;ε+de)−f(p0;ε))/de を cpos から p0 復元して評価。
            # p0 復元: cpos−z = 2·asin(sinθ0/(1+ε)) → sinθ0 = sin((cpos−z)/2·π/180)·(1+ε)
            theta0 = math.asin(
                min(1.0, math.sin(math.radians((cpos - zero) / 2.0)) * (1.0 + strain))
            )
            p0 = 2.0 * math.degrees(theta0)
            f0 = _transform(p0, strain, zero)
            f1 = _transform(p0, strain + de, zero)
            jeps = ((f1 - f0) / de) if (f0 is not None and f1 is not None) else 0.0
            jz = 1.0
            r = opos - cpos
            we = w * jeps
            wz = w * jz
            a00 += we * jeps
            a01 += we * jz
            a11 += wz * jz
            b0 += we * r
            b1 += wz * r
        # 2x2 正規方程式を解く (退化時は更新なし)
        det = a00 * a11 - a01 * a01
        if abs(det) < 1e-18:
            break
        d_eps = (b0 * a11 - b1 * a01) / det
        d_zero = (a00 * b1 - a01 * b0) / det
        new_strain = max(-max_strain, min(max_strain, strain + d_eps))
        new_zero = max(-max_zero_shift, min(max_zero_shift, zero + d_zero))
        # 【収束判定】: クランプ後の実変化で早期停止する。境界に張り付いた場合は更新量が
        #   丸められ、収束扱いで抜けるか iterations 上限まで回る。いずれも決定論的で ε,z は
        #   ±上限に有界なため出力は安定 (最適収束でない可能性のみ、正しさに影響しない)。🔵
        if abs(new_strain - strain) < 1e-7 and abs(new_zero - zero) < 1e-5:
            strain, zero = new_strain, new_zero
            break
        strain, zero = new_strain, new_zero

    # 【最終整合ピーク + 残差】: 収束 (ε,z) で変換し、一致ペアの RMS を測る 🔵
    transformed = _transform_all(calc, strain, zero)
    aligned = tuple(
        Peak(position=tp, height=float(calc[i].height)) for i, tp in transformed
    )
    pairs = _match(transformed, observed_peaks, tol_deg)
    n_matched = len(pairs)
    if pairs:
        rms = math.sqrt(sum((o - c) ** 2 for c, o, _ in pairs) / len(pairs))
    else:
        rms = 0.0
    return LatticeAlignment(strain, zero, aligned, n_matched, rms)


# ============================================================================
# 異方格子整合 (Issue #20 hybrid: 相同定 top-K の異方 re-score)
# ============================================================================

# 参照相の型 (循環 import を避け構造的に受ける): cell/crystal_system + hkl 付き peaks を持つもの。


@dataclass(frozen=True)
class AnisotropicAlignment:
    """異方格子整合の結果 (等方 ``LatticeAlignment`` の軸別版)。🔵 Issue #20 hybrid"""

    aligned_peaks: tuple[Peak, ...]  # 精密化セルで再計算した計算ピーク (位置整合・hkl 保持) 🔵
    cell: tuple[float, float, float, float, float, float]  # 精密化した異方セル 🔵
    strain: float  # 最大軸相対変化 max(|a'/a−1|,|b'/b−1|,|c'/c−1|)。ランキング減点用 🔵
    n_used: int  # フィットに使った反射数 🔵


def align_peaks_anisotropic(
    phase: object,
    observed_peaks: Sequence[Peak],
    *,
    wavelength: float = 1.5406,
    two_theta_range: tuple[float, float] | None = None,
) -> AnisotropicAlignment | None:
    """参照相 (cell + crystal_system + hkl 付き peaks) を観測へ**軸別**に整合させる (Issue #20 hybrid)。

    等方 ``align_peaks`` (ε 1 自由度) では吸収できない DFT の異方格子誤差 (軸ごとに数 %) を、逆格子
    計量テンソル線形解 + FoM グリッド (``autorietveld.lattice``, numpy) で補正し、精密化セルで計算ピークを
    再計算して返す。相同定の top-K 候補を異方再スコアするための整合器。GSAS/pymatgen 非依存
    (lattice は遅延 import; hkl とセルさえあれば numpy のみ)。

    :param phase: ``cell``/``crystal_system`` と hkl 付き ``peaks`` を持つ参照相 (``ReferencePhase``)
    :param observed_peaks: 観測ピーク列
    :param wavelength: 線源波長 (Å)
    :param two_theta_range: 評価 2θ 範囲 (None なら観測ピークの min/max)
    :returns: ``AnisotropicAlignment``。格子情報/hkl 不足・観測不足・未改善なら ``None`` (等方版へ縮退)
    """
    cell = getattr(phase, "cell", None)
    crystal_system = getattr(phase, "crystal_system", None)
    peaks = getattr(phase, "peaks", ())
    if cell is None or crystal_system is None or not observed_peaks:
        return None
    indexed = [p for p in peaks if p.hkl is not None]
    if len(indexed) < 3:
        return None

    hkls = [p.hkl for p in indexed]
    intensities = [p.height for p in indexed]
    obs_pos = [p.position for p in observed_peaks]
    obs_ht = [p.height for p in observed_peaks]
    rng = two_theta_range or (min(obs_pos), max(obs_pos))

    # 異方セル精密化は numpy コア (lattice) に委譲。遅延 import で循環依存/コア import 汚染を避ける。
    from ..autorietveld.lattice import refine_cell_from_indexed_peaks, two_theta_of_hkls

    sol = refine_cell_from_indexed_peaks(
        cell, crystal_system, hkls, intensities, obs_pos, obs_ht,
        wavelength=wavelength, two_theta_range=rng,
    )
    if sol is None:  # 改善せず (安全側): 等方版のまま
        return None

    # 精密化セルで計算ピーク位置を再計算 (強度・hkl は保持)
    tth = two_theta_of_hkls(sol.cell, hkls, wavelength)
    aligned = tuple(
        Peak(position=float(tth[k]), height=float(intensities[k]), hkl=tuple(hkls[k]))
        for k in range(len(hkls))
        if math.isfinite(float(tth[k]))
    )
    a0, b0, c0 = float(cell[0]), float(cell[1]), float(cell[2])
    strain = max(
        abs(sol.cell[0] / a0 - 1.0), abs(sol.cell[1] / b0 - 1.0), abs(sol.cell[2] / c0 - 1.0)
    )
    return AnisotropicAlignment(
        aligned_peaks=aligned, cell=sol.cell, strain=float(strain), n_used=sol.n_used
    )
