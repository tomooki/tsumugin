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
# 【削除済み】規定「cell 単独 → 試料変位は後段」(2026-07-27 追加 → 2026-07-28 実測で棄却)
#
# 格子と試料変位が強相関なのは事実だが (実測: Kα1 単色 CaTeO3 で Shift −274 µm 相当 =
# 2θ −0.15° を格子が肩代わりしていた)、**段を分ける配置は 3 通り試して全て別のデータを壊した**:
#   - 末尾配置 / 交互 (cell→変位→cell) : T3 PbSO4 joint 6.66% → 14.38% (格子発散)
#   - cell 直後                        : T4 NAC+CaF2 ~12.8% → 17.53%
# 「単一の段順序で全データを満たすことはできない」というのが実測の結論であり (requirements.md
# F1)、この規定をテストで固定すると**正しくない前提を将来にわたって強制する**ため削除した。
# 順序の選択は Phase 2 のレシピ探索 (REQ-SAR-500) が担う。
# ---------------------------------------------------------------------------


def _histograms(multiphase: bool):
    """X 線 Bragg-Brentano 1 本 (規定テスト用; 多相でも装置は共通)。"""
    return [_XRAY_BB]


def _phases(multiphase: bool, mixed_occ: bool):
    groups = (("Fe1", "Al1"),) if mixed_occ else ()
    out = [PhaseSpec(structure_path="p.cif", phase_name="a", mixed_occupancy_groups=groups)]
    if multiphase:
        out.append(PhaseSpec(structure_path="q.cif", phase_name="b"))
    return out


# ---------------------------------------------------------------------------
# 既定段列のピン留め (比較の基準を固定する)
# ---------------------------------------------------------------------------
#
# 上の【削除済み】が消したのは「cell 単独 → 変位は後段」という**棄却された規定**であって、
# 「既定段列を固定すること」自体ではない。ところが削除の際にピン留めごと失われ、既定レシピの
# 段列は**どのテストでも固定されていない**状態になっていた。10 案を既定と比較して選ぶには
# 基準が動かないことが前提なので、現行の実測ベースライン
# (T1 9.80617 / T2 4.3331 / T3 6.6602 / CaTeO3 12.1975) が載っている段列をここで固定する。
# ⚠ ここを変える差分は T1-T4/CaTeO3 の基準値すべてを無効化する — 意図的な変更なら
#    ベンチマークの再測定とセットで行うこと。

_XRAY_SINGLE = (
    "S0 scale+background",
    "S1 cell+displacement",
    "S2 profile+size_strain",
    "S3 coords",
    "S4 uiso",
    "S5 profile_lorentzian",
    "S6 profile_asymmetry",
)
_NEUTRON_MIXED_OCC = (
    "S0 scale+background",
    "S1 cell+displacement",
    "S2 occupancy",
    "S3 uiso",
    "S4 profile+size_strain",
    "S5 coords",
)
_XRAY_MULTIPHASE = (
    "S0 scale+background",
    "S1 phase_fractions",
    "S2 cell+displacement+profile",
    "S3 coords",
    "S4 uiso",
    "S5 size_strain",
    "S6 profile_lorentzian",
    "S7 profile_asymmetry",
)


def test_default_xray_single_phase_sequence_is_pinned():
    labels = tuple(s.label for s in build_recipe([_XRAY_BB], _SINGLE_PHASE))
    assert labels == _XRAY_SINGLE


def test_default_neutron_mixed_occupancy_sequence_is_pinned():
    phases = (PhaseSpec(structure_path="p.cif", phase_name="g",
                        mixed_occupancy_groups=(("Fe1", "Al1"),)),)
    labels = tuple(s.label for s in build_recipe([_NEUTRON_DS], phases))
    assert labels == _NEUTRON_MIXED_OCC


def test_default_xray_multiphase_sequence_is_pinned():
    phases = (
        PhaseSpec(structure_path="a.cif", phase_name="a"),
        PhaseSpec(structure_path="b.cif", phase_name="b"),
    )
    labels = tuple(s.label for s in build_recipe([_XRAY_BB], phases))
    assert labels == _XRAY_MULTIPHASE


def test_multiphase_with_mixed_occupancy_still_releases_phase_fractions():
    """★多相 + 混合占有が**相分率段を失っていた** (`multiphase and not mixed_occ` の穴)。

    非トートロジー: 混合占有の有無は「占有率をいつ解放するか」の話であって相分率の要否とは
    無関係なのに、条件が AND で結ばれていたため、この組合せだけ `phase_fraction_sum` が
    一度も出ず**各相の量が初期値のまま完走**していた。Rwp には「多相なのに量が動かない」
    としてしか現れず、段列を見ないと気づけない。ベンチマークにこの組合せが無いため
    (T4 は多相だが混合占有なし・T2 は混合占有だが単相) 実測でも露出していなかった。
    """
    phases = (
        PhaseSpec(structure_path="a.cif", phase_name="a",
                  mixed_occupancy_groups=(("Fe1", "Al1"),)),
        PhaseSpec(structure_path="b.cif", phase_name="b"),
    )
    stages = build_recipe([_NEUTRON_DS], phases)
    labels = [s.label for s in stages]

    assert any("phase_fractions" in lab for lab in labels), labels
    # 混合占有の解放順序 (占有率 → Uiso; 中性子コントラスト) は保たれること。
    occ_i = next(i for i, lab in enumerate(labels) if "occupancy" in lab)
    uiso_i = next(i for i, lab in enumerate(labels) if lab.endswith("uiso"))
    frac_i = next(i for i, lab in enumerate(labels) if "phase_fractions" in lab)
    assert frac_i < occ_i < uiso_i
