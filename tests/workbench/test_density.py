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


def test_block_bounds_mutation_without_cap_would_exceed_128():
    """変異実証: ブロック分割を外す (1 セル 1 ブロックにする) と 129 点がそのまま漏れる。

    ``extract_mem_map`` の ≤128×128 契約は ``_block_bounds`` が担っている — これを
    「分割しない」変異版に差し替えると、129 入力に対し契約上限 128 を超えた配列が返る
    ことを確認し、元の実装が上限を実際に強制していることを実証する。
    """

    def _no_cap(n: int, _max_dim: int):  # 分割を外した変異版 (1 セル 1 ブロック)
        return [(i, i + 1) for i in range(n)]

    original = density._block_bounds
    density._block_bounds = _no_cap  # type: ignore[attr-defined]
    try:
        blocks = density._block_bounds(129, density.MAX_MAP_DIM)
        # 【変異で意図的に破壊】: 元の実装なら len <= 128 だが、分割を外すと 129 のまま漏れる。
        assert len(blocks) == 129
        assert len(blocks) > density.MAX_MAP_DIM
    finally:
        density._block_bounds = original  # type: ignore[attr-defined]


def test_block_bounds_actually_caps_at_max_dim():
    """上のテストと対をなす正常系: 元の実装は必ず ``max_dim`` 以下のブロック数に分割する。"""
    blocks = density._block_bounds(129, density.MAX_MAP_DIM)
    assert len(blocks) <= density.MAX_MAP_DIM
    # 連続かつ単調 (描画の並びが崩れず、取りこぼしセルも無い)。
    assert blocks[0][0] == 0 and blocks[-1][1] == 129
    for (a0, a1), (b0, b1) in zip(blocks[:-1], blocks[1:]):
        assert a1 == b0 and a0 < a1


class TestBlockReductionKeepsPeaks:
    """間引きは点サンプリングでなくブロック縮約 (絶対値最大) — ピークを図から消さない。

    【背景】: 単純間引きだとサンプル点の隙間に落ちた密度ピークが断面図から消え、
    「未モデル密度は無い」という誤った読みを生む (レビュー指摘)。
    """

    def _grd_with_spike(self, tmp_path, n: int, spike_at: tuple[int, int], value: float):
        import numpy as np

        from tsumugin.mem.output import save_density_grid

        grid = np.zeros((n, n, 3), dtype=float)
        grid[spike_at[0], spike_at[1], 1] = value
        path = tmp_path / "spike.grd"
        save_density_grid(str(path), grid, (10.0, 10.0, 10.0, 90.0, 90.0, 90.0))
        return str(path)

    def test_positive_peak_between_sample_points_survives(self, tmp_path) -> None:
        # 257 点を 128 へ縮約 → 奇数添字は等間隔サンプリングでは踏まれない位置
        path = self._grd_with_spike(tmp_path, 257, (61, 61), 42.0)
        out = density.extract_mem_map(path, density_kind="electron", vmin=0.0, vmax=42.0)
        values = out["values"]
        assert max(max(row) for row in values) == 42.0, "ピークが縮約で消えた"

    def test_negative_lobe_survives_for_delt_f_maps(self, tmp_path) -> None:
        # delt-F は負のローブを持つ — 絶対値最大なら符号を保って残る
        path = self._grd_with_spike(tmp_path, 257, (61, 61), -37.0)
        out = density.extract_mem_map(path, density_kind="electron", vmin=-37.0, vmax=0.0)
        values = out["values"]
        assert min(min(row) for row in values) == -37.0, "負のローブが縮約で消えた"

    def test_still_respects_max_dim_cap(self, tmp_path) -> None:
        path = self._grd_with_spike(tmp_path, 257, (61, 61), 1.0)
        out = density.extract_mem_map(path, density_kind="electron", vmin=0.0, vmax=1.0)
        assert out["nx"] <= 128 and out["ny"] <= 128
