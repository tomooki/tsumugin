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

TASK-0034 では結合出力層 (``combined_csv`` / ``TransitionPoint`` / ``transition_point``) と
ヒステリシス解析層 (``BranchComparison`` / ``split_branches`` / ``branch_differences``) を
追加する (FR-314 / FR-315 / 設計 D9 / D-Q10)。

FR-318 ではクーロメトリー→可動アルカリ量の物理コア (``coulometry``: ``electron_count`` /
``alkali_targets`` / ``MobileSiteSpec`` / ``x_xrd_from_weight_fractions`` /
``coulometric_fractions``) を追加する (電気化学制約付き operando Rietveld)。
"""

from __future__ import annotations

from .cell_phases import (
    CELL_PHASE_PRESETS,
    FixedPhaseSpec,
    fixed_free_suffixes,
)
from .coulometry import (
    F_MAH_PER_MOL,
    AlkaliBudget,
    FrameTarget,
    MobileSiteSpec,
    alkali_targets,
    content_from_occupancies,
    coulometric_fractions,
    electron_count,
    feasibility,
    occupancies_for_content,
    x_xrd_from_weight_fractions,
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
from .hysteresis import (
    BranchComparison,
    branch_differences,
    split_branches,
)
from .output import (
    TransitionPoint,
    combined_csv,
    transition_point,
)
from .segmentation import (
    SegmentationConfig,
    SegmentationResult,
    segment_series,
)

__all__ = [
    "CELL_PHASE_PRESETS",
    "AlkaliBudget",
    "BiologicMprLoader",
    "BranchComparison",
    "DiscriminationConfig",
    "DiscriminationResult",
    "EchemData",
    "EchemLoader",
    "F_MAH_PER_MOL",
    "FixedPhaseSpec",
    "FrameTarget",
    "MobileSiteSpec",
    "SegmentationConfig",
    "SegmentationResult",
    "TransitionPoint",
    "alkali_targets",
    "branch_differences",
    "combined_csv",
    "content_from_occupancies",
    "coulometric_fractions",
    "discriminate_interval",
    "electron_count",
    "feasibility",
    "fixed_free_suffixes",
    "occupancies_for_content",
    "read_echem_csv",
    "segment_series",
    "split_branches",
    "transition_point",
    "x_xrd_from_weight_fractions",
]
