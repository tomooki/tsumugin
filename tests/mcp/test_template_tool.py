"""fit-then-judge P1-1B タスク 10: ② `auto_rietveld` のテンプレートと初期値プローブ (REQ-FTJ-1B-603/701)。"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tsumugin.autorietveld.claim_variables import PhaseVariables, claim_variable_names
from tsumugin.autorietveld.diagnostics import CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.mcp.rietveld_tools import auto_rietveld, refine_with_revisions

N_OBS = 1000

_H = {"data_path": "d.xye", "instrument_path": "i.instprm", "radiation": "xray_lab",
      "geometry": "bragg_brentano"}
_P = [{"structure_path": "a.cif", "phase_name": "A"}, {"structure_path": "b.cif", "phase_name": "B"}]


def _result(stages, phases, rwp=9.0, gpx_path="") -> AutoRietveldResult:
    out = tuple(
        StageResult(st.label, rwp, 1.0 + 0.01 * i, 5 + i, True) for i, st in enumerate(stages)
    ) or (StageResult("S0", rwp, 1.0, 5, True),)
    resid = np.random.default_rng(0).standard_normal(200)
    names = [p.phase_name for p in phases]
    return AutoRietveldResult(
        stage_results=out, final_rwp=rwp, final_gof=out[-1].gof,
        refined_cells={n: (5.0, 5.0, 5.0, 90.0, 90.0, 90.0) for n in names},
        validity=ValidityReport(passed=True), n_obs=N_OBS, gpx_path=gpx_path,
        residual_intensity=tuple(map(float, resid)), residual_sigma=(1.0,) * 200,
        atom_uiso={n: {f"{n}1": 0.01} for n in names},
        phase_integrated_intensity={n: (100.0 / (i + 1),) for i, n in enumerate(names)},
        cell_esd={n: (0.001, 0.001, 0.001, 0.0, 0.0, 0.0) for n in names},
        final_covariance=CovarianceRecord(
            vary_list=tuple(f"{i}::A0" for i in range(len(names))), dependent=(), correlations=(),
        ),
        claim_variables=claim_variable_names(
            [PhaseVariables(name=n, pid=i, labels=(f"{n}1",)) for i, n in enumerate(names)], [],
        ),
    )


def _pass1(trial, hists, phases, stages):
    return _result(stages, phases)


def _search_runner(cand):
    phases = cand.phases if cand.phases is not None else ()
    if not phases:
        from tsumugin.autorietveld.model import PhaseSpec

        phases = tuple(PhaseSpec.from_dict(p) for p in _P)
    return _result(cand.stages, phases, rwp=8.0 if cand.name == "template" else 9.0)


def _call(**kw):
    base = dict(
        search=["default", "template"], template={}, search_runner=_search_runner,
        template_pass1_runner=_pass1, save_gpx=False,
    )
    base.update(kw)
    return auto_rietveld([_H], _P, **base)


def test_the_template_is_reachable_and_its_derivation_is_reported():
    out = _call()
    assert "error" not in out, out
    json.dumps(out, allow_nan=False)
    assert out["template_version"] == "fit-then-judge/1B/1"
    assert out["template_derivation"]["decisions"]["target_phase"] == "A"
    tmpl = next(
        c["candidate"] for c in out["search"]["candidates"] if c["candidate"]["name"] == "template"
    )
    assert tmpl["derivation"]["template_version"] == "fit-then-judge/1B/1"
    # 返した specs はコンパイルされた相の指定で、再利用を断る目印付き
    assert all(p["template_version"] == "fit-then-judge/1B/1" for p in out["specs"]["phases"])
    assert out["specs"]["phases"][1]["frozen_coord_labels"] == ["B1"]


def test_compiled_phase_specs_cannot_be_fed_back():
    out = _call()
    for fn, extra in ((auto_rietveld, {}), (refine_with_revisions, {"actions": []})):
        back = fn([_H], out["specs"]["phases"], runner=lambda inp: None, **extra)
        assert back.get("error_type") == "ValueError" and "template_version" in back["error"]


def test_declarations_without_the_template_candidate_are_an_error():
    out = auto_rietveld([_H], _P, template={"target_phase": "A"}, runner=lambda inp: None)
    assert set(out) == {"error", "error_type"}
    out = _call(search=["default"])
    assert set(out) == {"error", "error_type"}


@pytest.mark.parametrize("radiation", ["neutron_cw", "neutron_tof"])
def test_out_of_scope_data_fails_the_whole_call(radiation):
    h = dict(_H, radiation=radiation)
    out = auto_rietveld(
        [h], _P, search=["default", "template"], template={}, search_runner=_search_runner,
        template_pass1_runner=_pass1, save_gpx=False,
    )
    assert out["error_type"] == "TemplateScopeError"


def test_extra_stages_and_the_template_cannot_be_combined():
    out = _call(stages=[{"label": "x", "flags": {"absorption": True}}])
    assert set(out) == {"error", "error_type"} and "stages" in out["error"]


@pytest.mark.parametrize("bad", [{"target_phas": "A"}, {"target_phase": "Z"}, "A"])
def test_malformed_declarations_are_error_dicts(bad):
    out = _call(template=bad)
    assert set(out) == {"error", "error_type"}


def test_the_template_runs_through_the_standard_route_with_its_phases():
    from tsumugin.autorietveld.multistart import RietveldMultistartResult

    seen = {}

    def ms(hists, phases, **kw):
        seen["phases"] = phases
        best = _result((), phases, rwp=7.5)
        return RietveldMultistartResult(
            best=best, best_index=0, starts=(), n_starts=0, n_diverged=0, n_basins=0,
            is_global_corroborated=False,
        )

    out = _call(
        multistart={"n_starts": 3, "coord_jitter_ang": 0.05}, multistart_runner=ms,
        initial_value_probe={},
    )
    assert "error" not in out, out
    assert "gpx" in out["initial_value_probe"]["reason"]  # 収束確認経路でも頼めば回る (保存なし→理由)
    assert seen["phases"][0].fix_polar_origin  # 対象相の極性原点 + 座標の摂動が組み合わせられる
    assert out["template_version"] == "fit-then-judge/1B/1"


# --- 初期値プローブ ----------------------------------------------------------------


def test_the_probe_is_not_run_without_a_saved_gpx():
    out = auto_rietveld(
        [_H], _P, runner=lambda inp: _result((), inp.phases), initial_value_probe={},
        prober=lambda *a, **k: pytest.fail("走った"),
    )
    assert out["initial_value_probe"]["complete"] is False
    assert "gpx" in out["initial_value_probe"]["reason"]


def test_the_probe_runs_from_the_returned_gpx(tmp_path):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    calls = []

    def prober(path, **kw):
        calls.append(path)
        from tsumugin.autorietveld.model import PhaseSpec

        return _result((), [PhaseSpec.from_dict(p) for p in _P])

    out = auto_rietveld(
        [_H], _P, runner=lambda inp: _result((), inp.phases, gpx_path=str(gpx)),
        initial_value_probe={"cell_frac": 0.002}, prober=prober,
    )
    assert calls == [str(gpx), str(gpx)]
    assert out["initial_value_probe"]["complete"] is True
    assert out["initial_value_probe"]["config"]["cell_frac"] == 0.002
    a = out["claims"]["cell:A.a"]
    assert a["determinacy"] == "locally_stable"
    assert a["witnesses"][-1]["kind"] == "initial_value_probe"
    json.dumps(out, allow_nan=False)


@pytest.mark.parametrize("bad", [{"cell_frc": 0.1}, {"cell_frac": -1.0}, [1]])
def test_malformed_probe_specs_are_error_dicts(bad):
    out = auto_rietveld([_H], _P, runner=lambda inp: None, initial_value_probe=bad)
    assert set(out) == {"error", "error_type"}


def test_the_probe_also_runs_on_the_search_route(tmp_path):
    gpx = tmp_path / "cand.gpx"
    gpx.write_bytes(b"gpx")

    def runner(cand):
        r = _search_runner(cand)
        from dataclasses import replace

        return replace(r, gpx_path=str(gpx))

    out = _call(search_runner=runner, initial_value_probe={},
                prober=lambda path, **kw: runner(type("C", (), {"phases": None, "stages": (),
                                                                "name": "x"})()))
    assert out["initial_value_probe"]["complete"] is True
