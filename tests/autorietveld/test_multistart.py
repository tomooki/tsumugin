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
    # 開始点は格子を実際に振っていること (全部 1.0 だと同じ入力 = 空虚な傍証。
    # `test_starts_that_perturb_nothing_are_not_corroboration` 参照)。
    factors = (0.99, 1.0, 1.01, 1.02)
    starts = tuple(
        MultistartStart(i, _pert({"ph": (f, f, f)}), _result(10.0 + i * 0.1, 9.372, valid=True))
        for i, f in enumerate(factors)
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


def test_matching_structure_with_a_large_rwp_spread_still_corroborates():
    """★構造と歪が一致していれば、プロファイル由来の Rwp のばらつきは**傍証を妨げない**。

    非トートロジー: T1 の実測でこれが起きた — ±0.7% の格子摂動 3 点で、格子/座標/占有率は
    全クラス AGREE なのに ``hist0.U`` が z=4634 で割れ Rwp が 9.81/12.54/19.59 になった。
    一度これを「同じ最小点ではない」として傍証条件にしたが**誤り**である: Caglioti U/V/W は
    装置側の nuisance であり、構造と歪が収束していれば**プロファイルは最良フィットを選ぶだけ**
    でよい。解が割れているのではなく当てはめの良し悪しである。

    ただし**黙ってはいけない** — ばらつきは所見として報告し、採用した最良値を明示する。
    """
    starts = [
        _jittered(0, 1.00, _result(9.81, 9.372)),
        _jittered(1, 1.01, _result(19.59, 9.372)),   # 同じ構造・当てはめだけが悪い
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))

    assert got.n_basins == 1
    assert got.is_global_corroborated is True, "構造が一致していれば傍証は成立する"
    assert got.corroboration_reason == "corroborated"
    assert got.rwp_spread == pytest.approx(9.78)
    assert any("最良フィット" in w for w in got.warnings), "ばらつきは黙らず報告する"
    assert got.best.final_rwp == pytest.approx(9.81), "採用は最良フィット"


def test_a_small_rwp_spread_reports_nothing_extra():
    """【対照】ばらつきが小さければ余計な警告を出さない。"""
    starts = [
        _jittered(0, 1.00, _result(9.8060, 9.372)),
        _jittered(1, 1.01, _result(9.8062, 9.372)),
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))
    assert got.is_global_corroborated is True
    assert not any("最良フィット" in w for w in got.warnings)


def test_start_failures_report_why_not_just_that_they_failed():
    """★開始点の失敗**理由**が warnings に残ること。

    非トートロジー: 開始点は子プロセスで走るので `TypeError` などは例外として上がらず
    「結果なし」に化ける。理由を捨てると「収束確認が空振りした」ことは判っても**なぜか**が
    判らない (実測: エンジンが受け取らない引数を渡して全開始点が落ちた。Rwp にも例外にも
    現れなかった)。
    """
    starts = (
        MultistartStart(
            index=0, perturbation=StartPerturbation(cell_scale={"ph": (1.0, 1.0, 1.0)}),
            result=None, error="TypeError: unexpected keyword argument 'background_coeffs'",
        ),
        MultistartStart(
            index=1, perturbation=StartPerturbation(cell_scale={"ph": (1.007, 1.007, 1.007)}),
            result=None, error="TypeError: unexpected keyword argument 'background_coeffs'",
        ),
    )
    got = summarize_multistart(starts, MultistartConfig(n_starts=2))

    assert got.is_global_corroborated is False
    joined = " / ".join(got.warnings)
    assert "2/2 開始点が失敗" in joined, joined
    assert "background_coeffs" in joined, "失敗理由が落ちている"


def test_a_dead_worker_becomes_failed_starts_not_an_exception(monkeypatch):
    """★worker の即死 (`BrokenProcessPool`) を例外として上げない。

    非トートロジー: `_run_one_start` は**自分の中の**例外しか捕まえられない。worker が
    OOM/segfault で落ちると `pool.map` 自身が投げ、その例外は `RuntimeError` の派生なので
    ② `auto_rietveld` の except タプル (ValueError/TypeError/KeyError/IndexError/
    AttributeError) をすり抜けて**MCP の境界を越える** — ③ は LLM なので回復不能なハード
    失敗になる。「バックエンドの失敗は結果に変換する」不変条件は、プロセスが死ぬ場合も同じ。
    """
    from concurrent.futures.process import BrokenProcessPool

    from tsumugin.autorietveld import multistart as ms

    class _DeadPool:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def map(self, fn, payloads):
            raise BrokenProcessPool("A process in the process pool was terminated abruptly")

    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

    monkeypatch.setattr("concurrent.futures.ProcessPoolExecutor", _DeadPool)
    hist = HistogramSpec(
        data_path="d.xra", instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )
    phase = PhaseSpec(structure_path="a.cif", phase_name="ph")

    got = ms.run_multistart_rietveld(
        [hist], [phase], config=MultistartConfig(n_starts=3), jobs=3,
    )

    assert got.best is None and got.best_index == -1
    assert got.is_global_corroborated is False
    assert all(s.result is None for s in got.starts), "全開始点が失敗として記録される"
    joined = " / ".join(got.warnings)
    assert "BrokenProcessPool" in joined, f"死因が落ちている: {joined}"


