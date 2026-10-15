"""サイト対称による特殊位置の扱い — バックエンド非依存 (純 numpy)。

CIF の対称操作から**サイト対称群**を作り、許される変位方向を線形代数で求める:

1. サイト対称群 ``G = {(R, t) : R·p + t ≡ p (mod 1)}``
2. 許される変位は ``G`` の全 ``R`` で不変なベクトル。射影子 ``P = (1/|G|)·Σ R`` の像が
   その部分空間になる。
3. 軸 ``e_i`` を**独立に**解放してよいのは ``P`` が第 i 行・列で対角 (``P[i,i]≈1`` かつ
   非対角が ``0``) のときだけ。三方晶の ``(x, -x, z)`` のように軸が**結束**している場合は
   1 変数として拘束式を書く必要があるので、v1 では**解放しない** (誤って独立に動かすより安全)。

例: Pnma の Pb (0.188, 1/4, 0.167) は ``x, -y+1/2, z`` で不変 → ``P = diag(1, 0, 1)`` →
x と z のみ解放、y は 1/4 に固定。

元は TOPAS 経路 (`topas.symmetry`) にあったが、GSAS 経路も同じ射影を要する
(:func:`snap_to_special_position` の「なぜ必要か」) ので、どちらのバックエンドも import
しないここへ移した。`topas.symmetry` は同じ実体を再エクスポートする。
"""

from __future__ import annotations

import re
from fractions import Fraction

import numpy as np

__all__ = [
    "fixed_coord_axes",
    "free_coord_axes",
    "parse_symop",
    "site_coord_axes",
    "site_symmetry_projector",
    "site_symmetry_residual",
    "snap_to_special_position",
]

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


def _site_symmetry_images(
    symops: "tuple[str, ...]",
    point: np.ndarray,
    tol: float,
    coord_error: "tuple[float, float, float] | None" = None,
) -> "list[tuple[np.ndarray, np.ndarray]]":
    """サイト対称群 ``G = {(R, t) : R·p + t ≡ p (mod 1)}`` の (R, 像) を集める。

    像は**格子並進を解いて** ``p`` の最近接になるよう戻す (``mod 1`` の折り返しをそのまま
    平均すると 0 と 1 が混ざって重心がずれるため)。

    ``coord_error`` (各軸の座標の丸め誤差の上限) を渡すと、成分 i の許容差を
    ``max(tol, Σ_j |(R − I)_ij|·coord_error_j)`` に広げる — 書かれた桁数では特殊位置と
    区別できない点を、区別できないとおりに扱う (:func:`snap_to_special_position`)。
    """
    found: list[tuple[np.ndarray, np.ndarray]] = []
    error = None if coord_error is None else np.asarray(coord_error, dtype=float)
    for text in symops:
        try:
            rotation, translation = parse_symop(text)
        except ValueError:
            continue
        image = rotation @ point + translation
        delta = image - point
        if error is None:
            limit: "float | np.ndarray" = tol
        else:
            # 境界 (ちょうど丸め誤差ぶん) は特殊位置側に含める — 浮動小数の誤差で落とさない。
            limit = np.maximum(tol, np.abs(rotation - np.eye(3)) @ error * (1.0 + 1e-9))
        if np.all(np.abs(delta - np.round(delta)) < limit):
            found.append((rotation, image - np.round(delta)))
    return found


def site_symmetry_projector(
    symops: "tuple[str, ...]", position: "tuple[float, float, float]", *, tol: float = 1e-4
) -> np.ndarray:
    """サイト対称群の射影子 ``P = (1/|G|)·Σ R`` を返す。

    許される変位方向はこの ``P`` の像である (``P·v = v`` なら全 ``R`` で不変)。
    """
    point = np.asarray(position, dtype=float)
    matrices = [rotation for rotation, _ in _site_symmetry_images(symops, point, tol)]
    if not matrices:
        return np.eye(3)
    return np.mean(np.stack(matrices, axis=0), axis=0)


