"""P0 §7.1: 1B の反証条件 R1-1〜R1-4・R3 と、H 単独 / H ∪ 準 hold-out の合わせ方。"""

from __future__ import annotations

import numpy as np

from tsumugin.prereg_eval.case import ArmOutcome, CaseInput, Judgment
from tsumugin.prereg_eval.falsify import (
    ProbeRow,
    SplitRow,
    either,
    exceeds_equivalence,
    r1_1,
    r1_2,
    r1_3,
    r1_4,
    r3,
)
from tsumugin.prereg_eval.structure import FitValue, RefValue


def _j(status, structure=None):
    if structure is None:
        structure = {"degraded": "degraded", "not_degraded": "not_degraded"}.get(status, "unevaluated")
    return Judgment(status=status, structure=structure, fired=(), evaluated=())


# --- R1-1 -----------------------------------------------------------------------------------


def test_r1_1_counts_only_structural_degradation():
    # フィットだけの劣化 (構造は not_degraded) は数えない
    fit_only = [_j("degraded", "not_degraded")] * 5 + [_j("not_degraded")] * 15
    assert r1_1(fit_only, [_j("not_degraded")] * 20).state == "not_fired"
    structural = [_j("degraded", "degraded")] * 3 + [_j("not_degraded")] * 17  # 0.15 > 0.10
    r = r1_1([_j("not_degraded")] * 20, structural)
    assert r.state == "fired" and "AB" in r.detail


def test_r1_1_rate_boundary_is_strict():
    exactly = [_j("degraded", "degraded")] * 2 + [_j("not_degraded")] * 18  # 0.10 ちょうどは発火しない
    assert r1_1(exactly, exactly).state == "not_fired"


def test_r1_1_indeterminate_when_structure_is_mostly_unevaluable():
    mostly = [_j("not_degraded", "unevaluated")] * 11 + [_j("not_degraded")] * 9
    assert r1_1(mostly, [_j("not_degraded")] * 20).state == "indeterminate"


# --- R1-2 -----------------------------------------------------------------------------------


def test_r1_2_fires_when_transplant_alone_matches_the_template():
    # X-transplant を「テンプレート」、テンプレートを比較相手に当てた判定。劣化の率 ≤ 0.10 → 発火 (1B の縮小)
    assert r1_2([_j("degraded")] * 1 + [_j("not_degraded")] * 10).state == "fired"
    assert r1_2([_j("degraded")] * 2 + [_j("not_degraded")] * 9).state == "not_fired"


def test_r1_2_needs_eleven_evaluable_cases():
    assert r1_2([_j("not_degraded")] * 10 + [_j("unevaluated")] * 5).state == "indeterminate"


# --- R1-3 -----------------------------------------------------------------------------------

LATTICE = tuple(map(tuple, np.eye(3) * 10.0))


def _arm(chi2=100.0, occ=0.6, f=0, b=0):
    return ArmOutcome(
        failed=False, chi2=chi2, obs_hash="h",
        values=(FitValue("occupancy", "Fe1", occ, 0.01, True),), fail_count=f, short_bonds=b,
    )


def test_exceeds_equivalence_is_two_sided():
    ref = (RefValue("occupancy", "Fe1", 0.6, 0.01),)
    base = _arm()
    for other, expected in [
        (_arm(chi2=105.0), False),
        (_arm(chi2=111.0), True),
        (_arm(chi2=90.0), True),  # 改善の向きにも同値幅を超えたら「違う」
        (_arm(occ=0.5), True),
        (_arm(f=1), True),
    ]:
        case = CaseInput("c", ref, LATTICE, {"T": base, "P": other})
        assert exceeds_equivalence(case, "T", "P") is expected, other
    # f は件数が違えば向きに関係なく「違う」
    case = CaseInput("c", ref, LATTICE, {"T": _arm(f=2), "P": _arm(f=1)})
    assert exceeds_equivalence(case, "T", "P") is True


def test_exceeds_equivalence_uses_short_bonds_without_reference():
    case = CaseInput("c", None, None, {"T": _arm(b=0), "P": _arm(b=2)})
    assert exceeds_equivalence(case, "T", "P") is True
    case = CaseInput("c", None, None, {"T": _arm(b=0), "P": _arm(b=1)})
    assert exceeds_equivalence(case, "T", "P") is False


def test_exceeds_equivalence_failure_cases():
    ok, bad = _arm(), ArmOutcome(failed=True)
    assert exceeds_equivalence(CaseInput("c", None, None, {"T": ok, "P": bad}), "T", "P") is True
    assert exceeds_equivalence(CaseInput("c", None, None, {"T": bad, "P": bad}), "T", "P") is None


