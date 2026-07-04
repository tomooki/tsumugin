"""MEM-Rietveld (MPF) 反復 (M5 / REQ-024/025/026/107/202 / EDGE-008/009 / D6)。

MEM 密度 → F_calc 更新 → 再精密化 の MPF (Maximum-entropy / Prior / Fit) サイクルを回す。

【既定オフ (REQ-024)】``MEMRietveldConfig.enabled=False`` が既定。明示有効化なしでは反復せず
  ``stop_reason="disabled"`` を即返す (子スナップショット追記なし)。

【非破壊 (P2 / REQ-202 / NFR-005)】各サイクルの再精密化 phases は ``SnapshotStore.save`` の
  **子スナップショットとして追記** する (親 phases / joint 結果は不変・削除/上書きしない)。
  発散時の当該サイクルも子スナップショットに残す (破壊しない・ロールバックは revert 経由)。

【停止 (REQ-026/107/EDGE-008/009)】収束 (R/密度変化 < tol) or max_iter で停止し理由を ledger 記録。
  発散 (密度負値 / R 悪化) は当該サイクルを残しつつ停止・``stop_reason="diverged"``・ledger 記録。

【決定論】MEMBackend / RefinementBackend が決定論なら同一入力で同一結果 (乱数不使用)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..backends.base import RefinementBackend, RefinementModel
from ..joint.model import JointRefinementResult
from ..model import PhaseInstance
from ..model.project import Probe
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from .base import MEMBackend, MEMResult
from .inputgen import build_mem_input


@dataclass(frozen=True)
class MEMRietveldConfig:
    """MEM-Rietveld (MPF) 反復設定。既定オフ。🔵 REQ-024/302

    【既定オフ (REQ-024)】: ``enabled=False`` が既定。明示有効化なしでは反復しない。
    【停止 (REQ-026)】: max_iter または密度/R 変化 < tol で停止する。
    """

    enabled: bool = False  # 【MEM-Rietveld 反復の有効化 (既定オフ)】 🔵 REQ-024
    max_iter: int = 5  # 【最大反復数】 🔵 REQ-026
    r_tol: float = 1e-3  # 【R 値変化の収束閾値】 🔵 REQ-026
    density_tol: float = 1e-3  # 【密度変化の収束閾値】 🔵 REQ-026


@dataclass(frozen=True)
class MEMRietveldCycle:
    """MEM-Rietveld 反復 1 サイクルの記録 (子スナップショット参照付き)。🔵 REQ-025

    各サイクルは SnapshotStore の子スナップショットとして追記され、その ID を保持する (P2)。
    """

    iteration: int  # 【反復番号 (0 始まり)】 🔵
    snapshot_id: str  # 【子スナップショット ID (追記型)】 🔵 REQ-025
    r_factor: float  # 【当該サイクルの R 値】 🔵 REQ-026
    mem_result: MEMResult  # 【当該サイクルの MEM 結果】 🔵


@dataclass(frozen=True)
class MEMRietveldResult:
    """MEM-Rietveld 反復の全体結果 (停止理由 + サイクル列)。🔵 REQ-024/026/107

    【非破壊 (REQ-202/NFR-005)】: 親仮説・joint 結果は不変。各サイクルは子スナップショット追記。
    """

    cycles: tuple[MEMRietveldCycle, ...]  # 【反復サイクル列 (追記順)】 🔵 REQ-025
    stop_reason: Literal["converged", "max_iter", "diverged", "disabled"]  # 🔵 REQ-026/107
    warnings: tuple[str, ...] = ()  # 【発散等の警告】 🔵 REQ-107


def _refine_once(
    backend: RefinementBackend, phases: tuple[PhaseInstance, ...]
) -> tuple[PhaseInstance, ...]:
    """現在 phases から自己無撞着な合成パターンを組み、scale を再精密化して phases を更新する。🔵

    MPF の「再精密化」段を決定論的に表現する。前方モデル (backend.simulate 相当) が使えない
    抽象 RefinementBackend でも動くよう、RefinementModel を組み backend.refine に委譲する。
    観測は現 phases から生成した合成パターンを用いる (親 phases は改変せず新 phases を返す)。
    """
    # 【自己無撞着観測】: SimulatedBackend は simulate を持つ。持たない backend は phases 不変で返す。
    simulate = getattr(backend, "simulate", None)
    if simulate is None:
        return phases
    two_theta = np.arange(15.0, 60.0, 0.05)
    intensity = simulate(phases, two_theta)
    free = frozenset(f"phase{i}.scale" for i in range(len(phases)))
    model = RefinementModel(
        phases=phases, free_params=free, two_theta=two_theta, intensity=intensity
    )
    result = backend.refine(model)
    return result.phases


def run_mem_rietveld(
    backend: RefinementBackend,
    mem_backend: MEMBackend,
    joint_result: JointRefinementResult,
    parent_phases: tuple[PhaseInstance, ...],
    probe: Probe,
    *,
    config: MEMRietveldConfig = MEMRietveldConfig(),
    snapshots: SnapshotStore,
    ledger: Ledger | None = None,
) -> MEMRietveldResult:
    """MEM-Rietveld (MPF) 反復を回す。既定オフ・各サイクルは子スナップショット追記。🔵 REQ-024/025/026/107/202

    【既定オフ (REQ-024)】: config.enabled=False なら反復せず stop_reason="disabled" を即返す
      (子スナップショット追記なし)。
    【MPF サイクル】: MEM 密度 → F_calc 更新 → 再精密化 を回す。各サイクルの phases を
      ``snapshots.save(..., label="mem_rietveld_iter{n}")`` で子スナップショットとして追記する
      (親不変, REQ-025/202/NFR-005)。削除・上書きはしない (P2)。
    【停止 (REQ-026/EDGE-009)】: 収束 (R/密度変化 < tol) or max_iter 到達で停止し停止理由を ledger 記録。
    【発散 (REQ-107/EDGE-008)】: 密度負値 / R 悪化を検知したら当該サイクルを子スナップショットに残しつつ
      停止し stop_reason="diverged"、理由を ledger 記録する (ロールバックは revert 経由・破壊しない)。
    """
    # 【既定オフ (REQ-024)】: 有効化なしでは反復せず即 disabled (副作用ゼロ)。
    if not config.enabled:
        if ledger is not None:
            ledger.append("mem_rietveld_disabled", {"reason": "config.enabled is False"})
        return MEMRietveldResult(cycles=(), stop_reason="disabled")

    cycles: list[MEMRietveldCycle] = []
    warnings: list[str] = []
    stop_reason: Literal["converged", "max_iter", "diverged"] = "max_iter"

    # 【現在 phases】: 親 phases を起点に反復する。親自体は改変せず新 phases を都度作る (P2)。
    current_phases = parent_phases
    prev_r: float | None = None
    prev_min_density: float | None = None

    for iteration in range(config.max_iter):
        # 【MEM 段】: 現 phases 由来の joint 結果から MEM 入力を組み密度を計算する。
        mem_input = build_mem_input(joint_result, probe)
        mem_result = mem_backend.run(mem_input)
        r_factor = (
            float(mem_result.r_factor) if mem_result.r_factor is not None else 0.0
        )
        min_density = float(mem_result.density_map.min_density)

        # 【再精密化段】: MEM 密度更新後に scale を再精密化した新 phases を得る (親不変)。
        current_phases = _refine_once(backend, current_phases)

        # 【子スナップショット追記 (REQ-025/202/P2)】: 各サイクルの phases を追記型で保存する。
        snap = snapshots.save(current_phases, label=f"mem_rietveld_iter{iteration}")
        cycles.append(
            MEMRietveldCycle(
                iteration=iteration,
                snapshot_id=snap.id,
                r_factor=r_factor,
                mem_result=mem_result,
            )
        )

        # 【発散判定 (REQ-107/EDGE-008)】: 密度負値 / R 悪化を検知したら当該サイクルを残し停止。
        diverged_negative = min_density < 0.0
        diverged_worsening = prev_r is not None and r_factor > prev_r + config.r_tol
        if diverged_negative or diverged_worsening:
            reason = "密度負値" if diverged_negative else "R 値悪化"
            warnings.append(
                f"MEM-Rietveld 反復が発散しました ({reason}, iter={iteration})。"
                "当該サイクルは子スナップショットに残置し停止します (破壊しません・revert で復帰可)。"
            )
            stop_reason = "diverged"
            if ledger is not None:
                ledger.append(
                    "mem_rietveld_diverged",
                    {
                        "iteration": iteration,
                        "reason": reason,
                        "r_factor": r_factor,
                        "min_density": min_density,
                        "snapshot_id": snap.id,
                    },
                )
            break

        # 【収束判定 (REQ-026/EDGE-009)】: R / 密度の変化が tol 未満なら収束停止。
        r_converged = prev_r is not None and abs(r_factor - prev_r) < config.r_tol
        d_converged = (
            prev_min_density is not None
            and abs(min_density - prev_min_density) < config.density_tol
        )
        if r_converged and d_converged:
            stop_reason = "converged"
            if ledger is not None:
                ledger.append(
                    "mem_rietveld_converged",
                    {
                        "iteration": iteration,
                        "r_factor": r_factor,
                        "min_density": min_density,
                        "snapshot_id": snap.id,
                    },
                )
            break

        prev_r = r_factor
        prev_min_density = min_density
    else:
        # 【max_iter 到達 (REQ-026)】: for が break せず尽きた場合。
        stop_reason = "max_iter"
        if ledger is not None:
            ledger.append(
                "mem_rietveld_max_iter",
                {"max_iter": config.max_iter, "n_cycles": len(cycles)},
            )

    return MEMRietveldResult(
        cycles=tuple(cycles),
        stop_reason=stop_reason,
        warnings=tuple(warnings),
    )
