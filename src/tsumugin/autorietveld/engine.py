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

import numpy as np

from .._json import finite_or_none
from ..store import Ledger
from .absorption import apply_absorption_correction
from .model import (
    AutoRietveldResult,
    CellEsd,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from .recipe import build_recipe
from .validity import (
    check_initial_uiso,
    check_profile_physicality,
    check_validity,
    warn_occupancy_uiso_coupling,
)


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


def _cells_physical(
    g2phases, min_length: float = 0.5, max_length: float = 1000.0
) -> bool:
    """全相の格子が物理的 (有限・妥当な長さ・幾何学的に可能な計量テンソル) かを判定する。

    多相・高分解能データではプロファイル/サイズ解放時に格子が 0 へ崩壊する発散が起こり得る
    (近ゼロ崩壊)。加えて Issue #49: 少数相の相分率が 0 に近づくと格子が悪条件化し、
    近ゼロ崩壊とは逆に長さが桁違いに**爆発**したり、角度が幾何学的に不可能な組み合わせ
    (計量テンソルが非正定値 = "Invalid cell metric tensor") に発散する場合がある。
    これらは chi2=inf 化されず validity のみ False になって結果に残留し得るため、
    revert 対象として検出する。参照格子 (前フレーム/CIF) に依存しないため operando の
    フレーム単位判定にもそのまま使える。

    判定は 3 種:
    1. 近ゼロ崩壊: a/b/c いずれかが非有限、または min_length 未満。
    2. 爆発: a/b/c いずれかが max_length を超過。
    3. 無効計量テンソル: α/β/γ が非有限、または体積項
       t = 1 - cos²α - cos²β - cos²γ + 2·cosα·cosβ·cosγ が非有限あるいは 0 以下
       (退化・非正定値 = 幾何学的に構成不可能な格子)。
    """
    for ph in g2phases:
        cell = ph.get_cell()
        for key in ("length_a", "length_b", "length_c"):
            v = float(cell[key])
            if not math.isfinite(v) or v < min_length or v > max_length:
                return False

        angles = []
        for key in ("angle_alpha", "angle_beta", "angle_gamma"):
            a = float(cell[key])
            if not math.isfinite(a):
                return False
            angles.append(a)
        alpha, beta, gamma = (math.radians(a) for a in angles)
        ca, cb, cg = math.cos(alpha), math.cos(beta), math.cos(gamma)
        t = 1.0 - ca * ca - cb * cb - cg * cg + 2.0 * ca * cb * cg
        if not math.isfinite(t) or t <= 0.0:
            return False
    return True


# 内省・物理性判定で抽出するプロファイル関連キー (CW + TOF)。
# Lam (波長) は較正 (calibrate_instrument_from_standard, Issue #61) で hist_profile に露出するため含める。
# FWHM/物理性判定は U,V,W,X,Y のみを用いるので Lam の追加は非破壊 (余分キーは無視される)。
_PROFILE_INTROSPECT_KEYS = (
    "Lam", "U", "V", "W", "X", "Y", "SH/L", "Zero",
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
        "refine_cell": spec.refine_cell,
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


def _should_refine_cell(info: dict, fraction: float | None, threshold: float | None) -> bool:
    """相のセル (格子) 解放可否を判定する (Issue #47 手動凍結 + Issue #80 自動閾値凍結)。

    ⚠ **`fraction`/`threshold` の basis は `phase_fractions` (= HAP Scale の Σ=1 正規化値) であり、
    `phase_weight_fractions` (wt%) ではない** (`_phase_fraction_map` 由来)。**答えは basis で割れる**:
    実測 K₂Mn[Fe(CN)₆] (cubic 1103.4 / tetra 517.8 amu) の `Scale {cubic .75, tetra .25}` は
    `wt% {cubic .865, tetra .135}` であり、`threshold=0.2` は **Scale では tetra を解放し wt% では
    凍結する**。出版値は wt% なので、閾値を wt% の直感で決めると静かに外れる (③ 側の警告は
    `skills/insitu`・`skills/operando-diagnose`・`AGENT_PLAYBOOK` の「分率の閾値は Scale 基準」節)。

    判定優先順位 (手動 > 自動 > 既定解放):

    1. 明示 ``PhaseSpec.refine_cell=False`` (手動, Issue #47) は常に優先し凍結する。
       自動閾値の有無や分率に関わらず解放しない (**手動が自動に勝つ**)。
    2. 自動閾値 (``threshold``) が ``None`` → 従来動作 (非回帰): 分率を見ず解放する。
    3. 分率が不明 (``fraction=None``, 例: 相分率抽出に失敗/精密化前で未取得) →
       **fail open** (凍結しない)。少数相と誤認して全相を凍結する事故を避ける。
    4. 分率が ``threshold`` 未満 → 自動凍結 (計量が近い相同士の相関による発散を防ぐ, Issue #80)。
    5. それ以外 (分率が閾値以上, 単相の分率 1.0 を含む) → 解放。
    """
    if not info.get("refine_cell", True):
        return False
    if threshold is None:
        return True
    if fraction is None:
        return True
    return fraction >= threshold


def _apply_stage(
    gpx, hists, phases, phase_infos, atom_flag_maps, radiations, stage, fixed_profile=None,
    auto_freeze_minor_cells: float | None = None,
) -> list[str]:
    """段階の宣言的フラグを GSAS-II 精密化フラグへ翻訳して適用する (enable のみ)。

    revert は .gpx スナップショット復元で行うため、ここでは有効化だけを担う。
    原子フラグは GSAS-II が「置換」セマンティクスのため、per-atom の累積マップを毎回設定する。
    `fixed_profile[i]=True` のヒストグラムは装置プロファイル (U,V,W/X,Y/SH·L) を解放しない (Issue #38)。

    :param auto_freeze_minor_cells: 分率連動の自動セル凍結閾値 (Issue #80)。**basis は Scale**
        (``_phase_fraction_map``; wt% ではない — `_should_refine_cell` 参照)。None で無効
        (従来動作)。有効時は "cell" 段の適用時点で ``_phase_fraction_map`` により**その時点の
        live な** g2phases/g2hists から相分率を取得し (フラグ解放前の直近値; 分率段が未実行の
        単相/初期状態では 1.0 または初期 Scale)、閾値未満の相のみ自動凍結する。
    :returns: この呼び出しで自動閾値により凍結された相名のリスト (手動凍結は含まない;
        cell 段以外や凍結なしなら空リスト)。ledger/StageResult で挙動を可視化するため。
    """
    auto_frozen: list[str] = []
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
        # refine_cell=False の相 (副相/不純物の格子固定, Issue #47) は Cell 解放をスキップする。
        # auto_freeze_minor_cells 有効時は加えて、この段階適用時点の live な相分率
        # (_phase_fraction_map, Issue #80) が閾値未満の相も自動でスキップする (手動 > 自動)。
        fraction_map: dict[str, float] | None = None
        if auto_freeze_minor_cells is not None:
            try:
                fraction_map = _phase_fraction_map(phases, hists)
            except Exception:  # noqa: BLE001 — 分率抽出不能は fail open (凍結しない)
                fraction_map = None
        for ph, info in zip(phases, phase_infos):
            fraction = fraction_map.get(ph.name) if fraction_map else None
            if _should_refine_cell(info, fraction, auto_freeze_minor_cells):
                ph.set_refinements({"Cell": True})
            elif info.get("refine_cell", True) and fraction is not None:
                # 手動凍結ではなく自動閾値により凍結された相のみ記録する。
                auto_frozen.append(ph.name)
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
        # フラグ値が文字列なら mustrain type を選択 (isotropic/uniaxial/generalized)。True は既定
        # isotropic (後方互換)。**異方 (uniaxial/generalized) は X 線に限定**する: 中性子 (特に TOF)
        # はピーク幅が装置分解能関数 (difC/sig/alpha/beta) に支配され異方 mustrain を分離できず発散する
        # (NaCuHCF·nD₂O iMATERIA 実測: ND 一般化 mustrain で ND Rwp 15→51%・係数 0 崩壊)。
        val = flags["size_strain"]
        allowed = {"isotropic", "uniaxial", "generalized"}
        mtype = val if (isinstance(val, str) and val in allowed) else "isotropic"
        non_lowres = [
            h for h, r in zip(hists, radiations) if r is not Radiation.NEUTRON_CW
        ]
        if mtype == "isotropic":
            targets = non_lowres if (non_lowres and len(hists) > 1) else list(hists)
        else:
            # 異方 mustrain は X 線ヒストグラムに限定 (中性子は分離不能で発散するため除外)。
            # X 線が無ければ従来の non_lowres へフォールバック (revert ガードが最終的な安全網)。
            xray = [h for h, r in zip(hists, radiations) if r.is_xray]
            targets = xray or (non_lowres if (non_lowres and len(hists) > 1) else list(hists))
        for ph in phases:
            ph.set_HAP_refinements(
                {
                    "Size": {"type": "isotropic", "refine": True},
                    "Mustrain": {"type": mtype, "refine": True},
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
    return auto_frozen


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


def _apply_content_constraint(gpx, g2phases, g2hists, content_constraint) -> None:
    """相間の線形 Scale 拘束 Σ cᵢ·Scaleᵢ = 0 を登録する (FR-318 lock_fractions, T12)。🔵

    総アルカリ量拘束はモル量 ∝ Scaleᵢ·Zᵢ を使うと Scale について**線形**:
    ``Σ Scaleᵢ·Zᵢ·(xᵢ − x_total) = 0``。係数 ``cᵢ = Zᵢ·(xᵢ − x_total)`` を相名キーで受け取り、
    各ヒストグラムの Scale 変数へ `add_EqnConstr` する (相 id 混在の前例 = 相分率和=1)。

    ⚠ **2 相では和=1 と合わせ相分率が完全決定される** — XRD は分率に寄与しなくなり Rwp が
    一致度の検定量になる。既定モードにしない理由 (設計 Correction A)。**実行可能性
    (feasibility) と縮退 (xᵢ 等値) のゲートは呼び出し側の責務** (`operando.coulometry.feasibility`)
    — 本関数は機械的に登録するだけ。係数が全て ~0 (縮退) の場合のみ安全側で skip する。
    """
    if not content_constraint or len(g2phases) < 2:
        return
    for hist in g2hists:
        hid = hist.id
        variables: list[str] = []
        mults: list[float] = []
        for ph in g2phases:
            c = content_constraint.get(ph.name)
            if c is None or not math.isfinite(float(c)):
                continue
            variables.append(f"{ph.id}:{hid}:Scale")
            mults.append(float(c))
        if len(variables) >= 2 and any(abs(m) > 1e-12 for m in mults):
            gpx.add_EqnConstr(0.0, variables, mults)


def _apply_initial_occupancies(g2phases, occupancies: Mapping[str, Mapping[str, float]]) -> None:
    """原子占有率を initial_occupancies で初期化する (FR-318 fix/warm-start 用, T8)。🔵

    `_apply_initial_fractions` (Scale シーダー) の占有率版。add_phase 直後・制約登録前に呼ぶ。
    値のみ差し替え、精密化フラグ (F) は触らない — **fix (凍結) は構造的に実現される**:
    原子がどの占有率グループ (`mixed_occupancy_groups`/`free_occupancy_labels` 等) にも属さなければ
    `_update_atom_flags` が F フラグを立てず、seed 値のまま固定される。逆に diagnose の
    warm-start では占有率グループ宣言と併用し、seed から精密化を出発させる。

    fail-open: 未知の相名/ラベル・非有限値は無視 (分率シーダーと同じ規律)。
    **範囲検証 ([0,1]) は `run_auto_rietveld` 冒頭で実施済み** (GSAS に触れる前に大声で失敗)。
    """
    if not occupancies:
        return
    for ph in g2phases:
        vals = occupancies.get(ph.name)
        if not vals:
            continue
        try:
            atoms = ph.data["Atoms"]
            cx, ct, _cs, _cia = ph.data["General"]["AtomPtrs"]
            label_to_idx = {str(row[ct - 1]): i for i, row in enumerate(atoms)}
        except Exception:  # noqa: BLE001 — 構造差は相ごとスキップ
            continue
        for lab, v in vals.items():
            idx = label_to_idx.get(str(lab))
            if idx is None or not math.isfinite(float(v)):
                continue
            atoms[idx][cx + 3] = float(v)


def _apply_bond_restraints(gpx, g2phases, bond_restraints) -> None:
    """相名→結合距離ソフト拘束を GSAS-II Bond restraint として登録する (O–H/D 漂流防止)。

    ``ph.addDistRestraint`` は**現在座標**で origin×target の距離が ``[bond/factor, bond*factor]`` に入る
    対を探して登録するため、**初期座標が理想幾何のうちに呼ぶ**必要がある (呼出は精密化開始前)。
    拘束は gpx データツリーに保存され revert (スナップショット復元) 後も保持される。不正 spec・GSAS
    未対応・ラベル不一致は当該拘束のみスキップして継続する (EDGE)。

    **weight は相単位**: GSAS の ``setDistRestraintWeight`` が相全体の wtFactor を設定するため、同一相の
    複数 spec で異なる weight を与えても**最後に指定された値**が相全体に適用される (per-bond 重みは不可)。
    通常は同一相の全 spec に同じ weight を渡す。既定 1000.0。
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
        weight = 1000.0  # 相単位 wtFactor (最後に指定された spec の weight を採用)
        for spec in specs:
            try:
                # 必須/任意キーの取り出しも try 内 (不正 spec は当該拘束のみスキップ)。
                origin = [str(a) for a in spec["origin"]]  # type: ignore[index]
                target = [str(a) for a in spec["target"]]  # type: ignore[index]
                dist = float(spec["distance"])  # type: ignore[index]
                esd = float(spec.get("esd", 0.02))  # type: ignore[union-attr]
                factor = float(spec.get("factor", 1.5))  # type: ignore[union-attr]
                weight = float(spec.get("weight", weight))  # type: ignore[union-attr]
                ph.addDistRestraint(origin, target, dist, factor=factor, ESD=esd)
            except Exception:  # noqa: BLE001 — 不正 spec/ラベル不一致/未対応はスキップし継続
                continue
        try:
            ph.setDistRestraintWeight(weight)
        except Exception:  # noqa: BLE001
            pass


def _apply_chem_comp_restraints(gpx, g2phases, chem_comp_restraints) -> None:
    """相名→組成 (ChemComp) ソフト拘束を GSAS-II Restraints ツリーへ直接注入する (FR-318 T10)。🔵

    GSAS-II 本体は化学組成拘束を実装している (`GSASIIstrMath` の penalty:
    ``calc = Σ mult·occ·factor`` vs ``obs`` を ``esd`` 重みで罰し、``Afrac`` 微分も持つ) が、
    scriptable API は Bond 拘束しか露出していない。そこで `_apply_bond_restraints` と同じ手口で
    ``gpx.data['Restraints']['data'][phase]['ChemComp']['Sites']`` へ
    ``[ranIds, factors, obs, esd]`` を直接書く。Restraints ツリーは gpx に保存されるため
    revert (スナップショット復元) 後も保持される (Bond と同じ性質)。

    ⚠ **本バージョンの GSAS-II では headless 最小二乗で restraint penalty が機能しない**
    (FR-318 実測, 3 経路で確認):

    1. 既定 (analytic Hessian, dlg=None): `errRefine` が penalty 項を ``if len(pVals) and dlg:``
       ゲート内で χ² に連結するため **目的関数から除外** — Marquardt は penalty を無視して
       データ解へ収束する (ChemComp 目標 3.2 [occ 0.8] vs 収束 occ 1.018, 重み 4e8 でも不動)。
    2. ダミー dlg 注入 (penalty を χ² に含める): `HessRefine` の penalty 勾配符号がデータ側と
       逆 (`Vec -=` vs データ `Vec +=`, dy=obs−calc は同一) のためステップが**逆方向** (occ
       1.0→1.2) に出て全ステップ棄却 → `Aborted: True` でロールバック。
    3. analytic Jacobian + ダミー dlg: shift/esd 0.000 (全パラメータ不動)。

    よって **soft モードは注入まで実装するが実質無効** — `insitu.charge.plan_frame_constraint`
    は soft を diagnose へ縮退させ警告する。GSAS-II 更新で修復された場合に検知するカナリアが
    `tests/autorietveld/test_charge_constraint_gsas.py::TestChemCompRestraint` (fail したら
    soft モードを再有効化する)。既存 `bond_restraints` も同じゲートの影響下にある (Issue 化)。

    **単位**: ``total`` は **セルあたり原子数** (Σ mult·occ·factor の目標値)。式単位あたり量 x を
    拘束したい場合は呼び出し側が ``x × Z`` に換算して渡す (①コアは GSAS ネイティブ単位)。

    各 spec: ``{"labels": [原子ラベル…], "total": セルあたり目標, "esd": 目標の esd,
    "factors": ラベル毎係数 (省略時 1.0), "weight": 相単位 wtFactor}``。
    不正 spec・ラベル不一致は当該拘束のみスキップして継続する (Bond と同じ縮退規律)。
    """
    if not chem_comp_restraints:
        return
    rroot = gpx.data.setdefault("Restraints", {"data": {}})
    rdata = rroot.setdefault("data", {})
    for ph in g2phases:
        specs = chem_comp_restraints.get(ph.name)
        if not specs:
            continue
        entry = rdata.setdefault(ph.name, {})
        cc = entry.setdefault("ChemComp", {"wtFactor": 1.0, "Sites": [], "Use": True})
        try:
            atoms = ph.data["Atoms"]
            _cx, ct, _cs, cia = ph.data["General"]["AtomPtrs"]
            # ChemComp の ids は**原子 ranId** (row[cia+8])。行 index ではない。
            label_to_ranid = {str(row[ct - 1]): row[cia + 8] for row in atoms}
        except Exception:  # noqa: BLE001 — 構造差は相ごとスキップ
            continue
        weight = 1.0
        for spec in specs:
            try:
                labels = [str(x) for x in spec["labels"]]  # type: ignore[index]
                total = float(spec["total"])  # type: ignore[index]
                esd = float(spec.get("esd", 0.1))  # type: ignore[union-attr]
                factors = [
                    float(f)
                    for f in spec.get("factors", [1.0] * len(labels))  # type: ignore[union-attr]
                ]
                weight = float(spec.get("weight", weight))  # type: ignore[union-attr]
                if len(factors) != len(labels):
                    continue
                ids = [label_to_ranid[lab] for lab in labels]
                cc["Sites"].append([ids, factors, total, esd])
            except Exception:  # noqa: BLE001 — 不正 spec/ラベル不一致はスキップし継続
                continue
        cc["wtFactor"] = weight
        cc["Use"] = True


def _atom_result_maps(g2phases):
    """ラベルキーの原子パラメータ (占有率/Uiso/多重度/占有率 esd) を抽出する (FR-318 T7/T11)。🔵

    `AutoRietveldResult.atom_occupancy`/`atom_uiso` は宣言されながら未配線だった
    (`_extract_state` は validity 用の位置リストしか作らない)。本関数がラベルキーで充填する。

    占有率 esd は**最終共分散の varyList** に ``<pId>::Afrac:<idx>`` が載っている原子のみ
    ``sig`` から取り、載っていない原子は **None** (精密化していない — `_cell_was_refined` と
    同じ規律で 0.0 を捏造しない)。抽出不能は空 dict へ縮退し例外を送出しない。
    """
    occ: dict[str, dict[str, float]] = {}
    uiso: dict[str, dict[str, float]] = {}
    mult: dict[str, dict[str, float]] = {}
    occ_esd: dict[str, dict[str, float | None]] = {}
    for ph in g2phases:
        try:
            atoms = ph.data["Atoms"]
            cx, ct, cs, cia = ph.data["General"]["AtomPtrs"]
            try:
                cov = ph.proj["Covariance"]["data"]
                # ⚠ varyList/sig は numpy 配列のことがある — `arr or ()` は真偽値評価で
                # ValueError になるため None 判定で分岐する (実測でこの罠を踏んだ)。
                vary_raw = cov.get("varyList")
                vary = [str(v) for v in (vary_raw if vary_raw is not None else ())]
                sig_raw = cov.get("sig")
                sig = list(sig_raw) if sig_raw is not None else []
            except Exception:  # noqa: BLE001 — 共分散なしは「未精密化」に縮退
                vary, sig = [], []
            pid = ph.id
            p_occ: dict[str, float] = {}
            p_uiso: dict[str, float] = {}
            p_mult: dict[str, float] = {}
            p_esd: dict[str, float | None] = {}
            for i, row in enumerate(atoms):
                label = str(row[ct - 1])
                p_occ[label] = float(row[cx + 3])
                p_mult[label] = float(row[cs + 1])
                if row[cia] == "I":
                    p_uiso[label] = float(row[cia + 1])
                var = f"{pid}::Afrac:{i}"
                esd: float | None = None
                if var in vary:
                    j = vary.index(var)
                    if j < len(sig):
                        esd = finite_or_none(sig[j])
                        if esd is not None and esd <= 0.0:
                            esd = None
                p_esd[label] = esd
            occ[ph.name] = p_occ
            uiso[ph.name] = p_uiso
            mult[ph.name] = p_mult
            occ_esd[ph.name] = p_esd
        except Exception:  # noqa: BLE001 — 構造差/抽出失敗は当該相をスキップし継続
            continue
    return occ, uiso, mult, occ_esd


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


def _finite_or_zero(x: object) -> float:
    """非有限 (NaN/inf) を 0.0 に落として float 化する (esd の JSON 安全化)。

    esd の 0.0 は GSAS-II の慣習で「精密化していない/不確かさ不明」を表す
    (`get_cell_and_esd` も共分散なしの場合 0.0 を返す)。算出不能を同じ表現へ寄せる。
    """
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _weight_esd_or_none(x: object) -> float | None:
    """多相の重量分率 esd を純化する。**0.0 / 非有限 / 負は `None`**、正のみ値を残す (捏造防止)。

    **0.0 を捏造しない** (レビュー第6巡 HIGH — R5 の cell_esd と同型の再発): GSAS-II の
    `calcMassFracs` は相分率 (HAP Scale) が**最終精密化の共分散 varyList に無い**とき、当該
    ヒストグラムの**全相**の su を厳密に ``0.0`` にする (導関数ベクトル `Avec` が全 0 → sqrt(0))。
    これは「精密化して 0 に決まった」ではなく「**この精密化からは決まっていない**」を意味する。

    実測 (K₂Mn[Fe(CN)₆] M10 双方向解析 `publication_m10.csv`): fr213 は直前 fr212 と重量分率が
    **完全一致** (0.80115/0.19885) で su だけ 0.0、fr224 も fr223 と一致で su 0.0 — 全段 revert
    (warm-start 種のまま) で共分散に Scale が残らなかったフレームである。素通しすると
    ``wt = 0.199(0)`` = 無限精度の捏造が出版経路 (`phase_weight_fraction_esd`) へ流れる。

    **多相の real な決定では su>0 が保証される** (両分率が (0,1) にあれば `Avec` は非零・共分散の
    Scale 部分は正定値) ため、多相で su==0.0 は一意に「未決定」を指す。単相の自明な ``0.0``
    (`_weight_fraction_maps` の早期 return) は本関数を通さないので影響しない。
    """
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v) or v <= 0.0:
        return None
    return v


#: `G2Phase.get_cell_and_esd()` の esd dict のキー (`refined_cells` と同じ a,b,c,α,β,γ 順)。
_CELL_ESD_KEYS = (
    "length_a", "length_b", "length_c", "angle_alpha", "angle_beta", "angle_gamma",
)
#: 逆格子計量テンソル項 `<pId>::A0..A5`。GSAS が格子を精密化するときの**実際の変数名**。
_CELL_A_TERMS = tuple(f"A{i}" for i in range(6))


def _cell_was_refined(ph) -> bool:
    """この相の格子が**最後に受理された精密化で実際に変数だったか**を Covariance から判定する。

    **典拠**: GSAS は格子を逆格子計量テンソル項 ``<pId>::A0..A5`` として精密化し、その名前は
    ``Covariance/data/varyList`` に載る。esd を作る `G2lat.getCellEsd` 自身が
    ``getVCov(RMnames, varyList, covMatrix)`` を引く — つまり **varyList に無い A 項の分散は 0** に
    なる。よって「varyList に A 項があるか」は「GSAS が esd を計算し得たか」と**厳密に同値**であり、
    `_cell_esd_map` の 0.0 が「精密化して 0」なのか「精密化していない」なのかを分ける authoritative
    な情報源である。

    **エンジン側の記録 (`refine_cell` / `auto_frozen`) を使わない理由**: 段階が revert されると
    gpx はセル解放前のスナップショットへ戻る (= 報告されるセルは入力 CIF 値のまま) が、
    エンジン側の「解放しようとした」という記録は残る。varyList は**報告するセルを実際に作った
    精密化**を指すため、revert を自動的に正しく扱う。

    判定不能 (Covariance 無し・構造差・未精密化) は **False** (= esd を主張しない) に倒す。
    捏造を防ぐのが目的なので、疑わしきは「無い」側が安全である。
    """
    try:
        cov = ph.proj["Covariance"]["data"]
        vary = {str(v) for v in (cov.get("varyList") or ())}
        pfx = f"{ph.id}::"
    except Exception:  # noqa: BLE001 — 共分散/構造差は「精密化していない」に縮退
        return False
    return any(f"{pfx}{term}" in vary for term in _CELL_A_TERMS)


def _cell_esd_map(g2phases) -> dict[str, CellEsd]:
    """相名→格子の標準不確かさ (a,b,c,α,β,γ) を GSAS-II の共分散から抽出する。

    出典 `G2Phase.get_cell_and_esd()` → (cellDict, esdDict)。両者は length_a/b/c・angle_alpha/beta/
    gamma・volume をキーに持つが、``refined_cells`` は**体積を含まない 6 要素**なので同一レイアウトへ
    揃える (体積 esd は落とす)。

    **0.0 を捏造しない** (レビュー第5巡 HIGH): `get_cell_and_esd()` は**凍結した格子でも例外を出さず
    全 0.0 を返す**ため、素通しすると「精密化して 0 に決まった」と読める値が出版経路へ流れる
    (実測: 論文用 CSV の `mono_a_esd=0.0` 192/192 フレーム・`cubic` 34/211 = `auto_freeze_minor_cells`
    が凍結した分)。よって `_cell_was_refined` で解放の有無を分け、**③ が 3 状態を区別できる**表現にする:

    | 状態 | 表現 |
    |---|---|
    | 解放して精密化した項 | ``>0.0`` (共分散由来の su) |
    | 解放したセルの**対称拘束項** | ``0.0`` — mono の α/γ は厳密に 90°。**真の陳述なので残す** |
    | 格子を解放していない相 | ``None`` × 6 (手動 `refine_cell=False` / `auto_freeze_minor_cells` / |
    |  | セル段が revert された / そもそも未精密化)。このデータからは決まっていない |
    | 抽出できなかった相 | **キーごと欠落** (`get_cell_and_esd()` が例外) |

    非有限 (NaN/inf) も ``None`` にする — 「値が無い」であって「厳密に 0」ではない。
    抽出不能な相はキーごと落とし、**例外は送出しない** (バックエンド失敗は結果へ縮退する不変条件)。
    """
    out: dict[str, CellEsd] = {}
    for ph in g2phases:
        try:
            _cell, esd = ph.get_cell_and_esd()
            if not _cell_was_refined(ph):
                out[ph.name] = (None, None, None, None, None, None)
                continue
            values = tuple(finite_or_none(esd[key]) for key in _CELL_ESD_KEYS)
            out[ph.name] = values  # type: ignore[assignment]
        except Exception:  # noqa: BLE001 — 共分散欠落/キー欠落は当該相をスキップし継続
            continue
    return out


def _weight_fraction_maps(g2phases, g2hists) -> tuple[dict[str, float], dict[str, float | None]]:
    """相名→(重量分率, その esd) を GSAS-II 自身の質量分率計算から抽出する。

    出典 `G2PwdrData.ComputeMassFracs()` → `GSASIIstrMath.calcMassFracs(varyList, covMatrix,
    Phases, hist, hId)`。正準式は ``wtSum = Σ mass[p]*Scale[p]``・``WgtFrac[j] =
    mass[j]*Scale[j]/wtSum`` で、esd は Jacobian と共分散行列から伝播される。

    **`phase_fractions` (Scale の和=1 正規化) との違い**: Scale は単位胞の散乱能に対する係数であり、
    単位胞質量が相間で異なると重量分率と大きく乖離する。さらに mass は精密化された占有率に依存して
    フレーム毎に変わるため、静的 CIF 質量からの後付け換算では正しくない → GSAS に毎回計算させる。

    先頭ヒストグラム基準 (`phase_fractions` と同じ規約)。単相は calcMassFracs が空を返す仕様
    (``len(valDict)==1`` で早期 return) なので、自明な ({name: 1.0}, {name: 0.0}) を返す。
    共分散が無い/取得不能なら空 dict へ縮退し**例外は送出しない**。

    **esd の 3 状態を区別する** (レビュー第6巡 HIGH; R5 の cell_esd と同型): 分率精密化 (相 Scale) が
    最終共分散に残った相は ``>0.0`` (calcMassFracs の伝播 su)、単相は自明な ``{name: 0.0}`` (真の
    陳述; 早期 return)、**多相で su==0.0 は「決まっていない」**ので ``None`` に倒す
    (`_weight_esd_or_none`)。旧実装は `_finite_or_zero` で全段 revert フレームの su を ``0.0`` として
    出版経路へ流していた (実測 fr213/fr224 が直前フレームと分率一致・su=0.0 = 無限精度の捏造)。
    """
    if not g2phases or not g2hists:
        return {}, {}
    if len(g2phases) == 1:
        return {g2phases[0].name: 1.0}, {g2phases[0].name: 0.0}
    try:
        vals = g2hists[0].ComputeMassFracs()
    except Exception:  # noqa: BLE001 — 共分散なし (未収束/未精密化) 等は空へ縮退
        return {}, {}
    fracs: dict[str, float] = {}
    esds: dict[str, float | None] = {}
    for name, pair in dict(vals).items():
        fracs[str(name)] = _finite_or_zero(pair[0])
        esds[str(name)] = _weight_esd_or_none(pair[1])
    return fracs, esds


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


def _apply_initial_fractions(g2phases, g2hists, fractions: Mapping[str, float]) -> None:
    """相分率 (HAP Scale) を initial_fractions で初期化する (逐次精密化ウォームスタート用, Issue #82)。

    実測動機: `run_sequential_rietveld` の warm_start は格子のみを引き継ぎ、相分率は毎フレーム既定
    HAP Scale (単相 1.0/多相は add_phase 既定の等分) から再出発するため、転移ドーム域で分率精密化が
    局所的に動かず既定値に張り付くフレームが生じる (実測 2 相 cubic+tetragonal 系列: f112 0.48, f116
    0.55, f120 0.60, **f124 0.50, f128 0.50** (未着手の seed 値そのまま), f132 0.59 — 分率 warm-start
    ありの系列は同域で ≈0.69 まで滑らかに追従した)。

    add_phase 直後・精密化前に `initial_cells` と対称の位置で呼ぶ。値は**相対値**で良い — GSAS の
    相分率和=1 制約 (`_setup_constraints` の `phase_fraction_sum`, 多相のみ登録) が精密化開始時に
    正規化する。既存の refine フラグ (解放/固定) は変更せず値のみ差し替える。

    :param g2phases: 相追加済みの G2Phase 列
    :param g2hists: 精密化対象ヒストグラム列 (Scale は HAP = 相×ヒストグラムの組ごとに持つ)
    :param fractions: 相名→相対分率。未知の相名は無視する

    fail-open (Issue #82 要件): fractions が空、または全値が非有限/ゼロなら何もしない。誤って
    全相を 0 分率に固定してしまう事故 (精密化が動けなくなる) を避けるための安全側フォールバック。
    """
    if not fractions or not g2hists:
        return
    finite_vals = [v for v in fractions.values() if math.isfinite(v)]
    if not finite_vals or not any(v != 0.0 for v in finite_vals):
        return
    for ph in g2phases:
        frac = fractions.get(ph.name)
        if frac is None or not math.isfinite(frac):
            continue
        for hist in g2hists:
            try:
                cur = ph.getHAPvalues(hist)["Scale"]
                refine_flag = cur[1]
            except (KeyError, IndexError, TypeError):
                refine_flag = True
            ph.setHAPvalues({"Scale": [float(frac), refine_flag]}, targethistlist=[hist])


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
    initial_fractions: Mapping[str, float] | None = None,
    bond_restraints: dict[str, Sequence[Mapping[str, object]]] | None = None,
    auto_freeze_minor_cells: float | None = None,
    initial_occupancies: Mapping[str, Mapping[str, float]] | None = None,
    chem_comp_restraints: Mapping[str, Sequence[Mapping[str, object]]] | None = None,
    content_constraint: Mapping[str, float] | None = None,
    check_occupancy_uiso: bool = False,
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
        "weight": wtFactor}`` の dict (origin/target/distance 必須, 他は既定 esd0.02/factor1.5/weight1000)。
        **初期座標が理想幾何のうちに**登録し、精密化中に O–H/D 結合長が理想値から外れる罰を与える
        (無秩序水の軽原子座標の漂流を防ぐ; 配向は自由)。weight は**相単位** (最後の spec 値が相全体に適用)。
        既定 None (拘束なし)。⚠ D/H の等値/占有率和など**対称・等値制約と併用すると GSAS scriptable が
        拘束勾配を制約変数へ伝播せず無効**になる (実測)。硬拘束が要るなら `PhaseSpec.frozen_coord_labels`。
    :param initial_cell_scale: 相名→(fa,fb,fc) の初期格子摂動倍率 (マルチスタート用, None で無摂動)。
        **参照格子は摂動前の初期値を採用**する (妥当性判定を摂動でずらさないため)。
    :param initial_cells: 相名→(a,b,c[,α,β,γ]) の絶対初期格子 (逐次精密化のウォームスタート用,
        None で CIF 既定)。直前フレームの精密化格子を次フレームの初期値に引き継ぐのに用いる。
        ``initial_cell_scale`` と併用時は本絶対セルを先に適用し、その上に摂動倍率を掛ける。
    :param initial_fractions: 相名→相対相分率 (逐次精密化の分率ウォームスタート用, Issue #82,
        None で GSAS 既定 HAP Scale)。直前フレームの精密化相分率を次フレームの HAP Scale 初期値に
        引き継ぐ。相分率和=1 制約 (多相のみ) が精密化開始時に正規化するため絶対値である必要はない。
        未知の相名は無視、全値が非有限/ゼロなら fail-open でシーディングを丸ごとスキップする。
    :param auto_freeze_minor_cells: 分率連動の自動セル凍結閾値 (opt-in, Issue #80: #47/#50 の
        自動化)。⚠ **basis は `phase_fractions` (= HAP Scale の Σ=1 正規化値) であり
        `phase_weight_fractions` (wt%) ではない** — 実測 K₂Mn[Fe(CN)₆] で ``Scale {cubic .75,
        tetra .25}`` = ``wt% {cubic .865, tetra .135}`` なので **0.2 は Scale では tetra を解放し
        wt% では凍結する** (`_should_refine_cell` 参照)。出版値は wt% なので wt% の直感で数字を
        決めると静かに外れる。None (既定) なら従来動作 (非回帰): "cell" 段は ``PhaseSpec.refine_cell`` の
        明示指定のみに従う。float (例 0.2) を与えると、"cell" 段の適用時点で live な
        ``g2phases``/``g2hists`` から ``_phase_fraction_map`` により取得した現在の相分率が
        閾値未満の相は、その段階の Cell 解放をスキップする (計量が近い相同士の相関で少数相
        セルを解放すると発散する実測知見, Issue #80 背景)。**手動が自動に勝つ**:
        ``PhaseSpec.refine_cell=False`` は本閾値の値に関わらず常に凍結を維持する。単相は
        分率 1.0 のため凍結されない。分率が取得できない場合は fail open (凍結しない) — 全相を
        誤って凍結する事故を避ける。自動凍結された相名は各段の ledger エントリ
        (``m7_stage`` の ``auto_frozen_cells``) に記録され、挙動が監査可能になる。
    :param initial_occupancies: 相名→{原子ラベル→占有率} の初期値シーダー (FR-318)。値のみ差し替え、
        精密化フラグは触らない — 占有率グループ非宣言の原子は seed 値のまま**固定**される (fix モード)。
        範囲外 ([0,1] 超) は GSAS import 前に ValueError (物理的に不可能な要求は大声で失敗)。
        非有限/未知ラベルは fail-open で無視。既定 None。
    :param chem_comp_restraints: 相名→組成 (ChemComp) ソフト拘束の列 (FR-318 soft モード)。各 spec は
        ``{"labels": [...], "total": セルあたり原子数目標, "esd": 目標 esd, "factors": 係数,
        "weight": 相単位 wtFactor}``。**total はセルあたり** (式単位量 x は呼び出し側で x×Z に換算)。
        GSAS 本体の ChemComp penalty を Restraints ツリー直接注入で使う。既定 None。
    :param content_constraint: 相名→係数 cᵢ の相間線形 Scale 拘束 ``Σ cᵢ·Scaleᵢ = 0``
        (FR-318 lock_fractions)。総アルカリ量拘束は cᵢ = Zᵢ·(xᵢ − x_total)。⚠ 2 相では相分率が
        完全決定され XRD は分率に寄与しなくなる。実行可能性/縮退ゲートは呼び出し側の責務
        (`operando.coulometry.feasibility`)。既定 None。
    :returns: AutoRietveldResult
    """
    # FR-318: 占有率シーダーの範囲検証は GSAS import 前に行う (物理的に不可能な要求は即時失敗)。
    if initial_occupancies:
        for _ph_name, _vals in initial_occupancies.items():
            for _lab, _v in _vals.items():
                if math.isfinite(float(_v)) and not (0.0 <= float(_v) <= 1.0 + 1e-9):
                    raise ValueError(
                        f"初期占有率が物理範囲 [0,1] を外れています: "
                        f"{_ph_name}/{_lab} = {_v}"
                    )
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
            if h.excluded_regions:
                # GSAS-II の Limits は [(orig_min,orig_max), [used_lo,used_hi], *excluded_pairs] で、
                # set_refinements に 'Exclude' キーは存在しない (実測で例外)。使用域確定後に
                # [lo, hi] を直接 append する (Issue #53)。
                for r in h.excluded_regions:
                    hist.data["Limits"].append([float(r[0]), float(r[1])])
            if h.absorber_layers:
                # 固定吸収体レイヤー (electrolyte/window, Issue #54): 角度依存の透過補正を
                # Yobs/weight へ直接適用する (定数部はスケール因子と縮退するため含めない)。
                d = hist.data["data"][1]  # [x, Yobs, weight, Ycalc, Ybkg, Ydiff]
                x = np.asarray(d[0])
                y = np.asarray(d[1])
                w = np.asarray(d[2])
                y2, w2 = apply_absorption_correction(x, y, w, h.absorber_layers)
                d[1] = y2
                d[2] = w2
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

        # --- 初期相分率ウォームスタート (逐次精密化, 任意, Issue #82) ---
        if initial_fractions:
            _apply_initial_fractions(g2phases, g2hists, initial_fractions)

        # --- 初期占有率シーダー (FR-318: fix モード/占有率 warm-start, 任意) ---
        if initial_occupancies:
            _apply_initial_occupancies(g2phases, initial_occupancies)

        # --- 初期 Uiso 妥当性 + 占有率/Uiso 結合の事前警告 (FR-318 / REQ-318-005) ---
        # **FR-318 の入力 (シーダー/組成拘束/分率拘束/明示フラグ) があるときのみ**検査する。
        # レビュー M4: 「占有率段があるか」で発火させると、既存の混合占有ワークフロー
        # (T2 garnet / NaCuHCF は occupancy 段 + uiso 段が正規レシピ) に新警告が出て非回帰契約が
        # 破れる。``check_occupancy_uiso`` は FR-318 の diagnose + 占有率解放 (x₀ 導出) フロー用 —
        # plan kwargs が空でも組成を占有率から導出する以上この検査が要る (最終レビュー F3;
        # `make_gsas_runner` が charge_constraint 有効時に立てる)。
        pre_warnings: tuple[str, ...] = ()
        _touches_occupancy = bool(
            initial_occupancies or chem_comp_restraints or content_constraint
            or check_occupancy_uiso
        )
        if _touches_occupancy:
            _, uiso_init, _, _ = _atom_result_maps(g2phases)
            pre_warnings = check_initial_uiso(uiso_init) + warn_occupancy_uiso_coupling(stages)

        # --- 制約登録 (混合占有: 占有率和=1 + Uiso 等価; 多相: 相分率和=1) ---
        _setup_constraints(gpx, g2phases, g2hists, phases)
        # 相間の総量線形拘束 (FR-318 lock_fractions; feasibility ゲートは呼び出し側)。
        _apply_content_constraint(gpx, g2phases, g2hists, content_constraint)
        # 結合距離ソフト拘束 (初期座標が理想幾何のうちに登録; O–H/D の漂流防止)。
        _apply_bond_restraints(gpx, g2phases, bond_restraints)
        # 組成 (ChemComp) ソフト拘束 (FR-318 soft モード; Restraints ツリー直接注入)。
        _apply_chem_comp_restraints(gpx, g2phases, chem_comp_restraints)
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
            auto_frozen: list[str] = []
            try:
                auto_frozen = _apply_stage(
                    gpx, g2hists, g2phases, phase_infos, atom_flag_maps, radiations, stage,
                    fixed_profile, auto_freeze_minor_cells,
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

            # 自動セル凍結 (Issue #80) が発生した相を note に付記し挙動を可視化する
            # (非破壊: stage.note 自体は変更せず、StageResult 側でのみ拡張する)。
            note = stage.note
            if auto_frozen:
                frozen_note = f"auto_frozen_cells={','.join(auto_frozen)}"
                note = f"{note}; {frozen_note}" if note else frozen_note

            stage_results.append(
                StageResult(
                    label=stage.label,
                    rwp=rwp,
                    gof=gof,
                    n_params=nvar,
                    converged=converged,
                    reverted=reverted,
                    note=note,
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
                    "auto_frozen_cells": list(auto_frozen),
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
            warnings=validity.warnings + prof_report.warnings + pre_warnings,
        )
        hist_profile = tuple({k: v for k, (v, _) in d.items()} for d in prof_full)

        final_rwp = stage_results[-1].rwp if stage_results else float("inf")
        final_gof = stage_results[-1].gof if stage_results else float("inf")
        final_nobs = _nobs(gpx) if stage_results else 0
        phase_fractions = _phase_fraction_map(g2phases, g2hists)
        # 出版用の不確かさ: 格子 esd と GSAS 自身が算出した重量分率 (±esd)。共分散が無ければ空へ縮退。
        cell_esd = _cell_esd_map(g2phases)
        wt_fracs, wt_frac_esd = _weight_fraction_maps(g2phases, g2hists)
        # 原子パラメータ (FR-318 T7/T11: ラベルキー占有率/Uiso/多重度 + 占有率 esd の 2 状態)。
        atom_occ_map, atom_uiso_map, atom_mult_map, atom_occ_esd_map = _atom_result_maps(g2phases)
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
        cell_esd=cell_esd,
        phase_weight_fractions=wt_fracs,
        phase_weight_fraction_esd=wt_frac_esd,
        atom_uiso=atom_uiso_map,
        atom_occupancy=atom_occ_map,
        atom_multiplicity=atom_mult_map,
        atom_occupancy_esd=atom_occ_esd_map,
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
