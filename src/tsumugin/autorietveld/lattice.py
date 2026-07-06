"""異方的格子精密化の numpy コア (Issue #20 / 逆格子計量テンソル最小二乗)。

Materials Project 等の DFT 緩和構造は格子定数が実測から**異方的に**ずれる (CaTeO3 delta:
a,b は <1% だが c 軸だけ +3.4% 過大)。等方歪み ε (reference.rietveld.align_peaks) はこの異方
誤差を吸収できず、Rietveld のセル精密化は 3.4% を超えるズレを収束半径外で追えない (Issue #20 診断)。

本モジュールは**指数付き反射 (hkl) + 観測 d 間隔**から格子を直接解く決定論ソルバを提供する。
鍵は 1/d² が逆格子計量テンソル G* の成分に**線形**であること:

    1/d² = h·G*·hᵀ = h²·G11 + k²·G22 + l²·G33 + 2hk·G12 + 2hl·G13 + 2kl·G23

これを結晶系の対称拘束 (立方=1 / 正方・六方=2 / 直方=3 / 単斜=4 / 三斜=6 自由度) 下で重み付き
最小二乗で解けば、初期値に依らず (線形なので局所解に嵌らず) 異方誤差をまとめて補正できる。
外れ値 (誤指数付けした反射) はロバスト再重み付けで除去する。

反射強度を精密化せず**反射位置 (d 間隔) だけ**から格子を解く位置ベース法 (Pawley/Le Bail のような
全パターン強度抽出は行わない)。numpy のみで指数付きピークがあれば即解ける。pymatgen XRDCalculator は
各ピークに hkl を返すため、参照 (DFT) 構造の計算反射を観測ピークへマッチすれば hkl が得られる
(cell_refine.py が配線)。

信頼性: 🔵 結晶学の標準 (計量テンソル)。Issue #20 の「異方整列 (hkl 線形解)」を頑健化。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

__all__ = [
    "Cell6",
    "LatticeSolution",
    "reciprocal_metric_from_cell",
    "cell_from_reciprocal_metric",
    "solve_cell_from_dspacings",
    "refine_cell_robust",
    "two_theta_of_hkls",
    "refine_cell_from_indexed_peaks",
]

# (a, b, c, α, β, γ) — 角度は度
Cell6 = tuple[float, float, float, float, float, float]

# 計量成分ベクトルの並び: [M11, M22, M33, M12, M13, M23]
_COMP_ORDER = ("11", "22", "33", "12", "13", "23")


@dataclass(frozen=True)
class LatticeSolution:
    """異方格子精密化の結果。🔵 Issue #20"""

    cell: Cell6  # 精密化した直接格子 (a,b,c,α,β,γ) 🔵
    crystal_system: str  # 適用した対称拘束 🔵
    n_used: int  # フィットに使った反射数 (外れ値除外後) 🔵
    rms_inv_d2: float  # 1/d² 残差の RMS (Å⁻²) 🔵
    rejected: tuple[int, ...]  # 外れ値として除外した反射の元 index (昇順) 🔵


def _metric_from_components(comp: np.ndarray) -> np.ndarray:
    """成分ベクトル [M11,M22,M33,M12,M13,M23] を対称 3x3 計量行列へ。"""
    m11, m22, m33, m12, m13, m23 = (float(x) for x in comp)
    return np.array(
        [[m11, m12, m13], [m12, m22, m23], [m13, m23, m33]], dtype=float
    )


def _cell_from_metric(metric: np.ndarray) -> Cell6:
    """計量行列 M から格子定数を復元する (直接計量なら直接格子, 逆計量なら逆格子)。

    a=√M11, cosα=M23/(bc) 等。数値誤差で cos が ±1 を僅かに超えても acos が定義されるようクリップ。
    """
    a = math.sqrt(max(metric[0, 0], 1e-30))
    b = math.sqrt(max(metric[1, 1], 1e-30))
    c = math.sqrt(max(metric[2, 2], 1e-30))
    cos_alpha = _clip_cos(metric[1, 2] / (b * c))
    cos_beta = _clip_cos(metric[0, 2] / (a * c))
    cos_gamma = _clip_cos(metric[0, 1] / (a * b))
    return (
        a,
        b,
        c,
        math.degrees(math.acos(cos_alpha)),
        math.degrees(math.acos(cos_beta)),
        math.degrees(math.acos(cos_gamma)),
    )


