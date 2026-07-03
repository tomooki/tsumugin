"""精密化戦略エンジン (段階解放 + ガードレール)。"""

from __future__ import annotations

from .guardrails import GuardConfig, GuardKind, GuardViolation, check_guards
from .staged import (
    DEFAULT_STAGE_TEMPLATE,
    RefinementReport,
    Stage,
    StageOutcome,
    StagedRefinementEngine,
)

__all__ = [
    "DEFAULT_STAGE_TEMPLATE",
    "GuardConfig",
    "GuardKind",
    "GuardViolation",
    "RefinementReport",
    "Stage",
    "StageOutcome",
    "StagedRefinementEngine",
    "check_guards",
]
