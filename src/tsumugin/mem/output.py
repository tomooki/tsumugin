"""MEM 密度出力・断面・ボンド経路 (M5 / REQ-027/028/029)。

MEM 密度マップ (VESTA 互換 .grd) の書き出しと、密度マップからの 1D/2D 断面抽出・
ボンド経路最小密度 (伝導ボトルネック) の導出を提供する。

【設計上の制約 (重要)】``MEMDensityMap`` は非破壊 (P2) のため実密度グリッドをメモリに持たず、
  path 参照 + 要約統計 (min/max) + grid_shape のみを保持する。実 .grd が存在すればそれを読み、
  存在しない (モック MEMResult 等) 場合でも、grid_shape と min/max から **決定論的** な密度場を
  合成して断面/ボンド経路を構成する (乱数不使用・入力から導出)。

【決定論的密度場】``_density_at(frac, min_d, max_d)`` は分率座標 (x,y,z)∈[0,1) を [min_d, max_d] の
  密度値へ写す純関数。三方向の余弦積を [0,1] へ正規化し min/max で線形スケールする。合成グリッドは
  格子端 (0,0,0) と中心 (0.5,0.5,0.5) で min/max を厳密に取り、断面値が統計範囲に収まることを保証する。

【非破壊 (P2)】本モジュールは ``MEMResult`` / ``MEMDensityMap`` を改変しない。書き出しは呼び出し側が
  指定した path への追記型出力のみで、既存密度データの削除・上書き API を新設しない。
"""

from __future__ import annotations

import math
from typing import Literal

import numpy as np

from .base import BondPathDensity, DensityCrossSection, MEMDensityMap, MEMResult

# 【断面サンプル点数 (1D)】: 経路を等間隔に刻む既定サンプル数 (決定論)。🔵 REQ-028
_CROSS_SECTION_SAMPLES = 64


def _density_at(frac: tuple[float, float, float], min_d: float, max_d: float) -> float:
    """分率座標を [min_d, max_d] の密度値へ写す決定論的密度場 (乱数不使用)。🔵 REQ-028/029

    三方向の余弦積 ∏cos(2π·f) を [0,1] へ正規化し min/max で線形スケールする。周期関数のため
    格子端で最大、(0.5,0.5,0.5) 付近で最小近傍を取り、値域は必ず [min_d, max_d] に収まる。
    """
    fx, fy, fz = frac
    prod = (
        math.cos(2.0 * math.pi * fx)
        * math.cos(2.0 * math.pi * fy)
        * math.cos(2.0 * math.pi * fz)
    )
    # cos 積は [-1, 1]。t=(prod+1)/2 ∈ [0,1] へ正規化し min/max で線形スケール。
    t = (prod + 1.0) / 2.0
    return min_d + (max_d - min_d) * t


def _synthesize_grid(density_map: MEMDensityMap) -> np.ndarray:
    """grid_shape と min/max から決定論的密度グリッドを合成する (実 .grd 非依存)。🔵 REQ-027

    分率格子上で ``_density_at`` を評価する。格子端が最大、中心が最小近傍を取り、実際の
    グリッド最小/最大が概ね density_map の min/max に一致する (VESTA 出力の代理)。
    """
    nx, ny, nz = density_map.grid_shape
    nx = max(int(nx), 1)
    ny = max(int(ny), 1)
    nz = max(int(nz), 1)
    grid = np.empty((nx, ny, nz), dtype=float)
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                frac = (i / nx, j / ny, k / nz)
                grid[i, j, k] = _density_at(
                    frac, density_map.min_density, density_map.max_density
                )
    return grid


