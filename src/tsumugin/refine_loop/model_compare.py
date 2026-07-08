"""構造モデル変種の BIC+妥当性裁定 (refine-loop-diagnostics REQ-005/202)。

単一モデル調律ループ (`orchestrator.run_refinement_loop`) の**外側**の薄い上位オーケストレータ。
構造モデル変種 (例 model5 / model6[+Ow] / +D₂O) をそれぞれ精密化し、`autorietveld.compare.
compare_models` に委譲して BIC + 物理妥当性で序列化する。best は妥当なモデルのうち最小 BIC、
妥当が皆無なら全体最小へフォールバック (best_is_valid=False)。各変種の評価を ledger に追記する
(verify() True を保つ, NFR-105)。

numpy コア + GSAS は runner (compare 経由) 内で遅延 import。決定論 (NFR-102)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from tsumugin.autorietveld.compare import ModelComparison, ModelVariant, compare_models
from tsumugin.autorietveld.model import HistogramSpec, PhaseSpec

__all__ = ["ModelCompareResult", "run_model_comparison"]


@dataclass(frozen=True)
class ModelCompareResult:
    """モデル比較の結果。

    :param comparison: `compare.ModelComparison` (scores/best/best_is_valid)
    :param best_phases: best 変種の相仕様 (継続精密化に用いる)
    :param ledger: 追記された台帳 (None なら未使用)
    """

    comparison: ModelComparison
    best_phases: tuple[PhaseSpec, ...] = ()
    ledger: object | None = None


def run_model_comparison(
    histograms: Sequence[HistogramSpec],
    variants: Sequence[ModelVariant],
    *,
    runner: object | None = None,
    ledger: object | None = None,
    **run_kwargs: object,
) -> ModelCompareResult:
    """変種を精密化し BIC+妥当性で裁定 + ledger 追記する (REQ-005/202)。

    :param histograms: 観測ヒストグラム集合 (同時精密化なら複数)
    :param variants: 比較する構造モデル変種
    :param runner: 精密化関数 (None なら compare 既定 = run_auto_rietveld; テストでスタブ注入)
    :param ledger: 追記台帳 (None なら未使用)
    :param run_kwargs: runner へ渡す追加引数 (recipe/max_cyc/keep_gpx 等)
    :returns: :class:`ModelCompareResult`

    Raises:
        ValueError: variants が空のとき (compare_models が送出)。
    """
    compare_kwargs = dict(run_kwargs)
    if runner is not None:
        compare_kwargs["runner"] = runner
    comparison = compare_models(histograms, variants, **compare_kwargs)

    if ledger is not None:
        for s in comparison.scores:
            ledger.append(
                "model_compare_variant",
                {
                    "name": s.name,
                    "bic": s.bic,
                    "delta_bic": s.delta_bic,
                    "validity": s.validity_passed,
                },
            )
        ledger.append(
            "model_compare_best",
            {"best": comparison.best, "best_is_valid": comparison.best_is_valid},
        )

    best_phases: tuple[PhaseSpec, ...] = ()
    for v in variants:
        if v.name == comparison.best:
            best_phases = tuple(v.phases)
            break

    return ModelCompareResult(comparison=comparison, best_phases=best_phases, ledger=ledger)
