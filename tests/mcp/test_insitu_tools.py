"""M9 薄い MCP 3 ツール (insitu_tools) の純テスト (stub runner/finder, GSAS/MP 非依存)。

SDK 非依存・素の型 dict 応答・json.dumps(allow_nan=False) 安全・決定論を検証する。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.model import FrameSpec
from tsumugin.mcp.insitu_tools import (
    INSITU_TOOLS,
    parametric_fit,
    sequential_rietveld,
)


def _result(rwp, cells, fracs, valid=True):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=1.0, refined_cells=cells,
        validity=ValidityReport(passed=valid), phase_fractions=fracs,
    )


def test_registry_has_three_tools():
    assert set(INSITU_TOOLS) == {"sequential_rietveld", "identify_and_add_phase", "parametric_fit"}


def test_sequential_rietveld_structured_output_json_safe():
    frames = [FrameSpec(f"f{i}.xrdml", axis_value=300.0 + 20 * i).to_dict() for i in range(3)]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    out = sequential_rietveld(frames, initial, runner=runner, reason="test")
    assert out["phase_names"] == ["alpha"]
    assert len(out["frames"]) == 3
    assert out["frames"][0]["rwp"] == 9.0
    assert out["appearances"] == []
    # json 安全 (allow_nan=False)
    json.dumps(out, allow_nan=False)


def test_sequential_rietveld_reports_appearance():
    frames = [FrameSpec(f"f{i}.xrdml", axis_value=300.0 + 20 * i).to_dict() for i in range(3)]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]
    delta = PhaseSpec("delta.cif", "new_delta")

    n = {"i": 0}

    def runner(frame, phases, initial_cells):
        names = [p.phase_name for p in phases]
        if "new_delta" in names:
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_delta": (13.3, 6.5, 8.1, 90, 90, 90)},
                           {"alpha": 0.6, "new_delta": 0.4})
        i = n["i"]
        n["i"] += 1
        return _result(9.0 if i < 2 else 22.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir, known_phases=()):
        return [(delta, {"source": "materials_project", "dara_score": 0.5})]

    out = sequential_rietveld(
        frames, initial, phase_id={"elements": ["Ca", "Te", "O"], "frac_min": 0.02},
        runner=runner, phase_finder=finder,
    )
    assert len(out["appearances"]) == 1
    ap = out["appearances"][0]
    assert ap["phase_name"] == "new_delta"
    assert ap["frame_index"] == 2
    assert ap["evidence"]["dara_score"] == 0.5
    json.dumps(out, allow_nan=False)


def test_parametric_fit_from_result_dict():
    # sequential_rietveld の出力を parametric_fit に渡す往復
    frames = [
        FrameSpec(f"f{k}.xrdml", axis_value=T).to_dict()
        for k, T in enumerate([300.0, 320.0, 340.0, 360.0, 380.0])
    ]
    initial = [PhaseSpec("alpha.cif", "alpha").to_dict()]

    def runner(frame, phases, initial_cells):
        a = 14.8 + 0.002 * (frame.axis_value - 300.0)
        return _result(9.0, {"alpha": (a, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    seq = sequential_rietveld(frames, initial, runner=runner)
    pf = parametric_fit(seq, "alpha", component="a", degree=1)
    assert pf["phase"] == "alpha"
    assert pf["baseline"]["coefficients"][1] == pytest.approx(0.002, abs=1e-5)
    assert pf["transition"] is None  # 単相
    json.dumps(pf, allow_nan=False)
