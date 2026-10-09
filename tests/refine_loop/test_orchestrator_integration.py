"""orchestrator × diagnose_residual 統合 (REQ-201/402/403, TASK-0009) の決定論テスト。

既定 diagnose を diagnose_residual に差し替えた閉ループが、拡張シグナルで新 SafeAction を
試行し accept/revert する・決定論である・ModelAction を open_proposals へ回すことを確認する。
"""

from __future__ import annotations

import dataclasses

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.action import AddPhase, ReleaseParams, RestrictUiso
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


def test_uiso_restriction_in_a_multiphase_loop_stays_within_each_phase():
    """多相で Uiso が 1 相だけ発散 → 限定はその相の原子だけで張られ、凍結相は凍結のまま。

    以前は全相のラベルを混ぜた 1 つの RestrictUiso が全相に掛かり、(1) 各相が他相の
    ラベルを抱える (GSAS は ``No such atom`` で uiso 段を revert = Uiso が 1 つも精密化
    されない) (2) ``free_uiso_labels=()`` の凍結相が解除される、の 2 つが同時に起きていた。
    """
    atoms = {"PbSO4": ("Pb", "S", "O1"), "CaF2": ("Ca", "O1")}  # O1 は両相に居る
    phases = [PhaseSpec("pbso4.cif", "PbSO4"),
              PhaseSpec("caf2.cif", "CaF2", free_uiso_labels=())]
    seen: list[tuple[PhaseSpec, ...]] = []

    def runner(inp):
        seen.append(inp.phases)
        pb = next(p for p in inp.phases if p.phase_name == "PbSO4")
        o1_free = pb.free_uiso_labels is None or "O1" in pb.free_uiso_labels
        res = _res(10.0 if not o1_free else 12.0)
        uiso = {
            "PbSO4": {"Pb": 0.01, "S": 0.01, "O1": 0.9 if o1_free else 0.02},
            # 凍結相の Ca は初期値 (CIF 由来) が範囲外 = 発散と判定されるが、解放されていない。
            "CaF2": {"Ca": 0.7, "O1": 0.02},
        }
        return dataclasses.replace(res, atom_uiso=uiso)

    res = run_refinement_loop(_H, phases, runner=runner)

    accepted = [s.action for s in res.steps if s.accepted]
    assert accepted == [RestrictUiso(("Pb", "S"), phase="PbSO4")]
    assert res.best.final_rwp == 10.0
    for inp_phases in seen:
        for p in inp_phases:
            if p.free_uiso_labels is not None:
                assert set(p.free_uiso_labels) <= set(atoms[p.phase_name]), p
        assert next(p for p in inp_phases if p.phase_name == "CaF2").free_uiso_labels == ()
