"""`tests/topas` 共通フィクスチャ。

**``docs/benchmark/testdata/`` は gitignore 対象**で CI には存在しない。実データを直接
参照するテストは skip し、実データを**必要としない**テスト (スタブ driver で段の受理/revert を
見るもの等) には合成 CIF を渡して CI でも動かす — skip で逃げるとカバレッジが CI から消える。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REAL_DATA = Path("docs/benchmark/testdata")

requires_real_data = pytest.mark.skipif(
    not (REAL_DATA / "PbSO4-Wyckoff.cif").is_file(),
    reason="実データ (docs/benchmark/testdata) が無い — gitignore 対象で CI には存在しない",
)

_SYNTHETIC_CIF = """\
# Synthetic CIF for tests. CIF content must stay ASCII: refinement engines read it
# with the platform codec (cp932 here), so non-ASCII breaks them.
data_synthetic
_cell_length_a    8.48000
_cell_length_b    5.40000
_cell_length_c    6.96000
_cell_angle_alpha 90.0000
_cell_angle_beta  90.0000
_cell_angle_gamma 90.0000
_symmetry_space_group_name_H-M   'P n m a'
_symmetry_Int_Tables_number      62
loop_
 _symmetry_equiv_pos_as_xyz
 'x,y,z'
 'x,1/2-y,z'
 '-x,-y,-z'
 '-x,1/2+y,-z'
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 _atom_site_U_iso_or_equiv
 Pb    Pb   0.18800   0.25000   0.16700  1.000  0.01000
 S     S    0.06300   0.25000   0.68600  1.000  0.01000
 O1    O    0.09500   0.02600   0.80600  1.000  0.01000
"""


@pytest.fixture(scope="session")
def synthetic_cif(tmp_path_factory) -> Path:
    """実データ非依存の最小 CIF (Pnma, 対称操作つき)。"""
    path = tmp_path_factory.mktemp("topas-cif") / "synthetic.cif"
    path.write_text(_SYNTHETIC_CIF, encoding="ascii")
    return path



@pytest.fixture(scope="session")
def synthetic_data(tmp_path_factory) -> "tuple[Path, Path]":
    """実データ非依存の (観測 .xye, 装置 .instprm)。

    単一ガウスピーク + 平坦背景。値そのものに意味は無く、「読める観測ファイルがある」
    という前提だけを満たす。
    """
    import math

    base = tmp_path_factory.mktemp("topas-data")
    rows = []
    for i in range(400):
        x = 20.0 + 0.05 * i
        y = 100.0 + 3000.0 * math.exp(-0.5 * ((x - 30.0) / 0.2) ** 2)
        rows.append(f"{x:.4f} {y:.4f} {max(math.sqrt(y), 1.0):.4f}")
    xye = base / "d.xye"
    xye.write_text("\n".join(rows) + "\n", encoding="ascii")

    prm = base / "i.instprm"
    prm.write_text(
        "#GSAS-II instrument parameter file\n"
        "Type:PXC\nBank:1.0\nLam:1.540600\nZero:0.0\n",
        encoding="ascii",
    )
    return xye, prm