def _clip_cos(x: float) -> float:
    return max(-1.0, min(1.0, float(x)))


def reciprocal_metric_from_cell(cell: Cell6) -> np.ndarray:
    """直接格子 (a,b,c,α,β,γ) から逆格子計量テンソル G* (3x3) を返す。

    直接計量 G を組み、G* = G⁻¹ を返す。1/d² = h·G*·hᵀ の係数行列に一致する。
    """
    a, b, c, alpha, beta, gamma = (float(x) for x in cell)
    ca = math.cos(math.radians(alpha))
    cb = math.cos(math.radians(beta))
    cg = math.cos(math.radians(gamma))
    g = np.array(
        [
            [a * a, a * b * cg, a * c * cb],
            [a * b * cg, b * b, b * c * ca],
            [a * c * cb, b * c * ca, c * c],
        ],
        dtype=float,
    )
    return np.linalg.inv(g)


def cell_from_reciprocal_metric(g_star: np.ndarray) -> Cell6:
    """逆格子計量テンソル G* (3x3) から直接格子 (a,b,c,α,β,γ) を復元する。"""
    direct = np.linalg.inv(np.asarray(g_star, dtype=float))
    return _cell_from_metric(direct)


def _design_row(hkl: Sequence[float]) -> np.ndarray:
    """反射 hkl の 1/d² を成分 [G11,G22,G33,G12,G13,G23] に写す係数行 [h²,k²,l²,2hk,2hl,2kl]。"""
    h, k, ll = float(hkl[0]), float(hkl[1]), float(hkl[2])
    return np.array([h * h, k * k, ll * ll, 2 * h * k, 2 * h * ll, 2 * k * ll], dtype=float)


def _system_basis(crystal_system: str) -> np.ndarray:
    """結晶系の対称拘束を表す基底行列 B (6×k)。成分 g_full = B @ p (p は自由パラメータ)。

    立方(1)/正方(2)/六方・三方h(2)/菱面体・三方r(2)/直方(3)/単斜b(4)/三斜(6)。未知系は三斜に縮退。
    順序は _COMP_ORDER = [11,22,33,12,13,23]。
    """
    s = crystal_system.strip().lower()
    if s == "cubic":
        # G11=G22=G33=p, 非対角 0
        b = np.zeros((6, 1))
        b[0, 0] = b[1, 0] = b[2, 0] = 1.0
        return b
    if s == "tetragonal":
        # G11=G22=p0, G33=p1
        b = np.zeros((6, 2))
        b[0, 0] = b[1, 0] = 1.0
        b[2, 1] = 1.0
        return b
    if s in ("hexagonal", "trigonal", "trigonal_h"):
        # 六方 (γ=120°): G11=G22=p0, G33=p1, G12=0.5·p0 (逆格子 γ*=60°)
        b = np.zeros((6, 2))
        b[0, 0] = b[1, 0] = 1.0
        b[2, 1] = 1.0
        b[3, 0] = 0.5
        return b
    if s in ("rhombohedral", "trigonal_r"):
        # 菱面体 (a=b=c, α=β=γ): G11=G22=G33=p0, G12=G13=G23=p1
        b = np.zeros((6, 2))
        b[0, 0] = b[1, 0] = b[2, 0] = 1.0
        b[3, 1] = b[4, 1] = b[5, 1] = 1.0
        return b
    if s == "orthorhombic":
        # G11,G22,G33 自由, 非対角 0
        b = np.zeros((6, 3))
        b[0, 0] = b[1, 1] = b[2, 2] = 1.0
        return b
    if s == "monoclinic":
        # b 軸ユニーク (β 自由, α=γ=90°): G11,G22,G33,G13 自由, G12=G23=0
        b = np.zeros((6, 4))
        b[0, 0] = b[1, 1] = b[2, 2] = 1.0
        b[4, 3] = 1.0  # G13
        return b
    # triclinic / 既定: 全 6 成分自由
    return np.eye(6)


