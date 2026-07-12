"""mem/output.py の失敗テスト (TASK-0056 / REQ-027/028/029)。

対象実装:
- ``src/tsumugin/mem/output.py``:
  ``write_density_map(mem_result, path) -> str`` (VESTA 互換 .grd) /
  ``extract_cross_section(density_map, *, start, end, dimension=1, label="") -> DensityCrossSection`` /
  ``bond_path_min_density(density_map, *, start_site, end_site, start, end) -> BondPathDensity``。
- ``src/tsumugin/mem/__init__.py``: re-export (__all__ 昇順)。

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の mem/output 節に依拠。

【設計】MEMDensityMap は密度グリッドを持たず path 参照 + min/max 統計のみ。断面/ボンド経路は
  grid_shape と min/max から決定論的近似 (乱数不使用) で構成する。write_density_map はテストで
  tmp_path を使い、リポジトリルートに出力を残さない。
"""

from __future__ import annotations

import numpy as np

from tsumugin.mem.base import BondPathDensity, DensityCrossSection, MEMDensityMap, MEMResult
from tsumugin.mem.output import (
    bond_path_min_density,
    extract_cross_section,
    load_density_grid,
    save_density_grid,
    write_density_map,
)


def _density_map(path: str = "mock.grd") -> MEMDensityMap:
    return MEMDensityMap(
        path=path,
        density_kind="electron",
        grid_shape=(8, 8, 8),
        min_density=0.0,
        max_density=10.0,
    )


def _mem_result(path: str = "mock.grd") -> MEMResult:
    return MEMResult(density_map=_density_map(path))


# ---------------------------------------------------------------------------
# (Z) save/load_density_grid + 実 .grd 優先 (REQ-027/028/029, gsas 連携)
# ---------------------------------------------------------------------------


def test_save_load_density_grid_roundtrip(tmp_path):
    """save→load でグリッドがビット近似で復元する (書式一元化)。"""
    rho = np.arange(2 * 3 * 4, dtype=float).reshape((2, 3, 4)) * 0.5 - 3.0
    p = tmp_path / "d.grd"
    save_density_grid(str(p), rho, (5.0, 6.0, 7.0, 90.0, 100.0, 90.0))
    back = load_density_grid(str(p))
    assert back.shape == (2, 3, 4)
    assert np.allclose(back, rho, atol=1e-6)


def test_load_density_grid_bad_count_raises(tmp_path):
    p = tmp_path / "bad.grd"
    p.write_text("title\n1 1 1 90 90 90\n2 2 2\n1.0\n2.0\n", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError):
        load_density_grid(str(p))


def test_extract_cross_section_uses_real_grid(tmp_path):
    """density_map.path に実 .grd があれば実密度をサンプルする (合成でなく)。"""
    # 端が 100、中央が 0 の実グリッドを作る。合成場 (min0/max10) では出ない値 100 を検出。
    rho = np.zeros((9, 9, 9))
    rho[0, 0, 0] = 100.0
    p = tmp_path / "real.grd"
    save_density_grid(str(p), rho, (8.0, 8.0, 8.0, 90.0, 90.0, 90.0))
    dm = MEMDensityMap(path=str(p), density_kind="nuclear", grid_shape=(9, 9, 9),
                       min_density=0.0, max_density=100.0)
    cs = extract_cross_section(dm, start=(0.0, 0.0, 0.0), end=(0.5, 0.0, 0.0))
    assert float(np.max(cs.values)) == 100.0  # 実グリッドの端点値


def test_cross_section_falls_back_to_synthetic_when_no_grd():
    """.grd が存在しない (モック path) 場合は合成密度へ縮退する (M5 互換)。"""
    dm = _density_map("does_not_exist_zzz.grd")
    cs = extract_cross_section(dm, start=(0.0, 0.0, 0.0), end=(0.5, 0.5, 0.5))
    assert cs.dimension == 1
    # 合成場は [min,max] に収まる。
    assert float(np.min(cs.values)) >= dm.min_density - 1e-9
    assert float(np.max(cs.values)) <= dm.max_density + 1e-9


def test_bond_path_min_density_real_grid(tmp_path):
    """伝導ボトルネック (経路最小密度) を実グリッドから取る。"""
    rho = np.full((9, 9, 9), 5.0)
    rho[4, 0, 0] = -2.0  # 経路途中に低密度ボトルネック
    p = tmp_path / "bp.grd"
    save_density_grid(str(p), rho, (9.0, 9.0, 9.0, 90.0, 90.0, 90.0))
    dm = MEMDensityMap(path=str(p), density_kind="nuclear", grid_shape=(9, 9, 9),
                       min_density=-2.0, max_density=5.0)
    bp = bond_path_min_density(dm, start_site="A", end_site="B",
                               start=(0.0, 0.0, 0.0), end=(0.889, 0.0, 0.0))
    assert bp.min_density == -2.0


# ---------------------------------------------------------------------------
# (A) write_density_map: .grd 書き出しパス返却 [TC-508-01/REQ-027]
# ---------------------------------------------------------------------------


