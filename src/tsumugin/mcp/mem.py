"""MEM 実行の M5 委譲境界 (M4 / REQ-101/EDGE-008 / interfaces.py mcp/mem 節)。

MEM バックエンド (M5 / FR-601〜606) は本マイルストーンでは未実装のため、``run_mem_boundary``
は委譲境界としてのみ存在する。既定 (``placeholder=False``) は ``MEMUnavailableError`` を送出し
「M5 で提供予定」を明示する。``placeholder=True`` のときは呼び出し側スキーマ将来互換のための
プレースホルダ dict を返す (D9)。**いずれの経路も状態変更・破壊的 ledger 追記を一切伴わない**
(M5 境界のみ・自動適用なし, NFR-101)。

本モジュールは MCP SDK を一切 import しない (SDK 非依存の実処理層, D7)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..errors import MEMUnavailableError

if TYPE_CHECKING:  # 【循環回避】: 型注釈のみ (実行時 import しない・SDK 非依存維持) 🔵
    from .tools import AnalysisSession

__all__ = ["run_mem_boundary"]


def run_mem_boundary(
    session: "AnalysisSession", *, placeholder: bool = False, **params: object
) -> dict:
    """MEM バックエンド (M5) 未実装の委譲境界。🔵 REQ-101/EDGE-008

    【機能概要】: ``placeholder=False`` (既定) は ``MEMUnavailableError`` を送出、``True`` は
      M5 プレースホルダ dict を返す。いずれも session を読み取らず、状態変更・破壊的 ledger 追記を
      伴わない (M5 境界のみ・自動適用なし)。
    【実装方針】: MEM の実処理は M5 スコープ。本タスクは「明示エラー / 将来互換プレースホルダ」の
      2 経路のみを提供し、破壊的操作を新設しない (NFR-101)。
    【テスト対応】: test_run_mem_default_raises_mem_unavailable /
      test_run_mem_placeholder_returns_dict_without_state_change /
      test_run_mem_default_does_not_mutate_ledger。
    🔵 信頼性レベル: interfaces.py mcp/mem 節 / REQ-101 / EDGE-008 に依拠。

    :param session: 8 ツール共通の facade (本境界では読み取らない)。
    :param placeholder: True でプレースホルダ dict を返す。False (既定) は例外送出。
    :param params: 将来の MEM パラメータ (現状は受理して破棄・スキーマ将来互換)。
    :returns: placeholder=True のとき M5 プレースホルダ dict。
    :raises MEMUnavailableError: placeholder=False (既定) のとき。
    """
    # 【プレースホルダ経路】: スキーマ将来互換のため素の型 dict を返す (状態変更なし) 🔵 D9
    if placeholder:
        return {"status": "not_implemented", "milestone": "M5", "tool": "run_mem"}
    # 【明示エラー経路】: M5 で提供予定を明示送出する (破壊的操作なし) 🔵 REQ-101
    raise MEMUnavailableError(
        "MEM バックエンド (最大エントロピー法) は M5 (FR-601〜606) で提供予定です。"
    )
