"""構造 CIF の正規化 (autorietveld.cif_normalize)。

Z-Rietveld などが書き出す checkCIF 準拠 (複数 ``data_`` ブロック・esd 付き数値・幾何パラメータ表) の CIF
は GSAS-II の CIF リーダが受け付けないことがある (空の ``data_global`` を先に拾う・validation error)。本
モジュールは CIF から**セル + 空間群 + 原子サイト**のみを抽出し、GSAS-II が確実に読める**単一 data ブロック
の最小 CIF** へ正規化する。numpy 非依存の純 text 処理で決定論的。

M9 教訓 (Jana→CIF は標準セッティング化が必須) と同型: 供給元 CIF の表現差を吸収し GSAS 取り込みを安定化。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "Atom",
    "Structure",
    "normalize_cif_for_gsas",
    "read_structure_cif",
    "write_gsas_cif",
]

_B_TO_U = 1.0 / (8.0 * math.pi**2)


@dataclass(frozen=True)
class Atom:
    """原子サイト 1 個 (最小 CIF の 1 行)。🔵"""

    label: str
    type_symbol: str
    x: float
    y: float
    z: float
    occ: float
    uiso: float


@dataclass(frozen=True)
class Structure:
    """最小構造 (セル + 空間群 + 原子)。🔵"""

    a: float
    b: float
    c: float
    alpha: float
    beta: float
    gamma: float
    spacegroup_hm: str
    it_number: int | None
    atoms: tuple[Atom, ...]


def _strip_esd(token: str) -> float:
    """``6.95976(2)`` / ``-0.2(19)`` の esd を捨てて float 化。"""
    return float(re.sub(r"\(.*?\)", "", token))


_CELL_TAGS = {
    "a": "_cell_length_a",
    "b": "_cell_length_b",
    "c": "_cell_length_c",
    "alpha": "_cell_angle_alpha",
    "beta": "_cell_angle_beta",
    "gamma": "_cell_angle_gamma",
}
_HM_TAGS = ("_space_group_name_H-M_alt", "_symmetry_space_group_name_H-M")
_IT_TAGS = ("_space_group_IT_number", "_symmetry_Int_Tables_number")


def _scalar(lines: list[str], tags: tuple[str, ...]) -> str | None:
    """指定タグ (複数候補) の最初のスカラ値を返す (引用符除去)。"""
    for ln in lines:
        parts = ln.split(None, 1)
        if len(parts) == 2 and parts[0] in tags:
            return parts[1].strip().strip("'\"")
    return None


def read_structure_cif(path: str | Path) -> Structure:
    """CIF からセル・空間群・原子サイトを読み :class:`Structure` を返す。🔵

    ``_atom_site_U_iso_or_equiv`` / ``_atom_site_B_iso_or_equiv`` の双方に対応 (B は U=B/8π² 換算)。
    占有率列が無ければ 1.0。type_symbol 列が無ければラベル先頭の英字を採る。

    Raises:
        ValueError: セル定数 / atom_site ループが読めないとき。
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    cell: dict[str, float] = {}
    for ln in lines:
        parts = ln.split()
        if len(parts) >= 2:
            for name, tag in _CELL_TAGS.items():
                if parts[0] == tag:
                    cell.setdefault(name, _strip_esd(parts[1]))
    if set(cell) != set(_CELL_TAGS):
        raise ValueError(f"CIF にセル定数が不足しています: {sorted(set(_CELL_TAGS) - set(cell))}")

    hm = _scalar(lines, _HM_TAGS) or "P 1"
    it_raw = _scalar(lines, _IT_TAGS)
    it_number = int(float(it_raw)) if it_raw is not None else None

    atoms = _read_atom_loop(lines)
    if not atoms:
        raise ValueError("CIF から原子サイトを読めませんでした。")
    return Structure(
        a=cell["a"], b=cell["b"], c=cell["c"],
        alpha=cell["alpha"], beta=cell["beta"], gamma=cell["gamma"],
        spacegroup_hm=hm, it_number=it_number, atoms=tuple(atoms),
    )


