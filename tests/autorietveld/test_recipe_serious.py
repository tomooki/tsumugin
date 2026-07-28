"""WS-3 3-2/3-3/3-5: `build_serious_recipe` の凍結セマンティクス・元素展開・Uiso 緩和。

本気フィット (順次解放/凍結 2 周 → 累積 → 全開放) の**段の並びとフラグ**を固定する。
新機能は opt-in 引数に閉じ、既定出力は 1 段も変わらないことをここで担保する
(T1–T4 の gated ベンチマークは既定レシピの上に載っているため、既定が動くと全部の基準が失われる)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.recipe import (
    UISO_TIERS,
    build_recipe,
    build_serious_recipe,
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
_PLAIN = (PhaseSpec(structure_path="p.cif", phase_name="a"),)
_TWO = _PLAIN + (PhaseSpec(structure_path="q.cif", phase_name="b"),)

#: 既定 (X 線単相) の段列 — S 番号を除いたラベル。**この並びが本気フィットの正**。
_SERIOUS_XRAY_LABELS = (
    "bkg+scale",
    # --- 1 周目 (順次解放 → 凍結) ---
    "cell", "displacement",
    "profile_W", "profile_WU", "profile_WUV",   # Caglioti は累積 (F2)
    "cell+displacement", "size_strain",
    "coords_z0", "coords_z1", "coords_z2", "coords_z3", "coords_z4", "coords_z5",
    "occupancy_z0", "occupancy_z1", "occupancy_z2", "occupancy_z3", "occupancy_z4",
    "occupancy_z5",
    "profile_lorentzian", "profile_asymmetry", "aniso_strain", "uiso",
    # --- 2 周目 (格子は常時解放のまま入る) ---
    "cell", "displacement",
    "profile_W", "profile_WU", "profile_WUV",
    "cell+displacement", "size_strain",
    "coords_z0", "coords_z1", "coords_z2", "coords_z3", "coords_z4", "coords_z5",
    "occupancy_z0", "occupancy_z1", "occupancy_z2", "occupancy_z3", "occupancy_z4",
    "occupancy_z5",
    "profile_lorentzian", "profile_asymmetry", "aniso_strain", "uiso",
    # --- 全開放 → 累積解放 → 全開放 ---
    "all_open",
    "cum_cell", "cum_displacement", "cum_profile", "cum_size_strain", "cum_coords",
    "cum_occupancy", "cum_profile_lorentzian", "cum_profile_asymmetry", "cum_aniso_strain",
    "cum_uiso",
    "all_open_final",
)


def _bare(stages) -> tuple[str, ...]:
    """S 番号を落としたラベル列。"""
    return tuple(s.label.split(" ", 1)[1] for s in stages)


def _find(stages, fragment: str):
    return [s for s in stages if fragment in s.label]


# ---------------------------------------------------------------------------
# 3-2: 凍結 (freeze_others) セマンティクスの固定
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "histograms,phases",
    [
        pytest.param([_XRAY_BB], _PLAIN, id="xray-single"),
        pytest.param([_NEUTRON_DS], _PLAIN, id="neutron-single"),
        pytest.param([_XRAY_BB], _TWO, id="xray-multiphase"),
        pytest.param([_XRAY_BB, _NEUTRON_DS], _TWO, id="joint-multiphase"),
    ],
)
def test_default_recipe_never_uses_freeze_others(histograms, phases):
    """**非回帰の核**: 既定レシピ (`build_recipe`) は凍結を一切使わない = 純粋な累積。

    `freeze_others` は engine で「段の適用前に既存の解放を落とす」破壊的な操作なので、
    ここに紛れ込むと T1–T4 の実測基準が静かに別物になる。
    """
    for stage in build_recipe(histograms, phases):
        assert "freeze_others" not in stage.flags, stage.label


def test_serious_sequential_stages_all_freeze_but_cumulative_stages_do_not():
    """本気フィットの 1-12 は**凍結あり**、14 の ``cum_*`` と全開放は**累積のまま**。

    手順 14 は「従来の累積セマンティクスで積み上げ直す」段なので、ここに凍結が付くと
    手順 13 までの成果を落としてしまう。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    for stage in stages:
        bare = stage.label.split(" ", 1)[1]
        if bare in ("bkg+scale", "phase_fractions") or bare.startswith(("cum_", "all_open")):
            assert "freeze_others" not in stage.flags, stage.label
        else:
            assert "freeze_others" in stage.flags, stage.label


