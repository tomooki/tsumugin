"""TASK-0807 支援: AnalysisAction / ActionProposal / ResidualFeatures の JSON 往復。

MCP が ③ (Claude) と Action を JSON でやり取りするための素の型シリアライズ。往復同型を保証する。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.autorietveld import PhaseSpec
from tsumugin.refine_loop.action import (
    AddPhase,
    AdjustBackground,
    ReleaseParams,
    RemovePhase,
    ReviseStructure,
    SetLimits,
    SetMixedOccupancy,
    Stop,
)
from tsumugin.refine_loop.diagnostics import ActionProposal, ResidualFeatures
from tsumugin.refine_loop.serialization import (
    action_from_dict,
    action_to_dict,
    features_from_dicts,
    proposal_to_dict,
)

_ACTIONS = [
    AdjustBackground(9),
    ReleaseParams("size_strain", {"size_strain": True}),
    Stop("done"),
    SetLimits(0, 2.5, 32.0),
    AddPhase(spec=PhaseSpec(structure_path="c.cif", phase_name="extra")),
    AddPhase(element_hint=("Ca", "F")),
    RemovePhase("caf2"),
    ReviseStructure("nac", {"structure_path": "nac_edited.cif"}),
    SetMixedOccupancy("nac", (("Fe1", "Al1"),)),
]


@pytest.mark.parametrize("action", _ACTIONS)
def test_action_roundtrip(action):
    d = action_to_dict(action)
    assert d["type"] == type(action).__name__
    json.dumps(d, allow_nan=False)  # JSON 安全
    assert action_from_dict(d) == action


def test_action_from_dict_unknown_type_raises():
    with pytest.raises(ValueError):
        action_from_dict({"type": "Bogus"})


def test_proposal_to_dict_carries_metadata():
    p = ActionProposal(
        action=AdjustBackground(9), rationale="bg", priority=0.5, evidence={"k": 1}, safe=True
    )
    d = proposal_to_dict(p)
    assert d["action"]["type"] == "AdjustBackground"
    assert d["safe"] is True and d["priority"] == 0.5 and d["rationale"] == "bg"
    json.dumps(d, allow_nan=False)


def test_features_from_dicts():
    feats = features_from_dicts(
        [{"hist_id": 0, "low_freq_bg_residual": 0.5, "n_background_coeffs": 6}]
    )
    assert feats[0].hist_id == 0 and feats[0].low_freq_bg_residual == 0.5
    assert isinstance(feats[0], ResidualFeatures)
