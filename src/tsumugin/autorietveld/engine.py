"""GSAS-II 駆動の自動 Rietveld エンジン (M7)。

HistogramSpec/PhaseSpec を GSAS-II プロジェクトに変換し、段階解放レシピ (recipe.py) の
宣言的フラグを GSAS-II 呼び出しへ翻訳して順に精密化する。各段階で Rwp が悪化した場合は
直前スナップショット (.gpx コピー) へ revert して当該段階なしで継続する (REQ-105 / FR-202)。
精密化失敗は例外でなく chi2=inf 相当 (converged=False, rwp=inf) に変換しガードレール的に
扱う (REQ-403)。全段階遷移を Ledger へ追記する (NFR-105)。

GSAS-II は本モジュール内で遅延 import するため、tsumugin コア import は numpy のみを維持する。

信頼性: 🔵 T1 プロトタイプの段階進行 (Rwp 45→13.7→11.2→9.84) を production 化。
"""

from __future__ import annotations

import math
import shutil
import tempfile
from pathlib import Path
from typing import Sequence

from ..store import Ledger
from .model import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
)
from .recipe import build_recipe
from .validity import check_validity


def _g2sc():
    """遅延 import + 出力抑制済みの GSASIIscriptable モジュール。"""
    from GSASII import GSASIIscriptable as G2sc

    try:
        G2sc.SetPrintLevel("none")
    except Exception:
        pass
    return G2sc


def _rvals(gpx) -> tuple[float, float, int]:
    """精密化後の (Rwp, GOF, nvar) を Covariance から取り出す。"""
    cov = gpx.data["Covariance"]["data"]
    rv = cov.get("Rvals", {})
    rwp = float(rv.get("Rwp", float("inf")))
    gof = float(rv.get("GOF", float("inf")))
    nvar = len(cov.get("varyList", []))
    return rwp, gof, nvar


def _converged(gpx) -> bool:
    cov = gpx.data["Covariance"]["data"]
    return bool(cov.get("Rvals", {}).get("converged", True))


def _profile_keys(radiation: Radiation) -> list[str]:
    """放射源に応じたプロファイル係数キー。CW/lab は U,V,W。"""
    # TOF は sig-1,sig-2,X,Y 等だが Phase D で個別対応。既定は CW の UVW。
    return ["U", "V", "W"]


def _apply_stage(gpx, hists, phases, radiations, stage: RefinementStage, atom_flags: str) -> str:
    """段階の宣言的フラグを GSAS-II 精密化フラグへ翻訳して適用する (enable のみ)。

    revert は .gpx スナップショット復元で行うため、ここでは有効化だけを担う。
    原子フラグ (X/U/F) は GSAS-II が「置換」セマンティクスのため、既解放分を含む和集合を
    毎回設定して累積させる (例: coords 後に uiso なら "XU")。累積後のフラグ文字列を返す。
    """
    flags = stage.flags
    if "background" in flags:
        n = int(flags["background"].get("coeffs", 6))  # type: ignore[union-attr]
        gpx.set_refinement({"set": {"Background": {"no. coeffs": n, "refine": True}}})
    # scale: GSAS-II はヒストグラムスケールを既定で精密化するため単相では no-op。
    # 多相の相分率 (HAP Scale) は phase_fraction_sum 制約側で扱う (Phase D)。
    if "cell" in flags:
        for ph in phases:
            ph.set_refinements({"Cell": True})
    if "displacement" in flags:
        mapping = flags["displacement"]
        for idx, keys in mapping.items():  # type: ignore[union-attr]
            if 0 <= idx < len(hists):
                hists[idx].set_refinements({"Sample Parameters": list(keys)})
    if "profile" in flags:
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            hist.set_refinements({"Instrument Parameters": _profile_keys(rad)})
    if "size_strain" in flags:
        for ph in phases:
            ph.set_HAP_refinements(
                {
                    "Size": {"type": "isotropic", "refine": True},
                    "Mustrain": {"type": "isotropic", "refine": True},
                }
            )
    # 原子フラグは和集合で累積 (X→coords, U→uiso, F→occupancy)。順序は GSAS 表記 XUF。
    new_flags = atom_flags
    if "coords" in flags and "X" not in new_flags:
        new_flags += "X"
    if "uiso" in flags and "U" not in new_flags:
        new_flags += "U"
    if "occupancy" in flags and "F" not in new_flags:
        new_flags += "F"
    if new_flags != atom_flags:
        ordered = "".join(c for c in "XUF" if c in new_flags)
        for ph in phases:
            ph.set_refinements({"Atoms": {"all": ordered}})
    return new_flags


def _extract_state(phases):
    """validity 用に各相の格子/Uiso/占有率を GSAS-II から抽出する。"""
    refined_cells = {}
    uiso = {}
    occ = {}
    for ph in phases:
        cell = ph.get_cell()
        refined_cells[ph.name] = (
            float(cell["length_a"]),
            float(cell["length_b"]),
            float(cell["length_c"]),
            float(cell["angle_alpha"]),
            float(cell["angle_beta"]),
            float(cell["angle_gamma"]),
        )
        atoms = ph.data["Atoms"]
        cx, ct, cs, cia = ph.data["General"]["AtomPtrs"]
        occ[ph.name] = [float(row[cx + 3]) for row in atoms]
        uvals = []
        for row in atoms:
            if row[cia] == "I":
                uvals.append(float(row[cia + 1]))
        uiso[ph.name] = uvals
    return refined_cells, uiso, occ


