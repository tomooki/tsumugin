"""multistart 層 (FR-230〜234) — 決定論マルチスタート大域最適確認。

TASK-0027 の決定論摂動列生成 (perturb) に加え、TASK-0028 で basin クラスタリング
(basin) と実行エンジン (engine) を提供する。新公開シンボルは __all__ へ非破壊追記。
"""

from __future__ import annotations

from .basin import BasinInfo, cluster_basins
from .engine import MultistartEngine, MultistartResult
from .perturb import MultistartConfig, PerturbationSpec, generate_starts

__all__ = [
    "BasinInfo",
    "MultistartConfig",
    "MultistartEngine",
    "MultistartResult",
    "PerturbationSpec",
    "cluster_basins",
    "generate_starts",
]
