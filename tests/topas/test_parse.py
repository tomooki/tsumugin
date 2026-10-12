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


def test_value_without_backtick_is_not_refined():
    vals = refined_values_from_out("a @ 8.48\n")
    assert vals == []  # バッククォートが無い = 精密化されていない値は拾わない


def test_backticked_value_without_esd_has_none_esd():
    """``do_errors`` 無しの精密化値 (``8.482776```) は拾い、esd は ``None`` (0 にしない)。

    0 にすると「完全に決まった値」と読める。esd が無いのは計算しなかったからである。
    """
    vals = refined_values_from_out("      a PbSO4_a  8.482776`\n")
    assert vals == [(pytest.approx(8.482776), None)]


def test_refined_values_skip_what_mvw_reports():
    """``MVW`` の体積・重量分率は TOPAS が計算して書き戻す**報告値** (同じ esd 記法を持つ)。"""
    vals = refined_values_from_out(
        "      a PbSO4_a  8.479139`_0.000126\n"
        "      MVW( 1213.050, 318.521`_0.008, mvw_wt_PbSO4_h0  100.000`_0.000)\n"
    )
    assert vals == [(pytest.approx(8.479139), pytest.approx(0.000126))]


def test_refined_values_stop_at_the_correlation_matrix():
    """末尾の ``C_matrix_normalized`` 以降はパラメータでなく相関行列 — 読むのはその手前まで。

    実 tc.exe の相関行列は整数だけで esd 記法を含まないが、境界は持ち越し
    (`named_refined_values_from_out`) と同じ所に引く (片方だけが行列を読む非対称を作らない)。
    """
    vals = refined_values_from_out(
        "      a PbSO4_a  8.479139`_0.000126\n"
        "C_matrix_normalized\n{\n PbSO4_a  1:  100  2.5`_0.1\n}\n"
    )
    assert vals == [(pytest.approx(8.479139), pytest.approx(0.000126))]


def test_nan_values_are_rejected():
    """NaN を数値として通さない (発散を「値がある」と誤読しない)。"""
    rec = parse_records("r_wp\tnan\n")
    assert "r_wp" not in rec.scalars or not math.isnan(rec.scalars.get("r_wp", 0.0))


def test_a_purely_numeric_key_is_not_usable():
    """**キーに裸の数字を使えない**ことを明示する (書き出し側への制約)。

    末尾の数値列を (値, esd) とみなす設計なので、``hist_rwp<TAB>0<TAB>8.6`` は
    索引 ``0`` まで数値として吸われ、キーが空になってレコードごと落ちる。書き出し側は
    ``h0`` のように非数値の接頭辞を付けること (`inp.TopasDocument._results_block`)。
    """
    assert parse_records("hist_rwp\t0\t8.6\n").keyed == {}
    assert parse_records("hist_rwp\th0\t8.6\n").keyed["hist_rwp"]["h0"] == (
        pytest.approx(8.6),
        None,
    )


# ---------------- 段の間の持ち越し: .out からの精密化値 (#218) ----------------

#: 実 tc.exe の ``.out`` (GSAS-II チュートリアル PbSO4, 公開データ) の抜粋。
#: raw 文字列: ``Out()`` の書式の ``\t`` は INP では字面 (バックスラッシュ + t) である。
_REFINED_OUT = r"""
r_p  5.66722753 r_wp  7.54225797 r_exp  4.12129093 gof  1.83007171
   prm ze0 -0.00847558532`_0.00052133348 min -0.5 max 0.5 del = .01 Yobs_dx_at(X1);
   th2_offset = ze0;
   One_on_X(!oox0, 0)
   Simple_Axial_Model(axial_h0, 9.77134733`_0.0605699294)
   lam
      la 1 lo 1.5405 lh 0.1
   bkg @  111.459139`_1.03152924  13.479005`_1.6142107 -5.96622276`_1.10063674
      a PbSO4_a  8.482776`_0.000101
      site Pb x PbSO4_Pb_x  0.18779`_0.00009 y 0.25 z !PbSO4_Pb_z 0.167 occ Pb 1.0
      TCHZ_Peak_Type(pku0_PbSO4,-0.00195887391`_0.00254119361, !pkz0_PbSO4, 0.0)
      scale PbSO4_scale_h0  0.000232608191`_8.768e-07
      CS_L(csl_PbSO4_h0, 443.12`_540.51_LIMIT_MIN_0.3)
      MVW( 1213.050, 318.923`_0.007, mvw_wt_PbSO4_h0  100.000`_0.000)
      Out(PbSO4_a, "cell\tPbSO4\ta\t%.8f", "\t%.8f\n")
C_matrix_normalized
{
                             1   2
ze0                    1:  100  74
PbSO4_a                2:   74 100
}
"""


