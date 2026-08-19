"""M12: TOPAS 向けの段階解放レシピ (純関数)。

**GSAS と順序が違うことが本質**: GSAS は装置ファイルから較正済み Caglioti U,V,W を読んで
始まるので格子を先に解放しても収束するが、TOPAS の TCHZ は装置ファイルを参照せず汎用初期値
から始まるため、ピーク幅が合わないまま格子を解放すると格子が幅の不一致を吸収して悪化する
(実測 garnet: GSAS 順だと S1 cell が 42.7 → 50.7 で revert、最終 23.6% 頭打ち)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.topas.recipe import build_topas_recipe


def _hist(
    radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, temperature=None
) -> HistogramSpec:
    return HistogramSpec(
        data_path="d", instrument_path="i", radiation=radiation, geometry=geometry,
        temperature=temperature,
    )


def _phase(name="P") -> PhaseSpec:
    return PhaseSpec(structure_path=f"{name}.cif", phase_name=name)


def _order(stages) -> list[str]:
    return [k for s in stages for k in s.flags]


def test_profile_comes_before_cell():
    """**これが TOPAS レシピの存在理由**。逆にすると格子がピーク幅の不一致を吸収する。"""
    order = _order(build_topas_recipe([_hist()], [_phase()]))
    assert order.index("profile") < order.index("cell")


def test_scale_and_background_come_first():
    stages = build_topas_recipe([_hist()], [_phase()])
    assert set(stages[0].flags) == {"background", "scale"}


def test_background_coefficient_count_is_threaded_through():
    stages = build_topas_recipe([_hist()], [_phase()], background_coeffs=24)
    assert stages[0].flags["background"]["coeffs"] == 24


def test_structure_comes_after_peak_position():
    """座標/占有率/Uiso はピーク位置 (格子+ゼロ点) が合ってから。"""
    order = _order(build_topas_recipe([_hist()], [_phase()]))
    for structural in ("coords", "occupancy", "uiso"):
        assert order.index("cell") < order.index(structural)


def test_size_strain_is_last():
    """微細構造は装置プロファイルと強く縮退するので最後に置く。"""
    order = _order(build_topas_recipe([_hist()], [_phase()]))
    assert order[-1] == "size_strain"


def test_displacement_covers_every_histogram():
    stages = build_topas_recipe([_hist(), _hist()], [_phase()])
    disp = next(s.flags["displacement"] for s in stages if "displacement" in s.flags)
    assert set(disp) == {0, 1}


def test_multiphase_separates_phase_fractions_before_structure():
    """多相は相分率を構造より先に分離する (M7 T4 の教訓)。"""
    order = _order(build_topas_recipe([_hist()], [_phase("A"), _phase("B")]))
    assert "phase_fraction_sum" in order
    assert order.index("phase_fraction_sum") < order.index("coords")


def test_single_phase_has_no_phase_fraction_stage():
    assert "phase_fraction_sum" not in _order(build_topas_recipe([_hist()], [_phase()]))


def test_lorentzian_stage_only_for_xray():
    xray = _order(build_topas_recipe([_hist()], [_phase()]))
    neutron = _order(
        build_topas_recipe([_hist(Radiation.NEUTRON_CW, Geometry.DEBYE_SCHERRER)], [_phase()])
    )
    assert "profile_lorentzian" in xray
    assert "profile_lorentzian" not in neutron


def test_tof_does_not_release_the_instrument_profile():
    """TOF の装置プロファイルは較正済み — 解放すると壊れる (GSAS 経路 T4 と同じ教訓)。"""
    order = _order(
        build_topas_recipe([_hist(Radiation.NEUTRON_TOF, Geometry.DEBYE_SCHERRER)], [_phase()])
    )
    for flag in ("profile", "profile_lorentzian", "profile_asymmetry"):
        assert flag not in order


def test_mixed_tof_and_cw_still_refines_the_cw_profile():
    order = _order(
        build_topas_recipe(
            [_hist(Radiation.NEUTRON_TOF, Geometry.DEBYE_SCHERRER), _hist()], [_phase()]
        )
    )
    assert "profile" in order


def test_every_stage_has_a_label_and_a_note():
    for stage in build_topas_recipe([_hist()], [_phase()]):
        assert stage.label and stage.note, f"{stage.label!r} に説明が無い"


def test_is_deterministic():
    a = build_topas_recipe([_hist()], [_phase()])
    b = build_topas_recipe([_hist()], [_phase()])
    assert [(s.label, dict(s.flags)) for s in a] == [(s.label, dict(s.flags)) for s in b]


def test_labels_are_unique():
    labels = [s.label for s in build_topas_recipe([_hist()], [_phase("A"), _phase("B")])]
    assert len(labels) == len(set(labels))


def test_empty_histograms_still_produces_the_opening_stage():
    """ヒストグラム無しでも例外にせず最小のレシピを返す (呼び出し側が判断する)。"""
    stages = build_topas_recipe([], [_phase()])
    assert stages and "background" in stages[0].flags


@pytest.mark.parametrize("n_phases", [1, 2, 3])
def test_recipe_length_grows_only_with_the_phase_fraction_stage(n_phases):
    stages = build_topas_recipe([_hist()], [_phase(f"P{i}") for i in range(n_phases)])
    # 単相 X 線: scale+bg / profile / cell+disp / coords / occ / uiso / lorentz / asym / size = 9
    expected = 10 if n_phases > 1 else 9
    assert len(stages) == expected


# ---------------- 温度差の吸収 (#173) ----------------


def _cw_neutron(temperature):
    return _hist(Radiation.NEUTRON_CW, Geometry.DEBYE_SCHERRER, temperature=temperature)


def test_temperature_difference_adds_a_hydrostatic_strain_stage():
    """joint のヒストグラムが別温度なら、格子は共有したまま per-xdd のずれを許す。

    M7 T3 (PbSO4) は X 線 295 K / 中性子 10 K で、GSAS 経路は per-histogram Dij を張って
    6.66% を出している。共有セル 1 本で両方を説明しようとすると**両方が同じくらい悪くなる**。
    """
    stages = build_topas_recipe(
        [_hist(temperature=295.0), _cw_neutron(10.0)], [_phase()]
    )
    assert "hydrostatic_strain" in _order(stages)
    order = _order(stages)
    # 格子を合わせてからずれを許す (先に張ると格子が決まらない)
    assert order.index("cell") <= order.index("hydrostatic_strain")


def test_same_temperature_does_not_add_the_stage():
    stages = build_topas_recipe(
        [_hist(temperature=295.0), _cw_neutron(295.0)], [_phase()]
    )
    assert "hydrostatic_strain" not in _order(stages)


def test_single_histogram_never_gets_the_stage():
    """単一ヒストグラムでは格子そのものと縮退する (`apply_stage` が落とす段を出さない)。"""
    stages = build_topas_recipe([_hist(temperature=295.0)], [_phase()])
    assert "hydrostatic_strain" not in _order(stages)


def test_unknown_temperature_does_not_add_the_stage():
    """温度が書かれていないヒストグラムを「差がある」と扱わない (推測で段を足さない)。"""
    stages = build_topas_recipe([_hist(), _cw_neutron(None)], [_phase()])
    assert "hydrostatic_strain" not in _order(stages)
