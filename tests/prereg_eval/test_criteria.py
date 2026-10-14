"""P0 §1.2 (50% 規則)・§2.2 (通過基準)・§2.3 (3 値の結論)。"""

from __future__ import annotations

from tsumugin.prereg_eval.case import Judgment
from tsumugin.prereg_eval.criteria import compare, conclude


def _j(status, structure=None):
    if structure is None:
        structure = {"degraded": "degraded", "not_degraded": "not_degraded"}.get(status, "unevaluated")
    return Judgment(status=status, structure=structure, fired=(), evaluated=())


def test_passes_within_the_allowed_count():
    r = compare([_j("degraded")] * 2 + [_j("not_degraded")] * 22)
    assert r.n == 24 and r.n_degraded == 2 and r.allowed == 2 and r.verdict == "pass"


def test_fails_above_the_allowed_count():
    r = compare([_j("degraded")] * 3 + [_j("not_degraded")] * 21)
    assert r.verdict == "fail"


def test_too_few_evaluable_cases_is_indeterminate():
    r = compare([_j("not_degraded")] * 23 + [_j("unevaluated")] * 1)
    assert r.n == 23 and r.verdict == "indeterminate"


def test_unevaluated_and_both_failed_are_reported_not_counted():
    r = compare([_j("not_degraded")] * 24 + [_j("both_failed")] * 2 + [_j("unevaluated")] * 3)
    assert (r.n, r.n_both_failed, r.n_unevaluated) == (24, 2, 3)
    assert r.verdict == "pass"


def test_more_than_half_unevaluated_is_indeterminate():
    r = compare([_j("not_degraded")] * 24 + [_j("unevaluated")] * 25)
    assert r.verdict == "indeterminate" and "W_i" in r.indeterminate_because


def test_structure_part_has_its_own_half_rule():
    # W_i はフィットだけで決まり、構造の部分が過半で判定できない
    r = compare([_j("not_degraded", "unevaluated")] * 13 + [_j("not_degraded")] * 11)
    assert r.verdict == "indeterminate" and "structure" in r.indeterminate_because


def test_failure_cases_do_not_count_as_unevaluable_structure():
    # 失敗で決まった事例は構造を比べようがない — 50% 規則の分母に入れない
    r = compare([_j("degraded", "n/a")] * 2 + [_j("not_degraded", "n/a")] * 11
                + [_j("not_degraded")] * 11)
    assert r.verdict == "pass"


def test_conclusion_needs_both_comparisons_and_no_fired_falsification():
    ok = compare([_j("not_degraded")] * 24)
    bad = compare([_j("degraded")] * 5 + [_j("not_degraded")] * 19)
    unk = compare([_j("not_degraded")] * 10)
    assert conclude(ok, ok, fired=(), indeterminate=()).verdict == "pass"
    assert conclude(ok, bad, fired=(), indeterminate=()).verdict == "fail"
    assert conclude(ok, unk, fired=(), indeterminate=()).verdict == "indeterminate"
    assert conclude(ok, ok, fired=("R1-1",), indeterminate=()).verdict == "fail"
    assert conclude(ok, ok, fired=(), indeterminate=("R3",)).verdict == "indeterminate"
    # 不通過の根拠がはっきりしていれば、ほかが判定不能でも不通過
    assert conclude(bad, unk, fired=(), indeterminate=()).verdict == "fail"


def test_failure_decided_cases_are_outside_the_structure_denominator():
    # 構造を比べられた事例 14 件のうち 8 件が評価できない → 過半。失敗で決まった 10 件で薄めない
    r = compare([_j("not_degraded", "n/a")] * 10 + [_j("not_degraded", "unevaluated")] * 8
                + [_j("not_degraded")] * 6)
    assert r.verdict == "indeterminate" and "structure" in r.indeterminate_because
