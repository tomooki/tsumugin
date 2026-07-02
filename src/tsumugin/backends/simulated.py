"""合成回折パターン精密化バックエンド。

GSAS-II 非導入環境で全パイプラインを end-to-end 検証するための、決定論的な参照実装。
相ごとにガウシアンピーク列を格子・scale から生成する前方モデルと、解放パラメータのみを
Levenberg–Marquardt で最適化する精密化を提供する。乱数は一切使わない (NFR-102)。
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from ..model import LatticeParams, PhaseInstance
from .base import RefinementModel, RefinementResult, parse_param

# 既定の反射リスト。s = h²+k²+l² が d 間隔 (d = L/√s) を決める。
_DEFAULT_HKL: tuple[tuple[int, int, int], ...] = (
    (1, 0, 0),
    (1, 1, 0),
    (1, 1, 1),
    (2, 0, 0),
    (2, 1, 0),
    (2, 1, 1),
)

# 認識する(＝最適化しうる)パラメータのキー suffix。
_LATTICE_KEYS = ("lattice.a", "lattice.b", "lattice.c",
                 "lattice.alpha", "lattice.beta", "lattice.gamma")
_SCALAR_KEYS = ("scale", "wt_frac")

_FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))
_DEFAULT_WAVELENGTH = 1.5406  # Cu Kα1 (Å)


class SimulatedBackend:
    """RefinementBackend の合成データ実装。"""

    name = "simulated"

    def __init__(
        self,
        *,
        peak_fwhm: float = 0.2,
        wavelength: float = _DEFAULT_WAVELENGTH,
        hkl_table: Mapping[str, Sequence[tuple[int, int, int]]] | None = None,
    ) -> None:
        self.peak_fwhm = float(peak_fwhm)
        self.wavelength = float(wavelength)
        self._hkl_table = dict(hkl_table) if hkl_table else {}

    # ---- 前方モデル -----------------------------------------------------

    def _hkl_for(self, phase: PhaseInstance) -> tuple[tuple[int, int, int], ...]:
        return tuple(self._hkl_table.get(phase.phase_ref, _DEFAULT_HKL))

    def _d_spacing(self, lattice: LatticeParams, h: int, k: int, ell: int) -> float:
        """直方(orthorhombic)近似の面間隔。1/d² = h²/a² + k²/b² + l²/c²。

        M0 では格子角は 90° と仮定し、a/b/c を個別に識別可能にする(体積縮退を避ける)。
        """
        inv_d2 = (h * h) / (lattice.a**2) + (k * k) / (lattice.b**2) + (ell * ell) / (lattice.c**2)
        if inv_d2 <= 0:
            return 0.0
        return 1.0 / math.sqrt(inv_d2)

    def peak_positions(self, phase: PhaseInstance, two_theta: np.ndarray) -> list[float]:
        """指定 2θ 範囲内に現れる反射の 2θ 位置(度)を返す。"""
        lo, hi = float(two_theta[0]), float(two_theta[-1])
        positions: list[float] = []
        for (h, k, ell) in self._hkl_for(phase):
            d = self._d_spacing(phase.lattice, h, k, ell)
            if d <= 0:
                continue
            sin_theta = self.wavelength / (2.0 * d)
            if not 0.0 < sin_theta < 1.0:
                continue
            two_theta_deg = 2.0 * math.degrees(math.asin(sin_theta))
            if lo <= two_theta_deg <= hi:
                positions.append(two_theta_deg)
        return positions

    def simulate(
        self, phases: Sequence[PhaseInstance], two_theta: np.ndarray
    ) -> np.ndarray:
        """観測強度をガウシアンピークの重ね合わせで生成する。"""
        two_theta = np.asarray(two_theta, dtype=float)
        y = np.zeros_like(two_theta)
        sigma = self.peak_fwhm * _FWHM_TO_SIGMA
        for phase in phases:
            for (h, k, ell) in self._hkl_for(phase):
                d = self._d_spacing(phase.lattice, h, k, ell)
                if d <= 0:
                    continue
                sin_theta = self.wavelength / (2.0 * d)
                if not 0.0 < sin_theta < 1.0:
                    continue
                center = 2.0 * math.degrees(math.asin(sin_theta))
                y += phase.scale * np.exp(-0.5 * ((two_theta - center) / sigma) ** 2)
        return y

    # ---- パラメータの読み書き ------------------------------------------

    def _recognized(self, free_params: frozenset[str]) -> list[str]:
        out: list[str] = []
        for name in sorted(free_params):
            _, key = parse_param(name)
            if key in _SCALAR_KEYS or key in _LATTICE_KEYS or key.startswith("occ."):
                out.append(name)
        return out

    def _get(self, phases: tuple[PhaseInstance, ...], name: str) -> float:
        idx, key = parse_param(name)
        phase = phases[idx]
        if key == "scale":
            return phase.scale
        if key == "wt_frac":
            return phase.wt_frac if phase.wt_frac is not None else 0.0
        if key.startswith("lattice."):
            return float(getattr(phase.lattice, key.split(".", 1)[1]))
        if key.startswith("occ."):
            return float(phase.occupancies.get(key.split(".", 1)[1], 0.0))
        raise KeyError(name)

    def _set(
        self, phases: tuple[PhaseInstance, ...], name: str, value: float
    ) -> tuple[PhaseInstance, ...]:
        idx, key = parse_param(name)
        phase = phases[idx]
        phases_list = list(phases)
        if key == "scale":
            phases_list[idx] = phase.with_updates(scale=max(value, 1e-8))
        elif key == "wt_frac":
            phases_list[idx] = phase.with_updates(wt_frac=max(value, 0.0))
        elif key.startswith("lattice."):
            attr = key.split(".", 1)[1]
            clipped = max(value, 1e-3) if attr in ("a", "b", "c") else min(max(value, 1.0), 179.0)
            phases_list[idx] = phase.with_updates(
                lattice=_replace_lattice(phase.lattice, attr, clipped)
            )
        elif key.startswith("occ."):
            site = key.split(".", 1)[1]
            occ = dict(phase.occupancies)
            occ[site] = max(value, 0.0)
            phases_list[idx] = phase.with_updates(occupancies=occ)
        else:
            raise KeyError(name)
        return tuple(phases_list)

    # ---- 精密化 (Levenberg–Marquardt) ----------------------------------

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        two_theta = np.asarray(model.two_theta, dtype=float)
        y_obs = np.asarray(model.intensity, dtype=float)
        n_obs = int(y_obs.size)
        if model.weights is not None:
            weights = np.asarray(model.weights, dtype=float)
        else:
            weights = 1.0 / np.maximum(y_obs, 1.0)
        sqrt_w = np.sqrt(weights)

        names = self._recognized(model.free_params)
        phases = model.phases

        def residual(ph: tuple[PhaseInstance, ...]) -> np.ndarray:
            return sqrt_w * (y_obs - self.simulate(ph, two_theta))

        r = residual(phases)
        chi2 = float(r @ r)

        if not names:
            return RefinementResult(
                phases=phases,
                chi2=chi2,
                rwp=_rwp(weights, y_obs, self.simulate(phases, two_theta)),
                n_obs=n_obs,
                n_params=0,
                converged=True,
                n_cycles=1,
                free_params=frozenset(),
            )

        p = np.array([self._get(phases, name) for name in names], dtype=float)
        lam = 1e-3
        converged = False
        cycle = 0
        for cycle in range(1, max_cycles + 1):
            jac = self._jacobian(phases, names, p, residual, r)
            jtj = jac.T @ jac
            jtr = jac.T @ r
            diag = np.diag(np.maximum(np.diag(jtj), 1e-12))

            improved = False
            for _ in range(12):  # inner λ adaptation
                a_matrix = jtj + lam * diag
                try:
                    delta = np.linalg.solve(a_matrix, -jtr)
                except np.linalg.LinAlgError:
                    lam *= 10.0
                    continue
                p_new = p + delta
                phases_new = phases
                for name, val in zip(names, p_new):
                    phases_new = self._set(phases_new, name, float(val))
                # clipping で p_new が動くため実際の値を読み戻す
                p_new = np.array([self._get(phases_new, name) for name in names])
                r_new = residual(phases_new)
                chi2_new = float(r_new @ r_new)
                if chi2_new < chi2:
                    rel = abs(chi2 - chi2_new) / max(chi2, 1e-30)
                    step_norm = float(np.linalg.norm(p_new - p))
                    phases, p, r, chi2 = phases_new, p_new, r_new, chi2_new
                    lam = max(lam / 3.0, 1e-12)
                    improved = True
                    if rel < 1e-4 or step_norm < 1e-6:
                        converged = True
                    break
                lam = min(lam * 3.0, 1e12)
            if not improved:
                converged = True
                break
            if converged:
                break

        return RefinementResult(
            phases=phases,
            chi2=chi2,
            rwp=_rwp(weights, y_obs, self.simulate(phases, two_theta)),
            n_obs=n_obs,
            n_params=len(names),
            converged=converged,
            n_cycles=cycle,
            free_params=frozenset(names),
        )

    def _jacobian(self, phases, names, p, residual, r) -> np.ndarray:
        """残差 r の各パラメータに対する数値ヤコビアン (前進差分)。"""
        jac = np.empty((r.size, len(names)))
        for j, name in enumerate(names):
            step = 1e-5 * max(1.0, abs(p[j]))
            phases_pert = phases
            for name2, val in zip(names, p):
                target = val + step if name2 == name else val
                phases_pert = self._set(phases_pert, name2, float(target))
            r_pert = residual(phases_pert)
            jac[:, j] = (r_pert - r) / step
        return jac


def _replace_lattice(lattice: LatticeParams, attr: str, value: float) -> LatticeParams:
    from dataclasses import replace

    return replace(lattice, **{attr: value})


def _rwp(weights: np.ndarray, y_obs: np.ndarray, y_calc: np.ndarray) -> float:
    num = float(np.sum(weights * (y_obs - y_calc) ** 2))
    den = float(np.sum(weights * y_obs**2))
    if den <= 0:
        return 0.0
    return 100.0 * math.sqrt(num / den)
