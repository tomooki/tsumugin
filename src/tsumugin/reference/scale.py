"""非負スケール joint フィット + プロファイル合成 (M11 逐次減算同定の受理段, FR-118-2)。

逐次同定の受理判定で、**全採用相 + 候補**のガウスプロファイルを原パターンへ**非負最小二乗**で同時に
スケールし直し、未説明強度 (正残差の二乗和) の減少で採否する。貪欲に1相ずつ引く誤差蓄積を避けるため、
毎回全相を原パターンに対して joint に解く (M10 consolidation の peak-space 版)。

非負最小二乗は Lawson-Hanson の active-set 法を numpy で実装 (scipy 非依存・決定論)。相数は小さい
(≤ max_phases) ため AᵀA は小行列で高速。numpy のみ。

信頼性: 🔵 `docs/design/m11-iterative-identification/architecture.md` §3。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = ["render_phase", "build_design_matrix", "fit_nonneg_scales", "nnls"]

# FWHM → ガウス σ の変換係数 (σ = FWHM / (2√(2 ln2)))
_FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))

# 相のピーク: (2θ 位置, 相対強度) の列
PeakList = Sequence[tuple[float, float]]


def render_phase(two_theta: np.ndarray, peaks: PeakList, fwhm: float) -> np.ndarray:
    """相の (単位スケールの) ガウスプロファイルを 2θ 上に合成する。

    :param two_theta: 2θ 軸 (度)
    :param peaks: (位置, 相対強度) の列
    :param fwhm: ガウス半値幅 (度)
    :returns: Σ height·exp(−½((2θ−pos)/σ)²) (単位スケール; スケール係数は fit 側が掛ける)
    """
    tt = np.asarray(two_theta, dtype=float)
    y = np.zeros_like(tt)
    sigma = max(float(fwhm), 1e-6) * _FWHM_TO_SIGMA
    for pos, height in peaks:
        y += float(height) * np.exp(-0.5 * ((tt - float(pos)) / sigma) ** 2)
    return y


def build_design_matrix(
    two_theta: np.ndarray, phase_peaks: Sequence[PeakList], fwhm: float
) -> np.ndarray:
    """各相のプロファイルを列に持つ設計行列 A (n_points × n_phases) を作る。"""
    tt = np.asarray(two_theta, dtype=float)
    if not phase_peaks:
        return np.zeros((tt.size, 0), dtype=float)
    return np.column_stack([render_phase(tt, pk, fwhm) for pk in phase_peaks])


def nnls(A: np.ndarray, b: np.ndarray, *, tol: float = 1e-10, max_iter: int | None = None) -> np.ndarray:
    """非負最小二乗 min‖A·x − b‖ s.t. x ≥ 0 (Lawson-Hanson active-set, 決定論)。

    列 (相) が少ないため AᵀA/Atb を前計算し小行列で回す。タイは最小 index 優先 (argmax) で決定論。
    """
    A = np.asarray(A, dtype=float)
    b = np.asarray(b, dtype=float)
    _, n = A.shape
    x = np.zeros(n)
    if n == 0:
        return x
    passive = np.zeros(n, dtype=bool)  # P: 非拘束 (>0 を許す) 集合
    ata = A.T @ A
    atb = A.T @ b
    outer_max = max_iter if max_iter is not None else 3 * n
    for _ in range(outer_max):
        w = atb - ata @ x  # 勾配 (負残差方向)
        active = ~passive
        if not active.any() or float(np.max(w[active])) <= tol:
            break
        # active 集合で勾配最大の列を passive へ (タイは最小 index)
        idx_active = np.where(active)[0]
        j = int(idx_active[int(np.argmax(w[idx_active]))])
        passive[j] = True
        # 内側ループ: passive 集合上で最小二乗し、負成分を active へ戻す
        for _inner in range(3 * n):
            p_idx = np.where(passive)[0]
            zp, *_ = np.linalg.lstsq(A[:, p_idx], b, rcond=None)
            if np.all(zp > tol):
                x = np.zeros(n)
                x[p_idx] = zp
                break
            # 負/零成分がある → x から z への線分で最初に 0 に達する alpha
            z = np.zeros(n)
            z[p_idx] = zp
            neg = passive & (z <= tol)
            with np.errstate(divide="ignore", invalid="ignore"):
                ratios = np.where(neg & (x - z != 0.0), x / (x - z), np.inf)
            alpha = float(np.min(ratios[neg])) if neg.any() else 0.0
            x = x + alpha * (z - x)
            passive[(x <= tol) & passive] = False
            x[~passive] = 0.0
        else:
            break  # 内側収束せず (数値異常) → 打ち切り
    return x


def fit_nonneg_scales(
    two_theta: np.ndarray,
    observed: np.ndarray,
    phase_peaks: Sequence[PeakList],
    fwhm: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    """観測 ≈ Σ sⱼ·profileⱼ を非負スケール sⱼ ≥ 0 で joint フィットする。

    :returns: (scales, model, residual, unexplained_ss)。unexplained_ss = ‖max(residual,0)‖²
        (**正残差** = 未説明強度のみ二乗和。負残差 = 過剰フィットは罰さない)。
        相ゼロなら scales 空・model 0・residual=observed。
    """
    tt = np.asarray(two_theta, dtype=float)
    y = np.asarray(observed, dtype=float)
    A = build_design_matrix(tt, phase_peaks, fwhm)
    if A.shape[1] == 0:
        resid = y.copy()
        return np.zeros(0), np.zeros_like(y), resid, float(np.sum(np.clip(resid, 0.0, None) ** 2))
    s = nnls(A, y)
    model = A @ s
    resid = y - model
    unexplained_ss = float(np.sum(np.clip(resid, 0.0, None) ** 2))
    return s, model, resid, unexplained_ss
