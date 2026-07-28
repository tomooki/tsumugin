"""TASK-0702: build_recipe — 段階解放レシピ生成 (GSAS 非依存)。"""

from __future__ import annotations

import pytest

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
    # S0 背景+scale が先頭、格子→プロファイル→座標→Uiso の順。
    # 【解放と凍結を区別する】: 変位段は格子を **凍結** する (`{"cell": False}`) ため
    # メンバシップ (`k in s.flags`) だけ見ると「格子を解放した段」と数えてしまう。
    # 初出の順序だけを見る (交互精密化 cell → 変位 → cell の再解放は重複として畳む)。
    released = [
        k
        for s in stages
        for k in ("background", "cell", "profile", "coords", "uiso")
        if s.flags.get(k) not in (None, False)
    ]
    assert list(dict.fromkeys(released)) == ["background", "cell", "profile", "coords", "uiso"]
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


# ---------------------------------------------------------------------------
# 規定: cell 単独 → 試料変位は後段 (2026-07-27)
# ---------------------------------------------------------------------------


def _stage_index(stages, flag: str) -> int:
    """``flag`` を持つ最初の段の index (無ければ -1)。"""
    for i, s in enumerate(stages):
        if flag in s.flags:
            return i
    return -1


def _all_flag_indices(stages, flag: str) -> list[int]:
    return [i for i, s in enumerate(stages) if flag in s.flags]


@pytest.mark.parametrize("multiphase", [False, True], ids=["single", "multi"])
@pytest.mark.parametrize("mixed_occ", [False, True], ids=["plain", "mixed_occ"])
def test_cell_is_never_released_together_with_sample_displacement(multiphase, mixed_occ):
    """**規定**: 格子と試料変位を同じ段で解放しない。

    どちらも 2θ を動かすため強く相関する (Bragg-Brentano の `Shift` は
    ``pos -= const·4·Shift·cosθ`` で、格子定数の変化とほぼ同じ形のピークシフトを作る)。
    同時に自由にすると片方が他方を吸収し、**物理的に誤った格子で自己整合な解**へ落ちる
    (実測: Kα1 単色 CaTeO3 で Shift −274 µm 相当のずれを格子が肩代わりしていた)。
    段を分けるのは相関するパラメータを分離する段階解放の規律そのもの。

    ⚠ 変位段は格子を**凍結**する (``{"cell": False}``) — これは同時解放ではないので
    「解放したか」(値が True か) で判定する。キーの有無で見ると凍結を誤検出する。
    """
    stages = build_recipe(
        _histograms(multiphase), _phases(multiphase, mixed_occ)
    )
    for s in stages:
        assert not (s.flags.get("cell") is True and "displacement" in s.flags), (
            f"格子と試料変位が同じ段で解放されている: {s.label} {sorted(s.flags)}"
        )


@pytest.mark.parametrize("multiphase", [False, True], ids=["single", "multi"])
@pytest.mark.parametrize("mixed_occ", [False, True], ids=["plain", "mixed_occ"])
def test_sample_displacement_comes_after_the_cell(multiphase, mixed_occ):
    """**規定**: 変位は格子より**後**の段で解放する (cell 単独 → Shift 後段)。"""
    stages = build_recipe(_histograms(multiphase), _phases(multiphase, mixed_occ))
    i_cell = _stage_index(stages, "cell")
    i_disp = _stage_index(stages, "displacement")
    assert i_cell >= 0 and i_disp >= 0, [s.label for s in stages]
    assert i_disp > i_cell, [s.label for s in stages]


@pytest.mark.parametrize("multiphase", [False, True], ids=["single", "multi"])
def test_sample_displacement_is_released_exactly_once(multiphase):
    """変位段は 1 つだけ (段を分けた結果の取りこぼし/重複がない)。"""
    stages = build_recipe(_histograms(multiphase), _phases(multiphase, False))
    assert len(_all_flag_indices(stages, "displacement")) == 1, [s.label for s in stages]


def test_sample_displacement_is_separated_from_zero():
    """変位と Zero も別段にする (どちらも 2θ の定数/角度依存オフセットで相関する)。

    ``profile_lorentzian`` 段が X,Y と一緒に Zero を解放するため、変位段はその**前**に置く。
    """
    stages = build_recipe(_histograms(False), _phases(False, False))  # X 線 → lorentzian 段あり
    i_disp = _stage_index(stages, "displacement")
    i_zero = _stage_index(stages, "profile_lorentzian")
    assert i_zero >= 0, [s.label for s in stages]
    assert i_disp < i_zero, [s.label for s in stages]


def test_hydrostatic_strain_stays_with_the_cell():
    """温度差 Dij は**格子側**のパラメータなので cell 段に残す (変位と一緒に動かさない)。"""
    hists = (
        HistogramSpec(data_path="a", instrument_path="i", radiation=Radiation.NEUTRON_CW,
                      geometry=Geometry.DEBYE_SCHERRER, data_format="XYE", temperature=300.0),
        HistogramSpec(data_path="b", instrument_path="i", radiation=Radiation.NEUTRON_CW,
                      geometry=Geometry.DEBYE_SCHERRER, data_format="XYE", temperature=500.0),
    )
    stages = build_recipe(hists, _phases(False, False))
    cell_stage = next(s for s in stages if "cell" in s.flags)
    assert "hydrostatic_strain" in cell_stage.flags
    assert "displacement" not in cell_stage.flags


