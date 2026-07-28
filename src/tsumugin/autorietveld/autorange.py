"""データ前処理の自動決定 (WS-4: REQ-SAR-401/402/403 + REQ-SAR-404 の設計)。

`docs/spec/stable-auto-rietveld/requirements.md` の「データ前処理の自動化」を担う **numpy
のみの純関数層**。GSAS-II を一切 import せず、観測パターン `(2θ, 強度)` だけから

- **データレンジ** (`suggest_two_theta_range`, REQ-SAR-402)
- **背景 Chebyshev 項数の候補列** (`suggest_background_terms`, REQ-SAR-401)
- **除外領域の候補** (`propose_excluded_regions`, REQ-SAR-403 — **提案のみ**)

を決定論的に導く。返り値はすべて frozen dataclass の素の float/int/str/tuple であり
(`dataclasses.asdict` でそのまま JSON 化できる)、② MCP 境界へ載せられる。

**なぜ要るか (実測された手動調整)**:

- CaTeO3 の **背景 24 項**は人手で決めた値であり、「M9 の鍵」として CLAUDE.md に残っている。
  データが変われば適正項数も変わるので、手で決めた定数は次のデータで壊れる。
- T4 (NAC+CaF2) の非収束の主因は **データリミット未設定**だった。高角のノイズ支配域が点数で
  最小二乗を支配し、フィットを平坦化させていた。`two_theta_limits` を設定して解消した。

いずれも「自動解析ソフト」を名乗る上での穴なので、**人が見て決めていた判断を関数にする**。

## 段の組み立ては呼び手 (レシピ側) の仕事

本モジュールは **候補を返すところまで**を担う。背景項数を 6→12→24 と実際に上げながら
「改善が止まったら確定する」エスカレーション (REQ-SAR-401 の後半) は、実精密化を回せる
レシピ/エンジン側の責務である (境界注入型の走査は既存の
`dataquality.scan_background_coeffs` が既にその形をしている)。ここで返すのは**その段列の
入力となる候補列**である。

## 既存 `dataquality` との関係 (重複ではない)

`dataquality.suggest_two_theta_limit` は ② `assess_data_quality` が呼ぶ **上限 1 値**の
アドバイザで、operando の寄生ピーク運用に合わせた契約 (esd 非対応・切り詰めガードなし) を
持つ。本モジュールの `suggest_two_theta_range` は **下限/上限の組** (`two_theta_limits` に
そのまま渡せる形) を返し、esd (計数統計) を noise 推定に使い、切り詰め量にガードを掛ける。
契約が違うので統合せず、**同じ合成データで両者が同じ信号終端域を指すことをテストで縛る**
(`test_range_upper_is_consistent_with_dataquality_single_limit` = 実装 drift 検出)。

## REQ-SAR-404 (Le Bail 基準線) の設計 — 本モジュールでは実装しない

「構造モデルがどこまで説明できるはずか」の基準線は Le Bail 抽出 (格子固定・各反射強度を
反復抽出し構造因子を使わない) の Rwp で与えられる。**これは実精密化が要るのでエンジン層の
仕事**であり (本モジュールは GSAS を触らない)、ここには実装せず設計だけ残す。

実装するときの手順:

1. **子スナップショット上で行う** (P2 非破壊)。通常の段階解放で得た gpx を複製し、
   そこで Le Bail を回す。元の精密化状態を上書きしない。
2. 各相のヒストグラム-相 (HAP) フラグ `LeBail` を True にし、**構造パラメータ (座標・占有率・
   Uiso) と相スケールを凍結**する。反射強度は Le Bail 反復が更新する。
3. 解放するのは**背景 (本モジュールの推奨項数) + プロファイル + ゼロ点**のみ。
   **格子は Rietveld で得た値に固定する** — Le Bail は抽出強度とセルが強く相関し計量テンソルが
   発散することが `cell_refine` の設計で実測済みで、そこは踏まない。
4. 収束まで数サイクル回し、得た Rwp を `lebail_rwp` として結果へ添える。
5. **解釈**: 構造モデルの Rwp が `lebail_rwp` に近ければ、残差は構造ではなく
   プロファイル/背景/データ由来であり、**構造をいじっても下がらない**。大きく離れていれば
   構造モデル (相の欠落・占有率・座標) に伸び代がある。Rwp の絶対値でなく**この差**が
   「次に何を触るか」を決める。
6. Le Bail 自身が収束していない場合 (REQ-SAR-101 の収束判定を流用) は基準線として報告しない。
   基準線が信用できないまま「モデルに伸び代なし」と言う方が有害である。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view

from ..reference.background import estimate_snip_background

__all__ = [
    "BackgroundTermsSuggestion",
    "ExcludedRegionCandidate",
    "ExclusionProposal",
    "TwoThetaRangeSuggestion",
    "propose_excluded_regions",
    "suggest_background_terms",
    "suggest_two_theta_range",
]


# =========================================================================
# 共通ヘルパ
# =========================================================================


def _as_sorted_xy(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    esd: "Sequence[float] | np.ndarray | None" = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
    """`(x, y[, esd])` を float 配列へ揃え x 昇順に並べ替える (入力配列は破壊しない)。"""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if x_arr.size != y_arr.size:
        raise ValueError(f"x と y の長さが一致しません: {x_arr.size} != {y_arr.size}")
    e_arr: np.ndarray | None = None
    if esd is not None:
        e_arr = np.asarray(esd, dtype=float)
        if e_arr.size != x_arr.size:
            raise ValueError(f"esd の長さが x と一致しません: {e_arr.size} != {x_arr.size}")
    order = np.argsort(x_arr, kind="stable")
    return x_arr[order], y_arr[order], (e_arr[order] if e_arr is not None else None)


def _point_noise(y: np.ndarray) -> float:
    """隣接差分から計数統計ノイズ σ をロバスト推定する。

    ``σ = 1.4826·median(|Δy|)/√2``。背景の傾斜やピークの裾があっても隣接差分の**中央値**は
    それらに引きずられないため、パターン全体の標準偏差より遥かに素直な noise 推定になる
    (√2 は差分が独立 2 点の差であることの補正)。
    """
    if y.size < 2:
        return 0.0
    diffs = np.abs(np.diff(y))
    return float(1.4826 * np.median(diffs) / np.sqrt(2.0))


def _window_grid(n: int, window: int, step: int) -> np.ndarray:
    """ローリング窓の開始 index グリッド (決定論)。"""
    return np.arange(0, n - window + 1, step, dtype=int)


# =========================================================================
# 4-2 データレンジ自動決定 (REQ-SAR-402)
# =========================================================================


@dataclass(frozen=True)
class TwoThetaRangeSuggestion:
    """`suggest_two_theta_range` の提案 (不変・素のスカラのみ)。

    :param lower: 提案する下限 2θ
    :param upper: 提案する上限 2θ
    :param data_lower: 元データの下限 2θ
    :param data_upper: 元データの上限 2θ
    :param n_points_kept: 提案レンジ内に残る観測点数
    :param fraction_kept: 全点数に対する残存比 (0-1)
    :param lower_reason: 下限をそう決めた理由 (人間/③ が読む)
    :param upper_reason: 上限をそう決めた理由
    :param noise_model: S/N 判定に使った noise 推定 (``"esd"`` = 計数統計 / ``"mad"`` = ロバスト分散)
    """

    lower: float
    upper: float
    data_lower: float
    data_upper: float
    n_points_kept: int
    fraction_kept: float
    lower_reason: str
    upper_reason: str
    noise_model: str

    def as_limits(self) -> tuple[float, float]:
        """ヒストグラム仕様の `two_theta_limits` に渡せる `(下限, 上限)` 組を返す。

        **適用するのは呼び手**である (本モジュールは提案までしか行わない)。
        """
        return (self.lower, self.upper)


def suggest_two_theta_range(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    esd: "Sequence[float] | np.ndarray | None" = None,
    *,
    snr_min: float = 5.0,
    window: int = 51,
    min_signal_points: int = 3,
    beamstop_factor: float = 3.0,
    min_fraction_kept: float = 0.15,
    excluded_regions: "Sequence[tuple[float, float]] | None" = None,
) -> TwoThetaRangeSuggestion:
    """精密化に使う 2θ レンジ (下限/上限) を観測パターンから自動決定する (REQ-SAR-402)。

    **上限 = 高角側のノイズ支配域の始まり**。高角から低角へローリング窓をずらし、窓内の
    「最大 − 中央値」が noise の `snr_min` 倍に達する最初の窓 (= 最後の Bragg 信号) の端を
    上限とする。noise は `esd` が与えられれば**その窓の中央 esd (計数統計そのもの)**、
    無ければ MAD ベースのロバスト分散 (``1.4826·MAD``) を使う。前者を優先するのは、
    平滑化/リビンされたデータでは MAD が真のノイズを過小評価し、逆にピーク裾を多く含む窓では
    過大評価するためである。ノイズ支配域を切ることが目的なのは、**そこが点数で最小二乗を
    支配してフィットを平坦化させるから**である (T4 の非収束主因)。

    **下限 = ビームストップ/空気散乱の裾の終わり**。低角側は「信号が無い」のではなく
    **背景モデルで説明できない巨大強度がある**のが問題なので、S/N ではなく水準で判定する:
    ローリング中央値 (ピークに強い) がパターン全体の背景水準の `beamstop_factor` 倍を
    下回る最初の点を下限とする。裾が無いデータでは下限は動かない。

    **切り詰めガード**: 残存点数が全点数の `min_fraction_kept` を下回る提案は、中心を保った
    まま満たすところまで広げる。**片側何 % までという形にしない**のは、ノイズ支配域が全点数の
    半分を超えるデータ (T4 がまさにそれ) で正しい切り詰めを妨げてしまうためである。
    また**信号がどこにも見つからない**場合は下限・上限とも一切動かさない (判定できないデータで
    破壊的に切るより、全域を残して呼び手に判断させる方が安全である)。

    :param x: 2θ 配列 (昇順でなくても内部でソートする)
    :param y: 観測強度
    :param esd: 観測 esd (計数統計)。与えれば noise 推定に使う
    :param snr_min: 「信号あり」とみなす窓内 S/N の閾値 (`dataquality` と同じ既定 5.0)
    :param window: ローリング窓の点数
    :param min_signal_points: 「信号あり」に必要な閾値超え点数。単発のノイズスパイクを信号と
        誤らないための持続性要求 (窓が数百個ある = 多重比較なので S/N 単独では負ける)
    :param beamstop_factor: 背景水準の何倍を「ビームストップ裾」とみなすか
    :param min_fraction_kept: 残さなければならない点数比の下限 (0-1)。下回る提案は中心を保って広げる
    :param excluded_regions: 判定から外す 2θ 区間の列。寄生ピーク等の「実在するが試料でない
        強度」を上限判定に混ぜないために使う (混ぜると上限が寄生ピークまで押し出される)
    :returns: `TwoThetaRangeSuggestion`
    :raises ValueError: `x`/`y`/`esd` の長さが一致しない場合 (空配列は例外化せず縮退する)
    """
    x_all, y_all, e_all = _as_sorted_xy(x, y, esd)
    n_all = x_all.size
    noise_model = "esd" if e_all is not None else "mad"

    if n_all == 0:
        return TwoThetaRangeSuggestion(
            lower=0.0,
            upper=0.0,
            data_lower=0.0,
            data_upper=0.0,
            n_points_kept=0,
            fraction_kept=0.0,
            lower_reason="データ点数が 0 のため判定できません。",
            upper_reason="データ点数が 0 のため判定できません。",
            noise_model=noise_model,
        )

    data_lower, data_upper = float(x_all[0]), float(x_all[-1])

    def _full(reason: str) -> TwoThetaRangeSuggestion:
        return TwoThetaRangeSuggestion(
            lower=data_lower,
            upper=data_upper,
            data_lower=data_lower,
            data_upper=data_upper,
            n_points_kept=int(n_all),
            fraction_kept=1.0,
            lower_reason=reason,
            upper_reason=reason,
            noise_model=noise_model,
        )

    # 判定に使う点 (除外区間は上限判定へ寄与させない)
    x_j, y_j, e_j = x_all, y_all, e_all
    if excluded_regions:
        keep = np.ones(n_all, dtype=bool)
        for lo, hi in excluded_regions:
            keep &= ~((x_all >= float(lo)) & (x_all <= float(hi)))
        if not np.any(keep):
            return _full("除外区間を除くと判定に使える点が残らないため全域を維持しました。")
        x_j, y_j = x_all[keep], y_all[keep]
        e_j = e_all[keep] if e_all is not None else None

    n_j = x_j.size
    win = max(3, min(int(window), n_j))
    if win >= n_j:
        return _full(f"点数 ({n_j}) がローリング窓 ({window}) を割れないため全域を維持しました。")
    step = max(1, win // 4)

    starts = _window_grid(n_j, win, step)
    win_y = sliding_window_view(y_j, win)[starts]
    med = np.median(win_y, axis=1)
    mx = np.max(win_y, axis=1)
    if e_j is not None:
        noise = np.median(sliding_window_view(e_j, win)[starts], axis=1)
    else:
        noise = 1.4826 * np.median(np.abs(win_y - med[:, None]), axis=1)
    # noise=0 (ノイズの無い合成データ・平坦窓) は 0 除算になる。窓内に高低差があるなら信号
    # ありとして inf、完全に平坦なら 0 とする (`dataquality` の縮退規約と同じ)。
    with np.errstate(divide="ignore", invalid="ignore"):
        snr = np.where(
            noise > 0.0,
            (mx - med) / np.where(noise > 0.0, noise, 1.0),
            np.where(mx > med, np.inf, 0.0),
        )

    # **持続性の要求**: 窓内で閾値を超える点が `min_signal_points` 点以上あること。
    # S/N 単独 (窓内最大 1 点) では多重比較に負ける — 窓は数百個あるので、純ノイズでも
    # どこかの窓が 5σ を超える点を 1 つ持ってしまい、上限が高角のノイズ域まで押し出される
    # (実測: 全域ノイズの合成データで誤って 42.5° を「信号終端」と判定した)。
    # 実ピークは必ず複数点にまたがるので、点数を要求するだけで単発スパイクと分離できる。
    above = np.count_nonzero(win_y > (med + snr_min * noise)[:, None], axis=1)
    signal = np.flatnonzero((snr >= snr_min) & (above >= min_signal_points))
    if signal.size == 0:
        # 信号が 1 つも見つからない: 切り詰めの根拠が無い。全域維持へ縮退する (非破壊)。
        return _full(
            f"S/N>={snr_min} の信号が全域で検出できないため、レンジを一切切り詰めませんでした "
            "(データまたは noise 推定を確認してください)。"
        )

    # --- 上限: 最も高角側にある「信号あり」窓の端 ---
    upper_raw = float(x_j[starts[int(signal[-1])] + win - 1])
    upper_reason = (
        f"2θ>{upper_raw:.3f}° は窓内 S/N<{snr_min} (noise={noise_model}) のノイズ支配域と判定。"
        "点数で最小二乗を支配しフィットを平坦化させるため除外を提案します。"
    )
    if upper_raw >= data_upper:
        upper_reason = "高角端まで Bragg 信号が続くため上限は動かしません。"

    # --- 下限: ビームストップ/空気散乱の裾 (S/N ではなく水準で判定) ---
    background_level = float(np.median(med))
    threshold = beamstop_factor * background_level
    lower_raw = data_lower
    lower_reason = "低角端にビームストップ/空気散乱の裾は検出されませんでした。"
    if background_level > 0.0 and med[0] > threshold:
        below = np.flatnonzero(med <= threshold)
        if below.size > 0:
            lower_raw = float(x_j[starts[int(below[0])]])
            lower_reason = (
                f"2θ<{lower_raw:.3f}° はローリング中央値が背景水準 ({background_level:.4g}) の"
                f"{beamstop_factor} 倍を超えるビームストップ/空気散乱の裾。"
                "背景多項式では説明できない巨大強度が重み付き最小二乗を支配するため除外を提案します。"
            )

    if not lower_raw < upper_raw:
        return _full("下限が上限を上回る判定になったため全域を維持しました (判定不能)。")

    # --- 切り詰めガード: 残存点数が下限を割るなら中心を保ったまま広げる ---
    lo_idx = int(np.searchsorted(x_all, lower_raw, side="left"))
    hi_idx = int(np.searchsorted(x_all, upper_raw, side="right")) - 1
    lo_idx = max(0, min(lo_idx, n_all - 1))
    hi_idx = max(lo_idx, min(hi_idx, n_all - 1))
    target = int(np.ceil(max(0.0, min(1.0, min_fraction_kept)) * n_all))
    need = target - (hi_idx - lo_idx + 1)
    if need > 0:
        add_hi = min(n_all - 1 - hi_idx, need)
        add_lo = min(lo_idx, need - add_hi)
        add_hi = min(n_all - 1 - hi_idx, need - add_lo)
        lo_idx -= add_lo
        hi_idx += add_hi
        guard = (
            f" (ガード: 残存点数が全体の {min_fraction_kept:.0%} を下回るため、"
            "中心を保ったまま広げました)"
        )
        lower_reason += guard
        upper_reason += guard

    lower, upper = float(x_all[lo_idx]), float(x_all[hi_idx])
    kept = hi_idx - lo_idx + 1
    return TwoThetaRangeSuggestion(
        lower=lower,
        upper=upper,
        data_lower=data_lower,
        data_upper=data_upper,
        n_points_kept=kept,
        fraction_kept=float(kept) / float(n_all),
        lower_reason=lower_reason,
        upper_reason=upper_reason,
        noise_model=noise_model,
    )


# =========================================================================
# 4-1 背景項数の提案 (REQ-SAR-401)
# =========================================================================


@dataclass(frozen=True)
class BackgroundTermsSuggestion:
    """`suggest_background_terms` の提案 (不変)。

    :param candidates: **エスカレーションの候補列** (昇順・重複なし)。段列を組むのはレシピ側
    :param recommended: 推奨項数 (`candidates` に必ず含まれる)
    :param n_inflections: 推定背景のうねりの数 (有意な転回点の数)。複雑さの目安
    :param noise_level: 観測の計数統計ノイズ σ (推奨判定の基準)
    :param misfits: `(項数, Chebyshev 当てはめ残差 rms)` の列 (昇順)
    :param reason: 推奨の根拠 (人間/③ が読む)
    """

    candidates: tuple[int, ...]
    recommended: int
    n_inflections: int
    noise_level: float
    misfits: tuple[tuple[int, float], ...]
    reason: str


def _count_waves(values: np.ndarray, threshold: float) -> int:
    """曲線の「有意な転回点」の数を数える (うねりの複雑さ指標)。

    単純な符号反転の数は、平坦な背景でも当てはめ誤差の微小な波で膨らむ。そこで各転回点の
    **prominence** (隣接する転回点との値差の小さい方) を測り、`threshold` を超えるものだけを
    数える。これによりノイズ由来の微小な波が指標を汚さない。
    """
    if values.size < 3:
        return 0
    d1 = np.gradient(values)
    sign = np.sign(d1)
    turns = [
        i
        for i in range(1, sign.size)
        if sign[i] != 0 and sign[i - 1] != 0 and sign[i] != sign[i - 1]
    ]
    if not turns:
        return 0
    pts = [0, *turns, values.size - 1]
    count = 0
    for k in range(1, len(pts) - 1):
        prominence = min(
            abs(float(values[pts[k]] - values[pts[k - 1]])),
            abs(float(values[pts[k]] - values[pts[k + 1]])),
        )
        if prominence > threshold:
            count += 1
    return count


def suggest_background_terms(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    *,
    ladder: Sequence[int] = (6, 12, 18, 24, 36),
    noise_factor: float = 1.5,
    improvement_tol: float = 0.05,
    headroom: int = 1,
    snip_window: int = 50,
) -> BackgroundTermsSuggestion:
    """背景の曲率/うねりから Chebyshev 項数の候補列を提案する (REQ-SAR-401)。

    **手順**: SNIP (`reference.background.estimate_snip_background`) で背景を推定し、ピーク域を
    除いた点に対して項数を `ladder` に沿って増やしながら Chebyshev を当てはめ、残差 rms が
    **計数統計ノイズ σ の `noise_factor` 倍以下**になる最小の項数を推奨とする。
    「残差がノイズに埋もれたらそれ以上の項は背景でなくノイズを追う」という基準であり、
    項数を増やせば必ず残差が減る指標 (rms 単独) で決めない (相数を Rwp で決めない規律と同じ)。

    ノイズが推定できない (合成データ等で σ≈0) 場合は**改善の飽和**へフォールバックする:
    1 段上げても残差の相対改善が `improvement_tol` 未満なら、そこで確定する。

    **ピーク域を当てはめから外す**のは、SNIP が強いピークの直下で背景を過小評価しがちで、
    その系統誤差を「背景のうねり」と誤読すると項数を過大に見積もるためである。

    返すのは**候補列**であり、実際に 6→12→24 と上げながら改善が止まった時点で確定する
    エスカレーション自体は、実精密化を回せるレシピ/エンジン側の仕事である
    (境界注入型の走査は `dataquality.scan_background_coeffs` を使える)。

    :param x: 2θ 配列
    :param y: 観測強度
    :param ladder: 走査する項数の梯子 (昇順・GSAS の Chebyshev 係数の**個数**)
    :param noise_factor: 残差 rms が σ の何倍以下なら「十分」とみなすか
    :param improvement_tol: 飽和判定の相対改善閾値 (ノイズ推定不能時のフォールバック)
    :param headroom: 推奨より上に何段ぶん候補を残すか (レシピ側がさらに上げられる余地)
    :param snip_window: SNIP のクリップ窓幅 (点数)
    :returns: `BackgroundTermsSuggestion`
    :raises ValueError: `x`/`y` の長さが一致しない、または `ladder` が空の場合
    """
    rungs = tuple(sorted({int(v) for v in ladder if int(v) >= 1}))
    if not rungs:
        raise ValueError("ladder が空です。走査する背景項数を 1 つ以上指定してください。")

    x_arr, y_arr, _ = _as_sorted_xy(x, y)
    if x_arr.size < 4 or float(x_arr[-1] - x_arr[0]) <= 0.0:
        return BackgroundTermsSuggestion(
            candidates=(rungs[0],),
            recommended=rungs[0],
            n_inflections=0,
            noise_level=0.0,
            misfits=(),
            reason="点数が不足しているため背景の複雑さを評価できません。最小項数を提案します。",
        )

    sigma = _point_noise(y_arr)
    background = estimate_snip_background(y_arr, max_window=snip_window)

    # ピーク域を当てはめから外す (SNIP の系統誤差を「うねり」と誤読しないため)
    excess = y_arr - background
    cut = max(3.0 * sigma, 1e-12)
    baseline_mask = excess <= cut
    if int(np.count_nonzero(baseline_mask)) < max(4 * rungs[-1], 32):
        baseline_mask = np.ones(x_arr.size, dtype=bool)

    span = float(x_arr[-1] - x_arr[0])
    u = 2.0 * (x_arr - x_arr[0]) / span - 1.0
    u_fit, b_fit = u[baseline_mask], background[baseline_mask]

    # 項数の上限: 当てはめ点数に対して過剰な自由度を提案しない
    max_terms = max(2, u_fit.size // 10)
    usable = tuple(t for t in rungs if t <= max_terms) or (rungs[0],)

    misfits: list[tuple[int, float]] = []
    fits: dict[int, np.polynomial.chebyshev.Chebyshev] = {}
    for terms in usable:
        cheb = np.polynomial.chebyshev.Chebyshev.fit(
            u_fit, b_fit, deg=terms - 1, domain=[-1.0, 1.0]
        )
        resid = b_fit - cheb(u_fit)
        fits[terms] = cheb
        misfits.append((int(terms), float(np.sqrt(np.mean(resid**2)))))

    recommended = usable[-1]
    reason = (
        f"最大項数 {usable[-1]} まで残差がノイズ水準 (σ={sigma:.4g} の {noise_factor} 倍) へ"
        "落ちませんでした。背景が複雑なため上限を推奨します。"
    )
    if sigma > 0.0:
        for terms, rms in misfits:
            if rms <= noise_factor * sigma:
                recommended = terms
                reason = (
                    f"{terms} 項で Chebyshev 当てはめ残差 (rms={rms:.4g}) が計数統計ノイズ "
                    f"σ={sigma:.4g} の {noise_factor} 倍以下に収まりました。"
                    "これ以上の項は背景でなくノイズを追います。"
                )
                break
    else:
        reason = (
            "ノイズが推定できない (σ≈0) ため、改善の飽和で決定しました "
            f"(相対改善 <{improvement_tol:.0%} で確定)。"
        )
        recommended = usable[0]
        for i in range(1, len(misfits)):
            prev_rms = misfits[i - 1][1]
            gain = (prev_rms - misfits[i][1]) / prev_rms if prev_rms > 0.0 else 0.0
            if gain < improvement_tol:
                recommended = misfits[i - 1][0]
                break
            recommended = misfits[i][0]

    # 候補列: 最小項数から推奨まで + headroom 段 (レシピ側がさらに上げられる余地を残す)
    idx = usable.index(recommended)
    candidates = usable[: min(len(usable), idx + 1 + max(0, int(headroom)))]
    if len(candidates) < 2 and len(usable) >= 2:
        candidates = usable[:2]

    grid = np.linspace(-1.0, 1.0, 201)
    curve = fits[recommended](grid)
    p2p = float(np.max(curve) - np.min(curve))
    n_inflections = _count_waves(curve, threshold=max(3.0 * sigma, 0.02 * p2p))

    return BackgroundTermsSuggestion(
        candidates=tuple(int(c) for c in candidates),
        recommended=int(recommended),
        n_inflections=int(n_inflections),
        noise_level=float(sigma),
        misfits=tuple(misfits),
        reason=reason,
    )


# =========================================================================
# 4-3 除外領域の提案 (REQ-SAR-403) — 提案のみ・自動適用禁止
# =========================================================================


@dataclass(frozen=True)
class ExcludedRegionCandidate:
    """除外**候補** 1 件 (不変)。適用は人間/③ の承認を要する (P-SAR-3)。

    :param center: ピーク中心 2θ
    :param lower: 候補区間の下限 2θ
    :param upper: 候補区間の上限 2θ
    :param height: 背景差引後のピーク高さ
    :param snr: 高さ / 計数統計ノイズ σ
    :param fwhm: 推定半値全幅 (2θ)
    :param sharpness: 試料ピーク代表幅 / 本ピーク幅。>1 で「試料より鋭い」
    :param nearest_explained: 供給された反射位置のうち最も近いものとの距離 (未供給なら None)
    :param reason: 候補に挙げた理由
    """

    center: float
    lower: float
    upper: float
    height: float
    snr: float
    fwhm: float
    sharpness: float
    nearest_explained: float | None
    reason: str


@dataclass(frozen=True)
class ExclusionProposal:
    """除外領域の**提案** (不変)。**適用 API を持たない**ことが型の主張である。

    :param candidates: 除外候補 (snr 降順)
    :param requires_human_approval: 常に True。適用は人間/③ の承認を要する (P-SAR-3)
    :param note: 適用前に読むべき注意 (未知相を消す危険)
    :param n_peaks_examined: 検討したピーク数
    :param median_fwhm: 試料ピークの代表幅 (中央値)
    :param noise_level: 計数統計ノイズ σ
    """

    candidates: tuple[ExcludedRegionCandidate, ...]
    requires_human_approval: bool
    note: str
    n_peaks_examined: int
    median_fwhm: float
    noise_level: float


def _estimate_fwhm(x: np.ndarray, y: np.ndarray, index: int) -> float:
    """ピーク位置 `index` の半値全幅を半値交差の走査で推定する (背景差引後の y を渡すこと)。"""
    half = 0.5 * float(y[index])
    left = index
    while left > 0 and y[left] > half:
        left -= 1
    right = index
    while right < y.size - 1 and y[right] > half:
        right += 1
    width = float(x[right] - x[left])
    if width <= 0.0:
        width = float(np.median(np.diff(x))) if x.size > 1 else 0.0
    return width


def propose_excluded_regions(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    *,
    explained_two_theta: "Sequence[float] | None" = None,
    match_tolerance: float = 0.15,
    snr_min: float = 8.0,
    sharpness_min: float = 2.0,
    isolation_factor: float = 5.0,
    pad_factor: float = 3.0,
    max_candidates: int = 10,
    snip_window: int = 50,
) -> ExclusionProposal:
    """どの相でも説明できない**鋭い孤立ピーク**を除外候補として提案する (REQ-SAR-403)。

    **自動適用しない** (P-SAR-3)。除外は解析の解釈を変える操作であり、未知相のピークを
    アーチファクトとして消せば相同定を殺す。返り値は候補と注意書きだけで、適用 API は持たない。

    候補の条件は 3 つとも満たすことである。「鋭い」を必須にするのが安全設計の要点で、
    **通常幅の未説明ピークは除外候補ではなく「相が足りない」証拠**だからである
    (それは `residual_report` / 相同定の担当)。

    1. **鋭い**: 幅が試料ピーク代表幅 (検出ピーク FWHM の中央値) の `1/sharpness_min` 以下。
       検出器スパイク・宇宙線・試料ホルダ由来の寄生線は、試料の粒径/装置分解能に従わない。
    2. **孤立**: 最近接ピークまで代表幅の `isolation_factor` 倍以上離れている。
       相のピークは群れを作るので、単独で立つピークほどアーチファクトらしい。
    3. **未説明**: `explained_two_theta` (相が予測する反射位置) のいずれからも
       `match_tolerance` より遠い。未供給なら偽陽性が増えるので `note` で警告する。

    **限界**: 代表幅を検出ピークの中央値に取るため、**アーチファクトが多数派のデータでは
    判定が反転する** (アーチファクトが「普通」になる)。試料ピークが多数派であることが前提。

    :param x: 2θ 配列
    :param y: 観測強度
    :param explained_two_theta: 相が説明する反射位置の列 (相同定/精密化の出力)
    :param match_tolerance: 「説明済み」とみなす位置の許容差 (2θ)
    :param snr_min: ピーク検出の S/N 閾値
    :param sharpness_min: 「鋭い」とみなす代表幅との比
    :param isolation_factor: 「孤立」とみなす最近接距離 (代表幅の倍数)
    :param pad_factor: 候補区間の幅 (中心 ± `pad_factor`×FWHM)
    :param max_candidates: 返す候補の最大数 (snr 降順)
    :param snip_window: SNIP のクリップ窓幅 (点数)
    :returns: `ExclusionProposal`
    :raises ValueError: `x`/`y` の長さが一致しない場合 (空配列は例外化せず縮退する)
    """
    x_arr, y_arr, _ = _as_sorted_xy(x, y)

    supplied = explained_two_theta is not None
    note = (
        "これは**候補**です。除外は解析の解釈を変えるため、適用には人間/③ の承認が必要です "
        "(P-SAR-3)。未知相のピークをアーチファクトとして消すと相同定を殺します。"
    )
    if not supplied:
        note += (
            " 相の反射位置 (explained_two_theta) が未供給のため、"
            "「どの相でも説明できない」の判定は行えておらず偽陽性が増えます。"
        )

    if x_arr.size < 5:
        return ExclusionProposal(
            candidates=(),
            requires_human_approval=True,
            note=note + " (点数不足のため判定していません)",
            n_peaks_examined=0,
            median_fwhm=0.0,
            noise_level=0.0,
        )

    sigma = _point_noise(y_arr)
    residual = y_arr - estimate_snip_background(y_arr, max_window=snip_window)
    floor = snr_min * sigma if sigma > 0.0 else 0.0

    interior = np.flatnonzero(
        (residual[1:-1] > residual[:-2])
        & (residual[1:-1] > residual[2:])
        & (residual[1:-1] > floor)
    ) + 1
    if interior.size == 0:
        return ExclusionProposal(
            candidates=(),
            requires_human_approval=True,
            note=note,
            n_peaks_examined=0,
            median_fwhm=0.0,
            noise_level=sigma,
        )

    # 高い順に貪欲採用し、自身の FWHM 内の副次極大 (肩) を同一ピークとして統合する
    order = interior[np.argsort(-residual[interior], kind="stable")]
    kept: list[tuple[int, float]] = []
    for idx in order:
        pos = float(x_arr[idx])
        fwhm = _estimate_fwhm(x_arr, residual, int(idx))
        if any(abs(pos - float(x_arr[k])) < max(fwhm, w) for k, w in kept):
            continue
        kept.append((int(idx), fwhm))
    kept.sort(key=lambda item: item[0])

    widths = np.asarray([w for _, w in kept], dtype=float)
    median_fwhm = float(np.median(widths))
    positions = np.asarray([float(x_arr[i]) for i, _ in kept], dtype=float)

    candidates: list[ExcludedRegionCandidate] = []
    if median_fwhm > 0.0 and len(kept) >= 2:
        explained = (
            np.asarray(list(explained_two_theta), dtype=float) if supplied else np.empty(0)
        )
        for k, (idx, fwhm) in enumerate(kept):
            if fwhm <= 0.0:
                continue
            sharpness = median_fwhm / fwhm
            if sharpness < sharpness_min:
                continue
            others = np.delete(positions, k)
            isolation = (
                float(np.min(np.abs(others - positions[k]))) if others.size else float("inf")
            )
            if isolation < isolation_factor * median_fwhm:
                continue
            nearest: float | None = None
            if supplied and explained.size:
                nearest = float(np.min(np.abs(explained - positions[k])))
                if nearest <= match_tolerance:
                    continue
            height = float(residual[idx])
            candidates.append(
                ExcludedRegionCandidate(
                    center=positions[k],
                    lower=positions[k] - pad_factor * fwhm,
                    upper=positions[k] + pad_factor * fwhm,
                    height=height,
                    snr=height / sigma if sigma > 0.0 else float("inf"),
                    fwhm=fwhm,
                    sharpness=sharpness,
                    nearest_explained=nearest,
                    reason=(
                        f"幅 {fwhm:.4g}° は試料ピーク代表幅 {median_fwhm:.4g}° の "
                        f"1/{sharpness:.2g} と鋭く、最近接ピークまで {isolation:.3g}° 孤立している"
                        + (
                            f"。供給された反射位置から {nearest:.3g}° 離れており説明されない"
                            if nearest is not None
                            else "。相の反射位置が未供給のため未説明かは未確認"
                        )
                    ),
                )
            )

    candidates.sort(key=lambda c: (-c.snr, c.center))
    return ExclusionProposal(
        candidates=tuple(candidates[: max(0, int(max_candidates))]),
        requires_human_approval=True,
        note=note,
        n_peaks_examined=len(kept),
        median_fwhm=median_fwhm,
        noise_level=sigma,
    )