def test_cell_becomes_permanently_free_after_the_convergence_check():
    """``cell+displacement`` (手順 5) 以降、格子は凍結対象から外れる (常時解放)。

    格子は他のほぼ全パラメータと相関するため、凍結したまま構造段に入ると
    構造側が格子のずれを吸収してしまう。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    labels = _bare(stages)
    pivot = labels.index("cell+displacement")
    # 手順 5 まで: keep なし (True = 全部凍結)
    assert stages[labels.index("cell")].flags["freeze_others"] is True
    assert stages[pivot].flags["freeze_others"] is True
    # 手順 6 以降: cell は keep される
    after = [s for s in stages[pivot + 1:] if "freeze_others" in s.flags]
    assert after, "手順 6 以降に凍結段が無い"
    for stage in after:
        keep = stage.flags["freeze_others"]
        assert keep is not True and "cell" in keep, stage.label


def test_second_round_enters_with_the_cell_kept_free():
    """2 周目の入口 (2 つ目の ``cell`` 段) は ``keep=["cell"]`` で入る。"""
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    cells = _find(stages, " cell")
    entries = [s for s in cells if s.label.endswith(" cell")]
    assert len(entries) == 2, [s.label for s in entries]
    assert entries[0].flags["freeze_others"] is True          # 1 周目は全凍結から
    assert entries[1].flags["freeze_others"] == ["cell"]      # 2 周目は格子を保持したまま


def test_lorentzian_stage_keeps_the_gaussian_coefficients():
    """Lorentzian 段は U,V,W を凍結しない (同じ FWHM の別成分 — 片方だけにすると割れる)。"""
    stage = _find(build_serious_recipe([_XRAY_BB], _PLAIN), "profile_lorentzian")[0]
    assert "profile" in stage.flags["freeze_others"]
    assert stage.flags["profile"] == ["U", "V", "W"]


def test_rounds_argument_controls_the_number_of_sweeps():
    one = build_serious_recipe([_XRAY_BB], _PLAIN, rounds=1)
    two = build_serious_recipe([_XRAY_BB], _PLAIN, rounds=2)
    assert _bare(one).count("cell+displacement") == 1
    assert _bare(two).count("cell+displacement") == 2
    assert len(two) > len(one)


# ---------------------------------------------------------------------------
# 既定出力の固定 (opt-in を足しても 1 段も動かないこと)
# ---------------------------------------------------------------------------


def test_serious_default_stage_sequence_is_pinned():
    """既定の 59 段が固定であること (新機能は opt-in に閉じる)。"""
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    assert _bare(stages) == _SERIOUS_XRAY_LABELS
    assert len(stages) == 59
    assert [s.label for s in stages] == [
        f"S{i} {name}" for i, name in enumerate(_SERIOUS_XRAY_LABELS)
    ]


@pytest.mark.parametrize(
    "kwargs",
    [
        pytest.param({}, id="bare"),
        pytest.param({"element_expansion": "ranks"}, id="explicit-ranks"),
        pytest.param({"uiso_tiers": None}, id="explicit-no-tiers"),
    ],
)
def test_optional_arguments_default_to_the_existing_behaviour(kwargs):
    """既定値を明示的に渡しても出力は既定と同一 (opt-in が既定を汚していない)。"""
    expected = build_serious_recipe([_XRAY_BB], _PLAIN)
    actual = build_serious_recipe([_XRAY_BB], _PLAIN, **kwargs)
    assert [(s.label, s.flags, s.note) for s in actual] == [
        (s.label, s.flags, s.note) for s in expected
    ]


# ---------------------------------------------------------------------------
# 3-3: 元素ランク展開 (REQ-SAR-303)
# ---------------------------------------------------------------------------


def test_default_expansion_keeps_the_fixed_integer_ranks():
    """既定は従来どおり int ランクの決め打ち (engine の後方互換経路)。"""
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    coords = _find(stages, "coords_z")
    assert [s.flags["coords"] for s in coords[:6]] == [0, 1, 2, 3, 4, 5]
    assert all(isinstance(s.flags["coords"], int) for s in coords)


def test_heavy_first_declares_one_stage_per_flag_instead_of_six():
    """``heavy_first`` はレシピ側で 1 段に畳み、展開を engine へ委ねる宣言になる。

    実元素数を知らないレシピが 6 段を決め打ちすると、元素数を超えた段が no-op として
    残る (T1 は 4 元素なので座標/占有率あわせて 4 段が空回りしていた)。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy_first")
    labels = _bare(stages)
    assert not _find(stages, "coords_z") and not _find(stages, "occupancy_z")
    assert labels.count("coords_heavy_first") == 2      # 2 周ぶん
    assert labels.count("occupancy_heavy_first") == 2
    for stage in _find(stages, "heavy_first"):
        key = "coords" if "coords" in stage.label else "occupancy"
        assert stage.flags[key] == "heavy_first"
        assert "cell" in stage.flags["freeze_others"]   # 凍結の keep は従来どおり
    # 段数は 1 周あたり 10 段 (= (6-1) × 2) 減る
    assert len(stages) == len(build_serious_recipe([_XRAY_BB], _PLAIN)) - 20


