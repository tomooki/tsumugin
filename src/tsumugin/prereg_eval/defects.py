"""P0 §6.3: 出発モデルに入れる欠陥 — `cif_normalize.Structure` への純関数 (numpy だけ)。

真値の側に入れる欠陥 (欠落相 #5・ゼロ点 #7・選択配向 #10) と、相の指定で表す欠陥 (副相の格子の凍結 #8 の凍結) は
パターンの生成と事例の組み立てで扱う。ここは出発構造の CIF を作り替えるものだけ。

- 原子の変位 (#4) は**一般位置の原子にだけ**使う (特殊位置の原子を任意の向きに動かすと多重度が変わり、
  「欠陥」ではなく別の構造になる)。どの原子に入れるかは事例の定義が決める。
- 格子の伸縮 (#6) は、元の格子で等しい軸を別々に伸ばすことを拒む (結晶系が変わる)。
"""

from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from ..autorietveld.cif_normalize import Structure

__all__ = [
    "displace_atom",
    "drop_atom",
    "lattice_matrix",
    "scale_cell",
    "shift_mixed_ratio",
    "swap_site_elements",
    "translate_along",
]


def lattice_matrix(s: Structure) -> np.ndarray:
    """行が格子ベクトル (Å) の 3×3。a を x 軸、b を xy 面に置く標準の向き。"""
    al, be, ga = (math.radians(v) for v in (s.alpha, s.beta, s.gamma))
    ax = np.array([s.a, 0.0, 0.0])
    bx = np.array([s.b * math.cos(ga), s.b * math.sin(ga), 0.0])
    cx = s.c * math.cos(be)
    cy = s.c * (math.cos(al) - math.cos(be) * math.cos(ga)) / math.sin(ga)
    cz = math.sqrt(max(s.c**2 - cx**2 - cy**2, 0.0))
    return np.array([ax, bx, [cx, cy, cz]])


def _find(s: Structure, label: str) -> int:
    for i, at in enumerate(s.atoms):
        if at.label == label:
            return i
    raise KeyError(label)


def swap_site_elements(s: Structure, label_a: str, label_b: str) -> Structure:
    """#1 席の元素の取り違え: 2 つの席の元素を入れ替える (位置・占有率は変えない)。"""
    i, j = _find(s, label_a), _find(s, label_b)
    atoms = list(s.atoms)
    atoms[i] = replace(atoms[i], type_symbol=s.atoms[j].type_symbol)
    atoms[j] = replace(atoms[j], type_symbol=s.atoms[i].type_symbol)
    return replace(s, atoms=tuple(atoms))


def drop_atom(s: Structure, label: str) -> Structure:
    """#2 原子の欠落。"""
    i = _find(s, label)
    return replace(s, atoms=s.atoms[:i] + s.atoms[i + 1:])


def shift_mixed_ratio(s: Structure, label_a: str, label_b: str, delta: float) -> Structure:
    """#3 混合占有の比の誤り: ``label_a`` に ``delta`` を足し ``label_b`` から引く (和は保つ)。"""
    i, j = _find(s, label_a), _find(s, label_b)
    oa, ob = s.atoms[i].occ + delta, s.atoms[j].occ - delta
    if not (0.0 <= oa <= 1.0 and 0.0 <= ob <= 1.0):
        raise ValueError(f"占有率が [0, 1] を出る: {label_a}={oa}, {label_b}={ob}")
    atoms = list(s.atoms)
    atoms[i] = replace(atoms[i], occ=oa)
    atoms[j] = replace(atoms[j], occ=ob)
    return replace(s, atoms=tuple(atoms))


def displace_atom(s: Structure, label: str, distance: float, rng: np.random.Generator) -> Structure:
    """#4 1 原子の変位: 乱数の向きに ``distance`` Å だけ動かす (一般位置の原子にだけ使う)。"""
    i = _find(s, label)
    v = rng.normal(size=3)
    v = v / np.linalg.norm(v) * float(distance)
    dfrac = v @ np.linalg.inv(lattice_matrix(s))
    at = s.atoms[i]
    atoms = list(s.atoms)
    atoms[i] = replace(at, x=at.x + float(dfrac[0]), y=at.y + float(dfrac[1]), z=at.z + float(dfrac[2]))
    return replace(s, atoms=tuple(atoms))


def scale_cell(s: Structure, factors: tuple[float, float, float]) -> Structure:
    """#6 / #8 格子の誤差: a, b, c をそれぞれ伸縮する。元で等しい軸を別々に伸ばすことは拒む。"""
    lengths = (s.a, s.b, s.c)
    for i in range(3):
        for j in range(i + 1, 3):
            if math.isclose(lengths[i], lengths[j], rel_tol=1e-9) and not math.isclose(factors[i], factors[j]):
                raise ValueError("元の格子で等しい軸を別々に伸ばすと結晶系が変わる")
    return replace(s, a=s.a * factors[0], b=s.b * factors[1], c=s.c * factors[2])


def translate_along(s: Structure, axis: str, delta: float) -> Structure:
    """#9 極性方向の並進: 全原子を軸 ``axis`` に沿って ``delta`` (分率) だけ動かす。"""
    k = "xyz".index(axis)
    atoms = []
    for at in s.atoms:
        xyz = [at.x, at.y, at.z]
        xyz[k] = (xyz[k] + delta) % 1.0
        atoms.append(replace(at, x=xyz[0], y=xyz[1], z=xyz[2]))
    return replace(s, atoms=tuple(atoms))
