"""プロット曲線抽出 — 精密化済み gpx から契約 fit.plot 形の曲線を構築する
(`docs/design/gui-workbench/architecture.md` §バックエンド `curves.py`)。

``hist.data["data"][1]`` = ``[x, Yobs, weight, Ycalc, Ybkg, Ydiff]``
(`autorietveld.engine._extract_residual` と同じ抽出テンプレート) と
``hist.data["Reflection Lists"][phase]["RefList"]`` (各反射行の index 5 = 2θ 位置,
`GSASIImpsubs.py` の ``refl[5+im]`` 規約 [im=0: 非変調構造]) から
``{x, yobs, ycalc, ybkg, residual, ticks}`` を構造化する。

大配列 (実データで数千点) を境界で無制限に跨がせないため ≤2000 点へ等間隔間引きする。
GSAS-II は関数内で遅延 import する (① への機能追加を避けるため workbench 内に置く設計)。
"""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from .._json import finite_or_none

__all__ = ["extract_curves"]

_MAX_POINTS = 2000


def _g2sc() -> Any:
    """遅延 import + 出力抑制済みの GSASIIscriptable モジュール (未導入は明示例外)。"""
    try:
        from GSASII import GSASIIscriptable as g2sc
    except ImportError as exc:
        raise RuntimeError(
            "GSAS-II が未導入のためフィット曲線を抽出できません "
            "(GSASIIscriptable を import できませんでした)。"
        ) from exc
    try:
        g2sc.SetPrintLevel("none")
    except Exception:  # 【出力抑制の失敗は無害】: 抽出自体は続行する 🔵
        pass
    return g2sc


def _decimate(*arrays: Sequence[float], max_points: int = _MAX_POINTS) -> tuple[list[float], ...]:
    """複数配列を同一インデックスで ≤``max_points`` へ等間隔間引きする (整合を保つ)。"""
    n = len(arrays[0]) if arrays else 0
    if n == 0:
        return tuple([] for _ in arrays)
    if n <= max_points:
        idx = np.arange(n)
    else:
        idx = np.unique(np.round(np.linspace(0, n - 1, max_points)).astype(int))
    return tuple(np.asarray(a, dtype=float)[idx].tolist() for a in arrays)


def extract_curves(
    gpx_path: str,
    *,
    two_theta_limits: "Sequence[tuple[float, float] | None] | None" = None,
    max_points: int = _MAX_POINTS,
) -> dict[str, dict[str, Any]]:
    """精密化済み gpx から各ヒストグラムの契約 fit.plot 形曲線を抽出する。

    :param gpx_path: ``run_auto_rietveld(keep_gpx=...)`` が保存した ``.gpx`` パス
    :param two_theta_limits: ヒストグラム索引順の使用域 (``None`` ならヒストグラム全域をそのまま)。
        要素が ``None`` の位置は当該ヒストグラムのみ全域を使う。
    :param max_points: 曲線点数の上限 (既定 2000)
    :returns: ``{"h0": {"x", "yobs", "ycalc", "ybkg", "residual", "ticks"}, "h1": ..., ...}``
        (``hist_id`` は gpx 内ヒストグラムの並び順に ``h0, h1, …``)
    :raises RuntimeError: GSAS-II が未導入のとき (呼び出し側 [`jobs.RefinementJobManager`] が
        ``failed`` ステータスへ縮退する)
    """
    g2sc = _g2sc()
    gpx = g2sc.G2Project(gpxfile=str(gpx_path))

    out: dict[str, dict[str, Any]] = {}
    for i, hist in enumerate(gpx.histograms()):
        hist_id = f"h{i}"
        d = hist.data["data"][1]  # [x, Yobs, weight, Ycalc, Ybkg, Ydiff]
        x = np.asarray(d[0], dtype=float)
        yobs = np.asarray(d[1], dtype=float)
        ycalc = np.asarray(d[3], dtype=float)
        ybkg = np.asarray(d[4], dtype=float)
        ydiff = np.asarray(d[5], dtype=float)

        lim = two_theta_limits[i] if two_theta_limits and i < len(two_theta_limits) else None
        if lim is not None:
            mask = (x >= lim[0]) & (x <= lim[1])
            x, yobs, ycalc, ybkg, ydiff = x[mask], yobs[mask], ycalc[mask], ybkg[mask], ydiff[mask]

        xs, ys, ycs, ybs, yds = _decimate(x, yobs, ycalc, ybkg, ydiff, max_points=max_points)

        ticks: dict[str, list[float]] = {}
        lo = float(x[0]) if len(x) else None
        hi = float(x[-1]) if len(x) else None
        refl_lists = hist.data.get("Reflection Lists", {}) or {}
        for pname, refl in refl_lists.items():
            positions: list[float] = []
            for row in refl.get("RefList", []):
                try:
                    pos = float(row[5])
                except (TypeError, IndexError, ValueError):
                    continue
                if lo is not None and hi is not None and not (lo <= pos <= hi):
                    continue
                positions.append(pos)
            ticks[str(pname)] = positions

        out[hist_id] = {
            "x": [finite_or_none(v) for v in xs],
            "yobs": [finite_or_none(v) for v in ys],
            "ycalc": [finite_or_none(v) for v in ycs],
            "ybkg": [finite_or_none(v) for v in ybs],
            "residual": [finite_or_none(v) for v in yds],
            "ticks": ticks,
        }
    return out
