"""Issue #101: ② `auto_rietveld`/`refine_with_revisions` から `stages`/`max_cyc` への到達可能性。

① `AnalysisInput.extra_stages` (`refine_loop/action.py`) と `run_auto_rietveld(max_cyc=)`
(`autorietveld/engine.py`) は既に存在するが、② の JSON 入口からは届かなかった (Issue 本文が言う
「放射光単一フレームが②経由で不可能」は誤りで、実際のギャップは recipe/精密化制御の到達可能性)。
本テストは stages (JSON→RefinementStage) と max_cyc の配線・不正 spec の縮退・後方互換を固定する。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.autorietveld import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from tsumugin.mcp.rietveld_tools import auto_rietveld, refine_with_revisions
from tsumugin.refine_loop.action import AnalysisInput

_H = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
).to_dict()
_P = PhaseSpec(structure_path="a.cif", phase_name="ph").to_dict()

_STAGE = {"label": "S9 abs", "flags": {"absorption": True}, "note": "opt-in"}


def _echo_extra_stages_runner(inp: AnalysisInput) -> AutoRietveldResult:
    """extra_stages の中身をそのまま結果の note に写して観測可能にするスタブ。"""
    labels = ",".join(s.label for s in inp.extra_stages)
    return AutoRietveldResult(
        stage_results=(StageResult(label=labels, rwp=10.0, gof=1.0, n_params=1, converged=True),),
        final_rwp=10.0,
        final_gof=1.0,
        refined_cells={},
        validity=ValidityReport(passed=True),
    )


# ---------------------------------------------------------------------------
# auto_rietveld: stages
# ---------------------------------------------------------------------------


def test_auto_rietveld_stages_reach_extra_stages():
    out = auto_rietveld([_H], [_P], stages=[_STAGE], runner=_echo_extra_stages_runner)
    assert out["stages"][0]["label"] == "S9 abs"
    json.dumps(out, allow_nan=False)


def test_auto_rietveld_stages_default_is_empty():
    """stages 省略時は extra_stages が空 (後方互換)。"""
    out = auto_rietveld([_H], [_P], runner=_echo_extra_stages_runner)
    assert out["stages"][0]["label"] == ""


@pytest.mark.parametrize(
    "bad_stages",
    [
        [{"label": ""}],
        [{"flags": {"absorption": True}}],
        [{"label": "S9", "unknown": 1}],
        "not-a-list",
    ],
)
def test_auto_rietveld_invalid_stages_returns_error_dict(bad_stages):
    out = auto_rietveld([_H], [_P], stages=bad_stages, runner=_echo_extra_stages_runner)
    assert out["error_type"] == "ValueError"
    assert isinstance(out["error"], str)
    json.dumps(out, allow_nan=False)


def test_auto_rietveld_specs_handle_roundtrips_stages():
    """spec ハンドル (③ が refine_with_revisions へ差し戻す往復) に stages が含まれる。"""
    out = auto_rietveld([_H], [_P], stages=[_STAGE], runner=_echo_extra_stages_runner)
    assert out["specs"]["stages"] == [_STAGE]


# ---------------------------------------------------------------------------
# refine_with_revisions: stages
# ---------------------------------------------------------------------------


def test_refine_with_revisions_stages_reach_extra_stages():
    out = refine_with_revisions(
        [_H], [_P], [], stages=[_STAGE], runner=_echo_extra_stages_runner
    )
    assert out["stages"][0]["label"] == "S9 abs"
    json.dumps(out, allow_nan=False)


def test_refine_with_revisions_invalid_stages_returns_error_dict():
    out = refine_with_revisions(
        [_H], [_P], [], stages=[{"label": ""}], runner=_echo_extra_stages_runner
    )
    assert out["error_type"] == "ValueError"


def test_refine_with_revisions_stages_combine_with_actions():
    """stages (spec, 既存の累積段階) と ReleaseParams (action, 今回の新規決定) が両方届く。

    ``stages`` は spec ハンドル経由で持ち回る累積段階 (`_specs_dict` が返す既存分)、
    ``actions`` は今回の反復で ③ が新たに決めた手 — 時系列順は「既存 stages → 新規 action」。
    """
    actions = [{"type": "ReleaseParams", "label": "S8 extra", "flags": {"coords": True}}]
    out = refine_with_revisions(
        [_H], [_P], actions, stages=[_STAGE], runner=_echo_extra_stages_runner
    )
    labels = out["stages"][0]["label"].split(",")
    assert labels == ["S9 abs", "S8 extra"]


# ---------------------------------------------------------------------------
# max_cyc: _default_gsas_runner への伝播 (runner= 未指定経路)
# ---------------------------------------------------------------------------


def _patch_default_gsas(monkeypatch):
    captured: dict[str, object] = {}

    def fake_run_auto_rietveld(histograms, phases, *, recipe=None, max_cyc=12, **kw):
        captured["recipe"] = recipe
        captured["max_cyc"] = max_cyc
        return AutoRietveldResult(
            stage_results=(), final_rwp=5.0, final_gof=1.0, refined_cells={},
            validity=ValidityReport(passed=True),
        )

    def fake_build_recipe(histograms, phases, *, background_coeffs=6):
        return (RefinementStage(label="S0"),)

    monkeypatch.setattr("tsumugin.autorietveld.run_auto_rietveld", fake_run_auto_rietveld)
    monkeypatch.setattr("tsumugin.autorietveld.build_recipe", fake_build_recipe)
    return captured


def test_auto_rietveld_max_cyc_reaches_default_runner(monkeypatch):
    captured = _patch_default_gsas(monkeypatch)

    auto_rietveld([_H], [_P], max_cyc=30)

    assert captured["max_cyc"] == 30


def test_auto_rietveld_max_cyc_default_is_12(monkeypatch):
    """max_cyc 省略時は既定 12 (非回帰)。"""
    captured = _patch_default_gsas(monkeypatch)

    auto_rietveld([_H], [_P])

    assert captured["max_cyc"] == 12


def test_auto_rietveld_default_runner_appends_extra_stages_to_build_recipe(monkeypatch):
    captured = _patch_default_gsas(monkeypatch)

    auto_rietveld([_H], [_P], stages=[_STAGE])

    labels = [s.label for s in captured["recipe"]]
    assert labels == ["S0", "S9 abs"]


def test_refine_with_revisions_max_cyc_reaches_default_runner(monkeypatch):
    captured = _patch_default_gsas(monkeypatch)

    refine_with_revisions([_H], [_P], [], max_cyc=25)

    assert captured["max_cyc"] == 25
