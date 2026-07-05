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


def _cells_physical(g2phases, min_length: float = 0.5) -> bool:
    """全相の格子長が物理的 (有限かつ min_length 以上) かを判定する。

    多相・高分解能データではプロファイル/サイズ解放時に格子が 0 へ崩壊する発散が起こり得る。
    崩壊した段階は「悪化」とみなして revert させるためのガード。
    """
    for ph in g2phases:
        cell = ph.get_cell()
        for key in ("length_a", "length_b", "length_c"):
            v = float(cell[key])
            if not math.isfinite(v) or v < min_length:
                return False
    return True


def _profile_keys(radiation: Radiation) -> list[str]:
    """CW (X 線/中性子) の Gaussian プロファイル係数キー U,V,W。

    TOF は本段階では精密化しない (呼び出し側で TOF をスキップ)。TOF の装置プロファイル
    (sig/alpha/beta) はキャリブレーション依存で、ピーク形状は size/mustrain で処理する。
    """
    return ["U", "V", "W"]


def _phase_atom_info(ph, spec: PhaseSpec) -> dict:
    """相の原子メタ情報 (座標可変ラベル・全ラベル・混合占有ラベル) を収集する。

    座標精密化は自由座標を 1 つ以上持つ原子のみに限定する。対称性で完全に固定された特殊位置
    (例 garnet 16a/24d, 自由座標 0) の座標解放はセル発散を招く (T2 実測)。一方 Pnma 4c のような
    部分特殊位置 (自由座標 x,z) は精密化する。判定は GSAS-II の GetCSxinel(site symmetry) で行う。
    """
    from GSASII import GSASIIspc as G2spc

    atoms = ph.data["Atoms"]
    cx, ct, cs, cia = ph.data["General"]["AtomPtrs"]
    labels = [row[ct - 1] for row in atoms]
    coord_atoms = []
    for row in atoms:
        try:
            free = G2spc.GetCSxinel(row[cs])[0]
            has_free = any(free)
        except Exception:
            has_free = str(row[cs]).strip() == "1"
        if has_free:
            coord_atoms.append(row[ct - 1])
    mixed = {lab for grp in spec.mixed_occupancy_groups for lab in grp}
    return {"labels": labels, "coord_atoms": coord_atoms, "mixed": mixed}


def _update_atom_flags(flag_map: dict[str, str], info: dict, stage_flags) -> bool:
    """段階フラグに応じて per-atom フラグ (X/U/F) の集合を更新する。変化があれば True。

    - coords: 一般位置原子に "X"
    - uiso: 全原子に "U"
    - occupancy: 混合占有原子に "F"
    """
    changed = False

    def add(label: str, ch: str) -> None:
        nonlocal changed
        cur = flag_map.get(label, "")
        if ch not in cur:
            flag_map[label] = "".join(c for c in "XUF" if c in cur + ch)
            changed = True

    if "coords" in stage_flags:
        for lab in info["coord_atoms"]:
            add(lab, "X")
    if "uiso" in stage_flags:
        for lab in info["labels"]:
            add(lab, "U")
    if "occupancy" in stage_flags:
        for lab in info["mixed"]:
            add(lab, "F")
    return changed


