"""M8: 決定論オーケストレータ — run_refinement_loop (観測→規則判断→適用→再実行)。

各反復で `run_auto_rietveld` を実行し、`propose_next_actions` で次手候補を得て `AnalysisPolicy`
(既定 RuleBasedPolicy) に判断させる。SafeAction は適用して再実行し、**受理基準 (Rwp 改善 ∧
ValidityReport.passed 維持)** を満たさなければ棄却して可逆に記録する (過剰適合ガード, §4.4)。
ModelAction は適用せず `open_proposals` に申し送る (③/人間へ)。全反復を ledger に追記する。

runner / diagnose は注入可能 (既定は GSAS 駆動)。純テストは決定論スタブを注入する (§12)。
RuleBasedPolicy + 同一入力でループはビット同一 (NFR-102)、ledger は verify() True (NFR-105)。

信頼性: 🔵 architecture.md §3.3, §4.4。コア numpy-only (GSAS は runner 内で遅延 import)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from tsumugin.autorietveld import AutoRietveldResult, HistogramSpec, PhaseSpec
from .action import AnalysisInput, Stop
from .diagnose_residual import diagnose_residual
from .diagnostics import ActionProposal, ResidualFeatures, propose_next_actions
from .policy import (
    AnalysisPolicy,
    AnalysisState,
    AnalysisStep,
    PolicyBudget,
    RuleBasedPolicy,
)

Runner = Callable[[AnalysisInput], AutoRietveldResult]
Diagnose = Callable[[AutoRietveldResult, AnalysisInput], Sequence[ResidualFeatures]]


@dataclass(frozen=True)
class RefinementLoopResult:
    """閉ループの結果。

    :param best: 最良の結果 = ベースライン or 受理された候補のうち最小 Rwp。受理候補は
        validity.passed が保証される (過剰適合ガード) が、**ベースラインが validity 不合格でも
        改善する safe 手が無ければ best はそのベースライン**になる。validity の修復は構造改訂等の
        ModelAction が要るため ``open_proposals`` として ③/人間に申し送られる (規則は担わない)。
    :param steps: 反復記録 (採用/棄却)
    :param open_proposals: 未適用の ModelAction 提案 (③/人間への申し送り)
    :param iterations: 実行反復数
    :param ledger: 追記された台帳 (None なら未使用)
    """

    best: AutoRietveldResult
    steps: tuple[AnalysisStep, ...]
    open_proposals: tuple[ActionProposal, ...]
    iterations: int
    ledger: object | None = None


def _accept(prev: AutoRietveldResult, cand: AutoRietveldResult, eps: float) -> bool:
    """受理基準: Rwp 改善 ∧ validity 維持 (過剰適合ガード, §4.4)。"""
    if not cand.validity.passed:
        return False
    return cand.final_rwp < prev.final_rwp - eps


def run_refinement_loop(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    policy: AnalysisPolicy | None = None,
    runner: Runner | None = None,
    diagnose: Diagnose | None = None,
    background_coeffs: int = 6,
    budget: PolicyBudget | None = None,
    ledger: object | None = None,
    accept_eps: float = 1e-6,
    seed: int = 0,
) -> RefinementLoopResult:
    """観測→規則判断→適用→再実行の決定論ループを回す (§3.3)。

    :param histograms: 観測ヒストグラム仕様
    :param phases: 相仕様
    :param policy: 判断ポリシー (既定 RuleBasedPolicy)
    :param runner: (AnalysisInput)->結果。None なら GSAS 駆動 run_auto_rietveld
    :param diagnose: (結果, 入力)->残差シグネチャ。None なら結果ベースの粗診断
    :param background_coeffs: 初期背景係数数
    :param budget: 停止条件 (既定 PolicyBudget())
    :param ledger: 追記台帳 (None なら未使用)
    :param accept_eps: Rwp 改善判定の下限
    :param seed: GSAS runner 用の乱数種 (再現性)
    """
    policy = policy or RuleBasedPolicy()
    budget = budget or PolicyBudget()
    if runner is None:
        runner = _default_gsas_runner(seed)
    if diagnose is None:
        # 既定は残差解析診断 (REQ-002/TASK-0009)。背景のみの粗診断 _default_diagnose は
        # 後方互換の代替として残置 (明示注入で選択可)。
        diagnose = diagnose_residual

    inp = AnalysisInput(tuple(histograms), tuple(phases), background_coeffs)
    result = runner(inp)  # ベースライン (反復 0)
    best = result
    steps: list[AnalysisStep] = []
    open_proposals: tuple[ActionProposal, ...] = ()

    if ledger is not None:
        ledger.append(
            "refine_loop_baseline",
            {"rwp": result.final_rwp, "gof": result.final_gof, "validity": result.validity.passed},
        )

    iteration = 0
    while True:
        features = diagnose(result, inp)
        proposals = propose_next_actions(result, features)
        state = AnalysisState(result, proposals, tuple(steps), iteration, budget)
        action = policy.decide(state)

        if isinstance(action, Stop):
            open_proposals = tuple(p for p in proposals if not p.safe)
            if ledger is not None:
                ledger.append("refine_loop_stop", {"reason": action.reason, "iteration": iteration})
            break

        candidate_inp = action.apply(inp)
        candidate = runner(candidate_inp)
        accepted = _accept(result, candidate, accept_eps)
        steps.append(AnalysisStep(iteration, action, candidate.final_rwp, accepted))
        if ledger is not None:
            ledger.append(
                "refine_loop_step",
                {
                    "iteration": iteration,
                    "action": type(action).__name__,
                    "rwp": candidate.final_rwp,
                    "accepted": accepted,
                },
            )
        if accepted:
            inp = candidate_inp
            result = candidate
            # best は受理済み候補 (いずれも _accept で eps 超の改善済み) の生の最小 Rwp を追う。
            if candidate.final_rwp < best.final_rwp:
                best = candidate
        # 棄却時は inp/result を据え置き (revert)。policy が既試行 Action を再選択しないため終了する。
        iteration += 1

    return RefinementLoopResult(
        best=best,
        steps=tuple(steps),
        open_proposals=open_proposals,
        iterations=iteration,
        ledger=ledger,
    )


# ---------------- 既定の GSAS 駆動 runner / 粗診断 ----------------


def _default_gsas_runner(seed: int) -> Runner:
    """AnalysisInput を run_auto_rietveld で実行する既定 runner (GSAS 遅延 import)。"""

    def runner(inp: AnalysisInput) -> AutoRietveldResult:
        from tsumugin.autorietveld import build_recipe, run_auto_rietveld

        recipe = build_recipe(
            inp.histograms, inp.phases, background_coeffs=inp.background_coeffs
        )
        recipe = (*recipe, *inp.extra_stages)
        return run_auto_rietveld(list(inp.histograms), list(inp.phases), recipe=recipe)

    return runner


def _default_diagnose(
    result: AutoRietveldResult, inp: AnalysisInput
) -> Sequence[ResidualFeatures]:
    """結果ベースの粗診断 (残差配列非依存): Rwp が高く背景が上限未満なら背景増項を促す。

    残差配列を用いた精密な診断 (FWHM 比・未指数ピーク) は richer diagnose を注入して差し替える。
    既定は M7 教訓「背景項数不足で平坦」の自動化に足る最小ヒューリスティクス。背景は全域スカラー
    のため 1 特徴のみ返す。
    """
    bg_residual = 0.0
    if inp.background_coeffs < 12 and result.final_rwp > 8.0:
        bg_residual = min(1.0, (result.final_rwp - 8.0) / 30.0)
    return [
        ResidualFeatures(
            hist_id=0,
            low_freq_bg_residual=bg_residual,
            n_background_coeffs=inp.background_coeffs,
        )
    ]