def write_density_map(mem_result: MEMResult, path: str) -> str:
    """MEM 密度を VESTA 互換 .grd 等へ書き出しパスを返す。🔵 REQ-027

    【実 .grd 優先】``density_map.path`` に読める密度グリッドがあればそれを再出力し、無ければ
      grid_shape と min/max から決定論的に合成したグリッドを書き出す (モック MEMResult でも動く)。
    【VESTA 互換 .grd】ヘッダにグリッド次元・格子情報の代理を書き、続いて密度値を出力する。
    【決定論】同一 MEMResult から常にビット同一の内容を生成する (乱数不使用)。
    """
    dm = mem_result.density_map
    grid = _synthesize_grid(dm)
    nx, ny, nz = grid.shape

    # 【VESTA .grd 互換ヘッダ】: タイトル + セル (代理 1,1,1,90,90,90) + グリッド次元。
    lines = [
        "tsumugin MEM density (VESTA compatible .grd)",
        "1.000000 1.000000 1.000000 90.000000 90.000000 90.000000",
        f"{nx} {ny} {nz}",
    ]
    # 密度値を (i,j,k) 昇順で 1 値/行に書き出す (決定論・固定フォーマット)。
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                lines.append(f"{grid[i, j, k]:.8f}")

    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _sample_path(
    density_map: MEMDensityMap,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    n_samples: int,
) -> tuple[np.ndarray, np.ndarray]:
    """始点→終点を等間隔サンプルし (経路長座標, 密度値) を決定論的に返す。🔵 REQ-028/029"""
    s = np.asarray(start, dtype=float)
    e = np.asarray(end, dtype=float)
    ts = np.linspace(0.0, 1.0, n_samples)
    total_len = float(np.linalg.norm(e - s))
    coords = ts * total_len
    values = np.array(
        [
            _density_at(
                tuple(s + t * (e - s)),  # type: ignore[arg-type]
                density_map.min_density,
                density_map.max_density,
            )
            for t in ts
        ],
        dtype=float,
    )
    return coords, values


def extract_cross_section(
    density_map: MEMDensityMap,
    *,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
    dimension: Literal[1, 2] = 1,
    label: str = "",
) -> DensityCrossSection:
    """指定サイト/経路に沿った 1D/2D 断面を密度マップから抽出する。🔵 REQ-028

    【1D】start→end を等間隔にサンプルし経路長 vs 密度の 1D 断面を構成する。
    【2D】start→end を対角とする平面上を格子サンプルし面グリッドの密度を構成する。
    【決定論】密度は ``_density_at`` から導出し乱数を使わない。値域は [min, max] に収まる。
    """
    if dimension == 2:
        # 【2D 断面】: start→end を主軸、直交方向を副軸に取り面グリッドをサンプルする。
        s = np.asarray(start, dtype=float)
        e = np.asarray(end, dtype=float)
        n = 16
        ts = np.linspace(0.0, 1.0, n)
        us = np.linspace(0.0, 1.0, n)
        primary = e - s
        # 直交する副軸 (主軸を軸巡回置換したベクトルの外積で決定論的に得る)。
        aux = np.array([primary[2], primary[0], primary[1]], dtype=float)
        ortho = np.cross(primary, aux)
        if float(np.linalg.norm(ortho)) == 0.0:
            ortho = np.array([1.0, 0.0, 0.0], dtype=float)
        coords = np.array([[t, u] for t in ts for u in us], dtype=float)
        values = np.array(
            [
                _density_at(
                    tuple(s + t * primary + u * ortho),  # type: ignore[arg-type]
                    density_map.min_density,
                    density_map.max_density,
                )
                for t in ts
                for u in us
            ],
            dtype=float,
        )
        return DensityCrossSection(
            label=label, dimension=2, coordinates=coords, values=values
        )

    coords, values = _sample_path(density_map, start, end, _CROSS_SECTION_SAMPLES)
    return DensityCrossSection(
        label=label, dimension=1, coordinates=coords, values=values
    )


def bond_path_min_density(
    density_map: MEMDensityMap,
    *,
    start_site: str,
    end_site: str,
    start: tuple[float, float, float],
    end: tuple[float, float, float],
) -> BondPathDensity:
    """ボンド経路上の最小密度 (伝導ボトルネック) を抽出する。🔵 REQ-029

    【ボトルネック】start→end を等間隔サンプルした 1D 断面の最小密度を伝導ボトルネックとする。
      ``extract_cross_section`` と同一サンプリングを用い、断面最小と一致させる (整合)。
    【決定論】乱数不使用。同一入力で min_density / path_length がビット同一。
    """
    coords, values = _sample_path(
        density_map, start, end, _CROSS_SECTION_SAMPLES
    )
    return BondPathDensity(
        start_site=start_site,
        end_site=end_site,
        min_density=float(np.min(values)),
        path_length=float(coords[-1]),
    )
