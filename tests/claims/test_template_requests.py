"""fit-then-judge P1-1B タスク 10: テンプレートの判断を出版状態に写す (設計 §8)。"""

from __future__ import annotations

import json

from tsumugin.autorietveld.claim_variables import (
    HistogramVariables,
    PhaseVariables,
    claim_variable_names,
)
from tsumugin.autorietveld.diagnostics import CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.claims.build import base_claims
from tsumugin.claims.model import Scope
from tsumugin.claims.requests import assess, template_adjustments

_VARS = claim_variable_names(
    [PhaseVariables(name="P", pid=0, labels=("Pb", "O1"))],
    [HistogramVariables(index=0, hid=0, profile_keys=("U", "Zero"))],
)


def _result() -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("S0", 10.0, 1.2, 5, True),),
        final_rwp=10.0, final_gof=1.2,
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        cell_esd={"P": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
        atom_coords={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.25, 0.1, 0.3)}},
        atom_coord_esd={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.001, 0.002, None)}},
        atom_coord_free_index={"P": {"Pb": (0, 0, 0), "O1": (1, 2, 3)}},
        atom_uiso={"P": {"Pb": 0.01, "O1": 0.02}},
        atom_uiso_esd={"P": {"Pb": 0.001, "O1": 0.003}},
        atom_occupancy={"P": {"Pb": 1.0, "O1": 1.0}},
        atom_occupancy_esd={"P": {"Pb": None, "O1": None}},
        phase_weight_fractions={"P": 1.0}, phase_weight_fraction_esd={"P": 0.0},
        hist_profile=({"U": 2.0, "Zero": 0.01},), hist_profile_esd=({"U": 0.1, "Zero": None},),
        final_covariance=CovarianceRecord(
            vary_list=("0::A0", "0::dAx:1", "0::dAy:1", "0::AUiso:0", "0::AUiso:1", ":0:U"),
            dependent=(), correlations=(),
        ),
        claim_variables=_VARS,
    )


def _derivation(**kw) -> dict:
    d = {
        "template_version": "fit-then-judge/1B/1",
        "decisions": {"target_phase": "P"},
        "evidence": {"zero_offset": {"significant": True}, "target_phase": {"ratio": 0.9}},
        "declarations": {},
        "target_phase_ambiguous": False,
        "zero_offset_significant": False,
    }
    d.update(kw)
    return d


def test_no_derivation_changes_nothing():
    claims = base_claims(_result())
    out, reqs = template_adjustments(claims, None)
    assert out == claims and reqs == []


def test_an_internal_standard_makes_refined_lattices_absolute_and_declared():
    claims = base_claims(_result())
    out, reqs = template_adjustments(
        claims, _derivation(declarations={"internal_standard": "Si"})
    )
    a = out["cell:P.a"]
    assert a.scope is Scope.ABSOLUTE and "declared:internal_standard" in a.provenance
    assert out["cell:P.alpha"].scope is Scope.RELATIVE_WITHIN_SAMPLE  # 対称で決まった値は触らない
    assert reqs == []


def test_a_significant_zero_keeps_lattices_relative_and_asks_without_blocking():
    claims = base_claims(_result())
    out, reqs = template_adjustments(
        claims,
        _derivation(declarations={"internal_standard": "Si"}, zero_offset_significant=True),
    )
    a = out["cell:P.a"]
    assert a.scope is Scope.RELATIVE_WITHIN_SAMPLE
    assert "profile:hist0.Zero" in a.correlations
    (req,) = reqs
    assert req.kind == "zero_offset_significant" and req.blocking is False


def test_an_ambiguous_target_blocks_every_structure_value():
    result = _result()
    body = assess(result, None, derivation=_derivation(target_phase_ambiguous=True))
    req = next(r for r in body.requests if r.kind == "target_phase_ambiguous")
    assert req.blocking and req.default is not None  # D が既定回答 (hold)
    assert "coord:P.O1.x" in req.blocks and "uiso:P.Pb" in req.blocks
    assert "cell:P.a" not in req.blocks
    assert "target_phase_ambiguous" in body.claims["coord:P.O1.x"].gate
    json.dumps(body.to_dict())


def test_declarations_are_carried_into_provenance():
    claims = base_claims(_result())
    out, _ = template_adjustments(
        claims, _derivation(declarations={"target_phase": "P", "instrument_calibrated": True})
    )
    assert "declared:target_phase" in out["coord:P.O1.x"].provenance
    assert "declared:target_phase" not in out["cell:P.a"].provenance


def test_assess_without_template_inputs_is_unchanged():
    result = _result()
    assert assess(result, None).to_dict() == assess(result, None, derivation=None, probe=None).to_dict()
