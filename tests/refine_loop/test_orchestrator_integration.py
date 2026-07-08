"""orchestrator × diagnose_residual 統合 (REQ-201/402/403, TASK-0009) の決定論テスト。

既定 diagnose を diagnose_residual に差し替えた閉ループが、拡張シグナルで新 SafeAction を
試行し accept/revert する・決定論である・ModelAction を open_proposals へ回すことを確認する。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.action import AddPhase, ReleaseParams
from tsumugin.refine_loop.diagnostics import ResidualFeatures
from tsumugin.refine_loop.orchestrator import run_refinement_loop

_H = [HistogramSpec("d.xye", "i.instprm", radiation=Radiation.XRAY_SYNCHROTRON,
                    geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")]
_P = [PhaseSpec("p.cif", "P1")]


def _res(rwp: float, *, asym: float = 0.0, valid: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=rwp, gof=1.2, n_params=8, converged=True),),
        final_rwp=rwp, final_gof=1.2, refined_cells={"P1": (5.0,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=valid),
        asymmetry_metric=(asym,),
    )


def _asymmetry_runner(inp):
    # 追加段が入る (ReleaseParams 適用後) と Rwp 改善 + 非対称解消。
    if inp.extra_stages:
        return _res(10.0, asym=0.0)
    return _res(15.0, asym=0.3)


def test_default_diagnose_triggers_and_accepts_safe_action():
    # 既定 (diagnose_residual) で非対称シグナル → ReleaseParams が試行され改善で採用 (REQ-201)。
    res = run_refinement_loop(_H, _P, runner=_asymmetry_runner)
    assert res.best.final_rwp == 10.0
    accepted = [s for s in res.steps if s.accepted]
    assert accepted, "少なくとも 1 つの SafeAction が採用されるはず"
    assert isinstance(accepted[0].action, ReleaseParams)
    assert accepted[0].action.label in ("xray_zero", "xray_asymmetry")


def test_loop_is_deterministic():
    a = run_refinement_loop(_H, _P, runner=_asymmetry_runner)
    b = run_refinement_loop(_H, _P, runner=_asymmetry_runner)
    assert [(type(s.action).__name__, s.accepted) for s in a.steps] == \
           [(type(s.action).__name__, s.accepted) for s in b.steps]
    assert a.best.final_rwp == b.best.final_rwp


def test_reverts_when_worse():
    # 適用しても改善しない runner → revert され best はベースライン (REQ-201)。
    def worse_runner(inp):
        if inp.extra_stages:
            return _res(15.0, asym=0.3)  # 改善しない (同じ Rwp)、非対称も残る
        return _res(15.0, asym=0.3)

    res = run_refinement_loop(_H, _P, runner=worse_runner)
    assert res.best.final_rwp == 15.0
    assert all(not s.accepted for s in res.steps)  # すべて棄却/revert


def test_model_action_routed_to_open_proposals():
    # ModelAction (相追加) は自律適用されず open_proposals へ (REQ-403)。
    def diag(result, inp):
        return [ResidualFeatures(hist_id=0, unindexed_peak_frac=0.3)]

    res = run_refinement_loop(_H, _P, runner=lambda inp: _res(15.0), diagnose=diag)
    assert any(isinstance(p.action, AddPhase) for p in res.open_proposals)
    # 相は増えていない (適用されていない)。
    assert all(not s.accepted or not isinstance(s.action, AddPhase) for s in res.steps)
