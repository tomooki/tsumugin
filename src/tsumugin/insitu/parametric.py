"""M9 パラメトリック解析 — 逐次精密化結果から物理量を抽出する (numpy-only)。

GSAS-II "Parametric Fitting and Pseudo Variables" チュートリアルに対応する解析層。
`SequentialRietveldResult` の格子/相分率系列を軸 (温度/時間) に対して回帰・転移推定する。
下位の統計は `tsumugin.sequential.thermal` (熱膨張ベースライン + 転移推定) を再利用し、本層は
系列結果からの抽出 + 擬変数 (pseudo-variable) の系列化のみを担う薄いアダプタ。

信頼性: 🔵 architecture.md §5。sequential.thermal (fit_thermal_baseline/estimate_transition) 上の薄層。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal

from ..sequential.thermal import (
    ThermalBaseline,
    TransitionEstimate,
    estimate_transition,
    fit_thermal_baseline,
)
from .model import Cell, SequentialRietveldResult

Component = Literal["a", "b", "c", "alpha", "beta", "gamma"]


@dataclass(frozen=True)
class ParametricAnalysis:
    """相 1 つのパラメトリック解析結果。

    :param phase: 相名
    :param baseline: 格子成分 vs 軸の熱膨張ベースライン (逸脱フレーム = 転移候補)
    :param transition: 相分率シグモイドからの転移推定 (無ければ None)
    """

    phase: str
    baseline: ThermalBaseline
    transition: TransitionEstimate | None


def lattice_baseline(
    result: SequentialRietveldResult,
    phase: str,
    *,
    component: Component = "a",
    degree: int = 1,
) -> ThermalBaseline:
    """相 phase の格子成分を軸 (温度) に対して多項式回帰し熱膨張ベースラインを返す。

    軸値を持つ有効フレームのみを用いる (欠測/失敗フレームは除外)。逸脱フレーム (残差ロバスト z が
    閾値超) は転移候補として `ThermalBaseline.outlier_frames` に入る。点数不足なら空の係数へ縮退。
    """
    axes, vals = result.cell_series(phase, component)
    return fit_thermal_baseline(
        list(axes), list(vals), degree=degree, parameter=f"{phase}.{component}"
    )


def transition_from_fractions(
    result: SequentialRietveldResult,
    phase: str,
) -> TransitionEstimate | None:
    """相 phase の相分率系列 (軸順) から転移 onset/midpoint±σ を推定する。

    方向 (appearing=出現 0→1 / disappearing=消失 1→0) は相分率トレンドから自動判定される
    (`sequential.thermal.estimate_transition`)。交差が無い/点数不足なら None。
    """
    axes, fracs = result.fraction_series(phase)
    return estimate_transition(list(axes), list(fracs), phase_ref=phase)


def pseudo_variable_series(
    result: SequentialRietveldResult,
    phase: str,
    func: Callable[[Cell], float],
) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """相 phase の格子から派生する擬変数 (例 b/c 比) の (軸値, 値) 系列を返す。

    func は格子 (a,b,c,α,β,γ) を受け取りスカラーを返す純関数。軸値を持ち当該相が存在する
    有効フレームのみを対象とする (CuCr₂O₄ の b/c 比収束 = 2 次転移の追跡等)。非有限は除外。
    """
    import math

    axes: list[float] = []
    vals: list[float] = []
    for f in result.frames:
        cell = f.refined_cells.get(phase)
        if cell is None or f.axis_value is None or f.refine_failed:
            continue
        try:
            v = float(func(cell))
        except (ZeroDivisionError, ValueError, TypeError):
            continue
        if not math.isfinite(v):
            continue
        axes.append(float(f.axis_value))
        vals.append(v)
    return tuple(axes), tuple(vals)


def analyze_phase(
    result: SequentialRietveldResult,
    phase: str,
    *,
    component: Component = "a",
    degree: int = 1,
) -> ParametricAnalysis:
    """相 phase の格子ベースライン + 相分率転移をまとめて解析する。"""
    return ParametricAnalysis(
        phase=phase,
        baseline=lattice_baseline(result, phase, component=component, degree=degree),
        transition=transition_from_fractions(result, phase),
    )
