"""nested evidence サブパッケージ (M5 / REQ-004〜017/101/301)。

TASK-0049 の型基盤: 事前分布 ``PriorSpec`` (逆 CDF 変換) と、既存 ``EvidenceBackend`` を非破壊で
拡張する ``EvidenceProblem`` + ``ProblemAwareEvidenceBackend`` (D1)、および restraint からの事前
分布自動構成 (``RestraintSpec`` / ``build_prior_from_restraints``) を提供する。後続の laplace/
sampler/arbitration が本型基盤に依存する。トップレベル ``tsumugin`` __all__ への統合は TASK-0058。

コア依存は numpy のみ (逆 CDF は numpy で実装し scipy に依存しない)。
"""

from __future__ import annotations

from .base import EvidenceProblem, PriorSpec, ProblemAwareEvidenceBackend
from .laplace import LaplaceBackend
from .prior import RestraintSpec, build_prior_from_restraints
from .sampler import NestedBackend, NestedConfig, NestedOutcome

__all__ = [
    "EvidenceProblem",
    "LaplaceBackend",
    "NestedBackend",
    "NestedConfig",
    "NestedOutcome",
    "PriorSpec",
    "ProblemAwareEvidenceBackend",
    "RestraintSpec",
    "build_prior_from_restraints",
]
