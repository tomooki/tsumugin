"""標準経路 `optimize_then_confirm` (Phase A → Phase B) — GSAS 非依存。

ここで固定するのは**順序と受け渡し**である: 手順を先に決め、その手順ごと (適応候補が変えた
入力も含めて) 固定して初期値を振る。固定を落とすと「別の土俵で収束確認した」ことになる。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.autorietveld.confirm import optimize_then_confirm
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    StabilityOptions,
    StageResult,
    ValidityReport,
)

_H = HistogramSpec(
    data_path="d.xra", instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
)
_P = PhaseSpec(structure_path="a.cif", phase_name="ph")


def _result(rwp: float, *, cell_a: float = 10.0, valid: bool = True) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(
            StageResult(label="S0", rwp=rwp * 2, gof=2.0, n_params=5, converged=True),
            StageResult(label="S1", rwp=rwp, gof=1.5, n_params=20, converged=True),
        ),
        final_rwp=rwp,
        final_gof=1.5,
        refined_cells={"ph": (cell_a, 10.0, 10.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=valid),
        cell_esd={"ph": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
        n_obs=4000,
    )


class _Recorder:
    """探索と収束確認の呼ばれ方を記録する差し替え。"""

    def __init__(self, rwp_by_name: dict[str, float]):
        self.rwp_by_name = rwp_by_name
        self.search_calls: list[str] = []
        self.multistart_kwargs: dict | None = None
        self.multistart_hists: list | None = None

    def search_runner(self, candidate):
        self.search_calls.append(candidate.name)
        return _result(self.rwp_by_name.get(candidate.name, 20.0))


def _fake_multistart(rec: _Recorder, *, corroborated: bool = True,
                     class_convergence: dict | None = None,
                     dependent: tuple = (),
                     cell_scale: dict | None = None,
                     n_axes: int = 3,
                     jitter: float = 0.05):
    """Phase B の差し替え。既定の開始点は**実際に振った**格子 (0.993/1.007) + 座標 3 軸 —
    全部 1.0 だと同じ入力 = 空虚な収束確認になる (`test_identical_starts_...`)。"""
    from tsumugin.autorietveld.multistart import (
        MultistartStart,
        RietveldMultistartResult,
        StartPerturbation,
    )

    def fake(histograms, phases, **kwargs):
        rec.multistart_kwargs = kwargs
        rec.multistart_hists = list(histograms)
        best = _result(9.5)
        starts = tuple(
            MultistartStart(
                index=i,
                perturbation=StartPerturbation(
                    cell_scale=(
                        {"ph": (f, f, f)} if cell_scale is None else cell_scale
                    ),
                    coord_jitter_ang=jitter,
                    jitter_seed=i,
                ),
                result=best,
                n_axes_jittered=n_axes,
            )
            for i, f in enumerate((0.993, 1.007))
        )
        return RietveldMultistartResult(
            best=best, best_index=0, starts=starts, n_starts=2, n_diverged=0,
            n_axes_jittered=n_axes * len(starts),
            n_basins=1 if corroborated else 2,
            is_global_corroborated=corroborated,
            corroboration_reason="corroborated" if corroborated else "multiple_basins",
            class_convergence=class_convergence or {
                "cell": "AGREE", "coord": "AGREE", "occupancy": "AGREE",
            },
            initial_value_dependent=dependent,
        )

    return fake


def test_phase_a_runs_first_and_its_winner_is_what_phase_b_confirms():
    """★手順を先に決め、**その手順ごと**収束確認へ渡すこと。"""
    rec = _Recorder({"default": 9.81, "sizestrain_last": 9.60, "polish": 9.70,
                     "serious1": 10.4})
    fake_ms = _fake_multistart(rec)

    got = optimize_then_confirm(
        [_H], [_P], candidates=("default", "sizestrain_last", "polish", "serious1"),
        search_runner=rec.search_runner,
        multistart_runner=fake_ms,
    )

    assert rec.search_calls, "Phase A が先に走ること"
    assert got.adopted_recipe == "sizestrain_last", "収束したうち最良が採用される"
    # Phase B は採用候補の段列を受け取る (元の入力ではなく)。
    assert rec.multistart_kwargs is not None
    assert "recipe" in rec.multistart_kwargs


def test_the_adopted_candidates_own_inputs_are_carried_into_phase_b():
    """★適応候補が変えた**入力ごと**固定する。

    非トートロジー: 適応層はレンジと背景項数を変える。元の入力で Phase B を回すと
    **別の土俵で収束確認した**ことになり、その傍証は採用した解に対するものではない。
    """
    rec = _Recorder({"polish": 9.0})
    fake_ms = _fake_multistart(rec)

    got = optimize_then_confirm([_H], [_P], candidates=("polish",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    assert got.adopted_recipe == "polish"
    assert rec.multistart_hists is not None
    selected = got.search.selected
    assert rec.multistart_hists == list(selected.candidate.histograms)


def test_a_candidate_with_its_own_stability_carries_it_into_phase_b():
    """★`polish` の違いは段列ではなく `StabilityOptions` にある — それも運ぶこと。

    非トートロジー: 段列だけ渡すと `polish` は `default` と同一になり、収束確認は
    **採用したのとは違う手順**で行われる。
    """
    rec = _Recorder({"polish": 9.0})
    fake_ms = _fake_multistart(rec)

    optimize_then_confirm([_H], [_P], candidates=("polish",), search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    stability = rec.multistart_kwargs.get("stability")
    assert isinstance(stability, StabilityOptions)
    assert stability.polish_frozen_undetermined is True


def test_failed_search_does_not_pretend_to_confirm():
    """★手順が 1 つも立たなければ収束確認へ進まない (捏造した傍証を出さない)。"""

    def boom(candidate):
        raise RuntimeError("boom")

    got = optimize_then_confirm([_H], [_P], candidates=("default",), search_runner=boom)

    assert got.adopted_recipe == ""
    assert got.multistart is None and got.best is None
    assert got.is_corroborated is False
    assert any("収束確認へ進めない" in w for w in got.warnings)


def test_structure_converged_but_strain_did_not_is_still_an_adoptable_answer():
    """★**規定の判断規則**: 構造が収束していれば解を採用してよい。割れたクラスは未決定と報告。

    非トートロジー: 縮退 (サイズ/微小歪み ↔ Caglioti U/V/W) は手順では解消できないので、
    全クラスの収束を採用条件にすると**どのデータでも解を出せなくなる** (実測: T1 は歪が
    常に割れる)。構造が収束していれば構造の答えは信頼でき、割れたクラスは「決まっていない」
    として報告すればよい — 値を捏造せず、かつ解析は前へ進む。
    """
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(
        rec, corroborated=False,
        class_convergence={"cell": "AGREE", "coord": "AGREE", "occupancy": "AGREE",
                           "microstructure": "DISAGREE"},
        dependent=("fap.hist0.size",),
    )

    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    assert got.is_corroborated is False, "全クラスの厳密 AND は False のまま"
    assert got.structure_is_corroborated is True, "構造は収束 = 解は採用してよい"
    assert got.undetermined_by_initial_values == ("fap.hist0.size",)
    assert any("出版してはならない" in w for w in got.warnings)
    assert any("構造 (格子・座標・占有率) は収束している" in w for w in got.warnings)
    assert got.best is not None


def test_a_diverged_structure_is_not_adoptable():
    """【対照】構造そのものが割れていれば `structure_is_corroborated` は False。"""
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(
        rec, corroborated=False,
        class_convergence={"cell": "DISAGREE", "coord": "AGREE", "occupancy": "AGREE"},
        dependent=("PbSO4.a",),
    )
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    assert got.structure_is_corroborated is False
    assert "PbSO4.a" in got.undetermined_by_initial_values


def test_report_dict_is_json_safe():
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(rec)
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)
    json.dumps(got.to_dict(), allow_nan=False)


def test_final_value_comes_from_the_confirmation_not_the_single_shot():
    """★最終値は収束確認の最良フィット。

    非トートロジー: 同じ手順で複数点走らせた最良は、単発結果と同等以上である。単発を返すと
    「確認のために回した計算」を捨てることになる。
    """
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(rec)
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)
    assert got.best.final_rwp == pytest.approx(9.5)


def test_phase_b_is_only_given_kwargs_that_the_engine_accepts():
    """★Phase B へ渡す引数が実際に `run_auto_rietveld` の引数であること。

    非トートロジー: 収束確認は開始点を**子プロセス**で回すので、`TypeError` は例外として
    上がらず「全開始点が失敗」(`corroboration_reason='no_valid_start'`) に化ける。Rwp にも
    例外にも現れないまま**収束確認が丸ごと空振りする**。実測でこれを起こしたのが
    `background_coeffs` — レシピを**組む**引数であって精密化の引数ではない (採用候補の背景
    項数は `cand.stages` に焼き込まれて運ばれる)。
    """
    import inspect

    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.multistart import run_multistart_rietveld

    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(rec)
    optimize_then_confirm(
        [_H], [_P], candidates=("default",), search_runner=rec.search_runner,
        multistart_runner=fake_ms,
        # ③/② が渡してくる「レシピを組む」引数。ここで落とさないと子へ漏れる。
        background_coeffs=24, max_cyc=8,
    )

    allowed = set(inspect.signature(run_multistart_rietveld).parameters) | set(
        inspect.signature(run_auto_rietveld).parameters
    )
    unknown = set(rec.multistart_kwargs) - allowed
    assert not unknown, f"Phase B へエンジンが受け取れない引数が渡っている: {sorted(unknown)}"


def test_identical_starts_are_not_an_adoptable_structure():
    """★どの開始点も初期値を動かしていなければ、全クラスの AGREE は**空虚**である。

    非トートロジー: 全相 ``refine_cell=False`` (格子倍率が記録されない) で座標摂動なし、
    のように開始点が全部同じ入力だと、同じ入力は同じ解へ行くので全クラスが AGREE になる。
    `structure_is_corroborated` は ③ が「解を採用してよい」と読む headline なので、
    ここが空虚に True になるのは最悪の失敗形 (何も試験していないのに採用を許す)。
    """
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(
        rec, cell_scale={}, n_axes=0, jitter=0.0,
        class_convergence={"cell": "AGREE", "coord": "AGREE", "occupancy": "AGREE",
                           "microstructure": "DISAGREE"},
    )
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    assert got.multistart is not None and got.multistart.perturbation_applied is False
    assert got.structure_is_corroborated is False, "何も振っていない収束確認で採用を許した"
    # 理由の文言は `summarize_multistart` が 1 箇所で出す (ここは転送するだけ)。confirm が
    # 「構造は収束している — 採用してよい」と**逆のことを言わない**ことを確かめる。
    assert not any("採用してよい" in w for w in got.warnings), got.warnings


def test_a_lattice_only_test_of_a_symmetry_fixed_structure_is_still_adoptable():
    """【対照】座標が全て対称固定 (動かせる軸 0) でも、格子を振っていれば試験は成立している。

    高対称の標準試料 (CeO₂ 等) は自由座標を持たないので座標軸は試験しようがない。
    格子は実際に振ったので、`structure_is_corroborated` を False へ縮退させない。
    """
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(rec, n_axes=0)
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    assert got.multistart.perturbation_applied is True
    assert got.structure_is_corroborated is True


def test_jittered_coordinates_alone_make_the_test_real():
    """【対照】格子が全相凍結 (倍率なし) でも、座標を実際に動かしていれば試験は成立している。"""
    rec = _Recorder({"default": 9.81})
    fake_ms = _fake_multistart(rec, cell_scale={}, n_axes=3)
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=fake_ms)

    assert got.multistart.perturbation_applied is True
    assert got.structure_is_corroborated is True


def test_all_failed_starts_are_not_reported_as_an_untested_run():
    """★全開始点が失敗したとき、confirm は「同じ入力だった/何も試験していない」と言わない。

    非トートロジー: 失敗した開始点は軸数 0 で返るので、`perturbation_applied` は False になる。
    それを「1 軸も動かしていない」と報告すると、③ は失敗の原因ではなく摂動の設定を直しに行く。
    """
    from tsumugin.autorietveld.multistart import (
        MultistartStart,
        RietveldMultistartResult,
        StartPerturbation,
    )

    def all_failed(histograms, phases, **kwargs):
        starts = tuple(
            MultistartStart(
                index=i,
                perturbation=StartPerturbation(
                    cell_scale={}, coord_jitter_ang=0.05, jitter_seed=i
                ),
                result=None,
                error="TypeError: boom",
            )
            for i in range(2)
        )
        return RietveldMultistartResult(
            best=None, best_index=-1, starts=starts, n_starts=0, n_diverged=0,
            n_basins=0, is_global_corroborated=False, corroboration_reason="no_valid_start",
            warnings=("2/2 開始点が失敗: TypeError: boom",),
        )

    rec = _Recorder({"default": 9.81})
    got = optimize_then_confirm([_H], [_P], candidates=("default",),
                                search_runner=rec.search_runner,
                                multistart_runner=all_failed)

    assert got.structure_is_corroborated is False
    assert not any("何も試験していない" in w for w in got.warnings), got.warnings
    assert any("TypeError: boom" in w for w in got.warnings), "失敗の理由は転送される"
