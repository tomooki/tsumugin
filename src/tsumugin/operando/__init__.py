"""operando/ パッケージ (operando 電池モードの入力・解析層)。

TASK-0029 では電気化学 (充放電) CSV を読み込み、電圧/電流/容量および容量→組成 x の
線形換算値を、粉末回折フレームに同期した ``ExternalChannel`` 群として供給する入力層
(``EchemData`` / ``read_echem_csv``) と、機種別バイナリ用ローダの交換境界 Protocol
(``EchemLoader`` / ``BiologicMprLoader``) を提供する。
"""

from __future__ import annotations

from .echem import (
    BiologicMprLoader,
    EchemData,
    EchemLoader,
    read_echem_csv,
)

__all__ = [
    "BiologicMprLoader",
    "EchemData",
    "EchemLoader",
    "read_echem_csv",
]
