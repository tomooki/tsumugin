"""薄い MCP 3 ツール (M8 要素3) — 実構造自動 Rietveld の計器+アクチュエータ。

閉ループの丸ごと (agentic_analyze) は **出さない**。③ (Claude Code) が以下を反復駆動して回す
(architecture.md §0, §6, 二重反転回避):

- ``auto_rietveld``: spec (JSON) を run_auto_rietveld で実行 → 段階別/最終 Rwp・格子・validity・
  **残差レポート**・**出版値** (重量分率 ± esd・格子 esd) を構造化して返す。spec ハンドルは
  stateless echo (サーバ状態なし)。残差配列
  (実データで 2392 点 × 3 本 ≈ 150KB) は跨がせず、小さなレポートのみサーバ側で算出して同梱する
  (operando 診断 ②, docs/design/operando-diagnosis/architecture.md §2)。
  ⚠ **``phase_weight_fractions`` が定量相分析の出版値**であり ``phase_fractions`` (Scale) ではない。
- ``propose_next_actions``: 直前結果 + 残差シグネチャ → ActionProposal[] (rationale/priority/**safe**)。
- ``refine_with_revisions``: spec + ③ が決めた AnalysisAction[] を適用して再実行。

**SDK 非依存**: 素の型 dict のみを返す (json.dumps allow_nan=False 安全)。GSAS は runner 内で遅延
import。runner は注入可能 (既定 GSAS 駆動; テストは決定論スタブ)。

信頼性: 🔵 architecture.md §6 の 3 ツール表と 1:1。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import AutoRietveldResult, HistogramSpec, PhaseSpec, ValidityReport
from ..refine_loop.action import AnalysisInput
from ..refine_loop.diagnostics import propose_next_actions as _propose
from ..refine_loop.orchestrator import _default_gsas_runner
from ..refine_loop.serialization import (
    action_from_dict,
    features_from_dicts,
    proposal_to_dict,
)
from .operando_diag_tools import residual_report_to_dict

Runner = Callable[[AnalysisInput], AutoRietveldResult]

__all__ = [
    "RIETVELD_TOOLS",
    "auto_rietveld",
    "propose_next_actions",
    "refine_with_revisions",
]


def _specs_dict(inp: AnalysisInput) -> dict[str, object]:
    """spec ハンドル (stateless echo): ③ が refine_with_revisions へ差し戻すための往復可能な spec。"""
    return {
        "histograms": [h.to_dict() for h in inp.histograms],
        "phases": [p.to_dict() for p in inp.phases],
        "background_coeffs": inp.background_coeffs,
    }


def _residual_report_dict(result: AutoRietveldResult) -> dict[str, object] | None:
    """精密化結果から残差レポートを**サーバ側で**算出し素の型 dict で返す (None = 残差なし)。

    【配列を跨がせない】: ``residual_two_theta``/``residual_intensity``/``residual_sigma`` は実データで
      2392 点 × 3 本 ≈ 150KB あり、MCP 境界を跨がせるべきでない。一方レポートは数個の float +
      ~6 特徴と小さいため、ここで算出して同梱する。これにより ③ (MCP しか触れない skill) が
      残差診断 (J2/J3: 未説明ピーク → 欠落相/対称性低下) を**再精密化なしに**行える
      (architecture.md §2 の ``residual_report`` 行)。
    【縮退】: ``residual_report_from_result`` は残差フィールドが空/長さ不一致/全点非有限のとき
      None を返す (後方互換の既定は空タプル = スタブ runner や旧構築)。その場合は None を返し、
      呼び出し側が ``"residual_report": None`` として出す (キーは常に存在させスキーマを安定させる)。
    """
    from ..autorietveld.residual_report import residual_report_from_result

    rep = residual_report_from_result(result)
    if rep is None:
        return None
    return residual_report_to_dict(rep)


def _result_to_dict(result: AutoRietveldResult, inp: AnalysisInput) -> dict[str, object]:
    """AutoRietveldResult + spec を素の型 dict へ (③ の判断入力)。"""
    return {
        "specs": _specs_dict(inp),
        "final_rwp": finite_or_none(result.final_rwp),
        "final_gof": finite_or_none(result.final_gof),
        "n_obs": result.n_obs,
        "stages": [
            {
                "label": s.label,
                "rwp": finite_or_none(s.rwp),
                "gof": finite_or_none(s.gof),
                "n_params": s.n_params,
                "converged": bool(s.converged),
                "reverted": bool(s.reverted),
            }
            for s in result.stage_results
        ],
        "refined_cells": {
            # 発散/崩壊した精密化で GSAS が NaN/Inf セルを返しうるため finite_or_none で None 化
            # (allow_nan=False の json.dumps クラッシュを防ぐ; 他フィールドと同一規律)。
            name: [finite_or_none(x) for x in cell] for name, cell in result.refined_cells.items()
        },
        "validity": {
            "passed": bool(result.validity.passed),
            "checks": [[name, bool(ok), detail] for name, ok, detail in result.validity.checks],
            "warnings": list(result.validity.warnings),
        },
        # 【残差レポート同梱 (operando 診断 ②)】: 大きな残差配列は跨がせず、小さなレポートのみを
        #   サーバ側で算出して返す。残差フィールドが空 (既定/スタブ) なら None (キーは常に存在) 🔵
        "residual_report": _residual_report_dict(result),
        # 【出版値 (Issue #96 レビュー)】: `phase_fractions` は **Scale** であって重量分率ではない。
        #   単位胞質量が相間で異なると乖離する (実測 K2Mn[Fe(CN)6] cubic 1103.4 / tetra 517.8 amu →
        #   47.2 wt% vs 65.6 Scale% で **2.1x**)。定量相分析の出版値は重量分率であり、esd を伴わない
        #   精密化値は出版できない。① にあっても ② に無ければ ③ は受け取れない (★ 規則)。
        #   キーは常に存在させる (欠落と「esd=0」を ③ が取り違えないため; residual_report と同一規律)。
        "phase_weight_fractions": {
            name: finite_or_none(v) for name, v in result.phase_weight_fractions.items()
        },
        "phase_weight_fraction_esd": {
            name: finite_or_none(v) for name, v in result.phase_weight_fraction_esd.items()
        },
        "cell_esd": {
            name: [finite_or_none(x) for x in esd] for name, esd in result.cell_esd.items()
        },
        "gpx_path": result.gpx_path,
    }


def _result_from_dict(result: Mapping[str, object]) -> AutoRietveldResult:
    """propose_next_actions が使う最小フィールドで AutoRietveldResult を復元する。"""
    v = result.get("validity") or {}
    validity = ValidityReport(
        passed=bool(v.get("passed", True)),
        checks=tuple(
            (str(name), bool(ok), str(detail)) for name, ok, detail in v.get("checks", ())
        ),
        warnings=tuple(str(w) for w in v.get("warnings", ())),
    )
    cells = {
        name: tuple(float(x) for x in cell)
        for name, cell in (result.get("refined_cells") or {}).items()
    }
    rwp = result.get("final_rwp")
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=float(rwp) if rwp is not None else float("inf"),
        final_gof=float(result.get("final_gof") or 0.0),
        refined_cells=cells,
        validity=validity,
        n_obs=int(result.get("n_obs") or 0),
    )


def _build_input(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    background_coeffs: int,
) -> AnalysisInput:
    return AnalysisInput(
        histograms=tuple(HistogramSpec.from_dict(h) for h in histograms),
        phases=tuple(PhaseSpec.from_dict(p) for p in phases),
        background_coeffs=background_coeffs,
    )


def auto_rietveld(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    *,
    background_coeffs: int = 6,
    seed: int = 0,
    runner: Runner | None = None,
) -> dict:
    """spec (JSON) を run_auto_rietveld で実行し段階別/最終メトリクスを構造化して返す (計器)。

    :param histograms: HistogramSpec.to_dict の列
    :param phases: PhaseSpec.to_dict の列
    :param background_coeffs: 初期背景係数数
    :param seed: 既定 GSAS runner 用乱数種
    :param runner: 注入 runner (None なら GSAS 駆動)。テスト用の内部シーム
    """
    inp = _build_input(histograms, phases, background_coeffs)
    run = runner or _default_gsas_runner(seed)
    return _result_to_dict(run(inp), inp)


def propose_next_actions(
    result: Mapping[str, object], features: Sequence[Mapping[str, object]]
) -> dict:
    """直前結果 + 残差シグネチャから次手候補を返す (計器・提案のみ)。

    :param result: auto_rietveld / refine_with_revisions の出力
    :param features: ResidualFeatures 相当の dict 列 (③ or 別ツールが供給)
    """
    reconstructed = _result_from_dict(result)
    feats = features_from_dicts(features)
    proposals = _propose(reconstructed, feats)
    return {"proposals": [proposal_to_dict(p) for p in proposals]}


def refine_with_revisions(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    actions: Sequence[Mapping[str, object]],
    *,
    background_coeffs: int = 6,
    seed: int = 0,
    runner: Runner | None = None,
) -> dict:
    """③ が決めた AnalysisAction[] を spec に適用して再実行する (アクチュエータ)。

    SafeAction (背景/パラメータ) も ModelAction (リミット/相追加/構造改訂) も適用できる。
    採否の判断は ③ が済ませた前提 (このツールは適用+再実行のみ)。
    """
    inp = _build_input(histograms, phases, background_coeffs)
    for a in actions:
        inp = action_from_dict(a).apply(inp)
    run = runner or _default_gsas_runner(seed)
    return _result_to_dict(run(inp), inp)


# 【ツールレジストリ断片】: tools.py の MCP_TOOLS へ合流する 3 ツール (要素3)。
RIETVELD_TOOLS: Mapping[str, object] = {
    "auto_rietveld": auto_rietveld,
    "propose_next_actions": propose_next_actions,
    "refine_with_revisions": refine_with_revisions,
}
