"""TASK-0804: refine_loop.orchestrator — run_refinement_loop (観測→規則判断→適用→再実行)。

受理基準 (Rwp 改善 ∧ validity 維持) を満たす safe 手のみ採用、棄却は可逆記録。ModelAction は
open_proposals に申し送り。ledger 追記 + 決定論 (architecture.md §3.3, §4.4)。純テスト (stub runner)。
"""

from __future__ import annotations

from tsumugin.autorietveld import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.refine_loop.action import AnalysisInput
from tsumugin.refine_loop.diagnostics import ResidualFeatures
from tsumugin.refine_loop.orchestrator import RefinementLoopResult, run_refinement_loop
from tsumugin.refine_loop.policy import PolicyBudget
from tsumugin.store.ledger import Ledger


def _mk_result(rwp: float, *, passed: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=rwp, gof=1.0, n_params=8, converged=True),),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=passed),
    )


_H = ()  # ヒストグラム/相はスタブ runner では未使用 (空で可)
_P = ()


def _improving_runner(inp: AnalysisInput) -> AutoRietveldResult:
    """背景係数が増えるほど Rwp が下がるスタブ (30 - coeffs)。"""
    return _mk_result(30.0 - float(inp.background_coeffs))


def _bg_diagnose(result, inp):
    """Rwp が高く背景が上限未満なら背景増項を提案する diagnose スタブ。"""
    if result.final_rwp > 12.0 and inp.background_coeffs < 12:
        return [ResidualFeatures(hist_id=0, low_freq_bg_residual=0.5,
                                 n_background_coeffs=inp.background_coeffs)]
    return [ResidualFeatures(hist_id=0)]  # クリーン


def _run(**kw):
    base = dict(
        histograms=_H, phases=_P, runner=_improving_runner, diagnose=_bg_diagnose,
        budget=PolicyBudget(max_iterations=8, target_rwp=None),
    )
    base.update(kw)
    return run_refinement_loop(**base)


def test_loop_applies_safe_actions_and_improves():
    res = _run()
    assert isinstance(res, RefinementLoopResult)
    # 背景 6→9→12 で Rwp 24→21→18、以降クリーン提案で停止
    assert res.best.final_rwp <= 18.0
    assert all(s.accepted for s in res.steps)
    assert res.steps, "少なくとも 1 手適用"


def test_rejected_action_does_not_worsen_best():
    # 背景を増やすと悪化する runner → 適用は棄却され best は初期のまま
    def worsening_runner(inp):
        return _mk_result(10.0 + float(inp.background_coeffs))  # coeffs↑ で悪化

    res = _run(runner=worsening_runner)
    assert res.best.final_rwp == 16.0  # 初期 background_coeffs=6 → 10+6
    assert res.steps and not res.steps[0].accepted  # 棄却記録


def test_validity_breaking_action_is_rejected():
    # Rwp は下がるが validity を壊す手は過剰適合として棄却
    def overfit_runner(inp):
        rwp = 30.0 - float(inp.background_coeffs)
        passed = inp.background_coeffs <= 6  # 増項で validity 崩れる
        return _mk_result(rwp, passed=passed)

    res = _run(runner=overfit_runner)
    assert res.best.validity.passed
    assert res.best.final_rwp == 24.0  # 初期のみ採用
    assert any(not s.accepted for s in res.steps)


def test_model_action_proposals_go_to_open_proposals():
    def diagnose_with_unindexed(result, inp):
        return [ResidualFeatures(hist_id=0, unindexed_peak_frac=0.3)]  # ModelAction 提案

    res = _run(diagnose=diagnose_with_unindexed)
    assert res.open_proposals, "未適用 ModelAction は ③ へ申し送り"
    assert all(not p.safe for p in res.open_proposals)


def test_target_rwp_stops_early():
    res = _run(budget=PolicyBudget(max_iterations=8, target_rwp=22.0))
    # 6→9 で Rwp 21 <= 22 到達 → それ以上増やさない
    assert res.best.final_rwp <= 22.0
    assert len(res.steps) <= 2


def test_ledger_is_appended_and_verifies():
    ledger = Ledger()
    res = _run(ledger=ledger)
    assert ledger.verify()
    assert len(ledger.entries) >= 1
    assert res.ledger is ledger


def test_deterministic_bitwise_identical():
    a = _run()
    b = _run()
    assert [(s.iteration, type(s.action).__name__, s.result_rwp, s.accepted) for s in a.steps] == [
        (s.iteration, type(s.action).__name__, s.result_rwp, s.accepted) for s in b.steps
    ]
    assert a.best.final_rwp == b.best.final_rwp


def test_open_proposals_empty_and_terminates_when_clean():
    res = _run(diagnose=lambda result, inp: [ResidualFeatures(hist_id=0)])
    assert res.steps == ()  # 提案なし → 即停止
    assert res.open_proposals == ()
