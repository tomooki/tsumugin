"""WS-3 3-1: 相関群の分割禁止 (REQ-SAR-301) — 不変条件 + 変異テスト。

**なぜ守るのか**: {U,V,W} のような群は「独立に回せる knob が 3 つ」ではなく
**1 つの物理量 (FWHM² = U·tan²θ + V·tanθ + W) の係数**である。1 つだけ解放して残りを凍結すると
担当できない角度依存まで背負わされて解が壊れる — 実測 (CaTeO3) では W 単独のあと U 単独/V 単独が
**両方 revert** し 18.07% で頭打ち、W から足していく累積なら 12.19% (requirements.md F2)。

**ここでのガードは変異させて fail することを実証している** (落ちないガードは無いより悪い):
実レシピの 1 段だけを「群を割る形」に書き換え、その差分だけで検証が落ちることを確かめる。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation, RefinementStage
from tsumugin.autorietveld import recipe as recipe_mod
from tsumugin.autorietveld.recipe import (
    CORRELATION_GROUPS,
    CorrelationGroupViolation,
    build_recipe,
    build_serious_recipe,
    released_group_members,
    validate_correlation_groups,
)

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
_TOF_DS = HistogramSpec(
    data_path="p.gsa",
    instrument_path="i.instprm",
    radiation=Radiation.NEUTRON_TOF,
    geometry=Geometry.DEBYE_SCHERRER,
)
_PLAIN = (PhaseSpec(structure_path="p.cif", phase_name="a"),)
_MIXED = (
    PhaseSpec(structure_path="g.cif", phase_name="g", mixed_occupancy_groups=(("Fe1", "Al1"),)),
)
_TWO = _PLAIN + (PhaseSpec(structure_path="q.cif", phase_name="b"),)

#: 実データ相当の全組み合わせ (X 線/中性子/TOF × 単相/多相/混合占有)。
_CONFIGS = [
    pytest.param([_XRAY_BB], _PLAIN, id="xray-single"),
    pytest.param([_NEUTRON_DS], _MIXED, id="neutron-mixedocc"),
    pytest.param([_TOF_DS], _PLAIN, id="tof-single"),
    pytest.param([_XRAY_BB], _TWO, id="xray-multiphase"),
    pytest.param([_XRAY_BB, _NEUTRON_DS], _PLAIN, id="joint"),
]


# ---------------------------------------------------------------------------
# 群の定義そのもの
# ---------------------------------------------------------------------------


def test_correlation_groups_cover_the_required_sets():
    """REQ-SAR-301 が名指しする群がすべて表にあること。"""
    assert set(CORRELATION_GROUPS["gaussian_profile"]) == {"U", "V", "W"}
    assert set(CORRELATION_GROUPS["lorentzian_profile"]) == {"X", "Y"}
    assert set(CORRELATION_GROUPS["size_strain"]) == {"Size", "Mustrain"}
    assert set(CORRELATION_GROUPS["displacement:bragg_brentano"]) == {"Shift"}
    assert set(CORRELATION_GROUPS["displacement:debye_scherrer"]) == {"DisplaceX", "DisplaceY"}
    assert CORRELATION_GROUPS["cell"] == ("cell",)


def test_geometry_displacement_map_is_derived_from_the_group_table():
    """変位キーの出所は群表 1 箇所であること (二重管理だと片方だけ増えて網から漏れる)。"""
    assert recipe_mod._GEOMETRY_DISPLACEMENT[Geometry.BRAGG_BRENTANO] == list(
        CORRELATION_GROUPS["displacement:bragg_brentano"]
    )
    assert recipe_mod._GEOMETRY_DISPLACEMENT[Geometry.DEBYE_SCHERRER] == list(
        CORRELATION_GROUPS["displacement:debye_scherrer"]
    )


@pytest.mark.parametrize(
    "flags,group,expected",
    [
        ({"profile": ["U", "V", "W"]}, "gaussian_profile", {"U", "V", "W"}),
        ({"profile": ["W"]}, "gaussian_profile", {"W"}),
        ({"profile": True}, "gaussian_profile", {"U", "V", "W"}),  # engine 既定キー
        ({"cell": True}, "gaussian_profile", set()),
        # X,Y は profile のキー列でも profile_lorentzian 段でも解放されうる (両方見る)
        ({"profile": ["U", "V", "W", "X", "Y", "Zero"]}, "lorentzian_profile", {"X", "Y"}),
        ({"profile_lorentzian": True}, "lorentzian_profile", {"X", "Y"}),
        ({"profile": ["U", "V", "W"]}, "lorentzian_profile", set()),
        ({"size_strain": True}, "size_strain", {"Size", "Mustrain"}),
        ({"size_strain": "generalized"}, "size_strain", {"Size", "Mustrain"}),
        ({"cell": True}, "cell", {"cell"}),
        ({"cell": False}, "cell", set()),  # 凍結は「解放」ではない
        ({"displacement": {0: ["Shift"]}}, "displacement:bragg_brentano", {"Shift"}),
        ({"displacement": {0: ["Shift"]}}, "displacement:debye_scherrer", set()),
    ],
)
def test_released_group_members_mirrors_engine_interpretation(flags, group, expected):
    """`released_group_members` は engine `_apply_stage` の解釈を写すこと。"""
    assert released_group_members(flags, group) == frozenset(expected)


# ---------------------------------------------------------------------------
# 実レシピは規則を満たす (基準)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("histograms,phases", _CONFIGS)
def test_build_recipe_satisfies_the_invariant(histograms, phases):
    validate_correlation_groups(build_recipe(histograms, phases), histograms=histograms)


@pytest.mark.parametrize("histograms,phases", _CONFIGS)
def test_build_serious_recipe_satisfies_the_invariant(histograms, phases):
    validate_correlation_groups(build_serious_recipe(histograms, phases), histograms=histograms)


def test_cumulative_profile_release_is_allowed():
    """W → W,U → W,U,V の**累積**は合法 (これが実測で効いた手順そのもの)。"""
    validate_correlation_groups(
        [
            RefinementStage(label="S0 W", flags={"profile": ["W"]}),
            RefinementStage(label="S1 WU", flags={"profile": ["W", "U"]}),
            RefinementStage(label="S2 WUV", flags={"profile": ["W", "U", "V"]}),
        ]
    )


def test_group_may_restart_from_scratch_after_completion():
    """一度丸ごと解放した群は、次の周で W から積み直してよい (本気フィットの 2 周目)。"""
    validate_correlation_groups(
        [
            RefinementStage(label="S0 WUV", flags={"profile": ["W", "U", "V"]}),
            RefinementStage(label="S1 W", flags={"freeze_others": True, "profile": ["W"]}),
            RefinementStage(label="S2 WUV", flags={"freeze_others": True,
                                                   "profile": ["W", "U", "V"]}),
        ]
    )


# ---------------------------------------------------------------------------
# 変異テスト — 群を割る段を書いたら必ず落ちる
# ---------------------------------------------------------------------------


def _mutate(stages, label_fragment: str, new_flags: dict) -> list[RefinementStage]:
    """``label_fragment`` を含む最初の段の flags だけを差し替える (他は実レシピのまま)。"""
    out = list(stages)
    for i, s in enumerate(out):
        if label_fragment in s.label:
            out[i] = RefinementStage(label=s.label, flags=new_flags, note=s.note)
            return out
    raise AssertionError(f"{label_fragment!r} を含む段が無い: {[s.label for s in stages]}")


def test_mutation_splitting_uvw_into_single_coefficients_is_rejected():
    """**変異**: 実レシピの ``profile_WU`` 段を「U 単独」に書き換えると検証が落ちる。

    これは F2 で実測した壊れ方 (W 単独 → 凍結 → U 単独) そのもの。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    validate_correlation_groups(stages)  # 変異前は通る (テストが空回りしていない証拠)
    mutated = _mutate(stages, "profile_WU", {"freeze_others": True, "profile": ["U"]})
    with pytest.raises(CorrelationGroupViolation, match="gaussian_profile"):
        validate_correlation_groups(mutated)


