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
from ..autorietveld import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    StabilityOptions,
    ValidityReport,
)
from ._degrade import degrade_oserror
from ._recipe_spec import stage_to_dict, stages_from_dicts
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
    """spec ハンドル (stateless echo): ③ が refine_with_revisions へ差し戻すための往復可能な spec。

    ``stages`` (Issue #101: ③ が渡した追加段階 = ``AnalysisInput.extra_stages``) も同梱する —
    背景係数と同じく、渡した spec がそのまま往復できないと ③ は次呼び出しで追加段階を失う。
    """
    return {
        "histograms": [h.to_dict() for h in inp.histograms],
        "phases": [p.to_dict() for p in inp.phases],
        "background_coeffs": inp.background_coeffs,
        "stages": [stage_to_dict(s) for s in inp.extra_stages],
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
                # 【note を落とさない (★ ②到達可能性)】: 段の所見 (``unconverged`` /
                #   ``noop`` / ``pruned=N`` / ``bound_hits=N`` / ``auto_frozen_cells=…``) は
                #   **ここにしか出ない**。ledger は ② の戻り値に含まれないので、note を落とすと
                #   ③ から見て診断ゲートも箱拘束も「結果に何も現れない」機能になる。
                "note": s.note,
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
        #   単位胞質量が相間で異なると乖離する (実測 K2Mn[Fe(CN)6] tetra: 同じ fit で 65.6 Scale%
        #   が 47.2 wt%。乖離はフレーム毎に違い [実測 1.39-1.62 倍]、大きさは単位胞質量比
        #   [cubic 1103.4 / tetra 517.8 amu = 2.13 倍] と分率で決まる = **換算係数は無い**)。
        #   定量相分析の出版値は重量分率であり、esd を伴わない
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
    extra_stages: Sequence[Mapping[str, object]] | None = None,
) -> AnalysisInput:
    """spec (JSON) を `AnalysisInput` へ変換する。

    :param extra_stages: 段階解放レシピの追加段階 spec (Issue #101: ``AnalysisInput.extra_stages``
        への到達口)。不正な段階 spec は `stages_from_dicts` が ``ValueError`` を送出する
        (呼び出し側が error dict へ縮退する)。
    """
    return AnalysisInput(
        histograms=tuple(HistogramSpec.from_dict(h) for h in histograms),
        phases=tuple(PhaseSpec.from_dict(p) for p in phases),
        background_coeffs=background_coeffs,
        extra_stages=stages_from_dicts(extra_stages),
    )


