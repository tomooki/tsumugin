"""M12 T6: 段階フラグ → TOPAS 解放指示 (純関数)。

`autorietveld.engine._apply_stage` の TOPAS 版。中立な宣言的フラグを受け取り、
`TopasDocument` を「そのパラメータが解放された新しい文書」へ純粋変換する。

**未対応フラグを黙って無視しない**ことが要点 — 無視すると「段を適用したのに何も解放されて
いない」段が rwp にも reverted にも現れないまま完走する (CLAUDE.md の無言 no-op と同型)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import RefinementStage
from tsumugin.topas.flags import SUPPORTED_FLAGS, UnsupportedStageFlagError, apply_stage
from tsumugin.topas.inp import (
    Param,
    PhaseHistogramTerms,
    TopasDocument,
    TopasHistogram,
    TopasPhase,
    TopasSite,
)


def _phase(**kw) -> TopasPhase:
    base = dict(
        phase_name="P",
        space_group="Pnma",
        cell={"a": Param(8.0), "b": Param(5.0), "c": Param(7.0)},
        sites=(
            TopasSite(
                "Pb", "Pb", Param(0.1), Param(0.25), Param(0.2),
                occupancy=Param(1.0), beq=Param(1.0), free_coord_axes=("x", "z"),
            ),
            TopasSite(
                "O", "O", Param(0.3), Param(0.4), Param(0.5),
                occupancy=Param(1.0), beq=Param(1.0), free_coord_axes=("x", "y", "z"),
            ),
        ),
        free_cell_keys=("a", "b", "c"),
    )
    base.update(kw)
    return TopasPhase(**base)  # type: ignore[arg-type]


def _hist(**kw) -> TopasHistogram:
    base = dict(
        data_path="d.xye",
        preamble=(
            "prm !ze0 0.0 min -0.5 max 0.5",
            "th2_offset = ze0;",
            "TCHZ_Peak_Type(!pku0, 0.0, !pkw0, 0.003, !pky0, 0.03)",
        ),
        background=Param(0.0),
        background_coeffs=6,
    )
    base.update(kw)
    return TopasHistogram(**base)  # type: ignore[arg-type]


def _doc(phase=None, hist=None) -> TopasDocument:
    return TopasDocument(histograms=(hist or _hist(),), phases=(phase or _phase(),))


def _apply(flags: dict, doc: TopasDocument | None = None) -> TopasDocument:
    return apply_stage(doc or _doc(), RefinementStage(label="S", flags=flags))


# ---------------- 未対応フラグ (最重要) ----------------


@pytest.mark.parametrize("flag", ["tof_profile", "hydrostatic_strain"])
def test_unsupported_flags_raise_instead_of_being_ignored(flag):
    """**黙って無視しない**。無視すると解放されていない段が完走する (無言 no-op 病理)。"""
    with pytest.raises(UnsupportedStageFlagError, match=flag):
        _apply({flag: True})


def test_error_names_the_stage_so_it_can_be_located():
    with pytest.raises(UnsupportedStageFlagError, match="S9"):
        apply_stage(_doc(), RefinementStage(label="S9", flags={"tof_profile": True}))


def test_supported_flag_set_matches_what_the_recipe_can_emit():
    """`build_topas_recipe` が出すフラグはすべて翻訳できること (自分で吐いて自分で落ちない)。"""
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.topas.recipe import build_topas_recipe

    hist = HistogramSpec(
        data_path="d", instrument_path="i",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )
    spec = PhaseSpec(structure_path="p.cif", phase_name="P")
    emitted = {k for stage in build_topas_recipe([hist], [spec]) for k in stage.flags}
    assert emitted <= SUPPORTED_FLAGS, f"レシピが未対応フラグを出す: {emitted - SUPPORTED_FLAGS}"


# ---------------- 個々のフラグ ----------------


def test_background_sets_coefficient_count_and_releases():
    out = _apply({"background": {"coeffs": 12}})
    assert out.histograms[0].background_coeffs == 12
    assert out.histograms[0].background.refine is True


def test_scale_releases_per_phase_histogram_term():
    out = _apply({"scale": True})
    assert out.histograms[0].phase_terms["P"].scale.refine is True


def test_cell_releases_only_symmetry_free_axes():
    phase = _phase(
        cell={"a": Param(8.0), "b": Param.reference("Get(a)"), "c": Param(7.0)},
        free_cell_keys=("a", "c"),
    )
    out = _apply({"cell": True}, _doc(phase=phase))
    assert out.phases[0].cell["a"].refine is True
    assert out.phases[0].cell["c"].refine is True
    assert out.phases[0].cell["b"].is_reference  # 従属軸は解放しない


def test_cell_false_re_freezes():
    released = _apply({"cell": True})
    out = apply_stage(released, RefinementStage(label="S", flags={"cell": False}))
    assert not any(p.refine for p in out.phases[0].cell.values())


def test_coords_release_only_free_axes():
    """特殊位置を解放すると対称性が壊れる (しかも Rwp は下がりうる)。"""
    out = _apply({"coords": True})
    pb, o = out.phases[0].sites
    assert (pb.x.refine, pb.y.refine, pb.z.refine) == (True, False, True)  # y=1/4 は固定
    assert (o.x.refine, o.y.refine, o.z.refine) == (True, True, True)


def test_uiso_releases_beq():
    out = _apply({"uiso": True})
    assert all(s.beq.refine for s in out.phases[0].sites)


def test_occupancy_releases_only_declared_sites():
    """占有率はスケールと大域的に縮退するので全サイト一斉解放をしない。"""
    out = _apply({"occupancy": True}, _doc(phase=_phase(free_occupancy_labels=("O",))))
    released = {s.label for s in out.phases[0].sites if s.occupancy.refine}
    assert released == {"O"}


def test_occupancy_with_no_declaration_releases_nothing():
    out = _apply({"occupancy": True})
    assert not any(s.occupancy.refine for s in out.phases[0].sites)


def test_shared_group_prms_are_released_by_their_stage():
    phase = _phase(occupancy_sum_groups=(("Pb", "O"),), beq_equiv_groups=(("Pb", "O"),))
    assert phase.release_occupancy_groups is False
    occ = _apply({"occupancy": True}, _doc(phase=phase))
    assert occ.phases[0].release_occupancy_groups is True
    uiso = _apply({"uiso": True}, _doc(phase=phase))
    assert uiso.phases[0].release_beq_groups is True


def test_size_strain_releases_both_terms():
    out = _apply({"size_strain": True})
    terms = out.histograms[0].phase_terms["P"]
    assert terms.size_lorentzian.refine and terms.strain_lorentzian.refine


def test_displacement_releases_the_zero_point():
    out = _apply({"displacement": {0: ["Shift"]}})
    assert any(line.startswith("prm ze0 ") for line in out.histograms[0].preamble)


def test_releasing_the_zero_point_does_not_corrupt_the_reference_expression():
    """**同じ名前が参照側にも現れる** — ``th2_offset = ze0;`` を ``= !ze0;`` にしない。

    ``!`` が意味を持つのは宣言のときだけ。行全体を置換対象にすると INP が壊れる。
    """
    hist = _hist(preamble=("prm !ze0 0.0 min -0.5 max 0.5", "th2_offset = ze0;"))
    out = _apply({"displacement": {0: ["Shift"]}}, _doc(hist=hist))
    assert out.histograms[0].preamble == (
        "prm ze0 0.0 min -0.5 max 0.5",
        "th2_offset = ze0;",
    )


def test_the_zero_point_box_survives_release_and_freeze():
    """束縛は解放/凍結で消えない (箱が消えるとゼロ点が暴走する)。"""
    hist = _hist(preamble=("prm !ze0 0.0 min -0.5 max 0.5", "th2_offset = ze0;"))
    released = _apply({"displacement": {0: ["Shift"]}}, _doc(hist=hist))
    frozen = apply_stage(released, RefinementStage(label="S", flags={"freeze_others": True}))
    for doc in (released, frozen):
        assert any("min -0.5 max 0.5" in line for line in doc.histograms[0].preamble)


@pytest.mark.parametrize(
    ("flag", "released"), [("profile", ("pku", "pkw")), ("profile_lorentzian", ("pky",))]
)
def test_profile_flags_unfreeze_the_named_tchz_terms(flag, released):
    hist = _hist(
        phase_terms={
            "P": PhaseHistogramTerms(
                peak_type="TCHZ_Peak_Type(!pku0, 0.0, !pkw0, 0.003, !pkx0, 0.0, !pky0, 0.03)"
            )
        }
    )
    out = _apply({flag: True}, _doc(hist=hist))
    line = out.histograms[0].phase_terms["P"].peak_type
    for marker in released:
        assert f"!{marker}" not in line, f"{marker} が解放されていない"


def test_profile_asymmetry_is_added_once():
    once = _apply({"profile_asymmetry": True})
    twice = _apply({"profile_asymmetry": True}, once)
    assert sum("Simple_Axial_Model" in x for x in twice.histograms[0].preamble) == 1


def test_phase_fraction_sum_is_a_documented_noop():
    """TOPAS は MVW が重量分率を正規化するので制約不要。**フラグ自体は受理する**。"""
    out = _apply({"phase_fraction_sum": True})
    assert out.phases[0].phase_name == "P"  # 例外にならず素通りする


def test_freeze_others_drops_accumulated_releases():
    released = _apply({"cell": True, "coords": True, "uiso": True})
    frozen = apply_stage(released, RefinementStage(label="S", flags={"freeze_others": True}))
    assert not any(p.refine for p in frozen.phases[0].cell.values())
    assert not any(s.x.refine or s.beq.refine for s in frozen.phases[0].sites)


# ---------------- 純関数性 ----------------


def test_apply_stage_does_not_mutate_the_input_document():
    doc = _doc()
    before = doc.render()
    _apply({"cell": True, "coords": True, "uiso": True}, doc)
    assert doc.render() == before


def test_releases_accumulate_across_stages():
    """段は既定で累積 (解放を落とすのは freeze_others だけ)。"""
    doc = _apply({"cell": True})
    doc = apply_stage(doc, RefinementStage(label="S2", flags={"uiso": True}))
    assert doc.phases[0].cell["a"].refine is True
    assert all(s.beq.refine for s in doc.phases[0].sites)


# ---------------- 選択配向 / 吸収 (#173) ----------------


def _extras(doc, phase="P", hist=0):
    return doc.histograms[hist].phase_terms[phase].extras


def test_preferred_orientation_uses_spherical_harmonics():
    """GSAS の ``Pref.Ori.`` (次数付き) は TOPAS の ``PO_Spherical_Harmonics`` に対応する。

    March-Dollase (``PO``) は**hkl 方向を引数に要求する**が、中立フラグはその情報を運ばない。
    方向を勝手に決めると「別のモデルを黙って当てはめた」ことになるので球面調和を使う。
    """
    out = _apply({"preferred_orientation": 4})
    assert any("PO_Spherical_Harmonics" in x and " 4)" in x for x in _extras(out))


def test_preferred_orientation_true_defaults_to_order_four():
    assert any(" 4)" in x for x in _extras(_apply({"preferred_orientation": True})))


def test_preferred_orientation_names_are_unique_per_phase_and_histogram():
    """**TOPAS のパラメータ名は大域** — 相ごと/ヒストグラムごとに別の配向分布を持てること。"""
    doc = TopasDocument(
        histograms=(_hist(), _hist()),
        phases=(_phase(), _phase(phase_name="Q")),
    )
    out = _apply({"preferred_orientation": 4}, doc)
    names = [
        x.split("(")[1].split(",")[0]
        for h in out.histograms
        for terms in h.phase_terms.values()
        for x in terms.extras
        if "PO_Spherical" in x
    ]
    assert len(names) == 4 and len(set(names)) == 4


def test_preferred_orientation_is_added_once():
    once = _apply({"preferred_orientation": 4})
    twice = _apply({"preferred_orientation": 4}, once)
    assert sum("PO_Spherical" in x for x in _extras(twice)) == 1


def test_freeze_others_removes_preferred_orientation():
    """球面調和は**宣言そのものが解放**なので、凍結は行を落とすことで表す。"""
    released = _apply({"preferred_orientation": 4})
    frozen = apply_stage(released, RefinementStage(label="S", flags={"freeze_others": True}))
    assert not any("PO_Spherical" in x for x in _extras(frozen))


def test_absorption_is_a_shared_cylindrical_correction():
    """吸収は**試料**の性質なので、多相でも 1 つの µR を共有する。

    TOPAS の ``scale_pks`` は ``str`` ブロックにしか書けないため各相へ行を出すが、
    値は共有 ``prm`` を参照させる (相ごとに別の µR を持つと物理的に誤り)。

    **マクロではなくその展開形**を書く: ``Cylindrical_I_Correction(=mur_h0;)`` は
    ``Error loading sstring_in`` で異常終了する (実測)。マクロは自分で ``prm`` を宣言する
    形しか通らないので、共有したい場合は展開形を書くしかない。
    """
    doc = TopasDocument(histograms=(_hist(),), phases=(_phase(), _phase(phase_name="Q")))
    out = _apply({"absorption": True}, doc)
    lines = [x for terms in out.histograms[0].phase_terms.values() for x in terms.extras]
    assert len(lines) == 2
    assert all(x.startswith("scale_pks = AL_Cyl_Corr(mur_h0)") for x in lines)
    assert all("Cylindrical_I_Correction" not in x for x in lines)
    assert any(p.name == "mur_h0" and p.refine for p in out.shared_params)


def test_absorption_is_refused_for_bragg_brentano():
    """反射光学系に円筒吸収を当てない — **黙って別のモデルを適用しない**。"""
    hist = _hist(is_bragg_brentano=True)
    with pytest.raises(UnsupportedStageFlagError, match="absorption"):
        _apply({"absorption": True}, _doc(hist=hist))