# ---------------------------------------------------------------------------
# 精密化しないパラメータは摂動しない (refine_cell=False / frozen_coord_labels)
# ---------------------------------------------------------------------------


def _stub_engine(
    monkeypatch, *, moved_axes: int = 0, free_index: dict | None = None
) -> list[dict]:
    """`run_auto_rietveld` を差し替え、開始点が engine へ**何を渡したか**を記録する。

    ``jobs=1`` の直列経路は同じプロセスで `_run_one_start` を呼ぶので差し替えが効く。
    ``moved_axes`` は engine が**実際に動かした**軸数 (`coord_jitter_axes_moved`) として返す。
    """
    from tsumugin.autorietveld import engine

    captured: list[dict] = []

    def fake_run(histograms, phases, **kw):
        captured.append(kw)
        return AutoRietveldResult(
            stage_results=(
                StageResult(label="S0", rwp=9.8, gof=1.0, n_params=1, converged=True),
            ),
            final_rwp=9.8,
            final_gof=1.0,
            refined_cells={"main": (9.372, 9.372, 9.372, 90.0, 90.0, 90.0)},
            validity=ValidityReport(passed=True),
            atom_coord_free_index=free_index or {},
            coord_jitter_axes_moved=moved_axes,
        )

    monkeypatch.setattr(engine, "run_auto_rietveld", fake_run)
    return captured


def _hist():
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation

    return HistogramSpec(
        data_path="d.xra", instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )


def test_frozen_cells_are_neither_perturbed_nor_recorded_as_perturbed(monkeypatch):
    """★`refine_cell=False` の相 (Issue #47 の副相格子固定) の格子を開始点で振らない。

    非トートロジー: cell 段は凍結相に Cell フラグを立てないので、摂動した格子が**そのまま
    最終格子**になる。開始点ごとに違う倍率で固定されるため、標準経路 Phase B は副相の格子差を
    偽のベイスン分岐として報告し、副相のフィットも摂動値で劣化する。記録 (start_key / ledger)
    も実際に掛けた摂動と一致させる — 掛けていない摂動を記録すると監査で嘘をつく。
    """
    from tsumugin.autorietveld.model import PhaseSpec
    from tsumugin.autorietveld.multistart import run_multistart_rietveld

    captured = _stub_engine(monkeypatch)
    phases = [
        PhaseSpec(structure_path="a.cif", phase_name="main"),
        PhaseSpec(structure_path="b.cif", phase_name="minor", refine_cell=False),
    ]
    got = run_multistart_rietveld(
        [_hist()], phases, config=MultistartConfig(n_starts=3), jobs=1, save_gpx=False,
    )

    passed = [kw["initial_cell_scale"] for kw in captured]
    assert len(passed) == 3
    assert all("minor" not in s for s in passed), f"凍結相の格子を摂動している: {passed}"
    assert len({s["main"] for s in passed}) == 3, "対照: 解放する相は従来どおり振る"
    assert all("minor" not in st.perturbation.cell_scale for st in got.starts), (
        "記録上の摂動が実際に掛けた摂動と食い違う"
    )


def test_moved_axes_are_what_the_engine_moved_not_a_recount(monkeypatch):
    """★「動かした軸数」は engine が**実際に動かした**数を読む (対称性からの数え直しをしない)。

    非トートロジー: ``n_axes_jittered`` は傍証の条件 (`perturbation_had_no_effect`) に使われる。
    結果の自由度指標から数え直すと、engine が動かさなかった軸 (凍結原子・読めなかった相) を
    「試験した」と数える — 数え直しの規則が engine とずれた瞬間に空虚な傍証が戻る。
    """
    from tsumugin.autorietveld.model import PhaseSpec
    from tsumugin.autorietveld.multistart import run_multistart_rietveld

    # 自由度指標は 6 軸ぶんあるが、engine が動かしたのは 2 軸だけ、という結果。
    _stub_engine(
        monkeypatch, moved_axes=2, free_index={"main": {"O1": (1, 2, 3), "O2": (1, 2, 3)}},
    )
    phases = [PhaseSpec(structure_path="a.cif", phase_name="main")]
    got = run_multistart_rietveld(
        [_hist()], phases, config=MultistartConfig(n_starts=3),
        coord_jitter_ang=0.05, jobs=1, save_gpx=False,
    )

    assert [st.n_axes_jittered for st in got.starts] == [2, 2, 2]
    assert got.n_axes_jittered == 6


