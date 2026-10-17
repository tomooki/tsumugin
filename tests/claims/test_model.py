"""fit-then-judge P1-1A タスク 1: `Claim` の型 (REQ-FTJ-1A-101..106)。"""

from __future__ import annotations

import json
import math

import pytest

from tsumugin.claims.model import (
    DETERMINACY_ORDER,
    Check,
    Claim,
    Determinacy,
    Scope,
    Witness,
    compose,
    required_checks_for,
    weaker_determinacy,
    worse_check,
)


def _claim(**kw) -> Claim:
    base = dict(
        key="cell:P.a", param_class="cell", value=9.37, esd=0.001, unit="angstrom",
        phase="P", axis="a", provenance=frozenset({"refined"}),
        checks={name: Check.PASS for name in required_checks_for("cell")},
    )
    base.update(kw)
    return Claim(**base)


# ---------------------------------------------------------------- 順序と合成


def test_determinacy_order_is_the_documented_total_order():
    assert DETERMINACY_ORDER == (
        Determinacy.EXACT, Determinacy.DETERMINED, Determinacy.LOCALLY_STABLE,
        Determinacy.ESD_ONLY, Determinacy.UNDETERMINED_ESD,
        Determinacy.INITIAL_VALUE_DEPENDENT, Determinacy.UNCONVERGED,
        Determinacy.UNDETERMINABLE,
    )


@pytest.mark.parametrize(
    ("a", "b", "want"),
    [
        (Determinacy.EXACT, Determinacy.ESD_ONLY, Determinacy.ESD_ONLY),
        (Determinacy.DETERMINED, Determinacy.INITIAL_VALUE_DEPENDENT,
         Determinacy.INITIAL_VALUE_DEPENDENT),
        (Determinacy.UNCONVERGED, Determinacy.ESD_ONLY, Determinacy.UNCONVERGED),
    ],
)
def test_composition_of_determinacy_takes_the_weaker(a, b, want):
    assert weaker_determinacy(a, b) is want
    assert weaker_determinacy(b, a) is want


def test_checks_compose_to_the_worse_outcome():
    assert worse_check(Check.PASS, Check.UNEVALUATED) is Check.UNEVALUATED
    assert worse_check(Check.FAIL, Check.UNEVALUATED) is Check.FAIL
    assert worse_check(Check.PASS, Check.PASS) is Check.PASS


def test_compose_across_starts():
    a = _claim(correlations=frozenset({"cell:P.b"}), gate=frozenset({"jr-1"}))
    b = _claim(
        determinacy=Determinacy.UNCONVERGED, scope=Scope.RELATIVE_WITHIN_SAMPLE,
        correlations=frozenset({"cell:P.c"}),
        checks={**a.checks, "crystal_chemistry": Check.FAIL},
    )
    got = compose(a, b)
    assert got.determinacy is Determinacy.UNCONVERGED
    assert got.scope is Scope.RELATIVE_WITHIN_SAMPLE
    assert got.correlations == {"cell:P.b", "cell:P.c"}
    assert got.gate == {"jr-1"}
    assert got.checks["crystal_chemistry"] is Check.FAIL


def test_compose_with_different_provenance_records_it_without_downgrading():
    """出自の違いだけでは初期値依存にしない (2026-10-15 ユーザー決定, proposal §3.1 の改訂)。値が割れたかは
    開始点の一致の比較 (`with_convergence`) が決める。違ったことは証人 ``provenance_varied`` に残す。"""
    got = compose(_claim(), _claim(provenance=frozenset({"pruned"})))
    assert got.provenance == {"refined", "pruned"}
    assert got.determinacy is Determinacy.ESD_ONLY
    assert any(w.kind == "provenance_varied" for w in got.witnesses)


def test_compose_refuses_different_values_keys():
    with pytest.raises(ValueError, match="key"):
        compose(_claim(), _claim(key="cell:P.b", axis="b"))


# ---------------------------------------------------------------- 出版可否の導出


def test_a_refined_value_with_all_required_checks_passed_is_publishable():
    assert _claim().publishable is True


@pytest.mark.parametrize(
    "change",
    [
        {"gate": frozenset({"jr-phase-set"})},
        {"determinacy": Determinacy.UNDETERMINED_ESD},
        {"determinacy": Determinacy.INITIAL_VALUE_DEPENDENT},
        {"determinacy": Determinacy.UNCONVERGED},
        {"value": None},
        {"provenance": frozenset({"input"})},  # 解放しなかった入力値は出版しない
        {"provenance": frozenset()},  # 出自不明
    ],
)
def test_conditions_that_withhold_publication(change):
    assert _claim(**change).publishable is False


