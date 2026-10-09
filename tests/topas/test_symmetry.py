"""M12: サイト対称による座標の自由軸判定。

GSAS の `GSASIIspc.GetCSxinel` に相当する機能を対称操作から純 numpy で求める。
**特殊位置を解放すると対称性が壊れる** — しかも Rwp は下がることがあるので、
実データでは静かに間違った構造へ行き着く。実 PbSO4 で座標段が revert された原因。
"""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

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


# ---------------- Sg/*.sg の補完 (#219) ----------------


def test_sg_probe_inp_declares_a_wavelength(monkeypatch):
    """**探査 INP に ``lam`` が無いと tc.exe は空間群を展開する前に必ず異常終了する** (#219)。

    実測: ``Cannot locate lam from riet_app_3 in data structures``。CW の X 線パターンとして
    解釈できないため。実 tc.exe での検算は下の ``-m topas`` テストが担う。
    """
    from tsumugin.topas import driver
    from tsumugin.topas.symmetry import _generate_sg_file

    seen: list[str] = []
    monkeypatch.setattr(driver, "run_tc", lambda inp, **kw: seen.append(inp))
    _generate_sg_file("P121/c1")
    assert seen, "探査 INP を流していない"
    assert "lam" in seen[0] and " lo " in seen[0], f"波長の宣言が無い:\n{seen[0]}"


def test_symop_generation_failure_is_raised_not_swallowed(monkeypatch):
    """**補完に失敗したら空タプルを黙って返さない** (#219)。

    空を返すと全サイトの ``free_coord_axes`` が空になり、座標段が何も解放しないまま
    完走する。特殊位置の吸着 (#172) も効かず、単位胞に存在しない原子が増えうる。
    原因 (対称操作の欠落) は段の記録からは辿れない。
    """
    from tsumugin.errors import TopasRunError, TsumuginError
    from tsumugin.topas import symmetry

    def boom(space_group):
        raise TopasRunError("Cannot locate lam from riet_app_3 in data structures")

    monkeypatch.setattr(symmetry, "read_sg_symops", lambda sg, home=None: ())
    monkeypatch.setattr(symmetry, "_generate_sg_file", boom)
    with pytest.raises(TsumuginError) as excinfo:
        symmetry.ensure_symops("P121/c1", ())
    assert type(excinfo.value).__name__ == "TopasSymmetryError"
    message = str(excinfo.value)
    assert "P121/c1" in message and "Cannot locate lam" in message, "原因が伝わらない"


def test_symop_generation_that_leaves_no_readable_file_is_raised(monkeypatch):
    """tc.exe が正常終了しても ``Sg/`` から読めなければ同じく失敗として伝える。

    ファイル名の符号化 (``/`` → ``o``) がずれると「生成は成功・読めない」になる (実測)。
    """
    from tsumugin.errors import TsumuginError
    from tsumugin.topas import symmetry

    monkeypatch.setattr(symmetry, "read_sg_symops", lambda sg, home=None: ())
    monkeypatch.setattr(symmetry, "_generate_sg_file", lambda sg: None)
    with pytest.raises(TsumuginError) as excinfo:
        symmetry.ensure_symops("P121/c1", ())
    assert type(excinfo.value).__name__ == "TopasSymmetryError"


def test_cif_symops_are_used_as_is_without_launching_tc(monkeypatch):
    """対称操作を持つ CIF の経路は不変 (#219 非回帰): tc.exe を起動しない。"""
    from tsumugin.topas import symmetry

    def must_not_run(*args, **kwargs):
        raise AssertionError("CIF に対称操作があるのに Sg/ を引きに行った")

    monkeypatch.setattr(symmetry, "read_sg_symops", must_not_run)
    monkeypatch.setattr(symmetry, "_generate_sg_file", must_not_run)
    assert symmetry.ensure_symops("Pnma", _PNMA) == _PNMA


_P21C_WITHOUT_SYMOPS = """\
data_synthetic
_cell_length_a 5.0
_cell_length_b 6.0
_cell_length_c 7.0
_cell_angle_alpha 90
_cell_angle_beta 100
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 1 21/c 1'
_symmetry_Int_Tables_number 14
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Fe1 Fe 0.1234 0.2345 0.3456 1.0 0.01
O1 O 0.4321 0.1111 0.2222 1.0 0.01
"""


