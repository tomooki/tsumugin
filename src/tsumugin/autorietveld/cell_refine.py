"""異方単位格子精密化 — DFT 参照構造のセルを実測データへ合わせる (Issue #20)。

Materials Project の DFT 緩和構造は格子が実測から**異方的に**ずれ (CaTeO3 delta: c 軸 +3.4%)、
そのままでは転移域の Rietveld が収束しない (Rwp 44%)。等方歪みでは異方誤差を吸収できず、full
Rietveld のセル精密化は収束半径 (~2%) を超えるズレを追えない。本モジュールは 2 段でこれを補正する:

1. **numpy プリアライン** (`prealign_cell_from_structure`): pymatgen XRDCalculator で参照構造の計算
   反射 (hkl + 強度) を得て観測ピークへマッチし、`lattice.refine_cell_from_indexed_peaks` で**指数付き
   ピーク位置から単位格子を最小二乗精密化**する (逆格子計量テンソル線形解 + 大域 FoM グリッド; 初期値に
   依らず大きな異方誤差も補正)。GSAS 不要。
2. **GSAS セル研磨** (`refine_structure_cell`): プリアライン格子を初期値に、GSAS-II で背景→セルを段階
   精密化する (通常の構造因子ありセル精密化; プリアラインが収束半径内へ入れるので安定な平坦解で足りる)。

**命名注記**: これは Pawley/Le Bail 法**ではない**。Pawley/Le Bail は構造因子を使わず反射強度を独立変数と
して抽出する全パターンフィットだが、本モジュールは (a) 反射強度は DFT 構造から計算した固定値を重みに
使うのみ (精密化しない)、(b) GSAS 段も構造因子ありの通常セル精密化 (LeBail は抽出強度とセルの強相関で
計量テンソルが発散するため不採用)。実態は**位置ベースの単位格子精密化 (peak-position cell refinement)**。

得られた異方セルを物質化 CIF に書き戻す (phaseid が配線) ことで、転移域 delta を実測級 Rwp へ導く。
コアの数値は numpy (`lattice`)。pymatgen (プリアライン) と GSAS-II (研磨) は各関数内で遅延 import する。

信頼性: 🔵 Issue #20 診断 (プリアライン MP-like 摂動で c 0.50→0.01 Å 回復を実測検証)。
"""

from __future__ import annotations

import math
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .lattice import Cell6, LatticeSolution

__all__ = [
    "CellRefinementResult",
    "prealign_cell_from_structure",
    "refine_structure_cell",
]

_DEFAULT_WAVELENGTH = 1.5406  # Cu Kα1 (Å)


@dataclass(frozen=True)
class CellRefinementResult:
    """異方単位格子精密化の結果 (プリアライン + 任意の GSAS セル研磨)。🔵 Issue #20"""

    cell: Cell6  # 精密化した直接格子 (a,b,c,α,β,γ) 🔵
    rwp: float  # GSAS セル研磨後の Rwp (%)。研磨なし (プリアラインのみ) は inf 🔵
    converged: bool  # GSAS 精密化が収束したか 🔵
    method: str  # "prealign" / "prealign+cell" / "cell" / "none" 🔵
    n_matched: int  # プリアラインでマッチした反射数 (0=プリアラインなし) 🔵
    prealign_cell: Cell6 | None = None  # プリアライン段の格子 (GSAS 研磨前) 🔵


def _crystal_system_of(structure: object) -> str:
    """pymatgen 構造の結晶系を返す。trigonal はセル角で hexagonal/rhombohedral に振り分ける。"""
    from pymatgen.symmetry.analyzer import SpacegroupAnalyzer

    sys = SpacegroupAnalyzer(structure).get_crystal_system()  # type: ignore[arg-type]
    if sys == "trigonal":
        latt = structure.lattice  # type: ignore[attr-defined]
        a, b, c = latt.a, latt.b, latt.c
        alpha = latt.alpha
        # 菱面体セッティング (a≈b≈c, α≈β≈γ≠90) か六方セッティング (γ≈120) か
        if abs(a - b) < 1e-3 and abs(b - c) < 1e-3 and abs(alpha - 90.0) > 1.0:
            return "rhombohedral"
        return "hexagonal"
    return sys