def _solve_components(
    hkls: Sequence[Sequence[float]],
    inv_d2: np.ndarray,
    weights: np.ndarray,
    crystal_system: str,
) -> np.ndarray | None:
    """重み付き線形最小二乗で成分ベクトル g_full (6,) を解く。退化時 None。"""
    basis = _system_basis(crystal_system)
    design = np.array([_design_row(h) for h in hkls], dtype=float)  # (N,6)
    a_red = design @ basis  # (N,k)
    w = np.sqrt(np.clip(weights, 0.0, None))
    aw = a_red * w[:, None]
    qw = inv_d2 * w
    if aw.shape[0] < aw.shape[1]:
        return None  # 反射数 < 自由度: 解不能
    try:
        p, _res, rank, _sv = np.linalg.lstsq(aw, qw, rcond=None)
    except np.linalg.LinAlgError:
        return None
    # ランク落ち (例: 全反射 l=0 で G33 が拘束されない) は least-norm 解が退化軸を返すため
    # 解なし扱いにする (呼び出し側が initial_cell へフォールバック)。
    if int(rank) < aw.shape[1]:
        return None
    return basis @ p


def _cell_plausible(cell: Cell6) -> bool:
    """格子が物理的に妥当か (有限・軸長 (0.1,1000)Å・角度 (1,179)°) を判定する。

    近特異な計量から復元した退化セル (巨大/微小軸・0/180° 角) を弾き、呼び出し側の
    フォールバックに委ねる (LOW-2 対策)。
    """
    if not all(math.isfinite(v) for v in cell):
        return False
    if not all(0.1 < cell[i] < 1000.0 for i in (0, 1, 2)):
        return False
    return all(1.0 < cell[i] < 179.0 for i in (3, 4, 5))


def solve_cell_from_dspacings(
    hkls: Sequence[Sequence[float]],
    d_obs: Sequence[float],
    *,
    crystal_system: str = "triclinic",
    weights: Sequence[float] | None = None,
    initial_cell: Cell6 | None = None,
) -> Cell6:
    """指数付き反射 (hkl) と観測 d から格子を 1 回の線形最小二乗で解く。

    :param hkls: 反射指数の列 [(h,k,l), ...]
    :param d_obs: 対応する観測 d 間隔 (Å, >0)
    :param crystal_system: 対称拘束 (cubic/tetragonal/hexagonal/rhombohedral/orthorhombic/
        monoclinic/triclinic)。未知は triclinic
    :param weights: 各反射の重み (None なら等重み)。強度を渡すと強反射を重視できる
    :param initial_cell: 解が退化 (反射不足/特異) した際に返すフォールバック格子
    :returns: 精密化した直接格子 (a,b,c,α,β,γ)。退化時は initial_cell (なければ ValueError)
    """
    d = np.asarray(d_obs, dtype=float)
    if len(hkls) != d.size:
        raise ValueError("hkls と d_obs は同長でなければならない。")
    good = d > 1e-9
    hkl_list = [hkls[i] for i in range(len(hkls)) if good[i]]
    inv_d2 = 1.0 / (d[good] ** 2)
    w = (
        np.ones(inv_d2.size)
        if weights is None
        else np.asarray([weights[i] for i in range(len(weights)) if good[i]], dtype=float)
    )
    g_full = _solve_components(hkl_list, inv_d2, w, crystal_system)
    cell: Cell6 | None = None
    if g_full is not None:
        try:
            cell = cell_from_reciprocal_metric(_metric_from_components(g_full))
        except (np.linalg.LinAlgError, ValueError):
            cell = None
    # 退化 (反射不足/ランク落ち/近特異による非物理セル) は initial_cell へフォールバック (LOW-2)。
    if cell is None or not _cell_plausible(cell):
        if initial_cell is not None:
            return initial_cell
        raise ValueError("格子を解けません (反射不足/ランク落ち/退化)。")
    return cell


