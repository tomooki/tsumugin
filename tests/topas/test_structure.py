"""M12 T3: CIF → TOPAS `str` ブロック (純関数)。

`autorietveld.cif_normalize.read_structure_cif` を再利用して構造を読み、`topas.inp` の
`TopasPhase` へ写像する。**TOPAS は空間群から格子を自動拘束しない** (実測: topas.inc の
`Cubic(cv)` は `a cv b = Get(a); c = Get(a);` と明示展開する) ため、結晶系ごとの拘束を
こちら側で張らないと立方晶の a/b/c が独立に精密化されて対称性が壊れる。
"""

from __future__ import annotations

import math
import re

import pytest

from .conftest import requires_real_data

from tsumugin.autorietveld.cif_normalize import Atom, Structure
from tsumugin.topas.structure import (
    BEQ_PER_UISO,
    crystal_system,
    structure_to_topas_phase,
    to_topas_element,
    to_topas_spacegroup,
)

# ---------------- 空間群表記 ----------------


@pytest.mark.parametrize(
    ("hm", "expected"),
    [
        ("P n m a", "Pnma"),
        ("F m -3 m", "Fm-3m"),
        ("I a -3 d", "Ia-3d"),
        ("P 63/m", "P63/m"),
        ("P 21/n", "P21/n"),
        ("P -1", "P-1"),
    ],
)
def test_hm_symbol_becomes_topas_spacegroup(hm, expected):
    """TOPAS は空白を除いた H-M 記号を受け付ける (Sg/ の生成ファイル名がその小文字形)。"""
    assert to_topas_spacegroup(hm, None) == expected


def test_falls_back_to_it_number_when_symbol_is_missing():
    """記号が無ければ IT 番号。TOPAS は `space_group 62` を受け付ける (Tutorial 実例あり)。"""
    assert to_topas_spacegroup("", 62) == "62"
    assert to_topas_spacegroup(None, 62) == "62"


def test_raises_when_neither_symbol_nor_number_is_available():
    """黙って P1 に落とさない — 対称性の取り違えは Rwp に現れないまま構造を壊す。"""
    with pytest.raises(ValueError):
        to_topas_spacegroup("", None)


def test_nonstandard_setting_is_preserved():
    """P21/n を標準セッティング P21/c へ勝手に正準化しない (M9 Jana 教訓と同型)。"""
    assert to_topas_spacegroup("P 21/n", 14) == "P21/n"


# ---------------- 元素/散乱種 ----------------


@pytest.mark.parametrize(
    ("cif_symbol", "expected"), [("Pb", "Pb"), ("O", "O"), ("Pb2+", "Pb"), ("O2-", "O")]
)
def test_neutral_element_is_the_default(cif_symbol, expected):
    """既定は中性原子。**常に TOPAS の散乱表に存在する**ので不明種で落ちない。"""
    assert to_topas_element(cif_symbol) == expected


@pytest.mark.parametrize(
    ("cif_symbol", "expected"), [("Pb2+", "Pb+2"), ("O2-", "O-2"), ("Fe3+", "Fe+3"), ("Pb", "Pb")]
)
def test_ionic_scattering_reorders_the_charge(cif_symbol, expected):
    """CIF は `Pb2+`、TOPAS は `Pb+2` の順。opt-in。"""
    assert to_topas_element(cif_symbol, ionic=True) == expected


# ---------------- 結晶系 ----------------


@pytest.mark.parametrize(
    ("it_number", "expected"),
    [
        (1, "triclinic"), (2, "triclinic"),
        (3, "monoclinic"), (15, "monoclinic"),
        (16, "orthorhombic"), (62, "orthorhombic"), (74, "orthorhombic"),
        (75, "tetragonal"), (142, "tetragonal"),
        (143, "trigonal"), (167, "trigonal"),
        (168, "hexagonal"), (194, "hexagonal"),
        (195, "cubic"), (225, "cubic"), (230, "cubic"),
    ],
)
def test_crystal_system_from_it_number(it_number, expected):
    assert crystal_system(it_number) == expected


