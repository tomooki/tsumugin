"""残差配列 + 内省フィールドから ResidualFeatures を算出する既定 diagnose (REQ-002)。

`orchestrator` の Diagnose 契約 ``(result, inp) -> Sequence[ResidualFeatures]`` を満たし、
背景のみの粗診断 `_default_diagnose` を置換する。`AutoRietveldResult` の残差配列
(residual_two_theta/intensity/sigma) と内省フィールド (peak_width_ratio/asymmetry_metric/
intensity_bias_metric/bg_extrema/atom_uiso/hist_absorption) から多シグナルを算出する。

**縮退の原則** (REQ-002):
- 内省フィールドが空 (旧 result/スタブ) の場合、該当シグナルを立てない (既定 0/空, EDGE-001)。
- 残差が空 or 全ノイズ (|resid| が σ を超えない) の場合、残差由来シグナルを立てない (EDGE-102)。

numpy 決定論 (NFR-102)。GSAS 非依存。
"""

from __future__ import annotations

from typing import Mapping, Sequence

import numpy as np

from tsumugin.autorietveld.model import AutoRietveldResult
from .action import AnalysisInput
from .diagnostics import ResidualFeatures

# 物理的な Uiso の範囲外 (発散/負値) と判定する境界 [Å²]。
_UISO_MIN = 0.0
_UISO_MAX = 0.5


def _diverged_uiso(atom_uiso: Mapping[str, Mapping[str, float]]) -> tuple[str, ...]:
    """全相を通じ Uiso が [0, 0.5] を外れる原子ラベルを昇順で返す (決定論)。"""
    bad: set[str] = set()
    for phase in atom_uiso.values():
        for label, uiso in phase.items():
            if uiso < _UISO_MIN or uiso > _UISO_MAX:
                bad.add(label)
    return tuple(sorted(bad))


def _residual_metrics(result: AutoRietveldResult) -> tuple[float | None, float | None]:
    """先頭ヒストグラムの残差から (低周波系統背景残差, 未指数ピーク割合) を返す。

    残差が空 or 全ノイズ (|resid| が 3σ を超えない) の場合は (None, None) (EDGE-102 FP 回避)。
    """
    resid = np.asarray(result.residual_intensity, dtype=float)
    if resid.size == 0:
        return None, None
    sigma = np.asarray(result.residual_sigma, dtype=float)
    if sigma.size == resid.size:
        significant = np.abs(resid) > 3.0 * np.maximum(sigma, 1e-12)
    else:
        significant = np.abs(resid) > 0.0
    if not significant.any():
        return None, None  # 全ノイズ

    eps = 1e-12
    total = float(np.sqrt(np.mean(resid**2))) + eps
    # 低周波系統残差: 移動平均で平滑化した残差の RMS / 全残差 RMS (∈[0,1], 大=系統的うねり)。
    w = max(3, resid.size // 20)
    kernel = np.ones(w) / w
    smoothed = np.convolve(resid, kernel, mode="same")
    low_freq = float(np.sqrt(np.mean(smoothed**2))) / total
    # 未指数ピーク割合: 有意な正の残差強度 / 全残差強度の絶対和 (∈[0,1], 未モデル正ピーク)。
    pos = resid[significant & (resid > 0.0)]
    unindexed = float(np.sum(pos)) / (float(np.sum(np.abs(resid))) + eps)
    return low_freq, unindexed


def diagnose_residual(
    result: AutoRietveldResult, inp: AnalysisInput
) -> Sequence[ResidualFeatures]:
    """残差 + 内省フィールドから per-histogram の ResidualFeatures 列を算出する。"""
    n = len(inp.histograms)
    if n == 0:
        return []
    diverged = _diverged_uiso(result.atom_uiso)
    low_freq, unindexed = _residual_metrics(result)

    feats: list[ResidualFeatures] = []
    for i, hist in enumerate(inp.histograms):
        kw: dict[str, object] = {
            "hist_id": i,
            "n_background_coeffs": inp.background_coeffs,
            "radiation_is_tof": hist.radiation.is_tof,
            "radiation_is_neutron": hist.radiation.is_neutron,
        }
        if i < len(result.peak_width_ratio):
            kw["fwhm_ratio"] = float(result.peak_width_ratio[i])
        if i < len(result.asymmetry_metric):
            kw["asymmetry_residual"] = float(result.asymmetry_metric[i])
        if i < len(result.intensity_bias_metric):
            kw["intensity_bias"] = float(result.intensity_bias_metric[i])
        if i < len(result.bg_extrema):
            kw["bg_extrema_count"] = int(result.bg_extrema[i])
        # 吸収が負値 (非物理) に振れている → free/物理/0 を試す (REQ-106)。
        if i < len(result.hist_absorption) and result.hist_absorption[i] < 0.0:
            kw["absorption_uncertain"] = True
        # 残差配列・Uiso は先頭ヒストグラムに代表させる (残差は先頭のみ・Uiso は相属性)。
        if i == 0:
            if diverged:
                kw["diverged_uiso_labels"] = diverged
            if low_freq is not None:
                kw["low_freq_bg_residual"] = low_freq
            if unindexed is not None:
                kw["unindexed_peak_frac"] = unindexed
        feats.append(ResidualFeatures(**kw))
    return feats
