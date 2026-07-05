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
    tol_deg: float = 0.2,
    intensity_tol: float = 2.0,
    max_intensity_tol: float = 5.0,
    w_matched: float = 1.0,
    w_wrong: float = 1.0,
    w_missing: float = 0.05,
    w_extra: float = 0.5,
) -> DaraScore:
    """Dara 式(1)のピークマッチングスコアを計算する (CederGroupHub/dara 準拠)。🔵

    分類は Dara の ``find_best_match`` に倣う: 位置一致ペアの強度比 (対数) が
    ``intensity_tol`` (既定 2) 以内なら matched、``max_intensity_tol`` (既定 5) 以内なら
    wrong-intensity、それを超える乖離は「説明不能」としてペアを解消し obs→missing・calc→extra
    にする。matched/wrong の寄与は ``min(観測強度, 計算強度)`` (重なり分)。

    Args:
        calculated_peaks: 参照相のシミュレートピーク列 (位置 2θ・相対強度)。
        observed_peaks: 観測ピーク列。
        tol_deg: 位置一致許容差 (度, 既定 0.2)。
        intensity_tol: matched とみなす強度比の上限 (既定 2)。
        max_intensity_tol: wrong-intensity とみなす強度比の上限。超過はペア解消 (既定 5)。
        w_matched, w_wrong, w_missing, w_extra: 係数 (既定 1.0/1.0/0.05/0.5。missing/extra は減算)。

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

    # 【強度スケール揃え】: 計算 (XRDCalculator 相対強度) を観測スケールへ。matched ペアの最小二乗
    #   スケール s = Σ(obs·calc)/Σ(calc²)。ペア無しは最大強度比で代替 (extra 罰を有意にする)。🔵
    num = sum(float(obs[oi].height) * float(calc[ci].height) for oi, ci in obs_to_calc.items())
    den = sum(float(calc[ci].height) ** 2 for ci in obs_to_calc.values())
    if den > 0.0:
        scale = num / den
    else:
        max_calc = max((float(c.height) for c in calc), default=0.0)
        max_obs = max(float(o.height) for o in obs)
        scale = (max_obs / max_calc) if max_calc > 0.0 else 0.0

    # 【4 分類 (2 閾値)】: 強度比で matched / wrong / (解消→missing+extra) に振り分ける 🔵
    i_matched = i_wrong = i_missing = 0.0
    matched_idx: list[int] = []
    dissolved_calc: set[int] = set()  # ペア解消で extra 化した計算ピーク index
    for oi in range(len(obs)):
        oh = float(obs[oi].height)
        ci = obs_to_calc.get(oi)
        if ci is None:
            i_missing += oh  # 観測にあり計算に無い → missing
            continue
        ch = scale * float(calc[ci].height)
        if ch <= 0.0:
            i_missing += oh
            dissolved_calc.add(ci)
            continue
        ratio = max(oh / ch, ch / oh)  # 対称強度比 (>=1)
        contrib = min(oh, ch)  # 重なり (両者の小さい方)
        if ratio <= intensity_tol:
            i_matched += contrib
            matched_idx.append(oi)
        elif ratio <= max_intensity_tol:
            i_wrong += contrib
            matched_idx.append(oi)
        else:
            # 強度が大きく乖離 → 説明不能。ペア解消し obs→missing, calc→extra 🔵
            i_missing += oh
            dissolved_calc.add(ci)

    # 【extra】: 未マッチ計算ピーク + 解消された計算ピークを観測スケールで集計 🔵
    i_extra = 0.0
    extra_positions: list[float] = []
    for ci in range(len(calc)):
        if not used_calc[ci] or ci in dissolved_calc:
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
