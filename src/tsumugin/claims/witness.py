"""相集合の完全性の証人 — 計算反射から離れた窓の残差 S/N (fit-then-judge P1-1A, REQ-FTJ-1A-402)。

モデルに無い相のピークは、**どの計算反射の位置からも離れた場所**に正の残差として残る。そこで:

1. 各点で装置プロファイルから FWHM を求め、最寄りの計算反射から ``exclusion_fwhm`` × FWHM 以内の点を
   除外する (計算反射の上の残差は既知の相の合わなさで、欠落相の証拠ではない)。
2. 残った点の連続区間ごとに、±5 FWHM の局所中央値を引いて背景のゆっくりした合わなさを除く。
3. 反射から離れた点の規格化残差の MAD で σ の過小評価 (GOF > 1) を割り戻す (1 未満にはしない)。
4. 各点を中心に**平均 0 の山形の窓** (中央 1 FWHM を +、その両側 FWHM/2 ずつを − で重み付けし和を 0 に
   する) を当て、``S/N = Σkr / (尺度·sqrt(Σk²σ²))`` の最大が ``snr_threshold`` を超えれば ``fail``。
   平均 0 なので**坂 (既知相のピークの裾・背景の傾き) は打ち消され、盛り上がり (欠落相の山) だけが残る**
   — 単純な窓の和では、除外域のすぐ外まで伸びた強い反射の裾を欠落相と取り違えた (実データ T2 garnet)。
   両側の帯が区間に収まらない窓は使わない (片側だけの窓は坂を打ち消せない)。

計算できないとき (残差が空・反射位置が無い・幅を決められない・窓が残らない) は **``unevaluated``**。
既存の ``unindexed_peak_frac`` (反射位置を見ない・計算できなくても 0.0) と ``check_phase_set``
(系列専用で 1 フレームでは常に完全と答える) は使わない (proposal §3.3)。

⚠ 既知の限界: 欠落相のピークが既知相の反射と重なる位置にしか無ければ拾えない (除外される)。
既知相の強度の合わなさ (選択配向等) が窓に漏れると偽の ``fail`` になり得る — 偽の fail は出版を
止める側 (保守的) に倒れる。閾値・除外幅は P1.5 で調整する (`WITNESS_VERSION`)。
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from .model import Check, Witness

__all__ = ["WITNESS_VERSION", "cw_fwhm_deg", "residual_window_witness"]

#: 証人の規則の版 (閾値・除外幅を変えたら上げる)。
WITNESS_VERSION = "residual-window/2"

_GAUSS_FWHM = 2.0 * math.sqrt(2.0 * math.log(2.0))  # σ → FWHM
#: GSAS の getFWHM と同じくガウス分散の下限 (centideg²) — 負の U,V,W で幅が虚数にならない。
_MIN_GAUSS_VAR = 0.001


def cw_fwhm_deg(two_theta: float | np.ndarray, profile: Mapping[str, float]) -> np.ndarray | float:
    """GSAS の CW プロファイル (U,V,W [centideg²], X,Y [centideg]) から FWHM (deg) を求める。

    ガウス分散 ``σ² = U tan²θ + V tanθ + W``、ローレンツ幅 ``γ = X/cosθ + Y tanθ``、
    合成は Thompson–Cox–Hastings の 5 次近似。``U``・``V``・``W`` が無ければ KeyError。
    """
    th = np.radians(np.asarray(two_theta, dtype=float) / 2.0)
    tan = np.tan(th)
    var = profile["U"] * tan**2 + profile["V"] * tan + profile["W"]
    g = _GAUSS_FWHM * np.sqrt(np.maximum(var, _MIN_GAUSS_VAR)) / 100.0
    lor = (profile.get("X", 0.0) / np.cos(th) + profile.get("Y", 0.0) * tan) / 100.0
    lor = np.maximum(lor, 0.0)
    fwhm = (
        g**5 + 2.69269 * g**4 * lor + 2.42843 * g**3 * lor**2 + 4.47163 * g**2 * lor**3
        + 0.07842 * g * lor**4 + lor**5
    ) ** 0.2
    return float(fwhm) if np.ndim(fwhm) == 0 else fwhm


def _unevaluated(reason: str) -> tuple[Check, Witness]:
    return Check.UNEVALUATED, Witness(
        "residual_window_snr", {"version": WITNESS_VERSION, "reason": reason},
    )


def residual_window_witness(
    two_theta: Sequence[float],
    residual: Sequence[float],
    sigma: Sequence[float],
    reflections: Sequence[float] | None,
    profile: Mapping[str, float] | None,
    *,
    exclusion_fwhm: float = 3.0,
    snr_threshold: float = 5.0,
    background_fwhm: float = 5.0,
) -> tuple[Check, Witness]:
    """相集合の完全性の検査結果と、その証人 (`Witness`) を返す。

    :param residual: ``obs − calc`` (`AutoRietveldResult.residual_intensity`)
    :param sigma: 各点の σ (重み 0 の点は inf — 使わない)
    :param reflections: 計算反射の 2θ (`AutoRietveldResult.reflection_two_theta`)。None = 計測していない
    :param profile: 先頭ヒストグラムの装置プロファイル (`AutoRietveldResult.hist_profile[0]`)
    """
    tt = np.asarray(two_theta, dtype=float)
    r = np.asarray(residual, dtype=float)
    s = np.asarray(sigma, dtype=float)
    if tt.size == 0 or tt.size != r.size or tt.size != s.size:
        return _unevaluated("empty_residual")
    if reflections is None:
        return _unevaluated("no_reflections")
    try:
        fwhm = np.asarray(cw_fwhm_deg(tt, profile or {}), dtype=float)
    except KeyError:
        return _unevaluated("no_profile")
    if not np.all(np.isfinite(fwhm)) or np.any(fwhm <= 0.0):
        return _unevaluated("no_profile")

    usable = np.isfinite(tt) & np.isfinite(r) & np.isfinite(s) & (s > 0.0)
    refl = np.sort(np.asarray(reflections, dtype=float))
    refl = refl[np.isfinite(refl)]
    if refl.size:
        pos = np.searchsorted(refl, tt)
        left = np.abs(tt - refl[np.clip(pos - 1, 0, refl.size - 1)])
        right = np.abs(refl[np.clip(pos, 0, refl.size - 1)] - tt)
        near = np.minimum(left, right) < exclusion_fwhm * fwhm
    else:
        near = np.zeros(tt.size, dtype=bool)
    # 区間は反射の除外域でだけ切る (重み 0 の点で切ると区間が細切れになり、窓も背景も作れない)。
    away = np.flatnonzero(~near)
    idx = np.flatnonzero(usable & ~near)
    if idx.size == 0:
        return _unevaluated("no_window")

    # 1 周目: 区間ごとに背景のゆっくりした合わなさを除く (±background_fwhm FWHM の局所中央値)。
    segments: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for segment in np.split(away, np.flatnonzero(np.diff(away) > 1) + 1):
        run = segment[usable[segment]]
        if run.size == 0:
            continue
        x, y, e, w = tt[run], r[run], s[run], fwhm[run]
        lo_bg = np.searchsorted(x, x - background_fwhm * w)
        hi_bg = np.searchsorted(x, x + background_fwhm * w, side="right")
        hp = y - np.array([np.median(y[i:j]) for i, j in zip(lo_bg, hi_bg)])
        segments.append((x, hp, e, w))

    # 【σ の過小評価を割り戻す】: Rietveld の σ は計数統計だけで GOF > 1 が普通。反射から離れた
    #   点の規格化残差の頑健な広がり (MAD) で尺度を推定し、1 未満には下げない (σ を信じる側へは
    #   補正しない)。欠落相のピークは窓の一部しか占めないので MAD はほぼ動かない。
    z = np.concatenate([hp / e for _, hp, e, _ in segments]) if segments else np.array([])
    noise_scale = max(1.0, 1.4826 * float(np.median(np.abs(z - np.median(z))))) if z.size else 1.0

    best_snr = -math.inf
    best_window = (math.nan, math.nan)
    n_windows = 0
    for x, hp, e, w in segments:
        cs_r = np.concatenate([[0.0], np.cumsum(hp)])
        cs_v = np.concatenate([[0.0], np.cumsum(e**2)])
        c_lo = np.searchsorted(x, x - w / 2.0)
        c_hi = np.searchsorted(x, x + w / 2.0, side="right")
        s_lo = np.searchsorted(x, x - w)
        s_hi = np.searchsorted(x, x + w, side="right")
        for k in range(x.size):
            ci, cj, si, sj = c_lo[k], c_hi[k], s_lo[k], s_hi[k]
            n_center, n_side = cj - ci, (ci - si) + (sj - cj)
            # 両側の帯が区間の端で切れていない (= 中心から ±1 FWHM の点がある) 窓だけ
            if n_center < 3 or ci - si < 2 or sj - cj < 2:
                continue
            if x[si] > x[k] - 0.9 * w[k] or x[sj - 1] < x[k] + 0.9 * w[k]:
                continue
            side_weight = n_center / n_side  # 中央 +1、両側 −n_center/n_side で和 0
            num = (cs_r[cj] - cs_r[ci]) - side_weight * (
                (cs_r[ci] - cs_r[si]) + (cs_r[sj] - cs_r[cj])
            )
            var = (cs_v[cj] - cs_v[ci]) + side_weight**2 * (
                (cs_v[ci] - cs_v[si]) + (cs_v[sj] - cs_v[cj])
            )
            n_windows += 1
            snr = num / (noise_scale * math.sqrt(var))
            if snr > best_snr:
                best_snr = snr
                best_window = (float(x[ci]), float(x[cj - 1]))
    if n_windows == 0:
        return _unevaluated("no_window")

    check = Check.FAIL if best_snr > snr_threshold else Check.PASS
    return check, Witness("residual_window_snr", {
        "version": WITNESS_VERSION,
        "max_snr": float(best_snr),
        "window_two_theta": list(best_window),
        "snr_threshold": snr_threshold,
        "exclusion_fwhm": exclusion_fwhm,
        "n_windows": n_windows,
        "noise_scale": noise_scale,
        "used_fraction": float(idx.size / tt.size),
    })
