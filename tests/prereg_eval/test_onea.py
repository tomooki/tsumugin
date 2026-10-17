"""P0 §1.6・§4: 1A の指標 (P_val・P_case・O_det・O_pub) と R1A-1/R1A-2。"""

from __future__ import annotations

import pytest

from tsumugin.prereg_eval.onea import ValueState, assess_1a, bootstrap_interval


def _v(publishable, *, det="esd_only", main=True, outlier=None, blocked=()):
    return ValueState("k", publishable, det, main, outlier, tuple(blocked))


def test_provisional_ratios():
    cases = [
        [_v(True), _v(False, blocked=("phase_set_completeness",))],
        [_v(False, blocked=("phase_set_completeness",)), _v(False, blocked=("initial_value_dependence",))],
    ]
    r = assess_1a(cases)
    assert r.p_val == pytest.approx(3 / 4)
    assert r.p_case == pytest.approx(1 / 2)  # 主相が全部止まった事例は 2 件中 1 件
    assert r.attribution == {"phase_set_completeness": 2, "initial_value_dependence": 1}
    assert r.r1a_1 == "fired"


def test_minor_phase_values_do_not_make_a_case_fully_held():
    cases = [[_v(True), _v(False, main=False)]]
    assert assess_1a(cases).p_case == 0.0


def test_outlier_rates_need_thirty_reference_values():
    few = [[_v(True, det="determined", outlier=False)] * 29]
    assert assess_1a(few).r1a_2 == "indeterminate"
    clean = [[_v(True, det="determined", outlier=False)] * 30]
    assert assess_1a(clean).r1a_2 == "not_fired"


def test_outlier_rates_fire_above_ten_percent():
    vals = [_v(True, det="determined", outlier=True)] * 4 + [_v(True, det="determined", outlier=False)] * 26
    r = assess_1a([vals])
    assert r.o_det == pytest.approx(4 / 30) and r.o_pub == pytest.approx(4 / 30)
    assert r.r1a_2 == "fired"


def test_unpublishable_values_do_not_enter_o_pub_but_count_for_overblocking():
    vals = [_v(True, outlier=False)] * 30 + [_v(False, outlier=False)] * 10 + [_v(False, outlier=True)] * 10
    r = assess_1a([vals])
    assert r.o_pub == 0.0
    assert r.overblocking == pytest.approx(10 / 20)  # 止めた値のうち参照と一致するもの
    assert r.o_det is None  # determined の値が無い


def test_values_without_reference_are_unevaluated_for_outliers():
    r = assess_1a([[_v(True, outlier=None)] * 40])
    assert r.n_ref_values == 0 and r.o_pub is None and r.r1a_2 == "indeterminate"


def test_bootstrap_is_case_level_and_reproducible():
    per_case = [(1, 10), (0, 10), (3, 10), (0, 10)]
    a = bootstrap_interval(per_case)
    assert a == bootstrap_interval(per_case)  # 種が固定
    lo, hi = a
    assert 0.0 <= lo <= 4 / 40 <= hi <= 0.3


def test_fully_held_case_looks_only_at_main_phase_values():
    # 主相が全部止まり副相だけ出せる事例は「全止め」
    r = assess_1a([[_v(False), _v(True, main=False), _v(True, main=False)]] * 2)
    assert r.p_case == 1.0 and r.p_val == pytest.approx(1 / 3)
    assert r.r1a_1 == "fired"  # P_val は 0.5 以下でも P_case だけで発火