def prealign_cell_from_structure(
    structure_path: str,
    observed_two_theta: np.ndarray,
    observed_intensity: np.ndarray,
    *,
    wavelength: float = _DEFAULT_WAVELENGTH,
    two_theta_range: tuple[float, float] = (10.0, 90.0),
    match_tol_deg: float = 1.5,
    min_intensity_frac: float = 0.05,
    reject_sigma: float = 3.0,
    iterations: int = 12,
    subtract_bg: bool = True,
) -> LatticeSolution | None:
    """参照構造 (CIF) の計算反射を観測ピークへマッチし、異方セルを直接解く (numpy プリアライン)。

    pymatgen XRDCalculator で参照構造の (2θ, 強度, hkl) を生成 → 各計算ピークを最寄りの観測ピークへ
    貪欲マッチ → マッチした (hkl, 観測 d, 強度重み) を `lattice.refine_cell_robust` に渡して結晶系拘束
    下で異方セルを解く。構造因子と分離した位置合わせ。

    【2 段】: DFT の異方誤差 (a,b,c が各々ずれる) では、貪欲最近傍マッチが初回に誤指数付けの基底へ
    ロックし部分収束に留まる (Issue #20; 実測 CaTeO3 delta で確認)。そこで
      段1 (大域): 参照反射リストを固定し、per-axis スケール (a,b,c 倍率) の**有界 FoM グリッド探索**で
        観測ピークへの整合を最大化する大域ベイスンのセルを先に見つける (DFT 誤差は数 % 有界なので
        グリッドは狭い)。これが誤基底問題を回避する鍵。
      段2 (精密): その大域セルから計算ピークを再生成→最近傍マッチ→`lattice.refine_cell_robust` で
        線形精密化 (段1 で既に整合しているためマッチが信頼でき、sub-0.01 Å まで詰める)。
    最後に FoM が DFT セルより改善したものだけ返す (悪化時は None; 呼び出し側は DFT/等方 strain へ)。決定論的。

    :param structure_path: 参照構造ファイル (CIF)
    :param observed_two_theta: 観測 2θ (度, 昇順)
    :param observed_intensity: 観測強度
    :param wavelength: 線源波長 (Å)。既定 Cu Kα1
    :param two_theta_range: 計算反射を生成/評価する 2θ 範囲
    :param match_tol_deg: 段2 の最近傍マッチ許容差 (度)
    :param min_intensity_frac: 使う計算反射の最小相対強度 (弱反射の誤マッチ抑制)
    :param reject_sigma: ロバスト外れ値棄却の閾値
    :param iterations: 段2 の再マッチ→再解の最大反復数
    :param subtract_bg: find_peaks 前に SNIP 背景減算するか (実測データで必須; 合成は不要)
    :returns: LatticeSolution。pymatgen 未導入・反射/マッチ/改善不足なら None
    """
    from ..reference.background import subtract_background
    from ..search.peaks import find_peaks
    from .lattice import refine_cell_from_indexed_peaks

    try:
        from pymatgen.analysis.diffraction.xrd import XRDCalculator
        from pymatgen.core import Structure
    except ImportError:
        return None

    structure = Structure.from_file(structure_path)
    crystal_system = _crystal_system_of(structure)
    dft_cell = _cell_of(structure)
    calc = XRDCalculator(wavelength=wavelength)

    # --- 参照反射リスト (hkl + 相対強度) を DFT セルで一度だけ抽出 (pymatgen はここだけ) ---
    pattern = calc.get_pattern(structure, scaled=True, two_theta_range=two_theta_range)
    if len(pattern.x) == 0:
        return None
    hkls = [_first_hkl(e) for e in pattern.hkls]
    intensities = np.asarray(pattern.y, dtype=float)

    # --- 観測強ピーク (背景減算) ---
    obs_int = np.asarray(observed_intensity, dtype=float)
    if subtract_bg:
        obs_int = subtract_background(obs_int)
    obs_peaks = find_peaks(np.asarray(observed_two_theta, dtype=float), obs_int)
    lo, hi = two_theta_range
    in_range = [(p.position, p.height) for p in obs_peaks if lo <= p.position <= hi]
    if len(in_range) < 3:
        return None
    obs_pos = np.array([p[0] for p in in_range], dtype=float)
    obs_ht = np.array([p[1] for p in in_range], dtype=float)

    # --- 異方セル精密化 (grid + linear) は numpy コア (lattice) に委譲 ---
    return refine_cell_from_indexed_peaks(
        dft_cell, crystal_system, hkls, intensities, obs_pos, obs_ht,
        wavelength=wavelength, two_theta_range=two_theta_range,
        min_intensity_frac=min_intensity_frac, match_tol_deg=match_tol_deg,
        reject_sigma=reject_sigma, iterations=iterations,
    )


