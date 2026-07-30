"""② `auto_rietveld` から**収束確認** (規定の標準経路 Phase A → Phase B) への到達可能性。

★不変条件 (CLAUDE.md): ① に機能を足したら**同じ PR で ② へ露出させる**。③ は JSON しか
送れないので、`optimize_then_confirm` を Python から呼べることは「呼び手が存在する」ことを
意味しない。本テストは ``multistart`` spec が**スカラだけ**で届き (他ツールの出力を要しない
= §4.5 到達可能性)、返り値に **何が収束し何が初期値依存か**が載ることを固定する。
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
from tsumugin.autorietveld.multistart import (
    MultistartStart,
    RietveldMultistartResult,
    StartPerturbation,
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


def _result(rwp: float) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(
            StageResult(label="S1", rwp=rwp, gof=1.5, n_params=30, converged=True),
        ),
        final_rwp=rwp,
        final_gof=1.5,
        refined_cells={"ph": (10.0, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        n_obs=4000,
    )


def _rwp_by_name(mapping: dict[str, float]):
    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        return _result(mapping.get(candidate.name, 20.0))

    return runner


def _install_fake_multistart(
    monkeypatch,
    *,
    best_rwp: float = 9.5,
    class_convergence: dict[str, str] | None = None,
    dependent: tuple[str, ...] = (),
    seen: dict | None = None,
):
    """Phase B を差し替える (実 GSAS を回さずに ② の配線だけを見る)。"""

    def fake(histograms, phases, **kwargs):
        if seen is not None:
            seen.update(kwargs)
            seen["histograms"] = list(histograms)
        best = _result(best_rwp)
        starts = tuple(
            MultistartStart(
                index=i,
                perturbation=StartPerturbation(cell_scale={"ph": (1.0, 1.0, 1.0)}),
                result=best,
            )
            for i in range(2)
        )
        return RietveldMultistartResult(
            best=best,
            best_index=0,
            starts=starts,
            n_starts=2,
            n_diverged=0,
            n_basins=1 if not dependent else 2,
            is_global_corroborated=not dependent,
            corroboration_reason="corroborated" if not dependent else "multiple_basins",
            class_convergence=class_convergence
            or {"cell": "AGREE", "coord": "AGREE", "occupancy": "AGREE"},
            initial_value_dependent=dependent,
        )

    monkeypatch.setattr("tsumugin.autorietveld.confirm.run_multistart_rietveld", fake)


def test_multistart_spec_reaches_the_standard_route_with_scalars_only(monkeypatch):
    """★JSON のスカラだけで規定の標準経路へ届くこと (§4.5 到達可能性)。"""
    seen: dict = {}
    _install_fake_multistart(monkeypatch, seen=seen)

    out = auto_rietveld(
        [_H], [_P],
        search=["default", "polish"],
        multistart={"n_starts": 5, "lattice_frac": 0.007,
                    "coord_jitter_ang": 0.05, "jitter_seed": 0, "jobs": 5},
        search_runner=_rwp_by_name({"default": 9.81, "polish": 9.67}),
    )

    assert "error" not in out
    conv = out["convergence"]
    assert conv["adopted_recipe"] == "polish", "Phase A の採用手順が返ること"
    assert conv["structure_is_corroborated"] is True
    assert conv["class_convergence"]["cell"] == "AGREE"
    # スカラ引数が Phase B へ実際に届いている (受け取って捨てていない)。
    assert seen["coord_jitter_ang"] == 0.05
    assert seen["jobs"] == 5
    json.dumps(out, allow_nan=False)


def test_the_payload_keeps_the_normal_shape(monkeypatch):
    """★返り値は通常の `auto_rietveld` と同じ形 + ``search``/``convergence``。

    非トートロジー: ③ が「収束確認したときだけ別の読み方をする」必要が出ると、手順書の
    分岐が増えて必ずどこかで読み違える。探索 (`search`) と同じ規律を守る。
    """
    _install_fake_multistart(monkeypatch)
    out = auto_rietveld(
        [_H], [_P], multistart={"n_starts": 3},
        search_runner=_rwp_by_name({"default": 9.81}),
    )
    for key in ("final_rwp", "final_gof", "stages", "validity", "specs"):
        assert key in out, key
    assert "search" in out and "convergence" in out


def test_final_values_come_from_the_confirmation_not_the_single_shot(monkeypatch):
    """★``final_rwp`` は収束確認の最良フィット。

    非トートロジー: 単発 (Phase A) の結果を返すと、確認のために回した 5 開始点分の計算を
    捨てることになる。同じ手順で複数点走らせた最良は単発と常に同等以上である。
    """
    _install_fake_multistart(monkeypatch, best_rwp=9.10)
    out = auto_rietveld(
        [_H], [_P], multistart={"n_starts": 3},
        search_runner=_rwp_by_name({"default": 9.81}),
    )
    assert out["final_rwp"] == pytest.approx(9.10)


def test_undetermined_values_are_named_not_hidden(monkeypatch):
    """★初期値依存で割れた値は**名指しで**返る (出版してはならない値)。

    非トートロジー: `structure_is_corroborated` だけを返すと、③ は「歪は決まっていない」を
    知らないまま size/mustrain を報告できてしまう。esd が付いているだけに「決まった値」と
    読まれるのが最悪の失敗形なので、名前を返すことが露出の要件になる。
    """
    _install_fake_multistart(
        monkeypatch,
        class_convergence={"cell": "AGREE", "coord": "AGREE", "occupancy": "AGREE",
                           "microstructure": "DISAGREE"},
        dependent=("ph.hist0.size",),
    )
    out = auto_rietveld(
        [_H], [_P], multistart={"n_starts": 3},
        search_runner=_rwp_by_name({"default": 9.81}),
    )
    conv = out["convergence"]
    assert conv["structure_is_corroborated"] is True, "構造は収束 = 解は採用してよい"
    assert conv["is_corroborated"] is False, "全クラスの厳密 AND は False のまま"
    assert conv["undetermined_by_initial_values"] == ["ph.hist0.size"]
    assert any("出版してはならない" in w for w in conv["warnings"])


def test_unknown_multistart_key_is_a_loud_error(monkeypatch):
    """★未知キーは error dict へ縮退する (黙って既定値で走らない)。"""
    _install_fake_multistart(monkeypatch)
    out = auto_rietveld(
        [_H], [_P], multistart={"n_start": 5},  # typo
        search_runner=_rwp_by_name({"default": 9.81}),
    )
    assert out["error_type"] == "ValueError"
    assert "n_start" in out["error"]


def test_extra_stages_with_multistart_is_refused(monkeypatch):
    """★運べない引数を黙って捨てない。

    非トートロジー: 収束確認は候補を**名前**で固定するので追加段階を運ぶ口が無い。黙って
    無視すると「追加段階つきで確認した」と読まれるが、実際に確認したのは別の手順である。
    """
    _install_fake_multistart(monkeypatch)
    out = auto_rietveld(
        [_H], [_P],
        stages=[{"label": "extra", "flags": {"cell": True}}],
        multistart={"n_starts": 3},
        search_runner=_rwp_by_name({"default": 9.81}),
    )
    assert out["error_type"] == "ValueError"
    assert "extra_stages" in out["error"]


def test_a_total_search_failure_does_not_pretend_to_have_confirmed():
    """★手順が 1 つも立たなければ「収束確認していない」と言う (捏造した傍証を出さない)。"""

    def boom(candidate: RecipeCandidate) -> AutoRietveldResult:
        raise RuntimeError("boom")

    out = auto_rietveld([_H], [_P], multistart={"n_starts": 3}, search_runner=boom)
    assert out["error_type"] == "ConvergenceNotAttempted"
    assert out["convergence"]["structure_is_corroborated"] is False


def test_multistart_without_search_still_optimizes_the_procedure(monkeypatch):
    """★`multistart` 単独でも Phase A を回す (規定は「手順最適化 → 収束確認」)。

    非トートロジー: 探索せずに収束確認すると、**決めていない手順**を確認することになる。
    どの手順を確認したのかが返り値から言えなくなるのが実害。
    """
    seen_names: list[str] = []

    def runner(candidate: RecipeCandidate) -> AutoRietveldResult:
        seen_names.append(candidate.name)
        return _result(9.81 + len(seen_names) * 0.01)

    _install_fake_multistart(monkeypatch)
    out = auto_rietveld([_H], [_P], multistart={"n_starts": 3}, search_runner=runner)

    from tsumugin.autorietveld.search import DEFAULT_CANDIDATES

    # 実行された候補は既定集合の中身であり、既定集合を先頭から辿っている
    # (`adaptive` は実データを読んでレンジを決めるのでスタブ入力では立たない)。
    assert seen_names, "Phase A が回ること"
    assert seen_names == [n for n in DEFAULT_CANDIDATES if n in seen_names]
    assert set(seen_names) <= set(DEFAULT_CANDIDATES)
    assert out["convergence"]["adopted_recipe"] in DEFAULT_CANDIDATES
