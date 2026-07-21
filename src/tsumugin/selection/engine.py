"""最終選択エンジン: エスカレーション検出 (detect_escalations) + 裁定 (FinalSelectionEngine)。

【機能概要】: SearchResult を非破壊で読み取り、エスカレーション 4 条件を検出する純粋関数と、
agent/human 2 モードで最終的な仮説採択 (裁定) を行う FinalSelectionEngine を提供する。
【実装方針】: detect_escalations は副作用ゼロ・冪等。FinalSelectionEngine は入力 SearchResult を
一切変更せず、accepted 化を dataclasses.replace の新 Hypothesis で表現し ledger に根拠付きで記録する。
【テスト対応】: tests/test_selection.py の detect_escalations 系 + Decision/FinalSelectionEngine 系。
🔵 信頼性レベル: 要件定義 2.1/2.2 / architecture.md D5/D6 / interfaces.py L328-362
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.model import Hypothesis
from tsumugin.search.tree import SearchResult
from tsumugin.store.ledger import Ledger

from .review_queue import EscalationReason, ReviewQueue


def detect_escalations(
    result: SearchResult,
    *,
    staged_escalated: bool | None = None,
    high_r_threshold: float = 30.0,
) -> tuple[EscalationReason, ...]:
    """【機能概要】: エスカレーションが必要な 4 条件を検出し宣言順のタプルで返す純粋関数。

    【実装方針】: 各条件の真偽を独立に評価し、発火したものだけを EscalationReason 宣言順に並べる。
    処理をブロックせず (例外を投げず) 材料としての tuple を返すのみ (FR-403)。
    【テスト対応】: N-01〜N-06 (単独/空/4 条件同時) / B-01〜B-03 (空 ranked・境界・単一) / B-05/B-06。
    🔵 信頼性レベル: 要件定義 2.2 4 条件 / D6 / NFR-102 決定論

    @param result: 木探索結果。ranked の metrics.rwp / close_competitor と unmatched.unknown_phase_flag を読む。
    @param staged_escalated: 段階的精密化のガード N 連続発動フラグ。``None`` (既定) なら
        ``result.final_reports`` の ``RefinementReport.escalated`` から自動導出する (FR-212)。
        ``True``/``False`` の明示指定はその値を優先する。
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

    # 【条件 (d) guard_escalated】: ガード N 連続発動 (FR-212) 🔵
    # 【自動導出】: 明示指定が無ければ result.final_reports から拾う。StagedRefinementEngine の
    #   3 連続失敗フラグは SearchResult に既に届いているのに、本モジュール内の呼び出し側
    #   (`FinalSelectionEngine.decide` / `.accept`) がどちらも staged_escalated を渡しておらず、
    #   ledger に載るだけで裁定に効いていなかった (仕様 FR-212「3 回失敗で Triage へ」の実質未発火)。
    # 【明示優先】: True/False の明示指定は導出より優先する (既存呼び出しの後方互換)。
    if staged_escalated is None:
        staged_escalated = any(
            bool(report.escalated) for report in result.final_reports.values()
        )
    if staged_escalated:
        reasons.append("guard_escalated")

    # 【決定論的返却】: 宣言順に積んだ reason をビット同一の tuple にして返す (NFR-102) 🔵
    return tuple(reasons)


@dataclasses.dataclass(frozen=True)
class Decision:
    """【機能概要】: 1 回の裁定結果を表す不変の値オブジェクト。

    【実装方針】: frozen dataclass にして生成後の再代入を禁止し、決定論的に組んだ根拠 (rationale) を
    自然言語 + 定量値で保持する。accepted は自動 accept 成立時のみ非 None の新 Hypothesis。
    【テスト対応】: N-01〜N-07 (各フィールド) / B-04 (rationale 決定論) / E-04 (frozen 再代入で例外)。
    🔵 信頼性レベル: 要件定義 2.1 / interfaces.py L328-337
    """

    mode: Literal["agent", "human"]  # 【裁定モード】: 裁定を行ったモード 🔵
    accepted: Hypothesis | None  # 【自動 accept 結果】: 成立時のみ accepted 化した新 Hypothesis 🔵
    provisional_id: str | None  # 【暫定裁定】: agent+エスカレーション時の best.id 🔵
    recommended_id: str | None  # 【推奨仮説 ID】: human / 暫定時の best.id 🔵
    escalations: tuple[EscalationReason, ...]  # 【検出条件】: 空なら無し 🔵
    rationale: str  # 【裁定根拠】: best.id / probability / evidence / close / unknown_phase 🔵