def _first_hkl(hkl_entry: object) -> tuple[float, float, float]:
    """XRDCalculator の hkls エントリ (list[dict{'hkl':(h,k,l)}]) から代表 hkl を取り出す。"""
    if isinstance(hkl_entry, (list, tuple)) and hkl_entry:
        first = hkl_entry[0]
        if isinstance(first, dict) and "hkl" in first:
            return tuple(first["hkl"])  # type: ignore[return-value]
        return tuple(first)  # type: ignore[return-value]
    raise ValueError(f"想定外の hkl エントリ: {hkl_entry!r}")


def _cell_of(structure: object) -> Cell6:
    latt = structure.lattice  # type: ignore[attr-defined]
    return (latt.a, latt.b, latt.c, latt.alpha, latt.beta, latt.gamma)


def _rvals(gpx) -> tuple[float, bool]:
    """精密化後の (Rwp, converged) を Covariance から取り出す。"""
    cov = gpx.data["Covariance"]["data"]
    rv = cov.get("Rvals", {})
    return float(rv.get("Rwp", float("inf"))), bool(rv.get("converged", True))


def _phase_cell(ph) -> Cell6:
    c = ph.get_cell()
    return (
        float(c["length_a"]), float(c["length_b"]), float(c["length_c"]),
        float(c["angle_alpha"]), float(c["angle_beta"]), float(c["angle_gamma"]),
    )


def _cells_finite(ph, min_length: float = 0.5) -> bool:
    c = ph.get_cell()
    for k in ("length_a", "length_b", "length_c"):
        v = float(c[k])
        if not math.isfinite(v) or v < min_length:
            return False
    return True


