"""fit-then-judge P1-1A タスク 7: 判断要求・止める値・既定ポリシー D (REQ-FTJ-1A-3xx)。

`assess(result, phases, multistart)` は写像 → 証人 → 結晶化学 → 判断要求 → D を通して、出版状態を
決める唯一の入口。検査器はここではスタブに差し替え (検査器自体はタスク 5/6 のテストが縛る)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.claim_variables import (
    HistogramVariables,
    PhaseVariables,
    claim_variable_names,
)
from tsumugin.autorietveld.diagnostics import CorrelatedPair, CovarianceRecord
from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    PhaseSpec,
    StageResult,
    ValidityReport,
)
from tsumugin.claims import requests as rq
from tsumugin.claims.model import Check, Determinacy, Witness

_VARS = claim_variable_names(
    [PhaseVariables(name="P", pid=0, labels=("Pb", "O1")),
     PhaseVariables(name="Q", pid=1, labels=("C1",))],
    [HistogramVariables(index=0, hid=0, profile_keys=("U",))],
)
_VARY = ("0::A0", "0::dAx:1", "0::dAy:1", "0::AUiso:0", "0::AUiso:1", "0:0:Scale", "1:0:Scale",
         "1::A0", ":0:U")


def _result(**kw) -> AutoRietveldResult:
    base = dict(
        stage_results=(StageResult("S0", 10.0, 1.2, 5, True),),
        final_rwp=10.0, final_gof=1.2,
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0),
                       "Q": (3.0, 3.0, 3.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True),
        cell_esd={"P": (0.001,) * 3 + (0.0,) * 3, "Q": (0.002,) * 3 + (0.0,) * 3},
        atom_coords={"P": {"Pb": (0.0, 0.0, 0.0), "O1": (0.25, 0.1, 0.3)},
                     "Q": {"C1": (0.0, 0.0, 0.0)}},
        atom_coord_esd={"P": {"Pb": (0.0,) * 3, "O1": (0.001, 0.002, 0.0)},
                        "Q": {"C1": (0.0,) * 3}},
        atom_coord_free_index={"P": {"Pb": (0, 0, 0), "O1": (1, 2, 0)}, "Q": {"C1": (0, 0, 0)}},
        atom_uiso={"P": {"Pb": 0.01, "O1": 0.02}},
        atom_uiso_esd={"P": {"Pb": 0.001, "O1": 0.002}},
        atom_occupancy={"P": {"Pb": 1.0, "O1": 1.0}, "Q": {"C1": 1.0}},
        atom_occupancy_esd={"P": {"Pb": None, "O1": None}, "Q": {"C1": None}},
        phase_weight_fractions={"P": 0.7, "Q": 0.3},
        phase_weight_fraction_esd={"P": 0.01, "Q": 0.01},
        hist_profile=({"U": 2.0},),
        hist_profile_esd=({"U": 0.1},),
        final_covariance=CovarianceRecord(
            vary_list=_VARY, dependent=(),
            correlations=(CorrelatedPair("0::dAx:1", "0::AUiso:1", 0.95),),
        ),
        claim_variables=_VARS,
        coordinate_freedom_mismatches={"P": (), "Q": ()},
    )
    base.update(kw)
    return AutoRietveldResult(**base)


_PHASES = (PhaseSpec("p.cif", "P"), PhaseSpec("q.cif", "Q"))


@pytest.fixture
def checks_pass(monkeypatch):
    """検査器をスタブにする (既定は全部 pass)。戻り値の dict を書き換えると結果を変えられる。"""
    state = {"phase_set": Check.PASS, "chem": {"P": Check.PASS, "Q": Check.PASS}}

    def witness(result):
        return state["phase_set"], Witness("residual_window_snr", {"stub": True})

    def chemistry(phase, path, result):
        outcome = state["chem"][phase]
        return {"crystal_chemistry": (outcome, Witness("crystal_chemistry", {"stub": True}))}

    monkeypatch.setattr(rq, "_phase_set_witness", witness)
    monkeypatch.setattr(rq, "crystal_chemistry", chemistry)
    return state


def _ids(assessment):
    return {r.id for r in assessment.requests}


def test_a_clean_result_publishes_its_refined_values(checks_pass):
    a = rq.assess(_result(), _PHASES)
    assert a.claims["cell:P.a"].publishable is True
    assert a.claims["coord:P.O1.y"].publishable is True
    assert "cell:P.a" in a.publishable_values()
    # 入力構造の出所は宣言でしか閉じない — 常に出るが止めない
    (prov,) = [r for r in a.requests if r.kind == "input_structure_provenance"]
    assert prov.blocking is False and not prov.blocks


def test_an_incomplete_phase_set_blocks_every_value(checks_pass):
    checks_pass["phase_set"] = Check.FAIL
    a = rq.assess(_result(), _PHASES)
    assert "phase_set_completeness" in _ids(a)
    assert not a.publishable_values()
    assert all("phase_set_completeness" in c.gate for c in a.claims.values())


def test_an_unevaluated_phase_set_also_blocks(checks_pass):
    checks_pass["phase_set"] = Check.UNEVALUATED
    a = rq.assess(_result(), _PHASES)
    assert not a.publishable_values()
    # 検査できなかったことも判断要求として出す (黙って出版不可にするだけにしない)
    assert "phase_set_completeness" in _ids(a)
    assert all("phase_set_completeness" in c.gate for c in a.claims.values())


def test_crystal_chemistry_blocks_only_the_structure_of_that_phase(checks_pass):
    checks_pass["chem"]["P"] = Check.FAIL
    a = rq.assess(_result(), _PHASES)
    assert "crystal_chemistry:P" in a.claims["coord:P.O1.y"].gate
    (req,) = [r for r in a.requests if r.id == "crystal_chemistry:P"]
    assert req.evidence["kind"] == "crystal_chemistry", "検査の中身 (証人) を根拠に載せる"
    assert "crystal_chemistry:P" in a.claims["uiso:P.Pb"].gate
    assert not a.claims["cell:P.a"].gate  # 格子・分率は止めない (表の範囲)
    assert a.claims["cell:P.a"].publishable is True
    assert not a.claims["coord:Q.C1.x"].gate


def test_without_phase_specs_the_chemistry_is_unevaluated(checks_pass):
    a = rq.assess(_result(), None)
    assert a.claims["coord:P.O1.y"].checks["crystal_chemistry"] is Check.UNEVALUATED
    assert a.claims["coord:P.O1.y"].publishable is False
    assert "crystal_chemistry:P" in a.claims["coord:P.O1.y"].gate


def test_a_validity_failure_blocks_the_violated_values_and_their_phase(checks_pass):
    validity = ValidityReport(passed=False, checks=(
        ("lattice_P_a", False, "dev"), ("uiso_P_1", False, "U<0"), ("lattice_Q_a", True, "ok"),
    ))
    a = rq.assess(_result(validity=validity), _PHASES)
    for key in ("cell:P.a", "uiso:P.O1", "coord:P.O1.y", "weight_fraction:P.wt"):
        assert a.claims[key].gate, key
    assert not a.claims["cell:Q.a"].gate


def test_a_validity_failure_that_names_no_known_phase_blocks_everything(checks_pass):
    validity = ValidityReport(passed=False, checks=(("phase_fraction_sum", False, "Σ=1.2"),))
    a = rq.assess(_result(validity=validity), _PHASES)
    assert a.claims["weight_fraction:P.wt"].gate and a.claims["weight_fraction:Q.wt"].gate


def test_initial_value_dependence_blocks_the_split_value_and_its_direct_partners(checks_pass):
    claims = rq.assess(_result(), _PHASES).claims
    split = claims["coord:P.O1.x"].weakened_to(
        Determinacy.INITIAL_VALUE_DEPENDENT, Witness("multistart_disagreement", {"z": 9.0}),
    )
    a = rq.assess_claims({**claims, "coord:P.O1.x": split}, _result(), _PHASES)
    (req,) = [r for r in a.requests if r.kind == "initial_value_dependence"]
    assert req.blocks == {"coord:P.O1.x", "uiso:P.O1"}  # 直接の |ρ| の相手まで
    assert "cell:P.a" not in req.blocks  # 推移閉包はとらない


def test_a_frozen_cell_blocks_the_weight_fraction_of_that_phase(checks_pass):
    phases = (PhaseSpec("p.cif", "P"), PhaseSpec("q.cif", "Q", refine_cell=False))
    a = rq.assess(_result(), phases)
    assert "frozen_cell:Q" in a.claims["weight_fraction:Q.wt"].gate
    assert not a.claims["cell:P.a"].gate  # 止めるのは分率だけ (格子・構造は止めない)


def test_a_coordinate_freedom_mismatch_blocks_that_atoms_coordinates(checks_pass):
    res = _result(coordinate_freedom_mismatches={"P": (("O1", "m", "1"),), "Q": ()})
    a = rq.assess(res, _PHASES)
    assert "coordinate_freedom:P.O1" in a.claims["coord:P.O1.y"].gate
    assert not a.claims["coord:P.Pb.x"].gate


def test_default_policy_answers_hold_and_never_lifts_a_gate(checks_pass):
    checks_pass["phase_set"] = Check.FAIL
    a = rq.assess(_result(), _PHASES)
    for r in a.requests:
        assert r.default == {"answer": "hold", "policy": rq.DEFAULT_POLICY}
    assert not a.publishable_values()


def test_assessment_serializes_without_dropping_state(checks_pass):
    import json

    a = rq.assess(_result(), _PHASES)
    d = json.loads(json.dumps(a.to_dict(), allow_nan=False))
    assert d["claims_version"] and d["policy"] == rq.DEFAULT_POLICY
    assert set(d["claims"]) == set(a.claims)
    assert set(d["publishable_values"]) == {k for k, c in a.claims.items() if c.publishable}
    for key, entry in d["publishable_values"].items():
        assert set(entry) == {"value", "esd", "unit", "scope", "determinacy"}
    assert d["publishable_values"]["cell:P.a"]["scope"] == "relative_within_sample"
    assert [r["id"] for r in d["judgment_requests"]] == [r.id for r in a.requests]


def test_a_cell_the_engine_froze_on_its_own_is_also_frozen(checks_pass):
    """`refine_cell` を指定していなくても、格子が 1 軸も精密化されなかった相 (自動凍結・段の
    revert) の分率は止める — 指定だけを見ると engine が凍結した相を見落とす。"""
    vary = tuple(v for v in _VARY if v != "1::A0")
    res = _result(final_covariance=CovarianceRecord(vary_list=vary, dependent=(),
                                                    correlations=()))
    a = rq.assess(res, _PHASES)
    assert "frozen_cell:Q" in a.claims["weight_fraction:Q.wt"].gate
    assert "frozen_cell:P" not in _ids(a)


def test_a_check_for_an_unknown_phase_is_not_attributed_to_a_prefix_phase(checks_pass):
    """``lattice_PX_a`` の相は ``P`` ではない — 前方一致で取り違えず、相を引けないので全値を止める。"""
    validity = ValidityReport(passed=False, checks=(("lattice_PX_a", False, "dev"),))
    a = rq.assess(_result(validity=validity), _PHASES)
    assert a.claims["cell:Q.a"].gate, "相を引けない違反は全値を止める"


def test_propagation_stops_at_direct_partners_along_a_chain(checks_pass):
    """A–B と B–C が相関していても、A が割れたとき止めるのは B まで (推移閉包をとらない — レビュー L10)。"""
    cov = CovarianceRecord(
        vary_list=_VARY, dependent=(),
        correlations=(CorrelatedPair("0::dAx:1", "0::AUiso:1", 0.95),
                      CorrelatedPair("0::AUiso:1", "0::AUiso:0", 0.95)),
    )
    claims = rq.assess(_result(final_covariance=cov), _PHASES).claims
    split = claims["coord:P.O1.x"].weakened_to(
        Determinacy.INITIAL_VALUE_DEPENDENT, Witness("multistart_disagreement", {"z": 9.0}),
    )
    a = rq.assess_claims({**claims, "coord:P.O1.x": split}, _result(final_covariance=cov), _PHASES)
    (req,) = [r for r in a.requests if r.kind == "initial_value_dependence"]
    assert "uiso:P.O1" in req.blocks and "uiso:P.Pb" not in req.blocks


def test_a_split_value_correlated_through_a_constraint_blocks_every_value(checks_pass):
    """混合占有の和の拘束は varyList で ``::constrN`` に置き換わり、相手の値を引けない (実 GSAS で確認)。
    拘束の中身は**別の相**のこともある (スケール ↔ 他相の占有率) ので、相手が分からない割れた値は
    全値を止める (止めすぎる側に倒す — レビュー M5 / 2 巡目 MEDIUM-2)。"""
    cov = CovarianceRecord(
        vary_list=_VARY + ("::constr0",), dependent=("0::Afrac:1",),
        correlations=(CorrelatedPair("0::AUiso:1", "::constr0", 0.97),),
    )
    claims = rq.assess(_result(final_covariance=cov), _PHASES).claims
    split = claims["uiso:P.O1"].weakened_to(
        Determinacy.INITIAL_VALUE_DEPENDENT, Witness("multistart_disagreement", {"z": 9.0}),
    )
    a = rq.assess_claims({**claims, "uiso:P.O1": split}, _result(final_covariance=cov), _PHASES)
    (req,) = [r for r in a.requests if r.kind == "initial_value_dependence"]
    assert "occupancy:P.O1" in req.blocks and "cell:Q.a" in req.blocks
    assert req.evidence["unmapped_partners"] == ["::constr0"]


def test_a_cross_phase_constraint_partner_is_not_missed(checks_pass):
    """P の分率が割れ、その変数 (Q のスケール) が Q の拘束 ``::constr0`` と相関 — Q の値も止める。"""
    cov = CovarianceRecord(
        vary_list=_VARY + ("::constr0",), dependent=(),
        correlations=(CorrelatedPair("1:0:Scale", "::constr0", 0.9),),
    )
    claims = rq.assess(_result(final_covariance=cov), _PHASES).claims
    split = claims["weight_fraction:P.wt"].weakened_to(
        Determinacy.INITIAL_VALUE_DEPENDENT, Witness("multistart_disagreement", {"z": 9.0}),
    )
    a = rq.assess_claims(
        {**claims, "weight_fraction:P.wt": split}, _result(final_covariance=cov), _PHASES,
    )
    (req,) = [r for r in a.requests if r.kind == "initial_value_dependence"]
    assert "occupancy:Q.C1" in req.blocks


def test_a_pruned_cell_is_a_frozen_cell(checks_pass):
    """剪定で凍結された格子も凍結 (レビュー L3)。"""
    res = _result(frozen_parameters=("1::A0",))
    a = rq.assess(res, _PHASES)
    assert "frozen_cell:Q" in _ids(a)


def test_a_trivially_exact_weight_fraction_is_not_blocked_by_a_frozen_cell(checks_pass):
    """単相の分率 = 1 は定義で決まる (exact) — 凍結した格子の誤差は移りようがない (2 巡目 L-a)。"""
    res = _result(
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        phase_weight_fractions={"P": 1.0}, phase_weight_fraction_esd={"P": 0.0},
    )
    a = rq.assess(res, (PhaseSpec("p.cif", "P", refine_cell=False),))
    assert "frozen_cell:P" in _ids(a)
    assert not a.claims["weight_fraction:P.wt"].gate


def test_a_frozen_cell_blocks_every_weight_fraction(checks_pass):
    """分率の和は 1 — 凍結した相の誤差は他相の分率にも同じだけ移る (レビュー L4)。"""
    phases = (PhaseSpec("p.cif", "P"), PhaseSpec("q.cif", "Q", refine_cell=False))
    a = rq.assess(_result(), phases)
    assert "frozen_cell:Q" in a.claims["weight_fraction:P.wt"].gate
