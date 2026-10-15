"""RefinementBackend 抽象境界 (仕様 P7 / §3.1)。

精密化エンジンを交換可能にする契約。入力 RefinementModel と出力 RefinementResult は
いずれも frozen dataclass で、バックエンドをまたいで同一の値オブジェクトを流通させる。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Protocol, runtime_checkable

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


# 値とみなす数字: 小数 (指数可) と ``=`` 直後の整数。相名・パスの数字 (A1.cif) は値でないので含めない
_VALUE_RE = re.compile(r"[-+]?\d+\.\d+(?:[eE][-+]?\d+)?|(?<==)[-+]?\d+")
_FOLDED_RE = re.compile(r" \[同種の文 ほか (\d+) 件\]$")


def merge_warnings(*groups: Iterable[str]) -> tuple[str, ...]:
    """backend の警告列を出現順に 1 本にする (同じ文は 1 回・同種の文は畳む)。

    backend の ``RefinementResult.warnings`` を消費側の結果へ運ぶときに使う。

    - **同じ文は 1 回**: GSAS の structure_ref 経路は同じ CIF なら精密化のたびに同じ吸着の
      記録を返す。回数は数えない (同じ入力についての同じ記録で、別の事象ではない)。
    - **値だけ違う同種の文は最初の 1 文 + 件数**: SimulatedBackend の μt・ノイズ推定の由来は
      精密化ごとに値を埋め込むので、そのままでは逐次 20 フレームで 140 行になった (実測)。
      数字 (小数と ``=`` 直後の整数) を伏せて同じになる文を同種とし、最初の文に
      ``[同種の文 ほか N 件]`` を付ける。値ごとの詳細は個々の ``RefinementResult`` にある。
      畳んだ文をさらに束ねても件数は足し合わされる (段階の結果 → 逐次の結果)。
    """
    first: dict[str, str] = {}  # 同種の鍵 -> 最初の文
    seen: dict[str, set[str]] = {}  # 同種の鍵 -> 見た文 (同じ文は数えない)
    folded: dict[str, int] = {}  # 同種の鍵 -> 畳み済みの文が抱えていた件数
    for group in groups:
        for warning in group:
            match = _FOLDED_RE.search(warning)
            text = warning[: match.start()] if match else warning
            key = _VALUE_RE.sub("#", text)
            first.setdefault(key, text)
            seen.setdefault(key, set()).add(text)
            if match:
                folded[key] = folded.get(key, 0) + int(match.group(1))
    merged: list[str] = []
    for key, text in first.items():
        rest = len(seen[key]) - 1 + folded.get(key, 0)
        merged.append(f"{text} [同種の文 ほか {rest} 件]" if rest else text)
    return tuple(merged)


def default_weights(intensity: np.ndarray) -> np.ndarray:
    """``RefinementModel.weights`` が未指定のときの統計重み ``w = 1/max(y, 1)``。

    **バックエンド横断で 1 つの定義に揃えるためにここに置く** (不変条件「chi2/rwp の
    セマンティクスはバックエンド間で統一 — BIC 比較の一貫性」)。重みが揃っていないと
    ``chi2`` の絶対値がエンジンごとに数桁ずれ、``close_threshold`` のような**絶対 ΔBIC の
    閾値がエンジン依存になる** (判別 `discriminate(backend=)` は同じ閾値を両エンジンに使う)。

    実測: 同じ実データ・同じ実 CIF で ``w=1`` の TOPAS 版は chi2 1.4e9、Poisson 重みの
    GSAS-II 版は 6.8e5 だった。**格子は 0.07% 以内で一致していたのに** chi2 だけが
    比較できない状態だった。
    """
    values = np.asarray(intensity, dtype=float)
    return 1.0 / np.maximum(values, 1.0)


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
