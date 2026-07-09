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
from typing import Mapping, Sequence

from ..store import Ledger
from .model import (
    AutoRietveldResult,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from .recipe import build_recipe
from .validity import check_profile_physicality, check_validity


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


def _nobs(gpx) -> int:
    """精密化に用いた実観測点数 (全ヒストグラム総和) を Covariance の Rvals から取り出す。

    レンジ制限 (two_theta_limits) 適用後の点数を反映する。未取得は 0 (利用側が代替源へ縮退)。
    """
    rv = gpx.data["Covariance"]["data"].get("Rvals", {})
    try:
        return int(rv.get("Nobs", 0))
    except (TypeError, ValueError):
        return 0


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


# 内省・物理性判定で抽出するプロファイル関連キー (CW + TOF)。
_PROFILE_INTROSPECT_KEYS = (
    "U", "V", "W", "X", "Y", "SH/L", "Zero",
    "sig-0", "sig-1", "sig-2", "alpha", "beta-0", "beta-1", "difC", "difA",
)


def _extract_profile(g2hists) -> tuple[dict[str, tuple[float, bool]], ...]:
    """各ヒストグラムの GSAS Instrument Parameters から {key: (value, refined)} を抽出する。

    GSAS 格納形は ``hist.data['Instrument Parameters'][0][key] = [default, value, refine_flag]``。
    プロファイル関連キー (_PROFILE_INTROSPECT_KEYS) のみ拾い、値・解放フラグを取り出す。
    ``Instrument Parameters`` 不在や要素構造差は当該ヒストグラムを空 dict に縮退する (EDGE-001)。
    GSAS を import しない純データ抽出のため numpy 決定論テスト可能。
    """
    out: list[dict[str, tuple[float, bool]]] = []
    for h in g2hists:
        d: dict[str, tuple[float, bool]] = {}
        try:
            inst = h.data["Instrument Parameters"][0]
        except (KeyError, IndexError, TypeError, AttributeError):
            out.append(d)
            continue
        for key in _PROFILE_INTROSPECT_KEYS:
            entry = inst.get(key) if hasattr(inst, "get") else None
            if not entry:
                continue
            try:
                if len(entry) >= 2:
                    val = float(entry[1])
                    ref = bool(entry[2]) if len(entry) >= 3 else False
                else:
                    val = float(entry[0])
                    ref = False
            except (IndexError, TypeError, ValueError):
                continue
            d[key] = (val, ref)
        out.append(d)
    return tuple(out)


def _profile_ranges(
    g2hists, radiations, profiles, histograms=None
) -> tuple[tuple[float, float] | None, ...]:
    """各ヒストグラムのプロファイル評価レンジ (CW=2θ°, TOF=d) を返す。

    評価レンジは **精密化に用いる区間** に限定する: getdata("x") の観測範囲を、指定があれば
    HistogramSpec.two_theta_limits で切り詰める。プロファイルはこの区間でのみ実際に使われるため、
    区間外 (ノイズ tail 等) の幅関数負値で誤 revert しないための処置 (T4 非回帰)。TOF は切り詰め後の
    範囲 (TOF μs) を d≈(t-Zero)/difC で d に換算する (difC,Zero は profiles から)。getdata 失敗・空・
    difC 欠落/0 は None に縮退し、利用側がレンジ依存判定を skip する (EDGE-003)。
    """
    out: list[tuple[float, float] | None] = []
    for i, (h, rad, prof) in enumerate(zip(g2hists, radiations, profiles)):
        try:
            xs = h.getdata("x")
        except Exception:  # noqa: BLE001 — 取得失敗は非致命 skip
            out.append(None)
            continue
        if xs is None or len(xs) == 0:
            out.append(None)
            continue
        lo, hi = float(min(xs)), float(max(xs))
        # 精密化レンジ (two_theta_limits) で切り詰める (残差抽出のマスクと同じ区間)。
        if histograms is not None and i < len(histograms):
            lim = histograms[i].two_theta_limits
            if lim is not None:
                lo, hi = max(lo, float(lim[0])), min(hi, float(lim[1]))
                if lo >= hi:  # 交差が空 (限界指定が観測外) → レンジ判定を skip
                    out.append(None)
                    continue
        if getattr(rad, "is_tof", False):
            dif_c = prof.get("difC", (0.0, False))[0]
            zero = prof.get("Zero", (0.0, False))[0]
            if dif_c == 0.0:
                out.append(None)
                continue
            d_lo, d_hi = (lo - zero) / dif_c, (hi - zero) / dif_c
            out.append((min(d_lo, d_hi), max(d_lo, d_hi)))
        else:
            out.append((lo, hi))
    return tuple(out)


def _profiles_physical(g2hists, radiations, histograms=None) -> ValidityReport:
    """プロファイル物理性を判定する薄いラッパ (_cells_physical と同格の revert ガード用)。

    抽出不能 (全 hist が空 dict) は passed=True に縮退する (判定 skip, EDGE-001)。
    """
    profiles = _extract_profile(g2hists)
    if not any(profiles):
        return ValidityReport(passed=True)
    ranges = _profile_ranges(g2hists, radiations, profiles, histograms)
    return check_profile_physicality(
        profiles=profiles, radiations=radiations, ranges=ranges
    )


def _profile_keys(radiation: Radiation) -> list[str]:
    """CW (X 線/中性子) の Gaussian プロファイル係数キー U,V,W。

    Lorentzian (X,Y) + Zero は別段階 (recipe の "profile_lorentzian") で revert ガード付きで追加する
    (同段階に混ぜると悪化時に U,V,W ごと revert され T3/T4 が回帰するため分離)。TOF は本段階では
    精密化しない (呼び出し側でスキップ)。TOF の装置プロファイル (sig/alpha/beta) はキャリブレーション
    依存で、ピーク形状は size/mustrain で処理する。
    """
    return ["U", "V", "W"]


def _tof_profile_keys() -> list[str]:
    """TOF (PNT) 装置プロファイルの較正キー。

    近似 instprm (Z-Code Type0m → GSAS PNT の変換で厳密でない sig/alpha/beta) を実測へ寄せる較正用。
    支配的な **Gaussian 幅の d 依存 (sig-1/sig-2)** のみに限定する。alpha/beta (立ち上がり/減衰) は
    ``1/alpha``・``1/beta`` を含みゼロ近傍で発散するため既定では解放しない (実 GSAS で div-by-zero を確認)。
    opt-in 段階 (既定レシピには含めない, T4 非回帰)。実測で幅較正が Rwp を改善する (17.3→16.2%)。
    """
    return ["sig-1", "sig-2"]


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
    # 座標凍結ラベル (剛体固定原子) は coords 段の解放対象から除く。
    frozen = set(spec.frozen_coord_labels)
    if frozen:
        coord_atoms = [lab for lab in coord_atoms if lab not in frozen]
    mixed = {lab for grp in spec.mixed_occupancy_groups for lab in grp}
    free_occ = set(spec.free_occupancy_labels)
    equiv_occ = {lab for grp in spec.occupancy_equiv_groups for lab in grp}
    sum_occ = {lab for grp in spec.occupancy_sum_groups for lab in grp}
    return {
        "labels": labels, "coord_atoms": coord_atoms,
        "mixed": mixed, "free_occ": free_occ, "equiv_occ": equiv_occ | sum_occ,
        "uiso_labels": list(spec.free_uiso_labels),
    }


def _update_atom_flags(flag_map: dict[str, str], info: dict, stage_flags) -> bool:
    """段階フラグに応じて per-atom フラグ (X/U/F) の集合を更新する。変化があれば True。

    - coords: 一般位置原子に "X"
    - uiso: 全原子に "U"
    - occupancy: 混合占有原子 + 単独解放原子 (free_occ) に "F"
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
        # free_uiso_labels 指定時はその原子のみ、未指定なら全原子の Uiso を解放。
        uiso_targets = info.get("uiso_labels") or info["labels"]
        for lab in uiso_targets:
            add(lab, "U")
    if "occupancy" in stage_flags:
        for lab in info["mixed"]:
            add(lab, "F")
        for lab in info.get("free_occ", set()):
            add(lab, "F")
        for lab in info.get("equiv_occ", set()):
            add(lab, "F")  # 等値グループ (例 Fe=C=N) も解放 ([0,1] 拘束は張らない)
    return changed


def _fixed_profile_flags(histograms) -> list[bool]:
    """各ヒストグラムが装置プロファイル固定か (instrument_profile 指定) を返す (numpy, Issue #38)。"""
    return [getattr(h, "instrument_profile", None) is not None for h in histograms]


def _seed_instrument_profile(g2hist, profile) -> None:
    """InstrumentProfile.values を GSAS Instrument Parameters に書き込む (GSAS 依存, Issue #38)。

    inst[0][key][1] = value。存在しないキー・構造差は無視する (EDGE-001)。
    """
    try:
        inst = g2hist.data["Instrument Parameters"][0]
    except (KeyError, IndexError, TypeError, AttributeError):
        return
    for key, val in profile.values.items():
        entry = inst.get(key) if hasattr(inst, "get") else None
        if entry is None or len(entry) < 2:
            continue
        try:
            entry[1] = float(val)
        except (TypeError, ValueError):
            continue


def _apply_stage(
    gpx, hists, phases, phase_infos, atom_flag_maps, radiations, stage, fixed_profile=None
):
    """段階の宣言的フラグを GSAS-II 精密化フラグへ翻訳して適用する (enable のみ)。

    revert は .gpx スナップショット復元で行うため、ここでは有効化だけを担う。
    原子フラグは GSAS-II が「置換」セマンティクスのため、per-atom の累積マップを毎回設定する。
    `fixed_profile[i]=True` のヒストグラムは装置プロファイル (U,V,W/X,Y/SH·L) を解放しない (Issue #38)。
    """
    if fixed_profile is None:
        fixed_profile = [False] * len(hists)
    flags = stage.flags
    if "background" in flags:
        bg = flags["background"]
        default_n = int(bg.get("coeffs", 6))  # type: ignore[union-attr]
        by_index = bg.get("by_index", {})  # type: ignore[union-attr]
        bg_type = bg.get("type")  # type: ignore[union-attr]
        # ヒストグラム毎に背景項数を設定 (ND は正規化 TOF で背景が支配的なため過剰項を避け少なめに)。
        for i, hist in enumerate(hists):
            n = int(by_index.get(i, default_n))
            spec = {"no. coeffs": n, "refine": True}
            if bg_type is not None:
                spec["type"] = bg_type
            hist.set_refinements({"Background": spec})
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
        # フラグ値がキー列なら**そのキー集合**を解放する (分解能抽出で U,V,W,X,Y を同時解放して
        # 相関局所解を脱出するため; GSAS set_refinements は Instrument Parameters を置換するので
        # 別段階に分けると先の U,V,W が凍結される)。True/未指定なら CW 既定 U,V,W (build_recipe 互換)。
        pf = flags["profile"]
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            # TOF の装置プロファイル (sig/alpha/beta) はキャリブレーション依存のため精密化しない。
            # TOF のピーク形状は最後の size/mustrain (HAP) で処理する (チュートリアル T4 準拠)。
            if rad.is_tof or fixed_profile[i]:
                continue
            keys = list(pf) if isinstance(pf, (list, tuple)) else _profile_keys(rad)
            hist.set_refinements({"Instrument Parameters": keys})
    if "absorption" in flags:
        # 試料吸収を解放する opt-in 段階。TOF 中性子は λ(=TOF) 依存吸収でピーク強度の d 依存を補正
        # (Cu/Fe 等の吸収)。既定レシピ非搭載。悪化時は本段階ごと revert。
        for hist in hists:
            hist.set_refinements({"Sample Parameters": ["Absorption"]})
    if "tof_profile" in flags:
        # TOF 装置プロファイル (sig/alpha/beta) を較正する opt-in 段階。既定レシピには含めない
        # (T4 非回帰)。近似 instprm 初期値を実測へ寄せ ND フィットを改善する。悪化時は本段階ごと revert。
        # フラグ値がリストならそのキー集合、True なら既定キー (_tof_profile_keys)。
        tp = flags["tof_profile"]
        keys = list(tp) if isinstance(tp, (list, tuple)) else _tof_profile_keys()
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            if not rad.is_tof:
                continue
            hist.set_refinements({"Instrument Parameters": keys})
    if "preferred_orientation" in flags:
        # 選択配向 (preferred orientation) を解放する opt-in 段階。既定レシピには含めない。
        # 値が偶数なら球面調和 (SH) その次数、1 なら March-Dollase、True なら SH order 4。PBA 等の
        # 系統的ピーク強度ズレ (obs>calc) を配向分布で吸収する。悪化時は本段階ごと revert。
        val = flags["preferred_orientation"]
        order = 4 if val is True else int(val)
        for ph in phases:
            try:
                ph.HAPvalue("Pref.Ori.", order)
            except Exception:
                pass
            ph.set_HAP_refinements({"Pref.Ori.": True}, histograms=list(hists))
    if "profile_lorentzian" in flags:
        # Lorentzian (X,Y) + Zero を X 線に追加解放する (別段階, revert ガード)。実験室/放射光 X 線は
        # Lorentzian 成分が支配的で U,V,W だけでは実測ピーク形状に合わない (CaTeO3: 43%→13%)。悪化時は
        # 本段階ごと revert され U,V,W は保持される (T3/T4 非回帰)。TOF/中性子は除外。
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            if rad.is_tof or rad.is_neutron or fixed_profile[i]:
                continue
            hist.set_refinements({"Instrument Parameters": ["X", "Y", "Zero"]})
    if "profile_asymmetry" in flags:
        # 軸発散非対称 (SH/L) を X 線に別段階で追加解放する (分割擬フォークト相当の経験的ピーク形状;
        # 物理解釈を要さない)。低角の非対称に効くが常には改善しないため X,Y,Zero とは分け、悪化時は
        # 本段階のみ revert する (X,Y,Zero を保持)。TOF/中性子は除外。
        for i, hist in enumerate(hists):
            rad = radiations[i] if i < len(radiations) else Radiation.XRAY_LAB
            if rad.is_tof or rad.is_neutron or fixed_profile[i]:
                continue
            hist.set_refinements({"Instrument Parameters": ["SH/L"]})
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


def _bound_occupancy(gpx, frac: str) -> None:
    """占有率パラメータを物理範囲 [0,1] に登録拘束する (GSAS-II parmMin/parmMax)。

    範囲外へ出た占有率は GSAS-II が境界で凍結する (dropOOBvars)。部分占有水など**単独解放**
    (free_occupancy_labels) の占有率が [0,1] を外れるのを防ぐ。

    注意: **占有率和=1 (add_EqnConstr) を張った共有サイトには効かない**。和=1 拘束下では GSAS-II は
    個々の Afrac でなく制約生成変数を varyList に入れるため、個別 Afrac の parmMin/parmMax は
    freeze 判定に載らない (NaCuHCF の Na2/O1 は和=1 のため境界を超えても凍結されない)。共有サイトの
    非物理占有は**正しいモデル選択で解消する**のが本筋 (model5→model6 で Ow が過剰密度を吸収し物理化)。
    """
    try:
        gpx.set_Controls("parmMin", 0.0, variable=frac)
        gpx.set_Controls("parmMax", 1.0, variable=frac)
    except Exception:
        # 古い GSAS-II で parmMin/parmMax 未対応でも精密化自体は継続させる (ガードのみ諦める)。
        pass


def _apply_profile_bounds(gpx, histograms) -> None:
    """`HistogramSpec.profile_bounds` を GSAS parmMin/parmMax に登録する (Issue #38 拘束抽出)。

    装置パラメータの変数名は ``:{hist_index}:{key}`` (例 ``:0:X``)。片側 None は登録しない。
    分解能抽出で U,W,X,Y≥0 を課し、相関非物理解 (負の Lorentzian) を避け転写可能な分解能を得る。
    古い GSAS で parmMin/parmMax 未対応でも精密化継続 (拘束のみ諦める, `_bound_occupancy` 流儀)。
    """
    for i, h in enumerate(histograms):
        bounds = getattr(h, "profile_bounds", None)
        if not bounds:
            continue
        for key, (lo, hi) in bounds.items():
            var = f":{i}:{key}"
            try:
                if lo is not None:
                    gpx.set_Controls("parmMin", float(lo), variable=var)
                if hi is not None:
                    gpx.set_Controls("parmMax", float(hi), variable=var)
            except Exception:  # noqa: BLE001 — 拘束未対応でも継続
                pass


def _equiv_positions(gpx, pid, idxs) -> None:
    """原子群の座標 (dAx/dAy/dAz shift) を等値拘束する (共有サイト/共位置を保つ)。

    GSAS-II の座標精密化は shift 変数 (dAx 等) で行うため、shift を等値にすれば共位置の原子が
    同じだけ動き相対位置を保つ (初期共位置が前提)。特殊位置で解放座標が無い成分は GSAS 側で無視される。
    """
    if len(idxs) < 2:
        return
    for coord in ("dAx", "dAy", "dAz"):
        try:
            gpx.add_EquivConstr([f"{pid}::{coord}:{i}" for i in idxs])
        except Exception:
            pass


def _setup_constraints(gpx, g2phases, g2hists, specs) -> None:
    """占有率和=1・Uiso 等価 (混合占有) と相分率和=1 (多相) の制約を登録する (REQ-102/104)。

    占有率和=1 (add_EqnConstr) がないと占有率解放が発散し、Uiso 等価 (add_EquivConstr) が
    ないと少数占有原子の Uiso が発散する (T2 実測)。混合占有・単独解放の占有率は物理範囲 [0,1] に
    拘束する。多相では各ヒストグラムで相分率和=1 を課す。
    """
    # 混合占有: 占有率和=1 + Uiso 等価 + [0,1] 拘束。単独解放 (free_occ) も [0,1] 拘束。
    for ph, spec in zip(g2phases, specs):
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
            for frac in fracs:
                _bound_occupancy(gpx, frac)
            # 共有サイトは共位置: 座標 (dAx/dAy/dAz) も等値拘束する。
            _equiv_positions(gpx, pid, idxs)
        # 明示的な座標等値グループ (共位置 H/D 対など)。
        for group in spec.position_equiv_groups:
            pidx = [label_to_idx[lab] for lab in group if lab in label_to_idx]
            if len(pidx) >= 2:
                _equiv_positions(gpx, pid, pidx)
        for lab in spec.free_occupancy_labels:
            if lab in label_to_idx:
                _bound_occupancy(gpx, f"{pid}::Afrac:{label_to_idx[lab]}")
        # 占有率等値 (D₂O の D を親水 O に連動): add_EquivConstr で 1 変数に束ねる。
        for group in spec.occupancy_equiv_groups:
            idxs = [label_to_idx[lab] for lab in group if lab in label_to_idx]
            if len(idxs) >= 2:
                gpx.add_EquivConstr([f"{pid}::Afrac:{i}" for i in idxs])
        # 占有率和 (H/D ミキシング): (親, 子1, 子2, ...) で Σ子 − 親 = 0 を課す。
        for group in spec.occupancy_sum_groups:
            if len(group) < 2 or group[0] not in label_to_idx:
                continue
            parent = label_to_idx[group[0]]
            children = [label_to_idx[lab] for lab in group[1:] if lab in label_to_idx]
            if not children:
                continue
            variables = [f"{pid}::Afrac:{i}" for i in children] + [f"{pid}::Afrac:{parent}"]
            gpx.add_EqnConstr(0.0, variables, [1.0] * len(children) + [-1.0])

    # 多相: 各ヒストグラムで相分率 (HAP Scale) 和 = 1 (REQ-104)
    if len(g2phases) > 1:
        for hist in g2hists:
            hid = hist.id
            scales = [f"{ph.id}:{hid}:Scale" for ph in g2phases]
            gpx.add_EqnConstr(1.0, scales, [1.0] * len(scales))


def _apply_bond_restraints(gpx, g2phases, bond_restraints) -> None:
    """相名→結合距離ソフト拘束を GSAS-II Bond restraint として登録する (O–H/D 漂流防止)。

    ``ph.addDistRestraint`` は**現在座標**で origin×target の距離が ``[bond/factor, bond*factor]`` に入る
    対を探して登録するため、**初期座標が理想幾何のうちに呼ぶ**必要がある (呼出は精密化開始前)。
    拘束は gpx データツリーに保存され revert (スナップショット復元) 後も保持される。GSAS 未対応・
    ラベル不一致は当該拘束のみスキップして継続する (EDGE)。
    """
    if not bond_restraints:
        return
    rroot = gpx.data.setdefault("Restraints", {"data": {}})
    rdata = rroot.setdefault("data", {})
    for ph in g2phases:
        specs = bond_restraints.get(ph.name)
        if not specs:
            continue
        # 相ごとの Bond 拘束ツリーを初期化 (addDistRestraint が参照する既定構造)。
        entry = rdata.setdefault(ph.name, {})
        entry.setdefault("Bond", {"wtFactor": 1.0, "Range": 1.1, "Bonds": [], "Use": True})
        weight = 1000.0
        for spec in specs:
            origin = [str(a) for a in spec["origin"]]  # type: ignore[index]
            target = [str(a) for a in spec["target"]]  # type: ignore[index]
            dist = float(spec["distance"])  # type: ignore[index]
            esd = float(spec.get("esd", 0.02))  # type: ignore[union-attr]
            factor = float(spec.get("factor", 1.5))  # type: ignore[union-attr]
            weight = float(spec.get("weight", weight))  # type: ignore[union-attr]
            try:
                ph.addDistRestraint(origin, target, dist, factor=factor, ESD=esd)
            except Exception:  # noqa: BLE001 — ラベル不一致/未対応はスキップし継続
                continue
        try:
            ph.setDistRestraintWeight(weight)
        except Exception:  # noqa: BLE001
            pass


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


def _phase_fraction_map(g2phases, g2hists) -> dict[str, float]:
    """相名→相分率 (先頭ヒストグラムの HAP Scale, 和=1 正規化) を返す (M9 逐次解析用)。

    単相は {name: 1.0}。多相は HAP Scale を抽出し総和で正規化する (和=1 制約下では概ね規格化済み)。
    抽出失敗の相は 0.0 を入れる。名前重複時は後勝ち (相名は一意想定)。
    """
    if not g2phases:
        return {}
    if len(g2phases) == 1:
        return {g2phases[0].name: 1.0}
    fracs = _extract_phase_fractions(g2phases, g2hists)  # g2phases 順に整列
    total = sum(f for f in fracs if math.isfinite(f) and f > 0)
    out: dict[str, float] = {}
    for ph, f in zip(g2phases, fracs):
        val = float(f) if math.isfinite(f) else 0.0
        out[ph.name] = (val / total) if total > 0 else 0.0
    return out


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


def _set_initial_cell(ph, cell: tuple[float, ...]) -> None:
    """相の初期格子を絶対値 cell=(a,b,c[,α,β,γ]) に設定し体積を再計算する (ウォームスタート用)。

    add_phase 直後・精密化前に呼ぶ。逐次 (sequential) 精密化で直前フレームの精密化格子を次フレームの
    初期値として引き継ぐのに用いる。角度は与えられなければ現在値を保つ。``initial_cell_scale``
    (相対摂動) と排他: こちらは絶対セルを与える。
    """
    from GSASII import GSASIIlattice as G2lat

    cur = ph.data["General"]["Cell"]
    a, b, c = float(cell[0]), float(cell[1]), float(cell[2])
    alpha = float(cell[3]) if len(cell) > 3 else float(cur[4])
    beta = float(cell[4]) if len(cell) > 4 else float(cur[5])
    gamma = float(cell[5]) if len(cell) > 5 else float(cur[6])
    new = [a, b, c, alpha, beta, gamma]
    ph.data["General"]["Cell"][1:7] = new
    ph.data["General"]["Cell"][7] = G2lat.calc_V(G2lat.cell2A(new))


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
    initial_cells: dict[str, tuple[float, ...]] | None = None,
    bond_restraints: dict[str, Sequence[Mapping[str, object]]] | None = None,
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
    :param bond_restraints: 相名→結合距離ソフト拘束の列 (GSAS-II Bond restraint)。各拘束は
        ``{"origin": (ラベル…), "target": (ラベル…), "distance": Å, "esd": Å, "factor": 探索係数,
        "weight": wtFactor}`` の dict。**初期座標が理想幾何のうちに**登録し、精密化中に O–H/D 結合長が
        理想値から外れる罰を与える (無秩序水の軽原子座標の漂流を防ぐ; 配向は自由)。既定 None (拘束なし)。
    :param initial_cell_scale: 相名→(fa,fb,fc) の初期格子摂動倍率 (マルチスタート用, None で無摂動)。
        **参照格子は摂動前の初期値を採用**する (妥当性判定を摂動でずらさないため)。
    :param initial_cells: 相名→(a,b,c[,α,β,γ]) の絶対初期格子 (逐次精密化のウォームスタート用,
        None で CIF 既定)。直前フレームの精密化格子を次フレームの初期値に引き継ぐのに用いる。
        ``initial_cell_scale`` と併用時は本絶対セルを先に適用し、その上に摂動倍率を掛ける。
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
            if h.weight != 1.0:
                # ヒストグラム重み係数 (GSAS-II wtFactor)。joint の相対重み調整。
                try:
                    hist.data["data"][0]["wtFactor"] = float(h.weight)
                except (KeyError, IndexError, TypeError):
                    pass
            if h.absorption != 0.0:
                # 試料吸収係数の初期値 (Sample Parameters Absorption)。TOF は λ 依存吸収を与える。
                try:
                    hist.data["Sample Parameters"]["Absorption"][0] = float(h.absorption)
                except (KeyError, IndexError, TypeError):
                    pass
            if h.instrument_profile is not None:
                # 標準試料から実測した装置分解能を seed し、以降の段階解放では固定する (Issue #38)。
                _seed_instrument_profile(hist, h.instrument_profile)
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

        # --- 参照格子 (妥当性判定の基準) を先に確保 ---
        # 既定は各相の CIF 初期格子。ただしウォームスタート (initial_cells) を与えた相は、その
        # **前フレームの精密化格子**を参照にする (逐次精密化 M9): 高温系列では格子が熱膨張で CIF
        # 室温値から系統的にずれるため、CIF 基準だと後半フレームが必ず妥当性 fail し、格子ドリフトを
        # 理由に転移フレームの新相を誤棄却する。フレーム間ドリフト基準なら滑らかな系列は各段小さく
        # 妥当、真の急変 (転移) のみ検出できる。新規追加相 (initial_cells になし) は CIF 基準のまま。
        if reference_cells is None:
            reference_cells = {}
            for ph in g2phases:
                cif_cell = tuple(
                    float(ph.get_cell()[k])
                    for k in (
                        "length_a", "length_b", "length_c",
                        "angle_alpha", "angle_beta", "angle_gamma",
                    )
                )
                seed = initial_cells.get(ph.name) if initial_cells else None
                if seed is not None:
                    reference_cells[ph.name] = (
                        float(seed[0]), float(seed[1]), float(seed[2]),
                        float(seed[3]) if len(seed) > 3 else cif_cell[3],
                        float(seed[4]) if len(seed) > 4 else cif_cell[4],
                        float(seed[5]) if len(seed) > 5 else cif_cell[5],
                    )
                else:
                    reference_cells[ph.name] = cif_cell

        # --- 初期格子ウォームスタート (逐次精密化, 任意): 絶対セルを先に適用 ---
        if initial_cells:
            for ph in g2phases:
                cell = initial_cells.get(ph.name)
                if cell is not None:
                    _set_initial_cell(ph, cell)

        # --- 初期格子摂動 (マルチスタート, 任意) ---
        if initial_cell_scale:
            for ph in g2phases:
                scale = initial_cell_scale.get(ph.name)
                if scale is not None:
                    _perturb_initial_cell(ph, scale)

        # --- 制約登録 (混合占有: 占有率和=1 + Uiso 等価; 多相: 相分率和=1) ---
        _setup_constraints(gpx, g2phases, g2hists, phases)
        # 結合距離ソフト拘束 (初期座標が理想幾何のうちに登録; O–H/D の漂流防止)。
        _apply_bond_restraints(gpx, g2phases, bond_restraints)
        # 装置パラメータの物理拘束 (profile_bounds; 分解能抽出の U,W,X,Y≥0 等) を登録する (Issue #38)。
        _apply_profile_bounds(gpx, histograms)
        phase_infos = [_phase_atom_info(ph, p) for ph, p in zip(g2phases, phases)]
        # 装置プロファイル固定 (instrument_profile 指定) の per-hist フラグ (Issue #38)。
        fixed_profile = _fixed_profile_flags(histograms)

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
                    gpx, g2hists, g2phases, phase_infos, atom_flag_maps, radiations, stage,
                    fixed_profile,
                )
                gpx.do_refinements([{}])
                rwp, gof, nvar = _rvals(gpx)
                converged = _converged(gpx)
                # 格子崩壊 (0 近傍/非有限) またはプロファイル非物理化 (幅関数がレンジ内で負・散乱/立上り
                # 係数が非物理) は発散とみなし inf 化 → 既存 revert 経路 (物理妥当性ガード)。
                # プロファイルガードは解放済パラメータのみ hard 判定するため T1〜T4 は非回帰。
                if not _cells_physical(g2phases) or not _profiles_physical(
                    g2hists, radiations, histograms
                ).passed:
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

        # --- プロファイル内省 + 物理性 (最終状態) ---
        # hist_profile を充填 (TASK-0001 で追加済・未配線だった内省フィールドを生かす → diagnose_residual
        # が実プロファイル値を使える)。物理性の checks/warnings (soft 上限含む) を validity にマージする。
        prof_full = _extract_profile(g2hists)
        prof_ranges = _profile_ranges(g2hists, radiations, prof_full, histograms)
        prof_report = (
            check_profile_physicality(
                profiles=prof_full, radiations=radiations, ranges=prof_ranges
            )
            if any(prof_full)
            else ValidityReport(passed=True)
        )
        validity = ValidityReport(
            passed=validity.passed and prof_report.passed,
            checks=validity.checks + prof_report.checks,
            warnings=validity.warnings + prof_report.warnings,
        )
        hist_profile = tuple({k: v for k, (v, _) in d.items()} for d in prof_full)

        final_rwp = stage_results[-1].rwp if stage_results else float("inf")
        final_gof = stage_results[-1].gof if stage_results else float("inf")
        final_nobs = _nobs(gpx) if stage_results else 0
        phase_fractions = _phase_fraction_map(g2phases, g2hists)
        resid_tt, resid_int, resid_sig = _extract_residual(g2hists, histograms)

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
        n_obs=final_nobs,
        phase_fractions=phase_fractions,
        residual_two_theta=resid_tt,
        residual_intensity=resid_int,
        residual_sigma=resid_sig,
        hist_profile=hist_profile,
    )


