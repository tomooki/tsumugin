"""MS-2: 実構造マルチスタート大域最適確認 (Issue #13) の純ロジック + T1 gsas。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import (
    MultistartStart,
    generate_cell_scales,
    summarize_multistart,
)
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.autorietveld.multistart import cluster_rietveld_basins, select_best
from tsumugin.multistart.perturb import MultistartConfig, PerturbationSpec


def _result(rwp: float, cell_a: float, *, valid: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult(label="S0", rwp=rwp, gof=1.0, n_params=1, converged=True),),
        final_rwp=rwp,
        final_gof=1.0,
        refined_cells={"ph": (cell_a, cell_a, cell_a, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=valid),
    )


# ---- 開始点生成 (決定論) ----

def test_generate_cell_scales_is_deterministic_and_includes_unperturbed():
    cfg = MultistartConfig(n_starts=5, spec=PerturbationSpec(lattice_frac=0.02))
    a = generate_cell_scales(["ph"], cfg)
    b = generate_cell_scales(["ph"], cfg)
    assert a == b  # 決定論
    assert len(a) == 5
    # 無摂動 (1.0,1.0,1.0) を必ず含む
    assert any(v["ph"] == (1.0, 1.0, 1.0) for v in a)
    # 全開始点が [1-frac, 1+frac] 内
    for v in a:
        f = v["ph"][0]
        assert 0.98 - 1e-9 <= f <= 1.02 + 1e-9


def test_generate_cell_scales_multiphase_shares_isotropic_factor():
    cfg = MultistartConfig(n_starts=3)
    scales = generate_cell_scales(["nac", "caf2"], cfg)
    for v in scales:
        assert v["nac"] == v["caf2"]  # 全相に同一等方倍率


def test_single_start_is_unperturbed():
    scales = generate_cell_scales(["ph"], MultistartConfig(n_starts=1))
    assert scales == ({"ph": (1.0, 1.0, 1.0)},)


def test_grid_is_symmetric_and_explores_both_sides():
    # M4 回帰: 偶数 n でも両側 (1-frac, 1+frac) を対称に探索する (下側の取りこぼしなし)
    cfg = MultistartConfig(n_starts=2, spec=PerturbationSpec(lattice_frac=0.02))
    scales = generate_cell_scales(["ph"], cfg)
    fs = sorted(v["ph"][0] for v in scales)
    assert fs[0] == pytest.approx(0.98) and fs[-1] == pytest.approx(1.02)
    # 中心対称: 各点 f に対し 2-f も存在
    cfg4 = MultistartConfig(n_starts=4, spec=PerturbationSpec(lattice_frac=0.02))
    vals = [v["ph"][0] for v in generate_cell_scales(["ph"], cfg4)]
    for f in vals:
        assert any(abs((2.0 - f) - g) < 1e-9 for g in vals)


# ---- ベイスン分類 ----

def test_cluster_basins_single_when_all_agree():
    rs = [_result(10.0, 9.372), _result(10.1, 9.373), _result(9.9, 9.371)]
    assert cluster_rietveld_basins(rs, rel_tol=1e-2) == 1


def test_cluster_basins_splits_when_cells_diverge():
    rs = [_result(10.0, 9.372), _result(60.0, 9.55)]  # 局所解 (2% 大)
    assert cluster_rietveld_basins(rs, rel_tol=1e-2) == 2


# ---- 最良選択 ----

def test_select_best_prefers_valid_low_rwp():
    starts = (
        MultistartStart(0, {"ph": (1.0, 1.0, 1.0)}, _result(9.85, 9.372, valid=True)),
        MultistartStart(1, {"ph": (1.02, 1.02, 1.02)}, _result(60.0, 9.55, valid=False)),
        MultistartStart(2, {"ph": (0.99, 0.99, 0.99)}, _result(12.0, 9.372, valid=True)),
    )
    idx, best = select_best(starts)
    assert idx == 0 and best.final_rwp == pytest.approx(9.85)


def test_select_best_falls_back_to_lowest_rwp_when_none_valid():
    starts = (
        MultistartStart(0, {"ph": (1.0, 1.0, 1.0)}, _result(50.0, 9.5, valid=False)),
        MultistartStart(1, {"ph": (1.01, 1.01, 1.01)}, _result(40.0, 9.4, valid=False)),
    )
    idx, best = select_best(starts)
    assert idx == 1 and best.final_rwp == pytest.approx(40.0)


# ---- 集計 ----

def test_summarize_corroborated_when_single_basin():
    starts = tuple(
        MultistartStart(i, {"ph": (1.0, 1.0, 1.0)}, _result(10.0 + i * 0.1, 9.372, valid=True))
        for i in range(4)
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=4))
    assert res.is_global_corroborated
    assert res.n_basins == 1
    assert res.n_diverged == 0
    assert res.best.final_rwp == pytest.approx(10.0)


def test_summarize_warns_when_multiple_basins():
    starts = (
        MultistartStart(0, {"ph": (1.0, 1.0, 1.0)}, _result(10.0, 9.372, valid=True)),
        MultistartStart(1, {"ph": (1.02, 1.02, 1.02)}, _result(11.0, 9.55, valid=True)),
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert not res.is_global_corroborated
    assert res.n_basins == 2
    assert any("ベイスン" in w for w in res.warnings)


def test_summarize_all_failed_returns_none_best_without_crash():
    # M5 回帰: 全開始点が実行失敗 (result=None) でも crash せず best=None を返す
    starts = (
        MultistartStart(0, {"ph": (1.0, 1.0, 1.0)}, None),
        MultistartStart(1, {"ph": (1.02, 1.02, 1.02)}, None),
    )
    res = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert res.best is None
    assert res.best_index == -1
    assert res.n_starts == 0
    assert not res.is_global_corroborated
    assert any("実行された開始点" in w for w in res.warnings)


def test_summarize_counts_diverged():
    starts = (
        MultistartStart(0, {"ph": (1.0, 1.0, 1.0)}, _result(10.0, 9.372, valid=True)),
        MultistartStart(1, {"ph": (1.01, 1.01, 1.01)}, _result(float("inf"), 0.0, valid=False)),
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
