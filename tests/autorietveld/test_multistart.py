"""MS-2: 実構造マルチスタート大域最適確認 (Issue #13) の純ロジック + T1 gsas。"""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from tsumugin.autorietveld import MultistartStart
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.autorietveld.multistart import (
    StartPerturbation,
    generate_perturbations,
    select_best,
    summarize_multistart,
)
from tsumugin.multistart.perturb import MultistartConfig, PerturbationSpec



def _pert(scale: dict) -> StartPerturbation:
    """旧テストの `cell_scale` dict を `StartPerturbation` へ包む補助。"""
    return StartPerturbation(cell_scale=scale)

def _result(rwp: float, cell_a: float, *, valid: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=rwp, gof=1.0, n_params=1, converged=True),),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"ph": (cell_a, cell_a, cell_a, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=valid),
    )


# ---- 開始点生成 (決定論) ----



# ---- 最良選択 ----

def test_select_best_prefers_valid_low_rwp():
    starts = (
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(9.85, 9.372, valid=True)),
        MultistartStart(1, _pert({"ph": (1.02, 1.02, 1.02)}), _result(60.0, 9.55, valid=False)),
        MultistartStart(2, _pert({"ph": (0.99, 0.99, 0.99)}), _result(12.0, 9.372, valid=True)),
    )
    idx, best = select_best(starts)
    assert idx == 0 and best.final_rwp == pytest.approx(9.85)


def test_select_best_falls_back_to_lowest_rwp_when_none_valid():
    starts = (
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(50.0, 9.5, valid=False)),
        MultistartStart(1, _pert({"ph": (1.01, 1.01, 1.01)}), _result(40.0, 9.4, valid=False)),
    )
    idx, best = select_best(starts)
    assert idx == 1 and best.final_rwp == pytest.approx(40.0)


# ---- 集計 ----

def test_summarize_corroborated_when_single_basin():
    starts = tuple(
        MultistartStart(i, _pert({"ph": (1.0, 1.0, 1.0)}), _result(10.0 + i * 0.1, 9.372, valid=True))
        for i in range(4)
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=4))
    assert res.is_global_corroborated
    assert res.n_basins == 1
    assert res.n_diverged == 0
    assert res.best.final_rwp == pytest.approx(10.0)


def test_summarize_warns_when_multiple_basins():
    starts = (
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(10.0, 9.372, valid=True)),
        MultistartStart(1, _pert({"ph": (1.02, 1.02, 1.02)}), _result(11.0, 9.55, valid=True)),
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert not res.is_global_corroborated
    assert res.n_basins == 2
    assert any("ベイスン" in w for w in res.warnings)


def test_summarize_all_failed_returns_none_best_without_crash():
    # M5 回帰: 全開始点が実行失敗 (result=None) でも crash せず best=None を返す
    starts = (
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), None),
        MultistartStart(1, _pert({"ph": (1.02, 1.02, 1.02)}), None),
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert res.best is None
    assert res.best_index == -1
    assert res.n_starts == 0
    assert not res.is_global_corroborated
    assert any("実行された開始点" in w for w in res.warnings)


def test_summarize_counts_diverged():
    starts = (
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(10.0, 9.372, valid=True)),
        MultistartStart(1, _pert({"ph": (1.01, 1.01, 1.01)}), _result(float("inf"), 0.0, valid=False)),
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert res.n_diverged == 1


# ---- 実データ (gsas) ----

_DATA = Path("docs/benchmark/testdata/m7/labdata")


@pytest.mark.gsas
@pytest.mark.skipif(
    not (_DATA / "FAP.XRA").exists(), reason="M7 T1 データ未取得"
)
def test_t1_multistart_corroborates_global_optimum():
    from tsumugin.autorietveld import (
        Geometry,
        HistogramSpec,
        PhaseSpec,
        Radiation,
        run_multistart_rietveld,
    )

    h = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    p = PhaseSpec(structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP")
    # 小さめ摂動 (±0.7%) で大域最適に収束する開始点が多数を占めることを確認
    cfg = MultistartConfig(n_starts=3, spec=PerturbationSpec(lattice_frac=0.007))
    res = run_multistart_rietveld([h], [p], config=cfg)

    assert res.n_starts == 3
    # 最良は tutorial 級 (Rwp <= 12%) で物理的
    assert res.best.final_rwp <= 12.0
    assert res.best.validity.passed
    assert 9.30 < res.best.refined_cells["fap"][0] < 9.45
    # 少なくとも 1 開始点が valid に収束している
    assert res.n_basins >= 1


# ---------------------------------------------------------------------------
# 傍証の空虚な True を塞ぐ (レビュー由来)
# ---------------------------------------------------------------------------


def test_a_single_valid_start_is_never_corroboration():
    """★開始点 1 つで「大域最適の傍証あり」と名乗ってはならない。

    非トートロジー: 単一の結果は必ず 1 クラスタになるので ``n_basins == 1`` だけを条件に
    すると**摂動を 1 つも振っていない run が傍証を主張できる**。傍証の意味は「複数の独立な
    出発点が同じ解へ来た」であって「クラスタが 1 つ」ではない。
    """
    starts = [MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(9.0, 9.372))]
    got = summarize_multistart(starts, MultistartConfig(n_starts=1))

    assert got.n_basins == 1
    assert got.is_global_corroborated is False
    assert any("1 ベイスン" in w for w in got.warnings), "理由を述べずに False にしない"


