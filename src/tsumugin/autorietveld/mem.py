"""実 Dysnomia MEM 駆動 (精密化済み gpx → 最大エントロピー密度) (XND / FR-601〜606)。

M5 の ``tsumugin.mem`` は MEM ソルバ境界 (Protocol) + 結果型 + シミュレート joint 用の
入力生成のモック実装だった。本モジュールは **実構造 Rietveld (autorietveld) で精密化した
gpx** から、GSAS-II 内蔵の実 Dysnomia 駆動系 (``GSASIIpwd.makePRFfile`` / ``makeMEMfile`` /
``MEMupdateReflData`` + Dysnomia バイナリ) を回して**実 MEM 密度**を得る。

【役割分担】結晶学 (反射リスト・構造因子・位相・空間群展開・Fourier 変換) は GSAS-II に委譲し、
  本モジュールは (1) バイナリ解決、(2) Dysnomia 制御辞書の組み立て、(3) 一時作業領域の準備
  (Dysnomia は ``spgra.dat`` 等を cwd から読む)、(4) MEM 前/後の密度統計・ピーク→原子割当の
  抽出、を担う。密度種別は probe (X 線→電子密度 / 中性子→核密度) から決定する。

【core-only import (REQ-403)】``import tsumugin.autorietveld.mem`` は numpy のみで成功する
  (GSAS-II は関数内で遅延 import)。バイナリ/GSAS 未導入時は ``MEMUnavailableError`` へ縮退する
  (``DysnomiaBackend`` と対称)。

【非破壊 (P2)】入力 gpx はコピーして扱い、元 gpx を書き換えない。MEM 密度は .grd 参照 + 要約
  統計で保持する (``MEMDensityMap`` 契約)。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from ..errors import MEMUnavailableError
from ..mem.base import MEMDensityMap
from ..store.ledger import Ledger

# Dysnomia が cwd から読む空間群/Wyckoff データファイル (バイナリと同ディレクトリに同梱)。
_DYS_DATFILES = ("spgra.dat", "spgro.dat", "wyckoff.dat")

# GSAS-II 内蔵 Dysnomia 制御辞書の既定 (GSASIIphsGUI の defaults に準拠)。
_LAM_FRAC = (1, 0, 0, 0, 0, 0, 0, 0)


@dataclass(frozen=True)
class MEMRunConfig:
    """実 Dysnomia MEM の実行設定。🔵 FR-601/602

    :param dmin: MEM の分解能下限 d (Å)。小さいほど高分解能・反射多。
    :param ncyc: Dysnomia 反復数。
    :param optimize: Lagrange 最適化法 (``"ZSPA"`` | ``"L-BFGS"``)。
    :param lagrange: Lagrange 乗数初期値 (user 指定)。
    :param grid_step: Fourier/MEM 密度グリッド刻み (Å)。密度グリッド次元を決める。
    :param density_kind: 密度種別を明示上書き (None なら probe から自動判定)。
    :param binary_path: Dysnomia 実行ファイルパス (None なら探索)。
    :param extra_search_dirs: バイナリ追加探索ディレクトリ (直下 + ``/Dysnomia`` を見る)。
    :param cutoff: SearchMap のピーク閾値 (rhoMax の %)。閾値 = cutoff% × rhoMax 以上を
        ピークとする。100 だと最大値しか拾えないため既定 30 (骨格〜中量原子を拾う)。
    :param top_peaks: 抽出する上位ピーク数 (正/負それぞれ)。
    """

    dmin: float = 0.9
    ncyc: int = 2000
    optimize: str = "ZSPA"
    lagrange: float = 0.001
    grid_step: float = 0.25
    density_kind: str | None = None
    binary_path: str | None = None
    extra_search_dirs: tuple[str, ...] = ()
    cutoff: float = 30.0
    top_peaks: int = 8


@dataclass(frozen=True)
class DensityPeak:
    """MEM 密度マップのピーク (最近接原子付き)。🔵 REQ-028/029"""

    frac: tuple[float, float, float]  # 【分率座標】
    magnitude: float  # 【ピーク高 (密度値)】
    nearest_atom: str  # 【最近接原子ラベル】
    distance: float  # 【最近接原子までの距離 (Å)】


@dataclass(frozen=True)
class MEMDensityResult:
    """実 Dysnomia MEM の実行結果 (密度マップ + MEM 前後統計 + ピーク)。🔵 FR-602/REQ-027

    【非破壊 (P2)】密度は ``density_map.path`` (.grd) 参照 + 要約統計で保持する。
    """

    density_map: MEMDensityMap  # 【MEM 密度マップ (.grd 参照 + min/max)】
    pre_min: float  # 【MEM 前 (通常 Fobs Fourier) の最小密度】
    pre_max: float  # 【MEM 前の最大密度】
    n_reflections: int  # 【使用反射数 (mult>0)】
    mem_r_factor: float | None  # 【Dysnomia の MEM R 因子 (取得できれば)】
    converged: bool  # 【Dysnomia 収束フラグ】
    density_kind: str  # 【electron | nuclear】
    peaks: tuple[DensityPeak, ...] = ()  # 【上位ピーク (正+負)】
    warnings: tuple[str, ...] = ()  # 【信頼性警告 (除外はしない, Dara 教訓)】


# ---------------------------------------------------------------------------
# 純関数 (GSAS 非依存・決定論)
# ---------------------------------------------------------------------------


def density_kind_from_type(gsas_type: str) -> str:
    """GSAS 反射 Type ('PXC'/'PNT'/'X'/'N'…) から密度種別を決める。🔵 REQ-022

    X 線 → 電子密度、中性子 → 核密度。判別不能な型は fail-loud (ValueError)。
    """
    t = gsas_type.upper()
    if "X" in t:
        return "electron"
    if "N" in t:
        return "nuclear"
    raise ValueError(f"密度種別を判定できない反射 Type: {gsas_type!r}")


def _default_search_dirs() -> list[str]:
    """GSAS-II が既定で見る Dysnomia 探索ベースディレクトリ (ホーム等)。GSAS 未導入でも動く。"""
    dirs = [os.path.expanduser("~"), os.path.expanduser(os.path.join("~", ".GSASII"))]
    try:  # GSAS-II のインストール先も探索対象に加える (best-effort)。
        from GSASII import GSASIIpath  # noqa: PLC0415

        p = getattr(GSASIIpath, "path2GSAS2", None)
        if p:
            dirs.append(p)
    except Exception:  # noqa: BLE001 - GSAS 未導入でも解決は続行する
        pass
    return dirs


def resolve_dysnomia_binary(
    *,
    binary_path: str | None = None,
    extra_search_dirs: Sequence[str] = (),
    binimage: str | None = None,
) -> str | None:
    """Dysnomia 実行ファイルを解決する。未検出なら None を返す。🔵 REQ-020/EDGE-006

    探索順: (1) ``binary_path`` (実在すれば), (2) ``extra_search_dirs`` の直下 + ``/Dysnomia``,
    (3) GSAS-II 既定ベース + ``/Dysnomia``, (4) PATH。Windows は ``Dysnomia64.exe``、他は
    ``Dysnomia``。実行可否は存在判定で近似する (Windows は X_OK が緩いため)。
    """
    binimage = binimage or ("Dysnomia64.exe" if os.name == "nt" else "Dysnomia")

    def _is_exe(p: str) -> bool:
        return os.path.isfile(p)

    if binary_path:
        return binary_path if _is_exe(binary_path) else None

    dirs: list[str] = []
    for d in extra_search_dirs:
        dirs.append(d)
        dirs.append(os.path.join(d, "Dysnomia"))
    for base in _default_search_dirs():
        dirs.append(os.path.join(base, "Dysnomia"))
    for d in dirs:
        cand = os.path.join(d, binimage)
        if _is_exe(cand):
            return cand

    for name in (binimage, "Dysnomia", "dysnomia"):
        found = shutil.which(name)
        if found:
            return found
    return None


def assign_peaks_to_atoms(
    peaks_frac: np.ndarray,
    magnitudes: np.ndarray,
    atoms: Sequence[tuple[str, float, float, float]],
    amat: np.ndarray,
    *,
    top: int | None = None,
) -> tuple[DensityPeak, ...]:
    """密度ピークを最近接原子へ周期最小像で割り当てる (|mag| 降順・決定論)。🔵 REQ-028/029

    :param peaks_frac: (N,3) の分率座標ピーク
    :param magnitudes: (N,) のピーク高
    :param atoms: (label, xf, yf, zf) の原子列
    :param amat: 分率→直交変換行列 (3,3)。距離は ``|amat @ dfrac_minimage|``。
    :param top: 上位 N 件に制限 (None で全件)
    """
    peaks_frac = np.atleast_2d(np.asarray(peaks_frac, dtype=float))
    magnitudes = np.asarray(magnitudes, dtype=float).ravel()
    if peaks_frac.size == 0 or magnitudes.size == 0 or len(atoms) == 0:
        return ()
    atom_frac = np.array([[a[1], a[2], a[3]] for a in atoms], dtype=float)
    atom_lbl = [a[0] for a in atoms]

    order = np.argsort(-np.abs(magnitudes))
    if top is not None:
        order = order[:top]

    out: list[DensityPeak] = []
    for i in order:
        pf = peaks_frac[i]
        # 各原子への分率差を最小像 [-0.5,0.5) に畳み、直交距離を取る。
        dfrac = (atom_frac - pf + 0.5) % 1.0 - 0.5
        dcart = dfrac @ amat.T
        dist = np.sqrt(np.sum(dcart * dcart, axis=1))
        j = int(np.argmin(dist))
        out.append(
            DensityPeak(
                frac=(float(pf[0]), float(pf[1]), float(pf[2])),
                magnitude=float(magnitudes[i]),
                nearest_atom=atom_lbl[j],
                distance=float(dist[j]),
            )
        )
    return tuple(out)


# ---------------------------------------------------------------------------
# 実 Dysnomia 駆動 (GSAS-II 遅延 import)
# ---------------------------------------------------------------------------


def _prepare_workdir(work: Path, binary: str) -> None:
    """Dysnomia が cwd から読む .dat ファイルをバイナリ同梱先から作業領域へ複製する。"""
    bindir = Path(binary).parent
    for dat in _DYS_DATFILES:
        src = bindir / dat
        dst = work / dat
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)


def _has_reflections(hist, pname: str) -> bool:
    rl = hist.data.get("Reflection Lists", {})
    return pname in rl and len(rl[pname].get("RefList", [])) > 0


def _select_histogram(gpx, phase_name, hist_name, wanted_kind):
    """MEM 対象の (phase, histogram, 反射リスト, Type) を選ぶ。

    ``hist_name`` 明示が最優先。未指定かつ ``wanted_kind`` (electron/nuclear) 指定時は、その
    密度種別に一致する反射を持つ最初のヒストグラムを選ぶ (joint データで X 線/中性子を取り違え
    ないため)。いずれも未指定なら反射リストを持つ最初のヒストグラム。
    """
    phases = gpx.phases()
    ph = None
    if phase_name is not None:
        ph = next((p for p in phases if p.data["General"]["Name"] == phase_name), None)
    ph = ph or phases[0]
    pname = ph.data["General"]["Name"]

    hists = gpx.histograms()
    chosen = None
    if hist_name is not None:
        chosen = next((h for h in hists if h.name == hist_name), None)
        if chosen is None:
            raise MEMUnavailableError(f"ヒストグラム {hist_name!r} が gpx にありません。")
    elif wanted_kind is not None:
        for h in hists:
            if not _has_reflections(h, pname):
                continue
            rtype = h.data["Reflection Lists"][pname].get("Type", "")
            try:
                if density_kind_from_type(rtype) == wanted_kind:
                    chosen = h
                    break
            except ValueError:
                continue
        if chosen is None:
            raise MEMUnavailableError(
                f"密度種別 {wanted_kind!r} に一致する反射リストを持つヒストグラムがありません。"
            )
    if chosen is None:
        chosen = next((h for h in hists if _has_reflections(h, pname)), None)
    if chosen is None:
        raise MEMUnavailableError(
            f"相 {pname!r} の反射リストを持つヒストグラムがありません (先に Rietveld 精密化が必要)。"
        )
    reflSets = chosen.data["Reflection Lists"][pname]
    return ph, chosen, reflSets["RefList"], reflSets.get("Type", "")


def _mem_type(gen, rtype: str) -> int:
    """Dysnomia の MEMtype (中性子で負の散乱長を含むと 1)。"""
    if "N" not in rtype.upper():
        return 0
    for el in gen.get("Isotope", {}):
        iso = gen["Isotope"][el]
        isos = gen.get("Isotopes", {})
        if el in isos and isos[el][iso]["SL"][0] < 0.0:
            return 1
    return 0


def run_dysnomia_mem(
    gpx_path: str,
    *,
    phase_name: str | None = None,
    hist_name: str | None = None,
    config: MEMRunConfig = MEMRunConfig(),
    out_grd: str | None = None,
    ledger: Ledger | None = None,
) -> MEMDensityResult:
    """精密化済み gpx から実 Dysnomia MEM 密度を計算する。🔵 FR-602/REQ-019/020

    【手順】(1) gpx をコピー (P2), (2) 対象相/ヒスト/反射を選択, (3) Fobs Fourier マップを
      用意 (MEM 前・グリッド次元決定), (4) Dysnomia 制御辞書を組み .prf/.mem を生成,
      (5) Dysnomia を実行, (6) ``MEMupdateReflData`` で MEM 最適化 F を回収し密度を再計算,
      (7) 密度統計 + ピーク→原子割当 + .grd 書き出し。
    【未導入縮退 (REQ-020/EDGE-006)】バイナリ/GSAS 未解決や実行失敗は ``MEMUnavailableError``。
    """
    binary = resolve_dysnomia_binary(
        binary_path=config.binary_path, extra_search_dirs=config.extra_search_dirs
    )
    if binary is None:
        raise MEMUnavailableError(
            "Dysnomia バイナリが見つかりません。MEMRunConfig(binary_path=...) で指定するか、"
            "jp-minerals.org/dysnomia から入手し PATH/~/.GSASII/Dysnomia 等に配置してください。"
        )
    if not os.path.isfile(gpx_path):
        raise MEMUnavailableError(f"gpx が存在しません: {gpx_path}")

    try:
        from GSASII import GSASIIscriptable as G2sc  # noqa: PLC0415
        from GSASII import GSASIImath as G2mth  # noqa: PLC0415
        from GSASII import GSASIIpwd as G2pwd  # noqa: PLC0415
        from GSASII import GSASIIElem as G2elem  # noqa: PLC0415
        from GSASII import GSASIIlattice as G2lat  # noqa: PLC0415
        from GSASII.GSASIIscriptable import SetupGeneral  # noqa: PLC0415
    except Exception as exc:  # noqa: BLE001
        raise MEMUnavailableError(f"GSAS-II を import できません: {exc}") from exc

    try:
        G2sc.SetPrintLevel("none")
    except Exception:  # noqa: BLE001
        pass

    if ledger is not None:
        ledger.append("dysnomia_mem_start",
                      {"gpx": os.path.basename(gpx_path), "dmin": config.dmin})

    with tempfile.TemporaryDirectory(prefix="tsumugin-mem-") as tmp:
        work = Path(tmp)
        _prepare_workdir(work, binary)
        gpx_copy = work / "mem_input.gpx"
        shutil.copyfile(gpx_path, gpx_copy)

        g = G2sc.G2Project(str(gpx_copy))
        ph, hist, reflData, rtype = _select_histogram(
            g, phase_name, hist_name, config.density_kind
        )
        gen = ph.data["General"]
        if not gen.get("NoAtoms"):
            SetupGeneral(ph.data, None)

        kind = config.density_kind or density_kind_from_type(rtype)

        # (3) Fobs Fourier マップ (MEM 前・グリッド次元決定)
        gen["Map"] = G2elem.mapDefault.copy()
        gen["Map"]["MapType"] = "Fobs"
        gen["Map"]["GridStep"] = config.grid_step
        gen["Map"]["cutOff"] = config.cutoff
        gen["Map"]["RefList"] = [hist.name]
        G2mth.FourierMap(ph.data, {"RefList": reflData, "Type": rtype})
        pre_min, pre_max = float(gen["Map"]["minmax"][1]), float(gen["Map"]["minmax"][0])

        # (4) Dysnomia 制御辞書
        ph.data["Dysnomia"] = {
            "DenStart": "uniform", "Optimize": config.optimize,
            "Lagrange": ["user", config.lagrange, 0.05], "wt pwr": 0, "E_factor": 1.0,
            "Ncyc": config.ncyc, "prior": "uniform", "Lam frac": list(_LAM_FRAC),
            "overlap": 0.2, "MEMdmin": config.dmin,
        }
        memtype = _mem_type(gen, rtype)
        n_reflections = int(np.sum(np.array([r[3] for r in reflData]) > 0))

        cwd0 = os.getcwd()
        os.chdir(work)
        try:
            prf = str(G2pwd.makePRFfile(ph.data, memtype))
            ok = G2pwd.makeMEMfile(ph.data, reflData, memtype, str(binary))
            if not ok:
                raise MEMUnavailableError(
                    f"makeMEMfile 失敗 (非標準空間群 {gen['SGData']['SpGrp']!r} は Dysnomia 非対応)。"
                )
            try:
                proc = subprocess.run(
                    [str(binary), prf], cwd=str(work), capture_output=True,
                    text=True, check=True,
                )
            except subprocess.CalledProcessError as exc:
                raise MEMUnavailableError(
                    f"Dysnomia 実行に失敗 (returncode={exc.returncode})。"
                ) from exc
            converged, mem_r = _parse_dysnomia_out(proc.stdout)

            fba = Path(prf).with_suffix(".fba")
            if not fba.exists():
                raise MEMUnavailableError("Dysnomia が .fba (MEM 構造因子) を生成しませんでした。")
            goon, newRefl = G2pwd.MEMupdateReflData(prf, ph.data, reflData)
            if not goon:
                raise MEMUnavailableError("MEMupdateReflData が MEM 構造因子を回収できませんでした。")
        finally:
            os.chdir(cwd0)

        # (6) MEM 最適化 F で密度を再計算 = MEM 密度
        G2mth.FourierMap(ph.data, {"RefList": newRefl, "Type": rtype})
        mp = gen["Map"]
        post_min, post_max = float(mp["minmax"][1]), float(mp["minmax"][0])
        grid_shape = tuple(int(x) for x in mp["rho"].shape)

        # (7) ピーク → 原子割当 (相の原子ラベル + 分率座標)
        atoms = [(a[0], float(a[3]), float(a[4]), float(a[5]))
                 for a in ph.data["Atoms"]]
        amat, _ = G2lat.cell2AB(gen["Cell"][1:7])
        peaks = _search_and_assign(gen, G2mth, np.asarray(amat, float), atoms,
                                   config.top_peaks)

        # .grd 書き出し (呼び出し側指定 or 入力 gpx の隣へ)。既定名に密度種別を含め、joint で
        # electron/nuclear を続けて回しても取り違え/上書きしない。
        grd_path = out_grd or str(Path(gpx_path).with_suffix(f".mem_{kind}.grd"))
        _write_grd(grd_path, mp["rho"], gen["Cell"][1:7], kind)

        density_map = MEMDensityMap(
            path=grd_path, density_kind=kind, grid_shape=grid_shape,
            min_density=post_min, max_density=post_max,
        )

    if ledger is not None:
        ledger.append("dysnomia_mem_done",
                      {"kind": kind, "post_max": post_max, "n_peaks": len(peaks)})

    return MEMDensityResult(
        density_map=density_map, pre_min=pre_min, pre_max=pre_max,
        n_reflections=n_reflections, mem_r_factor=mem_r, converged=converged,
        density_kind=kind, peaks=peaks, warnings=(),
    )


def _parse_dysnomia_out(stdout: str) -> tuple[bool, float | None]:
    """Dysnomia の標準出力から収束フラグと MEM R 因子を best-effort 抽出する。"""
    converged = "MEM analysis" in (stdout or "")
    mem_r: float | None = None
    for line in (stdout or "").splitlines():
        low = line.lower()
        if "r factor" in low or "rfactor" in low or "r-factor" in low:
            for tok in line.replace("=", " ").split():
                try:
                    mem_r = float(tok)
                except ValueError:
                    continue
    return converged, mem_r


def _search_and_assign(
    gen, G2mth, amat: np.ndarray,
    atoms: Sequence[tuple[str, float, float, float]], top: int,
) -> tuple[DensityPeak, ...]:
    """SearchMap で正/負ピークを取り、相の原子座標へ最近接割当する (失敗時は空)。

    SearchMap(Neg=True) は密度の符号を反転して探すため、返る mag は正値。核密度の負ピーク
    (H 等) を負符号で保持するため戻す。
    """
    if not atoms:
        return ()
    results: list[DensityPeak] = []
    for neg in (False, True):
        try:
            res = G2mth.SearchMap(gen, {}, Neg=neg)
            pk, mg = res[0], res[1]
        except Exception:  # noqa: BLE001 - ピーク探索失敗は空として扱う (縮退)
            continue
        if pk is None or len(pk) == 0:
            continue
        mags = np.ravel(np.asarray(mg, dtype=float))
        if neg:
            mags = -mags
        results.extend(
            assign_peaks_to_atoms(np.asarray(pk, dtype=float), mags, atoms, amat, top=top)
        )
    results.sort(key=lambda p: -abs(p.magnitude))
    return tuple(results)


def _write_grd(path: str, rho: np.ndarray, cell, kind: str) -> None:
    """VESTA 互換 .grd に密度グリッドを書き出す (決定論・固定フォーマット)。🔵 REQ-027"""
    rho = np.asarray(rho, dtype=float)
    nx, ny, nz = rho.shape
    a, b, c, al, be, ga = (float(x) for x in cell)
    lines = [
        f"tsumugin Dysnomia MEM density ({kind}) (VESTA .grd)",
        f"{a:.6f} {b:.6f} {c:.6f} {al:.6f} {be:.6f} {ga:.6f}",
        f"{nx} {ny} {nz}",
    ]
    flat = rho.reshape(-1)
    lines.extend(f"{v:.8f}" for v in flat)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
