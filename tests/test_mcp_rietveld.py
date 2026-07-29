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


# ===========================================================================
# 出版値の露出 (Issue #96 レビュー HIGH-2)
# ---------------------------------------------------------------------------
# `phase_fractions` は **Scale** であって重量分率ではない。単位胞質量が相間で異なると乖離する
# (実測 K2Mn[Fe(CN)6] tetra: 同じ fit で 65.6 Scale% が 47.2 wt% = この点で 1.39 倍。乖離は
# フレーム毎に違い [1.39-1.62 倍]、大きさは単位胞質量比 [cubic 1103.4 / tetra 517.8 amu = 2.13 倍]
# と分率で決まる = **単一の換算係数は無い**)。
# `autorietveld/model.py` は「出版値には phase_weight_fractions を使うこと」と言うが、② に載って
# いなければ ③ は**受け取れない** = その指示は実行不能である (★ 実行者から見えない実装は「無い」と同じ)。
# esd を伴わない精密化値は出版できないため、cell_esd / phase_weight_fraction_esd も同経路で出す。
# ===========================================================================


def _publication_runner(inp: AnalysisInput) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=7.0,
        final_gof=1.2,
        refined_cells={"ph": (10.4, 10.4, 10.4, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        phase_fractions={"cubic": 0.656, "tetra": 0.344},
        phase_weight_fractions={"cubic": 0.472, "tetra": 0.528},
        phase_weight_fraction_esd={"cubic": 0.006, "tetra": 0.006},
        cell_esd={"ph": (0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0)},
    )


def test_auto_rietveld_exposes_publication_weight_fractions_and_esd():
    """出版値 (重量分率 ± esd) と格子 esd が ② の出力に載ること。"""
    out = auto_rietveld([_H], [_P], runner=_publication_runner)

    assert out["phase_weight_fractions"] == {"cubic": 0.472, "tetra": 0.528}
    assert out["phase_weight_fraction_esd"] == {"cubic": 0.006, "tetra": 0.006}
    assert out["cell_esd"] == {"ph": [0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0]}
    json.dumps(out, allow_nan=False)


def test_auto_rietveld_publication_keys_present_even_when_unavailable():
    """キーは常に存在させスキーマを安定させる (residual_report と同一規律)。

    キーの**欠落**と「値が空」を ③ が区別できないと、esd 不明を「esd=0」と読む余地が残る。
    """
    out = auto_rietveld([_H], [_P], runner=_stub_runner)  # esd/重量分率を持たない runner

    assert out["phase_weight_fractions"] == {}
    assert out["phase_weight_fraction_esd"] == {}
    assert out["cell_esd"] == {}
    json.dumps(out, allow_nan=False)


def test_auto_rietveld_publication_values_are_json_safe():
    """非有限 (共分散が壊れた精密化) は None へ落とす (allow_nan=False クラッシュを防ぐ)。"""

    def runner(inp: AnalysisInput) -> AutoRietveldResult:
        return AutoRietveldResult(
            stage_results=(), final_rwp=7.0, final_gof=1.2,
            refined_cells={}, validity=ValidityReport(passed=True),
            phase_weight_fractions={"cubic": float("nan")},
            phase_weight_fraction_esd={"cubic": float("inf")},
            cell_esd={"cubic": (float("nan"), 0.1, 0.1, 0.0, 0.0, 0.0)},
        )

    out = auto_rietveld([_H], [_P], runner=runner)

    assert out["phase_weight_fractions"]["cubic"] is None
    assert out["phase_weight_fraction_esd"]["cubic"] is None
    assert out["cell_esd"]["cubic"][0] is None
    json.dumps(out, allow_nan=False)


def test_refine_with_revisions_exposes_publication_values():
    """アクチュエータ経路でも同じ (③ が改訂後の出版値を読めなければ改訂の意味がない)。"""
    out = refine_with_revisions([_H], [_P], [], runner=_publication_runner)

    assert out["phase_weight_fractions"] == {"cubic": 0.472, "tetra": 0.528}
    assert out["cell_esd"]["ph"] == [0.0002, 0.0002, 0.0002, 0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# 安定性診断ゲート (WS-1 stable-auto-rietveld) の ② 到達可能性
# ---------------------------------------------------------------------------


def test_stability_spec_reaches_the_real_runner(monkeypatch):
    """③ が JSON で送った ``stability`` が既定 (実 GSAS) runner まで届く。

    【目的】: ① に実装したゲートが ② から呼べること (CLAUDE.md ★ 不変条件)。runner を注入すると
    ゲートはその runner の責務になるので、**注入しない経路**で `_default_gsas_runner` に何が
    渡ったかを見る。ここが繋がっていないと ③ から見て機能は存在しない (dead on arrival)。
    """
    from tsumugin.autorietveld import StabilityOptions
    import tsumugin.mcp.rietveld_tools as rt

    seen: dict = {}

    def _spy(seed, max_cyc=12, stability=None):
        seen.update(seed=seed, max_cyc=max_cyc, stability=stability)
        return _stub_runner

    monkeypatch.setattr(rt, "_default_gsas_runner", _spy)

    out = rt.auto_rietveld(
        [_H], [_P], stability={"require_convergence": True, "max_shift_esd": 2.0}
    )

    assert "error" not in out
    assert seen["stability"] == StabilityOptions(require_convergence=True, max_shift_esd=2.0)


def test_stability_spec_defaults_to_the_no_op_options(monkeypatch):
    # 【目的】: 未指定は「全ゲート無効」の StabilityOptions (= 現行と同一挙動) であること。
    from tsumugin.autorietveld import StabilityOptions
    import tsumugin.mcp.rietveld_tools as rt

    seen: dict = {}
    monkeypatch.setattr(
        rt, "_default_gsas_runner",
        lambda seed, max_cyc=12, stability=None: seen.update(stability=stability) or _stub_runner,
    )

    rt.auto_rietveld([_H], [_P])

    assert seen["stability"] == StabilityOptions()
    assert seen["stability"].needs_diagnostics is False


def test_stage_note_is_returned_so_diagnostics_are_visible_to_layer3():
    """★②到達可能性: 段の所見 (`note`) が ② の戻り値に出ること。

    【目的】: `unconverged` / `noop` / `pruned=N` / `bound_hits=N` は **`StageResult.note` に
    しか出ない** (ledger は ② の戻り値に含まれない)。ここを落とすと、診断ゲートも箱拘束も
    「有効にしたのに結果に何も現れない」機能になり、③ から見て存在しないのと同じになる。
    """
    def _noted(inp):
        return AutoRietveldResult(
            stage_results=(
                StageResult(label="S1", rwp=12.0, gof=1.2, n_params=9, converged=True,
                            note="unconverged; bound_hits=2"),
            ),
            final_rwp=12.0, final_gof=1.2,
            refined_cells={"ph": (9.37, 9.37, 6.89, 90.0, 90.0, 120.0)},
            validity=ValidityReport(passed=True),
        )

    out = auto_rietveld([_H], [_P], runner=_noted)

    json.dumps(out, allow_nan=False)
    assert out["stages"][0]["note"] == "unconverged; bound_hits=2"


def test_box_bound_spec_reaches_the_real_runner(monkeypatch):
    """③ が JSON で送った**箱拘束** (WS-2) が既定 runner まで届く (REQ-SAR-201/202)。

    【目的】: ① に実装した箱拘束が ② から到達可能であること。診断ゲートと同じ `stability`
    引数に同居させたので、そこが本当に配線されているかを別途見る (同居 ≠ 到達可能)。
    """
    from tsumugin.autorietveld import StabilityOptions
    import tsumugin.mcp.rietveld_tools as rt

    seen: dict = {}
    monkeypatch.setattr(
        rt, "_default_gsas_runner",
        lambda seed, max_cyc=12, stability=None: seen.update(stability=stability) or _stub_runner,
    )

    out = rt.auto_rietveld(
        [_H], [_P],
        stability={"bound_cell": 0.05, "bound_displacement": 5000.0, "bound_size_strain": True},
    )

    assert "error" not in out
    assert seen["stability"] == StabilityOptions(
        bound_cell=0.05, bound_displacement=5000.0, bound_size_strain=True
    )
    assert seen["stability"].has_box_bounds is True


def test_enabling_restraints_without_reporting_degrades_to_an_error_dict():
    """② は例外を送出しない — REQ-SAR-203 の前提違反も error dict へ縮退する。

    【目的】: ③ は LLM なので例外は回復不能なハード失敗になる。かつ**黙って片肺で走らせない**
    (拘束は実質的に母数を増やすので、何が決まらなかったかを報告しない構成は認めない)。
    """
    out = auto_rietveld([_H], [_P], stability={"enable_restraints": True})

    assert out["error_type"] == "ValueError"
    assert "report_undetermined" in out["error"]


def test_the_renamed_prune_key_degrades_to_an_error_dict():
    """旧 ``prune_weak_vars`` を送ったら error dict になること (黙って無視しない)。

    【目的】: 意味が変わった (毎段永続凍結 → 観測/報告/救済の分離) キーを黙殺すると、
    ③ から見て「凍結しているつもりで凍結していない」逆向きの静かな失敗になる。
    """
    out = auto_rietveld([_H], [_P], stability={"prune_weak_vars": True})

    assert out["error_type"] == "ValueError"
    assert "prune_weak_vars" in out["error"]


def test_undetermined_parameters_reach_the_third_layer_with_their_numbers():
    """「決まらなかったパラメータ」が ② の出力に**値ごと**届くこと (REQ-SAR-103 の本体)。

    【目的】: ① で持っているだけでは ③ にとって存在しない (★ 不変条件)。所見として使うには
    名前だけでなく値と esd が要る (「どれくらい決まっていないか」が判断材料)。
    """
    from tsumugin.autorietveld.diagnostics import WeakVariable
    from tsumugin.autorietveld.model import FinalPolish

    def runner(_inp: AnalysisInput) -> AutoRietveldResult:
        return AutoRietveldResult(
            stage_results=(),
            final_rwp=9.86,
            final_gof=1.1,
            refined_cells={},
            validity=ValidityReport(passed=True),
            undetermined_parameters=(
                WeakVariable(name="0::AUiso:4", value=0.004, esd=0.012, ratio=3.0),
            ),
            undetermined_exempt=(
                WeakVariable(name="0::dAx:3", value=1e-6, esd=0.002, ratio=2000.0),
            ),
            frozen_parameters=("0::AUiso:4",),
            final_polish=FinalPolish(
                applied=True, frozen=("0::AUiso:4",), rwp_before=9.80, rwp_after=9.86
            ),
        )

    out = auto_rietveld([_H], [_P], runner=runner)
    json.dumps(out, allow_nan=False)

    assert out["undetermined_parameters"] == [
        {"name": "0::AUiso:4", "value": 0.004, "esd": 0.012, "ratio": 3.0}
    ]
    # 判定対象外にした変数も**捨てずに**届く (何を見なかったかを隠さない)。
    assert [w["name"] for w in out["undetermined_exempt"]] == ["0::dAx:3"]
    # 出版値が「一部を凍結した fit」のものであることが結果から判別できる。
    assert out["frozen_parameters"] == ["0::AUiso:4"]
    assert out["final_polish"]["applied"] is True
    assert out["final_polish"]["rwp_before"] == 9.80
    assert out["final_polish"]["rwp_after"] == 9.86


def test_a_run_without_diagnostics_does_not_claim_everything_was_determined():
    """診断を要求していない run で「決まらなかったパラメータは無い」と読ませない。

    【目的】: ② 不変条件「空/不正入力を『正常』と答えない」。キーは常に在るが空であり、
    それは *診断していない* の意味である — `final_polish` は null で区別できる。
    """
    out = auto_rietveld([_H], [_P], runner=_stub_runner)

    assert out["undetermined_parameters"] == []
    assert out["frozen_parameters"] == []
    assert out["final_polish"] is None


def test_unknown_stability_key_degrades_to_an_error_dict():
    # 【目的】: ② は例外を送出しない。かつ**黙って無視しない** — キー名を間違えたまま
    #   「ゲートを有効にしたつもり」で回るのが最悪 (静かな失敗)。
    out = auto_rietveld([_H], [_P], stability={"require_convergance": True})

    assert out["error_type"] == "ValueError"
    assert "require_convergance" in out["error"]


def test_refine_with_revisions_accepts_the_same_stability_spec(monkeypatch):
    from tsumugin.autorietveld import StabilityOptions
    import tsumugin.mcp.rietveld_tools as rt

    seen: dict = {}
    monkeypatch.setattr(
        rt, "_default_gsas_runner",
        lambda seed, max_cyc=12, stability=None: seen.update(stability=stability) or _stub_runner,
    )

    out = rt.refine_with_revisions(
        [_H], [_P], [], stability={"detect_noop_stages": True}
    )

    assert "error" not in out
    assert seen["stability"] == StabilityOptions(detect_noop_stages=True)
