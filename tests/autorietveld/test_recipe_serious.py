"""WS-3 3-2/3-3/3-5: `build_serious_recipe` の凍結セマンティクス・元素展開・Uiso 緩和。

本気フィット (順次解放/凍結 2 周 → 累積 → 全開放) の**段の並びとフラグ**を固定する。
新機能は opt-in 引数に閉じ、既定出力は 1 段も変わらないことをここで担保する
(T1–T4 の gated ベンチマークは既定レシピの上に載っているため、既定が動くと全部の基準が失われる)。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import _element_rank_labels
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

#: engine 側の展開が未実装の宣言値 (`recipe` の docstring / `mcp._recipe_spec` と同じ集合)。
_UNIMPLEMENTED = ("heavy_first", *UISO_TIERS)

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
    """★engine 未対応の間、note は**実際に起きること**を書くこと (note は ledger に出る = ③ が読む)。

    以前の note は「engine 未対応時は拘束なし = individual と同義」と書いており、
    engine が非 int 値を黙って全ラベル解放と読んでいた頃はそれで正しかった。その黙認を
    塞いだ (`_element_rank_labels` が ValueError) 時点で記述が嘘になり、``individual`` を
    別扱いする理由も消えた — **③ に「緩めたが効かなかっただけ」と読ませる** 誤った説明は
    実装バグと同等に有害なので、全 tier について revert することを明記する。
    """
    stages = build_serious_recipe([_XRAY_BB], _PLAIN, uiso_tiers=("shared", "individual"))
    for tier in ("shared", "individual"):
        note = _find(stages, f"uiso_{tier}")[0].note
        assert "engine 未対応" in note and "revert" in note, note
        assert "individual と同義" not in note, "engine が黙って個別解放へ落ちる経路はもう無い"


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

    ⚠ 見るのは**フラグ名**の到達可能性であって値ではない。engine が展開できない宣言値
    (``heavy_first`` / Uiso tier) は ② が意図的に拒否するので、名前の検査に通すときは
    実装済みの値へ正規化する。**その拒否が意図的であること自体**は下の
    `test_unimplemented_declaration_values_are_blocked_at_the_mcp_boundary` が固定する
    (ここで単に読み飛ばすと「値の検証が消えた」退行に気づけない)。
    """
    from tsumugin.mcp._recipe_spec import stage_from_dict, stage_to_dict

    stages = (
        build_serious_recipe([_XRAY_BB, _NEUTRON_DS], _TWO)
        + build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy_first",
                               uiso_tiers=("shared", "by_element", "individual"))
        + build_recipe([_XRAY_BB, _NEUTRON_DS], _TWO)
    )
    for stage in stages:
        d = stage_to_dict(stage)
        d["flags"] = {
            k: (True if isinstance(v, str) and v in _UNIMPLEMENTED else v)
            for k, v in d["flags"].items()
        }
        # 例外が漏れたらそのフラグ**名**は ③ から送れない (テストが理由付きで落ちる)
        stage_from_dict(d)


def test_unimplemented_declaration_values_are_blocked_at_the_mcp_boundary():
    """★engine が展開できない宣言値は ② が拒否する (上の正規化を無害化させない)。

    非トートロジー: `build_serious_recipe` の opt-in 出力から**実際に**宣言値を含む段を拾い、
    生のまま ② へ送ると `ValueError` になることを確かめる。値の検証を外すとここが落ちる。
    """
    from tsumugin.mcp._recipe_spec import stage_from_dict, stage_to_dict

    stages = build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy_first",
                                  uiso_tiers=list(UISO_TIERS))
    declared = [
        s for s in stages
        if any(isinstance(v, str) and v in _UNIMPLEMENTED for v in s.flags.values())
    ]
    assert declared, "宣言値を含む段が 1 つも無い = 検査が空回り"
    for stage in declared:
        with pytest.raises(ValueError):
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


# ---------------------------------------------------------------------------
# 宣言と engine の整合 — 未実装の宣言は「黙って別物」ではなく大声で落ちる
# ---------------------------------------------------------------------------


def test_engine_expands_bool_and_int_ranks():
    # 【目的】: 実装済みの語彙 (build_recipe の True / ranks 展開の int) は従来どおり動くこと。
    #   下の拒否テストが「全部拒否」へ縮んだらここで落ちる。
    info = {"coord_atoms": ["Ca", "P", "O"], "element_of": {"Ca": "Ca", "P": "P", "O": "O"}}
    assert _element_rank_labels(info, info["coord_atoms"], True) == ["Ca", "P", "O"]
    assert _element_rank_labels(info, info["coord_atoms"], 0) == ["Ca"]   # 最も重い元素
    assert _element_rank_labels(info, info["coord_atoms"], 9) == []       # 存在しない rank = no-op


@pytest.mark.parametrize(
    "declared",
    ["heavy_first", *UISO_TIERS],
)
def test_unexpanded_declarations_raise_instead_of_releasing_everything(declared):
    """★engine が展開できない宣言値は `ValueError` (旧: catch-all で全ラベル解放)。

    非トートロジー: ここに渡す値は `build_serious_recipe(element_expansion=...)` /
    ``uiso_tiers=`` が**実際に段のフラグへ書き込む**文字列そのもの。旧実装は
    ``isinstance(rank, int)`` でない値をすべて「全ラベル」と読んでいたため、
    「重原子から順に 1 元素ずつ」「等値拘束を段階的に緩める」と宣言した手順が
    **1 段で全原子解放**という別物になり、Rwp にも ledger にも痕跡が出なかった。
    WS-3 3-3 で実展開が入ったらこのテストは「展開結果の固定」へ置き換わる。
    """
    info = {"coord_atoms": ["Ca", "O"], "element_of": {"Ca": "Ca", "O": "O"}}
    with pytest.raises(ValueError):
        _element_rank_labels(info, info["coord_atoms"], declared)


def test_every_declaration_the_serious_recipe_emits_is_either_honored_or_rejected():
    """★レシピが書ける値と engine が読める値の drift を検出する (逆方向カバレッジ)。

    非トートロジー: `build_serious_recipe` の全 opt-in 組合せを実際に構築し、座標/占有率/Uiso
    段のフラグ値を engine の展開器へ通す。**黙って通る値が 1 つでもあれば落ちる** —
    「engine が読めないのに例外にもならない」= 宣言と手順が食い違ったまま完走する状態が
    この PR で塞いだ病理そのものなので、新しい宣言語彙を足したときに気づけるようにする。
    """
    info = {"coord_atoms": ["Ca", "O"], "element_of": {"Ca": "Ca", "O": "O"}}
    variants = (
        build_serious_recipe([_XRAY_BB], _PLAIN),
        build_serious_recipe([_XRAY_BB], _PLAIN, element_expansion="heavy_first"),
        build_serious_recipe([_XRAY_BB], _PLAIN, uiso_tiers=list(UISO_TIERS)),
    )
    seen = set()
    for stages in variants:
        for stage in stages:
            for key in ("coords", "occupancy", "uiso"):
                if key not in stage.flags:
                    continue
                value = stage.flags[key]
                seen.add(value if isinstance(value, (bool, int, str)) else type(value))
                if isinstance(value, (bool, int)):
                    _element_rank_labels(info, info["coord_atoms"], value)  # 展開できる
                else:
                    with pytest.raises(ValueError):
                        _element_rank_labels(info, info["coord_atoms"], value)
    assert {"heavy_first", *UISO_TIERS} <= seen, "宣言値が 1 つも現れていない = 検査が空回り"
