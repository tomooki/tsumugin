"""TASK-0702: build_recipe — 段階解放レシピ生成 (GSAS 非依存)。"""

from __future__ import annotations

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.recipe import build_recipe

_XRAY_BB = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
)
_NEUTRON_DS = HistogramSpec(
    data_path="g.raw",
    instrument_path="i.prm",
    radiation=Radiation.NEUTRON_CW,
    geometry=Geometry.DEBYE_SCHERRER,
)
_SINGLE_PHASE = (PhaseSpec(structure_path="p.cif", phase_name="fap"),)


def _labels(stages):
    return [s.label for s in stages]


def _find(stages, key):
    return [s for s in stages if key in s.flags]


def test_universal_sequence_order():
    stages = build_recipe([_XRAY_BB], _SINGLE_PHASE)
    # S0 背景+scale が先頭、格子→プロファイル→座標→Uiso の順
    keys_in_order = [k for s in stages for k in ("background", "cell", "profile", "coords", "uiso") if k in s.flags]
    assert keys_in_order == ["background", "cell", "profile", "coords", "uiso"]
    # 先頭は必ず scale+background
    assert "background" in stages[0].flags and stages[0].flags.get("scale") is True


def test_bragg_brentano_uses_sample_shift():
    stages = build_recipe([_XRAY_BB], _SINGLE_PHASE)
    disp = _find(stages, "displacement")
    assert disp, "変位段階が生成される"
    mapping = disp[0].flags["displacement"]
    # ヒストグラム 0 に Shift (Bragg-Brentano)
    assert mapping[0] == ["Shift"]


def test_debye_scherrer_uses_xy_displacement():
    stages = build_recipe([_NEUTRON_DS], _SINGLE_PHASE)
    disp = _find(stages, "displacement")[0]
    assert disp.flags["displacement"][0] == ["DisplaceX", "DisplaceY"]


def test_mixed_occupancy_adds_occupancy_stage():
    phases = (
        PhaseSpec(
            structure_path="g.cif",
            phase_name="garnet",
            mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
        ),
    )
    stages = build_recipe([_NEUTRON_DS], phases)
    occ = _find(stages, "occupancy")
    assert occ, "混合占有相では占有率段階が追加される"


def test_mixed_occupancy_refines_occupancy_before_profile():
    """中性子混合占有では占有率をプロファイルより先に解放する (散乱長コントラスト)。"""
    phases = (
        PhaseSpec(
            structure_path="g.cif",
            phase_name="garnet",
            mixed_occupancy_groups=(("Fe1", "Al1"),),
        ),
    )
    stages = build_recipe([_NEUTRON_DS], phases)
    labels = [k for s in stages for k in ("occupancy", "profile") if k in s.flags]
    assert labels.index("occupancy") < labels.index("profile")


def test_single_occupancy_omits_occupancy_stage():
    stages = build_recipe([_XRAY_BB], _SINGLE_PHASE)
    assert not _find(stages, "occupancy")


def test_multiphase_adds_phase_fraction_constraint_flag():
    phases = (
        PhaseSpec(structure_path="a.cif", phase_name="nac"),
        PhaseSpec(structure_path="b.cif", phase_name="caf2"),
    )
    stages = build_recipe([_XRAY_BB], phases)
    frac = _find(stages, "phase_fraction_sum")
    assert frac, "多相では相分率和=1 制約フラグが立つ"


def test_temperature_difference_triggers_hydrostatic_strain():
    hists = (
        HistogramSpec(
            data_path="x.xra",
            instrument_path="i.prm",
            radiation=Radiation.XRAY_LAB,
            geometry=Geometry.BRAGG_BRENTANO,
            temperature=295.0,
        ),
        HistogramSpec(
            data_path="n.cwn",
            instrument_path="j.prm",
            radiation=Radiation.NEUTRON_CW,
            geometry=Geometry.DEBYE_SCHERRER,
            temperature=10.0,
        ),
    )
    stages = build_recipe(hists, _SINGLE_PHASE)
    assert _find(stages, "hydrostatic_strain"), "温度差ありで静水圧歪みが有効化"


def test_no_temperature_difference_omits_hydrostatic_strain():
    stages = build_recipe([_XRAY_BB], _SINGLE_PHASE)
    assert not _find(stages, "hydrostatic_strain")


def test_recipe_stages_are_nonempty_and_labeled():
    stages = build_recipe([_XRAY_BB], _SINGLE_PHASE)
    assert len(stages) >= 5
    assert all(s.label for s in stages)


# ---- M9: X 線プロファイル追加段階 (profile_lorentzian / profile_asymmetry) ----


def test_xray_recipe_appends_lorentzian_then_asymmetry_last():
    """X 線レシピは末尾に profile_lorentzian → profile_asymmetry を X 線限定で追加する。"""
    stages = build_recipe([_XRAY_BB], _SINGLE_PHASE)
    assert _find(stages, "profile_lorentzian")
    assert _find(stages, "profile_asymmetry")
    # 最後の 2 段が Lorentzian → asymmetry の順であること
    assert "profile_lorentzian" in stages[-2].flags
    assert "profile_asymmetry" in stages[-1].flags


def test_neutron_only_recipe_has_no_xray_profile_stages():
    """中性子のみ (CW) のレシピには X 線プロファイル追加段階を入れない。"""
    stages = build_recipe([_NEUTRON_DS], _SINGLE_PHASE)
    assert not _find(stages, "profile_lorentzian")
    assert not _find(stages, "profile_asymmetry")


def test_tof_only_recipe_has_no_xray_profile_stages():
    """TOF 中性子のみのレシピにも X 線プロファイル追加段階を入れない。"""
    tof = HistogramSpec(
        data_path="p.gsa", instrument_path="i.instprm",
        radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER,
    )
    stages = build_recipe([tof], _SINGLE_PHASE)
    assert not _find(stages, "profile_lorentzian")
    assert not _find(stages, "profile_asymmetry")


def test_mixed_xray_neutron_recipe_appends_xray_stages_once():
    """X 線 + 中性子 joint では X 線プロファイル追加段階を 1 度だけ末尾に付ける。"""
    stages = build_recipe([_XRAY_BB, _NEUTRON_DS], _SINGLE_PHASE)
    assert len(_find(stages, "profile_lorentzian")) == 1
    assert len(_find(stages, "profile_asymmetry")) == 1