@pytest.mark.parametrize(
    ("hm", "expected"),
    [
        ("P n m a", "orthorhombic"), ("P b c m", "orthorhombic"), ("P c a 21", "orthorhombic"),
        ("P m m m", "orthorhombic"), ("P 2 2 2", "orthorhombic"),
        ("F m -3 m", "cubic"), ("I a -3 d", "cubic"), ("P 21 3", "cubic"), ("P a -3", "cubic"),
        ("R -3 c", "trigonal"), ("P 31 2 1", "trigonal"), ("P -3 m 1", "trigonal"),
        ("P 63/m", "hexagonal"), ("P 63 m c", "hexagonal"), ("P 6/m m m", "hexagonal"),
        ("P 42/m n m", "tetragonal"), ("I 4/m", "tetragonal"), ("P -4 21 c", "tetragonal"),
        ("P 21/n", "monoclinic"), ("C 2/c", "monoclinic"), ("P 21", "monoclinic"),
        ("P m", "monoclinic"),
        ("P 1", "triclinic"), ("P -1", "triclinic"),
    ],
)
def test_crystal_system_inferred_from_hm_when_it_number_is_absent(hm, expected):
    """**実 CIF は IT 番号を持たないことが多い** (docs/benchmark の PbSO4-Wyckoff.cif がそう)。

    番号が無いからと triclinic に落とすと、直方晶の 90° 角を 3 本とも解放してしまう。
    90° 近傍では角度方向の微分がほぼ 0 なのでヘッシアンが特異になり最小二乗が失敗する
    (CLAUDE.md の CaTeO3 P1 展開と同じ病理)。**緩い拘束は安全ではない**。
    """
    assert crystal_system(None, hm) == expected


def test_it_number_wins_over_the_symbol():
    assert crystal_system(62, "F m -3 m") == "orthorhombic"


def test_crystal_system_is_triclinic_when_nothing_is_known():
    assert crystal_system(None) == "triclinic"


def test_right_angles_are_never_released_in_the_triclinic_fallback():
    """系が不明でも 90°/120° ちょうどの角は解放しない (特異ヘッシアン防止の安全網)。"""
    phase = structure_to_topas_phase(
        _structure(alpha=90.0, beta=90.0, gamma=90.0, spacegroup_hm="P 1", it_number=None), "u"
    )
    assert phase.free_cell_keys == ("a", "b", "c")


def test_genuinely_oblique_angles_are_released_in_the_triclinic_fallback():
    phase = structure_to_topas_phase(
        _structure(alpha=88.0, beta=99.0, gamma=101.0, spacegroup_hm="P 1", it_number=None), "u"
    )
    assert phase.free_cell_keys == ("a", "b", "c", "al", "be", "ga")


@requires_real_data
def test_real_pbso4_cif_without_it_number_is_orthorhombic():
    """回帰: 実 CIF (IT 番号なし・H-M のみ) で角度が解放されないこと。"""
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    st = read_structure_cif("docs/benchmark/testdata/PbSO4-Wyckoff.cif")
    assert st.it_number is None  # この CIF は番号を持たない
    phase = structure_to_topas_phase(st, "PbSO4")
    assert phase.space_group == "Pnma"
    assert phase.free_cell_keys == ("a", "b", "c")


# ---------------- 構造 → TopasPhase ----------------


def _structure(**kw) -> Structure:
    base = dict(
        a=8.482, b=5.397, c=6.959, alpha=90.0, beta=90.0, gamma=90.0,
        spacegroup_hm="P n m a", it_number=62,
        atoms=(
            Atom(label="Pb", type_symbol="Pb", x=0.1879, y=0.25, z=0.1667, occ=1.0, uiso=0.019),
            Atom(label="S", type_symbol="S", x=0.4367, y=0.75, z=0.1842, occ=1.0, uiso=0.0089),
        ),
    )
    base.update(kw)
    return Structure(**base)  # type: ignore[arg-type]


def test_uiso_is_converted_to_beq():
    """TOPAS は B (beq)、CIF/GSAS は Uiso。**B = 8π²·Uiso**。"""
    phase = structure_to_topas_phase(_structure(), "PbSO4")
    assert phase.sites[0].beq.value == pytest.approx(0.019 * 8.0 * math.pi**2)
    assert BEQ_PER_UISO == pytest.approx(8.0 * math.pi**2)


def test_orthorhombic_emits_three_independent_axes():
    phase = structure_to_topas_phase(_structure(), "PbSO4")
    assert set(phase.cell) == {"a", "b", "c"}
    assert phase.free_cell_keys == ("a", "b", "c")
    assert all(not p.is_reference for p in phase.cell.values())


def test_cubic_constrains_b_and_c_to_a():
    """**これが無いと立方晶の a/b/c が独立に精密化されて対称性が壊れる**。"""
    phase = structure_to_topas_phase(
        _structure(a=5.46, b=5.46, c=5.46, spacegroup_hm="F m -3 m", it_number=225), "CaF2"
    )
    assert phase.cell["b"].expression == "Get(a)"
    assert phase.cell["c"].expression == "Get(a)"
    assert phase.free_cell_keys == ("a",)  # 解放してよいのは a のみ


def test_tetragonal_constrains_b_to_a_only():
    phase = structure_to_topas_phase(
        _structure(a=4.59, b=4.59, c=2.96, spacegroup_hm="P 42/m n m", it_number=136), "TiO2"
    )
    assert phase.cell["b"].expression == "Get(a)"
    assert "c" in phase.free_cell_keys
    assert phase.free_cell_keys == ("a", "c")