def _read_atom_loop(lines: list[str]) -> list[Atom]:
    """atom_site ループを走査し :class:`Atom` 列へ。"""
    label_idx = next((i for i, ln in enumerate(lines) if ln.strip() == "_atom_site_label"), None)
    if label_idx is None:
        raise ValueError("CIF に _atom_site_label ループが見つかりません。")
    start = label_idx
    while start > 0 and lines[start - 1].strip().startswith("_atom_site"):
        start -= 1
    tags: list[str] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("_atom_site"):
        tags.append(lines[i].strip())
        i += 1
    col = {t: k for k, t in enumerate(tags)}
    need = ("_atom_site_fract_x", "_atom_site_fract_y", "_atom_site_fract_z")
    if any(t not in col for t in need):
        raise ValueError("atom_site ループに分率座標列がありません。")

    atoms: list[Atom] = []
    for ln in lines[i:]:
        s = ln.strip()
        # 空行はサイト行の区切りとして許容し読み飛ばす (一部 CIF ライタは行間に空行を挿む)。
        # ループ終端は構造トークン (loop_/_tag/#/;) でのみ判定する。
        if not s:
            continue
        if s.startswith(("#", "loop_", "_", ";")):
            break
        row = s.split()
        if len(row) < len(tags):
            continue
        label = row[col["_atom_site_label"]]
        if "_atom_site_type_symbol" in col:
            tsym = row[col["_atom_site_type_symbol"]]
        else:
            m = re.match(r"[A-Za-z]+", label)
            tsym = m.group(0) if m else label
        occ = _strip_esd(row[col["_atom_site_occupancy"]]) if "_atom_site_occupancy" in col else 1.0
        if "_atom_site_U_iso_or_equiv" in col:
            uiso = _strip_esd(row[col["_atom_site_U_iso_or_equiv"]])
        elif "_atom_site_B_iso_or_equiv" in col:
            uiso = _strip_esd(row[col["_atom_site_B_iso_or_equiv"]]) * _B_TO_U
        else:
            uiso = 0.025
        atoms.append(
            Atom(
                label=label,
                type_symbol=tsym,
                x=_strip_esd(row[col["_atom_site_fract_x"]]),
                y=_strip_esd(row[col["_atom_site_fract_y"]]),
                z=_strip_esd(row[col["_atom_site_fract_z"]]),
                occ=occ,
                uiso=uiso,
            )
        )
    return atoms


def write_gsas_cif(structure: Structure, out_path: str | Path, *, phase_name: str = "phase") -> Path:
    """:class:`Structure` を GSAS-II が確実に読む単一ブロック最小 CIF へ書き出す。🔵"""
    sg = structure.spacegroup_hm
    lines = [
        f"data_{re.sub(r'[^A-Za-z0-9_]', '_', phase_name)}",
        f"_cell_length_a {structure.a:.6f}",
        f"_cell_length_b {structure.b:.6f}",
        f"_cell_length_c {structure.c:.6f}",
        f"_cell_angle_alpha {structure.alpha:.6f}",
        f"_cell_angle_beta {structure.beta:.6f}",
        f"_cell_angle_gamma {structure.gamma:.6f}",
        f'_symmetry_space_group_name_H-M "{sg}"',
    ]
    if structure.it_number is not None:
        lines.append(f"_symmetry_Int_Tables_number {structure.it_number}")
    lines += [
        "loop_",
        " _atom_site_label",
        " _atom_site_type_symbol",
        " _atom_site_fract_x",
        " _atom_site_fract_y",
        " _atom_site_fract_z",
        " _atom_site_occupancy",
        " _atom_site_U_iso_or_equiv",
    ]
    for at in structure.atoms:
        lines.append(
            f"{at.label} {at.type_symbol} {at.x:.5f} {at.y:.5f} {at.z:.5f} "
            f"{at.occ:.4f} {at.uiso:.5f}"
        )
    out = Path(out_path)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def normalize_cif_for_gsas(
    in_path: str | Path, out_path: str | Path, *, phase_name: str = "phase"
) -> Path:
    """供給元 CIF を GSAS-II 向け最小 CIF へ正規化して書き出す (read+write の合成)。🔵"""
    return write_gsas_cif(read_structure_cif(in_path), out_path, phase_name=phase_name)
