"""M12: サイト対称による座標の自由軸判定。

GSAS の `GSASIIspc.GetCSxinel` に相当する機能を対称操作から純 numpy で求める。
**特殊位置を解放すると対称性が壊れる** — しかも Rwp は下がることがあるので、
実データでは静かに間違った構造へ行き着く。実 PbSO4 で座標段が revert された原因。
"""

from __future__ import annotations

import numpy as np
import pytest

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