def test_named_refined_values_are_the_backticked_ones():
    """**バッククォートが精密化値の印** — 固定値 (``!name``) とキーワード (``lo``) は拾わない。"""
    from tsumugin.topas.parse import named_refined_values_from_out

    values = named_refined_values_from_out(_REFINED_OUT)
    assert values["PbSO4_a"] == pytest.approx(8.482776)
    assert values["PbSO4_Pb_x"] == pytest.approx(0.18779)
    assert values["ze0"] == pytest.approx(-0.00847558532)
    assert values["axial_h0"] == pytest.approx(9.77134733)
    assert values["pku0_PbSO4"] == pytest.approx(-0.00195887391), "マクロ引数 (name,値) を拾っていない"
    assert values["PbSO4_scale_h0"] == pytest.approx(0.000232608191)
    assert values["csl_PbSO4_h0"] == pytest.approx(443.12), "_LIMIT_ 付きの値を拾っていない"
    for fixed in ("PbSO4_Pb_z", "pkz0_PbSO4", "oox0", "lo", "la", "lh", "r_wp", "y"):
        assert fixed not in values, f"{fixed} は精密化値ではない"


def test_named_refined_values_skip_reported_values_and_the_correlation_matrix():
    """``MVW`` の重量分率は TOPAS が計算する**報告値**、相関行列の行頭は名前だが値ではない。"""
    from tsumugin.topas.parse import named_refined_values_from_out

    values = named_refined_values_from_out(_REFINED_OUT)
    assert "mvw_wt_PbSO4_h0" not in values
    assert set(values) == {
        "ze0", "axial_h0", "PbSO4_a", "PbSO4_Pb_x", "pku0_PbSO4", "PbSO4_scale_h0",
        "csl_PbSO4_h0",
    }


def test_named_refined_values_without_do_errors_still_carry_the_backtick():
    """``do_errors`` が無いと esd は付かないがバッククォートは付く (実測: ``8.482776```)。"""
    from tsumugin.topas.parse import named_refined_values_from_out

    assert named_refined_values_from_out("      a PbSO4_a  8.482776`\n") == {
        "PbSO4_a": pytest.approx(8.482776)
    }


def test_background_values_are_read_per_line_in_order():
    """``bkg`` の係数は名前を付けられないので行と位置で持ち越す。"""
    from tsumugin.topas.parse import background_values_from_out

    text = _REFINED_OUT.replace(
        "C_matrix_normalized", "   bkg @  1.5`_0.1 -2.0`\nC_matrix_normalized"
    )
    rows = background_values_from_out(text)
    assert rows[0] == pytest.approx((111.459139, 13.479005, -5.96622276))
    assert rows[1] == pytest.approx((1.5, -2.0))
    assert len(rows) == 2, "相関行列や他の行を bkg と読んでいる"


def test_background_line_with_a_non_numeric_token_is_not_positionally_carried():
    """位置の対応が取れない行は ``None`` — 別の係数へ入れるより持ち越さない方が安全。"""
    from tsumugin.topas.parse import background_values_from_out

    assert background_values_from_out("   bkg @ 1.0`_0.1 b1 2.0\n") == [None]


def test_spherical_harmonics_block_is_flattened_to_one_line_without_esd():
    """係数を展開した形を次段の行にする (1 行の形は実 tc.exe が受理することを確認済み)。"""
    from tsumugin.topas.parse import spherical_harmonics_blocks_from_out

    text = (
        "      PO_Spherical_Harmonics(po_PbSO4_h0, 4 load sh_Cij_prm {\n"
        "\t\t\ty00   !po_PbSO4_h0_c00  1.00000\n"
        "\t\t\ty20   po_PbSO4_h0_c20  -0.06592`_0.00475\n"
        "\t\t\ty44p  po_PbSO4_h0_c44p  0.01267`_0.00418\n"
        "\t\t\t} ) \n"
    )
    assert spherical_harmonics_blocks_from_out(text) == {
        "po_PbSO4_h0": (
            "PO_Spherical_Harmonics(po_PbSO4_h0, 4 load sh_Cij_prm { "
            "y00 !po_PbSO4_h0_c00 1.00000 y20 po_PbSO4_h0_c20 -0.06592 "
            "y44p po_PbSO4_h0_c44p 0.01267 } )"
        )
    }


def test_named_refined_values_do_not_reach_across_line_breaks():
    """名前と値は同じ行にある。行末の識別子と次行頭の精密化値を組にしない。"""
    from tsumugin.topas.parse import named_refined_values_from_out

    assert named_refined_values_from_out("   lam\n   -0.5`_0.1\n") == {}
