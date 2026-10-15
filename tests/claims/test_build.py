"""fit-then-judge P1-1A タスク 4: `AutoRietveldResult` → `Claim` の写像 (REQ-FTJ-1A-2xx, 401)。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.claim_variables import (
    HistogramVariables,
    PhaseVariables,
    claim_variable_names,
)
from tsumugin.autorietveld.diagnostics import CorrelatedPair, CovarianceRecord
from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.autorietveld.multistart import (
    MultistartStart,
    RietveldMultistartResult,
    StartPerturbation,
)
from tsumugin.claims.build import base_claims, with_convergence
from tsumugin.claims.model import Check, Determinacy, Scope

_VARS = claim_variable_names(
    [PhaseVariables(name="P", pid=0, labels=("Pb", "O1"))],
    [HistogramVariables(index=0, hid=0, profile_keys=("U",))],
)


def _result(**kw) -> AutoRietveldResult:
    base = dict(
        stage_results=(StageResult("S0", 10.0, 1.2, 5, True),),
        final_rwp=10.0, final_gof=1.2,
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        cell_esd={"P": (0.001, 0.001, 0.001, 0.0, 0.0, 0.0)},
        atom_coords={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.25, 0.1, 0.3)}},
        atom_coord_esd={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.001, 0.002, None)}},
        atom_coord_free_index={"P": {"Pb": (0, 0, 0), "O1": (1, 2, 3)}},
        atom_uiso={"P": {"Pb": 0.01, "O1": 0.02}},
        atom_uiso_esd={"P": {"Pb": 0.001, "O1": 0.03}},
        atom_occupancy={"P": {"Pb": 1.0, "O1": 1.0}},
        atom_occupancy_esd={"P": {"Pb": None, "O1": None}},
        phase_weight_fractions={"P": 1.0},
        phase_weight_fraction_esd={"P": 0.0},
        hist_profile=({"U": 2.0},),
        hist_profile_esd=({"U": 0.1},),
        final_covariance=CovarianceRecord(
            vary_list=("0::A0", "0::dAx:1", "0::dAy:1", "0::AUiso:0", "0::AUiso:1",
                       "0:0:Scale", ":0:U"),
            dependent=(),
            correlations=(CorrelatedPair("0::dAx:1", "0::AUiso:1", 0.95),),
        ),
        claim_variables=_VARS,
    )
    base.update(kw)
    return AutoRietveldResult(**base)


def test_a_refined_lattice_length_is_refined_esd_only_and_relative():
    c = base_claims(_result())["cell:P.a"]
    assert c.provenance == {"refined"}
    assert c.determinacy is Determinacy.ESD_ONLY
    assert c.scope is Scope.RELATIVE_WITHIN_SAMPLE  # 内部標準の宣言が無い (1B §4.1)
    assert c.checks["provenance_known"] is Check.PASS
    assert c.value == 5.0 and c.esd == 0.001 and c.unit == "angstrom"


def test_symmetry_fixed_values_are_exact_even_if_their_cell_terms_were_refined():
    """立方晶の α は A0 が varyList にあっても対称性で 90° — 「精密化した値」ではない。"""
    claims = base_claims(_result())
    assert claims["cell:P.alpha"].determinacy is Determinacy.EXACT
    assert claims["cell:P.alpha"].provenance == {"symmetry"}
    assert claims["coord:P.Pb.x"].determinacy is Determinacy.EXACT


def test_a_value_that_was_not_released_is_an_input_value_and_not_published():
    """座標段を受理しなかった軸 (varyList に無い) は入力値 — 「精密化した」と読ませない。"""
    c = base_claims(_result())["coord:P.O1.z"]
    assert c.provenance == {"input"}
    assert c.publishable is False


def test_a_pruned_variable_is_undetermined():
    c = base_claims(_result(frozen_parameters=("0::dAx:1",)))["coord:P.O1.x"]
    assert c.provenance == {"pruned"}
    assert c.determinacy is Determinacy.UNDETERMINED_ESD


def test_an_esd_as_large_as_the_value_is_undetermined():
    """Uiso O1 は esd 0.03 ≥ 値 0.02 — 決まっていない (`undetermined_parameters` を頼んでいなくても)。"""
    claims = base_claims(_result())
    assert claims["uiso:P.O1"].determinacy is Determinacy.UNDETERMINED_ESD
    assert claims["uiso:P.Pb"].determinacy is Determinacy.ESD_ONLY


def test_reported_undetermined_parameters_are_undetermined():
    from tsumugin.autorietveld.diagnostics import WeakVariable

    weak = (WeakVariable("0::A0", 5.0, 9.0, 1.8),)
    c = base_claims(_result(undetermined_parameters=weak))["cell:P.a"]
    assert c.determinacy is Determinacy.UNDETERMINED_ESD


def test_a_non_converged_final_stage_marks_refined_values_unconverged():
    res = _result(stage_results=(StageResult("S0", 10.0, 1.2, 5, False),))
    claims = base_claims(res)
    assert claims["cell:P.a"].determinacy is Determinacy.UNCONVERGED
    assert claims["cell:P.alpha"].determinacy is Determinacy.EXACT  # 対称性は収束と無関係


def test_without_the_final_covariance_provenance_is_unknown_and_nothing_is_published():
    """TOPAS・旧結果: 出自を決められない — 黙って「精密化した」にしない (REQ-FTJ-1A-203)。"""
    claims = base_claims(_result(final_covariance=None, claim_variables=None))
    assert claims
    for c in claims.values():
        assert c.checks["provenance_known"] is Check.UNEVALUATED
        assert c.publishable is False


def test_direct_correlations_are_mapped_to_value_keys():
    claims = base_claims(_result())
    assert "uiso:P.O1" in claims["coord:P.O1.x"].correlations
    assert "coord:P.O1.x" in claims["uiso:P.O1"].correlations
    assert not claims["cell:P.a"].correlations


def test_every_value_kind_is_covered():
    keys = set(base_claims(_result()))
    for want in ("cell:P.a", "coord:P.O1.x", "uiso:P.O1", "occupancy:P.O1",
                 "weight_fraction:P.wt", "profile:hist0.U"):
        assert want in keys


def test_no_value_is_publishable_before_the_required_checks_run():
    """写像だけでは相集合の完全性・結晶化学は未検査 = 出版しない (検査は後段の役目)。"""
    assert not any(c.publishable for c in base_claims(_result()).values())


# ---------------------------------------------------------------- 収束確認の証人


def _start(i, result, scale=1.0):
    return MultistartStart(
        index=i,
        perturbation=StartPerturbation(cell_scale={"P": (scale,) * 3}, jitter_seed=i),
        result=result,
    )


def _ms(results, *, scales=(0.993, 1.0, 1.007)):
    starts = tuple(_start(i, r, s) for i, (r, s) in enumerate(zip(results, scales)))
    return RietveldMultistartResult(
        best=results[0], best_index=0, starts=starts, n_starts=len(starts), n_diverged=0,
        n_basins=1, is_global_corroborated=True,
    )


def test_values_that_agree_across_all_starts_are_determined_with_a_witness():
    claims = with_convergence(base_claims(_result()), _ms([_result()] * 3))
    c = claims["cell:P.a"]
    assert c.determinacy is Determinacy.DETERMINED
    (w,) = [w for w in c.witnesses if w.kind == "multistart_agreement"]
    assert w.detail["n_starts"] == 3 and w.detail["n_pairs"] == 3


def test_an_input_value_is_not_determined_by_agreeing_starts():
    """解放しなかった入力値は開始点で同じなのが当然 — 「決まった」と読ませない (P1-1B で発見)。"""
    claims = with_convergence(base_claims(_result()), _ms([_result()] * 3))
    c = claims["coord:P.O1.z"]
    assert c.provenance == {"input"}
    assert c.determinacy is Determinacy.ESD_ONLY
    assert not any(w.kind == "multistart_agreement" for w in c.witnesses)


def test_only_coordinates_the_engine_actually_moved_are_determined():
    """件数でなく、どの座標を振ったかで判定する (極性原点の hold で振らない軸を「試験した」と数えない)。"""
    from dataclasses import replace

    moved = _result(coord_jitter_axes_moved=1, coord_jitter_moved=("P.O1.y",))
    starts = tuple(
        replace(_start(i, moved, s), perturbation=StartPerturbation(
            cell_scale={"P": (s,) * 3}, jitter_seed=i, coord_jitter_ang=0.05), n_axes_jittered=1)
        for i, s in enumerate((0.993, 1.0, 1.007))
    )
    ms = RietveldMultistartResult(
        best=moved, best_index=0, starts=starts, n_starts=3, n_diverged=0, n_basins=1,
        is_global_corroborated=True,
    )
    claims = with_convergence(base_claims(_result()), ms)
    assert claims["coord:P.O1.y"].determinacy is Determinacy.DETERMINED
    assert claims["coord:P.O1.x"].determinacy is Determinacy.ESD_ONLY


def test_a_value_that_split_between_starts_is_initial_value_dependent():
    split = _result(atom_coords={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.35, 0.1, 0.3)}})
    claims = with_convergence(base_claims(_result()), _ms([_result(), _result(), split]))
    assert claims["coord:P.O1.x"].determinacy is Determinacy.INITIAL_VALUE_DEPENDENT
    assert claims["coord:P.O1.y"].determinacy is Determinacy.DETERMINED


def test_starts_that_moved_nothing_are_not_a_witness():
    claims = with_convergence(
        base_claims(_result()), _ms([_result()] * 3, scales=(1.0, 1.0, 1.0)),
    )
    assert claims["cell:P.a"].determinacy is Determinacy.ESD_ONLY


def test_a_failed_start_withholds_the_witness():
    """「全開始点で一致」— 実行できなかった開始点があるなら全部では一致していない。"""
    ms = _ms([_result()] * 3)
    starts = ms.starts[:2] + (_start(2, None),)
    ms = RietveldMultistartResult(
        best=ms.best, best_index=0, starts=starts, n_starts=3, n_diverged=0, n_basins=1,
        is_global_corroborated=False,
    )
    assert with_convergence(base_claims(_result()), ms)["cell:P.a"].determinacy is (
        Determinacy.ESD_ONLY
    )


def test_an_invalid_start_withholds_the_witness():
    bad = _result(validity=ValidityReport(passed=False))
    claims = with_convergence(base_claims(_result()), _ms([_result(), _result(), bad]))
    assert claims["cell:P.a"].determinacy is Determinacy.ESD_ONLY


def test_weaker_labels_are_not_promoted_by_agreement():
    """一致しても `undetermined_esd` は `determined` にならない (esd が値を超える値は決まっていない)。"""
    claims = with_convergence(base_claims(_result()), _ms([_result()] * 3))
    assert claims["uiso:P.O1"].determinacy is Determinacy.UNDETERMINED_ESD


def test_provenance_that_differs_between_starts_is_recorded_but_not_promoted():
    """値が一致していれば出自の違いだけでは初期値依存にしない。ただし精密化しなかった開始点がある値は
    試験したとは言えないので `determined` にも上げない (2026-10-15 ユーザー決定)。"""
    pruned = _result(frozen_parameters=("0::dAx:1",))
    claims = with_convergence(base_claims(_result()), _ms([_result(), _result(), pruned]))
    c = claims["coord:P.O1.x"]
    # 剪定した開始点の主張 (undetermined_esd) との合成は弱い方 — 初期値依存でも determined でもない
    assert c.determinacy not in (Determinacy.INITIAL_VALUE_DEPENDENT, Determinacy.DETERMINED)
    assert any(w.kind == "provenance_varied" for w in c.witnesses)
    # 出自が揃った値 (同じ原子の y) は従来どおり昇格する
    assert claims["coord:P.O1.y"].determinacy is Determinacy.DETERMINED


def test_provenance_varied_values_that_split_are_still_initial_value_dependent():
    pruned_moved = _result(frozen_parameters=("0::dAx:1",),
                           atom_coords={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.35, 0.1, 0.3)}})
    claims = with_convergence(base_claims(_result()), _ms([_result(), _result(), pruned_moved]))
    assert claims["coord:P.O1.x"].determinacy is Determinacy.INITIAL_VALUE_DEPENDENT


@pytest.mark.parametrize("ms", [None])
def test_no_convergence_report_leaves_claims_unchanged(ms):
    base = base_claims(_result())
    assert with_convergence(base, ms) == base


def test_coordinates_are_not_witnessed_when_the_jitter_moved_nothing():
    """座標の摂動を頼んだのに 1 軸も動かなかった (高対称・全原子凍結) — 座標は試験していない。
    格子は振ったので格子は証人になる (レビュー L5: multistart 自身の傍証条件と揃える)。"""
    starts = tuple(
        MultistartStart(
            index=i,
            perturbation=StartPerturbation(cell_scale={"P": (s,) * 3}, coord_jitter_ang=0.05,
                                           jitter_seed=i),
            result=_result(), n_axes_jittered=0,
        )
        for i, s in enumerate((0.993, 1.0, 1.007))
    )
    ms = RietveldMultistartResult(
        best=starts[0].result, best_index=0, starts=starts, n_starts=3, n_diverged=0,
        n_basins=1, is_global_corroborated=False,
    )
    claims = with_convergence(base_claims(_result()), ms)
    assert claims["cell:P.a"].determinacy is Determinacy.DETERMINED
    assert claims["coord:P.O1.y"].determinacy is Determinacy.ESD_ONLY


def test_the_agreement_witness_records_its_tolerance():
    claims = with_convergence(base_claims(_result()), _ms([_result()] * 3))
    (w,) = claims["cell:P.a"].witnesses
    assert w.detail["k_esd"] == 3.0


def test_pruning_one_cell_term_demotes_only_the_axes_that_depend_on_it():
    """直方晶で c の項 (A2) だけ剪定 — a, b は精密化した値のまま (以前は 6 軸とも止まっていた)。"""
    variables = claim_variable_names(
        [PhaseVariables(name="P", pid=0, labels=("Pb", "O1"),
                        cell=(5.0, 6.0, 7.0, 90.0, 90.0, 90.0))],
        [HistogramVariables(index=0, hid=0, profile_keys=("U",))],
    )
    cov = CovarianceRecord(vary_list=("0::A0", "0::A1", "0::A2"), dependent=(), correlations=())
    claims = base_claims(_result(
        refined_cells={"P": (5.0, 6.0, 7.0, 90.0, 90.0, 90.0)}, claim_variables=variables,
        final_covariance=cov, frozen_parameters=("0::A2",),
    ))
    assert claims["cell:P.c"].provenance == {"pruned"}
    assert claims["cell:P.a"].provenance == {"refined"}
    assert claims["cell:P.b"].provenance == {"refined"}


def test_an_invalid_start_does_not_count_as_a_different_provenance():
    """validity に落ちた開始点は値の一致の比較から外す — 出自の合成からも外す (P1.5: 格子 ±0.7% で別ベイスンに
    落ちて validity に落ちた開始点が、出自の違いで値を初期値依存にしていた)。"""
    bad_pruned = _result(frozen_parameters=("0::dAx:1",), validity=ValidityReport(passed=False))
    claims = with_convergence(base_claims(_result()), _ms([_result(), _result(), bad_pruned]))
    c = claims["coord:P.O1.x"]
    assert c.determinacy is Determinacy.ESD_ONLY  # 剪定した (validity に落ちた) 開始点の弱い主張を合成しない
    assert not any(w.kind == "provenance_varied" for w in c.witnesses)


def test_a_value_left_unrefined_in_one_start_is_not_promoted():
    """ある開始点では O1.x を精密化しなかった (esd なし = input)。値は一致しても determined にはしない。"""
    unrefined = _result(final_covariance=CovarianceRecord(  # この開始点では O1.x (0::dAx:1) が varyList に無い
        vary_list=("0::A0", "0::dAy:1", "0::AUiso:0", "0::AUiso:1", "0:0:Scale", ":0:U"),
        dependent=(), correlations=(),
    ))
    claims = with_convergence(base_claims(_result()), _ms([_result(), _result(), unrefined]))
    c = claims["coord:P.O1.x"]
    assert c.determinacy is not Determinacy.DETERMINED
    assert c.determinacy is not Determinacy.INITIAL_VALUE_DEPENDENT
    assert any(w.kind == "provenance_varied" for w in c.witnesses)
