"""特殊位置への射影 — バックエンド非依存の `tsumugin.site_symmetry` (GSAS 非依存で測る)。

2026-10-15 実測: GSAS-II の ``GSASIIspc.SytSym`` は P6₃mc の ``(0.3333, 0.6667, 0)`` を
``('m(110)', 6)`` (一般位置扱い・多重度 3 倍) と判定し、``0.33333`` なら ``('3m(100)', 2)``。
CIF の座標欄が 4 桁だと特殊位置が網から漏れる。ここでは書かれた桁数から許容差を決めて
射影することを測る。
"""

from __future__ import annotations

import pytest

# P6₃mc (No. 186) の一般位置 (GSAS-II の SpcGroup が返す 12 操作と同じ集合)。
P63MC = (
    "x,y,z", "-y,x-y,z", "-x+y,-x,z", "-x,-y,z+1/2", "y,-x+y,z+1/2", "x-y,x,z+1/2",
    "-y,-x,z", "-x+y,y,z", "x,x-y,z", "y,x,z+1/2", "x-y,-y,z+1/2", "-x,-x+y,z+1/2",
)
FOUR_DECIMALS = (0.5e-4, 0.5e-4, 0.5e-4)


def test_four_decimal_third_is_snapped_when_precision_is_given():
    """★4 桁の 1/3 は、書かれた桁数の丸め誤差の範囲で 3m サイトと区別できない → 射影する。"""
    from tsumugin.site_symmetry import snap_to_special_position

    x, y, z = snap_to_special_position(P63MC, (0.3333, 0.6667, 0.0), coord_error=FOUR_DECIMALS)
    assert x == pytest.approx(1 / 3, abs=1e-12)
    assert y == pytest.approx(2 / 3, abs=1e-12)


def test_free_axis_is_not_moved():
    """★最小ノルム射影: 3m サイトの z は自由軸なので**ビット同一**で残る。"""
    from tsumugin.site_symmetry import snap_to_special_position

    _, _, z = snap_to_special_position(P63MC, (0.3333, 0.6667, 0.3817), coord_error=FOUR_DECIMALS)
    assert z == 0.3817


def test_displacement_beyond_written_precision_is_kept():
    """陽性対照: 0.3330 は 4 桁の丸めでは 1/3 に届かない (差 3.3e-4) — 実在の変位として残す。"""
    from tsumugin.site_symmetry import snap_to_special_position

    position = (0.3330, 0.6667, 0.0)
    assert snap_to_special_position(P63MC, position, coord_error=FOUR_DECIMALS) == position


def test_three_decimal_third_needs_the_written_precision():
    """★3 桁の 1/3 (``0.667``) は既定の ``tol=1e-4`` では拾えない (像のずれ 1e-3) — 桁数から
    許容差を決めて初めて射影される。4 桁は既定の 1e-4 のちょうど境界 (``-y, x-y`` のずれが
    1.0e-4) で浮動小数の丸め次第なので、精度を渡す形を正とする。"""
    from tsumugin.site_symmetry import snap_to_special_position

    position = (0.667, 0.333, 0.25)
    assert snap_to_special_position(P63MC, position) == position, "既定の挙動は変えない"
    x, y, z = snap_to_special_position(P63MC, position, coord_error=(0.5e-3, 0.5e-3, 0.5e-2))
    assert (x, y) == (pytest.approx(2 / 3, abs=1e-12), pytest.approx(1 / 3, abs=1e-12))
    assert z == 0.25


def test_topas_symmetry_reexports_the_same_functions():
    """`topas.symmetry` からの既存 import は同じ実体を指す (移設で二重実装にしない)。"""
    from tsumugin import site_symmetry
    from tsumugin.topas import symmetry

    for name in (
        "parse_symop", "site_symmetry_projector", "snap_to_special_position",
        "site_coord_axes", "free_coord_axes", "fixed_coord_axes", "site_symmetry_residual",
    ):
        assert getattr(symmetry, name) is getattr(site_symmetry, name), name


def test_site_symmetry_module_does_not_import_a_backend():
    """バックエンド非依存: GSAS 経路が TOPAS パッケージを引き込まない。"""
    import ast
    from pathlib import Path

    import tsumugin.site_symmetry as module

    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8"))
    imported = {
        node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    assert not any(("topas" in name) or ("GSASII" in name) for name in imported), imported


def test_site_axes_use_the_written_precision():
    """★自由軸・固定軸の判定も、射影と**同じ許容差**で行う (3 桁の 1/3 は 3m サイト)。

    ``(0.333, 0.667, z)`` は既定の 1e-4 では鏡映 ``-y,-x,z`` 上の m サイト (x/y は結束して動ける)
    としか読めない。射影だけ桁数を見て (1/3, 2/3, z) へ載せ、軸判定は m サイトのまま —
    だと、**値が対称で固定される** x/y を「固定」と言えず、座標 esd ``0.0`` の根拠を失う。
    """
    from tsumugin.site_symmetry import site_coord_axes

    position = (0.333, 0.667, 0.25)
    assert site_coord_axes(P63MC, position) == (("z",), ()), "既定の挙動は変えない"
    assert site_coord_axes(P63MC, position, coord_error=(0.5e-3, 0.5e-3, 0.5e-2)) == (
        ("z",), ("x", "y"),
    )
