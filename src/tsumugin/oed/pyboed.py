"""PyBOED 獲得関数接続境界 (OED / REQ-036/105/EDGE-011)。

PyBOED (``pyboed``) を用いた高度な獲得関数ベースの情報利得評価へ提案群を渡す接続境界。
v1 スコープでは提案生成 (``oed/proposal.py`` の ``propose_measurements``) は本境界に**非依存**で
動作し、本モジュールは PyBOED を**遅延 import** する薄いアダプタに留める。

【遅延 import 契約 (REQ-036/403)】: ``import tsumugin.oed.pyboed`` 自体はコア (numpy) のみで成功し、
  pyboed を引き込まない。pyboed を要求するのは ``acquire`` の**呼び出し時点**のみで、未導入なら
  ``OEDUnavailableError`` を送出して extra ``oed`` の導入手順を案内する
  (``NestedUnavailableError`` / ``MCPUnavailableError`` と対称の「available + 専用例外」パターン)。
"""

from __future__ import annotations

import importlib.util
from typing import Mapping, Sequence

from ..errors import OEDUnavailableError
from .proposal import OEDProposal

__all__ = ["acquire"]


def acquire(
    proposals: Sequence[OEDProposal], *, config: Mapping[str, object] | None = None
) -> tuple[OEDProposal, ...]:
    """PyBOED 獲得関数で提案を再評価する接続境界 (v1 は提案生成のみ)。🔵 REQ-036/105/EDGE-011

    【遅延 import (REQ-036/403)】: ``pyboed`` は本関数実行時にのみ import する。未導入なら
      ``OEDUnavailableError`` を送出する。``propose_measurements`` (v1 スコープ) は本境界に依存せず
      動作する (提案生成は外部依存なし, REQ-105)。

    Args:
        proposals: ``propose_measurements`` が生成した提案群 (獲得関数で再順位付けする対象)。
        config: PyBOED 獲得関数の設定 (取得関数種別・予算等)。v1 では未使用。

    Returns:
        PyBOED で再評価した提案 tuple。

    Raises:
        OEDUnavailableError: optional extra ``oed`` (pyboed) が未導入のとき。
    """
    # 【未導入検出 (REQ-036/EDGE-011)】: pyboed の有無を find_spec で確認し、無ければ専用例外へ縮退する 🔵
    if importlib.util.find_spec("pyboed") is None:
        raise OEDUnavailableError(
            "PyBOED (pyboed) が未導入です。獲得関数ベースの情報利得評価には "
            "`uv sync --extra oed` で pyboed を導入してください。v1 の提案生成 "
            "(propose_measurements) は本境界に依存せず動作します。"
        )

    # 【遅延 import (REQ-036)】: ここで初めて pyboed を import する (トップレベルでは引き込まない) 🔵
    import pyboed  # type: ignore  # noqa: F401, PLC0415

    # 【v1 スコープ】: 実獲得関数連携は将来拡張。導入済み環境では提案をそのまま (決定論順のまま) 返す。
    return tuple(proposals)