def test_hexagonal_adds_the_gamma_120_constraint():
    phase = structure_to_topas_phase(
        _structure(a=3.25, b=3.25, c=5.21, gamma=120.0, spacegroup_hm="P 63 m c", it_number=186),
        "ZnO",
    )
    assert phase.cell["b"].expression == "Get(a)"
    assert phase.cell["ga"].value == pytest.approx(120.0)
    assert "ga" not in phase.free_cell_keys  # 120° は固定
    assert phase.free_cell_keys == ("a", "c")


def test_monoclinic_frees_the_unique_angle_only():
    phase = structure_to_topas_phase(
        _structure(a=5.0, b=9.0, c=7.0, beta=99.5, spacegroup_hm="P 21/n", it_number=14), "m"
    )
    assert phase.free_cell_keys == ("a", "b", "c", "be")
    assert phase.cell["be"].value == pytest.approx(99.5)
    assert phase.cell["al"].value == pytest.approx(90.0)
    assert "al" not in phase.free_cell_keys


def test_triclinic_frees_everything():
    phase = structure_to_topas_phase(
        _structure(alpha=88.0, beta=99.0, gamma=101.0, spacegroup_hm="P -1", it_number=2), "t"
    )
    assert phase.free_cell_keys == ("a", "b", "c", "al", "be", "ga")


def test_sites_carry_labels_occupancies_and_coordinates():
    phase = structure_to_topas_phase(_structure(), "PbSO4")
    pb = phase.sites[0]
    assert (pb.label, pb.element) == ("Pb", "Pb")
    assert pb.x.value == pytest.approx(0.1879)
    assert pb.occupancy.value == pytest.approx(1.0)


def test_everything_starts_fixed():
    """構造読み込み時点では**何も解放しない**。解放は段階フラグ (T6) の責務。"""
    phase = structure_to_topas_phase(_structure(), "PbSO4")
    assert not any(p.refine for p in phase.cell.values())
    for site in phase.sites:
        assert not (site.x.refine or site.y.refine or site.z.refine)
        assert not site.beq.refine and not site.occupancy.refine


def test_phase_spec_constraint_groups_are_carried_through():
    """`PhaseSpec` の混合占有/等値宣言が TopasPhase の拘束宣言へ写る。"""
    from tsumugin.autorietveld.model import PhaseSpec

    spec = PhaseSpec(
        structure_path="x.cif",
        phase_name="garnet",
        mixed_occupancy_groups=(("Fe1", "Al1"),),
        occupancy_equiv_groups=(("O1", "D1"),),
    )
    phase = structure_to_topas_phase(_structure(), "garnet", spec=spec)
    assert phase.occupancy_sum_groups == (("Fe1", "Al1"),)
    # 混合占有サイトは Uiso 等価も張る (GSAS の add_EquivConstr 相当)
    assert ("Fe1", "Al1") in phase.beq_equiv_groups


def test_duplicate_labels_are_rejected():
    """同名サイトは共有 prm 名が衝突して**黙って別サイトを結合する**ので弾く。"""
    struct = _structure(
        atoms=(
            Atom(label="O", type_symbol="O", x=0.1, y=0.2, z=0.3, occ=1.0, uiso=0.01),
            Atom(label="O", type_symbol="O", x=0.4, y=0.5, z=0.6, occ=1.0, uiso=0.01),
        )
    )
    with pytest.raises(ValueError, match="重複"):
        structure_to_topas_phase(struct, "x")


# ---------------- 特殊位置の精度 (#172) ----------------

#: P6₃/m の一般位置 (fluoroapatite)。CIF が対称操作を持つときと同じ経路を通す。
_P63M = (
    "x,y,z", "-y,x-y,z", "-x+y,-x,z", "-x,-y,z+1/2", "y,-x+y,z+1/2", "x-y,x,z+1/2",
    "-x,-y,-z", "y,-x+y,-z", "x-y,x,-z", "x,y,-z+1/2", "-y,x-y,-z+1/2", "-x+y,-x,-z+1/2",
)


def _hexagonal(atoms) -> Structure:
    return Structure(
        a=9.37172, b=9.37172, c=6.88587, alpha=90.0, beta=90.0, gamma=120.0,
        spacegroup_hm="P 63/m", it_number=176, atoms=atoms, symops=_P63M,
    )


