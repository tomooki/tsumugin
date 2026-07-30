"""M12: サイト対称による座標の自由軸判定。

GSAS の `GSASIIspc.GetCSxinel` に相当する機能を対称操作から純 numpy で求める。
**特殊位置を解放すると対称性が壊れる** — しかも Rwp は下がることがあるので、
実データでは静かに間違った構造へ行き着く。実 PbSO4 で座標段が revert された原因。
"""

from __future__ import annotations

import numpy as np
import pytest

from .conftest import requires_real_data

from tsumugin.topas.symmetry import free_coord_axes, parse_symop, site_symmetry_projector

# Pnma (#62) の一般位置 8 個 (PbSO4-Wyckoff.cif 由来の書き方)
_PNMA = (
    "x,y,z",
    "1/2-x,1/2+y,1/2+z",
    "x,1/2-y,z",
    "1/2-x,-y,1/2+z",
    "-x,-y,-z",
    "1/2+x,1/2-y,1/2-z",
    "-x,1/2+y,-z",
    "1/2+x,y,1/2-z",
)


# ---------------- 対称操作のパース ----------------


def test_identity():
    rotation, translation = parse_symop("x,y,z")
    assert np.allclose(rotation, np.eye(3))
    assert np.allclose(translation, 0.0)


def test_sign_and_fraction_prefix_form():
    """CIF 流の ``1/2-x``。"""
    rotation, translation = parse_symop("1/2-x,1/2+y,z")
    assert np.allclose(rotation, np.diag([-1.0, 1.0, 1.0]))
    assert np.allclose(translation, [0.5, 0.5, 0.0])


def test_suffix_form_is_equivalent():
    """TOPAS ``.sg`` 流の ``-x+1/2``。同じ操作として読めること。"""
    a = parse_symop("-x+1/2,y+1/2,z")
    b = parse_symop("1/2-x,1/2+y,z")
    assert np.allclose(a[0], b[0]) and np.allclose(a[1], b[1])


def test_axis_permutation():
    rotation, _ = parse_symop("y,x,-z")
    assert np.allclose(rotation @ np.array([1.0, 2.0, 3.0]), [2.0, 1.0, -3.0])


def test_malformed_symop_raises():
    with pytest.raises(ValueError):
        parse_symop("x,y")


# ---------------- サイト対称 ----------------


def test_general_position_frees_all_axes():
    """一般位置 (どの操作でも自分に戻らない) は 3 軸とも独立。"""
    assert free_coord_axes(_PNMA, (0.123, 0.456, 0.789)) == ("x", "y", "z")


def test_mirror_site_fixes_the_perpendicular_axis():
    """Pnma の Pb (0.188, 1/4, 0.167) は鏡面上 — **y は 1/4 に固定**。

    これを解放したのが実 PbSO4 で座標段が revert された原因。
    """
    assert free_coord_axes(_PNMA, (0.1882, 0.25, 0.167)) == ("x", "z")


def test_projector_matches_the_expected_diagonal():
    projector = site_symmetry_projector(_PNMA, (0.1882, 0.25, 0.167))
    assert np.allclose(projector, np.diag([1.0, 0.0, 1.0]))


def test_inversion_centre_fixes_everything():
    assert free_coord_axes(_PNMA, (0.0, 0.0, 0.0)) == ()


def test_coupled_axes_are_not_released():
    """三方晶の (x, -x, z) のように軸が結束する場合は 1 変数の拘束式が要る。

    v1 は**解放しない** — 独立に動かすと対称性が壊れるため、書けないものは触らない。
    """
    trigonal = ("x,y,z", "-y,x-y,z", "-x+y,-x,z", "y,x,-z", "x-y,-y,-z", "-x,-x+y,-z")
    # z=0 の鏡映 (y,x,-z) 上の点。x と y が入れ替わるので独立には動かせない。
    free = free_coord_axes(trigonal, (0.3, 0.3, 0.0))
    assert free == ()
    projector = site_symmetry_projector(trigonal, (0.3, 0.3, 0.0))
    assert projector[0, 1] == pytest.approx(0.5)  # x-y が結束している証拠


