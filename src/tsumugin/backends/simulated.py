"""合成回折パターン精密化バックエンド。

GSAS-II 非導入環境で全パイプラインを end-to-end 検証するための、決定論的な参照実装。
相ごとにガウシアンピーク列を格子・scale から生成する前方モデルと、解放パラメータのみを
Levenberg–Marquardt で最適化する精密化を提供する。乱数は一切使わない (NFR-102)。
"""

from __future__ import annotations

import math
from dataclasses import replace as _dc_replace
from typing import Mapping, Sequence

import numpy as np

from ..absorption.model import AbsorptionConfig, transmission_factor
from ..evidence.noise import noise_extras
from ..model import LatticeParams, PhaseInstance
from .base import Curvature, RefinementModel, RefinementResult, parse_param

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
        estimate_noise: bool = False,
    ) -> None:
        self.peak_fwhm = float(peak_fwhm)
        self.wavelength = float(wavelength)
        self._hkl_table = dict(hkl_table) if hkl_table else {}
        # 【吸収設定】: None なら従来挙動 (透過因子乗算なし)。設定時は前方モデルへ吸収を織り込む 🔵
        self._absorption = absorption
        # 【Issue #64 / FR-123】: 既定 False (既存呼び出しとビット同一)。True のときのみ
        # refine() の最終残差から evidence.noise.estimate_noise_em を呼び、結果を
        # RefinementResult.noise_scale / globals["noise_scale"] / warnings へ記録する。🔵
        self._estimate_noise = bool(estimate_noise)

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
        # 【σ リセット】: 何も解放しない呼び出しでも σ セマンティクス (当該 refine() の推定のみ)
        #   に従い、入力に残る古い sigma/sigma_source を空へリセットする 🔵
        if not names and not fit_mu_t:
            y_calc0 = self._simulate(phases, two_theta, const_mu_t)
            noise_scale0, noise_globals0, noise_warnings0 = self._noise_estimate_extras(
                y_obs, y_calc0, weights
            )
            return RefinementResult(
                phases=self._apply_lattice_sigma(
                    phases, names, np.zeros(0), False, full_residual, r, chi2
                ),
                chi2=chi2,
                rwp=_rwp(weights, y_obs, y_calc0),
                n_obs=n_obs,
                n_params=0,
                converged=True,
                n_cycles=1,
                free_params=frozenset(),
                globals=noise_globals0,
                warnings=noise_warnings0,
                noise_scale=noise_scale0,
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
        # 【Issue #64 / FR-123】: opt-in (estimate_noise=True) のときのみ EM ノイズ推定を実行し、
        #   globals/warnings/noise_scale へ由来を記録する (既定 False は空 tuple/dict/None) 🔵
        noise_scale, noise_globals, noise_warnings = self._noise_estimate_extras(
            y_obs, y_final, weights
        )
        globals_out = {**globals_out, **noise_globals}
        warnings_out = warnings_out + noise_warnings
        # 【最終 J の一括計算 (Issue #76)】: 最終受理 p で J を 1 回だけ計算し、格子 σ 導出と
        #   Curvature 公開 (JᵀJ) で共有する (二重計算の排除)。chi2/J が非有限なら双方とも提供しない 🔵
        jac_final: np.ndarray | None = None
        if math.isfinite(chi2):
            jac_candidate = self._jacobian(phases, names, p, fit_mu_t, full_residual, r)
            if bool(np.all(np.isfinite(jac_candidate))):
                jac_final = jac_candidate
        # 【格子 σ】: 最終受理パラメータの JᵀJ 漸近共分散から解放格子属性の σ を導出し、
        #   解放しなかった相の古い σ はリセットする (FR-306/NFR-107) 🔵
        phases = self._apply_lattice_sigma(
            phases, names, p, fit_mu_t, full_residual, r, chi2, jac=jac_final
        )
        # 【Curvature 公開 (Issue #76)】: JᵀJ = −logL(=χ²/2) の Gauss-Newton Hessian。列順は
        #   names 順 + (fit_mu_t 時) 末尾 "global.mu_t"。非有限経路は None (NaN を漏らさない) 🔵
        curvature: Curvature | None = None
        if jac_final is not None:
            curve_names = tuple(names) + (("global.mu_t",) if fit_mu_t else ())
            curvature = Curvature(
                param_names=curve_names,
                point=p.copy(),
                hessian=jac_final.T @ jac_final,
            )
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
            noise_scale=noise_scale,
            curvature=curvature,
        )

    def _noise_estimate_extras(
        self, y_obs: np.ndarray, y_calc: np.ndarray, weights: np.ndarray
    ) -> tuple[float | None, dict[str, float], tuple[str, ...]]:
        """opt-in (``estimate_noise=True``) のときのみ EM ノイズ推定を実行する (Issue #64 / FR-123)。

        【機能概要】: 最終受理パラメータでの観測–計算残差 ``y_obs - y_calc`` と統計重み
          ``weights`` から ``evidence.noise.noise_extras`` (backend 非依存の共有オーケストレーション
          関数) へ委譲するだけの薄いラッパ (Issue #64 レビュー対応: 将来の GSAS-II backend 配線が
          同一実装を再利用できるように、EM 呼び出しの判定・変換ロジックそのものは backend 非依存に
          抽出済み)。既定オフ (``estimate_noise=False``) では追加計算なしでビット同一を保つ
          (REQ-404、``noise_extras`` 側の ``enabled=False`` 早期リターンに従う)。

        Args:
            y_obs: 観測強度。
            y_calc: 最終受理パラメータでの前方モデル計算強度。
            weights: 統計重み ``w_i`` (``estimate_noise_em`` が期待する分散モデルの重み)。

        Returns:
            ``estimate_noise=False`` なら ``(None, {}, ())``。``True`` なら
            ``(estimate.scale, {"noise_scale": estimate.scale}, (由来文字列,))``。
        """
        return noise_extras(y_obs - y_calc, weights, enabled=self._estimate_noise)

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

    def _apply_lattice_sigma(
        self,
        phases: tuple[PhaseInstance, ...],
        names: list[str],
        p: np.ndarray,
        fit_mu_t: bool,
        full_residual,
        r: np.ndarray,
        chi2: float,
        *,
        jac: np.ndarray | None = None,
    ) -> tuple[PhaseInstance, ...]:
        """最終受理パラメータの JᵀJ 漸近共分散から解放格子属性の σ を書き込む (FR-306/NFR-107)。

        【σ セマンティクス (統一定義)】: 出力の ``lattice.sigma``/``sigma_source`` は「当該
        refine() 呼び出しで推定した不確かさのみ」を表す。今回解放した格子属性のみからなる
        新 dict へ**置換**し (既存 sigma のマージ持ち越しは行わない)、今回格子を解放しなかった
        相は sigma={} / sigma_source="" にリセットする (入力に残る古い σ の混入排除。
        GSASIIBackend ``_read_back`` と対称)。

        【式】: 標準的な非線形最小二乗の漸近共分散
        ``cov = pinv(JᵀJ) × reduced_chi2``、``reduced_chi2 = chi2 / max(n_res − n_params, 1)``。
        J は最終受理パラメータ p で 1 回再計算した weighted Jacobian (restraint 行を含む)、
        n_res は restraint 行を含む残差ベクトル全長、n_params は μt を含む解放総数。
        解放した格子属性に対応する対角成分のみ ``σ = sqrt(cov[i,i])`` として抽出し
        ``sigma_source="covariance"`` を付す (scale/μt 等は対象外)。乱数不使用・同一入力で
        ビット同一 (NFR-102)。

        【識別可能性の事前判定 (Issue #66 レビュー対応)】: orthorhombic 近似の前方モデルは
        alpha/beta/gamma を一切参照しないため、これらを解放しても Jacobian 列は恒等的に 0
        (前進差分で摂動しても forward モデルが変化しない)。この列を含めたまま pinv(JᵀJ) を
        取ると、丸め誤差により当該対角成分が厳密な 0 でなく var≈1e-19 等の「偽高精度 σ」として
        混入することがある。そこで σ 組み立て前に、解放した格子属性ごとに Jacobian 列ノルム
        ``norm(jac[:, j])`` を確認し、J の全列 (μt 含む) の最大ノルムに対して
        ``norm(jac[:, j]) <= 1e-12 × 最大列ノルム`` (厳密な 0 列も max_col_norm=0 の退化ケースも
        自然に包含する相対閾値) なら「モデルに無寄与」と判定してその属性のみ σ エントリから
        除外する (相全体は殺さない)。**相単位の {} への丸ごと縮退は、識別可能と判定された属性の
        var が非有限/非正の場合のみ**に限定する (非識別属性しか解放していない場合に
        well-conditioned な他属性まで巻き添えにしない)。非識別属性 (モデルに無寄与) は σ 未提供、
        識別可能属性の σ は保持する。

        【ガード (NaN を絶対に書き込まない)】: chi2 非有限 / J に非有限 / pinv 失敗
        (LinAlgError) / 識別可能属性の σ が非有限・非正 のいずれでも、当該相の sigma は
        {} + "" に縮退する。

        :param phases: 精密化後の相集合
        :param names: 解放された free_params 名 (``phase{i}.lattice.a`` 等、p の先頭部と同順)
        :param p: 最終受理パラメータベクトル (fit_mu_t 時は末尾に μt)
        :param fit_mu_t: μt を精密化したか (J の μt 列の有無)
        :param full_residual: 拡張残差関数 (restraint 行を含む)
        :param r: 最終受理パラメータでの拡張残差ベクトル
        :param chi2: 精密化後の残差二乗和 (restraint 項含む)
        :returns: σ セマンティクスに従い sigma/sigma_source を更新した新しい phases
        """
        # 【解放格子属性の索引】: 相 idx -> {attr: p 内の列位置 j} (names 順 = J の列順) 🔵
        by_phase: dict[int, dict[str, int]] = {}
        for j, name in enumerate(names):
            idx, key = parse_param(name)
            if key.startswith("lattice."):
                by_phase.setdefault(idx, {})[key.split(".", 1)[1]] = j

        # 【共分散算出】: ガードを全て通過した場合のみ相ごとの σ dict を組み立てる 🔵
        sigma_by_phase: dict[int, dict[str, float]] = {}
        if by_phase and math.isfinite(chi2):
            dof = max(int(r.size) - int(p.size), 1)  # 【n_res 自由度】: restraint 行を含む 🔵
            reduced_chi2 = chi2 / dof
            # 【J の供給/再計算】: refine() 本経路は最終受理 p の J を渡してくる (Issue #76 の
            #   Curvature と共有・二重計算排除)。未供給の呼び出し (早期リターン経路等) のみ
            #   最終 p で 1 回計算する 🔵
            if jac is None:
                jac = self._jacobian(phases, names, p, fit_mu_t, full_residual, r)
            cov: np.ndarray | None = None
            if bool(np.all(np.isfinite(jac))):
                try:
                    cov = np.linalg.pinv(jac.T @ jac) * reduced_chi2
                except np.linalg.LinAlgError:
                    cov = None  # 【pinv 失敗】: σ 未提供へ縮退 🔵
            if cov is not None:
                # 【識別可能性の閾値】: 全列 (μt 含む) の最大ノルムに対する相対閾値 🔵
                col_norms = np.linalg.norm(jac, axis=0)
                max_col_norm = float(np.max(col_norms)) if col_norms.size else 0.0
                identifiability_tol = 1e-12 * max_col_norm
                for idx, attrs in by_phase.items():
                    sigma: dict[str, float] = {}
                    degraded = False
                    for attr, j in attrs.items():
                        if float(col_norms[j]) <= identifiability_tol:
                            # 【非識別属性】: モデルに無寄与 → この属性のみ σ 未提供 (相は殺さない) 🔵
                            continue
                        var = float(cov[j, j])
                        if not (math.isfinite(var) and var > 0.0):
                            # 【識別可能属性の σ が非有限/非正】: 相全体を丸ごと {} + "" へ縮退 🔵
                            degraded = True
                            break
                        sigma[attr] = math.sqrt(var)
                    if degraded:
                        sigma = {}
                    if sigma:
                        sigma_by_phase[idx] = sigma

        # 【置換 + リセット】: σ を得た相は新 dict へ置換、それ以外は空へリセット (混入排除) 🔵
        phases_list = list(phases)
        for idx, phase in enumerate(phases_list):
            new_sigma = sigma_by_phase.get(idx)
            if new_sigma:
                phases_list[idx] = phase.with_updates(
                    lattice=_dc_replace(
                        phase.lattice, sigma=new_sigma, sigma_source="covariance"
                    )
                )
            elif phase.lattice.sigma or phase.lattice.sigma_source:
                phases_list[idx] = phase.with_updates(
                    lattice=_dc_replace(phase.lattice, sigma={}, sigma_source="")
                )
        return tuple(phases_list)


def _replace_lattice(lattice: LatticeParams, attr: str, value: float) -> LatticeParams:
    return _dc_replace(lattice, **{attr: value})


def _rwp(weights: np.ndarray, y_obs: np.ndarray, y_calc: np.ndarray) -> float:
    num = float(np.sum(weights * (y_obs - y_calc) ** 2))
    den = float(np.sum(weights * y_obs**2))
    if den <= 0:
        return 0.0
    return 100.0 * math.sqrt(num / den)