def test_diverged_starts_prevent_corroboration():
    """★4 点中 3 点が発散して 1 点だけ valid、を傍証にしてはならない。

    非トートロジー: 旧実装は `n_diverged` を記録するだけで判定に使っておらず、
    「ほとんど失敗したが残った 1 つが 1 ベイスン」を傍証として通していた。
    """
    starts = [
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(9.0, 9.372)),
        MultistartStart(1, _pert({"ph": (1.01, 1.01, 1.01)}), _result(9.0, 9.372)),
        MultistartStart(2, _pert({"ph": (0.99, 0.99, 0.99)}), _result(float("inf"), 9.372, valid=False)),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=3))

    assert got.n_basins == 1 and got.n_diverged == 1
    assert got.is_global_corroborated is False
    assert any("発散" in w for w in got.warnings)


def test_two_agreeing_valid_starts_with_no_divergence_do_corroborate():
    # 【目的】: 上 2 件が「常に False」へ縮退していないことの対照 (過剰に厳しくしていない)。
    starts = [
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(9.0, 9.372)),
        MultistartStart(1, _pert({"ph": (1.01, 1.01, 1.01)}), _result(9.1, 9.372)),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert got.is_global_corroborated is True


# ---------------------------------------------------------------------------
# Phase B: 多軸の開始点生成 + agreement 委譲
# ---------------------------------------------------------------------------


def test_generate_perturbations_keeps_the_deterministic_lattice_grid():
    """格子軸は現行の対称グリッドを踏襲する (奇数本なら中央が無摂動)。"""
    cfg = MultistartConfig(n_starts=5, spec=PerturbationSpec(lattice_frac=0.02))
    perts = generate_perturbations(["ph"], cfg)

    factors = [p.cell_scale["ph"][0] for p in perts]
    assert factors == sorted(factors)
    assert factors[2] == 1.0, "奇数本は中央に無摂動を含む"
    assert factors[0] == pytest.approx(0.98) and factors[-1] == pytest.approx(1.02)


def test_each_start_gets_a_distinct_seed_so_coordinates_differ():
    """★座標軸は開始点ごとに**違う種**を持つこと。

    非トートロジー: 同じ種だと全開始点が同じ座標摂動になり、格子だけ違う開始点になる =
    「構造の局所解を試験した」と言えなくなる。
    """
    cfg = MultistartConfig(n_starts=5)
    perts = generate_perturbations(["ph"], cfg, coord_jitter_ang=0.05)

    seeds = [p.jitter_seed for p in perts]
    assert len(set(seeds)) == 5
    assert len({p.key for p in perts}) == 5, "開始点キーも全部違う"


def test_generate_perturbations_is_deterministic():
    cfg = MultistartConfig(n_starts=5)
    a = generate_perturbations(["ph"], cfg, coord_jitter_ang=0.05, seed=3)
    b = generate_perturbations(["ph"], cfg, coord_jitter_ang=0.05, seed=3)
    assert [p.key for p in a] == [p.key for p in b]
    c = generate_perturbations(["ph"], cfg, coord_jitter_ang=0.05, seed=4)
    assert [p.key for p in a] != [p.key for p in c]


def test_zero_jitter_means_the_coordinate_axis_is_not_exercised():
    perts = generate_perturbations(["ph"], MultistartConfig(n_starts=3))
    assert all(p.coord_jitter_ang == 0.0 for p in perts)


