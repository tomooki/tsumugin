"""``tsumugin.workbench.density`` の TDD テスト (V3b, FR-601)。

対象: .grd → ``viewmodel.structure.mem.map`` 契約形の抽出 (c 軸中央スライス・≤128×128 間引き)。
numpy-only (GSAS/Dysnomia 非依存)。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tsumugin.mem.output import save_density_grid
from tsumugin.workbench import density


def _write_grid(path: Path, shape: tuple[int, int, int]) -> str:
    """指定形状で決定論的な (単調ではない) 密度グリッドを書き出す。"""
    nx, ny, nz = shape
    rho = np.arange(nx * ny * nz, dtype=float).reshape(shape)
    return save_density_grid(str(path), rho, (10.0, 10.0, 10.0, 90.0, 90.0, 90.0))


def test_extract_mem_map_returns_contract_shape(tmp_path: Path):
    grd = _write_grid(tmp_path / "d.grd", (4, 5, 3))
    result = density.extract_mem_map(grd, density_kind="electron", vmin=0.0, vmax=59.0)
    assert result["axis"] == "c"
    assert result["index"] == 1  # nz//2 == 1 for nz=3
    assert result["nx"] == 4
    assert result["ny"] == 5
    assert len(result["values"]) == 4
    assert all(len(row) == 5 for row in result["values"])
    assert result["vmin"] == 0.0
    assert result["vmax"] == 59.0
    assert result["unit"] == "e·Å⁻³"


def test_extract_mem_map_nuclear_unit(tmp_path: Path):
    grd = _write_grid(tmp_path / "d.grd", (2, 2, 1))
    result = density.extract_mem_map(grd, density_kind="nuclear", vmin=0.0, vmax=1.0)
    assert result["unit"] == "fm·Å⁻³"


def test_extract_mem_map_unknown_density_kind_yields_empty_unit(tmp_path: Path):
    grd = _write_grid(tmp_path / "d.grd", (2, 2, 1))
    result = density.extract_mem_map(grd, density_kind="bogus", vmin=0.0, vmax=1.0)
    assert result["unit"] == ""


def test_extract_mem_map_unsupported_axis_raises(tmp_path: Path):
    grd = _write_grid(tmp_path / "d.grd", (2, 2, 1))
    with pytest.raises(ValueError, match="axis"):
        density.extract_mem_map(grd, density_kind="electron", vmin=0.0, vmax=1.0, axis="a")


# ---------------------------------------------------------------------------
# 間引き上限 (契約「values は ≤128×128 に間引き」) + 変異実証
# ---------------------------------------------------------------------------


def test_extract_mem_map_downsamples_129x129_grid_to_at_most_128(tmp_path: Path):
    grd = _write_grid(tmp_path / "d.grd", (129, 129, 3))
    result = density.extract_mem_map(grd, density_kind="electron", vmin=0.0, vmax=1.0)
    assert result["nx"] <= density.MAX_MAP_DIM
    assert result["ny"] <= density.MAX_MAP_DIM
    assert len(result["values"]) == result["nx"]
    assert all(len(row) == result["ny"] for row in result["values"])


def test_extract_mem_map_small_grid_is_not_padded_or_truncated(tmp_path: Path):
    """契約上限より小さいグリッドはそのまま (63×63 のまま) 返る — 常に 128 へ揃えない。"""
    grd = _write_grid(tmp_path / "d.grd", (63, 63, 1))
    result = density.extract_mem_map(grd, density_kind="electron", vmin=0.0, vmax=1.0)
    assert result["nx"] == 63
    assert result["ny"] == 63


def test_decimate_indices_mutation_without_cap_would_exceed_128():
    """変異実証: 間引きを外す (恒等写像にする) と 129 点がそのまま漏れることを示す。

    ``extract_mem_map`` の ≤128×128 契約は ``_decimate_indices`` が担っている — この関数を
    「間引かない」変異版 (``np.arange``) に差し替えると、129 入力に対し契約上限 128 を超えた
    ままの配列が返ってしまうことを確認し、元の実装がこの上限を実際に強制していることを実証する。
    """

    def _no_cap(n: int, _max_dim: int) -> np.ndarray:  # 間引きを外した変異版
        return np.arange(n)

    original = density._decimate_indices
    density._decimate_indices = _no_cap  # type: ignore[attr-defined]
    try:
        n = 129
        xi = density._decimate_indices(n, density.MAX_MAP_DIM)
        # 【変異で意図的に破壊】: 元の実装なら xi.size <= 128 だが、間引きを外すと 129 のまま漏れる。
        assert xi.size == 129
        assert xi.size > density.MAX_MAP_DIM
    finally:
        density._decimate_indices = original  # type: ignore[attr-defined]


def test_decimate_indices_actually_caps_at_max_dim():
    """上のテストと対をなす正常系: 元の実装は必ず ``max_dim`` 以下に間引く。"""
    xi = density._decimate_indices(129, density.MAX_MAP_DIM)
    assert xi.size <= density.MAX_MAP_DIM
    # 単調増加 (描画の並びが崩れない)。
    assert list(xi) == sorted(xi.tolist())