def refine_cell_robust(
    hkls: Sequence[Sequence[float]],
    d_obs: Sequence[float],
    *,
    crystal_system: str = "triclinic",
    weights: Sequence[float] | None = None,
    iterations: int = 3,
    reject_sigma: float = 3.0,
    initial_cell: Cell6 | None = None,
) -> LatticeSolution:
    """外れ値 (誤指数付け) を反復再重み付けで除去しつつ異方格子を精密化する。

    手順: 全反射で解く → 1/d² 残差を計算 → |残差| > reject_sigma·(残差 MAD 換算 σ) の反射を除外
    → 残りで再解 → 収束 (除外集合が不変) or iterations 上限で停止。全て決定論的。

    :param iterations: 再重み付けの最大反復数
    :param reject_sigma: 外れ値棄却の閾値 (残差 σ 倍)。小さいほど厳しい
    :returns: LatticeSolution (最終格子 + 使用反射数 + 残差 RMS + 除外 index)
    """
    d = np.asarray(d_obs, dtype=float)
    if len(hkls) != d.size:
        raise ValueError("hkls と d_obs は同長でなければならない。")
    base_w = np.ones(d.size) if weights is None else np.asarray(weights, dtype=float)
    valid = d > 1e-9
    idx_all = np.flatnonzero(valid)
    inv_d2_all = np.zeros(d.size)
    inv_d2_all[valid] = 1.0 / (d[valid] ** 2)

    active = set(int(i) for i in idx_all)
    cell = initial_cell or (1.0, 1.0, 1.0, 90.0, 90.0, 90.0)
    rms = 0.0
    for _ in range(max(1, iterations)):
        act = sorted(active)
        if len(act) < _system_basis(crystal_system).shape[1]:
            break
        sub_hkls = [hkls[i] for i in act]
        sub_inv = inv_d2_all[act]
        sub_w = base_w[act]
        g_full = _solve_components(sub_hkls, sub_inv, sub_w, crystal_system)
        if g_full is None:
            break
        try:
            candidate = cell_from_reciprocal_metric(_metric_from_components(g_full))
        except (np.linalg.LinAlgError, ValueError):
            break
        if not _cell_plausible(candidate):  # 近特異で退化したら直前セルを保持 (LOW-2)
            break
        cell = candidate
        # 全有効反射の残差で外れ値を再評価する
        g_star = _metric_from_components(g_full)
        resid = np.array(
            [inv_d2_all[i] - float(_design_row(hkls[i]) @ _sym_vec(g_star)) for i in idx_all]
        )
        rms = float(np.sqrt(np.mean(resid**2))) if resid.size else 0.0
        # MAD ベースの頑健 σ (中央値絶対偏差 × 1.4826)
        med = float(np.median(resid))
        mad = float(np.median(np.abs(resid - med)))
        sigma = mad * 1.4826
        if sigma <= 1e-15:
            break  # 残差がほぼ均一 = 外れ値なし
        keep = {
            int(idx_all[j])
            for j in range(idx_all.size)
            if abs(resid[j] - med) <= reject_sigma * sigma
        }
        if keep == active or len(keep) < _system_basis(crystal_system).shape[1]:
            active = keep if keep else active
            break
        active = keep

    rejected = tuple(sorted(set(int(i) for i in idx_all) - active))
    return LatticeSolution(
        cell=cell,
        crystal_system=crystal_system.strip().lower(),
        n_used=len(active),
        rms_inv_d2=rms,
        rejected=rejected,
    )


def _sym_vec(g_star: np.ndarray) -> np.ndarray:
    """対称 3x3 G* を成分ベクトル [G11,G22,G33,G12,G13,G23] に戻す (残差評価用)。"""
    return np.array(
        [
            g_star[0, 0], g_star[1, 1], g_star[2, 2],
            g_star[0, 1], g_star[0, 2], g_star[1, 2],
        ],
        dtype=float,
    )


# ============================================================================
# 指数付きピークからの異方セル精密化 (grid + linear, numpy のみ; cell_refine/reference が共用)
# ============================================================================


def two_theta_of_hkls(
    cell: Cell6, hkls: Sequence[Sequence[float]], wavelength: float
) -> np.ndarray:
    """格子 cell の各 hkl の 2θ (度) を逆格子計量から解析計算する (範囲外/回折不能は NaN)。

    Bragg: sinθ = λ·√(1/d²)/2、1/d² = h·G*·hᵀ。構造 (pymatgen) を再生成せず hkl とセルだけで
    計算できるため、セルを変えながらの探索/整合が numpy のみで高速に回る。
    """
    g_star = reciprocal_metric_from_cell(cell)
    h = np.asarray(hkls, dtype=float)
    if h.size == 0:
        return np.zeros(0)
    inv_d2 = np.clip(np.einsum("ij,jk,ik->i", h, g_star, h), 1e-12, None)
    s = wavelength * np.sqrt(inv_d2) / 2.0  # sinθ
    tth = np.full(h.shape[0], np.nan)
    ok = s < 1.0
    tth[ok] = 2.0 * np.degrees(np.arcsin(s[ok]))
    return tth