@pytest.mark.parametrize("outcome", [Check.UNEVALUATED, Check.FAIL])
def test_an_unpassed_required_check_withholds_publication(outcome):
    name = sorted(required_checks_for("cell"))[0]
    claim = _claim(checks={**_claim().checks, name: outcome})
    assert claim.publishable is False


def test_a_missing_required_check_counts_as_unevaluated():
    """検査を走らせ忘れた値は pass ではない (黙って pass にしない)。"""
    assert _claim(checks={}).publishable is False


def test_required_checks_are_decided_by_the_type_not_the_caller():
    assert "crystal_chemistry" in required_checks_for("coord")
    assert "crystal_chemistry" in required_checks_for("uiso")
    assert "crystal_chemistry" not in required_checks_for("cell")
    for cls in ("cell", "coord", "uiso", "occupancy", "weight_fraction", "microstructure",
                "profile"):
        assert {"phase_set_completeness", "provenance_known"} <= required_checks_for(cls)
    with pytest.raises(ValueError):
        required_checks_for("nonsense")


def test_symmetry_fixed_value_is_publishable_as_exact():
    claim = _claim(
        esd=0.0, determinacy=Determinacy.EXACT, provenance=frozenset({"symmetry"}),
    )
    assert claim.publishable is True


def test_non_required_failing_check_does_not_withhold():
    """必須でない検査の fail は記録されるが出版を止めない (止めるのは gate の役目)。"""
    claim = _claim(checks={**_claim().checks, "informational": Check.FAIL})
    assert claim.publishable is True


# ---------------------------------------------------------------- 証人の不変条件


@pytest.mark.parametrize("det", [Determinacy.DETERMINED, Determinacy.UNDETERMINABLE])
def test_strong_labels_require_a_witness(det):
    with pytest.raises(ValueError, match="witness|証人"):
        _claim(determinacy=det)


def test_determined_with_a_witness_is_accepted():
    claim = _claim(
        determinacy=Determinacy.DETERMINED,
        witnesses=(Witness("multistart_agreement", {"n_pairs": 10, "k_esd": 3.0}),),
    )
    assert claim.publishable is True


def test_value_must_be_finite_or_none():
    with pytest.raises(ValueError):
        _claim(value=math.nan)
    with pytest.raises(ValueError):
        _claim(esd=math.inf)


def test_unknown_provenance_atom_is_refused():
    with pytest.raises(ValueError, match="provenance"):
        _claim(provenance=frozenset({"magic"}))
    # 宣言・既定回答は id/版付きで許す
    _claim(provenance=frozenset({"refined", "declared:std-1", "policy_default:D-1A/1"}))


# ---------------------------------------------------------------- 直列化


def _rich_claim() -> Claim:
    return _claim(
        key="coord:P.O1.x", param_class="coord", label="O1", axis="x", unit="fractional",
        determinacy=Determinacy.DETERMINED,
        provenance=frozenset({"refined", "declared:std-1"}),
        correlations=frozenset({"coord:P.O1.y", "uiso:P.O1"}),
        scope=Scope.RELATIVE_WITHIN_SAMPLE,
        checks={"phase_set_completeness": Check.PASS, "provenance_known": Check.PASS,
                "crystal_chemistry": Check.UNEVALUATED, "validity": Check.FAIL},
        gate=frozenset({"jr-2", "jr-1"}),
        witnesses=(Witness("multistart_agreement", {"n_pairs": 10, "max_z": 1.2}),),
    )


def test_round_trip_through_json_preserves_every_axis():
    claim = _rich_claim()
    back = Claim.from_dict(json.loads(json.dumps(claim.to_dict(), allow_nan=False)))
    assert back == claim
    assert back.publishable == claim.publishable


def test_to_dict_carries_the_derived_publishable_flag_and_is_json_safe():
    d = _claim(value=None, esd=None).to_dict()
    assert d["publishable"] is False
    json.dumps(d, allow_nan=False)


def test_every_field_is_serialized():
    """フィールドを足して to_dict に載せ忘れると、往復で状態が落ちる (principles §4.4)。"""
    from dataclasses import fields

    d = _rich_claim().to_dict()
    for f in fields(Claim):
        assert f.name in d, f"{f.name} が to_dict に無い"


def test_from_dict_refuses_a_flattened_value():
    """素の float (状態の無い値) を Claim として読み込まない。"""
    with pytest.raises((TypeError, ValueError)):
        Claim.from_dict(9.37)  # type: ignore[arg-type]
    with pytest.raises((KeyError, ValueError)):
        Claim.from_dict({"value": 9.37})
