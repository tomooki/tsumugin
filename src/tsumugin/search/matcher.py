"""候補相のマッチングスコアと未マッチピーク集約 (FR-111 / FR-117)。

1 候補相のシミュレートピーク列と観測ピーク列を突き合わせ、位置一致に基づく
マッチングスコア ``MatchResult`` を計算する (``match_score``, FR-111)。加えて複数候補の
マッチ結果を集約し、どの仮説相でも説明できない未マッチ観測ピーク・観測に現れない
extra 計算ピーク・未知相フラグを ``UnmatchedPeakReport`` に構造化する (``unmatched_peaks``,
FR-117 / REQ-005)。numpy にも依存しないプレーンな純関数 (scipy・GSAS-II 非依存) で、
乱数を使わず同一入力に同一出力を返す (NFR-102 決定論)。空入力・全未マッチ等は例外化せず
``score=0.0`` / 空タプルに縮退する (EDGE-003 / M0 規約)。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .peaks import Peak


@dataclass(frozen=True)
class MatchResult:
    """1 候補相のマッチング結果。FR-111。🔵"""

    candidate_index: int  # 入力で渡された候補相の index 🔵
    score: float  # [0,1]。候補ピーク一致率と観測強度被覆率の等重み平均 🟡
    matched_observed: tuple[int, ...]  # マッチした観測ピーク index (昇順) 🔵 FR-117 用
    unmatched_candidate: tuple[float, ...]  # 観測に無い計算ピーク位置 (extra, 昇順) 🔵 FR-117


def match_score(
    candidate_peaks: Sequence[Peak],
    observed_peaks: Sequence[Peak],
    *,
    tol_deg: float = 0.15,
    candidate_index: int = 0,
) -> MatchResult:
    """1 候補相のマッチングスコアを計算する (FR-111)。

    【機能概要】: 候補ピークを位置昇順に走査し、各候補について tol_deg 以内 (閉区間) で
      未使用かつ最近傍の観測ピークを 1 本だけ確保する (1:1 貪欲一致)。一致率と観測強度
      被覆率の等重み平均をスコアとし、相手の無い候補位置を extra として返す。
    【実装方針】: 「候補 1 本 ⇔ 観測 1 本」の貪欲確保でマッチ本数を入力順に依存させない。
      観測を昇順走査順に評価し最小差を採るため、決定論 (NFR-102) を満たす。🟡
    【テスト対応】: test_matched_observed_returns_sorted_valid_indices /
      test_score_matches_equal_weight_formula / test_greedy_one_to_one_no_duplicate_match /
      test_tol_deg_boundary_* / test_zero_* を通す。
    🔵 信頼性レベル: 構造・契約・縮退挙動は interfaces.py / 要件定義に依拠。
      等重み配分・閉区間・貪欲規則は要件 §7 で確定した妥当な推測 (🟡)。

    Args:
        candidate_peaks: 候補相のシミュレートピーク列。位置は 2θ (度)。
        observed_peaks: 観測ピーク列 (``find_peaks`` 出力)。``position`` 昇順を想定。
        tol_deg: 位置一致許容幅 (度, キーワード専用, 既定 0.15)。``|Δ2θ| <= tol_deg`` を一致とする。
        candidate_index: 呼び出し側が採番する候補 index (キーワード専用, 既定 0)。

    Returns:
        ``MatchResult``。空入力等は ``score=0.0`` / 空タプルへ縮退し例外は投げない。
    """
    # 【一致許容の絶対値化】: 負の tol は無意味なため絶対値で扱い境界判定を安定させる 🟡
    tol = abs(float(tol_deg))

    # 【観測の使用済み管理】: 1 観測ピークを高々 1 候補にしか割り当てない (1:1 重複防止) 🟡
    used = [False] * len(observed_peaks)
    matched_obs_indices: list[int] = []  # 【蓄積】: マッチが成立した観測 index を格納
    unmatched_positions: list[float] = []  # 【蓄積】: 相手が無い候補位置 (extra) を格納

    # 【走査順の固定】: 候補を位置昇順で走査し、順序依存を排除して決定論を確保する (NFR-102) 🟡
    order = sorted(range(len(candidate_peaks)), key=lambda k: candidate_peaks[k].position)
    for k in order:
        cand_pos = float(candidate_peaks[k].position)

        # 【最近傍探索】: tol_deg 以内 (閉区間) で未使用の観測のうち最小差の 1 本を選ぶ 🟡
        # 【探索状態】: best_j=-1 は「未発見」を表す番兵、best_diff=inf は最小差の初期しきい値。
        #   inf を起点にすることで初回の有効差が必ず更新対象となり、None 特例分岐を排除する 🟡
        best_j = -1
        best_diff = float("inf")
        for j, obs in enumerate(observed_peaks):
            if used[j]:
                continue  # 【重複回避】: 既に他候補が確保した観測は対象外
            diff = abs(cand_pos - float(obs.position))
            # 【最小差の更新】: 閉区間内 (diff<=tol) かつ現状より真に小さい差のみ採用する。
            #   同差 (タイ) では < により先着 (より小さい観測 index) を保持し決定論を守る 🟡
            if diff <= tol and diff < best_diff:
                best_diff = diff
                best_j = j

        if best_j >= 0:
            # 【マッチ確定】: 観測を使用済みにし、マッチした観測 index を記録
            used[best_j] = True
            matched_obs_indices.append(best_j)
        else:
            # 【extra 確定】: 観測相手の無い候補位置を extra として記録
            unmatched_positions.append(cand_pos)

    # 【一致率】: マッチした候補本数 / 候補総数。候補ゼロは分母 0 のため 0.0 に縮退 (EDGE) 🟡
    n_candidate = len(candidate_peaks)
    match_rate = len(matched_obs_indices) / n_candidate if n_candidate > 0 else 0.0

    # 【観測強度被覆率】: マッチした観測 height 合計 / 全観測 height 合計。観測側 height を使用 🟡
    total_height = sum(float(p.height) for p in observed_peaks)
    matched_height = sum(float(observed_peaks[j].height) for j in matched_obs_indices)
    intensity_coverage = matched_height / total_height if total_height > 0.0 else 0.0

    # 【スコア合成】: 一致率と被覆率の等重み平均。両項 [0,1] のため score も [0,1] に収まる 🟡
    score = 0.5 * match_rate + 0.5 * intensity_coverage

    return MatchResult(
        candidate_index=candidate_index,
        score=score,
        matched_observed=tuple(sorted(matched_obs_indices)),  # 【昇順】: 観測 index を昇順で返す 🔵
        unmatched_candidate=tuple(sorted(unmatched_positions)),  # 【昇順】: extra 位置を昇順で返す 🔵
    )


@dataclass(frozen=True)
class UnmatchedPeakReport:
    """未マッチピークの構造化出力。FR-117 (REQ-005)。🔵"""

    unmatched_observed: tuple[Peak, ...]  # どの仮説相でも説明できない観測ピーク (位置昇順) 🔵
    extra_calculated: tuple[float, ...]  # 観測に現れない計算ピーク位置 (昇順・重複排除) 🔵
    unknown_phase_flag: bool  # 未マッチ非空 or 全仮説高 R で True 🔵 FR-117/REQ-106


def unmatched_peaks(
    match_results: Sequence[MatchResult],
    observed_peaks: Sequence[Peak],
    *,
    high_r_flag: bool = False,
) -> UnmatchedPeakReport:
    """複数候補のマッチ結果を集約し未マッチ観測・extra・未知相フラグを構造化する (FR-117)。

    【機能概要】: 全 ``MatchResult`` の ``matched_observed`` の和集合を「説明済み観測」とし、
      それ以外の観測ピークを位置・強度を保持した ``Peak`` 実体で未マッチとして復元する。
      各 ``unmatched_candidate`` を昇順・重複排除で集約し extra とする。未マッチ観測が非空、
      または ``high_r_flag=True`` のとき未知相フラグを立てる。
    【実装方針】: 集合演算で説明済み index を求め、観測を位置昇順で並べて復元する。空入力でも
      例外化せず空タプル / フラグ縮退に落とす (EDGE-003)。🔵
    【テスト対応】: test_unmatched_peaks_reports_unknown_phase / _complete_explanation /
      test_high_r_flag_forces_unknown_phase / test_flat_pattern_empty_observed /
      test_extra_calculated_aggregates_sorted_unique を通す。
    🔵 信頼性レベル: 契約・縮退・フラグ条件は interfaces.py / 要件 §2.2・§7#7 に直接依拠。

    Args:
        match_results: 各候補相の ``match_score`` 結果列。
        observed_peaks: 元の観測ピーク列 (未マッチ観測を ``Peak`` 実体で復元するために必要)。
        high_r_flag: 全仮説高 R のとき True (キーワード専用, 既定 False, REQ-106)。

    Returns:
        ``UnmatchedPeakReport``。空入力は空タプル / ``high_r_flag`` に従うフラグへ縮退する。
    """
    # 【候補結果の一括集約】: match_results を 1 度だけ走査し、説明済み観測 index の和集合
    #   (explained) と extra 計算ピーク位置の和集合 (extra_positions) を同時に構築する。
    #   同一列への 2 度の走査を 1 パスへ統合し重複を除去する (DRY) 🔵
    explained: set[int] = set()
    extra_positions: set[float] = set()
    for result in match_results:
        explained.update(result.matched_observed)
        extra_positions.update(result.unmatched_candidate)

    # 【未マッチ観測の復元】: 説明されない観測を Peak 実体のまま位置昇順で抽出する 🔵
    unmatched_observed = tuple(
        sorted(
            (peak for index, peak in enumerate(observed_peaks) if index not in explained),
            key=lambda peak: peak.position,
        )
    )

    # 【extra の集約】: 集約済み位置集合を昇順・重複排除で確定する 🔵
    extra_calculated = tuple(sorted(extra_positions))

    # 【未知相フラグ】: 未マッチ観測が非空、または high_r_flag=True で True を立てる 🔵
    unknown_phase_flag = bool(unmatched_observed) or bool(high_r_flag)

    return UnmatchedPeakReport(
        unmatched_observed=unmatched_observed,
        extra_calculated=extra_calculated,
        unknown_phase_flag=unknown_phase_flag,
    )
