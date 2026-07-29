"""実サイト抽出 — 精密化済み gpx から STRUCTURE タブの sites を構築する
(`docs/design/gui-workbench/api-contract.md` §解析ループ A2)。

行の読み取りと対称性の解釈は `autorietveld.atomrows` に集約してある (**唯一の実装**)。
以前はここが独自にレイアウトを解釈し、``not bool(free[i])`` で対称性を bool へ潰していた —
GUI のロック表示には足りるが、`GetCSxinel` は軸ごとに 3 状態 (固定/結束/独立) を返すので
esd の状態源としては誤りであり、engine 側と解釈が二重化していた。GSAS-II は関数内で
遅延 import する (curves.py と同じ流儀 — コアへ GSAS 依存を持ち込まない)。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..autorietveld.atomrows import atom_row, free_index_from_site_symmetry, lock_from_free_index
from .._json import finite_or_none
from .curves import _g2sc

__all__ = ["extract_sites"]


def _fmt(value: "float | None") -> str:
    return f"{value:.4f}" if value is not None else ""


def extract_sites(
    gpx_path: str,
    *,
    occupancy_esd: "Mapping[str, Mapping[str, float | None]] | None" = None,
) -> list[dict[str, Any]]:
    """精密化済み gpx から全相の実サイトを契約 ``structure.sites`` 形へ抽出する (A2)。

    :param gpx_path: ``run_auto_rietveld(keep_gpx=...)`` が保存した ``.gpx`` パス
    :param occupancy_esd: ``AutoRietveldResult.atom_occupancy_esd`` (相名→ラベル→esd)。
        与えると占有率の esd を ``note`` に併記する (``None``/非正は無視, engine の規律と同じ)。
    :returns: Site 辞書の列 (``id``/``label``/``el``/``x``/``y``/``z``/``occ``/``uiso``/``note``/
        ``lock``/``rel`` + 内部専用 ``phase`` キー)。``phase`` は占有率 revision (A3) を正しい
        相へ配線するための session 内部ルーティング用で、契約 Site スキーマには存在しないため
        呼び出し側 (`WorkbenchSession`) が viewmodel へ渡す前に取り除く。
    :raises RuntimeError: GSAS-II が未導入のとき (呼び出し側が空リストへ縮退させる)
    """
    g2sc = _g2sc()
    from GSASII import GSASIIspc as g2spc

    gpx = g2sc.G2Project(gpxfile=str(gpx_path))
    esd_by_phase = occupancy_esd or {}

    sites: list[dict[str, Any]] = []
    idx = 0
    for ph in gpx.phases():
        try:
            ptrs = ph.data["General"]["AtomPtrs"]
            cs = int(ptrs[2])
            atoms = ph.data["Atoms"]
        except (KeyError, TypeError, ValueError, IndexError):
            continue
        esd_map = esd_by_phase.get(ph.name, {})
        for row in atoms:
            idx += 1
            info = atom_row(row, ptrs)
            label, el = info.label, info.element
            x, y, z = (finite_or_none(v) for v in info.coords)
            occ = finite_or_none(info.occupancy)
            uiso = finite_or_none(info.uiso) if info.uiso is not None else None
            lock = lock_from_free_index(free_index_from_site_symmetry(g2spc.GetCSxinel, row[cs]))
            esd = esd_map.get(label)
            note = f"occ esd ±{esd:.4f}" if esd else ""
            sites.append(
                {
                    "id": f"s{idx}",
                    "label": label,
                    "el": el,
                    "x": _fmt(x),
                    "y": _fmt(y),
                    "z": _fmt(z),
                    "occ": _fmt(occ),
                    "uiso": _fmt(uiso),
                    "note": note,
                    "lock": lock,
                    "rel": {"x": False, "y": False, "z": False, "occ": False, "uiso": False},
                    "phase": ph.name,
                }
            )
    return sites
