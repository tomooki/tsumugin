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


def _residual_runner(inp: AnalysisInput) -> AutoRietveldResult:
    """残差フィールドを詰めた runner (実 GSAS runner が返す形)。

    ``residual_report_from_result`` は yobs≈sigma², ycalc=yobs-residual で復元する。ここでは
    ベースライン (obs≈100) に 1 本だけ未説明ピーク (calc 不足 = 残差 +) を置く。
    """
    n = 200
    x = [5.0 + 0.25 * i for i in range(n)]
    yobs = [100.0] * n
    yobs[50] = 5000.0
    resid = [0.0] * n
    resid[50] = 4900.0  # obs-calc > 0 = 未説明強度
    sigma = [v**0.5 for v in yobs]  # 計数統計慣習 (yobs ≈ sigma²)
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=12.0, gof=1.1, n_params=8, converged=True),),
        final_rwp=12.0,
        final_gof=1.1,
        refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
        validity=ValidityReport(passed=True),
        residual_two_theta=tuple(x),
        residual_intensity=tuple(resid),
        residual_sigma=tuple(sigma),
    )


def test_auto_rietveld_embeds_residual_report_when_residuals_present():
    # 【operando 診断 ②】: 残差配列は跨がせず、レポートのみをサーバ側で算出して同梱する。
    #   ③ (MCP しか触れない skill) が再精密化なしに J2 (未説明ピーク→欠落相) を判断できる。
    out = auto_rietveld([_H], [_P], runner=_residual_runner)
    json.dumps(out, allow_nan=False)

    rep = out["residual_report"]
    assert rep is not None
    assert set(rep) == {
        "rwp",
        "peak_only_rwp",
        "baseline_numerator_fraction",
        "peak_numerator_fraction",
        "angular_rwp",
        "top_features",
    }
    assert rep["rwp"] > 0.0
    # 最大の未説明特徴は仕込んだピーク位置 (5.0 + 0.25*50 = 17.5°) で符号は正 (calc 不足)
    top = rep["top_features"][0]
    assert top["two_theta"] == 17.5
    assert top["residual"] > 0.0
    # 大きな残差配列そのものは境界を跨がない (150KB 回避)
    assert "residual_two_theta" not in out
    assert "residual_intensity" not in out


def test_auto_rietveld_residual_report_is_none_when_residuals_empty():
    # 既定 (空タプル) / スタブ runner では復元不能 → None。例外を送出せずキーは常に存在する。
    out = auto_rietveld([_H], [_P], background_coeffs=6, runner=_stub_runner)
    assert out["residual_report"] is None
    json.dumps(out, allow_nan=False)


def test_refine_with_revisions_also_embeds_residual_report():
    # アクチュエータ経路 (_result_to_dict 共有) でも同梱される。
    actions = [{"type": "AdjustBackground", "n_coeffs": 9}]
    out = refine_with_revisions([_H], [_P], actions, runner=_residual_runner)
    assert out["residual_report"] is not None
    json.dumps(out, allow_nan=False)


def test_refine_with_model_action_setlimits():
    # ModelAction (SetLimits) も refine_with_revisions で適用できる (③ が判断した改訂)
    actions = [{"type": "SetLimits", "hist_id": 0, "low": 2.5, "high": 32.0}]
    out = refine_with_revisions([_H], [_P], actions, background_coeffs=6, runner=_stub_runner)
    assert out["specs"]["histograms"][0]["two_theta_limits"] == [2.5, 32.0]