def _jittered(index: int, factor: float, result, n_axes: int = 3) -> MultistartStart:
    return MultistartStart(
        index=index,
        perturbation=StartPerturbation(
            cell_scale={"ph": (factor, factor, factor)},
            coord_jitter_ang=0.05,
            jitter_seed=index,
        ),
        result=result,
        n_axes_jittered=n_axes,
    )


def test_basins_come_from_agreement_and_use_the_start_basis():
    """★ベイスン判定は `agreement` へ委譲し **basis="start"** で呼ぶこと。

    非トートロジー: 全開始点は同じ手順を走るので実効軌跡が同一になる。既定の
    ``"procedure"`` のまま呼ぶと全対が DUPLICATE になり、正しく実装しても
    **傍証が永久に成立しない** (Rwp には現れない壊れ方)。
    """
    starts = [
        _jittered(0, 1.00, _result(9.80, 9.372)),
        _jittered(1, 1.01, _result(9.80, 9.372)),
        _jittered(2, 0.99, _result(9.80, 9.372)),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=3))

    assert got.agreement is not None
    assert got.n_basins == 1
    assert got.is_global_corroborated is True
    assert got.corroboration_reason == "corroborated"


def test_a_requested_jitter_that_moved_nothing_is_not_corroboration():
    """★座標摂動を要求したのに動かせた軸が 0 なら**その軸では試験していない**。

    非トートロジー: 高対称構造では全軸が対称固定になり得る。そのとき開始点は実質同じもの
    なので、単一ベイスンでも傍証にはならない (`n_basins == 1` の空虚な True と同型)。
    """
    starts = [
        _jittered(0, 1.00, _result(9.80, 9.372), n_axes=0),
        _jittered(1, 1.01, _result(9.80, 9.372), n_axes=0),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))

    assert got.n_basins == 1 and got.n_axes_jittered == 0
    assert got.is_global_corroborated is False
    assert got.corroboration_reason == "perturbation_had_no_effect"
    assert any("試験していない" in w for w in got.warnings)


def test_lattice_only_multistart_is_not_penalised_for_zero_jitter():
    """【対照】座標摂動を要求していなければ 0 軸でも傍証を妨げない (格子だけの試験は有効)。"""
    starts = [
        MultistartStart(0, _pert({"ph": (1.0, 1.0, 1.0)}), _result(9.80, 9.372)),
        MultistartStart(1, _pert({"ph": (1.01, 1.01, 1.01)}), _result(9.80, 9.372)),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert got.is_global_corroborated is True


def test_summary_dict_is_json_safe_and_names_the_failing_condition():
    starts = [_jittered(0, 1.0, _result(9.8, 9.372))]
    got = summarize_multistart(starts, MultistartConfig(n_starts=1))
    payload = got.to_dict()
    json.dumps(payload, allow_nan=False)
    assert payload["corroboration_reason"] == "insufficient_valid_starts"


def test_matching_structure_with_a_large_rwp_spread_is_not_corroboration():
    """★構造が一致していても Rwp が離れていれば**同じ最小点ではない**。

    非トートロジー: T1 の実測でまさにこれが起きた — ±0.7% の格子摂動 3 点で、格子/座標/
    占有率/Uiso は**全クラス AGREE** なのに ``hist0.U`` が z=4634 で割れ、Rwp が
    **9.81 / 12.54 / 19.59** になった。構造クラスだけを見ると「同じ解」に見えるが、
    目的関数の値が 10 ポイント違う 2 点を「収束した」と呼ぶのは誤りである。

    プロファイルを一致条件から外した根拠 (平坦な相関谷) には「**同じ Rwp で**谷の別の点に
    落ちる」という隠れた前提があり、Rwp が離れている時点でその前提が破れている。
    """
    starts = [
        _jittered(0, 1.00, _result(9.81, 9.372)),
        _jittered(1, 1.01, _result(19.59, 9.372)),   # 同じ構造・全く違うフィット
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))

    assert got.n_basins == 1, "前提: 構造クラスは一致している"
    assert got.is_global_corroborated is False
    assert got.corroboration_reason == "rwp_spread"
    assert got.rwp_spread == pytest.approx(9.78)
    assert any("同じ最小点ではない" in w for w in got.warnings)


def test_a_small_rwp_spread_still_corroborates():
    """【対照】ばらつきが小さければ傍証は成立する (常に False へ縮退していないこと)。"""
    starts = [
        _jittered(0, 1.00, _result(9.8060, 9.372)),
        _jittered(1, 1.01, _result(9.8062, 9.372)),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert got.is_global_corroborated is True
    assert got.rwp_spread < 0.5