def test_no_symops_means_no_release():
    """**判定できないときは触らない**。対称性の破れは Rwp に現れにくく静かに構造を壊す。"""
    assert free_coord_axes((), (0.1, 0.2, 0.3)) == ()


def test_unparsable_symops_are_skipped_not_fatal():
    assert free_coord_axes(("x,y,z", "garbage"), (0.11, 0.22, 0.33)) == ("x", "y", "z")


# ---------------- 特殊位置への吸着 (#172) ----------------
#
# **TOPAS はサイトの多重度を「対称操作で写した点が元の点と一致するか」で決める。実測した
# 許容差は約 1e-8 (分率座標)** — 3.3e-8 ずれると別原子とみなされる。CIF の座標欄は 5-8 桁が
# 標準なので、1/3 は必ずこの網から漏れる。漏れると P6₃/m の 4f サイトが一般位置 (多重度 12)
# へ展開され、**単位胞に存在しない原子が 8 個増えたまま完走する** (実 fluoroapatite で
# cell_mass 1008.6 → 1329.2、Rwp 42%)。ピーク位置は正しいままなので気づきにくい。


def test_special_position_is_snapped_to_the_exact_value():
    """``0.333333`` を 1/3 へ吸着する。TOPAS の 1e-8 判定を通せる精度に載せるのが目的。"""
    from tsumugin.topas.symmetry import snap_to_special_position

    ops = ("x,y,z", "-y,x-y,z", "-x+y,-x,z")  # 3 回軸
    x, y, z = snap_to_special_position(ops, (0.333333, 0.666667, 0.001913))
    assert abs(x - 1 / 3) < 1e-12
    assert abs(y - 2 / 3) < 1e-12
    assert z == pytest.approx(0.001913)  # 自由軸は動かさない


def test_general_position_is_left_untouched():
    """一般位置はサイト対称群が単位元だけ — 恒等写像でなければならない。"""
    from tsumugin.topas.symmetry import snap_to_special_position

    position = (0.11, 0.22, 0.33)
    assert snap_to_special_position(("x,y,z", "-x,-y,-z"), position) == position


def test_snapping_survives_a_lattice_translation_in_the_operation():
    """並進を含む操作 (``-x,-y,z+1/2`` 等) でも格子並進を解いて平均する。"""
    from tsumugin.topas.symmetry import snap_to_special_position

    # 2₁ 軸上の (0, 0, z): -x,-y,z+1/2 では戻らないので鏡 -x,y,z / x,-y,z を使う。
    x, y, z = snap_to_special_position(("x,y,z", "-x,y,z", "x,-y,z"), (1e-7, -2e-7, 0.4))
    assert abs(x) < 1e-14 and abs(y) < 1e-14
    assert z == pytest.approx(0.4)


def test_no_symops_means_no_snapping():
    """判定材料が無ければ座標に触らない (`free_coord_axes` と同じ安全側の方針)。"""
    from tsumugin.topas.symmetry import snap_to_special_position

    assert snap_to_special_position((), (0.333333, 0.666667, 0.0)) == (
        0.333333,
        0.666667,
        0.0,
    )


def test_snapping_does_not_move_an_atom_that_is_far_from_the_special_position():
    """許容差 (既定 1e-4) の外にある座標は特殊位置とみなさない = 動かさない。"""
    from tsumugin.topas.symmetry import snap_to_special_position

    ops = ("x,y,z", "-y,x-y,z", "-x+y,-x,z")
    far = (0.3300, 0.6600, 0.1)
    assert snap_to_special_position(ops, far) == far


def test_snapped_axes_are_exactly_the_ones_that_are_not_free():
    """**吸着と自由軸判定は同じサイト対称群から出る**こと (別々の基準だと矛盾する)。"""
    from tsumugin.topas.symmetry import snap_to_special_position

    ops = ("x,y,z", "-y,x-y,z", "-x+y,-x,z")
    start = (0.333333, 0.666667, 0.001913)
    snapped = snap_to_special_position(ops, start)
    free = free_coord_axes(ops, start)
    moved = {axis for axis, a, b in zip("xyz", start, snapped) if a != b}
    assert moved.isdisjoint(free), "自由軸を動かしてはいけない"


