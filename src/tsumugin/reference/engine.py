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

import numpy as np

from ..search.matcher import MatchResult, match_score, unmatched_peaks
from ..search.peaks import find_peaks
from .model import PhaseIdentification, PhaseMatch, ReferencePhase
from .provider import ReferenceProvider

# hull フィルタ既定閾値。FR-103: 100 meV/atom = 0.1 eV/atom。
_DEFAULT_HULL_CUTOFF_EV = 0.1


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
) -> PhaseIdentification:
    """未知パターン + 元素一覧から候補相を同定する (FR-110/117)。🔵

    【処理フロー】: 観測ピーク検出 → 供給元から候補相取得 → 元素系 + hull フィルタ →
      候補ごとに ``match_score`` → score 降順 (同点 phase_id 昇順) にランキング →
      全生存候補の説明力から未知相レポートを構築。``max_results`` は表示件数のみ絞り、
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

    Returns:
        ``PhaseIdentification`` (ランキング済みマッチ + 未知相レポート + 観測ピーク)。

    Raises:
        ValueError: ``elements`` が空のとき。
    """
    if len(elements) == 0:
        raise ValueError("elements は非空の元素記号列である必要があります (相同定の対象元素系)。")

    # 【観測ピーク検出】: 局所極大 + 高さ閾値。全ゼロ等は空タプルへ縮退 (EDGE-003) 🔵
    observed = find_peaks(two_theta, intensity, min_height_frac=min_peak_height_frac)

    # 【候補取得】: 供給元へ元素一覧をそのまま渡す (クエリ意図を保存) 🔵
    candidates = provider.fetch(elements)

    # 【前処理フィルタ】: 元素系部分集合 + hull を冪等に適用する 🔵 FR-103
    survivors = filter_references(candidates, elements, hull_cutoff_ev=hull_cutoff_ev)

    # 【マッチング】: 生存候補ごとに一致率 + 被覆率スコアを求める 🔵 FR-111
    match_results: list[MatchResult] = []
    matches: list[PhaseMatch] = []
    for i, phase in enumerate(survivors):
        result = match_score(phase.peaks, observed, tol_deg=match_tol_deg, candidate_index=i)
        match_results.append(result)
        matches.append(
            PhaseMatch(
                reference=phase,
                score=result.score,
                matched_observed=result.matched_observed,
                extra_calculated=result.unmatched_candidate,
            )
        )

    # 【決定論ランキング】: score 降順・同点は phase_id 昇順で安定化 🔵 NFR-102
    matches.sort(key=lambda m: (-m.score, m.reference.phase_id))

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