def test_jitter_on_only_frozen_atoms_is_not_corroboration(monkeypatch):
    """★自由座標を持つ原子が全部凍結なら、座標摂動は 1 軸も効いていない — 傍証にしない。"""
    from tsumugin.autorietveld.model import PhaseSpec
    from tsumugin.autorietveld.multistart import run_multistart_rietveld

    _stub_engine(
        monkeypatch, moved_axes=0, free_index={"main": {"O1": (1, 2, 3), "Ca1": (0, 0, 0)}},
    )
    phases = [PhaseSpec(structure_path="a.cif", phase_name="main", frozen_coord_labels=("O1",))]
    got = run_multistart_rietveld(
        [_hist()], phases, config=MultistartConfig(n_starts=3),
        coord_jitter_ang=0.05, jobs=1, save_gpx=False,
    )

    assert got.n_axes_jittered == 0
    assert got.is_global_corroborated is False
    assert got.corroboration_reason == "perturbation_had_no_effect"


def test_starts_that_perturb_nothing_are_not_corroboration():
    """★全相の格子が凍結 (倍率なし) で座標摂動も無いなら、開始点は**全部同じ入力**である。

    非トートロジー: 凍結相を格子摂動から外すと、全相凍結 + 格子だけの試験では開始点の初期値が
    ビット同一になる。同じ入力は同じ解へ行くので 1 ベイスンは**空虚に**成立する
    (`test_a_requested_jitter_that_moved_nothing_is_not_corroboration` の格子版)。
    """
    starts = [
        MultistartStart(i, StartPerturbation(cell_scale={}, jitter_seed=i), _result(9.8, 9.372))
        for i in range(3)
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=3))

    assert got.n_basins == 1
    assert got.is_global_corroborated is False
    assert got.corroboration_reason == "perturbation_had_no_effect"
    assert any("試験していない" in w for w in got.warnings), "理由を述べずに False にしない"


def test_a_run_that_tested_nothing_says_so_and_names_the_adoption_flag():
    """★何も振っていない収束確認は「何も試験していない」と言い、採用判断に使えないことを名指す。

    非トートロジー: ③ は `structure_is_corroborated` を「解を採用してよいか」と読む。全クラス
    AGREE なのにそれが false になる理由が書かれていなければ、③ は手順の不具合と誤読する。
    """
    starts = [
        MultistartStart(i, StartPerturbation(cell_scale={}, jitter_seed=i), _result(9.8, 9.372))
        for i in range(3)
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=3))

    assert got.perturbation_applied is False
    nothing = [w for w in got.warnings if "何も試験していない" in w]
    assert len(nothing) == 1, got.warnings
    assert "structure_is_corroborated" in nothing[0]
    assert got.to_dict()["perturbation_applied"] is False, "② の JSON に理由のフラグが無い"


def test_failed_starts_are_not_reported_as_identical_inputs():
    """★全開始点が失敗したときに「同じ入力だった」と言わない — 不明であって「動かなかった」ではない。

    非トートロジー: 失敗した開始点は軸数 0 で返る (`_run_one_start`)。それを「1 軸も動かして
    いない」と読むと、③ は本当の原因 (失敗) ではなく摂動の設定を直しに行く。
    """
    starts = [
        MultistartStart(
            i,
            StartPerturbation(
                cell_scale={"ph": (f, f, f)}, coord_jitter_ang=0.05, jitter_seed=i
            ),
            result=None, error="TypeError: boom",
        )
        for i, f in enumerate((0.993, 1.0, 1.007))
    ]
    got = summarize_multistart(starts, MultistartConfig(n_starts=3))

    assert not any("何も試験していない" in w for w in got.warnings), got.warnings
    assert any("TypeError: boom" in w for w in got.warnings), "失敗の理由は従来どおり残る"
    # 失敗した開始点に記録された倍率は「試験した」証拠にならない (実行できていない)。
    assert got.perturbation_applied is False
