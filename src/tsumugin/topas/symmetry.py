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
from pathlib import Path

import numpy as np

__all__ = [
    "ensure_symops",
    "free_coord_axes",
    "parse_symop",
    "read_sg_symops",
    "site_symmetry_projector",
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


# ---------------------------------------------------------------- Sg/*.sg からの補完

_XYZS_BLOCK = re.compile(r"xyzs\s*\{(.*?)\}", re.DOTALL)


def read_sg_symops(space_group: str, home: "Path | None" = None) -> "tuple[str, ...]":
    """TOPAS が生成した ``Sg/<sg>.sg`` から対称操作を読む (無ければ空タプル)。

    ``Sg/`` は **sgcom6.exe がオンデマンドで生成するキャッシュ**ディレクトリで、
    ``xyzs { x, y, z / -x, y+1/2, -z / … }`` の形で一般位置を列挙している。**CIF が対称操作を
    持たない場合の権威的な供給元**である (空間群記号から自前で展開するより確実)。
    """
    from .availability import topas_home

    base = home or topas_home()
    if base is None:
        return ()
    # ファイル名は H-M 記号を小文字にして空白を除いたもの (実測: Pnma → pnma.sg)。
    name = re.sub(r"\s+", "", space_group).lower()
    path = Path(base) / "Sg" / f"{name}.sg"
    if not path.is_file():
        return ()
    match = _XYZS_BLOCK.search(path.read_text(encoding="utf-8", errors="replace"))
    if match is None:
        return ()
    ops = [line.strip() for line in match.group(1).splitlines()]
    return tuple(op for op in ops if op and op.count(",") == 2)


def ensure_symops(
    space_group: str, symops: "tuple[str, ...]", *, generate: bool = True
) -> "tuple[str, ...]":
    """対称操作を確保する。CIF 由来があればそれを、無ければ TOPAS の ``Sg/`` から補完する。

    ``Sg/<sg>.sg`` がまだ生成されていない場合、``generate=True`` なら**空間群だけを宣言した
    最小 INP を 1 回流して** TOPAS に生成させる (sgcom6 は tc.exe 経由でしか呼べない)。
    確保できなければ空タプルを返し、呼び出し側は「座標を解放しない」を選ぶ。
    """
    if symops:
        return symops
    found = read_sg_symops(space_group)
    if found or not generate:
        return found
    try:
        _generate_sg_file(space_group)
    except Exception:  # noqa: BLE001 — 生成できなくても致命ではない (座標を解放しないだけ)
        return ()
    return read_sg_symops(space_group)


def _generate_sg_file(space_group: str) -> None:
    """空間群だけを宣言した最小 INP を流し、TOPAS に ``Sg/<sg>.sg`` を生成させる。"""
    import tempfile

    from .driver import run_tc

    with tempfile.TemporaryDirectory(prefix="tsumugin-topas-sg-") as tmp:
        work = Path(tmp)
        (work / "sgprobe.xye").write_text(
            "\n".join(f"{10.0 + 0.05 * i:.4f} 1.0 1.0" for i in range(200)) + "\n",
            encoding="utf-8",
        )
        inp = (
            "r_wp 0\n"
            "iters 0\n"
            'xdd "sgprobe.xye"\n'
            "   bkg 0\n"
            "   str\n"
            f"      space_group {space_group}\n"
            "      a 5 b 5 c 5\n"
            "      site A x 0 y 0 z 0 occ C 1 beq 1\n"
            "      scale 0.0001\n"
        )
        run_tc(inp, workdir=work, basename="sgprobe", timeout=120.0)