def _extract_residual(
    g2hists, histograms
) -> tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]:
    """先頭ヒストグラムの (2θ, Yobs−Ycalc, σ) を精密化レンジ内で返す (残差 S/N 判定用)。

    GSAS の getdata('Residual')=obs−calc、getdata('yweight')=1/σ² (計数統計の重み)。σ=1/√weight。
    レンジ外は calc=0 で残差=obs の偽ピークになるため two_theta_limits でマスクする。取得不能
    (getdata 失敗) は空タプルに縮退。numpy 不使用。
    """
    if not g2hists:
        return (), (), ()
    try:
        h0 = g2hists[0]
        xs = list(h0.getdata("x"))
        resid = list(h0.getdata("Residual"))
        weights = list(h0.getdata("yweight"))
    except Exception:
        return (), (), ()
    lim = histograms[0].two_theta_limits if histograms else None
    out_x: list[float] = []
    out_r: list[float] = []
    out_s: list[float] = []
    for xi, ri, wi in zip(xs, resid, weights):
        fx = float(xi)
        if lim is not None and not (lim[0] <= fx <= lim[1]):
            continue
        out_x.append(fx)
        out_r.append(float(ri))
        fw = float(wi)
        out_s.append((1.0 / math.sqrt(fw)) if fw > 0 else float("inf"))
    return tuple(out_x), tuple(out_r), tuple(out_s)


def _data_fmthint(h: HistogramSpec) -> str:
    """HistogramSpec.data_format を GSAS-II importer ヒントへ写像する。"""
    return {
        "GSAS": "GSAS",
        "FXYE": "GSAS",  # .fxye も GSAS powder importer が読む
        "XYE": "xye",
        "XRDML": "Panalytical",  # Panalytical xrdml (xml) importer (実験室 X 線 in situ)
    }.get(h.data_format, "GSAS")