def _peak_match_fom(
    cell: Cell6, hkls, wavelength, obs_pos: np.ndarray, obs_ht: np.ndarray, tth_range
) -> float:
    """観測ピークと計算ピーク位置の整合度 FoM (小さいほど良い)。

    各観測ピークを最寄りの計算ピークへ割り当て、距離 (上限 1°) を観測強度で重み付き平均する。
    hkl 本数はセルスケールに不変なので、スケール間で公平に比較できる。
    """
    tth = two_theta_of_hkls(cell, hkls, wavelength)
    lo, hi = tth_range
    good = np.isfinite(tth) & (tth >= lo) & (tth <= hi)
    if int(good.sum()) < 3:
        return 1e9
    tc = tth[good]
    dist = np.abs(obs_pos[:, None] - tc[None, :]).min(axis=1)
    denom = float(obs_ht.sum())
    if denom <= 0.0:
        return 1e9
    return float(np.sum(obs_ht * np.minimum(dist, 1.0)) / denom)


def _grid_search_scale(
    cell0: Cell6, hkls, wavelength, obs_pos, obs_ht, crystal_system, tth_range,
    *, span_lo: float = 0.95, span_hi: float = 1.05, step: float = 0.006,
) -> Cell6:
    """per-axis スケール倍率の有界グリッドで FoM 最小のセルを探す (大域ベイスン特定)。

    DFT 格子誤差は数 % 有界なので探索域は対称 ±5% で足りる。ステップは粗く取り、残差は後段の線形解が
    詰める (粗グリッド + 線形研磨が最も費用対効果が高い)。目的関数 (FoM) が安価な numpy 計算のため、
    多峰でも網羅グリッドが Bayes 最適化 (TPE) より頑健かつ高速 (Issue #20 実測比較で確認)。結晶系で
    自由スケール軸を減らす (立方/菱面体=1軸, 正方/六方=2軸, それ以外=3軸)。角度は保持し線形解に委ねる。
    """
    s = crystal_system.strip().lower()
    grid = np.arange(span_lo, span_hi + 1e-9, step)
    a0, b0, c0, al, be, ga = cell0

    def combos():
        if s in ("cubic", "rhombohedral", "trigonal_r"):
            for g in grid:
                yield g, g, g
        elif s in ("tetragonal", "hexagonal", "trigonal", "trigonal_h"):
            for gab in grid:
                for gc in grid:
                    yield gab, gab, gc
        else:
            for sa in grid:
                for sb in grid:
                    for sc in grid:
                        yield sa, sb, sc

    best_fom = math.inf
    best = cell0
    for sa, sb, sc in combos():
        cell = (a0 * sa, b0 * sb, c0 * sc, al, be, ga)
        f = _peak_match_fom(cell, hkls, wavelength, obs_pos, obs_ht, tth_range)
        if f < best_fom:
            best_fom = f
            best = cell
    return best


def _match_indexed(
    cell: Cell6, hkls, intensities, wavelength, obs_pos: np.ndarray, tol_deg: float
) -> list[tuple[tuple[int, int, int], float, float]]:
    """hkl 付き計算ピークを観測ピークへ貪欲 1:1 マッチし (hkl, 観測 d, 強度) 列を返す (強度降順に確保)。"""
    tth = two_theta_of_hkls(cell, hkls, wavelength)
    order = sorted(range(len(hkls)), key=lambda i: -float(intensities[i]))
    used = np.zeros(obs_pos.size, dtype=bool)
    out: list[tuple[tuple[int, int, int], float, float]] = []
    for i in order:
        if not math.isfinite(float(tth[i])):
            continue
        diffs = np.abs(obs_pos - tth[i])
        diffs[used] = np.inf
        j = int(np.argmin(diffs))
        if not np.isfinite(diffs[j]) or diffs[j] > tol_deg:
            continue
        used[j] = True
        theta = math.radians(float(obs_pos[j]) / 2.0)
        if theta <= 0.0:
            continue
        d = wavelength / (2.0 * math.sin(theta))
        hkl = tuple(int(round(x)) for x in hkls[i])
        out.append((hkl, d, float(intensities[i])))  # type: ignore[arg-type]
    return out


def _cell_shift(c1: Cell6, c2: Cell6) -> float:
    """2 格子の a,b,c の最大絶対差 (Å) を返す (収束/暴走判定用)。"""
    return max(abs(c1[0] - c2[0]), abs(c1[1] - c2[1]), abs(c1[2] - c2[2]))