def _apply_stage(gpx, hists, phases, phase_infos, atom_flag_maps, radiations, stage):
    """段階の宣言的フラグを GSAS-II 精密化フラグへ翻訳して適用する (enable のみ)。

    revert は .gpx スナップショット復元で行うため、ここでは有効化だけを担う。
    原子フラグは GSAS-II が「置換」セマンティクスのため、per-atom の累積マップを毎回設定する。
    """
    flags = stage.flags
    if "background" in flags:
        n = int(flags["background"].get("coeffs", 6))  # type: ignore[union-attr]
        gpx.set_refinement({"set": {"Background": {"no. coeffs": n, "refine": True}}})
    # scale: GSAS-II はヒストグラムスケールを既定で精密化するため単相では no-op。
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
            # TOF の装置プロファイル (sig/alpha/beta) はキャリブレーション依存のため精密化しない。
            # TOF のピーク形状は最後の size/mustrain (HAP) で処理する (チュートリアル T4 準拠)。
            if rad.is_tof:
                continue
            hist.set_refinements({"Instrument Parameters": _profile_keys(rad)})
    if "size_strain" in flags:
        # サイズ/微小歪みは分解能の低い CW 中性子 (例 D1a) を多ヒストグラム時に除外し、
        # X 線/放射光・TOF (高分解能) に張る。理由: 低分解能 CW 中性子の幅は器械分解能に
        # 支配され試料由来の情報が乏しく、joint で張ると過剰母数化してフィットを希釈する
        # (T3 実測: X線+CW中性子で CW 中性子を外すと 8.4%→6.7%)。一方 TOF POWGEN は高分解能で
        # 試料ピーク幅情報を持つため張る (T4)。単一 or 全て CW 中性子なら全ヒストグラムに張る (T2)。
        non_lowres = [
            h for h, r in zip(hists, radiations) if r is not Radiation.NEUTRON_CW
        ]
        targets = non_lowres if (non_lowres and len(hists) > 1) else list(hists)
        for ph in phases:
            ph.set_HAP_refinements(
                {
                    "Size": {"type": "isotropic", "refine": True},
                    "Mustrain": {"type": "isotropic", "refine": True},
                },
                histograms=targets,
            )
    if "hydrostatic_strain" in flags:
        # ヒストグラム間の温度差を per-histogram の静水圧歪み Dij で吸収する (REQ-103)。
        # 格子は共有したまま各ヒストグラムに独立の実効格子ずれを許す。
        for ph in phases:
            ph.set_HAP_refinements({"HStrain": True})
    if "phase_fraction_sum" in flags:
        # 多相の相分率 (HAP Scale) を全ヒストグラムで解放する。和=1 制約は _setup_constraints で登録済み。
        for ph in phases:
            ph.set_HAP_refinements({"Scale": True}, histograms=list(hists))
    # 原子フラグ (per-atom, 累積)
    for ph, info, fmap in zip(phases, phase_infos, atom_flag_maps):
        if _update_atom_flags(fmap, info, flags):
            active = {lab: fl for lab, fl in fmap.items() if fl}
            if active:
                ph.set_refinements({"Atoms": active})


def _setup_constraints(gpx, g2phases, g2hists, specs) -> None:
    """占有率和=1・Uiso 等価 (混合占有) と相分率和=1 (多相) の制約を登録する (REQ-102/104)。

    占有率和=1 (add_EqnConstr) がないと占有率解放が発散し、Uiso 等価 (add_EquivConstr) が
    ないと少数占有原子の Uiso が発散する (T2 実測)。多相では各ヒストグラムで相分率和=1 を課す。
    """
    # 混合占有: 占有率和=1 + Uiso 等価
    for ph, spec in zip(g2phases, specs):
        if not spec.mixed_occupancy_groups:
            continue
        atoms = ph.data["Atoms"]
        ct = ph.data["General"]["AtomPtrs"][1]
        label_to_idx = {row[ct - 1]: i for i, row in enumerate(atoms)}
        pid = ph.id
        for group in spec.mixed_occupancy_groups:
            idxs = [label_to_idx[lab] for lab in group if lab in label_to_idx]
            if len(idxs) < 2:
                continue
            fracs = [f"{pid}::Afrac:{i}" for i in idxs]
            uisos = [f"{pid}::AUiso:{i}" for i in idxs]
            gpx.add_EqnConstr(1.0, fracs, [1.0] * len(fracs))
            gpx.add_EquivConstr(uisos)

    # 多相: 各ヒストグラムで相分率 (HAP Scale) 和 = 1 (REQ-104)
    if len(g2phases) > 1:
        for hist in g2hists:
            hid = hist.id
            scales = [f"{ph.id}:{hid}:Scale" for ph in g2phases]
            gpx.add_EqnConstr(1.0, scales, [1.0] * len(scales))


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


def _extract_phase_fractions(g2phases, g2hists) -> list[float]:
    """先頭ヒストグラムにおける各相の相分率 (HAP Scale) を返す (多相の和=1 検査用, M6)。

    抽出失敗の相は NaN を入れて**長さを相数に保つ** (欠落で continue すると len が縮み、
    check_validity の和=1 検査が黙って skip され偽 valid になるため)。NaN があれば和検査は fail する。
    """
    if not g2hists:
        return []
    hist = g2hists[0]
    fractions: list[float] = []
    for ph in g2phases:
        try:
            fractions.append(float(ph.getHAPvalues(hist)["Scale"][0]))
        except Exception:
            fractions.append(float("nan"))
    return fractions


def _perturb_initial_cell(ph, scale: tuple[float, float, float]) -> None:
    """相の初期格子 a/b/c を scale 倍に摂動し体積を再計算する (マルチスタート用)。

    add_phase 直後・精密化前に呼ぶ。GSAS-II の Cell 配列 [refine, a, b, c, α, β, γ, V] の
    長さ 3 成分を掛け、体積を cell2A→calc_V で整合させる (get_cell に反映される)。
    """
    from GSASII import GSASIIlattice as G2lat

    cell = ph.data["General"]["Cell"]
    a, b, c = float(cell[1]) * scale[0], float(cell[2]) * scale[1], float(cell[3]) * scale[2]
    new = [a, b, c, float(cell[4]), float(cell[5]), float(cell[6])]
    ph.data["General"]["Cell"][1:7] = new
    ph.data["General"]["Cell"][7] = G2lat.calc_V(G2lat.cell2A(new))


