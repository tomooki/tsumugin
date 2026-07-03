"""JSON 配信・直列化のための数値純化ユーティリティ (TASK-0023 / Issue #5)。

【機能概要】: 非有限値 (inf/-inf/NaN) と ``None`` を ``None`` へ、有限値を ``float`` へ写像する
  純関数 ``finite_or_none`` を単一実装として提供する無依存の葉モジュール。
【実装方針】: 標準ライブラリ ``math`` のみに依存し、上位レイヤ (search/webui/store/…) や numpy を
  一切 import しない。全層がこれを下向きに import することで、従来 3 箇所に散在していた
  ``_finite_or_none`` 相当の重複と webui→search の私的横断 import (レイヤ逆依存) を解消する。
【テスト対応】: tests/test_json_util.py (16 件) — 有限値の透過 / 非有限・None → None /
  委譲の検証 (tree/webui/serialization) / 葉モジュールのレイヤ制約。
🔵 信頼性レベル: 要件定義 §2 真理値表 / interfaces.py L24-32 / D-Q9 に直接依拠。
"""

from __future__ import annotations

import math

__all__ = ["finite_or_none"]


def finite_or_none(value: float | None) -> float | None:
    """【機能概要】: JSON 配信用に数値を純化する。非有限 (inf/-inf/NaN) と None は None、
      有限値は float として返す純関数。
    【実装方針】: json.dumps(allow_nan=False) を通すため配信前に非有限を None へ縮退させる
      (EDGE-004: chi2=inf は正常経路だが JSON に inf は存在しないため)。tree のセンチネル
      閾値判定は探索固有契約のため本関数には持ち込まず tree 側に残す (D-Q9)。
    【テスト対応】: TC-J-N01〜N03 (有限透過) / TC-J-E01〜E03 (非有限→None) /
      TC-J-B01〜B05 (None・0.0・極値・純関数性)。
    🔵 信頼性レベル: 要件定義 §2 真理値表 / 既存 3 実装 (tree/webui/serialization) の現行挙動に一致。

    Args:
        value: 純化対象の数値 (float / int / None)。float(value) で変換可能であること。

    Returns:
        value が None または非有限なら None、有限なら float(value)。
    """
    # 【None 受理】: serialization は None を渡しうるため float 変換前に早期 return し
    #   TypeError を防ぐ (現行 store/serialization.py の挙動を保存) 🔵
    if value is None:
        return None
    # 【純化判定】: math.isfinite が False の値 (inf/-inf/NaN) を None へ写像し、
    #   有限値は float へ正規化して返す (0.0 等の falsy 有限値も潰さない) 🔵
    v = float(value)
    return v if math.isfinite(v) else None
