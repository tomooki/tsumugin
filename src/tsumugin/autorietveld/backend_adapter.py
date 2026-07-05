"""M8 要素4: AutoRietveldBackend — 実構造自動 Rietveld を RefinementBackend Protocol に配線。

現状 `pipeline`/`search` はダミー `SimulatedBackend` を用いる。本アダプタは `RefinementModel`
(相 + 観測) を `PhaseSpec`/`HistogramSpec` へ写像して `run_auto_rietveld` へ委譲し、結果を
`RefinementResult` へ写像する。これにより `HypothesisTreeSearch`/evidence/chem が**実構造**で
多仮説を精密化・ランキングできる (architecture.md §7)。

chi2 は既存 GSASIIBackend と整合する **weighted-SSR** (= gof²·(n_obs−n_params)) で再構成し、
BIC 比較の一貫性を保つ (CLAUDE.md 不変条件「chi2/rwp のセマンティクスはバックエンド間で統一」)。
精密化失敗は例外でなく **chi2=inf の結果**へ縮退させガードレールに処理させる (同不変条件)。

**既知の制限 (n_obs の源)**: ``AutoRietveldResult`` が観測点数 (Nobs) を露出しないため、chi2/BIC の
Nobs には ``model.intensity`` の長さを用いる。``two_theta_limits`` によるレンジ制限やマルチ
ヒストグラム joint では GSAS の実 Nobs (= Σ Nobs_i) と一致しないため、**同一ヒストグラム集合内での
序列比較には妥当**だが、GSASIIBackend と混在させた絶対値比較・BIC の ln(n) 罰は厳密でない。
真の Nobs を engine から ``AutoRietveldResult`` へ通す厳密化は M-later (Issue 化候補)。

相の構造ファイル解決は `resolver` (phase_ref→PhaseSpec) に委ね、観測ファイルは `histograms`
テンプレートで与える (PhaseInstance はファイルパスを持たないため)。GSAS は runner 内で遅延 import。

信頼性: 🔵 architecture.md §7.1 + backends/base.py の RefinementResult 契約。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..backends.base import RefinementModel, RefinementResult
from ..refine_loop.action import AnalysisInput
from .model import AutoRietveldResult, HistogramSpec, PhaseSpec

Resolver = Callable[[str], PhaseSpec]
Runner = Callable[[AnalysisInput], AutoRietveldResult]


@dataclass(frozen=True)
class AutoRietveldBackend:
    """`RefinementBackend` Protocol を満たす実構造 Rietveld アダプタ (§7.1)。

    :param resolver: phase_ref → PhaseSpec (構造ファイルの解決)
    :param histograms: 観測ヒストグラム仕様テンプレート (実データ + 装置)
    :param background_coeffs: 初期背景係数数
    :param name: バックエンド名 (Protocol 属性)
    :param runner: 注入 runner (None なら GSAS 駆動 run_auto_rietveld)
    """

    resolver: Resolver
    histograms: tuple[HistogramSpec, ...]
    background_coeffs: int = 6
    name: str = "auto_rietveld"
    runner: Runner | None = None

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        """RefinementModel を run_auto_rietveld で精密化し RefinementResult へ写像する。

        失敗は chi2=inf/ rwp=inf の結果へ縮退 (例外にしない, 既存規約)。
        """
        n_obs = int(np.size(model.intensity)) if model.intensity is not None else 0
        try:
            phases = tuple(self.resolver(p.phase_ref) for p in model.phases)
            inp = AnalysisInput(
                histograms=tuple(self.histograms),
                phases=phases,
                background_coeffs=self.background_coeffs,
            )
            run = self.runner or _make_gsas_runner(max_cycles)
            result = run(inp)
        except Exception:  # noqa: BLE001 — 失敗はガードレールへ (chi2=inf に縮退)
            return RefinementResult(
                phases=model.phases,
                chi2=float("inf"),
                rwp=float("inf"),
                n_obs=n_obs,
                n_params=0,
                converged=False,
                n_cycles=0,
            )

        n_params = result.stage_results[-1].n_params if result.stage_results else 0
        # weighted-SSR 再構成: reduced χ² = gof² ⇒ SSR = gof²·(n_obs − n_params) (GSASIIBackend 整合)
        dof = max(n_obs - n_params, 1)
        chi2 = float(result.final_gof) ** 2 * dof
        converged = bool(result.stage_results[-1].converged) if result.stage_results else False
        return RefinementResult(
            phases=model.phases,
            chi2=chi2,
            rwp=float(result.final_rwp),
            n_obs=n_obs,
            n_params=n_params,
            converged=converged,
            n_cycles=len(result.stage_results),
        )


def _make_gsas_runner(max_cycles: int) -> Runner:
    """AnalysisInput を run_auto_rietveld で実行する既定 runner (GSAS 遅延 import)。"""

    def runner(inp: AnalysisInput) -> AutoRietveldResult:
        from .engine import run_auto_rietveld
        from .recipe import build_recipe

        recipe = build_recipe(
            inp.histograms, inp.phases, background_coeffs=inp.background_coeffs
        )
        recipe = (*recipe, *inp.extra_stages)
        return run_auto_rietveld(
            list(inp.histograms), list(inp.phases), recipe=recipe, max_cyc=max_cycles
        )

    return runner
