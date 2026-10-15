"""特殊位置への吸着 — GSAS-II が CIF を読む**前に**原子座標をサイト対称の不変部分空間へ射影する。

GSAS-II は原子のサイト対称と多重度を ``GSASIIspc.SytSym`` で**座標の一致**から決める。CIF の
座標欄が 4 桁だと 1/3 が網から漏れる (2026-10-15 実測: P6₃mc の ``(0.3333, 0.6667, 0)`` が
``('m(110)', 6)``、``0.33333`` なら ``('3m(100)', 2)``)。漏れた原子は一般位置として**多重度
3 倍**で読まれ、精密化は良い Rwp のまま完走する (合成 ZnO 6.37%) — 壊れるのは対称で固定される
軸の esd (0.7・4.5)・結晶化学の GII (~0.5)・組成だけで、Rwp からは見えない。

ここでは `tsumugin.site_symmetry.snap_to_special_position` で射影し、動いた原子だけを書き換えた
CIF の写しを GSAS に渡す。許容差は**書かれた桁数**から決める (:func:`_coord_error`): その桁数では
特殊位置と区別できない点は特殊位置に載せ、区別できる変位 (4 桁で 1/3 から 3e-4) は残す。

入力 CIF は書き換えない。写しは座標トークン以外をバイト単位で保つ (`write_gsas_cif` で
書き直すと異方性 ADP 等の GSAS が読む情報を落とすため)。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np

from ..site_symmetry import snap_to_special_position
from .cif_normalize import _atom_loop_rows, _strip_esd, read_structure_cif

__all__ = ["SnapReport", "snap_cif_special_positions"]

_AXIS_TAGS = ("_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
_NOISE = 1e-12


@dataclass(frozen=True)
class SnapReport:
    """1 相ぶんの吸着の記録 (ledger ``m7_special_position_snap`` の中身)。

    :param status: ``"snapped"`` (写しを渡した) / ``"unchanged"`` (動かす原子なし・元の CIF を
        渡した) / ``"skipped"`` (射影できなかった・元の CIF を渡した。理由は ``reason``)
    :param symop_source: ``"cif"`` (CIF の対称操作ループ) / ``"space_group"`` (CIF に無く
        空間群記号から引いた) / ``None`` (引く前に止まった)
    :param path: GSAS に渡すパス
    """

    phase: str
    status: str
    path: str
    symop_source: str | None = None
    moved: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "status": self.status,
            "symop_source": self.symop_source,
            "moved": [dict(m) for m in self.moved],
            "reason": self.reason,
            "path": self.path,
        }


def _coord_error(token: str) -> float:
    """座標トークンの丸め誤差の上限 (``0.3333`` → ``0.5e-4``)。

    小数 2 桁以下 (``0``・``0.5``・``0.25``) は**厳密値**として扱い 0 を返す — 1/2・1/4 を書く
    のに桁を省くのは普通で、それを ±0.005 の幅と読むと近くの一般位置を誤って吸着する。
    1/3 を 2 桁 (``0.33``) で書く CIF はこの規則では拾えない (既定の許容差 1e-4 のまま)。
    """
    match = re.fullmatch(r"[+-]?\d*\.(\d+)", re.sub(r"\(.*?\)", "", token))
    if match is None:
        return 0.0
    decimals = len(match.group(1))
    return 0.5 * 10.0 ** (-decimals) if decimals >= 3 else 0.0


def _metric(structure) -> np.ndarray:
    """分率座標の計量テンソル G (|Δ|² = Δᵀ·G·Δ, Å²)。"""
    a, b, c = structure.a, structure.b, structure.c
    ca, cb, cg = (math.cos(math.radians(v)) for v in (structure.alpha, structure.beta, structure.gamma))
    return np.array(
        [[a * a, a * b * cg, a * c * cb], [a * b * cg, b * b, b * c * ca], [a * c * cb, b * c * ca, c * c]]
    )


def _format(value: float) -> str:
    return f"{value:.12f}"


def snap_cif_special_positions(
    path: str | Path,
    out_dir: str | Path,
    *,
    phase_name: str,
    space_group_symops: Callable[[str], "tuple[str, ...]"],
) -> SnapReport:
    """CIF の原子を特殊位置へ射影し、GSAS に渡すパスと記録を返す。

    :param space_group_symops: CIF に対称操作ループが無いときに H-M 記号から一般位置を引く
        関数 (GSAS 経路では GSAS-II 自身の ``SpcGroup`` — GSAS が CIF を読むときに作る群と
        同じもの)。例外か空タプルなら ``"skipped"`` として理由を記録する。

    射影しない・できないときは**止めない** — CIF を読むかどうかは GSAS の判断 (読めない CIF は
    GSAS のエラーとしてそのまま上がる)。代わりに ``status="skipped"`` と理由を返す。
    """
    src = Path(path)

    def skipped(reason: str, source: str | None = None) -> SnapReport:
        return SnapReport(phase=phase_name, status="skipped", path=str(src),
                          symop_source=source, reason=reason)

    try:
        structure = read_structure_cif(src)
        # latin-1 は全バイトを 1 文字へ写すので、書き戻しで座標以外のバイトが変わらない。
        raw = src.read_bytes().decode("latin-1")
    except (OSError, ValueError) as exc:
        return skipped(f"CIF を読めない: {type(exc).__name__}: {exc}"[:300])

    pieces = re.split(r"(?<=\n)", raw)
    lines = [p.rstrip("\r\n") for p in pieces]
    if sum(1 for ln in lines if ln.strip() == "_atom_site_label") > 1:
        # 複数 data ブロック: GSAS がどのブロックを読むかをここでは決められない。
        return skipped("atom_site ループが複数ある (どのブロックを GSAS が読むか決められない)")

    if structure.symops:
        symops, source = structure.symops, "cif"
    else:
        source = "space_group"
        try:
            symops = tuple(space_group_symops(structure.spacegroup_hm))
        except Exception as exc:  # noqa: BLE001 — 理由として記録して素通しにする
            return skipped(
                f"CIF に対称操作が無く、空間群 {structure.spacegroup_hm!r} から引けない: "
                f"{type(exc).__name__}: {exc}"[:300],
                source,
            )
        if not symops:
            return skipped(
                f"CIF に対称操作が無く、空間群 {structure.spacegroup_hm!r} から引けない", source
            )

    col, rows = _atom_loop_rows(lines)
    axis_cols = [col[t] for t in _AXIS_TAGS]
    metric = _metric(structure)
    moved: list[dict[str, Any]] = []
    for index, row in rows:
        tokens = [row[k] for k in axis_cols]
        original = tuple(_strip_esd(t) for t in tokens)
        error = tuple(_coord_error(t) for t in tokens)
        snapped = snap_to_special_position(symops, original, coord_error=error)
        delta = np.subtract(snapped, original)
        # 既に特殊位置にある原子 (0.5・0.25) の最小二乗の丸め (~1e-17) を「動いた」と数えない。
        if not np.any(np.abs(delta) > _NOISE):
            continue
        moved.append({
            "label": row[col["_atom_site_label"]],
            "from": list(original),
            "to": list(snapped),
            "shift_frac": [float(d) for d in delta],
            "shift_angstrom": float(math.sqrt(max(delta @ metric @ delta, 0.0))),
        })
        new_row = list(row)
        for k, shift, value in zip(axis_cols, delta, snapped):
            if abs(shift) > _NOISE:  # 動かない軸 (自由軸) は元のトークン (esd 付き) のまま
                new_row[k] = _format(value)
        indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
        ending = pieces[index][len(lines[index]):]
        pieces[index] = indent + " ".join(new_row) + ending

    if not moved:
        return SnapReport(phase=phase_name, status="unchanged", path=str(src), symop_source=source)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", phase_name) or "phase"
    target = out / f"{safe}.special-positions.cif"
    n = 1
    while target.exists():
        n += 1
        target = out / f"{safe}.special-positions-{n}.cif"
    target.write_bytes("".join(pieces).encode("latin-1"))
    return SnapReport(
        phase=phase_name, status="snapped", path=str(target), symop_source=source,
        moved=tuple(moved),
    )
