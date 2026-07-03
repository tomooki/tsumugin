"""動的枝刈り閾値 (FR-112 / REQ-101)。

候補相のマッチングスコア列から、スコア降順ソート列の累積分布の変曲点 (二階差分の
絶対値が最大となる点 = 最大曲率) に基づく枝刈り閾値を算出する純関数を提供する。
numpy のみで実装し (scipy・GSAS-II 非依存)、ソートは関数内で行い入力順に依存しない
(NFR-102 / REQ-403 決定論)。ドメイン的縮退 (候補不足・点数不足・全同値) は例外化せず
``float("-inf")`` (全展開) に一元化する (EDGE-001 / M0 規約)。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

# 【定数定義】: 二階差分には内部点 (両隣が必要) が最低 1 つ要るため実質 3 点が下限 🟡
_MIN_POINTS_FOR_SECOND_DIFF = 3


def dynamic_threshold(scores: Sequence[float], *, min_candidates: int = 4) -> float:
    """スコア降順の累積分布の変曲点 (二階差分最大) で枝刈り閾値を返す (FR-112 / REQ-101)。

    【機能概要】: ``scores`` を関数内で降順ソートし、累積和の二階差分
      ``d2[i] = c[i+1] - 2*c[i] + c[i-1]`` の絶対値が最大 (最大曲率 = 変曲点) となる
      内部点位置のスコアを閾値として返す。この値「未満」のスコアの相が枝刈り対象で、
      閾値そのものは展開側に含む (REQ-101 の境界は「未満」)。
    【実装方針】: np.sort / np.cumsum / np.diff / np.argmax によるベクトル化 (peaks.py と
      同じ numpy コア方針)。縮退 (候補不足・点数不足・全同値・平坦分布) は例外でなく
      -inf へ一元化し、タイは np.argmax の先頭一致 (高スコア側) で固定して決定論を守る。
    【テスト対応】: tests/test_pruning.py の TC-N01〜03 / TC-E01〜03 / TC-B01〜05 を通す。
    🔵 信頼性レベル: 契約・縮退値・決定論は interfaces.py / REQ-101/403 に依拠。
      二階差分最大=変曲点の実装式とタイ規則は interview Q8 からの妥当な推測 (🟡)。

    Args:
        scores: 候補相のマッチングスコア列 (順不同、``MatchResult.score`` 群を想定)。
        min_candidates: 枝刈りを有効化する最小候補数 (キーワード専用, 既定 4)。
            候補数がこれ未満なら枝刈りを行わない。

    Returns:
        枝刈り閾値 (素の ``float``)。縮退時は ``float("-inf")``
        (全スコア >= -inf となり全展開を意味する)。NaN・例外は返さない。
    """
    # 【候補不足ガード】: min_candidates 未満は枝刈り無効 (TC-002-03)。二階差分に必要な
    #   3 点未満も IndexError を出さず同じ縮退へ倒す (min_candidates 縮小指定時の保険) 🟡
    n = len(scores)
    if n < max(min_candidates, _MIN_POINTS_FOR_SECOND_DIFF):
        return float("-inf")

    # 【降順ソート (関数内・非破壊)】: 入力順に依存しない決定論を確保する (REQ-403/完了条件4)。
    #   np.sort はコピーを返すため入力 scores は変更されない (NFR-101 非破壊性) 🔵
    ordered = np.sort(np.asarray(scores, dtype=float))[::-1]

    # 【全同値ガード】: 分布が平坦だと二階差分が恒等的にゼロで変曲点が定まらないため、
    #   偽の閾値を返さず全展開へフォールバックする (TC-002-04) 🟡
    if ordered[0] == ordered[-1]:
        return float("-inf")

    # 【累積分布と二階差分】: c = cumsum(降順スコア)、d2[m] = c[m+2] - 2*c[m+1] + c[m]
    #   (内部点 i = m+1 に対応)。降順列では d2 <= 0 のため、絶対値最大 = 最大曲率点 🟡
    cumulative = np.cumsum(ordered)
    curvature = np.abs(np.diff(cumulative, n=2))

    # 【平坦分布フォールバック】: 内部の二階差分が全ゼロ (変曲点なし) は全展開へ倒す 🟡
    if float(curvature.max()) == 0.0:
        return float("-inf")

    # 【変曲点の確定】: 絶対値最大の位置を採用。タイは np.argmax の先頭一致で
    #   高スコア側に固定し、入力順で揺れない一意規則とする (決定論) 🟡
    inflection = int(np.argmax(curvature)) + 1

    # 【閾値返却】: numpy スカラーでなく素の float に変換して返す (契約) 🔵
    return float(ordered[inflection])
