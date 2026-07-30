"""サイト対称による座標の自由軸判定 (M12) — 純 numpy。

GSAS 経路は ``GSASIIspc.GetCSxinel`` で「その原子のどの座標成分が独立に動けるか」を得ている。
TOPAS には同等の scriptable API が無く、**特殊位置の座標をそのまま解放すると対称性が壊れる**
(実 PbSO4 で座標段の Rwp が 11.1 → 12.1 に悪化し revert された)。

ここでは CIF の対称操作から**サイト対称群**を作り、許される変位方向を線形代数で求める:

1. サイト対称群 ``G = {(R, t) : R·p + t ≡ p (mod 1)}``
2. 許される変位は ``G`` の全 ``R`` で不変なベクトル。射影子 ``P = (1/|G|)·Σ R`` の像が
   その部分空間になる。
3. 軸 ``e_i`` を**独立に**解放してよいのは ``P`` が第 i 行・列で対角 (``P[i,i]≈1`` かつ
   非対角が ``0``) のときだけ。三方晶の ``(x, -x, z)`` のように軸が**結束**している場合は
   1 変数として拘束式を書く必要があるので、v1 では**解放しない** (誤って独立に動かすより安全)。

例: Pnma の Pb (0.188, 1/4, 0.167) は ``x, -y+1/2, z`` で不変 → ``P = diag(1, 0, 1)`` →
x と z のみ解放、y は 1/4 に固定。
"""

from __future__ import annotations

import re
from fractions import Fraction

import numpy as np

__all__ = ["free_coord_axes", "parse_symop", "site_symmetry_projector"]

_AXES = ("x", "y", "z")
_TERM = re.compile(r"([+-]?)\s*(\d+/\d+|\d*\.?\d+)?\s*\*?\s*([xyz])?")


def parse_symop(text: str) -> "tuple[np.ndarray, np.ndarray]":
    """``"1/2-x,1/2+y,z"`` → (回転行列 R, 並進 t)。

    CIF / TOPAS の ``.sg`` 双方の書き方 (``-x+1/2`` と ``1/2-x``) を扱う。
    """
    rotation = np.zeros((3, 3), dtype=float)
    translation = np.zeros(3, dtype=float)
    parts = [p.strip() for p in text.replace(" ", "").split(",")]
    if len(parts) != 3:
        raise ValueError(f"対称操作の成分が 3 つではありません: {text!r}")
    for row, component in enumerate(parts):
        for sign, number, axis in _TERM.findall(component):
            if not number and not axis:
                continue
            factor = -1.0 if sign == "-" else 1.0
            magnitude = float(Fraction(number)) if number else 1.0
            if axis:
                rotation[row, _AXES.index(axis)] += factor * magnitude
            else:
                translation[row] += factor * magnitude
    return rotation, translation


def site_symmetry_projector(
    symops: "tuple[str, ...]", position: "tuple[float, float, float]", *, tol: float = 1e-4
) -> np.ndarray:
    """サイト対称群の射影子 ``P = (1/|G|)·Σ R`` を返す。

    許される変位方向はこの ``P`` の像である (``P·v = v`` なら全 ``R`` で不変)。
    """
    point = np.asarray(position, dtype=float)
    matrices: list[np.ndarray] = []
    for text in symops:
        try:
            rotation, translation = parse_symop(text)
        except ValueError:
            continue
        image = rotation @ point + translation
        # 格子並進を除いて自分自身へ戻るか (mod 1)。
        delta = image - point
        if np.all(np.abs(delta - np.round(delta)) < tol):
            matrices.append(rotation)
    if not matrices:
        return np.eye(3)
    return np.mean(np.stack(matrices, axis=0), axis=0)


def free_coord_axes(
    symops: "tuple[str, ...]",
    position: "tuple[float, float, float]",
    *,
    tol: float = 1e-4,
) -> tuple[str, ...]:
    """独立に解放してよい座標軸 (``"x"``/``"y"``/``"z"``) を返す。

    対称操作が与えられない場合は **空タプル** を返す — 「判定できないので触らない」。
    誤って解放すると Rwp が下がりながら構造が壊れる (対称性の破れは Rwp に現れにくい) ため、
    分からないときは動かさないのが安全側である。
    """
    if not symops:
        return ()
    projector = site_symmetry_projector(symops, position, tol=tol)
    free: list[str] = []
    for index, axis in enumerate(_AXES):
        diagonal = projector[index, index]
        off_row = np.abs(np.delete(projector[index, :], index)).max()
        off_col = np.abs(np.delete(projector[:, index], index)).max()
        # 独立に動かせるのは「自分自身に完全に射影され、他軸と混ざらない」軸だけ。
        if abs(diagonal - 1.0) < 1e-6 and off_row < 1e-6 and off_col < 1e-6:
            free.append(axis)
    return tuple(free)