def test_r1_3_fires_on_any_permutation():
    calm = [False] * 20
    noisy = [True] * 3 + [False] * 17  # 0.15
    assert r1_3({"p1": calm, "p2": calm}).state == "not_fired"
    r = r1_3({"p1": calm, "p2": noisy})
    assert r.state == "fired" and "p2" in r.detail
    assert r1_3({"p1": [None] * 5}).state == "indeterminate"


# --- R1-4 -----------------------------------------------------------------------------------


def test_r1_4_compares_template_only_and_baseline_only_splits():
    rows = [SplitRow(True, t_split=True, b_split=False)] * 3 + [SplitRow(True, False, False)] * 17
    assert r1_4(rows).state == "fired"  # (3 − 0) / 20 = 0.15
    rows = [SplitRow(True, True, False)] * 3 + [SplitRow(True, False, True)] * 2 + [SplitRow(True, False, False)] * 15
    assert r1_4(rows).state == "not_fired"  # (3 − 2) / 20 = 0.05


def test_r1_4_counts_only_cases_where_both_were_perturbed():
    rows = [SplitRow(False, True, False)] * 10 + [SplitRow(True, False, False)] * 10
    assert r1_4(rows).state == "indeterminate"  # N₄ = 10 < 11


# --- R3 -------------------------------------------------------------------------------------


def _rows(role, injected, refuted, other, outcome_other="not_refuted"):
    return [ProbeRow("p", role, injected, "refuted", None)] * refuted + [
        ProbeRow("p", role, injected, outcome_other, None)
    ] * other


def test_r3_detection_rates_have_separate_floors():
    main_ok = _rows("main", True, 8, 2)  # 0.8
    minor_ok = _rows("minor", True, 5, 5)  # 0.5
    clean = _rows("main", False, 2, 18)  # 誤発火 0.10
    assert r3(main_ok + minor_ok + clean, holdout_power=[0.9]).state == "not_fired"
    assert r3(_rows("main", True, 7, 3) + minor_ok + clean, holdout_power=[0.9]).state == "fired"
    assert r3(main_ok + _rows("minor", True, 4, 6) + clean, holdout_power=[0.9]).state == "fired"
    assert r3(main_ok + minor_ok + _rows("main", False, 3, 17), holdout_power=[0.9]).state == "fired"


def test_r3_low_power_is_not_a_detection():
    rows = _rows("main", True, 7, 3, outcome_other="not_refuted_low_power") + _rows("minor", True, 5, 5)
    assert r3(rows, holdout_power=[0.9]).state == "fired"


def test_r3_holdout_power_median():
    rows = _rows("main", True, 10, 0) + _rows("minor", True, 10, 0) + _rows("main", False, 0, 20)
    assert r3(rows, holdout_power=[0.5, 0.7, 0.95]).state == "fired"  # 中央値 0.7 < 0.8
    assert r3(rows, holdout_power=[0.5, 0.85, 0.95]).state == "not_fired"


def test_r3_indeterminate_when_a_rate_has_no_rows():
    # 無注入の事例が無ければ誤発火率を測れない — 「発火しない」にしない
    rows = _rows("main", True, 10, 0) + _rows("minor", True, 10, 0)
    assert r3(rows, holdout_power=[0.9]).state == "indeterminate"


def test_r3_indeterminate_when_probes_mostly_fail():
    rows = _rows("main", True, 4, 0) + _rows("main", True, 0, 5, outcome_other="unevaluated")
    assert r3(rows, holdout_power=[0.9]).state == "indeterminate"


# --- H 単独と合算 ---------------------------------------------------------------------------


def test_either_fires_if_any_fires_and_is_conservative_otherwise():
    from tsumugin.prereg_eval.falsify import Falsification

    f = Falsification("R1-1", "fired", "")
    n = Falsification("R1-1", "not_fired", "")
    i = Falsification("R1-1", "indeterminate", "")
    assert either(n, f).state == "fired"
    assert either(i, f).state == "fired"
    assert either(n, i).state == "indeterminate"
    assert either(n, n).state == "not_fired"


def test_r1_2_boundary_is_inclusive():
    # 「0.10 以下」で発火 (= 移植だけでテンプレートとほぼ同等)
    assert r1_2([_j("degraded")] * 2 + [_j("not_degraded")] * 18).state == "fired"


def test_r3_half_rule_counts_all_s_eval_rows():
    rows = (
        _rows("main", True, 8, 2)
        + _rows("main", True, 0, 60, outcome_other="unevaluated(diverged)")
        + _rows("minor", True, 5, 5)
        + _rows("main", False, 0, 20)
    )
    assert r3(rows, holdout_power=[0.9]).state == "indeterminate"  # 60/100 が評価できない