def run_auto_rietveld(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    recipe: Sequence[RefinementStage] | None = None,
    reference_cells: dict[str, tuple[float, ...]] | None = None,
    ledger: Ledger | None = None,
    max_cyc: int = 8,
    worsen_eps: float = 1e-6,
    keep_gpx: str | None = None,
) -> AutoRietveldResult:
    """実構造 Rietveld を段階解放で自動実行する (単相/単一ヒストグラムから対応)。

    :param histograms: 観測ヒストグラム仕様
    :param phases: 相仕様 (実 CIF/EXP)
    :param recipe: 段階解放レシピ (None なら build_recipe で生成)
    :param reference_cells: 妥当性判定の参照格子 (None なら初期格子を採用)
    :param ledger: 遷移を追記する Ledger (None なら内部生成)
    :param max_cyc: 各段階の最大精密化サイクル
    :param worsen_eps: Rwp 悪化とみなす閾値
    :param keep_gpx: 最終 .gpx をこのパスへ保存 (None なら破棄)
    :returns: AutoRietveldResult
    """
    g2sc = _g2sc()
    stages = tuple(recipe) if recipe is not None else build_recipe(histograms, phases)
    ledger = ledger if ledger is not None else Ledger()
    radiations = [h.radiation for h in histograms]

    with tempfile.TemporaryDirectory(prefix="tsumugin-m7-") as tmp:
        tmp_path = Path(tmp)
        gpx_path = tmp_path / "auto.gpx"
        gpx = g2sc.G2Project(newgpx=str(gpx_path))

        # --- ヒストグラム追加 ---
        g2hists = []
        for h in histograms:
            hist = gpx.add_powder_histogram(
                h.data_path, h.instrument_path, fmthint=_data_fmthint(h)
            )
            if h.two_theta_limits is not None:
                lo, hi = h.two_theta_limits
                hist.set_refinements({"Limits": [lo, hi]})
            g2hists.append(hist)

        # --- 相追加 ---
        g2phases = []
        for p in phases:
            ph = gpx.add_phase(
                p.structure_path,
                phasename=p.phase_name,
                histograms=g2hists,
                fmthint=p.format_hint,
            )
            g2phases.append(ph)

        # 参照格子 (未指定なら初期格子)
        if reference_cells is None:
            reference_cells = {
                ph.name: tuple(
                    float(ph.get_cell()[k])
                    for k in (
                        "length_a",
                        "length_b",
                        "length_c",
                        "angle_alpha",
                        "angle_beta",
                        "angle_gamma",
                    )
                )
                for ph in g2phases
            }

        gpx.data["Controls"]["data"]["max cyc"] = max_cyc

        stage_results: list[StageResult] = []
        prev_rwp = float("inf")
        atom_flags = ""

        for stage in stages:
            snap = tmp_path / "snap.gpx"
            gpx.save()
            shutil.copyfile(gpx_path, snap)
            prev_atom_flags = atom_flags
            try:
                atom_flags = _apply_stage(
                    gpx, g2hists, g2phases, radiations, stage, atom_flags
                )
                gpx.do_refinements([{}])
                rwp, gof, nvar = _rvals(gpx)
                converged = _converged(gpx)
            except Exception as exc:  # 精密化失敗 → inf 変換 (REQ-403)
                rwp, gof, nvar, converged = float("inf"), float("inf"), 0, False
                ledger.append(
                    "m7_stage_error",
                    {"stage": stage.label, "error": repr(exc)[:200]},
                )

            reverted = False
            # 悪化 (または inf) なら直前スナップショットへ revert して継続 (REQ-105)
            if not math.isfinite(rwp) or rwp > prev_rwp + worsen_eps:
                if prev_rwp < float("inf"):
                    shutil.copyfile(snap, gpx_path)
                    gpx = g2sc.G2Project(gpxfile=str(gpx_path))
                    g2hists = gpx.histograms()
                    g2phases = gpx.phases()
                    gpx.data["Controls"]["data"]["max cyc"] = max_cyc
                    reverted = True
                    atom_flags = prev_atom_flags
                    rwp, gof = prev_rwp, stage_results[-1].gof if stage_results else float("inf")
            else:
                prev_rwp = rwp

            stage_results.append(
                StageResult(
                    label=stage.label,
                    rwp=rwp,
                    gof=gof,
                    n_params=nvar,
                    converged=converged,
                    reverted=reverted,
                    note=stage.note,
                )
            )
            ledger.append(
                "m7_stage",
                {
                    "stage": stage.label,
                    "rwp": rwp,
                    "gof": gof,
                    "n_params": nvar,
                    "reverted": reverted,
                },
            )

        # --- 妥当性判定 ---
        refined_cells, uiso, occ = _extract_state(g2phases)
        phase_fractions = None  # 多相は Phase D で phase_fraction 抽出
        validity = check_validity(
            refined_cells=refined_cells,
            reference_cells=reference_cells,
            uiso=uiso,
            occupancies=occ,
            phase_fractions=phase_fractions,
            converged=stage_results[-1].converged if stage_results else False,
        )

        final_rwp = stage_results[-1].rwp if stage_results else float("inf")
        final_gof = stage_results[-1].gof if stage_results else float("inf")

        out_gpx = ""
        if keep_gpx is not None:
            gpx.save()
            shutil.copyfile(gpx_path, keep_gpx)
            out_gpx = keep_gpx

    return AutoRietveldResult(
        stage_results=tuple(stage_results),
        final_rwp=final_rwp,
        final_gof=final_gof,
        refined_cells=refined_cells,
        validity=validity,
        gpx_path=out_gpx,
    )


def _data_fmthint(h: HistogramSpec) -> str:
    """HistogramSpec.data_format を GSAS-II importer ヒントへ写像する。"""
    return {
        "GSAS": "GSAS",
        "FXYE": "GSAS",  # .fxye も GSAS powder importer が読む
        "XYE": "xye",
    }.get(h.data_format, "GSAS")
