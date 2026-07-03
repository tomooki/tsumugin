"""multistart 層 (FR-230〜234) — 決定論マルチスタート大域最適確認。

本タスク (TASK-0027) は決定論摂動列生成 (perturb) のみを提供する。
basin クラスタ / MultistartEngine は TASK-0028 で追加される。
"""

from __future__ import annotations

from .perturb import MultistartConfig, PerturbationSpec, generate_starts

__all__ = [
    "MultistartConfig",
    "PerturbationSpec",
    "generate_starts",
]
