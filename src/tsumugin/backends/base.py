"""RefinementBackend 抽象境界 (仕様 P7 / §3.1)。

精密化エンジンを交換可能にする契約。入力 RefinementModel と出力 RefinementResult は
いずれも frozen dataclass で、バックエンドをまたいで同一の値オブジェクトを流通させる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Protocol, runtime_checkable

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
    # 【大域 fitted 値】: 相に属さない精密化値 (例 {"mu_t": 0.48})。既定 空 dict (非破壊追加) 🔵
    globals: Mapping[str, float] = field(default_factory=dict)
    # 【警告列】: 経験推定モード明示 / 逆算 μt 提示 / restraint 逸脱の相関疑い。既定 空 tuple 🔵
    warnings: tuple[str, ...] = ()
    # 【追加フィールド (Issue #64 / FR-123)】: opt-in の EM ノイズ推定 (evidence.noise) を
    # 呼んだ場合のみ設定されるノイズスケール s。既定 None は「未推定」= 既存呼び出し元と
    # ビット同一 (末尾・既定値付きで非破壊追加, REQ-404)。🔵
    noise_scale: float | None = None


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
    """正準パラメータ名を (相インデックス, キー) へ逆変換。キーはドットを含みうる。

    ``"phase{i}.{suffix}" -> (i, suffix)`` (既存・不変)。大域パラメータは
    ``"global.{key}" -> (-1, key)`` を返す。相インデックス -1 は「どの相にも属さない
    大域パラメータ」の標識 (例: ``"global.mu_t" -> (-1, "mu_t")``)。
    """
    head, _, tail = name.partition(".")
    # 【大域分岐】: head=="global" かつ tail 非空のとき相インデックス -1 を返す (D8) 🔵
    if head == "global" and tail:
        return -1, tail
    if not head.startswith("phase") or not tail:
        raise ValueError(f"invalid parameter name: {name!r}")
    return int(head[len("phase"):]), tail