def test_mutation_stopping_the_accumulation_halfway_is_rejected():
    """**変異**: 実レシピを ``profile_WU`` の直後で打ち切ると、V が未解放のまま終わり落ちる。

    「累積の途中で他の段に移り、二度と戻らない」= 群を割ったのと同じ結果になる。
    """
    stages = list(build_serious_recipe([_XRAY_BB], _PLAIN))
    cut = next(i for i, s in enumerate(stages) if "profile_WU" in s.label and "WUV" not in s.label)
    with pytest.raises(CorrelationGroupViolation, match="部分解放のまま"):
        validate_correlation_groups(stages[: cut + 1])
    # 1 段伸ばして W,U,V まで含めれば通る (打ち切り位置だけが原因であることの確認)
    validate_correlation_groups(stages[: cut + 2])


def test_mutation_splitting_debye_scherrer_displacement_is_rejected():
    """**変異**: Debye-Scherrer の変位から DisplaceY を落とすと落ちる。

    DisplaceX/Y はどちらも同じ試料位置ずれの成分で、片方だけ解放すると残りを他の
    パラメータ (格子/Zero) が肩代わりする。
    """
    stages = build_recipe([_NEUTRON_DS], _PLAIN)
    validate_correlation_groups(stages, histograms=[_NEUTRON_DS])
    mutated = _mutate(stages, "displacement", {"cell": False, "displacement": {0: ["DisplaceX"]}})
    with pytest.raises(CorrelationGroupViolation, match="試料変位の群"):
        validate_correlation_groups(mutated, histograms=[_NEUTRON_DS])