def run_auto_rietveld(
    histograms: Sequence[HistogramSpec],
    phases: Sequence[PhaseSpec],
    *,
    recipe: Sequence[RefinementStage] | None = None,
    reference_cells: dict[str, tuple[float, ...]] | None = None,
    ledger: Ledger | None = None,
    max_cyc: int = 12,
    worsen_eps: float = 1e-6,
    keep_gpx: str | None = None,
    initial_cell_scale: dict[str, tuple[float, float, float]] | None = None,
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
    :param initial_cell_scale: 相名→(fa,fb,fc) の初期格子摂動倍率 (マルチスタート用, None で無摂動)。
        **参照格子は摂動前の初期値を採用**する (妥当性判定を摂動でずらさないため)。
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

        # --- 参照格子 (摂動前の初期格子) を先に確保 ---
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

        # --- 初期格子摂動 (マルチスタート, 任意) ---
        if initial_cell_scale:
            for ph in g2phases:
                scale = initial_cell_scale.get(ph.name)
                if scale is not None:
                    _perturb_initial_cell(ph, scale)

        # --- 制約登録 (混合占有: 占有率和=1 + Uiso 等価; 多相: 相分率和=1) ---
        _setup_constraints(gpx, g2phases, g2hists, phases)
        phase_infos = [_phase_atom_info(ph, p) for ph, p in zip(g2phases, phases)]

        gpx.data["Controls"]["data"]["max cyc"] = max_cyc

        stage_results: list[StageResult] = []
        # 「直前の受理状態」の指標を明示追跡する (復帰時に nvar/gof を正しく巻き戻すため, H1)。
        prev_rwp = float("inf")
        prev_gof = float("inf")
        prev_nvar = 0
        atom_flag_maps: list[dict[str, str]] = [{} for _ in g2phases]

        for stage in stages:
            snap = tmp_path / "snap.gpx"
            gpx.save()
            shutil.copyfile(gpx_path, snap)
            prev_atom_flag_maps = [dict(m) for m in atom_flag_maps]
            try:
                _apply_stage(
                    gpx, g2hists, g2phases, phase_infos, atom_flag_maps, radiations, stage
                )
                gpx.do_refinements([{}])
                rwp, gof, nvar = _rvals(gpx)
                converged = _converged(gpx)
                # 格子崩壊 (0 近傍/非有限) は発散とみなし inf 化 → revert (物理妥当性ガード)
                if not _cells_physical(g2phases):
                    rwp, gof, converged = float("inf"), float("inf"), False
            except Exception as exc:  # 精密化失敗 → inf 変換 (REQ-403)
                rwp, gof, nvar, converged = float("inf"), float("inf"), 0, False
                ledger.append(
                    "m7_stage_error",
                    {"stage": stage.label, "error": repr(exc)[:200]},
                )

            reverted = False
            # 悪化 (または inf) なら直前スナップショット (この段階適用前の状態) へ revert して継続
            # (REQ-105/FR-202)。snap は各段階の冒頭で必ず取得済みなので、初段失敗でも
            # 「精密化前の健全なプロジェクト」へ戻せる (H2: prev_rwp==inf でも復帰する)。
            if not math.isfinite(rwp) or rwp > prev_rwp + worsen_eps:
                shutil.copyfile(snap, gpx_path)
                gpx = g2sc.G2Project(gpxfile=str(gpx_path))
                g2hists = gpx.histograms()
                g2phases = gpx.phases()
                phase_infos = [
                    _phase_atom_info(ph, p) for ph, p in zip(g2phases, phases)
                ]
                gpx.data["Controls"]["data"]["max cyc"] = max_cyc
                reverted = True
                atom_flag_maps = prev_atom_flag_maps
                # 復帰後の指標は「直前の受理状態」を反映する (H1: nvar も巻き戻す)。
                rwp, gof, nvar = prev_rwp, prev_gof, prev_nvar
            else:
                prev_rwp, prev_gof, prev_nvar = rwp, gof, nvar

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
        # 多相なら先頭ヒストグラムの相分率 (HAP Scale) を抽出し 和=1 制約の充足を検査する (M6)。
        # 制約は各ヒストグラムで同一 (和=1) のため代表として先頭を採る。単相は None (検査省略)。
        phase_fractions = _extract_phase_fractions(g2phases, g2hists) if len(g2phases) > 1 else None
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
