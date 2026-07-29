"""② `auto_rietveld` からレシピ探索 (REQ-SAR-500/501) への到達可能性。

★不変条件 (CLAUDE.md): ① に機能を足したら**同じ PR で ② へ露出させる**。③ は JSON しか
送れないので、callable シーム (`search_runner`) だけの経路は「呼び手が存在しない」に等しい。
本テストは ``search`` / ``search_config`` が JSON だけで届き、返り値に候補表と警告が載ること、
そして**採用候補の入力が `specs` に返る** (次の反復へ持ち回れる) ことを固定する。
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
    StageResult,
    ValidityReport,
)
from tsumugin.autorietveld.search import RecipeCandidate
from tsumugin.mcp.rietveld_tools import auto_rietveld

_H = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
).to_dict()
_P = PhaseSpec(structure_path="a.cif", phase_name="ph").to_dict()


def _result(rwp: float, *, converged: bool = True, n_params: int = 30) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(
            StageResult(label="S1", rwp=rwp, gof=1.5, n_params=n_params, converged=converged),
        ),
        final_rwp=rwp,
        final_gof=1.5,
        refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        n_obs=4000,
    )


def _rwp_by_name(mapping: dict[str, float]):
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        return _result(mapping[candidate.name])

    return runner


def test_search_returns_the_selected_result_plus_a_candidate_table():
    out = auto_rietveld(
        [_H], [_P],
        search=["default", "serious"],
        search_runner=_rwp_by_name({"default": 9.81, "serious": 10.45}),
    )

    assert out["final_rwp"] == pytest.approx(9.81)
    assert out["search"]["selected"] == "default"
    assert [c["candidate"]["name"] for c in out["search"]["candidates"]] == [
        "default", "serious"
    ]
    # 段の note と同じ規律で「なぜ選ばれたか」を落とさない (③ の判断材料)。
    assert out["search"]["selection_reason"] in (
        "tier", "observation_set", "rwp", "bic", "only_candidate"
    )


def test_search_true_means_every_candidate():
    seen: list[str] = []

    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        seen.append(candidate.name)
        return _result(9.0)

    auto_rietveld([_H], [_P], search=True, search_runner=runner)

    # adaptive は観測パターンを読めないので立たない (固定層が保険として残る)。
    assert seen == ["default", "serious"]


def test_search_selects_the_converged_candidate_over_a_better_but_unconverged_one():
    # 【目的】: S1 の核心が ② 経由でも効くこと。
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        if candidate.name == "default":
            return _result(6.02, converged=False)
        return _result(6.66, converged=True)

    out = auto_rietveld([_H], [_P], search=["default", "serious"], search_runner=runner)

    assert out["search"]["selected"] == "serious"
    assert out["final_rwp"] == pytest.approx(6.66)


def test_search_config_reaches_the_selection_rule_from_json():
    # 【目的】: 閾値が JSON で届くこと。tie 窓を広げると BIC 裁定に切り替わる。
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        if candidate.name == "default":
            return _result(9.80, n_params=200)
        return _result(9.85, n_params=30)

    narrow = auto_rietveld([_H], [_P], search=["default", "serious"],
                           search_config={"rwp_tie_eps": 0.0}, search_runner=runner)
    wide = auto_rietveld([_H], [_P], search=["default", "serious"],
                         search_config={"rwp_tie_eps": 0.1}, search_runner=runner)

    assert narrow["search"]["selected"] == "default"   # Rwp 最小
    assert wide["search"]["selected"] == "serious"     # BIC 裁定


def test_unknown_search_config_key_degrades_to_an_error_dict():
    # 【② 不変条件】: 例外を送出せず error dict へ縮退。黙って無視すると「閾値を変えたつもり」
    #   が静かに効かない。
    out = auto_rietveld([_H], [_P], search=True, search_config={"rwp_tie_epss": 0.1},
                        search_runner=_rwp_by_name({"default": 9.0, "serious": 9.0}))

    assert "error" in out and out["error_type"] == "ValueError"


def test_unknown_candidate_name_degrades_to_an_error_dict():
    out = auto_rietveld([_H], [_P], search=["defualt"],
                        search_runner=_rwp_by_name({"default": 9.0}))

    assert "error" in out and "未知" in out["error"]


def test_all_candidates_failing_degrades_to_an_error_dict_not_a_fake_best():
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        raise RuntimeError("boom")

    out = auto_rietveld([_H], [_P], search=["default", "serious"], search_runner=runner)

    assert out["error_type"] == "RecipeSearchFailed"
    assert out["search"]["selected_index"] == -1


def test_order_dependence_warning_is_visible_through_the_boundary():
    # 【目的】: REQ-SAR-501 の警告が ③ に届くこと (届かなければ「信頼度を言える」利点が消える)。
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        res = _result(9.80 if candidate.name == "default" else 9.85)
        if candidate.name == "serious":
            res = AutoRietveldResult(
                stage_results=res.stage_results, final_rwp=res.final_rwp,
                final_gof=res.final_gof,
                refined_cells={"ph": (10.5, 10.0, 10.0, 90.0, 90.0, 90.0)},
                validity=res.validity, n_obs=res.n_obs,
            )
        return res

    out = auto_rietveld([_H], [_P], search=["default", "serious"], search_runner=runner)

    assert out["search"]["order_dependent"] is True
    assert any("順序依存" in w for w in out["search"]["warnings"])


def test_search_payload_is_json_safe():
    out = auto_rietveld([_H], [_P], search=["default", "serious"],
                        search_runner=_rwp_by_name({"default": 9.0, "serious": float("inf")}))

    json.dumps(out, allow_nan=False)


def test_default_call_without_search_is_unchanged():
    # 【非回帰】: 探索は opt-in。既定は現行と完全に同一の形 (``search`` キーも生えない)。
    out = auto_rietveld([_H], [_P], runner=lambda inp: _result(9.0))

    assert "search" not in out
    assert out["final_rwp"] == pytest.approx(9.0)


def test_selected_candidate_inputs_come_back_in_specs_for_the_next_iteration():
    # 【② 到達可能性】: 採用候補の入力が返らないと、次の `refine_with_revisions` は
    #   別の土俵 (元のレンジ/背景) で走ってしまう。
    out = auto_rietveld([_H], [_P], background_coeffs=12, search=["serious"],
                        search_runner=_rwp_by_name({"serious": 9.0}))

    assert out["specs"]["background_coeffs"] == 12
    assert out["specs"]["histograms"][0]["data_path"] == "d.xra"


def test_single_name_search_is_the_json_route_to_a_full_recipe_replacement():
    # 【目的】: 探索で勝ったレシピ ("serious") を次の反復でも使い続ける唯一の JSON 経路。
    seen: list[str] = []

    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        seen.append(candidate.name)
        return _result(9.0)

    auto_rietveld([_H], [_P], search=["serious"], search_runner=runner)

    assert seen == ["serious"]
    assert len(_serious_stage_count()) > 7  # 既定レシピ (7 段) の置換であること


def _serious_stage_count():
    from tsumugin.autorietveld.model import Geometry as G
    from tsumugin.autorietveld.model import HistogramSpec as H
    from tsumugin.autorietveld.model import PhaseSpec as P
    from tsumugin.autorietveld.model import Radiation as R
    from tsumugin.autorietveld.recipe import build_serious_recipe

    return build_serious_recipe(
        [H(data_path="d", instrument_path="i", radiation=R.XRAY_LAB,
           geometry=G.BRAGG_BRENTANO)],
        [P(structure_path="a.cif", phase_name="ph")],
    )