def test_heavy_first_keeps_the_rest_of_the_recipe_untouched():
    """宣言化は座標/占有率の段だけを差し替える (他の段は既定と同一)。"""
    default = build_serious_recipe([_XRAY_BB], _PLAIN)
    declared = build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy_first")

    def _others(stages):
        return [
            (s.label.split(" ", 1)[1], s.flags)
            for s in stages
            if "coords" not in s.label and "occupancy" not in s.label
        ]

    assert _others(declared) == _others(default)


def test_unknown_element_expansion_is_rejected_loudly():
    """未知の展開方式は黙って既定に落とさず ValueError (静かな誤りを作らない)。"""
    with pytest.raises(ValueError, match="element_expansion"):
        build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy-first")


# ---------------------------------------------------------------------------
# 3-5: Uiso 等値拘束の段階的緩和 (REQ-SAR-305)
# ---------------------------------------------------------------------------


def test_default_uiso_stage_is_a_single_unconstrained_release():
    stages = build_serious_recipe([_XRAY_BB], _PLAIN)
    uiso = [s for s in stages if s.label.endswith(" uiso")]
    assert len(uiso) == 2  # 2 周ぶん
    assert all(s.flags["uiso"] is True for s in uiso)


def test_uiso_tiers_expand_into_a_staged_relaxation():
    """全原子 1 変数 → 元素ごと → 個別 の順に緩む段列になる。"""
    tiers = ("shared", "by_element", "individual")
    stages = build_serious_recipe([_XRAY_BB], _PLAIN, uiso_tiers=tiers)
    labels = _bare(stages)
    for tier in tiers:
        assert labels.count(f"uiso_{tier}") == 2, tier
    # 1 周目の並びが shared → by_element → individual であること (緩める向きが逆だと母数が減らない)
    order = [name for name in labels if name.startswith("uiso_")][:3]
    assert order == [f"uiso_{t}" for t in tiers]
    values = [s.flags["uiso"] for s in stages if s.label.split(" ", 1)[1].startswith("uiso_")][:3]
    assert values == list(tiers), "tier 名がそのまま uiso フラグ値になること"
    assert tuple(UISO_TIERS) == tiers, "UISO_TIERS は拘束の強い順に並んでいること"


def test_uiso_tier_notes_warn_that_the_engine_binding_is_pending():
    """engine 未対応の間は「拘束なし = individual と同義」であることを note に残す。

    黙って個別解放になると「緩和したのに効かない」を silent failure として学習させる
    (P-SAR-2: 検出できない失敗を作らない)。note は ledger に出る。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN, uiso_tiers=("shared", "individual"))
    shared = _find(stages, "uiso_shared")[0]
    assert "engine 未対応" in shared.note
    assert "engine 未対応" not in _find(stages, "uiso_individual")[0].note


def test_uiso_tiers_do_not_use_restraints():
    """⚠ 等値拘束 (constraint) であって restraint ではないこと。

    GSAS-II の headless 経路では restraint の penalty が χ² から外れる一方で勾配/Hessian
    だけが引っ張られる (requirements.md F5 / Issue #112) ため、ソフト拘束は使えない。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN, uiso_tiers=("shared",))
    for stage in stages:
        assert not any("restraint" in str(key) for key in stage.flags)


def test_every_recipe_flag_is_reachable_from_the_mcp_layer():
    """レシピが使うフラグはすべて ② の語彙にあること (CLAUDE.md ②到達可能性)。

    ② は未知フラグ名を拒否する。① のレシピが使うフラグが語彙から漏れていると、③ は
    同じ手順を JSON で再現できない (= その機能は ③ から存在しない)。
    ``freeze_others`` の取りこぼしはこの検査で見つかった。
    """
    from tsumugin.mcp._recipe_spec import stage_from_dict, stage_to_dict

    stages = (
        build_serious_recipe([_XRAY_BB, _NEUTRON_DS], _TWO)
        + build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy_first",
                               uiso_tiers=("shared", "by_element", "individual"))
        + build_recipe([_XRAY_BB, _NEUTRON_DS], _TWO)
    )
    for stage in stages:
        # 例外が漏れたらそのフラグは ③ から送れない (テストが理由付きで落ちる)
        stage_from_dict(stage_to_dict(stage))


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param(("elementwise",), id="unknown-tier"),
        pytest.param((), id="empty"),
        # 緩い方から始めると母数が減らず等値拘束の意味が無い (順序が本質)
        pytest.param(("individual", "shared"), id="wrong-order"),
    ],
)
def test_invalid_uiso_tiers_are_rejected(bad):
    with pytest.raises(ValueError, match="uiso_tiers"):
        build_serious_recipe([_XRAY_BB], _PLAIN, uiso_tiers=bad)