class FinalSelectionEngine:
    """【機能概要】: agent/human 2 モードで木探索結果を最終裁定する最終選択エンジン。

    【実装方針】: 入力 SearchResult を非破壊で読み取り (D5)、accepted 化は dataclasses.replace の
    新 Hypothesis で表現して engine の追記型レジストリ + 注入 ledger に記録する。agent モードは
    Q8 4 条件成立時に自動 accept、条件欠如時は暫定裁定 + Review Queue 通知でブロックしない (REQ-102)。
    human モードは推奨提示のみで accepted 化は明示 accept API 経由に限る (REQ-103)。
    【テスト対応】: N-01〜N-08 / E-01〜E-04 / B-01〜B-05。
    🔵 信頼性レベル: 要件定義 2.2/3/4 / interfaces.py L345-361 / architecture.md D5
    """

    def __init__(
        self,
        *,
        mode: Literal["agent", "human"] = "agent",
        ledger: Ledger | None = None,
        queue: ReviewQueue | None = None,
    ) -> None:
        # 【状態初期化】: 現在モード・注入 ledger・注入 ReviewQueue・追記型 accepted レジストリを保持 🔵
        # 【注入設計】: ledger/queue は None でも動作する (依存性注入パターン) 🔵
        self._mode: Literal["agent", "human"] = mode
        self._ledger = ledger
        self._queue = queue
        self._accepted: dict[str, Hypothesis] = {}

    @property
    def mode(self) -> Literal["agent", "human"]:
        """【機能概要】: 現在の裁定モードを読み取り専用で返す 🔵"""
        return self._mode

    @property
    def review_queue(self) -> ReviewQueue | None:
        """【機能概要】: 注入された ReviewQueue を読み取り専用で返す (Issue #125)。

        【実装方針】: 内部 _queue をそのまま返す (未注入時は None)。② `list_review_queue` /
        `resolve_review_item` が review queue へアクセスする唯一の経路になる (§4.5 到達可能性)。
        🔵 信頼性レベル: Issue #125 — ② が review queue を読む経路
        """
        return self._queue

    def set_mode(self, mode: Literal["agent", "human"]) -> None:
        """【機能概要】: 裁定モードを切替し、切替を ledger に追記する (実行中いつでも切替可能)。

        【実装方針】: mode を更新し、注入 ledger があれば素の型 payload で追記する (REQ-104)。
        【テスト対応】: N-05 (mode 切替が ledger に記録され切替後は human として振る舞う)。
        🔵 信頼性レベル: 要件定義 2.2 set_mode / REQ-104
        """
        # 【モード更新】: 以後の decide の分岐を切替える 🔵
        self._mode = mode
        # 【ledger 記録】: 注入時のみ切替を追記 (payload は canonical JSON 可能な素の型) 🔵
        if self._ledger is not None:
            self._ledger.append("selection_set_mode", {"mode": mode})

    def decide(self, result: SearchResult, *, frame_index: int | None = None) -> Decision:
        """【機能概要】: SearchResult を非破壊で裁定し Decision を返す (例外を投げない)。

        【実装方針】: detect_escalations で条件を集約し、agent は Q8 4 条件成立時のみ自動 accept、
        欠如時は暫定裁定 + Queue 通知。human は best を推奨提示するのみ。入力は 1 バイトも変更しない。
        【テスト対応】: N-01/N-02/N-03/N-05 / E-01 / B-01/B-02/B-03/B-04。
        🔵 信頼性レベル: 要件定義 2.2 decide / 4.1 / D5
        """
        # 【入力読取】: best=ranked[0] (空なら None)・未知相フラグ・エスカレーション条件を非破壊で取得 🔵
        best = result.ranked[0] if result.ranked else None
        unknown = result.unmatched.unknown_phase_flag
        escalations = detect_escalations(result)
        # 【根拠生成】: 決定論的な rationale を組む (乱数・時刻不使用) 🔵
        rationale = self._build_rationale(target=best, unknown=unknown, escalations=escalations)

        # 【human 分岐】: 推奨提示のみで自動 accept しない (REQ-103) 🔵
        if self._mode == "human":
            recommended_id = best.hypothesis.id if best is not None else None
            self._notify_queue(escalations, hypothesis_id=recommended_id, frame_index=frame_index)
            return Decision(
                mode="human",
                accepted=None,
                provisional_id=None,
                recommended_id=recommended_id,
                escalations=escalations,
                rationale=rationale,
            )

        # 【裁定対象ゼロ】: best 不在では accept を試みずエスカレーションのみに落とす (EDGE-004) 🟡
        if best is None:
            self._notify_queue(escalations, hypothesis_id=None, frame_index=frame_index)
            return Decision(
                mode="agent",
                accepted=None,
                provisional_id=None,
                recommended_id=None,
                escalations=escalations,
                rationale=rationale,
            )

        # 【Q8 4 条件 AND 判定】: best 存在 + エスカレーション空 + best 非僅差 + 未知相なし 🔵
        # 【close 直接判定】: detect が空でも best 自身の close_competitor が True なら auto accept を阻む (B-01) 🔵
        can_auto_accept = not escalations and best.close_competitor is False and unknown is False
        if can_auto_accept:
            # 【単一 accept 経路】: agent 自動 accept も accept と同一経路 (by="agent") を通す (REQ-013) 🔵
            accepted_hyp = self._register_accept(best.hypothesis, by="agent", rationale=rationale)
            return Decision(
                mode="agent",
                accepted=accepted_hyp,
                provisional_id=None,
                recommended_id=None,
                escalations=escalations,
                rationale=rationale,
            )

        # 【暫定裁定】: 条件欠如時はブロックせず best を暫定提示し各 reason を Queue へ通知 (REQ-102) 🔵
        self._notify_queue(escalations, hypothesis_id=best.hypothesis.id, frame_index=frame_index)
        return Decision(
            mode="agent",
            accepted=None,
            provisional_id=best.hypothesis.id,
            recommended_id=best.hypothesis.id,
            escalations=escalations,
            rationale=rationale,
        )

    def accept(
        self,
        result: SearchResult,
        hypothesis_id: str,
        *,
        by: Literal["agent", "human"],
        frame_index: int | None = None,
    ) -> Hypothesis:
        """【機能概要】: 指定仮説を明示的に accept し accepted 化した新 Hypothesis を返す。

        【実装方針】: result.hypotheses から対象を引き当て (未知 id は KeyError)、replace で
        status="accepted"/accepted_by=by の新インスタンスを作りレジストリ + ledger に記録する (REQ-013/014)。
        入力 SearchResult は変更しない (D5)。
        【Issue #125】: エスカレーション条件が立っている中で accept するのは、まさに人間が後追いで
        確認すべき事象。``decide()`` を経由しない明示 accept 経路 (② `accept_hypothesis` は
        `selection.accept` を直接呼び `decide` を迂回する) でも Review Queue へ通知することで、
        エスカレーションが ③ から不可視になる DOA を回避する。``frame_index`` は ``decide()`` と
        対称に追加した末尾・既定 None のキーワード引数で、既存呼び出しは無指定のまま動作する。
        【テスト対応】: N-04 (human 明示 accept) / N-08 (追記型 Mapping) / E-02 (未知 id 例外) / B-03 (非破壊)。
        Issue #125: test_accept_notifies_queue_when_escalation_present /
        test_accept_does_not_notify_queue_when_no_escalation / test_accept_notify_uses_frame_index_kwarg /
        test_accept_without_frame_index_is_backward_compatible。
        🔵 信頼性レベル: 要件定義 2.2 accept / REQ-013/014 / D5 / Issue #125
        """
        # 【引き当て】: 存在しない hypothesis_id は誤操作防御として KeyError (レジストリ非汚染) 🟡
        hyp = self._lookup(result, hypothesis_id)
        # 【エスカレーション検出】: rationale とキュー通知の双方で同じ検出結果を使い回す (整合性) 🔵
        escalations = detect_escalations(result)
        # 【根拠生成】: 対象仮説の ranked 情報から決定論的 rationale を組む 🔵
        target = next((r for r in result.ranked if r.hypothesis.id == hypothesis_id), None)
        rationale = self._build_rationale(
            target=target,
            unknown=result.unmatched.unknown_phase_flag,
            escalations=escalations,
        )
        # 【Queue 通知 (Issue #125)】: 検出条件が空なら _notify_queue は何もしない (ループ 0 回) 🔵
        self._notify_queue(escalations, hypothesis_id=hypothesis_id, frame_index=frame_index)
        return self._register_accept(hyp, by=by, rationale=rationale)

    def revert(self, hypothesis_id: str, *, note: str = "") -> Hypothesis:
        """【機能概要】: accept 済み仮説を superseded 化した新 Hypothesis を返す (削除しない)。

        【実装方針】: レジストリの現行仮説を replace で status="superseded" へ遷移させ、旧 accept 履歴を
        残したまま revert を ledger に追記する (件数を減らさない・REQ-202/P2)。未 accept id は KeyError。
        【テスト対応】: N-06 (superseded 化 + 履歴保持) / E-03 (未 accept id 例外) / B-05 (件数不減)。
        🔵 信頼性レベル: 要件定義 2.2 revert / 4.2 / REQ-202
        """
        # 【引き当て】: レジストリに無い仮説の差し戻しは拒否する (履歴の一貫性) 🟡
        current = self._accepted.get(hypothesis_id)
        if current is None:
            raise KeyError(hypothesis_id)
        # 【状態遷移】: 削除でなく superseded への遷移で表現する (P2 追記型) 🔵
        superseded = dataclasses.replace(current, status="superseded")
        self._accepted[hypothesis_id] = superseded
        # 【履歴追記】: revert 操作を ledger に追記 (旧 accept エントリは残り件数は減らない) 🔵
        if self._ledger is not None:
            self._ledger.append(
                "selection_revert",
                {"hypothesis_id": hypothesis_id, "note": note, "status": "superseded"},
            )
        return superseded

    @property
    def accepted(self) -> Mapping[str, Hypothesis]:
        """【機能概要】: 裁定レジストリを読み取り専用 Mapping で公開する (追記のみ・削除 API なし)。

        【実装方針】: 内部 dict を MappingProxyType で包み書き換え不可のビューを返す (P2) 🔵
        🔵 信頼性レベル: 要件定義 2.2 accepted / REQ-013 / P2
        """
        return MappingProxyType(self._accepted)

    # ------------------------------------------------------------------
    # 内部ヘルパ (実装コード内モック不使用・実ロジックのみ)
    # ------------------------------------------------------------------

    def _lookup(self, result: SearchResult, hypothesis_id: str) -> Hypothesis:
        # 【防御的引き当て】: result.hypotheses に無い id は KeyError にして誤採択を防ぐ 🟡
        if hypothesis_id not in result.hypotheses:
            raise KeyError(hypothesis_id)
        return result.hypotheses[hypothesis_id]

    def _register_accept(
        self, hyp: Hypothesis, *, by: Literal["agent", "human"], rationale: str
    ) -> Hypothesis:
        # 【非破壊 accept】: replace で新 Hypothesis を生成 (入力を変更しない・D5) 🔵
        accepted_hyp = dataclasses.replace(hyp, status="accepted", accepted_by=by)
        # 【レジストリ追記】: id をキーに accepted 仮説を登録する 🔵
        self._accepted[hyp.id] = accepted_hyp
        # 【根拠付き記録】: 注入時のみ accept を素の型 payload で ledger に記録 (REQ-014) 🔵
        if self._ledger is not None:
            self._ledger.append(
                "selection_accept",
                {
                    "hypothesis_id": hyp.id,
                    "by": by,
                    "rationale": rationale,
                    "status": "accepted",
                },
            )
        return accepted_hyp

    def _notify_queue(
        self,
        escalations: tuple[EscalationReason, ...],
        *,
        hypothesis_id: str | None,
        frame_index: int | None,
    ) -> None:
        # 【Queue 通知】: 注入時のみ検出した各 reason を Review Queue へ追記する (ブロックしない) 🔵
        if self._queue is None:
            return
        for reason in escalations:
            self._queue.add(reason, hypothesis_id=hypothesis_id, frame_index=frame_index)

    def _build_rationale(
        self,
        *,
        target: RankedHypothesis | None,
        unknown: bool,
        escalations: tuple[EscalationReason, ...],
    ) -> str:
        # 【決定論的根拠生成】: 乱数・時刻を使わず固定順で best.id/確率/evidence/close/未知相を並べる (NFR-102) 🔵
        esc = ",".join(escalations) if escalations else "none"
        if target is None:
            return f"no ranked hypotheses; unknown_phase={unknown}; escalations=[{esc}]"
        hyp = target.hypothesis
        return (
            f"best={hyp.id}; probability={target.probability!r}; "
            f"evidence={target.evidence.value!r}; close_competitor={target.close_competitor}; "
            f"unknown_phase={unknown}; escalations=[{esc}]"
        )