@degrade_oserror
def auto_rietveld(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    *,
    background_coeffs: int = 6,
    stages: Sequence[Mapping[str, object]] | None = None,
    max_cyc: int = 12,
    stability: Mapping[str, object] | None = None,
    seed: int = 0,
    runner: Runner | None = None,
) -> dict:
    """spec (JSON) を run_auto_rietveld で実行し段階別/最終メトリクスを構造化して返す (計器)。

    :param histograms: HistogramSpec.to_dict の列
    :param phases: PhaseSpec.to_dict の列
    :param background_coeffs: 初期背景係数数
    :param stages: **段階解放レシピの追加段階** (Issue #101)。``build_recipe`` が生成する既定
        レシピの末尾に追加される (``AnalysisInput.extra_stages`` と同じ意味論)。各要素は
        ``{"label": str, "flags": {GSAS 語彙}, "note": str (省略可)}``
        (語彙は ``autorietveld.recipe`` docstring 参照: ``profile_lorentzian``/``tof_profile``/
        ``size_strain``/``preferred_orientation``/``absorption`` 等)。不正なキー/型は
        ``{"error","error_type"}`` へ縮退する (黙って無視しない)。既定 None (追加段階なし・非回帰)。
    :param max_cyc: 各段階の最大精密化サイクル (``run_auto_rietveld`` へ転送。既定 12 は非回帰)。
        ``runner`` を明示注入した場合はそちらの責務になり本引数は無視される。
    :param stability: **安定性診断ゲート + 箱拘束** (stable-auto-rietveld)。
        診断 (WS-1): ``{"require_convergence": true, "max_shift_esd": 1.0, "extra_cycles": 1,
        "detect_noop_stages": true, "prune_weak_vars": true, "record_correlations": true}``。
        収束判定 (未収束段を追加サイクル → 駄目なら revert) / no-op 段の警告 / esd >= |値| の
        自動凍結 / 高相関ペアの記録を opt-in で有効化する。
        拘束 (WS-2): ``{"bound_cell": 0.05, "bound_displacement": 5000.0,
        "bound_size_strain": true, "enable_restraints": true}``。**装置・幾何パラメータだけ**に
        箱拘束 (格子 ±X% / 試料変位 µm / Size・Mustrain の正値性) を張り、境界に到達したら
        所見にする (握り潰さない)。⚠ **占有率・Uiso・座標には箱を張らない** — 異常値はモデル
        誤りの診断信号であり、握り潰すと NaCuHCF model5/model6 のような判別ができなくなる
        (そのためのキーは存在しない)。``enable_restraints`` は登録済み restraint
        (``bond_restraints``/``chem_comp_restraints``) を χ² に入れる (既定 OFF — GSAS-II は
        headless では penalty を目的関数から外すため、有効にしない限り拘束は効かない)。
        ⚠ **``prune_weak_vars`` との併用が必須**で、単独指定は error dict になる。
        ⚠ 有効化すると **Rwp が penalty を含む値**に変わるため、拘束の重みは
        データ項と同程度に抑えること (過大な重みは全段が「悪化」と判定され revert される)。
        判定結果は ledger (``m7_stage_unconverged``/``m7_stage_noop``/``m7_stage_prune``/
        ``m7_stage_correlation``/``m7_box_bounds``/``m7_stage_bound_hit``) と ``stages[*].note``
        (``unconverged``/``noop``/``pruned=N``/``bound_hits=N``) に出る。
        **未知キーは error dict へ縮退**する (黙って無視しない)。
        既定 None = 現行と同一挙動 (共分散も Controls も触らない)。``runner`` 注入時は無視される。
    :param seed: 既定 GSAS runner 用乱数種
    :param runner: 注入 runner (None なら GSAS 駆動)。テスト用の内部シーム
    """
    try:
        inp = _build_input(histograms, phases, background_coeffs, stages)
        opts = StabilityOptions.from_dict(stability)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    run = runner or _default_gsas_runner(seed, max_cyc=max_cyc, stability=opts)
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


@degrade_oserror
def refine_with_revisions(
    histograms: Sequence[Mapping[str, object]],
    phases: Sequence[Mapping[str, object]],
    actions: Sequence[Mapping[str, object]],
    *,
    background_coeffs: int = 6,
    stages: Sequence[Mapping[str, object]] | None = None,
    max_cyc: int = 12,
    stability: Mapping[str, object] | None = None,
    seed: int = 0,
    runner: Runner | None = None,
) -> dict:
    """③ が決めた AnalysisAction[] を spec に適用して再実行する (アクチュエータ)。

    SafeAction (背景/パラメータ) も ModelAction (リミット/相追加/構造改訂) も適用できる。
    採否の判断は ③ が済ませた前提 (このツールは適用+再実行のみ)。

    :param stages: `auto_rietveld` と同じ意味論の追加段階 spec (Issue #101)。``ReleaseParams``
        action が足す段階 (`AnalysisAction.apply` 経由) と共存する。合成順は
        **``stages`` が先 (既定レシピ直後) → action 由来の段階が末尾**
        (`_build_input` が stages を extra_stages に置いた後、actions ループが apply で末尾に足す)。
        不正な段階 spec は error dict へ縮退する。
    :param max_cyc: `auto_rietveld` と同じ (既定 GSAS runner への転送)。
    :param stability: `auto_rietveld` と同じ安定性診断ゲート + 箱拘束 spec (既定 None = 非回帰)。
        箱拘束 (``bound_cell``/``bound_displacement``/``bound_size_strain``) と restraint 有効化
        (``enable_restraints``, 要 ``prune_weak_vars``) も同じキーで到達できる。
    """
    try:
        inp = _build_input(histograms, phases, background_coeffs, stages)
        for a in actions:
            inp = action_from_dict(a).apply(inp)
        opts = StabilityOptions.from_dict(stability)
    except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    run = runner or _default_gsas_runner(seed, max_cyc=max_cyc, stability=opts)
    return _result_to_dict(run(inp), inp)


# 【ツールレジストリ断片】: tools.py の MCP_TOOLS へ合流する 3 ツール (要素3)。
RIETVELD_TOOLS: Mapping[str, object] = {
    "auto_rietveld": auto_rietveld,
    "propose_next_actions": propose_next_actions,
    "refine_with_revisions": refine_with_revisions,
}