def test_mutation_using_the_wrong_geometry_displacement_is_rejected():
    """**変異**: Bragg-Brentano のヒストグラムに Debye-Scherrer のキーを与えると落ちる。

    群としては完全なので構造検査だけでは通ってしまう — 幾何との突き合わせが要る。
    """
    stages = build_recipe([_XRAY_BB], _PLAIN)
    mutated = _mutate(
        stages, "displacement", {"cell": False, "displacement": {0: ["DisplaceX", "DisplaceY"]}}
    )
    with pytest.raises(CorrelationGroupViolation, match="一致しません"):
        validate_correlation_groups(mutated, histograms=[_XRAY_BB])
    # 幾何を渡さなければ群としては完全なので通る (検査の守備範囲を明示)
    validate_correlation_groups(mutated)


def test_partially_released_group_at_the_end_is_rejected():
    """W だけ解放して終わる段列は不可 (U,V が永久に凍結された誤ったフィット)。"""
    with pytest.raises(CorrelationGroupViolation, match="部分解放のまま"):
        validate_correlation_groups([RefinementStage(label="S0 W", flags={"profile": ["W"]})])


def test_freezing_does_not_reset_the_accumulation():
    """凍結を挟んで別メンバへ乗り換える手順は不可 (これが F2 の壊れ方そのもの)。"""
    with pytest.raises(CorrelationGroupViolation, match="累積して足す"):
        validate_correlation_groups(
            [
                RefinementStage(label="S0 W", flags={"profile": ["W"]}),
                RefinementStage(label="S1 U", flags={"freeze_others": True, "profile": ["U"]}),
                RefinementStage(label="S2 V", flags={"freeze_others": True,
                                                     "profile": ["U", "V", "W"]}),
            ]
        )


def test_size_and_mustrain_cannot_be_separated_by_construction():
    """Size/Mustrain は engine が常に同時解放するため、レシピ側で割る表現が存在しない。

    (割れないことを構造で示す — フラグ 1 つで両方が立つ。)
    """
    assert released_group_members({"size_strain": True}, "size_strain") == frozenset(
        {"Size", "Mustrain"}
    )


# ---------------------------------------------------------------------------
# 生成側に検証が**組み込まれている**こと (呼び出しを消したら落ちる)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("builder", [build_recipe, build_serious_recipe])
def test_builders_run_the_validator(monkeypatch, builder):
    """レシピ生成は必ず検証を通ること — 「群を割る段を作れない」の実体はここ。

    検証呼び出しを削ると本テストが落ちる (ガードが実装から外れたことを検出する)。
    """
    seen: list[tuple] = []

    def spy(stages, *, histograms=None):
        seen.append((tuple(s.label for s in stages), histograms))

    monkeypatch.setattr(recipe_mod, "validate_correlation_groups", spy)
    stages = builder([_XRAY_BB], _PLAIN)
    assert seen, "レシピ生成が validate_correlation_groups を呼んでいない"
    assert seen[-1][0] == tuple(s.label for s in stages), "検証対象が返り値と同じ段列でない"
    assert seen[-1][1] is not None, "幾何との突き合わせのため histograms を渡すこと"


def test_builder_rejects_a_split_stage_at_generation_time(monkeypatch):
    """**変異**: レシピ生成の中身が群を割る形に変わったら、生成そのものが失敗する。

    `_displacement_map` を「DisplaceX だけ返す」実装に差し替えて、レシピを組んだ瞬間に
    `CorrelationGroupViolation` になることを確かめる (engine まで届かせない)。
    """
    monkeypatch.setattr(recipe_mod, "_displacement_map", lambda hists: {0: ["DisplaceX"]})
    with pytest.raises(CorrelationGroupViolation):
        build_recipe([_NEUTRON_DS], _PLAIN)
    with pytest.raises(CorrelationGroupViolation):
        build_serious_recipe([_NEUTRON_DS], _PLAIN)