def refine_cell_from_indexed_peaks(
    initial_cell: Cell6,
    crystal_system: str,
    hkls: Sequence[Sequence[float]],
    intensities: Sequence[float],
    observed_positions: Sequence[float],
    observed_heights: Sequence[float],
    *,
    wavelength: float,
    two_theta_range: tuple[float, float],
    min_intensity_frac: float = 0.05,
    match_tol_deg: float = 1.5,
    reject_sigma: float = 3.0,
    iterations: int = 12,
    grid_span: tuple[float, float] = (0.95, 1.05),
    grid_step: float = 0.006,
    require_improvement: bool = True,
) -> LatticeSolution | None:
    """指数付き計算ピーク (hkl+強度) を観測ピークへ整合させ異方セルを解く (numpy のみ・構造不要)。

    2 段: (1) per-axis スケールの有界 FoM グリッドで大域ベイスンを特定 → (2) その大域セルから最近傍
    マッチ + `refine_cell_robust` で線形精密化。計算ピーク 2θ は hkl とセルから解析計算するため pymatgen
    不要で、既知の hkl があれば相同定側 (reference) でも DFT 格子誤差を異方補正できる (Issue #20 hybrid)。

    :param initial_cell: 参照 (DFT) 格子 (a,b,c,α,β,γ)。探索の基準
    :param crystal_system: 対称拘束 (cubic/tetragonal/hexagonal/orthorhombic/monoclinic/triclinic 等)
    :param hkls: 計算反射の指数列
    :param intensities: 各反射の相対強度 (重み。弱反射は誤マッチ抑制で除外)
    :param observed_positions: 観測ピーク 2θ (度)
    :param observed_heights: 観測ピーク強度
    :param wavelength: 線源波長 (Å)
    :param two_theta_range: 反射を評価する 2θ 範囲
    :param require_improvement: True で FoM が initial_cell より改善しなければ None を返す (安全側)
    :returns: LatticeSolution。データ不足/未改善なら None
    """
    hkl_list = [tuple(float(x) for x in h) for h in hkls]
    inten = np.asarray(intensities, dtype=float)
    if inten.size == 0:
        return None
    thresh = min_intensity_frac * float(inten.max())
    strong = [i for i in range(len(hkl_list)) if inten[i] >= thresh]
    if len(strong) < 3:
        return None
    H = [hkl_list[i] for i in strong]
    W = inten[strong]
    obs_pos = np.asarray(observed_positions, dtype=float)
    obs_ht = np.asarray(observed_heights, dtype=float)
    if obs_pos.size < 3:
        return None

    # 段1: FoM グリッドで大域ベイスン
    seed = _grid_search_scale(
        initial_cell, H, wavelength, obs_pos, obs_ht, crystal_system, two_theta_range,
        span_lo=grid_span[0], span_hi=grid_span[1], step=grid_step,
    )
    init_fom = _peak_match_fom(initial_cell, H, wavelength, obs_pos, obs_ht, two_theta_range)

    # 段2: seed から線形精密化 (解析マッチ, pymatgen 不要)
    cur = seed
    n_used = len(H)
    rms = 0.0
    for it in range(max(1, iterations)):
        tol = max(0.6, match_tol_deg * (0.85 ** it))
        matched = _match_indexed(cur, H, W, wavelength, obs_pos, tol)
        if len(matched) < 3:
            break
        sol = refine_cell_robust(
            [m[0] for m in matched], [m[1] for m in matched], crystal_system=crystal_system,
            weights=[m[2] for m in matched], reject_sigma=reject_sigma, initial_cell=cur,
        )
        n_used, rms = sol.n_used, sol.rms_inv_d2
        if _cell_shift(cur, sol.cell) < 1e-4:
            cur = sol.cell
            break
        cur = sol.cell

    seed_fom = _peak_match_fom(seed, H, wavelength, obs_pos, obs_ht, two_theta_range)
    refined_fom = _peak_match_fom(cur, H, wavelength, obs_pos, obs_ht, two_theta_range)
    if refined_fom <= seed_fom:
        best_cell, best_fom, best_n, best_rms = cur, refined_fom, n_used, rms
    else:
        best_cell, best_fom, best_n, best_rms = seed, seed_fom, len(H), 0.0

    if require_improvement and best_fom > init_fom:
        return None
    return LatticeSolution(
        cell=best_cell, crystal_system=crystal_system.strip().lower(),
        n_used=best_n, rms_inv_d2=best_rms, rejected=(),
    )
