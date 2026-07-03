"""段階的パラメータ解放エンジン (仕様 FR-200 / FR-201 / FR-202 + FR-210)。

既定テンプレートに沿って段階的にパラメータを解放し、各段で
  snapshot 保存 -> backend.refine -> ガード検査
を回す。ガード違反時はスナップショットへ revert し、原因となった段の解放パラメータを固定して
再試行する。max_retries 回失敗した段はエスカレーション扱いとし、処理はブロックせず次段へ進む
(FR-403)。全遷移は理由付きで ledger に追記される (FR-214)。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..backends.base import (
    RefinementBackend,
    RefinementModel,
    RefinementResult,
    param_name,
)
from ..model import PhaseInstance, RefinementMetrics
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from .guardrails import GuardConfig, GuardViolation, check_guards


@dataclass(frozen=True)
class Stage:
    name: str
    param_keys: tuple[str, ...]


# FR-201 既定テンプレート。suffix は engine が全相へ展開する。
# profile 以降は M0 の SimulatedBackend では認識されず no-op で通過する枠。
DEFAULT_STAGE_TEMPLATE: tuple[Stage, ...] = (
    Stage("scale_bg", ("scale",)),
    Stage("lattice_zero", ("lattice.a", "lattice.b", "lattice.c")),
    Stage("profile", ("profile",)),
    Stage("texture", ("texture",)),
    Stage("occupancy", ("occupancy",)),
    Stage("coordinates", ("coordinates",)),
    Stage("adp", ("adp",)),
)


@dataclass(frozen=True)
class StageOutcome:
    stage: str
    accepted: bool
    result: RefinementResult
    violations: tuple[GuardViolation, ...]
    retries: int


@dataclass(frozen=True)
class RefinementReport:
    final_phases: tuple[PhaseInstance, ...]
    metrics: RefinementMetrics
    stage_outcomes: tuple[StageOutcome, ...]
    escalated: bool
    free_params: frozenset[str] = field(default_factory=frozenset)


class StagedRefinementEngine:
    def __init__(
        self,
        backend: RefinementBackend,
        store: SnapshotStore,
        ledger: Ledger,
        *,
        template: tuple[Stage, ...] = DEFAULT_STAGE_TEMPLATE,
        config: GuardConfig = GuardConfig(),
        max_retries: int = 3,
        worsen_tol: float = 1e-9,
    ) -> None:
        self.backend = backend
        self.store = store
        self.ledger = ledger
        self.template = template
        self.config = config
        self.max_retries = max_retries
        self.worsen_tol = worsen_tol

    def _expand(self, keys: tuple[str, ...], n_phases: int) -> set[str]:
        return {param_name(i, key) for i in range(n_phases) for key in keys}

    def _refine(
        self,
        phases: tuple[PhaseInstance, ...],
        free: frozenset[str],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        weights: np.ndarray | None,
    ) -> RefinementResult:
        model = RefinementModel(
            phases=phases,
            free_params=free,
            two_theta=two_theta,
            intensity=intensity,
            weights=weights,
        )
        return self.backend.refine(model)

    def run(
        self,
        phases: tuple[PhaseInstance, ...],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        *,
        weights: np.ndarray | None = None,
    ) -> RefinementReport:
        two_theta = np.asarray(two_theta, dtype=float)
        intensity = np.asarray(intensity, dtype=float)
        n_phases = len(phases)

        # ベースライン: 何も解放せずに現状を評価し、以後のガード/改善比較の基準にする。
        prev = self._refine(phases, frozenset(), two_theta, intensity, weights)
        current = phases
        free: frozenset[str] = frozenset()
        self.ledger.append(
            "initial_refine", {"rwp": prev.rwp, "chi2": prev.chi2, "n_params": prev.n_params}
        )

        outcomes: list[StageOutcome] = []
        escalated = False

        for stage in self.template:
            stage_params = self._expand(stage.param_keys, n_phases)
            trial_free = free | stage_params
            snap = self.store.save(current, label=stage.name)

            attempt = 0
            stage_result = prev
            violations: tuple[GuardViolation, ...] = ()
            accepted = False
            stage_escalated = False

            while True:
                attempt += 1
                result = self._refine(current, trial_free, two_theta, intensity, weights)
                violations = check_guards(prev, result, config=self.config)
                self.ledger.append(
                    "stage_refine",
                    {
                        "stage": stage.name,
                        "attempt": attempt,
                        "rwp": result.rwp,
                        "chi2": result.chi2,
                        "free": sorted(trial_free),
                        "violations": [v.kind for v in violations],
                    },
                )
                stage_result = result

                if not violations:
                    break

                # ガード違反: 記録 -> revert -> 原因(当該段の解放)を固定
                self.ledger.append(
                    "guard_violation",
                    {
                        "stage": stage.name,
                        "attempt": attempt,
                        "violations": [
                            {"kind": v.kind, "param": v.param, "detail": v.detail}
                            for v in violations
                        ],
                    },
                )
                current = self.store.revert(snap.id)
                self.ledger.append(
                    "rollback", {"stage": stage.name, "attempt": attempt, "to": snap.id}
                )
                trial_free = trial_free - stage_params

                if attempt >= self.max_retries:
                    stage_escalated = True
                    escalated = True
                    self.ledger.append(
                        "escalate",
                        {
                            "stage": stage.name,
                            "reason": "max_retries_exceeded",
                            "violations": [v.kind for v in violations],
                        },
                    )
                    break

            if not stage_escalated and not violations:
                worsened = (
                    prev is not None
                    and stage_result.rwp > prev.rwp + self.worsen_tol
                )
                if worsened:
                    # 悪化: 固定戻し (FR-202)。前段の phases を保持し free は据え置き。
                    current = self.store.revert(snap.id)
                    self.ledger.append(
                        "stage_fixed_back",
                        {"stage": stage.name, "rwp": stage_result.rwp, "prev_rwp": prev.rwp},
                    )
                    accepted = False
                else:
                    current = stage_result.phases
                    free = trial_free
                    prev = stage_result
                    accepted = True
                    self.ledger.append(
                        "stage_accepted",
                        {"stage": stage.name, "rwp": stage_result.rwp, "free": sorted(free)},
                    )

            outcomes.append(
                StageOutcome(
                    stage=stage.name,
                    accepted=accepted,
                    result=stage_result,
                    violations=violations,
                    retries=attempt - 1,
                )
            )

        metrics = RefinementMetrics(
            rwp=prev.rwp,
            gof=_gof(prev),
            chi2=prev.chi2,
            n_obs=prev.n_obs,
            n_params=prev.n_params,
        )
        return RefinementReport(
            final_phases=current,
            metrics=metrics,
            stage_outcomes=tuple(outcomes),
            escalated=escalated,
            free_params=free,
        )


def _gof(result: RefinementResult) -> float:
    dof = max(result.n_obs - result.n_params, 1)
    return float((result.chi2 / dof) ** 0.5)
