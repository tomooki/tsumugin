"""D₂O の重水素を水 O サイトへ幾何配置する (autorietveld.deuterium)。

D₂O 置換試料の中性子 Rietveld では、水素 (実際は重水素 D) を明示的にモデル化する必要がある。本モジュールは
CIF の水 O サイト (例 O1/O3/Ow) それぞれに、O–D≈0.96 Å・D–O–D≈104.5° の幾何で **D を 2 個**種配置した
新しい CIF を書き出す。配向は無秩序チャネル水では平均的に等方だが、決定論的な種配向を与えて中性子
Rietveld で座標を解放する (占有率は親 O に等値拘束する = ``DeuteriumSite`` として返し engine が制約化)。

numpy-only。CIF は素の text 操作で読み書きする (pymatgen は元素 "D" を扱えないため使わない)。frac→cart は
結晶標準セッティング (a∥x) の直交化行列で行う。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = [
    "DeuteriumSite",
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


_CELL_KEYS = {
    "a": "_cell_length_a",
    "b": "_cell_length_b",
    "c": "_cell_length_c",
    "alpha": "_cell_angle_alpha",
    "beta": "_cell_angle_beta",
    "gamma": "_cell_angle_gamma",
}


def _strip_esd(token: str) -> float:
    """``6.95976(2)`` のような esd 付き数値を float 化する (括弧以降を捨てる)。"""
    return float(re.sub(r"\(.*\)", "", token))


def _read_cell(lines: list[str]) -> dict[str, float]:
    """CIF 行から 6 セル定数を読む。"""
    out: dict[str, float] = {}
    for ln in lines:
        parts = ln.split()
        if len(parts) >= 2:
            for name, key in _CELL_KEYS.items():
                if parts[0] == key:
                    out[name] = _strip_esd(parts[1])
    missing = set(_CELL_KEYS) - set(out)
    if missing:
        raise ValueError(f"CIF にセル定数が不足しています: {sorted(missing)}")
    return out


def _find_atom_loop(lines: list[str]) -> tuple[int, list[str], int, int]:
    """atom_site loop のヘッダ列・データ行範囲を返す ``(header_start, tags, data_start, data_end)``。

    data_end は最後のデータ行の次のインデックス (挿入位置)。
    """
    # _atom_site_label を含む loop_ ヘッダを探す。
    label_idx = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "_atom_site_label"), None
    )
    if label_idx is None:
        raise ValueError("CIF に _atom_site_label ループが見つかりません。")
    # ヘッダ (_atom_site_*) の連続区間。
    start = label_idx
    while start > 0 and lines[start - 1].strip().startswith("_atom_site"):
        start -= 1
    tags: list[str] = []
    i = start
    while i < len(lines) and lines[i].strip().startswith("_atom_site"):
        tags.append(lines[i].strip())
        i += 1
    data_start = i
    # データ行: 空行 / loop_ / '#' / '_' 開始 まで。
    j = data_start
    while j < len(lines):
        s = lines[j].strip()
        if not s or s.startswith(("#", "loop_", "_", ";")):
            break
        j += 1
    return start, tags, data_start, j


def place_d2o(
    structure_path: str | Path,
    water_labels: list[str] | tuple[str, ...],
    out_path: str | Path,
    *,
    od_distance: float = 0.96,
    dod_angle: float = 104.5,
    uiso: float | None = None,
) -> tuple[Path, tuple[DeuteriumSite, ...]]:
    """CIF の水 O サイトへ D を 2 個ずつ幾何配置した新 CIF を書き出す。🔵

    :param structure_path: 入力 CIF (水 O を含むモデル)
    :param water_labels: D を付ける水 O サイトのラベル列 (例 ``["O1", "O3", "Ow"]``)
    :param out_path: 出力 CIF パス
    :param od_distance: O–D 距離 [Å]
    :param dod_angle: D–O–D 角 [deg]
    :param uiso: D の Uiso 初期値 (None なら親 O の変位値を流用)
    :returns: ``(出力 CIF パス, 配置した DeuteriumSite のタプル)``

    Raises:
        ValueError: セル定数 / atom_site ループ / 指定した水ラベルが見つからないとき。
    """
    text = Path(structure_path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    cell = _read_cell(lines)
    mat = frac_to_cart_matrix(
        cell["a"], cell["b"], cell["c"], cell["alpha"], cell["beta"], cell["gamma"]
    )
    inv = np.linalg.inv(mat)

    _hstart, tags, data_start, data_end = _find_atom_loop(lines)
    col = {tag: k for k, tag in enumerate(tags)}
    if "_atom_site_label" not in col:
        raise ValueError("atom_site ループに _atom_site_label 列がありません。")
    ix = col["_atom_site_fract_x"]
    iy = col["_atom_site_fract_y"]
    iz = col["_atom_site_fract_z"]

    rows = [lines[k].split() for k in range(data_start, data_end)]
    by_label = {r[col["_atom_site_label"]]: r for r in rows if r}

    # 種配向: 直交系で bisector=+z, 面内 perp=+x (無秩序水は decision-free で決定論的に固定)。
    half = math.radians(dod_angle / 2.0)
    bisector = np.array([0.0, 0.0, 1.0])
    perp = np.array([1.0, 0.0, 0.0])
    dirs = (
        math.cos(half) * bisector + math.sin(half) * perp,
        math.cos(half) * bisector - math.sin(half) * perp,
    )

    new_rows: list[str] = []
    d_sites: list[DeuteriumSite] = []
    for parent in water_labels:
        if parent not in by_label:
            raise ValueError(f"水ラベル {parent!r} が atom_site に見つかりません。")
        prow = by_label[parent]
        o_frac = np.array(
            [_strip_esd(prow[ix]), _strip_esd(prow[iy]), _strip_esd(prow[iz])]
        )
        o_cart = mat @ o_frac
        occ = _strip_esd(prow[col["_atom_site_occupancy"]]) if "_atom_site_occupancy" in col else 1.0
        for n, direction in enumerate(dirs, start=1):
            d_cart = o_cart + od_distance * direction
            d_frac = inv @ d_cart
            label = f"D{parent}{n}"
            new_rows.append(
                _format_row(tags, col, prow, label, d_frac, occ, uiso)
            )
            d_sites.append(
                DeuteriumSite(
                    label=label,
                    parent_label=parent,
                    frac=(float(d_frac[0]), float(d_frac[1]), float(d_frac[2])),
                    occupancy=occ,
                )
            )

    out_lines = lines[:data_end] + new_rows + lines[data_end:]
    out = Path(out_path)
    out.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    return out, tuple(d_sites)


def _format_row(
    tags: list[str],
    col: dict[str, int],
    parent_row: list[str],
    label: str,
    d_frac: np.ndarray,
    occ: float,
    uiso: float | None,
) -> str:
    """親 O の行を雛形に D 行を組む (列順は元ループに一致)。"""
    fields: list[str] = []
    for k, tag in enumerate(tags):
        if tag == "_atom_site_label":
            fields.append(label)
        elif tag == "_atom_site_fract_x":
            fields.append(f"{d_frac[0]:.5f}")
        elif tag == "_atom_site_fract_y":
            fields.append(f"{d_frac[1]:.5f}")
        elif tag == "_atom_site_fract_z":
            fields.append(f"{d_frac[2]:.5f}")
        elif tag == "_atom_site_occupancy":
            fields.append(f"{occ:.4f}")
        elif tag == "_atom_site_type_symbol":
            fields.append("D")
        elif tag in ("_atom_site_U_iso_or_equiv", "_atom_site_B_iso_or_equiv"):
            if uiso is not None:
                fields.append(f"{uiso:.5f}")
            else:
                fields.append(parent_row[k] if k < len(parent_row) else "0.05")
        else:
            # multiplicity/Wyckoff/adp_type など: 親 O からコピー (無ければプレースホルダ)。
            fields.append(parent_row[k] if k < len(parent_row) else ".")
    return " ".join(fields)