@contextmanager
def _sg_file_absent(filename: str):
    """TOPAS ホームの ``Sg/<filename>`` を**一時的に退避**し、生成経路を必ず通らせる。

    既に生成済みの機械では補完が試されず、テストが何も検証しなくなる (この Issue の
    環境依存そのもの)。終了時は元に戻し、元々無かったなら生成物を消す (ホームを汚さない)。
    """
    from tsumugin.topas.availability import topas_home

    home = topas_home()
    if home is None:
        pytest.skip("TOPAS ホームが無い")
    path = Path(home) / "Sg" / filename
    backup = path.with_name(path.name + ".tsumugin-test-backup")
    existed = path.is_file()
    if existed:
        path.replace(backup)
    try:
        yield path
    finally:
        if existed:
            backup.replace(path)
        elif path.is_file():
            path.unlink()


@pytest.fixture()
def p21c_sg_absent():
    with _sg_file_absent("p121oc1.sg") as path:
        yield path


def test_probe_that_aborts_after_writing_the_sg_file_is_not_fatal(monkeypatch):
    """**成否は探査の終了状態ではなく「Sg/ から読めるか」で決める**。

    実測: Fd-3m / I41/amd / R-3 / P42/mnm では tc.exe が ``.sg`` を書いた**後で**
    ``No hkls`` により異常終了する。探査の失敗を致命扱いすると、対称操作が手に入って
    いるのに `TopasSymmetryError` で止めてしまう (対称操作の無い CIF でよくある群)。
    """
    from tsumugin.errors import TopasRunError
    from tsumugin.topas import symmetry

    written: list[str] = []

    def probe_writes_then_aborts(space_group):
        written.append(space_group)
        raise TopasRunError("No hkls for sgprobe.xye | Abnormal program termination.")

    monkeypatch.setattr(
        symmetry, "read_sg_symops", lambda sg, home=None: _PNMA if written else ()
    )
    monkeypatch.setattr(symmetry, "_generate_sg_file", probe_writes_then_aborts)
    assert symmetry.ensure_symops("Fd-3m", ()) == _PNMA


@pytest.mark.topas
@pytest.mark.parametrize(
    ("space_group", "filename", "count"),
    [
        ("Fd-3m", "fd-3m.sg", 192),
        ("I41/amd", "i41oamd.sg", 32),
        ("R-3", "r-3.sg", 18),
        ("P42/mnm", "p42omnm.sg", 16),
        ("P6/mmm", "p6ommm.sg", 24),
        ("P-1", "p-1.sg", 2),
    ],
)
def test_sg_generation_covers_every_crystal_system(space_group, filename, count):
    """消滅則の多い群でも探査が通り、一般位置が揃うこと (実 tc.exe)。

    当初の探査 (2θ 10–20°・a=5 Å) は Fd-3m 等で**反射が 1 本も無く** ``No hkls`` で
    異常終了していた。生成ファイルは一時退避/掃除する (TOPAS ホームを汚さない)。
    """
    from tsumugin.topas.symmetry import _generate_sg_file, read_sg_symops

    with _sg_file_absent(filename):
        _generate_sg_file(space_group)  # 探査そのものが異常終了しないこと
        assert len(read_sg_symops(space_group)) == count


@pytest.mark.topas
def test_space_group_missing_from_sg_is_generated_and_frees_general_positions(
    tmp_path, p21c_sg_absent
):
    """**``Sg/`` に無い空間群 + 対称操作の無い CIF** で一般位置の原子が 3 軸とも解放される (#219)。

    以前は探査 INP が必ず異常終了し、例外が握りつぶされて ``{'Fe1': (), 'O1': ()}`` に
    なっていた。同じ CIF でも、その空間群を過去に TOPAS で回した機械かどうかで結果が
    変わっていた (NFR-102)。
    """
    from tsumugin.autorietveld.cif_normalize import read_structure_cif
    from tsumugin.topas.structure import structure_to_topas_phase, to_topas_spacegroup
    from tsumugin.topas.symmetry import ensure_symops

    cif = tmp_path / "synthetic_p21c_nosymops.cif"
    cif.write_text(_P21C_WITHOUT_SYMOPS, encoding="ascii")
    st = read_structure_cif(str(cif))
    assert not st.symops, "前提: CIF に対称操作が無い"
    sg = to_topas_spacegroup(st.spacegroup_hm, st.it_number)
    assert not p21c_sg_absent.is_file(), "前提: Sg/ に未生成"

    ops = ensure_symops(sg, st.symops)
    assert len(ops) == 4, f"P21/c の一般位置 4 個が引けていない: {ops}"
    phase = structure_to_topas_phase(st, "syn", symops=ops)
    assert {s.label: s.free_coord_axes for s in phase.sites} == {
        "Fe1": ("x", "y", "z"),
        "O1": ("x", "y", "z"),
    }
