"""P0 §2.1: 事例ごとの劣化の判定 W_i (テンプレート対 比較相手 1 つ)。"""

from __future__ import annotations

import numpy as np

from tsumugin.prereg_eval.case import ArmOutcome, CaseInput, judge
from tsumugin.prereg_eval.structure import FitValue, RefValue

LATTICE = tuple(map(tuple, np.eye(3) * 10.0))
REF = (RefValue("occupancy", "Fe1", 0.60, 0.01),)


def _arm(*, failed=False, chi2=100.0, obs="h", occ=0.60, esd=0.01, f=0, b=0):
    values = () if occ is None else (FitValue("occupancy", "Fe1", occ, esd, True),)
    return ArmOutcome(failed=failed, chi2=chi2, obs_hash=obs, values=values, fail_count=f, short_bonds=b)


def _case(t, b, *, t_fit=None, reference=REF):
    arms = {"T": t, "B": b}
    if t_fit is not None:
        arms["T/bkg"] = t_fit
    return CaseInput("c1", reference=reference, lattice=LATTICE if reference else None, arms=arms)


def _judge(case, *, fit_arm=None):
    return judge(case, template="T", comparator="B", template_fit=fit_arm or "T")


def test_equal_arms_are_not_degraded():
    j = _judge(_case(_arm(), _arm()))
    assert j.status == "not_degraded" and j.fired == ()
    assert j.structure == "not_degraded"


def test_a_template_failure_is_a_loss():
    j = _judge(_case(_arm(failed=True), _arm()))
    assert j.status == "degraded" and j.fired == ("a",)
    assert j.structure == "n/a"  # 失敗で決まった事例は構造を比べようがない (unevaluated ではない)


def test_a_comparator_failure_is_the_comparators_loss():
    j = _judge(_case(_arm(), _arm(failed=True)))
    assert j.status == "not_degraded" and j.structure == "n/a"


def test_both_failed_is_counted_separately():
    assert _judge(_case(_arm(failed=True), _arm(failed=True))).status == "both_failed"


def test_fit_uses_the_background_matched_arm_and_the_equivalence_margin():
    case = _case(_arm(chi2=500.0), _arm(chi2=100.0), t_fit=_arm(chi2=110.0))
    assert _judge(case, fit_arm="T/bkg").status == "not_degraded"  # 1.10 は同値幅の内側
    case = _case(_arm(), _arm(chi2=100.0), t_fit=_arm(chi2=110.5))
    j = _judge(case, fit_arm="T/bkg")
    assert j.status == "degraded" and j.fired == ("b",)


def test_fit_is_unevaluated_when_observation_sets_differ():
    j = _judge(_case(_arm(chi2=1000.0, obs="x"), _arm(chi2=100.0, obs="y")))
    assert "b" not in j.evaluated and j.status == "not_degraded"


def test_structure_with_reference_uses_d_and_outlier_counts():
    # T は参照から 0.10 (u = 10/√2 ≈ 7.1)、B は一致 → D の差 > 1.0
    j = _judge(_case(_arm(occ=0.50), _arm(occ=0.60)))
    assert j.status == "degraded" and "c" in j.fired and j.structure == "degraded"


def test_fail_count_is_categorical():
    j = _judge(_case(_arm(f=1), _arm(f=0)))
    assert j.fired == ("d",)


def test_short_bonds_only_without_reference():
    j = _judge(_case(_arm(occ=None, b=2), _arm(occ=None, b=0), reference=None))
    assert j.fired == ("e",)
    j = _judge(_case(_arm(occ=None, b=1), _arm(occ=None, b=0), reference=None))
    assert j.status == "not_degraded"
    # 参照がある事例では (e) を見ない (c と相補)
    j = _judge(_case(_arm(b=5), _arm(b=0)))
    assert "e" not in j.evaluated


def test_nothing_evaluable_is_unevaluated_not_a_pass():
    t = ArmOutcome(failed=False, chi2=None, obs_hash=None, values=(), fail_count=None, short_bonds=None)
    j = _judge(_case(t, t))
    assert j.status == "unevaluated" and j.structure == "unevaluated"


def test_structure_part_is_unevaluated_when_only_fit_is_judged():
    t = ArmOutcome(failed=False, chi2=100.0, obs_hash="h", values=(), fail_count=None, short_bonds=None)
    j = _judge(_case(t, t))
    assert j.status == "not_degraded" and j.structure == "unevaluated"


def _many(n, shifted, *, shift, esd):
    """n 席の占有率。先頭 ``shifted`` 席だけ参照から ``shift`` ずらす。"""
    return tuple(
        FitValue("occupancy", f"S{i}", 0.5 + (shift if i < shifted else 0.0), esd, True) for i in range(n)
    )


def test_two_extra_outliers_fire_even_when_d_is_within_margin():
    ref = tuple(RefValue("occupancy", f"S{i}", 0.5, 0.001) for i in range(50))
    # 床 0.02/3 が効くので u = 0.025 / 0.00667 = 3.75 (外れ)。D_T = √(2·3.75²/50) ≈ 0.75 < 1
    t = ArmOutcome(failed=False, values=_many(50, 2, shift=0.025, esd=0.001))
    b = ArmOutcome(failed=False, values=_many(50, 0, shift=0.0, esd=0.001))
    j = judge(CaseInput("c", ref, LATTICE, {"T": t, "B": b}), template="T", comparator="B", template_fit="T")
    assert j.fired == ("c",)
    t1 = ArmOutcome(failed=False, values=_many(50, 1, shift=0.025, esd=0.001))
    j = judge(CaseInput("c", ref, LATTICE, {"T": t1, "B": b}), template="T", comparator="B", template_fit="T")
    assert j.status == "not_degraded"  # 外れ 1 件の差は偶然の範囲


def test_structure_comparison_uses_a_common_denominator():
    ref = (RefValue("occupancy", "Fe1", 0.60, 0.001),)
    # T だけで測ると u = 0.05 / 0.00667 = 7.5 だが、B の esd 0.05 に揃えると u ≈ 1.0 (D の差は同値幅の内側)
    t = ArmOutcome(failed=False, values=(FitValue("occupancy", "Fe1", 0.65, 0.001, True),))
    b = ArmOutcome(failed=False, values=(FitValue("occupancy", "Fe1", 0.60, 0.05, True),))
    j = judge(CaseInput("c", ref, LATTICE, {"T": t, "B": b}), template="T", comparator="B", template_fit="T")
    assert j.status == "not_degraded"
