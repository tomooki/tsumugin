"""仮説・精密化メトリクスのデータモデル (仕様 §4 Hypothesis)。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .phase import PhaseInstance

HypothesisStatus = Literal["candidate", "refined", "accepted", "rejected", "superseded"]


@dataclass(frozen=True)
class RefinementMetrics:
    """精密化の品質指標。evidence は backend 名 -> 値。"""

    rwp: float
    gof: float
    chi2: float
    n_obs: int
    n_params: int
    evidence: Mapping[str, float] = field(default_factory=dict)
    # 【追加フィールド】: マルチスタート精密化のメタ ({"n","n_basins","n_diverged"})。末尾・既定 None で後方互換 (REQ-006/REQ-404) 🔵
    multistart: Mapping[str, int] | None = None


@dataclass(frozen=True)
class Hypothesis:
    """相組合せ仮説。木探索(M1)ではノードとして分岐する。"""

    id: str
    phases: tuple[PhaseInstance, ...]
    parent_id: str | None = None
    metrics: RefinementMetrics | None = None
    status: HypothesisStatus = "candidate"
    accepted_by: Literal["agent", "human", None] = None
    # 【追加フィールド】: 仮説の有効フレーム区間 [start, end]。末尾・既定 None で後方互換 (REQ-404) 🔵
    frame_range: tuple[int, int] | None = None
