"""Dara 式ピークマッチングスコア (Fei et al., Chem. Mater. 2026, 38, 1364; 式1)。

相ライブラリからの相同定で、計算ピーク列と観測ピーク列の適合度を評価する発見的スコア。
既存の対称型 ``match_score`` (候補ピーク数で正規化 → peak-rich 相を希釈) の弱点を解消し、
**実測強度で正規化**して候補のピーク数では罰しない。ピークを 4 分類する:

- matched: 位置一致かつ強度が近い (係数 +1.0)
- wrong-intensity: 位置一致だが強度が factor 超で乖離 (係数 +1.0; EFLECH 等の強度誤差に頑健)
- missing: 観測にあり計算に無い (係数 −0.1; 他相の存在も示すため弱い罰)
- extra: 計算にあり観測に無い (係数 −0.5; 構造不一致の強い指標として強い罰)

``Score = (I_matched + I_wrong − 0.1·I_missing − 0.5·I_extra) / I_exp``。
計算/観測の強度スケール差は matched ペアの最小二乗スケールで揃える。numpy 非依存・決定論的。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..search.peaks import Peak

__all__ = ["DaraScore", "dara_peak_score"]


@dataclass(frozen=True)
class DaraScore:
    """Dara 式スコアと内訳。🔵 Fei et al. 2026 式(1)"""

    score: float  # 総合スコア (≤ 1.0、完全一致で 1.0)。ランキングキー 🔵
    i_matched: float  # matched 観測ピークの強度和 🔵
    i_wrong_intensity: float  # wrong-intensity 観測ピークの強度和 🔵
    i_missing: float  # missing 観測ピークの強度和 (未説明) 🔵
    i_extra: float  # extra 計算ピークの強度和 (スケール済) 🔵
    matched_observed: tuple[int, ...]  # matched+wrong の観測 index (昇順)。未マッチ集約用 🔵
    extra_calculated: tuple[float, ...]  # extra 計算ピーク位置 (昇順) 🔵


def dara_peak_score(
    calculated_peaks: Sequence[Peak],
    observed_peaks: Sequence[Peak],
    *,
    tol_deg: float = 0.15,
    intensity_factor: float = 5.0,
    w_matched: float = 1.0,
    w_wrong: float = 1.0,
    w_missing: float = 0.1,
    w_extra: float = 0.5,
) -> DaraScore:
    """Dara 式(1)のピークマッチングスコアを計算する。🔵

    Args:
        calculated_peaks: 参照相のシミュレートピーク列 (位置 2θ・相対強度)。
        observed_peaks: 観測ピーク列。
        tol_deg: 位置一致許容差 (度)。
        intensity_factor: matched/wrong-intensity を分ける強度比の閾値 (既定 5)。
        w_matched, w_wrong, w_missing, w_extra: 各カテゴリの係数 (既定 1.0/1.0/0.1/0.5)。

    Returns:
        ``DaraScore`` (総合スコア + 内訳 + matched 観測 index + extra 位置)。
        観測が空 or 総強度 0 なら score=0.0 に縮退する。
    """
    obs = list(observed_peaks)
    calc = list(calculated_peaks)
    i_exp_total = sum(float(o.height) for o in obs)
    if not obs or i_exp_total <= 0.0:
        return DaraScore(0.0, 0.0, 0.0, 0.0, 0.0, (), ())

    # 【位置マッチング (1:1 貪欲)】: 観測を位置昇順に走査し tol 内の未使用最近傍計算ピークを確保 🔵
    calc_order = sorted(range(len(calc)), key=lambda k: calc[k].position)
    used_calc = [False] * len(calc)
    obs_to_calc: dict[int, int] = {}
    obs_order = sorted(range(len(obs)), key=lambda k: obs[k].position)
    for oi in obs_order:
        opos = float(obs[oi].position)
        best_k = -1
        best_diff = tol_deg
        for ci in calc_order:
            if used_calc[ci]:
                continue
            diff = abs(opos - float(calc[ci].position))
            if diff <= best_diff:
                best_diff = diff
                best_k = ci
        if best_k >= 0:
            used_calc[best_k] = True
            obs_to_calc[oi] = best_k

    # 【強度スケール揃え】: matched ペアの最小二乗スケール s で計算強度を観測スケールへ 🔵
    #   s = Σ(obs·calc) / Σ(calc²)。ペア無しは s=0 (全 extra が 0 になるのを避け max 比で代替)。
    num = sum(float(obs[oi].height) * float(calc[ci].height) for oi, ci in obs_to_calc.items())
    den = sum(float(calc[ci].height) ** 2 for ci in obs_to_calc.values())
    if den > 0.0:
        scale = num / den
    else:
        # matched ペアが無い: 最大強度比で暫定スケール (extra 罰を意味あるものにする) 🟡
        max_calc = max((float(c.height) for c in calc), default=0.0)
        max_obs = max(float(o.height) for o in obs)
        scale = (max_obs / max_calc) if max_calc > 0.0 else 0.0

    # 【4 分類】: 観測側 matched/wrong/missing、計算側 extra を強度で集計 🔵
    i_matched = i_wrong = i_missing = 0.0
    matched_idx: list[int] = []
    for oi in range(len(obs)):
        oh = float(obs[oi].height)
        ci = obs_to_calc.get(oi)
        if ci is None:
            i_missing += oh  # 観測にあり計算に無い
            continue
        ch = scale * float(calc[ci].height)
        matched_idx.append(oi)
        # 強度比 (0 割回避)。factor 内なら matched、外なら wrong-intensity (どちらも +1.0)
        if ch <= 0.0:
            i_wrong += oh
        else:
            ratio = oh / ch
            if (1.0 / intensity_factor) <= ratio <= intensity_factor:
                i_matched += oh
            else:
                i_wrong += oh

    extra_positions: list[float] = []
    i_extra = 0.0
    for ci in range(len(calc)):
        if not used_calc[ci]:
            i_extra += scale * float(calc[ci].height)
            extra_positions.append(float(calc[ci].position))

    score = (
        w_matched * i_matched + w_wrong * i_wrong - w_missing * i_missing - w_extra * i_extra
    ) / i_exp_total
    return DaraScore(
        score=score,
        i_matched=i_matched,
        i_wrong_intensity=i_wrong,
        i_missing=i_missing,
        i_extra=i_extra,
        matched_observed=tuple(sorted(matched_idx)),
        extra_calculated=tuple(sorted(extra_positions)),
    )