def test_write_density_map_writes_file_and_returns_path(tmp_path):
    out = tmp_path / "density.grd"
    result = write_density_map(_mem_result(), str(out))
    assert result == str(out)
    assert out.exists()
    assert out.stat().st_size > 0


def test_write_density_map_is_deterministic(tmp_path):
    """同一 MEMResult から生成される .grd 内容がビット同一 (乱数不使用)。"""
    out1 = tmp_path / "a.grd"
    out2 = tmp_path / "b.grd"
    write_density_map(_mem_result(), str(out1))
    write_density_map(_mem_result(), str(out2))
    assert out1.read_bytes() == out2.read_bytes()


def test_write_density_map_reflects_grid_and_stats(tmp_path):
    """.grd 内容に grid_shape と min/max が反映される (VESTA 互換ヘッダ)。"""
    out = tmp_path / "density.grd"
    write_density_map(_mem_result(), str(out))
    text = out.read_text(encoding="utf-8")
    # グリッド次元が現れる。
    assert "8" in text


def test_write_density_map_does_not_mutate_result(tmp_path):
    mr = _mem_result()
    out = tmp_path / "density.grd"
    write_density_map(mr, str(out))
    # density_map は不変 (frozen)。
    assert mr.density_map.min_density == 0.0
    assert mr.density_map.max_density == 10.0


# ---------------------------------------------------------------------------
# (B) extract_cross_section: 1D/2D 断面 [TC-508-02/REQ-028]
# ---------------------------------------------------------------------------


def test_extract_cross_section_1d_returns_density_cross_section():
    dm = _density_map()
    cs = extract_cross_section(
        dm, start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0), dimension=1, label="A-B"
    )
    assert isinstance(cs, DensityCrossSection)
    assert cs.dimension == 1
    assert cs.label == "A-B"
    assert isinstance(cs.coordinates, np.ndarray)
    assert isinstance(cs.values, np.ndarray)
    assert cs.coordinates.shape[0] == cs.values.shape[0]
    assert cs.values.shape[0] >= 2


def test_extract_cross_section_values_within_stats():
    """断面値が密度統計 [min, max] の範囲に収まる (決定論導出)。"""
    dm = _density_map()
    cs = extract_cross_section(dm, start=(0.0, 0.0, 0.0), end=(1.0, 1.0, 1.0))
    assert float(np.min(cs.values)) >= dm.min_density - 1e-9
    assert float(np.max(cs.values)) <= dm.max_density + 1e-9


def test_extract_cross_section_is_deterministic():
    dm = _density_map()
    cs1 = extract_cross_section(dm, start=(0.0, 0.0, 0.0), end=(1.0, 0.5, 0.0))
    cs2 = extract_cross_section(dm, start=(0.0, 0.0, 0.0), end=(1.0, 0.5, 0.0))
    assert np.array_equal(cs1.coordinates, cs2.coordinates)
    assert np.array_equal(cs1.values, cs2.values)


def test_extract_cross_section_2d():
    dm = _density_map()
    cs = extract_cross_section(
        dm, start=(0.0, 0.0, 0.0), end=(1.0, 1.0, 0.0), dimension=2
    )
    assert cs.dimension == 2


# ---------------------------------------------------------------------------
# (C) bond_path_min_density: 経路最小密度 [TC-508-03/REQ-029]
# ---------------------------------------------------------------------------


def test_bond_path_min_density_returns_bond_path_density():
    dm = _density_map()
    bp = bond_path_min_density(
        dm, start_site="Na1", end_site="Na2", start=(0.0, 0.0, 0.0), end=(1.0, 0.0, 0.0)
    )
    assert isinstance(bp, BondPathDensity)
    assert bp.start_site == "Na1"
    assert bp.end_site == "Na2"
    assert bp.path_length > 0.0


def test_bond_path_min_density_is_minimum_along_path():
    """min_density は経路上断面の最小値と一致し統計範囲内 (ボトルネック)。"""
    dm = _density_map()
    start = (0.0, 0.0, 0.0)
    end = (1.0, 0.0, 0.0)
    bp = bond_path_min_density(
        dm, start_site="Na1", end_site="Na2", start=start, end=end
    )
    cs = extract_cross_section(dm, start=start, end=end, dimension=1)
    assert bp.min_density == float(np.min(cs.values))
    assert dm.min_density - 1e-9 <= bp.min_density <= dm.max_density + 1e-9


def test_bond_path_min_density_is_deterministic():
    dm = _density_map()
    bp1 = bond_path_min_density(
        dm, start_site="Na1", end_site="Na2", start=(0.0, 0.0, 0.0), end=(0.5, 0.5, 0.0)
    )
    bp2 = bond_path_min_density(
        dm, start_site="Na1", end_site="Na2", start=(0.0, 0.0, 0.0), end=(0.5, 0.5, 0.0)
    )
    assert bp1.min_density == bp2.min_density
    assert bp1.path_length == bp2.path_length