def test_special_position_coordinates_are_written_at_full_precision():
    """**CIF の 6 桁 1/3 では TOPAS が 4f を一般位置と誤り、原子が 8 個増える** (#172)。

    TOPAS は多重度を座標の一致 (許容差 ~1e-8) で決めるので、``0.333333`` のままでは
    4f サイトが多重度 12 へ化ける。実 fluoroapatite で cell_mass 1008.6 → 1329.2、
    Rwp 42%。ピーク位置は正しいままなので Rwp からは原因に辿り着けない。
    """
    struct = _hexagonal(
        (Atom(label="CA1", type_symbol="Ca", x=0.333333, y=0.666667, z=0.001913,
              occ=1.0, uiso=0.006),)
    )
    site = structure_to_topas_phase(struct, "FAP").sites[0]
    assert abs(site.x.value - 1 / 3) < 1e-12
    assert abs(site.y.value - 2 / 3) < 1e-12
    assert site.z.value == pytest.approx(0.001913)  # 自由軸は動かさない


def test_general_position_coordinates_are_not_touched():
    struct = _hexagonal(
        (Atom(label="O7", type_symbol="O", x=0.33951, y=0.258126, z=0.070641,
              occ=1.0, uiso=0.0067),)
    )
    site = structure_to_topas_phase(struct, "FAP").sites[0]
    assert (site.x.value, site.y.value, site.z.value) == (0.33951, 0.258126, 0.070641)


def test_snapping_does_not_change_which_axes_are_free():
    """吸着は**判定を変えない** — 自由軸判定と同じサイト対称群から出るため。"""
    struct = _hexagonal(
        (
            Atom(label="CA1", type_symbol="Ca", x=0.333333, y=0.666667, z=0.001913,
                 occ=1.0, uiso=0.006),
            Atom(label="F4", type_symbol="F", x=0.0, y=0.0, z=0.25, occ=1.0, uiso=0.014),
            Atom(label="O7", type_symbol="O", x=0.33951, y=0.258126, z=0.070641,
                 occ=1.0, uiso=0.0067),
        )
    )
    free = {s.label: s.free_coord_axes for s in structure_to_topas_phase(struct, "FAP").sites}
    assert free == {"CA1": ("z",), "F4": (), "O7": ("x", "y", "z")}


def test_snapping_is_skipped_when_the_cif_has_no_symops():
    """対称操作が無ければ触らない (判定できないものは動かさない)。"""
    struct = Structure(
        a=9.37172, b=9.37172, c=6.88587, alpha=90.0, beta=90.0, gamma=120.0,
        spacegroup_hm="P 63/m", it_number=176, symops=(),
        atoms=(Atom(label="CA1", type_symbol="Ca", x=0.333333, y=0.666667, z=0.0,
                    occ=1.0, uiso=0.006),),
    )
    site = structure_to_topas_phase(struct, "FAP").sites[0]
    assert site.x.value == 0.333333


_SITE_LINE = re.compile(r"^\s*site\s+(\S+)\s+x\s+(\S+)\s+y\s+(\S+)\s+z\s+(\S+)", re.M)


def _rendered_coords(structure: Structure, name: str) -> "dict[str, tuple[float, ...]]":
    """**INP の字面から**座標を読み戻す (TOPAS が実際に読む値で検算するため)。"""
    from tsumugin.topas.inp import Param, TopasDocument, TopasHistogram

    doc = TopasDocument(
        histograms=(TopasHistogram(data_path="d.xye", background=Param(0.0)),),
        phases=(structure_to_topas_phase(structure, name),),
    )
    return {
        m.group(1): tuple(float(m.group(i)) for i in (2, 3, 4))
        for m in _SITE_LINE.finditer(doc.render())
    }


def test_rendered_coordinates_satisfy_the_topas_site_merge_tolerance():
    """**INP に書き出された数字**がサイト対称を 1e-8 精度で満たすこと (#172 の恒久ガード)。

    吸着を実装した後でも、整形が桁を落とせば同じ欠陥が戻る。TOPAS が多重度判定に使う量
    (`site_symmetry_residual`) を**レンダリング結果から**測ることで、float の値だけでなく
    字面の精度まで含めて縛る。
    """
    from tsumugin.topas.symmetry import SITE_MERGE_TOLERANCE, site_symmetry_residual

    struct = _hexagonal(
        (
            Atom(label="CA1", type_symbol="Ca", x=0.333333, y=0.666667, z=0.001913,
                 occ=1.0, uiso=0.006),
            Atom(label="CA2", type_symbol="Ca", x=0.241976, y=0.992603, z=0.25,
                 occ=1.0, uiso=0.0046),
            Atom(label="F4", type_symbol="F", x=0.0, y=0.0, z=0.25, occ=1.0, uiso=0.014),
            Atom(label="O7", type_symbol="O", x=0.33951, y=0.258126, z=0.070641,
                 occ=1.0, uiso=0.0067),
        )
    )
    for label, position in _rendered_coords(struct, "FAP").items():
        residual = site_symmetry_residual(_P63M, position)
        assert residual < SITE_MERGE_TOLERANCE, (
            f"{label}: 残差 {residual:.3e} — TOPAS が特殊位置を一般位置へ展開する"
        )
