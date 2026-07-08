"""D₂O の重水素を水 O サイトへ幾何配置する (autorietveld.deuterium)。

D₂O 置換試料の中性子 Rietveld では、水素 (実際は重水素 D) を明示的にモデル化する必要がある。本モジュールは
CIF の水 O サイト (例 O1/O3/Ow) それぞれに、O–D≈0.96 Å・D–O–D≈104.5° の幾何で **D を 2 個**種配置した
新しい CIF を書き出す。配向は無秩序チャネル水では平均的に等方だが、決定論的な種配向を与えて中性子
Rietveld で座標を解放する (占有率は親 O に等値拘束する = ``DeuteriumSite`` として返し engine が制約化)。

構造 CIF の読み書きは :mod:`tsumugin.autorietveld.cif_normalize` に委譲し、出力は GSAS-II が確実に読める
最小 CIF になる。frac↔cart は結晶標準セッティング (a∥x) の直交化行列で行う。numpy-only。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from tsumugin.autorietveld.cif_normalize import (
    Atom,
    read_structure_cif,
    write_gsas_cif,
)

__all__ = [
    "DeuteriumSite",
    "equiv_groups_from_sites",
    "frac_to_cart_matrix",
    "place_d2o",
]


@dataclass(frozen=True)
class DeuteriumSite:
    """種配置した D サイト 1 個の記述 (占有率拘束の入力)。🔵

    :param label: 新規 D サイトのラベル (例 ``"DO11"``)
    :param parent_label: 由来する水 O サイトのラベル (例 ``"O1"``)
    :param frac: 分率座標 ``(x, y, z)``
    :param occupancy: 初期占有率 (親 O と等値)
    """

    label: str
    parent_label: str
    frac: tuple[float, float, float]
    occupancy: float


def equiv_groups_from_sites(
    sites: tuple[DeuteriumSite, ...],
) -> tuple[tuple[str, ...], ...]:
    """``DeuteriumSite`` 列から占有率等値グループ ``(親O, D1, D2, ...)`` を親ごとに組む。🔵

    ``PhaseSpec.occupancy_equiv_groups`` にそのまま渡し、D の占有率を親水 O に連動 (1 変数化) させる。
    親ラベルの初出順を保つ (決定論)。
    """
    order: list[str] = []
    by_parent: dict[str, list[str]] = {}
    for s in sites:
        if s.parent_label not in by_parent:
            by_parent[s.parent_label] = [s.parent_label]
            order.append(s.parent_label)
        by_parent[s.parent_label].append(s.label)
    return tuple(tuple(by_parent[p]) for p in order)


def frac_to_cart_matrix(
    a: float, b: float, c: float, alpha: float, beta: float, gamma: float
) -> np.ndarray:
    """セル定数 (長さ Å・角度 deg) から分率→直交座標の 3×3 行列を返す (a∥x 標準)。🔵

    ``cart = M @ frac`` (列が結晶軸ベクトル)。逆行列で ``frac = inv(M) @ cart``。
    """
    al, be, ga = (math.radians(x) for x in (alpha, beta, gamma))
    cos_al, cos_be, cos_ga = math.cos(al), math.cos(be), math.cos(ga)
    sin_ga = math.sin(ga)
    vol = math.sqrt(
        max(1.0 - cos_al**2 - cos_be**2 - cos_ga**2 + 2.0 * cos_al * cos_be * cos_ga, 1e-12)
    )
    return np.array(
        [
            [a, b * cos_ga, c * cos_be],
            [0.0, b * sin_ga, c * (cos_al - cos_be * cos_ga) / sin_ga],
            [0.0, 0.0, c * vol / sin_ga],
        ],
        dtype=float,
    )


def place_d2o(
    structure_path: str | Path,
    water_labels: list[str] | tuple[str, ...],
    out_path: str | Path,
    *,
    od_distance: float = 0.96,
    dod_angle: float = 104.5,
    uiso: float | None = None,
    phase_name: str = "phase",
) -> tuple[Path, tuple[DeuteriumSite, ...]]:
    """CIF の水 O サイトへ D を 2 個ずつ幾何配置した GSAS 向け最小 CIF を書き出す。🔵

    :param structure_path: 入力 CIF (水 O を含むモデル)
    :param water_labels: D を付ける水 O サイトのラベル列 (例 ``["O1", "O3", "Ow"]``)
    :param out_path: 出力 CIF パス (正規化された最小 CIF)
    :param od_distance: O–D 距離 [Å]
    :param dod_angle: D–O–D 角 [deg]
    :param uiso: D の Uiso 初期値 (None なら親 O の Uiso を流用)
    :param phase_name: 出力 CIF の data ブロック名
    :returns: ``(出力 CIF パス, 配置した DeuteriumSite のタプル)``

    Raises:
        ValueError: 指定した水ラベルが atom_site に見つからないとき。
    """
    struct = read_structure_cif(structure_path)
    mat = frac_to_cart_matrix(
        struct.a, struct.b, struct.c, struct.alpha, struct.beta, struct.gamma
    )
    inv = np.linalg.inv(mat)
    by_label = {at.label: at for at in struct.atoms}

    # 種配向: 直交系で bisector=+z, 面内 perp=+x (無秩序水は decision-free で決定論的に固定)。
    half = math.radians(dod_angle / 2.0)
    bisector = np.array([0.0, 0.0, 1.0])
    perp = np.array([1.0, 0.0, 0.0])
    dirs = (
        math.cos(half) * bisector + math.sin(half) * perp,
        math.cos(half) * bisector - math.sin(half) * perp,
    )

    new_atoms = list(struct.atoms)
    d_sites: list[DeuteriumSite] = []
    for parent in water_labels:
        if parent not in by_label:
            raise ValueError(f"水ラベル {parent!r} が atom_site に見つかりません。")
        po = by_label[parent]
        o_cart = mat @ np.array([po.x, po.y, po.z])
        d_uiso = uiso if uiso is not None else po.uiso
        for n, direction in enumerate(dirs, start=1):
            d_frac = inv @ (o_cart + od_distance * direction)
            label = f"D{parent}{n}"
            new_atoms.append(
                Atom(
                    label=label,
                    type_symbol="D",
                    x=float(d_frac[0]),
                    y=float(d_frac[1]),
                    z=float(d_frac[2]),
                    occ=po.occ,
                    uiso=d_uiso,
                )
            )
            d_sites.append(
                DeuteriumSite(
                    label=label,
                    parent_label=parent,
                    frac=(float(d_frac[0]), float(d_frac[1]), float(d_frac[2])),
                    occupancy=po.occ,
                )
            )

    out = write_gsas_cif(
        replace(struct, atoms=tuple(new_atoms)), out_path, phase_name=phase_name
    )
    return out, tuple(d_sites)
