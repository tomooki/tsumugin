"""合成回折パターン精密化バックエンド。

GSAS-II 非導入環境で全パイプラインを end-to-end 検証するための、決定論的な参照実装。
相ごとにガウシアンピーク列を格子・scale から生成する前方モデルと、解放パラメータのみを
Levenberg–Marquardt で最適化する精密化を提供する。乱数は一切使わない (NFR-102)。
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from ..absorption.model import AbsorptionConfig, transmission_factor
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

# restraint 逸脱 (相関疑い) 判定の残差閾値。restraint が μt を中心へ引き留めた結果、
# 強度プロファイルに系統的な残差 (rwp[%]) が残るとき μt–scale 相関 (§14) を疑う。
# 🟡 設計裁量 (要件定義 2.4 の「許容幅は設計裁量」)。合成データの良好適合は rwp≈0。
_CORRELATION_RWP_THRESHOLD = 0.5


class SimulatedBackend:
    """RefinementBackend の合成データ実装。"""

    name = "simulated"

    def __init__(
        self,
        *,
        peak_fwhm: float = 0.2,
        wavelength: float = _DEFAULT_WAVELENGTH,
        hkl_table: Mapping[str, Sequence[tuple[int, int, int]]] | None = None,
        absorption: AbsorptionConfig | None = None,
    ) -> None:
        self.peak_fwhm = float(peak_fwhm)
        self.wavelength = float(wavelength)
        self._hkl_table = dict(hkl_table) if hkl_table else {}
        # 【吸収設定】: None なら従来挙動 (透過因子乗算なし)。設定時は前方モデルへ吸収を織り込む 🔵
        self._absorption = absorption

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
        """観測強度をガウシアンピークの重ね合わせで生成する。

        absorption 設定時は初期実効 μt (``mu_t_initial``) による透過因子を乗算する。
        absorption 未設定なら乗算せず従来挙動と完全一致する (公開シグネチャは不変)。
        """
        mu_t = self._absorption.mu_t_initial if self._absorption is not None else None
        return self._simulate(phases, two_theta, mu_t)

    def _simulate(
        self,
        phases: Sequence[PhaseInstance],
        two_theta: np.ndarray,
        mu_t: float | None,
    ) -> np.ndarray:
        """ガウシアン重ね合わせに (指定時) 透過吸収因子を乗算する内部前方モデル。

        【実装方針】: ``mu_t is None`` のときは乗算をスキップし従来経路とビット一致させる
                      (REQ-404 / EDGE-006)。μt=0 の場合も transmission_factor が全域 1.0 の
                      ため乗算結果は無補正と一致する。精密化中は現在のフィット μt を渡す。
        🔵 信頼性レベル: 要件定義 2.4 / architecture.md D8 L95-96 に依拠。
        """
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
        # 【吸収補正】: μt 指定時のみ透過因子を一様乗算。None は無補正でビット一致 🔵
        if mu_t is not None:
            y = y * transmission_factor(two_theta, mu_t)
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
        n_phase = len(names)

        # 【μt 精密化の判定】: absorption 設定かつ "global.mu_t" 解放時のみ μt をフィットする 🔵
        absorption = self._absorption
        fit_mu_t = absorption is not None and "global.mu_t" in model.free_params
        # 【定数 μt】: μt を精密化しない場合に simulate へ渡す固定値 (無設定は None=無補正) 🔵
        const_mu_t = absorption.mu_t_initial if absorption is not None else None
        if fit_mu_t:
            w_r = float(absorption.restraint_weight)  # 【restraint 重み w_r】🔵
            sqrt_wr = math.sqrt(w_r)
            # 【restraint 中心】: μt_calc 提供時はそれ、経験推定 (None) は 0 とし弱く動かす 🟡
            mu_t_center = (
                float(absorption.mu_t_calc) if absorption.mu_t_calc is not None else 0.0
            )

        def full_residual(ph: tuple[PhaseInstance, ...], mu_t: float) -> np.ndarray:
            # 【強度残差】: 精密化時は現在の μt、非精密化時は固定 μt で前方モデルを評価 🔵
            sim_mu_t = mu_t if fit_mu_t else const_mu_t
            data_r = sqrt_w * (y_obs - self._simulate(ph, two_theta, sim_mu_t))
            if fit_mu_t:
                # 【restraint 項】: sqrt(w_r)·(μt − μt_calc) を残差末尾に追加し chi2 へ加算 🟡
                restraint_r = sqrt_wr * (mu_t - mu_t_center)
                return np.concatenate([data_r, np.array([restraint_r], dtype=float)])
            return data_r

        def set_phase_params(
            base: tuple[PhaseInstance, ...], vals: np.ndarray
        ) -> tuple[PhaseInstance, ...]:
            ph = base
            for name, val in zip(names, vals):
                ph = self._set(ph, name, float(val))
            return ph

        def read_vec(ph: tuple[PhaseInstance, ...], mu_t: float) -> np.ndarray:
            vals = [self._get(ph, name) for name in names]
            if fit_mu_t:
                vals.append(mu_t)  # 【μt 併走】: 相パラメータ末尾に μt 成分を連結 🔵
            return np.array(vals, dtype=float)

        mu_t = float(absorption.mu_t_initial) if fit_mu_t else 0.0
        r = full_residual(phases, mu_t)
        chi2 = float(r @ r)

        # 【早期リターン】: 解放パラメータ (相 or μt) が皆無なら 1 サイクルで確定 (既存挙動保存) 🔵
        if not names and not fit_mu_t:
            return RefinementResult(
                phases=phases,
                chi2=chi2,
                rwp=_rwp(weights, y_obs, self._simulate(phases, two_theta, const_mu_t)),
                n_obs=n_obs,
                n_params=0,
                converged=True,
                n_cycles=1,
                free_params=frozenset(),
            )

        p = read_vec(phases, mu_t)
        lam = 1e-3
        converged = False
        cycle = 0
        for cycle in range(1, max_cycles + 1):
            jac = self._jacobian(phases, names, p, fit_mu_t, full_residual, r)
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
                phases_new = set_phase_params(phases, p_new[:n_phase])
                # 【μt clip】: 物理的に μt ≥ 0。負値は 0 へ丸め読み戻す 🔵
                mu_t_new = max(float(p_new[n_phase]), 0.0) if fit_mu_t else mu_t
                # clipping で p_new が動くため実際の値を読み戻す
                p_new = read_vec(phases_new, mu_t_new)
                r_new = full_residual(phases_new, mu_t_new)
                chi2_new = float(r_new @ r_new)
                if chi2_new < chi2:
                    rel = abs(chi2 - chi2_new) / max(chi2, 1e-30)
                    step_norm = float(np.linalg.norm(p_new - p))
                    phases, mu_t, p, r, chi2 = phases_new, mu_t_new, p_new, r_new, chi2_new
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

        y_final = self._simulate(phases, two_theta, mu_t if fit_mu_t else const_mu_t)
        rwp = _rwp(weights, y_obs, y_final)
        free_out = frozenset(names) | ({"global.mu_t"} if fit_mu_t else frozenset())
        globals_out: dict[str, float] = {"mu_t": float(mu_t)} if fit_mu_t else {}
        warnings_out = self._build_warnings(absorption, fit_mu_t, mu_t, rwp)
        return RefinementResult(
            phases=phases,
            chi2=chi2,
            rwp=rwp,
            n_obs=n_obs,
            n_params=len(p),
            converged=converged,
            n_cycles=cycle,
            free_params=free_out,
            globals=globals_out,
            warnings=warnings_out,
        )

    def _build_warnings(
        self,
        absorption: AbsorptionConfig | None,
        fit_mu_t: bool,
        mu_t: float,
        rwp: float,
    ) -> tuple[str, ...]:
        """精密化後の μt に対する警告 (経験推定モード明示 / restraint 幅超過の相関疑い) を構成する。

        【機能概要】: 精密化した μt に対し、経験推定モードの明示・逆算 μt 提示 (REQ-018) と、
                      restraint 中心からの逸脱に基づく相関疑い警告 (REQ-103) を組み立てる。
        【改善内容】: REQ-103 の字義「μt が restraint 幅を超えて逸脱したら警告」を直接判定する
                      ``_deviation_warning`` (一次シグナル) を新設し、Green で唯一実装していた
                      rwp 閾値ベースの ``_residual_correlation_warning`` は補完シグナルとして併設した。
        【設計方針】: 逸脱は 2 面で捉える — (1) μt が中心から実際に離れた「顕在的逸脱」(restraint_width
                      超過) と、(2) μt が中心へ拘束されても残差 rwp が示す「データ選好との潜在的乖離」。
                      両者は排他でなく、相関リスク (§14) を取りこぼさないための多重シグナルとして共存する。
        🔵 信頼性レベル: 要件定義 2.4 / REQ-018/103 に依拠 (許容幅/判定閾値は 🟡 設計裁量)。

        :param absorption: 吸収設定 (None なら μt 非精密化)
        :param fit_mu_t: μt を精密化したか
        :param mu_t: 精密化後の実効 μt
        :param rwp: 強度残差ベースの重み付き R 値 [%]
        :returns: 警告文字列のタプル (決定論的順序: 経験推定 → 顕在的逸脱 → 潜在的乖離)
        """
        if not fit_mu_t or absorption is None:
            return ()
        warnings_list: list[str] = []
        if absorption.empirical_mode:
            # 【経験推定モード明示 + 逆算 μt】: CellConfig 由来 μt 未提供を通知 🔵
            warnings_list.append(
                f"経験推定モード: CellConfig 由来の μt_calc 未提供のため弱 restraint で "
                f"推定しました。逆算 μt={mu_t:.4g}"
            )
        if absorption.mu_t_calc is not None:
            center = float(absorption.mu_t_calc)
            # 【一次シグナル (REQ-103 字義)】: |μt − μt_calc| が許容幅超で顕在的逸脱を通知 🔵
            deviation = self._deviation_warning(mu_t, center, absorption.restraint_width)
            if deviation is not None:
                warnings_list.append(deviation)
            # 【補完シグナル (rwp ベース)】: 逸脱が小さくても残差が示す潜在的乖離を通知 🔵
            residual = self._residual_correlation_warning(mu_t, center, rwp)
            if residual is not None:
                warnings_list.append(residual)
        return tuple(warnings_list)

    @staticmethod
    def _deviation_warning(mu_t: float, center: float, width: float) -> str | None:
        """|μt − μt_calc| が許容幅 (restraint_width) を超えたら相関疑い警告文を返す (REQ-103 字義)。

        【ヘルパー関数】: restraint 幅超過の「顕在的逸脱」判定を単一責任で切り出す。
        【単一責任】: fitted μt が restraint 中心からどれだけ離れたかだけを見る (rwp は見ない)。
        🔵 信頼性レベル: REQ-103 / requirements 2.4 の字義に依拠 (許容幅は 🟡 設計裁量)。
        """
        deviation = abs(mu_t - center)
        if deviation <= width:
            return None
        return (
            f"restraint 幅逸脱: fitted μt={mu_t:.4g} が restraint 中心 {center:.4g} から "
            f"|Δμt|={deviation:.4g} 逸脱 (許容幅 {width:.4g} 超)。"
            f"μt–scale 相関による誤収束の疑い (§14)"
        )

    @staticmethod
    def _residual_correlation_warning(mu_t: float, center: float, rwp: float) -> str | None:
        """μt が中心へ拘束されても残差 rwp が閾値超なら潜在的乖離の警告文を返す (補完シグナル)。

        【ヘルパー関数】: restraint が μt を中心へ引き留めた結果、強度プロファイルに系統的残差が
                          残る場合の「潜在的乖離」を検出する。顕在的逸脱 (_deviation_warning) が
                          μt=中心近傍で沈黙するケースを補い、相関リスク (§14) を取りこぼさない。
        🔵 信頼性レベル: requirements 2.4 の相関リスク / REQ-103 補完に依拠 (rwp 閾値は 🟡 設計裁量)。
        """
        if rwp <= _CORRELATION_RWP_THRESHOLD:
            return None
        return (
            f"restraint 逸脱の相関疑い: fitted μt={mu_t:.4g} (restraint 中心 {center:.4g}) "
            f"だが残差 rwp={rwp:.3g}% が残存。μt–scale 相関による誤収束の疑い (§14)"
        )

    def _jacobian(self, phases, names, p, fit_mu_t, full_residual, r) -> np.ndarray:
        """拡張残差 r の各パラメータに対する数値ヤコビアン (前進差分)。

        相パラメータ列に加え、fit_mu_t のとき末尾に μt 列 (restraint 行を含む) を持つ。
        """
        n_phase = len(names)
        n = n_phase + (1 if fit_mu_t else 0)
        mu_t = float(p[n_phase]) if fit_mu_t else 0.0
        jac = np.empty((r.size, n))
        for j in range(n):
            step = 1e-5 * max(1.0, abs(p[j]))
            if j < n_phase:
                # 【相パラメータ摂動】: 対象 j のみ +step し他は現値で前方評価 🔵
                phases_pert = phases
                for idx, name2 in enumerate(names):
                    target = p[idx] + step if idx == j else p[idx]
                    phases_pert = self._set(phases_pert, name2, float(target))
                r_pert = full_residual(phases_pert, mu_t)
            else:
                # 【μt 摂動】: 相パラメータは現値、μt のみ +step し前方評価 (restraint 行も変化) 🔵
                phases_pert = phases
                for idx, name2 in enumerate(names):
                    phases_pert = self._set(phases_pert, name2, float(p[idx]))
                r_pert = full_residual(phases_pert, mu_t + step)
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