def snap_to_special_position(
    symops: "tuple[str, ...]",
    position: "tuple[float, float, float]",
    *,
    tol: float = 1e-4,
    coord_error: "tuple[float, float, float] | None" = None,
) -> "tuple[float, float, float]":
    """座標をサイト対称群の**不変部分空間へ射影**する (機械精度で特殊位置に載せる)。

    厳密な特殊位置は ``(R − I)·p = −t`` を全操作について満たす点なので、これを**最小ノルム
    最小二乗**で解いて元の座標からの変位が最小になる解を採る。``0.333333`` →
    ``0.3333333333333333``。有理数の当てずっぽう (「1/3 に近いから 1/3」) ではなく対称操作
    そのものから導くため、``(x, 2x, 1/4)`` のような**軸が結束した拘束**もそのまま正しく扱える。

    軌道の重心 (=不動点) を採る手もあるが、それは対称操作の集合が**群として閉じている**ことを
    前提にする。最小二乗ならその前提を要らない — CIF が一般位置を一部しか列挙していなくても
    生成される群の不動点へ落ちる。

    なぜ必要か: どちらのバックエンドも多重度を**座標の一致**で決め、外れると特殊位置が一般位置へ
    化けて**単位胞に存在しない原子が増えたまま完走する** (Rwp は良いまま)。

    - TOPAS の許容差は約 1e-8 (`topas.symmetry.SITE_MERGE_TOLERANCE`)。CIF の 5-8 桁では
      1/3 が届かない。
    - GSAS-II の ``GSASIIspc.SytSym`` も同じ種類の判定で、**4 桁の 1/3 を取りこぼす**
      (2026-10-15 実測: P6₃mc の ``(0.3333, 0.6667, 0)`` が ``('m(110)', 6)``、
      ``0.33333`` なら ``('3m(100)', 2)``)。合成 ZnO で Rwp 6.37% のまま、対称で固定される
      軸の esd が 0.7・4.5、正しい構造の GII が ~0.5、組成が 3 倍になった。以前この docstring は
      「GSAS-II は特殊位置を拘束として扱うので問題にならない」と書いていたが、**誤り**である。

    ``coord_error`` は各軸の座標の丸め誤差の上限 (4 桁なら ``0.5e-4``)。渡すと、操作ごとの
    許容差を「その桁数では特殊位置と区別できない」範囲まで広げる (:func:`_site_symmetry_images`)。
    4 桁の 1/3 は既定の ``tol=1e-4`` ちょうどの境界に落ち (``-y, x-y`` の像のずれが
    ``1.0e-4``)、拾えるかは浮動小数の丸め次第、3 桁 (``0.667``) は既定では拾えない。
    渡さなければ従来どおり ``tol`` だけで判定する。

    自由軸 (:func:`free_coord_axes` が返す軸) は射影で動かない — 変位が ``range(Aᵀ)`` =
    ``null(A)`` (許される変位方向) の直交補空間に入るという最小ノルム解の性質による。どちらも
    **同じサイト対称群**から出るので、基準がずれて矛盾することはない。対称操作が無い /
    サイト対称群が単位元だけのときは座標をそのまま返す。
    """
    if not symops:
        return position
    point = np.asarray(position, dtype=float)
    images = _site_symmetry_images(symops, point, tol, coord_error)
    if len(images) <= 1:
        return position
    # A·δ = r₀ (r₀ = 各操作の残差) を最小ノルム最小二乗で解く。
    matrix = np.concatenate([rotation - np.eye(3) for rotation, _ in images], axis=0)
    residual = np.concatenate([point - image for _, image in images], axis=0)
    shift, *_ = np.linalg.lstsq(matrix, residual, rcond=None)
    snapped = point + shift
    return (float(snapped[0]), float(snapped[1]), float(snapped[2]))


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
    return site_coord_axes(symops, position, tol=tol)[0]


def fixed_coord_axes(
    symops: "tuple[str, ...]",
    position: "tuple[float, float, float]",
    *,
    tol: float = 1e-4,
) -> tuple[str, ...]:
    """サイト対称で**値が厳密に固定される**座標軸を返す (GSAS の ``GetCSxinel`` の ``0``)。

    許される変位はすべて ``P`` の像 ``P·w`` なので、その第 i 成分が常に 0 になる
    (= ``P`` の第 i 行が 0) とき、かつそのときだけ軸 i の値は動けない。
    :func:`free_coord_axes` の補集合**ではない** — 三方晶の ``(x, x, 0)`` の x/y のように
    他軸と結束した軸は独立に解放できないだけで動く。固定と名乗ると座標 esd が ``0.0``
    (「厳密にこの値」) を主張してしまう。

    対称操作が無ければ空 — 判定できないものを固定とは言わない。
    """
    return site_coord_axes(symops, position, tol=tol)[1]


def site_coord_axes(
    symops: "tuple[str, ...]",
    position: "tuple[float, float, float]",
    *,
    tol: float = 1e-4,
) -> "tuple[tuple[str, ...], tuple[str, ...]]":
    """``(自由軸, 固定軸)`` を **1 回の射影子計算**で返す (:func:`free_coord_axes` /
    :func:`fixed_coord_axes` の本体)。

    射影子は全対称操作をパースして作るので安くない (192 操作 × 20 原子で 1 相 ~70 ms)。
    `backends.topas` は simulate/refine のたびに相を組み直すので、サイトごとに 2 回作らない。
    """
    if not symops:
        return (), ()
    projector = site_symmetry_projector(symops, position, tol=tol)
    free: list[str] = []
    fixed: list[str] = []
    for index, axis in enumerate(_AXES):
        row = projector[index, :]
        diagonal = projector[index, index]
        off_row = np.abs(np.delete(row, index)).max()
        off_col = np.abs(np.delete(projector[:, index], index)).max()
        # 独立に動かせるのは「自分自身に完全に射影され、他軸と混ざらない」軸だけ。
        if abs(diagonal - 1.0) < 1e-6 and off_row < 1e-6 and off_col < 1e-6:
            free.append(axis)
        # 値が動けないのは、許される変位の第 i 成分が常に 0 (= 行が 0) のときだけ。
        if np.abs(row).max() < 1e-6:
            fixed.append(axis)
    return tuple(free), tuple(fixed)



def site_symmetry_residual(
    symops: "tuple[str, ...]",
    position: "tuple[float, float, float]",
    *,
    tol: float = 1e-4,
) -> float:
    """サイト対称群の各操作で写した点と元の点との**最大ずれ** (格子並進を除く)。

    これは `topas.symmetry.SITE_MERGE_TOLERANCE` で TOPAS が測っている量そのものである。
    ``SITE_MERGE_TOLERANCE`` を超えると TOPAS は写像先を別原子とみなし、特殊位置が
    一般位置へ展開されて**単位胞に存在しない原子が増える** (#172)。

    :func:`snap_to_special_position` を通した座標ならこの残差は機械精度に落ちるので、
    「吸着が効いているか」を tc.exe を起動せずに検算できる。
    """
    point = np.asarray(position, dtype=float)
    images = _site_symmetry_images(symops, point, tol)
    if not images:
        return 0.0
    return float(max(np.abs(image - point).max() for _, image in images))
