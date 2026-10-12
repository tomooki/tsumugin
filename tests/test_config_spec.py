"""`_config_spec` の型検査 (``check_*``) と往復 spec の null 規則 (``spec_value``/``spec_required``)。

`config_from_dict` 経由の振る舞いは `tests/mcp/test_phase_id_spec.py` が持つ。ここは PhaseSpec /
HistogramSpec / StabilityOptions / SearchConfig が共有する部品そのものの契約を固定する。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin._config_spec import (
    check_bool,
    check_float,
    check_int,
    check_str,
    check_str_tuple,
    spec_required,
    spec_value,
)


# ---------------- spec_value: 欠落/null だけが既定 ----------------


def test_spec_value_missing_and_null_are_the_default():
    assert spec_value({}, "k", "S", 7, check_int) == 7
    assert spec_value({"k": None}, "k", "S", 7, check_int) == 7


@pytest.mark.parametrize(
    "value, check, expected",
    [(0, check_int, 0), (0.0, check_float, 0.0), ("", check_str, ""), ([], check_str_tuple, ()),
     (False, check_bool, False)],
)
def test_spec_value_does_not_collapse_falsy_values_to_the_default(value, check, expected):
    # `or` で読むと 0 / "" / [] / false が既定へ潰れる (#189: [] は「凍結」、0.0 は幅ゼロの箱)。
    assert spec_value({"k": value}, "k", "S", "DEFAULT", check) == expected


def test_spec_value_names_the_key_in_the_error():
    with pytest.raises(ValueError, match=r"^S\.k は真偽値"):
        spec_value({"k": "false"}, "k", "S", True, check_bool)


def test_spec_required_keeps_key_error_for_missing_and_refuses_null():
    with pytest.raises(KeyError):
        spec_required({}, "k", "S", check_str)
    with pytest.raises(ValueError, match=r"S\.k に null"):
        spec_required({"k": None}, "k", "S", check_str)
    assert spec_required({"k": "x"}, "k", "S", check_str) == "x"


# ---------------- check_*: 黙って別の値にしない ----------------


@pytest.mark.parametrize("value", ["false", "true", 0, 1, None])
def test_check_bool_accepts_only_real_booleans(value):
    with pytest.raises(ValueError):
        check_bool("n", value)


def test_check_int_accepts_integral_numbers_only():
    assert check_int("n", 3) == 3
    assert check_int("n", 40.0) == 40  # JSON クライアントは int/float を区別しないことがある
    assert check_int("n", np.int64(5)) == 5
    for bad in (3.9, True, "3", float("inf")):
        with pytest.raises(ValueError):
            check_int("n", bad)


def test_check_float_refuses_bools_and_strings():
    assert check_float("n", 2) == 2.0
    assert check_float("n", np.float32(0.5)) == 0.5
    for bad in (True, "2", [2.0]):
        with pytest.raises(ValueError):
            check_float("n", bad)


@pytest.mark.parametrize("value", ["O7", b"O7", 7, {"O7": 1}])
def test_check_str_tuple_refuses_anything_but_a_list(value):
    with pytest.raises(ValueError, match="リスト"):
        check_str_tuple("n", value)


def test_check_str_tuple_refuses_non_string_elements():
    with pytest.raises(ValueError, match="要素"):
        check_str_tuple("n", ["O7", 19])
    assert check_str_tuple("n", ("O7", "D1")) == ("O7", "D1")
