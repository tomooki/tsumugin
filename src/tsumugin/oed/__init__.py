"""OED (最適実験計画) サブパッケージ (M5 / REQ-035〜038/105/304 / EDGE-010/011 / D9)。

僅差競合 (close_competitor) を判別するための追加測定を情報利得順に提案する **非破壊** レイヤ。
提案生成 (``propose_measurements`` / ``proposals_to_json``) はコアのみで動作し、仮説を
accepted/rejected 化せず・データを改変せず・ledger 非 None のとき ``oed_proposal`` を追記記録する
のみ (提案のみ・P2)。

PyBOED (``pyboed``) 獲得関数を用いた高度な情報利得評価は ``acquire`` の**遅延 import** 境界に隔離し、
未導入なら ``OEDUnavailableError`` へ縮退する (v1 の提案生成は本境界に非依存)。トップレベル
``tsumugin`` __all__ への統合は TASK-0058。

コア import は numpy 不要 (標準ライブラリのみ) で、``import tsumugin`` に pyboed を持ち込まない
(REQ-403)。
"""

from __future__ import annotations

from .proposal import (
    MeasurementKind,
    OEDProposal,
    propose_measurements,
    proposals_to_json,
)
from .pyboed import acquire

__all__ = [
    "MeasurementKind",
    "OEDProposal",
    "acquire",
    "propose_measurements",
    "proposals_to_json",
]
