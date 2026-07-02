"""Evidence Engine の抽象境界 (仕様 FR-120 / FR-121)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..model import RefinementMetrics


@dataclass(frozen=True)
class EvidenceResult:
    """1 仮説の evidence 値。logz_err は nested 系のみ (M0 では None)。"""

    backend: str
    value: float  # 小さいほど良い (情報量規準の慣習)
    logz_err: float | None = None


@runtime_checkable
class EvidenceBackend(Protocol):
    """evidence 計算バックエンドの構造的インターフェース。"""

    name: str

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        ...
