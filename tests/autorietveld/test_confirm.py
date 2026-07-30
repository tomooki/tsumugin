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
                     dependent: tuple = ()):
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
                perturbation=StartPerturbation(cell_scale={"ph": (1.0, 1.0, 1.0)}),
                result=best,
            )
            for i in range(2)
        )
        return RietveldMultistartResult(
            best=best, best_index=0, starts=starts, n_starts=2, n_diverged=0,
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
