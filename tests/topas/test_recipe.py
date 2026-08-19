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
    phase = PhaseSpec(structure_path="P.cif", phase_name="P", free_occupancy_labels=("O1",))
    order = _order(build_topas_recipe([_hist()], [phase]))
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


def test_no_phase_fraction_stage_because_scale_already_is_the_phase_fraction():
    """GSAS の「相分率を構造より先に分離する」は **TOPAS では S0 で済んでいる**。

    相ごとの ``scale`` が相分率そのもので S0 が解放しており、和=1 の拘束も ``MVW`` の
    正規化があるので存在しない。段を置いても**何も変わらない段が「相分率を分離した」という
    顔で段列に残る**だけだった (実測 T4 で rwp・gof・n_params がビット同一の no-op)。
    """
    order = _order(build_topas_recipe([_hist()], [_phase("A"), _phase("B")]))
    assert "phase_fraction_sum" not in order
    assert "scale" in _order(build_topas_recipe([_hist()], [_phase()]))[:2]


def test_occupancy_stage_only_when_some_phase_declares_it():
    """`apply_stage` は**宣言されたサイトだけ**解放する — 宣言が無ければ段は構造的に空振り。"""
    plain = _order(build_topas_recipe([_hist()], [_phase()]))
    assert "occupancy" not in plain

    declared = PhaseSpec(structure_path="P.cif", phase_name="P", free_occupancy_labels=("O1",))
    assert "occupancy" in _order(build_topas_recipe([_hist()], [declared]))

    mixed = PhaseSpec(
        structure_path="P.cif", phase_name="P", mixed_occupancy_groups=(("Fe1", "Al1"),)
    )
    assert "occupancy" in _order(build_topas_recipe([_hist()], [mixed]))


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
def test_recipe_length_does_not_depend_on_the_phase_count(n_phases):
    """**相数で段は増えない** — 相分率は S0 の ``scale`` で既に自由だから。

    X 線単相/多相: scale+bg / profile / cell+disp / coords / uiso / lorentz / asym / size = 8。
    占有率段は宣言があるときだけ増える (別テスト)。
    """
    stages = build_topas_recipe([_hist()], [_phase(f"P{i}") for i in range(n_phases)])
    assert len(stages) == 8, [s.label for s in stages]


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


# ---------------- TOF の幅を解放する段とその位置 (#179) ----------------


def _tof(temperature=None) -> HistogramSpec:
    return HistogramSpec(
        data_path="d", instrument_path="i", radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER, temperature=temperature,
    )


def _synchrotron() -> HistogramSpec:
    return _hist(Radiation.XRAY_SYNCHROTRON, Geometry.DEBYE_SCHERRER)


def test_tof_histogram_gets_a_width_stage():
    """**TOPAS は装置ファイルの σ を読まない** — 幅の初期値は粗い当て推量なので解放する。

    GSAS 経路の教訓は「TOF 装置プロファイルは較正済みなので精密化しない」だったが、
    出発点が違うので同じ教訓が逆向きに効く。
    """
    assert "tof_profile" in _order(build_topas_recipe([_tof()], [_phase()]))


def test_tof_width_stage_comes_after_the_xray_profile():
    """段列の**規約**を固定する (順序が偶然変わっても気づけるように)。

    ⚠ **これは物理的な要請ではない**: 決定論実行 (1 スレッド) では前に置いても後ろに置いても
    T4 は 19.2525% でビット同一だった。当初 24 ポイントの差を観測したが、それは
    **tc.exe のスレッド依存の非決定性**であって順序の効果ではない — 同一入力の同一設定が
    43.49 / 67.62 / 43.49 / 29.29% に散らばっていた。段の効果そのものは別テストで見る。
    """
    order = _order(build_topas_recipe([_synchrotron(), _tof()], [_phase()]))
    assert order.index("profile_lorentzian") < order.index("tof_profile")


def test_no_tof_histogram_means_no_tof_stage():
    """**呼べない段を出さない** — 段が黙って no-op になるのを避ける。"""
    assert "tof_profile" not in _order(build_topas_recipe([_hist()], [_phase()]))


def test_all_tof_recipe_omits_the_size_strain_stage():
    """全 TOF では ``CS_L``/``Strain_L`` を張れない — **落ちる段を出さない**。"""
    assert "size_strain" not in _order(build_topas_recipe([_tof()], [_phase()]))


def test_mixed_recipe_marks_the_size_strain_stage_as_non_tof_only():
    """混在 joint では非 TOF にだけ張る。**段列を見た人に分かる**ようラベルへ出す。"""
    stages = build_topas_recipe([_synchrotron(), _tof()], [_phase()])
    labels = [s.label for s in stages if "size_strain" in s.flags]
    assert labels and "非 TOF" in labels[0], labels


def test_empty_histograms_do_not_get_a_stage_that_always_fails():
    """ヒストグラムが空のとき `size_strain` を出すと、適用時に必ず例外になる。

    `all_tof` は空リストでは False なので、条件を「非 TOF が 1 本でもある」にしないと
    **適用すると必ず `UnsupportedStageFlagError` で落ちる段**をレシピが抱えることになる。
    """
    assert "size_strain" not in _order(build_topas_recipe([], [_phase()]))
