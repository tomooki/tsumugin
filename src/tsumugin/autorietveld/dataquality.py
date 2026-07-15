"""データ品質診断 (第2層 = 決定論条件判定): 背景減算検出・2θ上限提案・背景項走査 (Issue #78)。

K₂Mn[Fe(CN)₆] operando 実解析で判明した、データ品質そのものが最大の改善要因になるケースを
決定論ルールとして先読み検出するアドバイザ。**分析・提案のみ**を行い、エンジンの既定動作は
変えない (非破壊)。

- `detect_background_subtracted`: 背景**減算済み**データ (esd=√I 重み付けが減算後のノイズ底を
  過大評価し Rwp を膨らませる; 実測 26%→生データ+背景精密化で 6.7%) を検出する。
- `suggest_two_theta_limit`: 高角のノイズ領域が最小二乗を支配する問題を避けるため、Bragg 信号が
  途絶える 2θ を検出し上限を提案する (実測: 30°→18° で 369s→8s かつ収束改善)。
- `scan_background_coeffs`: 背景項数を境界注入された `runner` で走査し最良 Rwp の項数を返す
  (境界層は呼び出し側が実精密化を配線する; GSAS は import しない)。

numpy のみで完結する (CLAUDE.md 不変条件: コア import は numpy のみ)。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

import numpy as np


@dataclass(frozen=True)
class BackgroundSubtractedReport:
    """`detect_background_subtracted` の判定結果 (不変)。

    :param is_subtracted: 背景減算済みデータの可能性が高いか
    :param confidence: 判定信頼度 (0-1; ヒューリスティック投票の重み付き割合)
    :param baseline_level: 推定ベースライン水準 (下位 percentile 点の強度)
    :param peak_max: 最大強度 (ピーク高さの目安)
    :param reasons: 判定根拠 (発火したヒューリスティックの説明文の列; 空 = 根拠なし)
    :param recommendation: 推奨アクション文
    """

    is_subtracted: bool
    confidence: float
    baseline_level: float
    peak_max: float
    reasons: tuple[str, ...]
    recommendation: str


@dataclass(frozen=True)
class BackgroundScanReport:
    """`scan_background_coeffs` の走査結果 (不変)。

    :param best: 最良 Rwp を与えた背景項数 (同点は項数が最小のものを選ぶ)
    :param results: (項数, Rwp) の列 (`candidates` と同順)
    """

    best: int
    results: tuple[tuple[int, float], ...]


def detect_background_subtracted(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    esd: "Sequence[float] | np.ndarray | None" = None,
    *,
    low_percentile: float = 10.0,
    baseline_ratio_threshold: float = 0.05,
    min_ratio_threshold: float = 0.03,
    flatness_ratio_threshold: float = 0.4,
    flatness_n_bins: int = 20,
    esd_sqrt_rel_tol: float = 0.15,
    vote_threshold: float = 0.5,
) -> BackgroundSubtractedReport:
    """観測データが背景減算済みかを決定論ヒューリスティックの組み合わせで判定する。

    背景減算済みデータは esd=√I 重み付けの下で、減算によりほぼ 0 になったノイズ底を過大に
    重み付けし Rwp を膨らませる (fit の質でなく重み付けの問題)。以下の**判別的な**
    ヒューリスティックのみを重み付き投票で組み合わせる (いずれも独立に成立し得るため OR では
    なく多数決に近い設計。`total_weight` = 1.0+0.7+0.8 = 2.5):

    1. ピーク間ベースライン (下位 `low_percentile` %点) がピーク最大値に対しほぼ 0 (重み 1.0)
    2. 最小強度がピーク最大値に対しほぼ 0 (重み 0.7)
    3. ベースラインが 2θ 全域で平坦・構造なし (重み 0.8。実背景は低角側で立ち上がる等の構造を持つ)

    **`esd ≈ √y` は意図的に投票へ含めない**。`esd=√max(I,1)` は `.xye` 等を作成する際の一般的な
    esd 慣習であり、**生データでも背景減算済みデータでも等しく成立する**ため、減算の有無について
    判別情報を持たないからである。投票に含めると生データにも偽の confidence が乗り (実測: 生
    データが confidence 0.29)、さらに「平坦で低い背景を持つ生データ」では h1+h3 と合算して誤って
    `is_subtracted=True` を導く恐れがある。`esd` は判定に一切用いず、`is_subtracted` が True と
    判定された場合に限り**補助的な文脈情報**として `reasons` に付記する (`esd_sqrt_rel_tol` は
    この付記の判定にのみ使う)。

    閾値はすべてキーワード引数でチューニング可能。データ点数が 0 または最大強度が 0 以下の
    退化ケースは例外を送出せず `is_subtracted=False, confidence=0.0` を返す (判定不能)。

    :param x: 2θ (または TOF) 配列 (昇順を想定)
    :param y: 観測強度
    :param esd: 観測誤差 (esd) 配列。**判定 (confidence) には一切寄与しない**。減算済みと判定
        された場合に補助的な文脈情報を `reasons` へ付記するためだけに使う
    :returns: `BackgroundSubtractedReport`
    """
    y_arr = np.asarray(y, dtype=float)
    x_arr = np.asarray(x, dtype=float)
    n = y_arr.size

    if n == 0:
        return BackgroundSubtractedReport(
            is_subtracted=False,
            confidence=0.0,
            baseline_level=0.0,
            peak_max=0.0,
            reasons=(),
            recommendation="データ点数が 0 のため判定できません。データを確認してください。",
        )

    peak_max = float(np.max(y_arr))
    if peak_max <= 0.0:
        return BackgroundSubtractedReport(
            is_subtracted=False,
            confidence=0.0,
            baseline_level=0.0,
            peak_max=peak_max,
            reasons=(),
            recommendation="最大強度が 0 以下のため判定できません。データを確認してください。",
        )

    baseline_level = float(np.percentile(y_arr, low_percentile))
    min_level = float(np.min(y_arr))

    reasons: list[str] = []
    votes = 0.0
    total_weight = 0.0

    # ヒューリスティック 1: ピーク間ベースラインがほぼ 0
    weight = 1.0
    total_weight += weight
    ratio_baseline = baseline_level / peak_max
    if ratio_baseline < baseline_ratio_threshold:
        votes += weight
        reasons.append(
            f"ピーク間ベースライン(下位{low_percentile:.0f}%点={baseline_level:.3g}) が"
            f"ピーク最大値({peak_max:.3g})に対しほぼ0 (比={ratio_baseline:.3g} "
            f"< 閾値{baseline_ratio_threshold})"
        )

    # ヒューリスティック 2: 最小強度がほぼ 0
    weight = 0.7
    total_weight += weight
    ratio_min = max(min_level, 0.0) / peak_max
    if ratio_min < min_ratio_threshold:
        votes += weight
        reasons.append(
            f"最小強度({min_level:.3g})がピーク最大値に対しほぼ0 "
            f"(比={ratio_min:.3g} < 閾値{min_ratio_threshold})"
        )

    # ヒューリスティック 3: ベースラインの平坦性 (十分なデータ点数がある場合のみ評価)
    if n >= flatness_n_bins * 3:
        edges = np.linspace(float(x_arr.min()), float(x_arr.max()), flatness_n_bins + 1)
        bin_idx = np.clip(np.digitize(x_arr, edges) - 1, 0, flatness_n_bins - 1)
        bin_baselines = [
            np.percentile(y_arr[bin_idx == i], low_percentile)
            for i in range(flatness_n_bins)
            if np.any(bin_idx == i)
        ]
        bin_baselines_arr = np.asarray(bin_baselines, dtype=float)
        if bin_baselines_arr.size >= 3 and np.median(bin_baselines_arr) > 0:
            weight = 0.8
            total_weight += weight
            flatness_ratio = float(np.std(bin_baselines_arr) / np.median(bin_baselines_arr))
            if flatness_ratio < flatness_ratio_threshold:
                votes += weight
                reasons.append(
                    "ピーク間ベースラインが2θ全域でほぼ平坦・構造なし "
                    f"(変動比={flatness_ratio:.3g} < 閾値{flatness_ratio_threshold})"
                )

    # confidence は判別的な h1/h2/h3 のみから決まる (esd は投票に含めない: 下記参照)。
    confidence = votes / total_weight if total_weight > 0 else 0.0
    is_subtracted = confidence >= vote_threshold

    # 補助情報 (投票には不使用): esd ≈ sqrt(強度) か。esd=√max(I,1) は生データ・減算済みデータの
    # 双方で用いられる一般的な慣習であり減算の有無を判別しないため、confidence には寄与させず、
    # 減算済みと判定された場合に限り文脈として付記する。
    if esd is not None and is_subtracted:
        esd_arr = np.asarray(esd, dtype=float)
        if esd_arr.size == y_arr.size and esd_arr.size > 0:
            expected = np.sqrt(np.maximum(y_arr, 1.0))
            valid = expected > 0
            if np.any(valid):
                rel_diff = float(
                    np.median(np.abs(esd_arr[valid] - expected[valid]) / expected[valid])
                )
                if rel_diff < esd_sqrt_rel_tol:
                    reasons.append(
                        "(補助情報; 生データでも成立するため判定には不使用) "
                        "esd が sqrt(強度) にほぼ一致 "
                        f"(中央相対差={rel_diff:.3g} < 閾値{esd_sqrt_rel_tol}); "
                        "減算後強度に対し Poisson esd が与えられている場合、"
                        "ノイズ底が過大に重み付けされる"
                    )

    if is_subtracted:
        recommendation = (
            "背景減算済みデータの可能性があります。esd=√I 重み付けが減算後のノイズ底を"
            "過大評価し Rwp を膨らませるため (実測: 同一モデルで 26%→生データ+背景精密化で 6.7%)、"
            "可能であれば生データ (背景減算前) を使用し、Rietveld 内で背景を精密化することを"
            "推奨します。"
        )
    else:
        recommendation = "生データ(背景未減算)の特徴と判定されました。背景項を精密化してください。"

    return BackgroundSubtractedReport(
        is_subtracted=is_subtracted,
        confidence=confidence,
        baseline_level=baseline_level,
        peak_max=peak_max,
        reasons=tuple(reasons),
        recommendation=recommendation,
    )


def suggest_two_theta_limit(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    *,
    snr_min: float = 5.0,
    window: int = 51,
    excluded_regions: "Sequence[tuple[float, float]] | None" = None,
) -> float:
    """Bragg 信号が高角側で途絶える 2θ (**S/N ベースの信号終端**) を検出し、上限として提案する。

    高角側から低角側へ向けてローリングウィンドウの局所 S/N (=(最大−中央値)/ロバスト標準偏差) を
    評価し、S/N が `snr_min` を下回り続ける (=ノイズのみの) 領域と、信号が存在する領域の
    境界を探す。ロバスト標準偏差は MAD (中央絶対偏差) ベース (``1.4826×MAD``) とし、ウィンドウ内に
    ピークの裾が広く含まれる場合でも通常の標準偏差より外れ値 (ピーク自身) に指標が引きずられ
    にくくする。

    **本関数が返すのは「実強度が S/N 的に途絶える 2θ」であり、「精密化に使うべき上限」そのもの
    ではない**。以下 2 点に注意すること:

    - **寄生ピークは `excluded_regions` で渡すこと**。operando/in-situ セルのハードウェア由来の
      寄生反射は「実在する強度」であり、本関数の S/N 判定は正しくこれを信号として拾う。試料の
      信号終端を求めたい場合、寄生ピークの窓を `excluded_regions` で除外しなければ、上限は寄生
      ピークの位置まで押し出される (実測: K₂Mn[Fe(CN)₆] 生データで寄生ピーク未除外なら 38.1°)。
    - **速度目的でより厳しい上限を選ぶのは利用者の判断**。高角のノイズ領域が最小二乗を支配して
      精密化が遅く不正確になるため、信号終端より内側で切るトレードオフは妥当な運用判断である
      (実測: 2θ≤18° への制限で 369s→8s。この時捨てたのは ~20° 付近の弱い反射のみ)。本関数は
      その判断を代行せず、あくまで信号終端を提示する。

    :param x: 2θ 配列 (昇順を想定; 非昇順でもソートして扱う)
    :param y: 観測強度
    :param snr_min: 「信号あり」とみなす局所 S/N の閾値
    :param window: ローリングウィンドウの点数
    :param excluded_regions: 除外する 2θ 区間 ``(下限, 上限)`` の列 (両端を含む)。区間内の点は
        ローリング統計の計算前にマスクされ、S/N 評価に一切寄与しない。セル由来の寄生ピーク等を
        信号終端の判定から外すために使う。None (既定) なら除外なし。
    :returns: 提案する 2θ 上限。データ範囲内に収まる。信号が終端まで続く場合は `x.max()`。
        データ点数が 0 の場合は 0.0 (判定不能; 例外は送出しない)。除外後に点が残らない場合も
        0.0 を返す。
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)

    if x_arr.size == 0:
        return 0.0

    order = np.argsort(x_arr)
    x_sorted = x_arr[order]
    y_sorted = y_arr[order]

    if excluded_regions:
        # 除外区間内の点をローリング統計の計算前にマスクする (窓端の読み飛ばしではなく点の除去)。
        keep = np.ones(x_sorted.size, dtype=bool)
        for lo, hi in excluded_regions:
            keep &= ~((x_sorted >= float(lo)) & (x_sorted <= float(hi)))
        if not np.any(keep):
            return 0.0
        x_sorted = x_sorted[keep]
        y_sorted = y_sorted[keep]

    n = x_sorted.size
    win = max(3, min(int(window), n))
    if win >= n:
        # ウィンドウを分割できるだけの点数がない: ノイズ推定不能のため全域を信号とみなす
        return float(x_sorted[-1])

    step = max(1, win // 4)

    # 高角側 (配列末尾) から低角側へウィンドウをずらしながら局所 S/N を評価する。
    last_signal_end_idx: int | None = None
    start = n - win
    while start >= 0:
        seg = y_sorted[start : start + win]
        med = float(np.median(seg))
        mx = float(np.max(seg))
        sd = 1.4826 * float(np.median(np.abs(seg - med)))
        if sd > 0:
            snr = (mx - med) / sd
        else:
            snr = 0.0 if mx == med else float("inf")
        if snr >= snr_min:
            last_signal_end_idx = start + win - 1
            break
        start -= step

    if last_signal_end_idx is None:
        # 有意な信号がどこにも見つからない (全域ノイズの疑い): 最も保守的に下限を返す
        return float(x_sorted[0])

    return float(x_sorted[last_signal_end_idx])


def scan_background_coeffs(
    runner: Callable[[int], float],
    candidates: Sequence[int] = (6, 12, 18, 24),
) -> BackgroundScanReport:
    """背景項数の候補を走査し、最良 Rwp を与える項数を選ぶ (境界注入型・GSAS 非依存)。

    `runner` は背景項数を受け取り実精密化を行って Rwp を返す境界層 (呼び出し側が配線する)。
    本関数自体は GSAS を import せず、走査ロジックのみを担う。

    :param runner: 背景項数 → Rwp を返す callable (実精密化への境界)
    :param candidates: 走査する背景項数の候補 (既定: 6, 12, 18, 24)
    :returns: `BackgroundScanReport` (`best` は最小 Rwp を与える項数; 同点は項数最小を選ぶ)
    :raises ValueError: `candidates` が空の場合
    """
    if not candidates:
        raise ValueError("candidates が空です。走査する背景項数を1つ以上指定してください。")

    results = tuple((int(c), float(runner(int(c)))) for c in candidates)
    min_rwp = min(rwp for _, rwp in results)
    best = min(c for c, rwp in results if rwp == min_rwp)
    return BackgroundScanReport(best=best, results=results)
