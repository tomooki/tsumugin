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
            mixed_occupancy_sites=("Fe2", "Al3"),
        ),
    )
    stages = build_recipe([_NEUTRON_DS], phases)
    occ = _find(stages, "occupancy")
    assert occ, "混合占有相では占有率段階が追加される"


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
