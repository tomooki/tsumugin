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
from ._degrade import degrade_oserror
from ._gpx_spec import gpx_args

__all__ = ["COMPARE_TOOLS", "compare_structure_models"]


@degrade_oserror
def compare_structure_models(
    histograms: Sequence[Mapping[str, object]],
    variants: Sequence[Mapping[str, object]],
    *,
    runner: Callable | None = None,
    gpx_dir: str | None = None,
    save_gpx: bool = True,
    reason: str = "",
) -> dict:
    """構造モデルバリアントを精密化し BIC/AIC + 妥当性で序列化する (Ow 要否等のモデル選択)。

    :param histograms: HistogramSpec.to_dict の列 (instrument 情報を含む; joint なら複数)
    :param variants: ``[{"name": str, "phases": [PhaseSpec.to_dict, ...]}, ...]``。**構造の差**
        (Ow サイトの有無・D₂O の有無・空間群) を相集合として表現する。1 つ以上必要
    :param runner: **注入/テスト用** callable ((histograms, phases, **run_kwargs)→AutoRietveldResult;
        保存指定 ``gpx_dir``/``save_gpx`` も kwargs で届く)。JSON 越しには渡せない。None なら既定
        ``run_auto_rietveld`` (HistogramSpec の instrument で実精密化)
    :param gpx_dir: **精密化成果物の保存先の根** (2026-08-20 規定「全解析で保存する」; env
        ``TSUMUGIN_GPX_DIR`` より強い)。1 回の比較は run ディレクトリを**1 つ**共有し、その下に
        **棄却されたモデルも含めて**バリアントごとに ``model_<名前>.gpx`` と ``manifest.jsonl`` が
        並ぶ。省略時は env → 先頭ヒストグラムのデータ隣接 ``<data_dir>/tsumugin_gpx/run-<日時>/``。
        実際の保存先は返り値の ``scores[].gpx_path``
    :param save_gpx: 保存の opt-out (既定 True = 保存する)。opt-out は**明示の ``false`` だけ**
        (``null`` は既定 = 保存、bool 以外は error dict)。⚠ **棄却モデルの fit を止めない** —
        ΔBIC の根拠 (棄却側がどう壊れていたか) は数字だけでは検算できない
    :returns: ``best`` (物理妥当なモデルのうち最小 BIC) + ``best_is_valid`` + ``scores`` (BIC 昇順、
        各 ``delta_bic`` は全体最小 BIC 基準、各 ``gpx_path`` はそのバリアントの成果物 = "" は未保存)
        + ``warnings`` (保存先に書けず一時領域へ退避したときの理由など)。空 variants・不正 spec・
        型の違う ``gpx_dir``/``save_gpx`` は ``{"error", "error_type"}``

    ΔBIC の読み: ``delta_bic > ~10`` は最良モデルへの決定的支持 (実測 XND: model6[+Ow] は model5 に
    ΔBIC≈2.6e5 で支持され、かつ model6 のみ物理妥当だった)。**best_is_valid=False は「妥当な
    モデルが 1 つも無い」= どの候補も採れない**ので、モデル空間を広げること。
    """
    from ..autorietveld.compare import ModelVariant, compare_models

    try:
        # 【保存指定の型を先に検査】: 型違いは黙って別の意味になる (`_gpx_spec` 参照)。
        gpx_dir, save_gpx = gpx_args(gpx_dir, save_gpx)
        hist = [HistogramSpec.from_dict(h) for h in histograms]
        model_variants = [
            ModelVariant(
                name=str(v["name"]),
                phases=tuple(PhaseSpec.from_dict(p) for p in v["phases"]),  # type: ignore[union-attr]
            )
            for v in variants
        ]
        kwargs = {} if runner is None else {"runner": runner}
        comparison = compare_models(
            hist, model_variants,
            # 【成果物の指定は ① へ明示的に運ぶ】: ここで落とすと ``save_gpx=False`` (唯一の
            #   opt-out) も明示 ``gpx_dir`` も**黙って無視され**、全バリアントが既定 (env →
            #   データ隣接) へ書かれる。ΔBIC には現れない。
            gpx_dir=gpx_dir, save_gpx=save_gpx,
            **kwargs,  # type: ignore[arg-type]
        )
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
                # 【このバリアントの fit (規定 2026-08-20)】: **棄却モデルの fit を開くための唯一の
                #   ハンドル** (§4.5 到達可能性)。`best` の名前と ΔBIC だけでは、棄却側がどう
                #   壊れていたかを ③ も人間も確かめられない。"" = 未保存。
                "gpx_path": str(s.gpx_path),
            }
            for s in comparison.scores
        ],
        "warnings": list(comparison.warnings),
        "reason": reason,
    }


#: MCP_TOOLS へマージする構造モデル比較ツール (Issue #100)。
COMPARE_TOOLS: Mapping[str, object] = {
    "compare_structure_models": compare_structure_models,
}
