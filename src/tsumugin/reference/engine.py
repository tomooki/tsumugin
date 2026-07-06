"""単一パターン相同定オーケストレーション (仕様 §5 FR-110/117)。

未知の XRD パターン ``(two_theta, intensity)`` と、含まれ得る元素一覧を受け取り、
供給元 (``ReferenceProvider``) の候補相をマッチング・ランキングし、未知相レポートを添えて返す。
既存の純関数 ``find_peaks`` / ``match_score`` / ``unmatched_peaks`` を土台とし、コアは numpy のみ
(scipy・GSAS-II・pymatgen 非依存)、乱数を使わず同一入力に同一出力を返す (NFR-102 決定論)。

前処理として 2 つの絞り込みを冪等に適用する:
- **元素系フィルタ**: 候補相の構成元素が指定元素一覧の部分集合であるものだけを残す。
- **hull フィルタ (FR-103)**: ``energy_above_hull`` が閾値超過の相を落とす。``None`` (MP 未登録) は保持。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Literal

import numpy as np

from ..search.matcher import MatchResult, match_score, unmatched_peaks
from ..search.peaks import find_peaks
from .background import subtract_background
from .kalpha import KAlpha2, add_kalpha2_satellites
from .model import PhaseIdentification, PhaseMatch, ReferencePhase
from .rietveld import align_peaks, align_peaks_anisotropic
from .scoring import dara_peak_score
from .provider import ReferenceProvider

# hull フィルタ既定閾値。FR-103: 100 meV/atom = 0.1 eV/atom。
_DEFAULT_HULL_CUTOFF_EV = 0.1


def augment_kalpha2(
    candidates: Sequence[ReferencePhase], config: KAlpha2
) -> list[ReferencePhase]:
    """各候補相のピークに Kα2 サテライトを付加した新リストを返す (非破壊)。🔵 FR-105

    単相/多相同定が共有する前処理。実測の Kα1/Kα2 二重線に参照ピークを整合させる。
    """
    return [replace(c, peaks=add_kalpha2_satellites(c.peaks, config)) for c in candidates]


def align_references(
    candidates: Sequence[ReferencePhase],
    observed: Sequence,
    *,
    max_strain: float = 0.01,
) -> list[ReferencePhase]:
    """各候補相の計算ピークを観測へ格子整合した新リストを返す (非破壊)。🔵 Phase A/C

    単相/多相同定が共有する前処理。DFT 緩和格子のピーク位置ずれを等方歪み+ゼロシフトで吸収する。
    整合は各相を観測ピーク全体に対して 1 回だけ行う (歪みは相と試料の関係で組合せに依らない)。
    """
    return [
        replace(c, peaks=align_peaks(c.peaks, observed, max_strain=max_strain).aligned_peaks)
        for c in candidates
    ]


def preprocess_intensity(
    intensity: np.ndarray, *, subtract_bg: bool, bg_max_window: int
) -> np.ndarray:
    """観測強度の前処理 (背景減算)。``subtract_bg=False`` なら素通し。🔵"""
    if not subtract_bg:
        return np.asarray(intensity, dtype=float)
    return subtract_background(intensity, max_window=bg_max_window)


def _passes_hull(phase: ReferencePhase, cutoff_ev: float | None) -> bool:
    """hull フィルタ (FR-103)。閾値 None で無効化、energy None は保持、境界は包含 (<=)。🔵"""
    if cutoff_ev is None:
        return True
    if phase.energy_above_hull is None:  # MP 未登録 / 不明は除外しない (FR-103) 🔵
        return True
    return phase.energy_above_hull <= cutoff_ev


def filter_references(
    candidates: Sequence[ReferencePhase],
    elements: Sequence[str],
    *,
    hull_cutoff_ev: float | None = _DEFAULT_HULL_CUTOFF_EV,
) -> list[ReferencePhase]:
    """候補相に元素系部分集合フィルタ + hull フィルタ (FR-103) を冪等に適用する。🔵

    単相同定 (``identify_phases``) と多相同定 (``identify_phase_mixtures``) が共有する前処理。
    構成元素が ``elements`` の部分集合である相のみを残し、hull 閾値超過の相を落とす
    (``energy_above_hull=None`` の未登録相は保持)。

    Args:
        candidates: 供給元が返した候補相。
        elements: 許容元素系 (非空)。
        hull_cutoff_ev: hull フィルタ閾値 (eV/atom)。``None`` で無効化。

    Returns:
        フィルタ後の候補相リスト (入力順を保つ)。
    """
    allowed = set(elements)
    return [
        phase
        for phase in candidates
        if set(phase.element_system) <= allowed and _passes_hull(phase, hull_cutoff_ev)
    ]


def identify_phases(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    provider: ReferenceProvider,
    *,
    elements: Sequence[str],
    hull_cutoff_ev: float | None = _DEFAULT_HULL_CUTOFF_EV,
    min_peak_height_frac: float = 0.05,
    match_tol_deg: float = 0.15,
    max_results: int | None = None,
    high_r_threshold: float | None = None,
    subtract_bg: bool = False,
    bg_max_window: int = 50,
    kalpha2: KAlpha2 | None = None,
    scoring: Literal["dara", "coverage"] = "dara",
    refine_lattice: bool = False,
    max_strain: float = 0.01,
    strain_penalty: float = 0.0,
    rerank_top_k: int = 0,
    rerank_wavelength: float = 1.5406,
) -> PhaseIdentification:
    """未知パターン + 元素一覧から候補相を同定する (FR-110/117)。🔵

    【処理フロー】: (背景減算) → 観測ピーク検出 → 供給元から候補相取得 → 元素系 + hull フィルタ →
      (Kα2 サテライト付加) → 候補ごとに ``match_score`` → score 降順 (同点 phase_id 昇順) に
      ランキング → 全生存候補の説明力から未知相レポートを構築。``max_results`` は表示件数のみ絞り、
      未知相判定は絞り込み前の全生存候補で行う (説明力の隠蔽をしない)。

    Args:
        two_theta: 2θ 軸 (度)。1 次元・昇順・``intensity`` と同長。
        intensity: 観測強度。1 次元・``two_theta`` と同長。
        provider: 相ライブラリ供給元 (``fetch(elements)``)。
        elements: 含まれ得る元素記号列 (非空)。供給元へのクエリ + 元素系フィルタに使う。
        hull_cutoff_ev: hull フィルタ閾値 (eV/atom, キーワード専用)。``None`` で無効化。既定 0.1 (FR-103)。
        min_peak_height_frac: 観測ピーク検出の高さ下限比率。既定 0.05。
        match_tol_deg: ピーク一致許容差 (度)。既定 0.15。
        max_results: 返すマッチ件数の上限。``None`` で無制限。
        high_r_threshold: 全候補の最大 score がこの値未満なら未知相フラグを強制 (REQ-106)。``None`` で無効。
        subtract_bg: True で観測強度に SNIP 背景減算を前処理適用する (実測データの精度向上)。
        bg_max_window: SNIP の最大クリップ窓幅 (点数)。``subtract_bg`` 時のみ有効。
        kalpha2: 参照ピークに付加する Kα2 サテライト設定。``None`` で無効 (単色近似)。
        scoring: マッチスコア方式。``"dara"`` (既定, Fei et al. 2026 式1: 実測強度正規化 +
            extra 罰。peak-rich 相を希釈しない) / ``"coverage"`` (旧 ``match_score``: 一致率と
            被覆率の等重み平均)。
        refine_lattice: True で各候補の計算ピークを等方格子歪み+ゼロシフトで観測へ整合してから
            スコアする (DFT 緩和格子のピーク位置ずれを吸収, Phase A)。
        max_strain: ``refine_lattice`` 時の等方歪み上限 (既定 0.01 = 1%, Dara 準拠)。
        strain_penalty: ランキングで格子シフトを罰する係数 (Dara FoM の ΔU に対応)。実効スコア =
            ``score − strain_penalty·|strain|``。大きな格子調整を要した相を下げる。既定 0 (無効)。
        rerank_top_k: >0 で**上位 K 候補のみ異方格子整合で再スコア**する (Issue #20 hybrid)。等方
            ``refine_lattice`` は 1 自由度で DFT の**軸別**格子誤差を吸収できず正解相のスコアを負に落とす
            ことがある。上位 K に限り軸別 (``align_peaks_anisotropic``) で再整合→再スコアし、識別マージンを
            上げる (実測: alpha/delta で margin +0.09→+1.14)。全候補でなく top-K に限るのは過剰整合による
            偽陽性と計算コストを抑えるため。格子情報 (cell/crystal_system/hkl) を持たない相はスキップ。
        rerank_wavelength: 異方再スコアの線源波長 (Å, hkl↔2θ 変換用)。既定 Cu Kα1。

    Returns:
        ``PhaseIdentification`` (ランキング済みマッチ + 未知相レポート + 観測ピーク)。

    Raises:
        ValueError: ``elements`` が空のとき。
    """
    if len(elements) == 0:
        raise ValueError("elements は非空の元素記号列である必要があります (相同定の対象元素系)。")

    # 【背景減算】: 実測の遅変化背景を SNIP で除く (オプション、実データ精度向上) 🔵
    intensity = preprocess_intensity(
        intensity, subtract_bg=subtract_bg, bg_max_window=bg_max_window
    )

    # 【観測ピーク検出】: 局所極大 + 高さ閾値。全ゼロ等は空タプルへ縮退 (EDGE-003) 🔵
    observed = find_peaks(two_theta, intensity, min_height_frac=min_peak_height_frac)

    # 【候補取得】: 供給元へ元素一覧をそのまま渡す (クエリ意図を保存) 🔵
    candidates = provider.fetch(elements)

    # 【前処理フィルタ】: 元素系部分集合 + hull を冪等に適用する 🔵 FR-103
    survivors = filter_references(candidates, elements, hull_cutoff_ev=hull_cutoff_ev)

    # 【Kα2 サテライト】: 実測の二重線に整合させ未マッチ低減 (オプション) 🔵 FR-105
    if kalpha2 is not None:
        survivors = augment_kalpha2(survivors, kalpha2)

    # 【マッチング】: 生存候補ごとにスコアを求める (dara: 式1 / coverage: 旧 match_score) 🔵 FR-111
    match_results: list[MatchResult] = []
    matches: list[PhaseMatch] = []
    for i, phase in enumerate(survivors):
        # 【格子整合】: DFT 格子ズレを吸収するため計算ピークを観測へ整合してからスコアする 🔵 Phase A
        strain = 0.0
        if refine_lattice:
            alignment = align_peaks(phase.peaks, observed, max_strain=max_strain)
            calc_peaks = alignment.aligned_peaks
            strain = alignment.strain
        else:
            calc_peaks = phase.peaks
        if scoring == "dara":
            ds = dara_peak_score(calc_peaks, observed, tol_deg=match_tol_deg)
            score = ds.score
            matched_observed = ds.matched_observed
            extra_calculated = ds.extra_calculated
        else:
            mr = match_score(calc_peaks, observed, tol_deg=match_tol_deg, candidate_index=i)
            score = mr.score
            matched_observed = mr.matched_observed
            extra_calculated = mr.unmatched_candidate
        # 未知相レポート (unmatched_peaks) 用に MatchResult 互換へ写す (方式に依らず統一) 🔵
        match_results.append(
            MatchResult(
                candidate_index=i,
                score=score,
                matched_observed=matched_observed,
                unmatched_candidate=extra_calculated,
            )
        )
        matches.append(
            PhaseMatch(
                reference=phase,
                score=score,
                matched_observed=matched_observed,
                extra_calculated=extra_calculated,
                strain=strain,
            )
        )

    # 【決定論ランキング】: 実効スコア (score − strain_penalty·|strain|) 降順・同点 phase_id 昇順 🔵
    #   strain_penalty>0 で大きな格子シフトを要した相を下げる (Dara FoM ΔU)。既定 0 で純 score。
    def _effective(m: PhaseMatch) -> tuple[float, str]:
        return (-(m.score - strain_penalty * abs(m.strain)), m.reference.phase_id)

    matches.sort(key=_effective)

    # 【異方 re-score (Issue #20 hybrid)】: 上位 K のみ軸別格子整合で再スコアし再ランキングする 🔵
    if rerank_top_k > 0 and observed:
        matches = _rerank_anisotropic(
            matches, tuple(observed), top_k=rerank_top_k, scoring=scoring,
            match_tol_deg=match_tol_deg, wavelength=rerank_wavelength,
        )
        matches.sort(key=_effective)

    # 【未知相レポート】: 全生存候補の説明力で未マッチ観測・extra・未知相フラグを構築 🔵 FR-117
    #   max_results による表示絞り込みの前に計算し、説明力の隠蔽を避ける。
    high_r = bool(
        high_r_threshold is not None
        and matches
        and max(m.score for m in matches) < high_r_threshold
    )
    report = unmatched_peaks(match_results, observed, high_r_flag=high_r)

    # 【表示絞り込み】: max_results はマッチ表示件数のみ制限する 🔵
    if max_results is not None:
        matches = matches[:max_results]

    return PhaseIdentification(
        matches=tuple(matches),
        unmatched=report,
        observed_peaks=tuple(observed),
    )


def _rerank_anisotropic(
    matches: list[PhaseMatch],
    observed: tuple,
    *,
    top_k: int,
    scoring: str,
    match_tol_deg: float,
    wavelength: float,
) -> list[PhaseMatch]:
    """上位 top_k マッチを異方格子整合で再スコアした新リストを返す (Issue #20 hybrid)。

    各上位候補を ``align_peaks_anisotropic`` で軸別に観測へ整合 → 同じスコア方式で再評価し、score と
    strain (異方=最大軸相対変化) を差し替える。格子情報/hkl 不足・未改善の候補は等方スコアのまま残す
    (align が None)。top_k を超える候補は無変更。再ソートは呼び出し側が行う。
    """
    rng = (min(p.position for p in observed), max(p.position for p in observed))
    rr = min(top_k, len(matches))
    head: list[PhaseMatch] = []
    for m in matches[:rr]:
        al = align_peaks_anisotropic(
            m.reference, observed, wavelength=wavelength, two_theta_range=rng
        )
        if al is None:
            head.append(m)
            continue
        if scoring == "dara":
            ds = dara_peak_score(al.aligned_peaks, observed, tol_deg=match_tol_deg)
            head.append(
                PhaseMatch(
                    reference=m.reference, score=ds.score,
                    matched_observed=ds.matched_observed,
                    extra_calculated=ds.extra_calculated, strain=al.strain,
                )
            )
        else:
            mr = match_score(al.aligned_peaks, observed, tol_deg=match_tol_deg, candidate_index=0)
            head.append(
                PhaseMatch(
                    reference=m.reference, score=mr.score,
                    matched_observed=mr.matched_observed,
                    extra_calculated=mr.unmatched_candidate, strain=al.strain,
                )
            )
    return head + list(matches[rr:])
