"""TASK-0807: 薄い MCP 3 ツール — auto_rietveld / propose_next_actions / refine_with_revisions。

計器 (auto_rietveld/propose_next_actions) + アクチュエータ (refine_with_revisions) を JSON 露出し、
③ (Claude) が反復駆動して閉ループを回す (architecture.md §6)。決定論スタブ runner で e2e 再現。
ループ丸ごと (agentic_analyze) は MCP に出さない = ③ が回す。
"""

from __future__ import annotations

import json

from tsumugin.autorietveld import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.mcp.rietveld_tools import (
    auto_rietveld,
    propose_next_actions,
    refine_with_revisions,
)
from tsumugin.mcp.tools import MCP_TOOLS
from tsumugin.refine_loop.action import AnalysisInput

_H = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
).to_dict()
_P = PhaseSpec(structure_path="a.cif", phase_name="ph").to_dict()


def _stub_runner(inp: AnalysisInput) -> AutoRietveldResult:
    """背景係数が増えるほど Rwp が下がるスタブ (30 - coeffs)。"""
    rwp = 30.0 - float(inp.background_coeffs)
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=rwp, gof=1.0, n_params=8, converged=True),),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=True, checks=(("lattice_a", True, "ok"),)),
    )


def test_tools_registered_in_mcp_registry():
    for name in ("auto_rietveld", "propose_next_actions", "refine_with_revisions"):
        assert name in MCP_TOOLS


def test_auto_rietveld_returns_structured_result_and_spec_handle():
    out = auto_rietveld([_H], [_P], background_coeffs=6, runner=_stub_runner)
    json.dumps(out, allow_nan=False)  # 素の型のみ
    assert out["final_rwp"] == 24.0
    assert out["validity"]["passed"] is True
    assert out["refined_cells"]["ph"] == [9.37, 9.37, 6.89, 90.0, 90.0, 120.0]
    # spec ハンドル (stateless echo) が往復可能
    assert out["specs"]["histograms"][0]["data_path"] == "d.xra"
    assert out["specs"]["background_coeffs"] == 6


def test_propose_next_actions_tool_returns_proposals_with_safe_flag():
    result = auto_rietveld([_H], [_P], background_coeffs=6, runner=_stub_runner)
    features = [{"hist_id": 0, "low_freq_bg_residual": 0.5, "n_background_coeffs": 6}]
    out = propose_next_actions(result, features)
    json.dumps(out, allow_nan=False)
    props = out["proposals"]
    assert props and props[0]["action"]["type"] == "AdjustBackground"
    assert props[0]["safe"] is True


def test_refine_with_revisions_applies_actions_and_reruns():
    # ③ が決めた改訂 (背景 6→9) を適用して再実行 → Rwp 改善
    actions = [{"type": "AdjustBackground", "n_coeffs": 9}]
    out = refine_with_revisions([_H], [_P], actions, background_coeffs=6, runner=_stub_runner)
    assert out["final_rwp"] == 21.0
    assert out["specs"]["background_coeffs"] == 9


def test_closed_loop_e2e_with_stub_judge():
    # ③ (スタブ判断者) が auto_rietveld → propose → refine_with_revisions を反復駆動する
    result = auto_rietveld([_H], [_P], background_coeffs=6, runner=_stub_runner)
    specs = result["specs"]
    for _ in range(3):
        n = specs["background_coeffs"]
        features = [{"hist_id": 0, "low_freq_bg_residual": 0.5, "n_background_coeffs": n}]
        props = propose_next_actions(result, features)["proposals"]
        safe = [p for p in props if p["safe"]]
        if not safe:
            break
        action = safe[0]["action"]  # スタブ判断者は先頭 safe を採る
        result = refine_with_revisions(
            specs["histograms"], specs["phases"], [action],
            background_coeffs=n, runner=_stub_runner,
        )
        specs = result["specs"]
    # 6→9→12 で Rwp 24→18 に改善
    assert result["final_rwp"] <= 18.0


def test_auto_rietveld_json_safe_when_cells_non_finite():
    # H-adapter 回帰: 発散/崩壊で refined_cells に NaN/Inf が出ても finite_or_none で None 化し
    # json.dumps(allow_nan=False) が通る (計器がクラッシュせず失敗を構造化して返す)
    def diverged_runner(inp):
        return AutoRietveldResult(
            stage_results=(StageResult(label="S0", rwp=99.0, gof=9.0, n_params=3, converged=False),),
            final_rwp=99.0,
            final_gof=9.0,
            refined_cells={"ph": (float("nan"), 9.4, float("inf"), 90.0, 90.0, 90.0)},
            validity=ValidityReport(passed=False),
        )

    out = auto_rietveld([_H], [_P], runner=diverged_runner)
    json.dumps(out, allow_nan=False)  # クラッシュしない
    assert out["refined_cells"]["ph"][0] is None and out["refined_cells"]["ph"][2] is None


def test_refine_with_model_action_setlimits():
    # ModelAction (SetLimits) も refine_with_revisions で適用できる (③ が判断した改訂)
    actions = [{"type": "SetLimits", "hist_id": 0, "low": 2.5, "high": 32.0}]
    out = refine_with_revisions([_H], [_P], actions, background_coeffs=6, runner=_stub_runner)
    assert out["specs"]["histograms"][0]["two_theta_limits"] == [2.5, 32.0]
