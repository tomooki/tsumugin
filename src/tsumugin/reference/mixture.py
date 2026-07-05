"""多相同定 — 相ライブラリ候補を既存木探索へ接続する (仕様 §5 FR-110/115)。

単相ランキング (``identify_phases``) を超えて、観測パターンを複数相の混合として同定する。
参照相のピーク列を ``RefinementBackend`` として供給する ``ReferenceBackend`` アダプタを介し、
既存の ``HypothesisTreeSearch`` (相組合せ木探索・動的枝刈り・BIC ランキング) を再利用する。

コアは numpy のみ (pymatgen 非依存)。``ReferenceBackend`` は参照ピークをガウシアン描画し
(``simulate``)、相スケールを重み付き最小二乗でフィットする (``refine``)。chi2/rwp のセマンティクスは
``SimulatedBackend`` と統一し (weights 既定 = 1/max(y,1)、chi2 = Σ w(yo-yc)²、rwp[%])、BIC 比較の
一貫性を保つ (CLAUDE.md 不変条件)。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import replace

import numpy as np

from ..backends.base import RefinementModel, RefinementResult
from ..model import LatticeParams, PhaseInstance
from ..search.peaks import Peak, find_peaks
from ..search.tree import HypothesisTreeSearch, SearchConfig, SearchResult
from .engine import (
    _DEFAULT_HULL_CUTOFF_EV,
    augment_kalpha2,
    filter_references,
    preprocess_intensity,
)
from .kalpha import KAlpha2
from .provider import ReferenceProvider
from .rietveld import align_peaks
from .scoring import dara_peak_score
from .threshold import inflection_threshold

# 絞り込みスコアの係数 (Dara の木戦略準拠): extra を強く罰し (−1.0)、missing は弱く (−0.01)。
# missing ピークは他相が説明し得るため罰を弱め、無関係相の予測する余剰 extra ピークを強く罰する。
_PRUNE_EXTRA_WEIGHT = 1.0
_PRUNE_MISSING_WEIGHT = 0.01

__all__ = ["ReferenceBackend", "identify_phase_mixtures"]

_FWHM_TO_SIGMA = 1.0 / (2.0 * math.sqrt(2.0 * math.log(2.0)))
# ダミー格子。``ReferenceBackend`` は格子を参照せず peak_map でピークを供給するため、候補
# ``PhaseInstance`` の必須 lattice フィールドを満たすためだけの器 (値に意味はない)。
_PLACEHOLDER_LATTICE = LatticeParams(1.0, 1.0, 1.0)


def _rwp(weights: np.ndarray, y_obs: np.ndarray, y_calc: np.ndarray) -> float:
    """重み付き Rwp[%] (``SimulatedBackend._rwp`` と同式・同スケール)。🔵"""
    num = float(np.sum(weights * (y_obs - y_calc) ** 2))
    den = float(np.sum(weights * y_obs**2))
    if den <= 0:
        return 0.0
    return 100.0 * math.sqrt(num / den)


class ReferenceBackend:
    """参照相のピーク列を供給する ``RefinementBackend`` アダプタ。🔵 FR-110/115

    ``peak_map`` は ``phase_ref`` → 参照ピーク列。木探索はこの backend の ``simulate`` で候補
    ピークを生成し、``refine`` で相スケールをフィットして chi2/rwp を得る。格子・座標・ADP は
    フィットせず、相同定に必要なスケール (相分率の代理) のみを線形最小二乗で決める。
    """

    name = "reference"

    def __init__(
        self, peak_map: Mapping[str, Sequence[Peak]], *, peak_fwhm_deg: float = 0.1
    ) -> None:
        # phase_ref → ピーク列 (不変タプル化)。未知 phase_ref は空ピーク (寄与なし) に縮退する。
        self._peak_map: dict[str, tuple[Peak, ...]] = {
            ref: tuple(peaks) for ref, peaks in peak_map.items()
        }
        self._sigma = peak_fwhm_deg * _FWHM_TO_SIGMA

    def _render_unit(self, phase_ref: str, two_theta: np.ndarray) -> np.ndarray:
        """1 相の参照ピークを単位スケール (相スケール=1) でガウシアン描画する。🔵"""
        y = np.zeros_like(two_theta)
        for peak in self._peak_map.get(phase_ref, ()):  # 未知 ref は空 → 寄与なし
            y += peak.height * np.exp(-0.5 * ((two_theta - peak.position) / self._sigma) ** 2)
        return y

    def simulate(self, phases: Sequence[PhaseInstance], two_theta: np.ndarray) -> np.ndarray:
        """相スケールを乗じた参照ピークの重ね合わせを返す (木探索の候補ピーク生成に使う)。🔵"""
        two_theta = np.asarray(two_theta, dtype=float)
        y = np.zeros_like(two_theta)
        for phase in phases:
            y += phase.scale * self._render_unit(phase.phase_ref, two_theta)
        return y

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        """相スケールを重み付き線形最小二乗でフィットする (相同定用の簡約精密化)。🔵 FR-110

        各相の単位スケールパターンを基底とし、観測強度への非負線形結合を解く。格子等は
        フィットしない (探索モードで解放される a/b/c は無視)。chi2/rwp は ``SimulatedBackend``
        と同一セマンティクスで返し、BIC ランキングの一貫性を保つ。``n_params`` は相数 = 相ごとの
        スケール数とし、相数増加を BIC が正しくペナルティする (多相の過剰当てはめ抑制)。
        """
        two_theta = np.asarray(model.two_theta, dtype=float)
        y_obs = np.asarray(model.intensity, dtype=float)
        n_obs = int(y_obs.size)
        if model.weights is not None:
            weights = np.asarray(model.weights, dtype=float)
        else:
            weights = 1.0 / np.maximum(y_obs, 1.0)  # SimulatedBackend と同一の既定重み 🔵
        sqrt_w = np.sqrt(weights)
        phases = model.phases
        n_phase = len(phases)

        if n_phase == 0:  # 相なしは観測全体が残差 (EDGE 縮退, 例外化しない)
            chi2 = float(np.sum(weights * y_obs**2))
            return RefinementResult(
                phases=phases,
                chi2=chi2,
                rwp=_rwp(weights, y_obs, np.zeros_like(y_obs)),
                n_obs=n_obs,
                n_params=0,
                converged=True,
                n_cycles=1,
                free_params=model.free_params,
            )

        # 【基底行列】: 各相の単位スケールパターンを列に持つ (n_obs × n_phase) 🔵
        basis = np.column_stack(
            [self._render_unit(phase.phase_ref, two_theta) for phase in phases]
        )
        # 【重み付き最小二乗】: min ||√w (y - B s)||。非負スケール制約はクリップで近似する 🟡
        design = sqrt_w[:, None] * basis
        target = sqrt_w * y_obs
        scales, *_ = np.linalg.lstsq(design, target, rcond=None)
        scales = np.clip(scales, 0.0, None)  # 相分率は非負 (負スケールを 0 へ丸める) 🔵

        y_calc = basis @ scales
        chi2 = float(np.sum(weights * (y_obs - y_calc) ** 2))
        rwp = _rwp(weights, y_obs, y_calc)
        fitted = tuple(
            phase.with_updates(scale=float(s)) for phase, s in zip(phases, scales)
        )
        return RefinementResult(
            phases=fitted,
            chi2=chi2,
            rwp=rwp,
            n_obs=n_obs,
            n_params=n_phase,  # 相ごとに 1 スケール → BIC が相数をペナルティ 🔵
            converged=True,
            n_cycles=1,
            free_params=model.free_params,
        )


def identify_phase_mixtures(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    provider: ReferenceProvider,
    *,
    elements: Sequence[str],
    hull_cutoff_ev: float | None = _DEFAULT_HULL_CUTOFF_EV,
    config: SearchConfig | None = None,
    peak_fwhm_deg: float = 0.1,
    subtract_bg: bool = False,
    bg_max_window: int = 50,
    kalpha2: KAlpha2 | None = None,
    prefilter_top_k: int | None = None,
    prefilter_dynamic: bool = False,
    match_tol_deg: float = 0.15,
    refine_lattice: bool = False,
    max_strain: float = 0.01,
    strain_penalty: float = 0.0,
) -> SearchResult:
    """未知パターン + 元素一覧から多相混合を同定する (FR-110/115)。🔵

    供給元の候補相を元素系 + hull でフィルタ (``filter_references``) し、参照ピークを
    ``ReferenceBackend`` として既存 ``HypothesisTreeSearch`` に載せて相組合せを探索する。
    返り値は木探索ネイティブの ``SearchResult`` (ランキング済み多相仮説 + 未マッチ集約 + 台帳)。

    Args:
        two_theta: 2θ 軸 (度)。1 次元・``intensity`` と同長。
        intensity: 観測強度。1 次元。
        provider: 相ライブラリ供給元 (``fetch(elements)``)。
        elements: 含まれ得る元素記号列 (非空)。
        hull_cutoff_ev: hull フィルタ閾値 (eV/atom)。``None`` で無効化。既定 0.1 (FR-103)。
        config: 木探索設定 (``max_phases`` 等)。``None`` で既定 ``SearchConfig()``。
        peak_fwhm_deg: 参照ピーク描画の半値幅 (度)。既定 0.1。
        subtract_bg: True で観測強度に SNIP 背景減算を前処理適用する (実測データの精度向上)。
        bg_max_window: SNIP の最大クリップ窓幅 (点数)。``subtract_bg`` 時のみ有効。
        kalpha2: 参照ピークに付加する Kα2 サテライト設定。``None`` で無効 (単色近似)。
        prefilter_top_k: 絞り込みの安全上限。実効スコア上位 k 相のみ木探索へ渡す。``None`` で無制限。
            ``prefilter_dynamic`` と併用可 (動的閾値通過後にさらに上限を掛ける)。
        prefilter_dynamic: True で動的閾値 (スコア分布の変曲点, Dara 準拠) を適用し、良い相を件数に
            依らず残す (固定 top-k より正解を落としにくい)。閾値通過相のみ木探索へ渡す。
        match_tol_deg: 絞り込みスコアのピーク一致許容差 (度)。
        refine_lattice: True で各候補の計算ピークを観測へ格子整合してから絞り込み/木探索に使う
            (DFT 緩和格子のピーク位置ずれを吸収, Phase A/C)。整合してからスコアするので正解を落とさず、
            junk は強い extra 罰 + ``strain_penalty`` で沈む。
        max_strain: ``refine_lattice`` 時の等方歪み上限 (既定 0.01 = 1%)。
        strain_penalty: 絞り込みスコアで格子シフトを罰す係数 (Dara FoM の ΔU)。実効スコア =
            score − strain_penalty·|strain|。大きな整合を要した無関係相を下げる。既定 0。

    Returns:
        ``SearchResult``。候補ゼロ (フィルタ全滅) でも例外化せず空へ縮退する。

    Raises:
        ValueError: ``elements`` が空のとき。
    """
    if len(elements) == 0:
        raise ValueError("elements は非空の元素記号列である必要があります (相同定の対象元素系)。")

    # 【背景減算】: 実測背景を SNIP で除く (オプション)。木探索の refine も背景減算後を当てる 🔵
    intensity = preprocess_intensity(
        intensity, subtract_bg=subtract_bg, bg_max_window=bg_max_window
    )

    survivors = filter_references(provider.fetch(elements), elements, hull_cutoff_ev=hull_cutoff_ev)
    # 【Kα2 サテライト】: 実測二重線に参照を整合させる (オプション) 🔵 FR-105
    if kalpha2 is not None:
        survivors = augment_kalpha2(survivors, kalpha2)

    # 【整合 → 絞り込み】: Dara 準拠。各候補を観測へ格子整合してから (DFT ズレ吸収) Dara スコアで
    #   評価し、動的閾値 (変曲点) + 安全 top-k で絞る。整合後にスコアするので正解を落とさず、junk は
    #   強い extra 罰 + 格子シフト罰 (strain_penalty) で沈むため偽マッチしても残らない (Fei et al. 2026)。
    pruning = prefilter_dynamic or prefilter_top_k is not None
    if refine_lattice or pruning:
        observed = find_peaks(two_theta, intensity)
        evaluated: list[tuple] = []  # (整合済 ref, 実効スコア)
        for ref in survivors:
            if refine_lattice:
                al = align_peaks(ref.peaks, observed, max_strain=max_strain)
                ref = replace(ref, peaks=al.aligned_peaks)  # noqa: PLW2901 整合済ピークを下流へ
                strain = abs(al.strain)
            else:
                strain = 0.0
            ds = dara_peak_score(
                ref.peaks,
                observed,
                tol_deg=match_tol_deg,
                w_extra=_PRUNE_EXTRA_WEIGHT,
                w_missing=_PRUNE_MISSING_WEIGHT,
            )
            evaluated.append((ref, ds.score - strain_penalty * strain))

        if pruning:
            if prefilter_dynamic:
                threshold = inflection_threshold([e for _, e in evaluated])
                kept = [(r, e) for r, e in evaluated if e >= threshold]
                # 【安全網】: 変曲点で全滅した場合は最良 1 相を残す (相同定を空にしない) 🔵
                if not kept and evaluated:
                    kept = sorted(evaluated, key=lambda t: (-t[1], t[0].phase_id))[:1]
            else:
                kept = list(evaluated)
            # 【安全上限】: top-k 指定時は実効スコア降順で上位のみ (動的閾値と併用可) 🔵
            if prefilter_top_k is not None and len(kept) > prefilter_top_k:
                kept = sorted(kept, key=lambda t: (-t[1], t[0].phase_id))[:prefilter_top_k]
            survivors = [r for r, _ in kept]
        else:
            survivors = [r for r, _ in evaluated]

    # 【候補 + backend 構築】: 各参照相を PhaseInstance 候補に、ピークを peak_map に写す 🔵
    peak_map = {ref.phase_id: ref.peaks for ref in survivors}
    candidates = tuple(
        PhaseInstance(phase_ref=ref.phase_id, lattice=_PLACEHOLDER_LATTICE) for ref in survivors
    )
    backend = ReferenceBackend(peak_map, peak_fwhm_deg=peak_fwhm_deg)
    search = HypothesisTreeSearch(
        backend, config=config if config is not None else SearchConfig()
    )
    return search.search(two_theta, intensity, candidates)
