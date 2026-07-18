"""薄い MCP ツール — 構造モデルバリアントの BIC 比較 (compare_structure_models, Issue #100)。

`autorietveld.compare.compare_models` (XND) は callable 制約が無い (runner の既定が実装関数
`run_auto_rietveld` そのもの) のに ② 未露出だった。model5 / model6[+Ow] / +D₂O のような**構造の
差**を同一観測で精密化し **BIC/AIC + 物理妥当性**で序列化する = ③ が「Ow は要るか」「編集候補の
どれが最良か」を ΔBIC で判定する計器。

**runner/identifier の callable 問題は無い**: HistogramSpec が instrument (instprm/radiation/
geometry) を dict で持つため、variants の phases を差し替えるだけで実運用の精密化に到達する。
runner はテスト注入専用シーム (既定は run_auto_rietveld)。

**SDK 非依存**: 素の型 dict のみ (json.dumps allow_nan=False 安全)。GSAS は runner 内で遅延 import。

信頼性: 🔵 Issue #100 / architecture.md §4.5 カバレッジ規則④。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import HistogramSpec, PhaseSpec

__all__ = ["COMPARE_TOOLS", "compare_structure_models"]


def compare_structure_models(
    histograms: Sequence[Mapping[str, object]],
    variants: Sequence[Mapping[str, object]],
    *,
    runner: Callable | None = None,
    reason: str = "",
) -> dict:
    """構造モデルバリアントを精密化し BIC/AIC + 妥当性で序列化する (Ow 要否等のモデル選択)。

    :param histograms: HistogramSpec.to_dict の列 (instrument 情報を含む; joint なら複数)
    :param variants: ``[{"name": str, "phases": [PhaseSpec.to_dict, ...]}, ...]``。**構造の差**
        (Ow サイトの有無・D₂O の有無・空間群) を相集合として表現する。1 つ以上必要
    :param runner: **注入/テスト用** callable ((histograms, phases)→AutoRietveldResult)。JSON 越し
        には渡せない。None なら既定 ``run_auto_rietveld`` (HistogramSpec の instrument で実精密化)
    :returns: ``best`` (物理妥当なモデルのうち最小 BIC) + ``best_is_valid`` + ``scores`` (BIC 昇順、
        各 ``delta_bic`` は全体最小 BIC 基準)。空 variants・不正 spec は ``{"error", "error_type"}``

    ΔBIC の読み: ``delta_bic > ~10`` は最良モデルへの決定的支持 (実測 XND: model6[+Ow] は model5 に
    ΔBIC≈2.6e5 で支持され、かつ model6 のみ物理妥当だった)。**best_is_valid=False は「妥当な
    モデルが 1 つも無い」= どの候補も採れない**ので、モデル空間を広げること。
    """
    from ..autorietveld.compare import ModelVariant, compare_models

    try:
        hist = [HistogramSpec.from_dict(h) for h in histograms]
        model_variants = [
            ModelVariant(
                name=str(v["name"]),
                phases=tuple(PhaseSpec.from_dict(p) for p in v["phases"]),  # type: ignore[union-attr]
            )
            for v in variants
        ]
        kwargs = {} if runner is None else {"runner": runner}
        comparison = compare_models(hist, model_variants, **kwargs)  # type: ignore[arg-type]
    except (ValueError, TypeError, KeyError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    return {
        "best": comparison.best,
        "best_is_valid": comparison.best_is_valid,
        "scores": [
            {
                "name": s.name,
                "rwp": finite_or_none(s.rwp),
                "gof": finite_or_none(s.gof),
                "n_params": s.n_params,
                "bic": finite_or_none(s.bic),
                "aic": finite_or_none(s.aic),
                "delta_bic": finite_or_none(s.delta_bic),
                "validity_passed": bool(s.validity_passed),
                "phase_fractions": {k: finite_or_none(v) for k, v in s.phase_fractions.items()},
                "warnings": list(s.warnings),
            }
            for s in comparison.scores
        ],
        "reason": reason,
    }


#: MCP_TOOLS へマージする構造モデル比較ツール (Issue #100)。
COMPARE_TOOLS: Mapping[str, object] = {
    "compare_structure_models": compare_structure_models,
}
