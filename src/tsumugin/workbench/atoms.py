"""実サイト抽出 — 精密化済み gpx から STRUCTURE タブの sites を構築する
(`docs/design/gui-workbench/api-contract.md` §解析ループ A2)。

``ph.data["Atoms"]`` + ``ph.data["General"]["AtomPtrs"]`` (`autorietveld.engine._phase_atom_info`/
``_extract_state`` と同じ抽出テンプレート, ``AtomPtrs=[cx, ct, cs, cia]``) から
``{label, el, x, y, z, occ, uiso}`` を読み、``GSASIIspc.GetCSxinel(site_sym)`` (`engine._phase_atom_info`
と同じ判定) で特殊位置の座標ロックを判定する。GSAS-II は関数内で遅延 import する
(curves.py と同じ流儀 — コアへ GSAS 依存を持ち込まない)。
"""

from __future__ import annotations

from typing import Any, Mapping

from .._json import finite_or_none
from .curves import _g2sc

__all__ = ["extract_sites"]


def _fmt(value: "float | None") -> str:
    return f"{value:.4f}" if value is not None else ""


def _lock_from_site_symmetry(g2spc: Any, site_sym: object) -> dict[str, bool]:
    """site symmetry から x/y/z の特殊位置ロックを判定する (``engine._phase_atom_info`` と同じ判定)。

    ``GetCSxinel`` が返す自由項リストの各軸が非零なら「自由 (ロックなし)」、0 なら「対称拘束で
    固定」。判定に失敗した構造差異は site symmetry 文字列が ``"1"`` (一般位置) かどうかで代用する
    フォールバックへ縮退する (`engine._phase_atom_info` と同じ安全側)。
    """
    try:
        free = g2spc.GetCSxinel(site_sym)[0]
        return {
            "x": not bool(free[0]),
            "y": not bool(free[1]),
            "z": not bool(free[2]),
        }
    except Exception:  # noqa: BLE001 — 構造差異は保守的に「一般位置か否か」で代用する
        general = str(site_sym).strip() == "1"
        fixed = not general
        return {"x": fixed, "y": fixed, "z": fixed}


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
            cx, ct, cs, cia = ph.data["General"]["AtomPtrs"]
            atoms = ph.data["Atoms"]
        except (KeyError, TypeError, ValueError):
            continue
        esd_map = esd_by_phase.get(ph.name, {})
        for row in atoms:
            idx += 1
            label = str(row[ct - 1])
            el = str(row[ct])
            x = finite_or_none(row[cx])
            y = finite_or_none(row[cx + 1])
            z = finite_or_none(row[cx + 2])
            occ = finite_or_none(row[cx + 3])
            uiso = finite_or_none(row[cia + 1]) if row[cia] == "I" else None
            lock = _lock_from_site_symmetry(g2spc, row[cs])
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
