"""薄い MCP 3 ツール (M8-③ Phase C) — MEM 駆動の構造モデル修正の計器+アクチュエータ。

閉ループ丸ごとは出さない。③ (Claude Code) が以下を反復駆動する (architecture.md §0/§6):

- ``mem_density``: 精密化済み gpx ハンドル (auto_rietveld 由来) → 実 Dysnomia MEM を回し、密度
  min/max・**未モデル密度ピーク** (frac/mag/最近接原子/距離)・.grd パスを構造化して返す (計器)。
- ``propose_structure_revisions``: MEM ピーク → ``ReviseStructure`` 候補 (具体 evidence) を返す
  (計器・純関数)。
- ``edit_cif``: CIF + 具体編集 (AtomEdit) → 新 CIF を書く (アクチュエータ)。③ はこの新 CIF を
  ``refine_with_revisions`` の ``ReviseStructure(edits={"structure_path": ...})`` で参照する。

**SDK 非依存**: 素の型 dict のみを返す (json.dumps allow_nan=False 安全)。GSAS/Dysnomia は
``mem_density`` 内で ``mem.gsas.run_dysnomia_mem`` 経由に遅延。未解決は ``MEMUnavailableError``
をエラー dict へ変換 (既存 ``run_mem`` 縮退規約と同型・破壊なし)。

信頼性: 🔵 docs/design/m8-agentic-loop/mem-model-fix.md §2 の ② 表と 1:1。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from .._json import finite_or_none
from ..errors import MEMUnavailableError

__all__ = [
    "MEM_MODEL_TOOLS",
    "edit_cif",
    "mem_density",
    "propose_structure_revisions",
]


def mem_density(
    gpx_path: str,
    *,
    phase: str | None = None,
    hist: str | None = None,
    density_kind: str | None = None,
    dmin: float = 0.9,
    grid_step: float = 0.25,
    cutoff: float = 30.0,
    top_peaks: int = 8,
    binary_path: str | None = None,
    extra_search_dirs: Sequence[str] = (),
    out_grd: str | None = None,
) -> dict:
    """精密化済み gpx から実 Dysnomia MEM を回し密度統計 + 未モデル密度ピークを返す (計器)。

    :param gpx_path: auto_rietveld が返した gpx ハンドル
    :param phase/hist: 対象相/ヒスト (None は既定選択; joint は density_kind で取り違え防止)
    :param density_kind: ``electron``/``nuclear`` を明示 (None は probe から自動)
    :returns: 密度統計 + peaks[] の素の型 dict。Dysnomia 未解決は ``{"error", "error_type"}``。
    """
    from ..mem.gsas import MEMRunConfig, run_dysnomia_mem  # 遅延 (GSAS 境界隔離)

    cfg = MEMRunConfig(
        dmin=dmin, grid_step=grid_step, density_kind=density_kind, cutoff=cutoff,
        top_peaks=top_peaks, binary_path=binary_path,
        extra_search_dirs=tuple(extra_search_dirs),
    )
    try:
        res = run_dysnomia_mem(
            gpx_path, phase_name=phase, hist_name=hist, config=cfg, out_grd=out_grd
        )
    except MEMUnavailableError as exc:
        return {"error": str(exc), "error_type": "MEMUnavailableError"}

    return {
        "density_kind": res.density_kind,
        "density_min": finite_or_none(res.density_map.min_density),
        "density_max": finite_or_none(res.density_map.max_density),
        "pre_min": finite_or_none(res.pre_min),
        "pre_max": finite_or_none(res.pre_max),
        "n_reflections": res.n_reflections,
        "converged": bool(res.converged),
        "mem_r_factor": (
            finite_or_none(res.mem_r_factor) if res.mem_r_factor is not None else None
        ),
        "grd_path": res.density_map.path,
        "peaks": [
            {
                "frac": [finite_or_none(x) for x in p.frac],
                "magnitude": finite_or_none(p.magnitude),
                "nearest_atom": p.nearest_atom,
                "distance": finite_or_none(p.distance),
            }
            for p in res.peaks
        ],
    }


def propose_structure_revisions(
    peaks: Sequence[Mapping[str, object]],
    density_kind: str,
    *,
    phase: str,
    unmodeled_distance: float = 0.8,
    max_proposals: int = 8,
) -> dict:
    """MEM ピーク (mem_density.peaks) → ReviseStructure 候補を返す (計器・純関数・提案のみ)。

    :param peaks: ``mem_density`` の ``peaks`` (frac/magnitude/nearest_atom/distance)
    :param density_kind: ``electron``/``nuclear``
    :param phase: 対象相名
    """
    from ..mem.base import MEMDensityMap  # numpy-only
    from ..mem.gsas import DensityPeak, MEMDensityResult
    from ..refine_loop.mem_diagnostics import propose_structure_revisions_from_mem
    from ..refine_loop.serialization import proposal_to_dict

    dpeaks = tuple(
        DensityPeak(
            frac=tuple(float(x) for x in p["frac"]),  # type: ignore[arg-type]
            magnitude=float(p["magnitude"]),  # type: ignore[arg-type]
            nearest_atom=str(p["nearest_atom"]),
            distance=float(p["distance"]),  # type: ignore[arg-type]
        )
        for p in peaks
    )
    mem = MEMDensityResult(
        density_map=MEMDensityMap(
            path="", density_kind=density_kind, grid_shape=(0, 0, 0),
            min_density=0.0, max_density=0.0,
        ),
        pre_min=0.0, pre_max=0.0, n_reflections=0, mem_r_factor=None, converged=True,
        density_kind=density_kind, peaks=dpeaks,
    )
    props = propose_structure_revisions_from_mem(
        mem, phase=phase, unmodeled_distance=unmodeled_distance, max_proposals=max_proposals
    )
    return {"proposals": [proposal_to_dict(p) for p in props]}


def edit_cif(
    cif_path: str,
    edits: Sequence[Mapping[str, object]],
    out_path: str,
    *,
    phase_name: str = "phase",
) -> dict:
    """CIF に原子編集 (AtomEdit) を適用し新 CIF を書く (アクチュエータ・純関数)。

    :param edits: ``{"op","label","element","frac","occ","uiso"}`` の列 (③ が確定した具体編集)
    :returns: ``{"cif_path", "n_edits"}``。編集エラーは ``{"error", "error_type"}``。
    """
    from ..autorietveld.cif_edit import AtomEdit, apply_atom_edits

    aedits = []
    for e in edits:
        frac = e.get("frac")
        occ = e.get("occ")
        uiso = e.get("uiso")
        aedits.append(
            AtomEdit(
                op=str(e["op"]),  # type: ignore[arg-type]
                label=str(e["label"]),
                element=str(e["element"]) if e.get("element") is not None else None,
                frac=tuple(float(x) for x in frac) if frac is not None else None,  # type: ignore[arg-type]
                occ=float(occ) if occ is not None else None,  # type: ignore[arg-type]
                uiso=float(uiso) if uiso is not None else None,  # type: ignore[arg-type]
            )
        )
    try:
        path = apply_atom_edits(cif_path, aedits, out_path, phase_name=phase_name)
    except (ValueError, KeyError, FileNotFoundError, OSError) as exc:
        # 編集エラー (不正 op/重複/欠落ラベル) や入力 CIF 未存在/不読を破壊なくエラー dict へ縮退。
        return {"error": str(exc), "error_type": type(exc).__name__}
    return {"cif_path": path, "n_edits": len(aedits)}


# 【ツールレジストリ断片】: tools.py の MCP_TOOLS へ合流する 3 ツール (M8-③ Phase C)。
MEM_MODEL_TOOLS: Mapping[str, object] = {
    "mem_density": mem_density,
    "propose_structure_revisions": propose_structure_revisions,
    "edit_cif": edit_cif,
}
