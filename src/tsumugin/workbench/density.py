"""MEM 密度マップ断面抽出 (V3b, FR-601) — `docs/design/gui-workbench/api-contract.md`
§MEM 密度マップ。

実 Dysnomia MEM (``tsumugin.mem.gsas.run_dysnomia_mem``) が書き出す .grd
(``tsumugin.mem.output`` の書式) から c 軸に垂直な中央スライスを取り出し、
``viewmodel.structure.mem.map`` 契約形 (``{"axis","index","nx","ny","values","vmin","vmax","unit"}``)
に組み立てる。既存 ``mem.output.extract_cross_section`` は bond path 用の start/end 経路サンプルで
面全体のスライスには使えないため、本モジュールで別途実装する。

numpy-only (GSAS/Dysnomia 非依存) — ``mem.output.load_density_grid`` は .grd を読むだけの純関数。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..mem.output import load_density_grid

__all__ = ["MAX_MAP_DIM", "UNIT_BY_DENSITY_KIND", "extract_mem_map"]

#: viewmodel.structure.mem.map の 1 辺あたり最大サンプル数
#: (api-contract.md「values は ≤128×128 に間引き」)。大配列を境界で無制限に跨がせない規律の一環。
MAX_MAP_DIM = 128

#: density_kind → 表示単位 (seed_mem_peaks の "0.82 fm Å⁻³" と同じ流儀)。
UNIT_BY_DENSITY_KIND: dict[str, str] = {"electron": "e·Å⁻³", "nuclear": "fm·Å⁻³"}


def _decimate_indices(n: int, max_dim: int) -> np.ndarray:
    """``0..n-1`` を ``max_dim`` 点以下へ均等間引きする単調増加の添字列 (決定論)。"""
    if n <= max_dim:
        return np.arange(n)
    return np.unique(np.round(np.linspace(0, n - 1, max_dim)).astype(int))


def extract_mem_map(
    grd_path: str,
    *,
    density_kind: str,
    vmin: float,
    vmax: float,
    axis: str = "c",
    max_dim: int = MAX_MAP_DIM,
) -> dict[str, Any]:
    """.grd から ``axis`` 垂直の中央スライスを ``viewmodel.structure.mem.map`` 契約形で返す。

    :param grd_path: ``mem.output.save_density_grid`` 形式の .grd パス (実 MEM 出力)。
    :param density_kind: ``"electron"``/``"nuclear"`` (単位表示に使う。未知種別は単位空文字)。
    :param vmin/vmax: 密度統計 (``mem_density`` の ``density_min``/``density_max`` をそのまま
        渡す想定 — 全グリッドの統計を凡例に使い、間引き後の部分配列の min/max とはあえて分離する
        [描画と凡例の一貫性])。
    :param axis: 契約「断面は既定で c 軸に垂直な中央スライス」— 現状 ``"c"`` のみ対応。
    :param max_dim: 1 辺あたり最大サンプル数 (既定 128, 契約 ≤128×128)。
    :raises ValueError: ``axis`` が ``"c"`` 以外。
    """
    if axis != "c":
        raise ValueError(f"unsupported axis: {axis!r} (only 'c' is supported)")
    grid = load_density_grid(grd_path)
    _nx, _ny, nz = grid.shape
    index = nz // 2
    plane = grid[:, :, index]
    xi = _decimate_indices(plane.shape[0], max_dim)
    yi = _decimate_indices(plane.shape[1], max_dim)
    sub = plane[np.ix_(xi, yi)]
    # 【非有限値の防御】: 実 MEM 出力は常に有限だが、契約「非有限は null」は 2D 数値配列との相性が
    #   悪い (None が混ざると frontend の number[][] 契約が崩れる) ため 0.0 へ丸める。
    sub = np.where(np.isfinite(sub), sub, 0.0)
    return {
        "axis": axis,
        "index": index,
        "nx": int(sub.shape[0]),
        "ny": int(sub.shape[1]),
        "values": sub.tolist(),
        "vmin": float(vmin),
        "vmax": float(vmax),
        "unit": UNIT_BY_DENSITY_KIND.get(density_kind, ""),
    }
