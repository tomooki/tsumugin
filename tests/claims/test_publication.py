"""fit-then-judge P1c タスク 1: 出版状態の計算と記録の唯一の入口 (`claims.publication`)。"""

from __future__ import annotations

import json

from tsumugin.autorietveld.claim_variables import PhaseVariables, claim_variable_names
from tsumugin.autorietveld.diagnostics import CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.claims.publication import input_publication, publication_state


def _result() -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("S0", 10.0, 1.2, 5, True),),
        final_rwp=10.0, final_gof=1.2,
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        cell_esd={"P": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
        atom_coords={"P": {"O1": (0.25, 0.1, 0.3)}},
        atom_coord_esd={"P": {"O1": (0.001, 0.002, None)}},
        atom_coord_free_index={"P": {"O1": (1, 2, 3)}},
        atom_uiso={"P": {"O1": 0.02}}, atom_uiso_esd={"P": {"O1": 0.003}},
        final_covariance=CovarianceRecord(
            vary_list=("0::A0", "0::dAx:0", "0::AUiso:0"), dependent=(), correlations=(),
        ),
        claim_variables=claim_variable_names([PhaseVariables(name="P", pid=0, labels=("O1",))], []),
    )


def test_the_state_is_json_safe_and_written_next_to_the_gpx(tmp_path):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    state = publication_state(_result(), None, gpx_path=str(gpx))
    json.dumps(state, allow_nan=False)
    assert state["claims_sidecar"].endswith("fit.claims.json") and state["claims_sidecar_reason"] == ""
    assert "error" not in state and state["claims"] and state["claims_policy"]


def test_without_a_gpx_no_sidecar_is_written():
    state = publication_state(_result(), None)
    assert state["claims_sidecar"] == "" and state["claims"]


def test_a_failure_degrades_to_nothing_publishable():
    state = publication_state(object(), None)
    assert state["claims"] is None and state["publishable_values"] == {}
    assert state["error"]


def test_input_publication_of_an_unknown_gpx(tmp_path):
    out = input_publication(str(tmp_path / "none.gpx"))
    assert out["state"] == "unknown" and out["structure_held"] is None
    json.dumps(out, allow_nan=False)


def test_input_publication_reads_the_matching_sidecar(tmp_path):
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    publication_state(_result(), None, gpx_path=str(gpx))
    out = input_publication(str(gpx))
    assert out["state"] == "known" and out["sidecar"].endswith("fit.claims.json")
    assert out["n_values"] > 0 and out["n_publishable"] == 0  # 結晶化学も相集合も未検査
    assert "coord:P.O1.x" in out["structure_held"]
    assert any(r["kind"] == "phase_set_completeness" for r in out["blocking_requests"])
    gpx.write_bytes(b"other")  # 上書きされた gpx — 古い状態を使わない
    assert input_publication(str(gpx))["state"] == "unknown"
