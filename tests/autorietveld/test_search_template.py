"""fit-then-judge P1-1B タスク 7: 候補 ``"template"`` を探索・収束確認に載せる (REQ-FTJ-1B-501〜504)。"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tsumugin.autorietveld import search as search_mod
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.search import RecipeCandidate, build_candidates, run_recipe_search
from tsumugin.store import Ledger
from tsumugin.template.declarations import TemplateDeclarations, TemplateScopeError

N_OBS = 1000


def _hist(radiation=Radiation.XRAY_LAB) -> HistogramSpec:
    return HistogramSpec(
        data_path="d.xye", instrument_path="i.instprm",
        radiation=radiation, geometry=Geometry.BRAGG_BRENTANO,
    )


A = PhaseSpec("a.cif", "A")
B = PhaseSpec("b.cif", "B")


def _result(stages, phases, rwp=9.0) -> AutoRietveldResult:
    out = tuple(
        StageResult(st.label, rwp, 1.0 + 0.01 * i, 5 + i, True) for i, st in enumerate(stages)
    )
    resid = np.random.default_rng(0).standard_normal(200)
    return AutoRietveldResult(
        stage_results=out, final_rwp=rwp, final_gof=out[-1].gof, refined_cells={},
        validity=ValidityReport(passed=True), n_obs=N_OBS,
        residual_intensity=tuple(map(float, resid)), residual_sigma=(1.0,) * 200,
        atom_uiso={p.phase_name: {f"{p.phase_name}1": 0.01} for p in phases},
        phase_integrated_intensity={p.phase_name: (100.0 / (i + 1),) for i, p in enumerate(phases)},
    )


class Pass1Fake:
    def __init__(self, fail=False):
        self.fail = fail
        self.trials: list[str] = []

    def __call__(self, trial, hists, phases, stages):
        self.trials.append(trial)
        if self.fail:
            raise RuntimeError("GSAS failed")
        return _result(stages, phases)


class CandidateFake:
    def __init__(self):
        self.seen: list[RecipeCandidate] = []

    def __call__(self, cand):
        self.seen.append(cand)
        phases = cand.phases if cand.phases is not None else (A, B)
        return _result(cand.stages, phases, rwp=8.0 if cand.name == "template" else 9.0)


def _search(phases=(A, B), names=("default", "template"), **kw):
    p1 = kw.pop("pass1", None) or Pass1Fake()
    cands = CandidateFake()
    out = run_recipe_search(
        [kw.pop("hist", None) or _hist()], list(phases), names=names, runner=cands,
        template_pass1_runner=p1, save_gpx=False, **kw,
    )
    return out, p1, cands


def test_the_template_is_not_a_default_candidate_and_build_candidates_skips_it():
    assert "template" not in search_mod.DEFAULT_CANDIDATES
    built = build_candidates([_hist()], [A], names=["default", "template"])
    assert [c.name for c in built] == ["default"]


def test_existing_candidates_serialize_exactly_as_before():
    cand = build_candidates([_hist()], [A], names=["default"])[0]
    assert set(cand.to_dict()) == {
        "name", "origin", "n_stages", "background_coeffs", "two_theta_limits", "note"
    }
    assert cand.phases is None and cand.derivation is None and cand.blas_threads is None


def test_the_template_candidate_runs_pass1_and_carries_its_compiled_model():
    out, p1, cands = _search()
    assert p1.trials == ["A", "B"]
    tmpl = next(c for c in cands.seen if c.name == "template")
    assert tmpl.origin == "template" and tmpl.blas_threads == 1
    assert tmpl.stability is not None and tmpl.stability.require_convergence
    assert tmpl.phases is not None and tmpl.phases[0].fix_polar_origin
    assert tmpl.phases[1].frozen_coord_labels == ("B1",)  # 非対象相の構造凍結
    d = tmpl.to_dict()
    assert d["template_version"] == "fit-then-judge/1B/1"
    json.dumps(d, allow_nan=False)
    assert d["derivation"]["decisions"]["target_phase"] == "A"
    assert "target_phase_ambiguous" in d["derivation"]
    # 他の候補と同じ表で比べられる
    assert {o.candidate.name for o in out.outcomes} == {"default", "template"}


def test_declarations_are_recorded_and_flow_into_the_derivation():
    ledger = Ledger()
    _, _, cands = _search(
        template_declarations=TemplateDeclarations(target_phase="B"), ledger=ledger
    )
    tmpl = next(c for c in cands.seen if c.name == "template")
    assert tmpl.derivation["declarations"] == {"target_phase": "B"}
    assert tmpl.derivation["decisions"]["target_phase"] == "B"
    kinds = [e.kind for e in ledger.entries]
    assert "template_declaration" in kinds and "template_pass1" in kinds


@pytest.mark.parametrize(
    ("hist", "phases"),
    [(_hist(Radiation.NEUTRON_CW), (A,)), (_hist(Radiation.NEUTRON_TOF), (A,))],
)
def test_out_of_scope_requests_fail_before_anything_runs(hist, phases):
    p1 = Pass1Fake()
    cands = CandidateFake()
    with pytest.raises(TemplateScopeError):
        run_recipe_search(
            [hist], list(phases), names=["default", "template"], runner=cands,
            template_pass1_runner=p1, save_gpx=False,
        )
    assert p1.trials == [] and cands.seen == []


def test_joint_histograms_are_out_of_scope():
    with pytest.raises(TemplateScopeError):
        run_recipe_search(
            [_hist(), _hist()], [A], names=["template"], runner=CandidateFake(),
            template_pass1_runner=Pass1Fake(), save_gpx=False,
        )


def test_declarations_without_the_template_are_refused():
    with pytest.raises(ValueError, match="template"):
        run_recipe_search(
            [_hist()], [A], names=["default"], runner=CandidateFake(),
            template_declarations=TemplateDeclarations(), save_gpx=False,
        )


def test_a_failed_pass1_leaves_no_template_and_says_why():
    out, _, cands = _search(pass1=Pass1Fake(fail=True))
    assert [c.name for c in cands.seen] == ["default"]
    assert any("template" in w and "組めない" in w for w in out.warnings)


def test_the_default_runner_uses_the_candidate_phases_and_blas(monkeypatch):
    seen = {}

    def fake_run(hists, phases, *, recipe, **kw):
        seen.update(phases=phases, kw=kw)
        return "result"

    import tsumugin.autorietveld.engine as engine

    monkeypatch.setattr(engine, "run_auto_rietveld", fake_run)
    runner = search_mod._default_candidate_runner([A, B], {"max_cyc": 3})
    own = (PhaseSpec("a.cif", "A", fix_polar_origin=True),)
    cand = RecipeCandidate(
        name="template", stages=(), origin="template", histograms=(_hist(),),
        phases=own, blas_threads=1,
    )
    assert runner(cand) == "result"
    assert seen["phases"] == list(own) and seen["kw"]["blas_threads"] == 1
    plain = RecipeCandidate(name="default", stages=(), origin="fixed", histograms=(_hist(),))
    runner(plain)
    assert seen["phases"] == [A, B] and "blas_threads" not in seen["kw"]


def test_phase_b_confirms_the_template_with_its_own_phases():
    from tsumugin.autorietveld.confirm import optimize_then_confirm
    from tsumugin.autorietveld.multistart import RietveldMultistartResult

    captured = {}

    def fake_multistart(hists, phases, **kw):
        captured.update(phases=phases, kw=kw)
        return RietveldMultistartResult(
            best=None, best_index=-1, starts=(), n_starts=0, n_diverged=0, n_basins=0,
            is_global_corroborated=False,
        )

    report = optimize_then_confirm(
        [_hist()], [A, B], candidates=["default", "template"], coord_jitter_ang=0.0,
        search_runner=CandidateFake(), multistart_runner=fake_multistart,
        template_pass1_runner=Pass1Fake(), save_gpx=False,
    )
    assert report.adopted_recipe == "template"
    assert captured["phases"][0].fix_polar_origin
    assert captured["kw"]["blas_threads"] == 1


def test_the_internal_standard_keeps_its_certified_lattice():
    _, p1, cands = _search(template_declarations=TemplateDeclarations(internal_standard="A"))
    tmpl = next(c for c in cands.seen if c.name == "template")
    std = next(p for p in tmpl.phases if p.phase_name == "A")
    assert std.refine_cell is False
    assert tmpl.derivation["decisions"]["target_phase"] == "B"


def test_pass1_runs_with_the_same_acceptance_rules_as_pass2(monkeypatch):
    """pass 1 と pass 2 で段の受理規則 (収束判定) を揃える (セルフレビュー H2)。"""
    import tsumugin.autorietveld.engine as engine

    seen = []

    def fake_run(hists, phases, *, recipe, **kw):
        seen.append(kw)
        return _result(recipe, phases)

    monkeypatch.setattr(engine, "run_auto_rietveld", fake_run)
    out = run_recipe_search(
        [_hist()], [A, B], names=["template"], runner=CandidateFake(), save_gpx=False,
    )
    assert out.outcomes and seen
    tmpl = out.outcomes[0].candidate
    assert all(kw["stability"] == tmpl.stability for kw in seen)
    assert all(kw["blas_threads"] == 1 for kw in seen)


def test_an_engine_refusal_of_the_compiled_phases_fails_only_the_template_candidate():
    """テンプレートがコンパイルした相の指定の誤りで他の候補の結果ごと失わない (セルフレビュー M4)。"""
    from tsumugin.errors import InvalidPhaseSpecError

    def runner(cand):
        if cand.name == "template":
            raise InvalidPhaseSpecError("極性原点を固定できません")
        return _result(cand.stages, (A, B))

    out = run_recipe_search(
        [_hist()], [A, B], names=["default", "template"], runner=runner,
        template_pass1_runner=Pass1Fake(), save_gpx=False,
    )
    tmpl = next(o for o in out.outcomes if o.candidate.name == "template")
    assert tmpl.result is None and "極性原点" in tmpl.error
    assert out.selected is not None and out.selected.candidate.name == "default"


def test_a_user_phase_spec_error_still_propagates_from_ordinary_candidates():
    from tsumugin.errors import InvalidPhaseSpecError

    def runner(cand):
        raise InvalidPhaseSpecError("相に無いラベル")

    with pytest.raises(InvalidPhaseSpecError):
        run_recipe_search([_hist()], [A], names=["default"], runner=runner, save_gpx=False)


def test_a_user_phase_spec_error_in_pass1_propagates_from_the_search():
    """search=["template"] 単独でも呼び手の指定の誤りは警告に畳まない (セルフレビュー N4)。"""
    from tsumugin.errors import InvalidPhaseSpecError

    def pass1(trial, h, p, s):
        raise InvalidPhaseSpecError("相に無いラベル")

    with pytest.raises(InvalidPhaseSpecError):
        run_recipe_search(
            [_hist()], [A], names=["template"], runner=CandidateFake(),
            template_pass1_runner=pass1, save_gpx=False,
        )
