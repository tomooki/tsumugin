"""Jana2020 .m50 (cell+spacegroup) + .m40 (atoms) → 標準セッティング CIF (GSAS-II 互換)。

M9 CaTeO3 cyclic の初期相 (alpha CaTeO3·H₂O) / 参照相 (delta CaTeO3) を Jana ネイティブ形式から
GSAS-II が読める CIF へ変換する。要点 (実装で判明した教訓):

1. **対称操作は comma 区切り**で pymatgen `SymmOp.from_xyz_str` に渡す (Jana は space 区切り)。
   space 区切りだと誤解釈され全原子が (x,0,0) に潰れて構造因子が壊れる。
2. **標準セッティングへ設定変換**する (`get_conventional_standard_structure`)。Jana の非標準設定
   (P2₁cn 等) は GSAS が拒否する ("space group setting not compatible")。原子は改変せず軸のみ標準化。
   `get_refined_structure` は原子を改変し強度が狂うため使わない。
3. 厳密な Jana 非対称単位原子を対称展開してから標準化する (構造因子を保つ)。

使い方: python jana_to_cif.py <in.m50> <in.m40> <out.cif>
"""
from __future__ import annotations

import re
import sys

from pymatgen.core import Lattice, Structure
from pymatgen.core.operations import SymmOp
from pymatgen.io.cif import CifWriter
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


def _isfloat(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _norm_elem(e: str) -> str:
    known = {"Ca", "Te", "O", "H"}
    if e in known:
        return e
    if e.startswith("Ow"):
        return "O"
    for k in ("Ca", "Te", "O", "H"):
        if e.startswith(k):
            return k
    return e[:2] if e[:2] in known else e[:1]


def parse_m50(path: str):
    """cell / spacegroup / symmetry ops を .m50 から読む。"""
    cell = sg = None
    syms: list[str] = []
    for ln in open(path, encoding="utf-8", errors="replace"):
        t = ln.split()
        if not t:
            continue
        if t[0] == "cell":
            cell = [float(x) for x in t[1:7]]
        elif t[0] == "spgroup":
            sg = (t[1], int(t[2]))
        elif t[0] == "symmetry":
            syms.append(",".join(t[1:]))  # comma 区切り (SymmOp.from_xyz_str 用)
    return cell, sg, syms


def parse_m40_atoms(path: str):
    """.m40 の非対称単位原子 (elem, occ, x, y, z) を読む。各原子 2 行 (座標行 + Uiso 行)。"""
    lines = open(path, encoding="utf-8", errors="replace").read().splitlines()
    atoms = []
    i = 0
    while i < len(lines):
        t = lines[i].split()
        if len(t) >= 7 and re.match(r"^[A-Za-z]", t[0]) and _isfloat(t[3]) and _isfloat(t[4]):
            atoms.append((_norm_elem(re.match(r"^[A-Za-z]+", t[0]).group(0)),
                          float(t[3]), float(t[4]), float(t[5]), float(t[6])))
            i += 2
            continue
        if lines[i].startswith("---") or "s.u. block" in lines[i]:
            break
        i += 1
    return atoms


def convert(m50: str, m40: str, out: str) -> None:
    cell, sg, syms = parse_m50(m50)
    atoms = parse_m40_atoms(m40)
    lat = Lattice.from_parameters(*cell)
    ops = [SymmOp.from_xyz_str(s) for s in syms]
    sp_all, co_all, seen = [], [], set()
    for (sp, _occ, x, y, z) in atoms:
        for op in ops:
            nc = [v % 1.0 for v in op.operate([x, y, z])]
            key = (sp, round(nc[0], 3), round(nc[1], 3), round(nc[2], 3))
            if key in seen:
                continue
            seen.add(key)
            sp_all.append(sp)
            co_all.append(nc)
    st = Structure(lat, sp_all, co_all)
    sga = SpacegroupAnalyzer(st, symprec=0.05)
    std = sga.get_conventional_standard_structure()  # 設定標準化 (原子改変なし)
    CifWriter(std, symprec=0.05).write_file(out)
    print(f"OK {out}: {len(st)} atoms, jana=#{sg[1]} {sg[0]}, std={sga.get_space_group_symbol()}, "
          f"cell_std={[round(x, 3) for x in std.lattice.abc]}")


if __name__ == "__main__":
    convert(sys.argv[1], sys.argv[2], sys.argv[3])