def refine_structure_cell(
    structure_path: str,
    data_path: str,
    instrument_path: str,
    *,
    radiation: object | None = None,
    data_format: str = "XYE",
    two_theta_limits: tuple[float, float] | None = None,
    background_coeffs: int = 12,
    max_cyc: int = 15,
    prealign_two_theta: np.ndarray | None = None,
    prealign_intensity: np.ndarray | None = None,
    wavelength: float = _DEFAULT_WAVELENGTH,
    initial_cell: Cell6 | None = None,
    gsas_polish: bool = True,
) -> CellRefinementResult:
    """DFT 参照構造のセルを実測データへ精密化する (numpy プリアライン → GSAS 段階セル研磨)。

    観測ピークを与えれば (``prealign_two_theta``/``prealign_intensity``) まず numpy プリアラインで
    大きな異方誤差を大域 FoM グリッド + 線形解で補正し (Rietveld 収束半径内へ)、その格子を初期値に
    GSAS-II の**平坦な段階セル精密化** (背景→セル, 構造因子は正しい前提) で sub-0.01 Å まで研磨する。

    LeBail 抽出下のセル精密化は抽出強度とセルの強相関で計量テンソルが発散しやすい (実測 CaTeO3 で
    確認) ため採らない。プリアラインが既に大域ベイスンへ収束させるので、安定な平坦セル精密化で足りる。
    格子が崩壊/悪化した段は revert してプリアライン格子を返す (提案≠適用の安全側)。

    :param structure_path: 参照構造 (CIF)
    :param data_path: 観測データ (GSAS-II importer が読める形式。XRDML は事前に XYE 変換して渡す)
    :param instrument_path: 装置パラメータ (.instprm)
    :param radiation: 線源 (現状は fmthint 選択に未使用。将来の中性子分岐用)
    :param data_format: GSAS importer ヒント種別 ("XYE"/"GSAS"/"FXYE")
    :param two_theta_limits: 精密化レンジ (ノイズ域除外)
    :param background_coeffs: Chebyshev 背景項数
    :param max_cyc: 各段の最大精密化サイクル
    :param prealign_two_theta: プリアライン用の観測 2θ (None でプリアライン省略)
    :param prealign_intensity: プリアライン用の観測強度
    :param wavelength: プリアラインの線源波長 (Å)
    :param initial_cell: 初期格子 (None なら CIF 既定 or プリアライン結果)
    :param gsas_polish: GSAS 段階セル研磨を行うか (False なら numpy プリアライン格子をそのまま返す)
    :returns: CellRefinementResult (格子崩壊/悪化時はプリアライン格子へ revert)
    """
    # --- 段 0: numpy プリアライン (任意) ---
    prealign_cell: Cell6 | None = None
    n_matched = 0
    if prealign_two_theta is not None and prealign_intensity is not None:
        sol = prealign_cell_from_structure(
            structure_path, prealign_two_theta, prealign_intensity, wavelength=wavelength,
            two_theta_range=two_theta_limits or (10.0, 90.0),
        )
        if sol is not None and sol.n_used >= 3:
            prealign_cell = sol.cell
            n_matched = sol.n_used

    seed_cell = initial_cell or prealign_cell

    # プリアラインだけで済ませる (GSAS 研磨なし)
    if not gsas_polish:
        cell = seed_cell or _cif_cell(structure_path)
        method = "prealign" if prealign_cell is not None else "none"
        return CellRefinementResult(
            cell=cell, rwp=float("inf"), converged=False, method=method,
            n_matched=n_matched, prealign_cell=prealign_cell,
        )

    from GSASII import GSASIIscriptable as G2sc

    try:
        G2sc.SetPrintLevel("none")
    except Exception:
        pass

    with tempfile.TemporaryDirectory(prefix="tsumugin-cellrefine-") as tmp:
        tmp_path = Path(tmp)
        gpx_path = tmp_path / "cellrefine.gpx"
        gpx = G2sc.G2Project(newgpx=str(gpx_path))
        fmthint = {"XYE": "xye", "FXYE": "GSAS", "GSAS": "GSAS"}.get(data_format.upper(), "xye")
        hist = gpx.add_powder_histogram(data_path, instrument_path, fmthint=fmthint)
        if two_theta_limits is not None:
            hist.set_refinements({"Limits": list(two_theta_limits)})
        ph = gpx.add_phase(structure_path, phasename="cellref", histograms=[hist], fmthint="CIF")
        if seed_cell is not None:
            _set_cell(ph, seed_cell)
        gpx.data["Controls"]["data"]["max cyc"] = max_cyc
        start_cell = _phase_cell(ph)

        method = "prealign" if prealign_cell is not None else "none"
        rwp = float("inf")
        converged = False
        refined = start_cell
        try:
            # 段 1: 背景を先に合わせる (セルは固定)
            gpx.set_refinement(
                {"set": {"Background": {"no. coeffs": int(background_coeffs), "refine": True}}}
            )
            gpx.do_refinements([{}])
            bg_rwp, _ = _rvals(gpx)
            snap = tmp_path / "snap.gpx"
            gpx.save()
            shutil.copyfile(gpx_path, snap)
            # 段 2: セルを解放 (対称拘束は GSAS が担う)。悪化/崩壊なら revert。
            ph.set_refinements({"Cell": True})
            gpx.do_refinements([{}])
            cell_rwp, converged = _rvals(gpx)
            if _cells_finite(ph) and cell_rwp <= bg_rwp + 1e-6:
                refined = _phase_cell(ph)
                rwp = cell_rwp
                method = "prealign+cell" if prealign_cell is not None else "cell"
            else:
                refined = seed_cell or start_cell
                rwp = bg_rwp
        except Exception:
            # 例外時は seed (initial_cell or プリアライン) を優先し start_cell へ縮退 (LOW-3, 非例外の
            # 悪化ブランチと整合)。
            refined = seed_cell or start_cell
            rwp, converged = float("inf"), False

    final_cell = refined if _cell_ok(refined) else (prealign_cell or start_cell)
    return CellRefinementResult(
        cell=final_cell,
        rwp=rwp,
        converged=converged,
        method=method,
        n_matched=n_matched,
        prealign_cell=prealign_cell,
    )


def _cif_cell(structure_path: str) -> Cell6:
    """CIF から格子定数のみ読む (pymatgen 遅延)。プリアライン省略時のフォールバック。"""
    from pymatgen.core import Structure

    return _cell_of(Structure.from_file(structure_path))


def _cell_ok(cell: Cell6, min_length: float = 0.5) -> bool:
    return all(math.isfinite(v) for v in cell) and min(cell[0], cell[1], cell[2]) >= min_length


def _set_cell(ph, cell: Cell6) -> None:
    """相の格子を絶対値 cell に設定し体積を再計算する (LeBail 初期値注入)。"""
    from GSASII import GSASIIlattice as G2lat

    new = [float(cell[0]), float(cell[1]), float(cell[2]),
           float(cell[3]), float(cell[4]), float(cell[5])]
    ph.data["General"]["Cell"][1:7] = new
    ph.data["General"]["Cell"][7] = G2lat.calc_V(G2lat.cell2A(new))
