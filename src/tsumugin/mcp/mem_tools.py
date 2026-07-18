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
from ._degrade import degrade_oserror

__all__ = [
    "MEM_MODEL_TOOLS",
    "edit_cif",
    "mem_density",
    "mem_rietveld_iterate",
    "propose_structure_revisions",
]


@degrade_oserror
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
    map_type: str = "Fobs",
    binary_path: str | None = None,
    extra_search_dirs: Sequence[str] = (),
    out_grd: str | None = None,
) -> dict:
    """精密化済み gpx から実 MEM/差フーリエ密度を回し密度統計 + 未モデル密度ピークを返す (計器)。

    :param gpx_path: auto_rietveld が返した gpx ハンドル
    :param phase/hist: 対象相/ヒスト (None は既定選択; joint は density_kind で取り違え防止)
    :param density_kind: ``electron``/``nuclear`` を明示 (None は probe から自動)
    :param map_type: ``"Fobs"`` (Dysnomia MEM 密度・既定) / ``"delt-F"`` (差フーリエ Fo-Fc,
        **欠損原子探索向け**・Dysnomia 不要・高分解能データで有効)。model-fix は delt-F 推奨。
    :returns: 密度統計 + peaks[] の素の型 dict。Dysnomia 未解決は ``{"error", "error_type"}``。
    """
    from ..mem.gsas import MEMRunConfig, run_dysnomia_mem  # 遅延 (GSAS 境界隔離)

    cfg = MEMRunConfig(
        dmin=dmin, grid_step=grid_step, density_kind=density_kind, cutoff=cutoff,
        top_peaks=top_peaks, map_type=map_type, binary_path=binary_path,
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


@degrade_oserror
def mem_rietveld_iterate(
    gpx_path: str,
    *,
    max_iter: int = 5,
    refine_max_cyc: int = 5,
    unmodeled_distance: float = 0.8,
    rwp_tol: float = 1e-3,
    density_tol: float = 1e-3,
    worsen_eps: float = 1e-3,
    phase: str | None = None,
    hist: str | None = None,
    dmin: float = 0.9,
    grid_step: float = 0.25,
    density_kind: str | None = None,
    cutoff: float = 30.0,
    top_peaks: int = 8,
    map_type: str = "Fobs",
    binary_path: str | None = None,
    extra_search_dirs: Sequence[str] = (),
    snapshot_dir: str | None = None,
    reason: str = "",
) -> dict:
    """精密化済み gpx に MEM-Rietveld (MPF) 反復を回す — 単発 mem_density で改善が止まったとき (計器, FR-603)。

    ``mem_density`` は 1 回の MEM を見るだけ。MPF は **Rietveld 再精密化 ⇄ 実 Dysnomia MEM** を
    交互反復し、密度と構造が同時に自己無撞着へ向かうかを見る。各反復は**独立の子スナップショット
    gpx** を書き (P2: 前反復を上書きしない)、ledger に追記する。収束/発散/max_iter で停止する。

    **このツールを呼ぶこと自体が反復の opt-in** (① `MPFConfig.enabled` の既定 False は安全弁で、
    ③ が明示的に本ツールを呼んだ時点で有効化する)。**提案のみ**: 反復結果 (未モデル密度が残るか・
    Rwp が下がり続けるか) を ③ が読み、構造改訂 (mem-model-fix skill) の要否を判断する。

    :param gpx_path: ``auto_rietveld`` が返した精密化済み gpx ハンドル
    :param max_iter: 最大反復数。``refine_max_cyc`` は各反復の Rietveld 再精密化サイクル数
    :param unmodeled_distance: 未モデル密度ピークとみなす最近接原子距離 (Å) 下限
    :param rwp_tol/density_tol: Rwp / 密度 max の相対変化がこれ未満で収束。``worsen_eps``: Rwp 悪化
        (発散) 判定閾値
    :param phase/hist: 対象相/ヒスト。``dmin``〜``map_type`` は各反復の MEM 設定 (mem_density と同義)
    :param snapshot_dir: 子スナップショット gpx (``mpf_iter{i}.gpx``) の出力先。**呼び出しごとに固有の
        ディレクトリを渡すこと** (再利用すると別実行の gpx を上書きする)
    :returns: ``cycles[]`` (反復毎の gpx/rwp/密度/未モデルピーク数) + ``stop_reason``
        ("converged"/"max_iter"/"diverged") + ``warnings`` + ``ledger_verified``。GSAS/Dysnomia
        未解決は ``{"error", "error_type"}`` (③ は LLM なので例外は回復不能)
    """
    from ..errors import GSASUnavailableError
    from ..mem.gsas import MEMRunConfig
    from ..mem.mpf import MPFConfig, run_mem_rietveld_gpx
    from ..store.ledger import Ledger

    mem_cfg = MEMRunConfig(
        dmin=dmin, grid_step=grid_step, density_kind=density_kind, cutoff=cutoff,
        top_peaks=top_peaks, map_type=map_type, binary_path=binary_path,
        extra_search_dirs=tuple(extra_search_dirs),
    )
    config = MPFConfig(
        enabled=True,  # ツールを呼ぶこと自体が opt-in (① 既定 False は安全弁)
        max_iter=int(max_iter),
        rwp_tol=float(rwp_tol),
        density_tol=float(density_tol),
        worsen_eps=float(worsen_eps),
        refine_max_cyc=int(refine_max_cyc),
        mem=mem_cfg,
        unmodeled_distance=float(unmodeled_distance),
    )
    ledger = Ledger()
    try:
        result = run_mem_rietveld_gpx(
            gpx_path, phase_name=phase, hist_name=hist, config=config,
            snapshot_dir=snapshot_dir, ledger=ledger,
        )
    except (MEMUnavailableError, GSASUnavailableError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}

    return {
        "stop_reason": result.stop_reason,
        "n_cycles": len(result.cycles),
        "cycles": [
            {
                "iteration": c.iteration,
                "gpx_path": c.gpx_path,
                "rwp": finite_or_none(c.rwp),
                "density_max": finite_or_none(c.density_max),
                "density_min": finite_or_none(c.density_min),
                "mem_r_factor": (
                    finite_or_none(c.mem_r_factor) if c.mem_r_factor is not None else None
                ),
                "n_unmodeled": c.n_unmodeled,
            }
            for c in result.cycles
        ],
        "warnings": list(result.warnings),
        "ledger_verified": ledger.verify(),
        "reason": reason,
    }


# 【ツールレジストリ断片】: tools.py の MCP_TOOLS へ合流する 4 ツール (M8-③ Phase C + FR-603 反復)。
MEM_MODEL_TOOLS: Mapping[str, object] = {
    "mem_density": mem_density,
    "propose_structure_revisions": propose_structure_revisions,
    "edit_cif": edit_cif,
    "mem_rietveld_iterate": mem_rietveld_iterate,
}
