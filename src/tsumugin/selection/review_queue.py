"""ReviewQueue + ReviewItem (M2 エスカレーション通知の追記型キュー)。

【機能概要】: detect_escalations が検出したエスカレーションを人間の後追い確認のために蓄積する。
【実装方針】: Ledger/Snapshot と同じ P2 構造的非破壊性 (削除 API なし・resolve は状態遷移) に準拠する。
【テスト対応】: tests/test_selection.py の ReviewQueue/ReviewItem 系テスト (N-07〜N-10 / E-01〜E-03 / B-04)。
🔵 信頼性レベル: 要件定義 2.3/2.4 / interfaces.py L299-325 / design-interview.md D-Q7
"""

from __future__ import annotations

import dataclasses
from typing import Literal

from tsumugin.store.ledger import Ledger

# 【定数定義】: M2 で利用可能なエスカレーション 4 条件のみを表す型エイリアス (吸収補正は M3 スコープ外) 🔵
# 【宣言順の意味】: detect_escalations の返り値順序はこの宣言順に固定される (NFR-102 決定論)
EscalationReason = Literal[
    "all_high_r", "unknown_phase", "close_competitor", "guard_escalated"
]


@dataclasses.dataclass(frozen=True)
class ReviewItem:
    """【機能概要】: Review Queue に積まれるエスカレーション 1 件の値オブジェクト。

    【実装方針】: frozen dataclass にして生成・等価比較可能・再代入不可 (状態変更は replace 経由)。
    【テスト対応】: N-07 (add 生成) / N-08 (resolve) / E-01 (frozen 再代入で FrozenInstanceError)。
    🔵 信頼性レベル: 要件定義 2.3 / interfaces.py L304-313
    """

    item_id: str  # 【追加順連番】: "rq-0000" 形式の一意 ID 🔵
    reason: EscalationReason  # 【エスカレーション理由】: 4 条件のいずれか 🔵
    hypothesis_id: str | None  # 【関連仮説 ID】: 無ければ None 🔵
    frame_index: int | None  # 【関連フレーム index】: 単一パターン解析等では None 🔵
    detail: str  # 【補足説明】: 自然言語 (既定は空文字) 🔵
    resolved: bool = False  # 【解決済みか】: resolve は resolved=True への状態遷移で表現 🔵 P2


class ReviewQueue:
    """【機能概要】: エスカレーションを蓄積する追記型キュー。削除 API を持たない。

    【実装方針】: 内部 list へ append し items/unresolved は不変タプルで公開 (P2 構造的非破壊性)。
    ledger 注入時は add/resolve を canonical JSON 可能な素の型で ledger にも記録する (D-Q7)。
    【テスト対応】: N-07〜N-10 / E-02 (削除 API 不在) / E-03 (未知 item_id) / B-04 (連番決定論)。
    🔵 信頼性レベル: 要件定義 2.4 / interfaces.py L316-325 / design-interview.md D-Q7
    """

    def __init__(self, ledger: Ledger | None = None) -> None:
        # 【状態初期化】: 追記専用の内部列と任意注入 ledger を保持する 🔵
        # 【注入設計】: ledger=None でもキュー単体として機能する (依存性注入パターン)
        self._items: list[ReviewItem] = []
        self._ledger = ledger

    def add(
        self,
        reason: EscalationReason,
        *,
        hypothesis_id: str | None = None,
        frame_index: int | None = None,
        detail: str = "",
    ) -> ReviewItem:
        """【機能概要】: エスカレーションを 1 件 Queue へ追記し生成した ReviewItem を返す。

        【実装方針】: 追加順連番 "rq-{n:04d}" を採番し resolved=False の ReviewItem を生成して追記する。
        【テスト対応】: N-07 (全フィールド保持) / N-10 (review_add 記録) / B-04 (連番決定論)。
        🔵 信頼性レベル: 要件定義 2.4 add / interfaces.py L320
        """
        # 【連番採番】: 現在の件数を 4 桁ゼロ埋めして決定論的な item_id を作る (乱数不使用) 🔵
        item_id = f"rq-{len(self._items):04d}"
        # 【ReviewItem 生成】: resolved 既定 False で全フィールドを保持する 🔵
        item = ReviewItem(
            item_id=item_id,
            reason=reason,
            hypothesis_id=hypothesis_id,
            frame_index=frame_index,
            detail=detail,
        )
        # 【内部列へ追記】: 追記のみ (削除・上書きなし) で P2 を担保する 🔵
        self._items.append(item)
        # 【ledger 連携】: 注入時のみ review_add を追記 (payload は素の型に限る) 🟡 D-Q7
        if self._ledger is not None:
            self._ledger.append(
                "review_add",
                {
                    "item_id": item_id,
                    "reason": reason,
                    "hypothesis_id": hypothesis_id,
                    "frame_index": frame_index,
                    "detail": detail,
                },
            )
        return item

    def resolve(self, item_id: str, *, note: str = "") -> ReviewItem:
        """【機能概要】: 指定 item_id を resolved=True の新インスタンスへ差し替える (件数不変)。

        【実装方針】: dataclasses.replace で新 ReviewItem を作り同 index へ差し替える (削除しない)。
        存在しない item_id は誤操作防御として KeyError を送出し ledger にも記録しない。
        【テスト対応】: N-08 (件数不変で resolved=True) / N-10 (review_resolve 記録) / E-03 (未知 id 例外)。
        🔵 信頼性レベル: 要件定義 2.4 resolve / interfaces.py L321
        """
        # 【対象探索】: item_id に一致する index を線形探索する 🔵
        for index, current in enumerate(self._items):
            if current.item_id == item_id:
                # 【状態遷移】: 削除でなく resolved=True の新インスタンスへ差し替える (追記表現) 🔵 P2
                resolved_item = dataclasses.replace(current, resolved=True)
                self._items[index] = resolved_item
                # 【ledger 連携】: 注入時のみ review_resolve を追記する 🟡 D-Q7
                if self._ledger is not None:
                    self._ledger.append(
                        "review_resolve",
                        {"item_id": item_id, "note": note},
                    )
                return resolved_item
        # 【防御的例外】: 未知 item_id は「解決した」と誤認させないため例外にする (ledger 非記録) 🟡
        raise KeyError(item_id)

    @property
    def items(self) -> tuple[ReviewItem, ...]:
        """【機能概要】: これまで add された全 ReviewItem の不変タプル (resolve 済み含む・減らない)。

        【実装方針】: 内部 list を tuple 化して読み取り専用ビューを返す 🔵
        🔵 信頼性レベル: 要件定義 2.4 items / interfaces.py L323
        """
        return tuple(self._items)

    @property
    def unresolved(self) -> tuple[ReviewItem, ...]:
        """【機能概要】: items のうち resolved is False のみを絞り込んだ派生ビュー。

        【実装方針】: items から未解決のみをフィルタした不変タプルを返す 🔵
        🔵 信頼性レベル: 要件定義 2.4 unresolved / interfaces.py L325
        """
        return tuple(item for item in self._items if item.resolved is False)
