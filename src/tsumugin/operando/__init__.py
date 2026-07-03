"""operando/ パッケージ (operando 電池モードの入力・解析層)。

TASK-0029 では電気化学 (充放電) CSV を読み込み、電圧/電流/容量および容量→組成 x の
線形換算値を、粉末回折フレームに同期した ``ExternalChannel`` 群として供給する入力層
(``EchemData`` / ``read_echem_csv``) と、機種別バイナリ用ローダの交換境界 Protocol
(``EchemLoader`` / ``BiologicMprLoader``) を提供する。

TASK-0030 ではセル固定相プリセット層 (``FixedPhaseSpec`` / ``CELL_PHASE_PRESETS`` /
``fixed_free_suffixes``) を追加する (FR-312 / REQ-009)。

TASK-0032 では固溶体 vs 二相判別層 (``DiscriminationConfig`` / ``DiscriminationResult`` /
``discriminate_interval``) を追加する (FR-313 / 設計 D4)。

TASK-0033 では IC 区間自動分割層 (``SegmentationConfig`` / ``SegmentationResult`` /
``segment_series``) を追加する (FR-316 / 設計 D5/D6)。
"""

from __future__ import annotations

from .cell_phases import (
    CELL_PHASE_PRESETS,
    FixedPhaseSpec,
    fixed_free_suffixes,
)
from .discrimination import (
    DiscriminationConfig,
    DiscriminationResult,
    discriminate_interval,
)
from .echem import (
    BiologicMprLoader,
    EchemData,
    EchemLoader,
    read_echem_csv,
)
from .segmentation import (
    SegmentationConfig,
    SegmentationResult,
    segment_series,
)

__all__ = [
    "CELL_PHASE_PRESETS",
    "BiologicMprLoader",
    "DiscriminationConfig",
    "DiscriminationResult",
    "EchemData",
    "EchemLoader",
    "FixedPhaseSpec",
    "SegmentationConfig",
    "SegmentationResult",
    "discriminate_interval",
    "fixed_free_suffixes",
    "read_echem_csv",
    "segment_series",
]
