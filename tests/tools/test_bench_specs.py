"""ベンチマークレジストリ (`tools/bench_specs.py`) の整合 — GSAS 非依存。

ハーネスが gated テストと**違う条件**を測っていると以降の全判断が狂う (実測: T3 の
`temperature=295/10` を落としたら Dij 段が消えて Rwp 6.66% → 12.56% になり「回帰した」と
誤読しかけた)。以前これはコメントでしか担保されていなかった。
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "tools"))

import bench_specs as B  # noqa: E402 — sys.path 調整後


def test_recipes_tuple_is_derived_from_the_registry():
    """★CLI の choices・表の列順・子の dispatch が**同じ列挙順**であること。

    非トートロジー: 以前は親の `RECIPES` タプルと子の if/elif 連鎖が二重管理で、
    片方だけ更新すると「選べるのに実行できない候補」ができた。
    """
    assert B.RECIPES == tuple(B.RECIPE_REGISTRY)
    assert len(B.RECIPES) == len(set(B.RECIPES)), "候補名が重複している"


def test_a0_default_is_enumeration_index_zero():
    """★A0 が index 0 であること。

    非トートロジー: `search.observation_groups` は「最初に結果を返した候補」を観測集合の
    基準にする。A0 が先頭でなければ基準が別物になり、レンジを変えた候補の扱いが変わる。
    """
    assert B.RECIPES[0] == "A0-default"
    assert B.RECIPE_REGISTRY["A0-default"].builder == "default"
    assert not B.RECIPE_REGISTRY["A0-default"].recipe_kwargs
    assert not B.RECIPE_REGISTRY["A0-default"].stability, "基準がゲートを持ってはならない"


def test_the_negative_control_is_excluded_from_selection():
    """★負の対照が 5 案に選ばれ得ないこと (校正器が採用されては困る)。"""
    assert B.RECIPE_REGISTRY["N0-NEGATIVE"].eligible is False
    assert "N0-NEGATIVE" not in B.ELIGIBLE_RECIPES


def test_eligible_count_matches_the_planned_subset_enumeration():
    """★選定は C(eligible, 5) の全列挙で行う。母数がずれたら計画と食い違う。"""
    assert len(B.ELIGIBLE_RECIPES) == 9
    assert math.comb(len(B.ELIGIBLE_RECIPES), 5) == 126


def test_every_candidate_declares_its_axis_and_motivation():
    """★「なぜこの候補か」を言えない候補を置かない (ノブ弄りの禁止)。"""
    for name, build in B.RECIPE_REGISTRY.items():
        assert build.axis, name
        assert len(build.motivation) > 30, f"{name}: 動機が薄い"
        assert build.reference in B.RECIPE_REGISTRY, f"{name}: 基準候補が実在しない"


def test_each_eligible_candidate_moves_exactly_one_axis_from_its_reference():
    """★一案一軸 (「改善は単独で測る」)。基準と同じ軸の候補が 2 つ以上あってはならない。"""
    axes = [b.axis for b in B.RECIPE_REGISTRY.values() if b.eligible and b.axis != "(reference)"]
    assert len(axes) == len(set(axes)), f"軸が重複している: {axes}"


def test_unimplemented_declarations_are_not_used_by_any_candidate():
    """★`heavy_first` / `uiso_tiers` はどの候補にも使わない。

    非トートロジー: engine 側の展開が未実装で `ValueError` → revert になるため、使うと
    **レシピ差ではなく実装欠落を測る**ことになる (Issue #165)。
    """
    for name, build in B.RECIPE_REGISTRY.items():
        kw = build.recipe_kwargs
        assert kw.get("element_expansion") in (None, "ranks"), name
        assert "uiso_tiers" not in kw, name


def test_observe_only_stability_never_changes_the_fit():
    """★観測列に**フィットを変える設定**を入れないこと。

    非トートロジー: `prune_weak_vars_each_stage` は実測で S1 末に背景 6 項を全凍結して以降を
    痩せた母数で走らせた。箱拘束は値を境界へ丸めて凍結する**判断**であって観測ではなく、
    N0 の格子発散を鈍らせて負の対照そのものを壊す。
    """
    forbidden = {
        "prune_weak_vars_each_stage", "require_convergence", "rescue_freeze_on_failure",
        "polish_frozen_undetermined", "bound_cell", "bound_displacement",
        "bound_size_strain", "enable_restraints",
    }
    assert not (set(B.OBSERVE_ONLY_STABILITY) & forbidden)


def test_gated_settings_live_only_on_the_candidates_that_declare_them():
    a5 = B.RECIPE_REGISTRY["A5-gated"].stability
    a6 = B.RECIPE_REGISTRY["A6-polish"].stability
    assert a5.get("require_convergence") is True and a5.get("extra_cycles")
    assert a6.get("polish_frozen_undetermined") is True
    # ゲートを持つのはこの 2 案だけ (観測列は全候補共通なので他は空)。
    gated = {n for n, b in B.RECIPE_REGISTRY.items() if b.is_gated}
    assert gated == {"A5-gated", "A6-polish"}


def test_t4_is_excluded_from_the_campaign_with_a_stated_reason():
    """★除外は宣言する — 黙って外すと「多相/TOF も検証した」と読まれる。"""
    assert "T4" not in B.CAMPAIGN_DATASETS
    assert B.DATASETS["T4"].slow is True
    assert "多相" in B.DATASETS["T4"].excluded_reason


def test_campaign_datasets_cover_the_branches_they_claim():
    assert set(B.CAMPAIGN_DATASETS) == {"T1", "T2", "T3", "CaTeO3"}
    # T2 が混合占有分岐・T3 が温度差 Dij・CaTeO3 が背景 24 項を踏む唯一のデータである、
    # という説明が spec 側に残っていること (次に読む人がカバレッジを再導出できる)。
    assert "混合占有" in B.DATASETS["T2"].note
    assert "温度差" in B.DATASETS["T3"].note or "Dij" in B.DATASETS["T3"].note
    assert "24" in B.DATASETS["CaTeO3"].note


@pytest.mark.parametrize("key", ["T1", "T2", "T3", "CaTeO3"])
def test_background_and_cycles_match_the_gated_engine_tests(key):
    """★spec が gated テストと 1 対 1 であること (ドリフトの実測コスト 6.66 → 12.56)。"""
    spec = B.DATASETS[key]
    assert spec.background_coeffs > 0 and spec.max_cyc > 0
    if key == "CaTeO3":
        assert spec.background_coeffs == 24, "手で与えている 24 項が A3 の動機"
        assert spec.max_cyc == 20
    else:
        assert spec.background_coeffs == 6 and spec.max_cyc == 12
