"""M12 T5a: TOPAS 出力のパース (純関数)。

一次のパース対象は ``out "results.txt"`` + ``Out(...)`` が吐く**タブ区切りレコード**
(T0 実測で最も決定論的)。``.out`` (精密化後の INP そのもの) は補助的に 1 行目の指標を拾う。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.topas.parse import (
    parse_out_metrics,
    parse_records,
    refined_values_from_out,
)

# 実 tc.exe が生成した results.txt (T0/T3 実測)
_RESULTS = (
    "r_wp\t12.29700805\n"
    "gof\t2.49377456\n"
    "r_exp\t4.93108248\n"
    "r_wp_dash\t15.71134168\n"
    "wt_frac\tPbSO4\t94.96000000\t0.08000000\n"
    "wt_frac\tCaF2\t5.04000000\t0.04000000\n"
)


def test_scalar_records_are_parsed():
    rec = parse_records(_RESULTS)
    assert rec.scalars["r_wp"] == pytest.approx(12.29700805)
    assert rec.scalars["gof"] == pytest.approx(2.49377456)
    assert rec.scalars["r_exp"] == pytest.approx(4.93108248)


def test_background_subtracted_rwp_is_kept_separately():
    """`r_wp_dash` は背景差引き (実測)。GSAS 同スケールなのは `r_wp` の方なので取り違えない。"""
    rec = parse_records(_RESULTS)
    assert rec.scalars["r_wp_dash"] == pytest.approx(15.71134168)
    assert rec.scalars["r_wp"] != rec.scalars["r_wp_dash"]


def test_keyed_records_carry_value_and_esd():
    rec = parse_records(_RESULTS)
    assert rec.keyed["wt_frac"]["PbSO4"] == (pytest.approx(94.96), pytest.approx(0.08))
    assert rec.keyed["wt_frac"]["CaF2"] == (pytest.approx(5.04), pytest.approx(0.04))


def test_keyed_record_without_esd_yields_none():
    rec = parse_records("wt_frac\tX\t100.0\n")
    assert rec.keyed["wt_frac"]["X"] == (pytest.approx(100.0), None)


def test_nested_key_records_are_supported():
    """相ごと・サイトごとの 2 段キー (`cell\tPbSO4\ta\t8.48\t0.0001`)。"""
    rec = parse_records("cell\tPbSO4\ta\t8.4799\t0.000098\n")
    assert rec.keyed["cell"]["PbSO4/a"] == (pytest.approx(8.4799), pytest.approx(0.000098))


def test_blank_and_malformed_lines_are_ignored():
    """壊れた行で全体を落とさない (部分的な結果でも段の判定はできる)。"""
    rec = parse_records("\nr_wp\tnot_a_number\ngof\t1.5\n   \n")
    assert "r_wp" not in rec.scalars
    assert rec.scalars["gof"] == pytest.approx(1.5)


def test_empty_text_gives_empty_records():
    rec = parse_records("")
    assert rec.scalars == {} and rec.keyed == {}


# ---------------- .out (精密化後の INP) ----------------

_OUT = (
    "r_p  17.7869016 r_wp  26.062666 r_exp  12.020972 gof  2.16809972\n"
    "r_wp_dash  23.1846044 r_exp_dash  10.6935139\n"
    "do_errors \n"
    "iters 100 \n"
    "   ZE(@, 0.0224290623`_0.000346580638) \n"
    "      Trigonal(@  4.759537`_0.000535, @  12.993783`_0.002249) \n"
    "      a @  8.479896`_0.000098\n"
    "      scale @  8.37517516e-06`_5.229e-07\n"
    "      CS_L(@, 443.12225`_540.515641_LIMIT_MIN_0.3) \n"
)


def test_out_metrics_come_from_the_first_lines():
    m = parse_out_metrics(_OUT)
    assert m["r_wp"] == pytest.approx(26.062666)
    assert m["gof"] == pytest.approx(2.16809972)
    assert m["r_exp"] == pytest.approx(12.020972)
    assert m["r_p"] == pytest.approx(17.7869016)


def test_out_metrics_absent_gives_empty():
    assert parse_out_metrics("iters 10\n") == {}


def test_refined_values_read_value_and_esd():
    """TOPAS は精密化後の値を ``value`_esd`` (バッククォート+下線) で書き戻す。"""
    vals = refined_values_from_out(_OUT)
    assert any(
        v == pytest.approx(8.479896) and e == pytest.approx(0.000098) for v, e in vals
    )


def test_scientific_notation_is_handled():
    vals = refined_values_from_out(_OUT)
    assert any(v == pytest.approx(8.37517516e-06) for v, _ in vals)


def test_limit_suffix_does_not_corrupt_the_esd():
    """``_LIMIT_MIN_0.3`` が付いても値と esd を取り違えない。"""
    vals = refined_values_from_out("CS_L(@, 443.12225`_540.515641_LIMIT_MIN_0.3)\n")
    assert vals == [(pytest.approx(443.12225), pytest.approx(540.515641))]


def test_limit_hits_are_reported():
    """境界に張り付いたパラメータは診断として上げる (GSAS の detect_bound_hits と同じ役割)。"""
    from tsumugin.topas.parse import limit_hits_from_out

    hits = limit_hits_from_out(_OUT)
    assert hits == ("LIMIT_MIN_0.3",)


def test_no_limit_hits_when_clean():
    from tsumugin.topas.parse import limit_hits_from_out

    assert limit_hits_from_out("a @ 8.48`_0.0001\n") == ()


def test_missing_esd_is_none():
    vals = refined_values_from_out("a @ 8.48\n")
    assert vals == []  # esd 記法が無い = 精密化されていない値は拾わない


def test_nan_values_are_rejected():
    """NaN を数値として通さない (発散を「値がある」と誤読しない)。"""
    rec = parse_records("r_wp\tnan\n")
    assert "r_wp" not in rec.scalars or not math.isnan(rec.scalars.get("r_wp", 0.0))
