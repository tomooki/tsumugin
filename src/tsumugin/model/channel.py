"""外部チャネル同期のデータモデル (仕様 §4 / REQ-006 ExternalChannel)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

# 【kind 拡張】: 既存 4 値の末尾に echem 用 4 値を追加 (Literal 末尾追加で後方互換 / REQ-007/REQ-404) 🔵
ChannelKind = Literal[
    "temperature",
    "time",
    "pressure",
    "custom",
    "voltage",
    "current",
    "capacity",
    "composition",
]


@dataclass(frozen=True)
class ExternalChannel:
    """外部物理量 (温度/時間等) とフレームの同期写像を保持する値オブジェクト。

    【機能概要】: frame_index → value の同期写像を持ち、任意フレームの外部値を引ける不変値オブジェクト。
    【実装方針】: sync_map は Mapping (dict) を保持し、value_for は dict.get 相当で欠損を None に縮退。
    【テスト対応】: N-03/N-04/E-02/E-03/B-04 を通す。
    🔵 信頼性レベル: 要件定義 2.4 / TC-105-01/02 / interfaces.py L44-54 / EDGE-102 に依拠。
    """

    kind: ChannelKind  # 【チャネル種別】: 位置必須。echem は M3 スコープ外のため含めない 🔵
    sync_map: Mapping[int, float]  # 【同期写像】: 位置必須。frame_index → value 🔵
    label: str | None = None  # 【任意ラベル】: 既定 None (interfaces.py 🟡)

    def value_for(self, frame_index: int) -> float | None:
        """指定フレームの外部値を返す。欠損フレームは None (例外なし)。

        【実装方針】: sync_map.get(frame_index) で欠損を None に縮退し KeyError を送出しない。
        【テスト対応】: EDGE-102 (TC-105-02) の中核。存在フレームは対応値、欠損は None。
        🔵 信頼性レベル: 要件定義 2.4 / EDGE-102 に依拠。
        """
        # 【欠損縮退】: 存在フレームは float 値、未登録フレームは None を返す (上位で軸値 None + 警告扱い) 🔵
        return self.sync_map.get(frame_index)
