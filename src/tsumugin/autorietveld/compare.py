"""複数構造モデルの Rietveld 比較 (autorietveld.compare)。

同一の観測ヒストグラム集合に対し、構造モデルのバリアント (例 Model5 / Model6[+Ow] / +D₂O) をそれぞれ
:func:`~tsumugin.autorietveld.engine.run_auto_rietveld` で精密化し、**BIC/AIC + 物理妥当性**で序列化する。
Model 6 の追加 O サイト (``Ow``) が必要かの定量判定 (ΔBIC) に用いる。

BIC は情報量規準 ``BIC = χ² + k·ln(n)`` (小さいほど良い)。``AutoRietveldResult`` の GOF から
``χ² = GOF²·(n_obs − k)`` を復元して :class:`~tsumugin.model.RefinementMetrics` を組み、
:class:`~tsumugin.evidence.BICBackend` に委譲する。精密化本体 (``runner``) は注入可能で、GSAS-II 非依存に
決定論テストできる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping, Sequence

from tsumugin.autorietveld.engine import run_auto_rietveld
from tsumugin.autorietveld.model import AutoRietveldResult, HistogramSpec, PhaseSpec
from tsumugin.evidence import AICBackend, BICBackend
from tsumugin.gpxstore import gpx_context, group_context
from tsumugin.model import RefinementMetrics

__all__ = [
    "ModelComparison",
    "ModelScore",
    "ModelVariant",
    "compare_models",
    "metrics_from_result",
]

# run_auto_rietveld と同じシグネチャの精密化関数 (テストでスタブ注入する)。
Runner = Callable[..., AutoRietveldResult]


@dataclass(frozen=True)
class ModelVariant:
    """比較する構造モデル 1 つ。🔵

    :param name: 表示名 (例 ``"model5"`` / ``"model6"`` / ``"model6+D"``)
    :param phases: 相仕様 (実 CIF)
    """

    name: str
    phases: tuple[PhaseSpec, ...]


@dataclass(frozen=True)
class ModelScore:
    """1 モデルの精密化品質と情報量規準。🔵"""

    name: str
    rwp: float
    gof: float
    n_obs: int
    n_params: int
    chi2: float
    bic: float
    aic: float
    validity_passed: bool
    phase_fractions: Mapping[str, float] = field(default_factory=dict)
    delta_bic: float = 0.0  # 最良モデル比 (最良=0, 正=劣る)
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModelComparison:
    """全バリアントの序列 (BIC 昇順) と最良モデル名。🔵

    :param scores: BIC 昇順の全モデルスコア (``delta_bic`` は全体最小 BIC 基準の ΔBIC)
    :param best: 選定モデル = **物理妥当なモデルのうち最小 BIC** (CLAUDE.md「BIC + 妥当性」)。
        妥当なモデルが 1 つも無いときのみ全体最小 BIC にフォールバックする。
    :param best_is_valid: ``best`` が物理妥当性を満たすか (全モデル不妥当なら False)
    """

    scores: tuple[ModelScore, ...]
    best: str
    best_is_valid: bool = True


def _final_n_params(result: AutoRietveldResult) -> int:
    """最終段階のパラメータ数 (段階が無ければ 0)。"""
    if result.stage_results:
        return int(result.stage_results[-1].n_params)
    return 0


def metrics_from_result(result: AutoRietveldResult) -> RefinementMetrics:
    """``AutoRietveldResult`` から BIC 用の :class:`RefinementMetrics` を組む。🔵

    ``χ² = GOF²·(n_obs − k)`` で重み付き残差二乗和を復元する (GOF²=χ²/自由度)。自由度が非正になる
    縮退時は ``n_obs`` を下限に採る。

    【noise_scale 対象外 (Issue #64 レビュー対応)】: 入力は ``RefinementResult`` でなく
      ``AutoRietveldResult`` (GSAS-II 駆動の自動 Rietveld 結果) で、noise_scale フィールドを
      持たない (EM ノイズ推定は現状 SimulatedBackend のみに配線, GSASIIBackend への配線はスコープ外)。
      よって本関数は noise_scale を伝播しない。
    """
    k = _final_n_params(result)
    n = int(result.n_obs)
    dof = max(n - k, 1)
    chi2 = float(result.final_gof) ** 2 * dof
    return RefinementMetrics(
        rwp=float(result.final_rwp),
        gof=float(result.final_gof),
        chi2=chi2,
        n_obs=n,
        n_params=k,
    )


def compare_models(
    histograms: Sequence[HistogramSpec],
    variants: Sequence[ModelVariant],
    *,
    runner: Runner = run_auto_rietveld,
    **run_kwargs: object,
) -> ModelComparison:
    """各バリアントを精密化し BIC/AIC + 妥当性で序列化する。🔵

    :param histograms: 観測ヒストグラム集合 (同時精密化なら複数)
    :param variants: 比較する構造モデル群
    :param runner: 精密化関数 (既定 ``run_auto_rietveld``; テストでスタブ注入可)
    :param run_kwargs: runner へ渡す追加引数 (recipe / max_cyc / keep_gpx 等)
    :returns: :class:`ModelComparison` (BIC 昇順, best=最小 BIC)

    Raises:
        ValueError: variants が空のとき。
    """
    if not variants:
        raise ValueError("compare_models には 1 つ以上の ModelVariant が必要です。")

    bic_backend = BICBackend()
    aic_backend = AICBackend()

    # 【棄却モデルの fit も残す (規定 2026-08-20)】: ΔBIC の根拠は「棄却された方がどう
    #   壊れていたか」(実測 NaCuHCF model5 は Na>1 / O<0 に発散) にある。数値だけでは検算できない。
    group, _reason = group_context(
        histograms[0].data_path if histograms else "",
        gpx_dir=run_kwargs.get("gpx_dir"),  # type: ignore[arg-type]
        save=bool(run_kwargs.get("save_gpx", True)),
    )

    raw: list[ModelScore] = []
    for v in variants:
        with gpx_context(group.child(role="model", label=v.name)):
            result = runner(list(histograms), list(v.phases), **run_kwargs)
        metrics = metrics_from_result(result)
        raw.append(
            ModelScore(
                name=v.name,
                rwp=metrics.rwp,
                gof=metrics.gof,
                n_obs=metrics.n_obs,
                n_params=metrics.n_params,
                chi2=metrics.chi2,
                bic=bic_backend.score(metrics).value,
                aic=aic_backend.score(metrics).value,
                validity_passed=result.validity.passed,
                phase_fractions=dict(result.phase_fractions),
                warnings=tuple(result.validity.warnings),
            )
        )

    best_bic = min(s.bic for s in raw)  # ΔBIC 基準 (全体最小 BIC, 情報量規準)
    # 選定は「BIC + 物理妥当性」: 妥当なモデルのうち最小 BIC を採る。妥当なモデルが無ければ
    # 全体最小 BIC にフォールバック (best_is_valid=False で呼び出し側に警告)。
    valid = [s for s in raw if s.validity_passed]
    pool = valid if valid else raw
    best_score = min(pool, key=lambda s: s.bic)
    best = best_score.name
    best_is_valid = bool(valid)
    scored = tuple(
        ModelScore(
            name=s.name,
            rwp=s.rwp,
            gof=s.gof,
            n_obs=s.n_obs,
            n_params=s.n_params,
            chi2=s.chi2,
            bic=s.bic,
            aic=s.aic,
            validity_passed=s.validity_passed,
            phase_fractions=s.phase_fractions,
            delta_bic=s.bic - best_bic,
            warnings=s.warnings,
        )
        for s in sorted(raw, key=lambda s: s.bic)
    )
    return ModelComparison(scores=scored, best=best, best_is_valid=best_is_valid)