@requires_real_data
def test_real_pbso4_cif_site_symmetry():
    """実 CIF の対称操作で PbSO4 の各サイトの自由軸を求める (回帰)。"""
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    structure = read_structure_cif("docs/benchmark/testdata/PbSO4-Wyckoff.cif")
    assert structure.symops, "この CIF は対称操作を持つ"
    free = {
        atom.label: free_coord_axes(structure.symops, (atom.x, atom.y, atom.z))
        for atom in structure.atoms
    }
    # Pb/S/O1/O2 は鏡面上 (y = 1/4) — x, z のみ。O3 は一般位置。
    assert free["Pb"] == ("x", "z")
    assert free["S"] == ("x", "z")
    assert free["O3"] == ("x", "y", "z")


@pytest.mark.topas
def test_sg_filename_encodes_slash_as_o():
    """**TOPAS は空間群名の ``/`` を ``o`` (over) にエンコードする** (実測: P63/m → p63om.sg)。

    これを知らないと ``/`` を含む空間群 (P21/c・C2/c・P63/m …) で対称操作が引けず、
    座標段が**黙って no-op** になる (実 fluoroapatite で発覚)。
    """
    from tsumugin.topas.symmetry import ensure_symops

    ops = ensure_symops("P63/m", ())
    assert len(ops) >= 12, "P63/m の一般位置が引けていない"
    # 6₃ 軸上の CA1 (1/3, 2/3, z) は z のみ自由、-6 サイトの F4 は完全固定。
    assert free_coord_axes(ops, (0.333333, 0.666667, 0.001913)) == ("z",)
    assert free_coord_axes(ops, (0.0, 0.0, 0.25)) == ()


# ---------------- ``.sg`` のコメント行 ----------------


def test_sg_comment_lines_are_not_mistaken_for_symops(tmp_path):
    """**体心/面心群の ``.sg`` は ``' +(1/2, 1/2, 1/2) ---`` というコメント行を挟む** (実測)。

    カンマが 2 つあるので素朴な行数フィルタを通ってしまい、回転行列が**零行列**の偽の操作に
    化ける。零行列はサイト対称群の射影子を薄めるので、``(1/2,1/2,1/2)`` にあるサイト
    (体心格子では珍しくない) の自由軸判定が崩れ、**座標が一度も解放されないまま完走する**。
    """
    from tsumugin.topas.symmetry import read_sg_symops

    sg = tmp_path / "Sg" / "test.sg"
    sg.parent.mkdir(parents=True)
    sg.write_text(
        "space_group\n{\n\txyzs\n\t{\n"
        "\t\tx, y, z\n"
        "\t\t-x, -y, -z\n"
        "' +(1/2, 1/2, 1/2) -------------------------\n"
        "\t\tx+1/2, y+1/2, z+1/2\n"
        "\t}\n}\n",
        encoding="utf-8",
    )
    ops = read_sg_symops("test", home=tmp_path)
    assert ops == ("x, y, z", "-x, -y, -z", "x+1/2, y+1/2, z+1/2")


def test_body_centre_site_keeps_its_free_axes_despite_the_comment_line():
    """コメント行を操作として拾うと (1/2,1/2,1/2) のサイトで自由軸が消える (退行ガード)。"""
    ops = ("x,y,z", "' +(1/2, 1/2, 1/2) ----", "x+1/2,y+1/2,z+1/2")
    # コメント行を除いた真の集合では一般位置 = 3 軸とも自由。
    assert free_coord_axes(("x,y,z", "x+1/2,y+1/2,z+1/2"), (0.5, 0.5, 0.5)) == (
        "x",
        "y",
        "z",
    )
    # 混入した状態では壊れることを明示しておく (だから読み取り側で落とす)。
    assert free_coord_axes(ops, (0.5, 0.5, 0.5)) == ()
