"""最終選択エンジンのエスカレーション検出 (detect_escalations)。

【機能概要】: SearchResult を非破壊で読み取り、エスカレーション 4 条件を宣言順の tuple で返す純粋関数。
【実装方針】: 副作用ゼロ・冪等 (SearchResult を変更しない・ledger に書かない・乱数を使わない)。
【テスト対応】: tests/test_selection.py の detect_escalations 系 (N-01〜N-06 / B-01〜B-03 / B-05/B-06)。
🔵 信頼性レベル: 要件定義 2.2 / architecture.md D6 (L84-87) / interfaces.py L340-342
"""

from __future__ import annotations

from tsumugin.search.tree import SearchResult

from .review_queue import EscalationReason


def detect_escalations(
    result: SearchResult,
    *,
    staged_escalated: bool = False,
    high_r_threshold: float = 30.0,
) -> tuple[EscalationReason, ...]:
    """【機能概要】: エスカレーションが必要な 4 条件を検出し宣言順のタプルで返す純粋関数。

    【実装方針】: 各条件の真偽を独立に評価し、発火したものだけを EscalationReason 宣言順に並べる。
    処理をブロックせず (例外を投げず) 材料としての tuple を返すのみ (FR-403)。
    【テスト対応】: N-01〜N-06 (単独/空/4 条件同時) / B-01〜B-03 (空 ranked・境界・単一) / B-05/B-06。
    🔵 信頼性レベル: 要件定義 2.2 4 条件 / D6 / NFR-102 決定論

    @param result: 木探索結果。ranked の metrics.rwp / close_competitor と unmatched.unknown_phase_flag を読む。
    @param staged_escalated: 段階的精密化のガード N 連続発動フラグ (呼び出し側供給)。
    @param high_r_threshold: 全高 R 判定の Rwp 閾値 (%)。既定 30.0。
    @returns: 発火した EscalationReason を宣言順に含む tuple。条件なしなら空タプル。
    """
    # 【結果蓄積】: 発火した reason を宣言順に積む (all_high_r → unknown_phase → close_competitor → guard_escalated) 🔵
    reasons: list[EscalationReason] = []

    # 【条件 (a) all_high_r】: ranked が非空かつ全仮説の rwp が閾値を厳密超過するとき発火 🔵
    # 【空ガード】: 空 ranked では all() の真空的 True を避けるため発火させない 🔵 B-01
    # 【None ガード】: metrics is None の仮説は高 R 判定できないため all_high_r を成立させない 🔵
    if result.ranked and all(
        r.hypothesis.metrics is not None and r.hypothesis.metrics.rwp > high_r_threshold
        for r in result.ranked
    ):
        reasons.append("all_high_r")

    # 【条件 (b) unknown_phase】: SearchResult 側の集約済み未知相フラグをそのまま信頼する 🔵
    if result.unmatched.unknown_phase_flag:
        reasons.append("unknown_phase")

    # 【条件 (c) close_competitor】: 1-2 位の僅差競合を 2 位の close_competitor フラグで判定 🔵
    # 【2 位判定の理由】: ranked[0] は rank() 実装上つねに close=True になるため 2 位を見る (B-03) 🔵
    if len(result.ranked) >= 2 and result.ranked[1].close_competitor:
        reasons.append("close_competitor")

    # 【条件 (d) guard_escalated】: ガード N 連続発動を示す bool 引数をそのまま採用 🔵
    if staged_escalated:
        reasons.append("guard_escalated")

    # 【決定論的返却】: 宣言順に積んだ reason をビット同一の tuple にして返す (NFR-102) 🔵
    return tuple(reasons)
