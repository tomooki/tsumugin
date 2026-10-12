"""#218: 段の間の精密化値の持ち越し (純関数)。

TOPAS は精密化値を埋め込んだ INP を ``.out`` に書き戻す。次段はその値から始めなければ
ならない — 以前は毎段 CIF の出発値から描き直しており、段階解放が「累積フラグで出発値から
解き直す」になっていた。
"""

from __future__ import annotations

import pytest

from tsumugin.topas.carry import carry_refined_values
from tsumugin.topas.inp import (
    Param,
    PhaseHistogramTerms,
    TopasDocument,
    TopasHistogram,
    TopasPhase,
    TopasSite,
)


def _doc(*, histograms=None, extras=()) -> TopasDocument:
    phase = TopasPhase(
        phase_name="P",
        space_group="Pnma",
        cell={"a": Param(8.48, refine=True)},
        sites=(TopasSite("Pb", "Pb", Param(0.1882, refine=True), Param(0.25), Param(0.167)),),
    )
    hist = TopasHistogram(
        data_path="d.xye",
        background=Param(0.0, refine=True),
        background_coeffs=3,
        phase_terms={"P": PhaseHistogramTerms(extras=tuple(extras))},
    )
    return TopasDocument(
        histograms=tuple(histograms or (hist,)), phases=(phase,), results_path="r.txt"
    )


_OUT = (
    "r_wp 9.0\n"
    "   bkg @  111.4`_1.0  13.5`_1.6 -5.9`_1.1\n"
    "      a P_a  8.482776`_0.000101\n"
    "      site Pb x P_Pb_x  0.18779`_0.00009 y 0.25 z 0.167 occ Pb 1.0 beq 1.0\n"
)


def test_named_and_background_values_are_carried_into_the_next_render():
    doc, warnings = carry_refined_values(_doc(), _OUT)
    assert warnings == ()
    text = doc.render()
    assert "      a P_a 8.482776\n" in text
    assert " x P_Pb_x 0.18779 " in text
    assert "   bkg @ 111.4 13.5 -5.9\n" in text


def test_values_not_refined_in_this_stage_keep_the_earlier_carried_value():
    """前段で持ち越した値は、この段で精密化されなかったなら**そのまま残る**。"""
    doc, _ = carry_refined_values(_doc(), _OUT)
    doc, _ = carry_refined_values(doc, "r_wp 8.0\n   bkg @ 1.0` 2.0` 3.0`\n      a P_a 8.4801`\n")
    assert doc.carried_values["P_a"] == pytest.approx(8.4801)
    assert doc.carried_values["P_Pb_x"] == pytest.approx(0.18779)


def test_refine_flags_are_untouched():
    """**値はここ、フラグは各 Param** — 持ち越しが解放状態を変えてはならない。"""
    before = _doc()
    after, _ = carry_refined_values(before, _OUT)
    assert after.phases == before.phases
    assert after.histograms[0].background == before.histograms[0].background


def test_background_rows_that_do_not_match_the_histograms_are_reported_not_guessed():
    """bkg 行の数が合わないと位置で写せない。**黙って出発値へ戻さず**警告を返す。"""
    doc, warnings = carry_refined_values(_doc(), "r_wp 9.0\n      a P_a 8.4801`\n")
    assert doc.histograms[0].background_values == ()
    assert warnings and "背景係数を持ち越せません" in warnings[0]
    assert doc.carried_values["P_a"] == pytest.approx(8.4801), "名前付きの値まで捨てている"


def test_short_preferred_orientation_line_is_replaced_by_the_expanded_block():
    """短い形のまま次段に描くと球面調和の係数が 0 から解き直しになる。"""
    doc = _doc(extras=("PO_Spherical_Harmonics(po_P_h0, 4)",))
    out = _OUT + (
        "      PO_Spherical_Harmonics(po_P_h0, 4 load sh_Cij_prm {\n"
        "\t\t\ty00   !po_P_h0_c00  1.00000\n"
        "\t\t\ty20   po_P_h0_c20  -0.06592`_0.00475\n"
        "\t\t\t} ) \n"
    )
    doc, _ = carry_refined_values(doc, out)
    (line,) = doc.histograms[0].phase_terms["P"].extras
    assert line == (
        "PO_Spherical_Harmonics(po_P_h0, 4 load sh_Cij_prm { "
        "y00 !po_P_h0_c00 1.00000 y20 po_P_h0_c20 -0.06592 } )"
    )
