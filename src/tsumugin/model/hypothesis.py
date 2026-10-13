"""仮説・精密化メトリクスのデータモデル (仕様 §4 Hypothesis)。"""

from __future__ import annotations

import math
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
    # 【追加フィールド (Issue #64 / FR-123)】: EM 推定したノイズスケール s。既定 None は
    # 「未推定 (現行 chi2 をそのまま使う)」を意味し、evidence/ic.py の BIC/AIC は None のとき
    # 従来式と完全一致する (末尾・既定値付きで非破壊追加, REQ-404)。🔵
    noise_scale: float | None = None
    # 【追加フィールド (fit-then-judge P1-1B, proposal §5)】: 残差の系列相関から推定した実効自由度の比
    # n_eff/n (`evidence.fitstats.effective_dof_ratio`)。既定 None は「補正しない」で、BIC/AIC は従来式と
    # ビット同一。`noise_scale` と同時には使えない (どちらも χ² の尺度を変えるので二重になる)。
    effective_dof_ratio: float | None = None

    def __post_init__(self) -> None:
        r = self.effective_dof_ratio
        if r is None:
            return
        if not (isinstance(r, (int, float)) and math.isfinite(r) and 0.0 < r <= 1.0):
            raise ValueError(f"effective_dof_ratio は (0, 1] の有限値です: {r!r}")
        if self.noise_scale is not None:
            raise ValueError(
                "effective_dof_ratio と noise_scale は同時に指定できません (どちらも χ² の尺度を変える)"
            )


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