# ---------------------------------------------------------------------------
# WS-3 3-2: 既定レシピ (M7) の出力を 1 段ずつ固定する — **完全非回帰**
# ---------------------------------------------------------------------------
#
# 安定自動 Rietveld の作業では `build_serious_recipe` 側に凍結・元素展開・Uiso 緩和を足す。
# それらは opt-in であり、**既定レシピは 1 段も変えてはならない** — T1–T4 と CaTeO3 の
# gated ベンチマーク (9.83 / 4.33 / 6.66 / ~12.8 / 12.43%) はすべてこの段列の上で測った値で、
# 既定が動くと比較の土俵そのものが失われる。段の追加・並べ替えは新しいレシピ関数として足すこと。

_DEFAULT_XRAY_SINGLE = (
    ("S0 scale+background", {"scale": True, "background": {"coeffs": 6}}),
    ("S1 cell", {"cell": True}),
    ("S2 displacement", {"cell": False, "displacement": {0: ["Shift"]}}),
    ("S3 cell (repolish)", {"cell": True}),
    ("S4 profile+size_strain", {"profile": ["U", "V", "W"], "size_strain": True}),
    ("S5 coords", {"coords": True}),
    ("S6 uiso", {"uiso": True}),
    ("S7 profile_lorentzian", {"profile_lorentzian": True}),
    ("S8 profile_asymmetry", {"profile_asymmetry": True}),
)

_DEFAULT_XRAY_MULTIPHASE = (
    ("S0 scale+background", {"scale": True, "background": {"coeffs": 6}}),
    ("S1 phase_fractions", {"phase_fraction_sum": True}),
    ("S2 cell+profile", {"cell": True, "profile": ["U", "V", "W"]}),
    ("S3 displacement", {"cell": False, "displacement": {0: ["Shift"]}}),
    ("S4 cell (repolish)", {"cell": True}),
    ("S5 coords", {"coords": True}),
    ("S6 uiso", {"uiso": True}),
    ("S7 size_strain", {"size_strain": True}),
    ("S8 profile_lorentzian", {"profile_lorentzian": True}),
    ("S9 profile_asymmetry", {"profile_asymmetry": True}),
)

_DEFAULT_NEUTRON_MIXED_OCC = (
    ("S0 scale+background", {"scale": True, "background": {"coeffs": 6}}),
    ("S1 cell", {"cell": True}),
    ("S2 displacement", {"cell": False, "displacement": {0: ["DisplaceX", "DisplaceY"]}}),
    ("S3 cell (repolish)", {"cell": True}),
    ("S4 occupancy", {"occupancy": True}),
    ("S5 uiso", {"uiso": True}),
    ("S6 profile+size_strain", {"profile": ["U", "V", "W"], "size_strain": True}),
    ("S7 coords", {"coords": True}),
)

_MIXED_PHASE = (
    PhaseSpec(structure_path="g.cif", phase_name="g", mixed_occupancy_groups=(("Fe1", "Al1"),)),
)
_TWO_PHASES = (
    PhaseSpec(structure_path="p.cif", phase_name="a"),
    PhaseSpec(structure_path="q.cif", phase_name="b"),
)


@pytest.mark.parametrize(
    "histograms,phases,expected",
    [
        pytest.param([_XRAY_BB], _SINGLE_PHASE, _DEFAULT_XRAY_SINGLE, id="xray-single"),
        pytest.param([_XRAY_BB], _TWO_PHASES, _DEFAULT_XRAY_MULTIPHASE, id="xray-multiphase"),
        pytest.param([_NEUTRON_DS], _MIXED_PHASE, _DEFAULT_NEUTRON_MIXED_OCC, id="neutron-mixed"),
    ],
)
def test_default_recipe_is_pinned_stage_by_stage(histograms, phases, expected):
    """既定レシピのラベルとフラグを丸ごと固定する (段の追加/削除/並べ替えを検出)。"""
    stages = build_recipe(histograms, phases)
    assert [(s.label, dict(s.flags)) for s in stages] == [
        (label, flags) for label, flags in expected
    ]


def test_default_recipe_keeps_pure_cumulative_semantics():
    """既定レシピは ``freeze_others`` を使わない = 段のフラグは累積 (enable のみ)。

    凍結は engine で「既存の解放を落とす」破壊的操作なので、既定に紛れ込むと実測基準が
    静かに別物になる (本気フィット `build_serious_recipe` 側だけの機構に閉じる)。
    """
    for phases in (_SINGLE_PHASE, _TWO_PHASES, _MIXED_PHASE):
        for stage in build_recipe([_XRAY_BB, _NEUTRON_DS], phases):
            assert "freeze_others" not in stage.flags, stage.label


def _histograms(multiphase: bool):
    """X 線 Bragg-Brentano 1 本 (規定テスト用; 多相でも装置は共通)。"""
    return [_XRAY_BB]


def _phases(multiphase: bool, mixed_occ: bool):
    groups = (("Fe1", "Al1"),) if mixed_occ else ()
    out = [PhaseSpec(structure_path="p.cif", phase_name="a", mixed_occupancy_groups=groups)]
    if multiphase:
        out.append(PhaseSpec(structure_path="q.cif", phase_name="b"))
    return out
