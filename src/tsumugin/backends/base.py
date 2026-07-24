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


@dataclass(frozen=True, eq=False)
class Curvature:
    """最終受理パラメータにおける目的関数の曲率情報 (Issue #76 / FR-121)。

    バックエンドが σ 導出のために既に計算している重み付き JᵀJ を evidence 層 (Laplace/nested)
    へ公開する。``hessian`` は **負対数尤度 −logL = χ²/2 の Hessian の Gauss-Newton 近似
    (JᵀJ)** であり、`nested.laplace.LaplaceBackend.score_problem` の ``hessian`` 契約
    (負対数尤度の Hessian) にそのまま渡せるスケールで統一する。restraint 行を残差に含む
    バックエンドでは J も restraint 行込み (σ 導出と同一の J)。

    ``param_names`` は J の列順 (= ``point``/``hessian`` の次元順)。非識別パラメータ
    (恒等 0 列) を含む場合 hessian は特異になるが、それは消費側 (Laplace の正定値ガード)
    が正しく縮退するための情報であり、ここでは加工しない。
    """

    param_names: tuple[str, ...]  # 【列順】: J の列に対応するパラメータ名 (point/hessian と同順)
    point: np.ndarray  # 【最終受理パラメータベクトル】: param_names 順の実値
    hessian: np.ndarray  # 【JᵀJ】: −logL=χ²/2 の Hessian (Gauss-Newton 近似, 重み・restraint 行込み)

    # 【値等価 (eq=False + 手書き __eq__)】: dataclass 既定の __eq__ は ndarray の `==` が配列を
    #   返すため bool 文脈で ValueError (truth value ambiguous) になり、Curvature を内包する
    #   RefinementResult の等価比較 (決定論テスト等) を壊す。np.array_equal による値等価を定義する。
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Curvature):
            return NotImplemented
        return (
            self.param_names == other.param_names
            and bool(np.array_equal(self.point, other.point))
            and bool(np.array_equal(self.hessian, other.hessian))
        )

    # 【非ハッシュ化】: 値等価と整合するハッシュは配列内容に依存し高コストなため提供しない
    #   (内包側の RefinementResult も globals: Mapping を持ち元来非ハッシュ)。
    __hash__ = None  # type: ignore[assignment]


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
    # 【追加フィールド (Issue #76)】: 最終受理パラメータの JᵀJ 曲率 (Laplace/nested の実
    # Hessian 供給源)。提供できないバックエンド/経路 (解放ゼロ・非有限・GSAS 未配線) は None。
    # 末尾・既定値付きの非破壊追加。🔵
    curvature: Curvature | None = None


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
