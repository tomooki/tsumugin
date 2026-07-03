"""RefinementBackend 抽象境界 (仕様 P7 / §3.1)。

精密化エンジンを交換可能にする契約。入力 RefinementModel と出力 RefinementResult は
いずれも frozen dataclass で、バックエンドをまたいで同一の値オブジェクトを流通させる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

import numpy as np

from ..model import PhaseInstance


@dataclass(frozen=True)
class RefinementModel:
    """精密化への入力。free_params は "phase{i}.{suffix}" 形式の解放中パラメータ名。"""

    phases: tuple[PhaseInstance, ...]
    free_params: frozenset[str]
    two_theta: np.ndarray
    intensity: np.ndarray
    weights: np.ndarray | None = None


@dataclass(frozen=True)
class RefinementResult:
    """精密化からの出力。"""

    phases: tuple[PhaseInstance, ...]
    chi2: float
    rwp: float
    n_obs: int
    n_params: int
    converged: bool
    n_cycles: int
    free_params: frozenset[str] = field(default_factory=frozenset)


@runtime_checkable
class RefinementBackend(Protocol):
    """精密化バックエンドの構造的インターフェース。"""

    name: str

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        ...


def param_name(phase_index: int, key: str) -> str:
    """(相インデックス, キー) を正準パラメータ名へ。"""
    return f"phase{phase_index}.{key}"


def parse_param(name: str) -> tuple[int, str]:
    """正準パラメータ名を (相インデックス, キー) へ逆変換。キーはドットを含みうる。"""
    head, _, tail = name.partition(".")
    if not head.startswith("phase") or not tail:
        raise ValueError(f"invalid parameter name: {name!r}")
    return int(head[len("phase"):]), tail
