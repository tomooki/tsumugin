"""相集合の完全性チェック (第2層 → 第3層への提案, Issue #84)。

**計量が近い相は互いの強度を吸収し合う**。ある領域で 1 相を相集合から外すと、残った相
(格子・対称性が近い相) がその強度を肩代わりし、**Rwp は良好なまま物理的に誤った描像**を生む。
実測 (K₂Mn[Fe(CN)₆] operando, mono/cubic/tetra はいずれも cubic 派生で計量が近い) で確認:

- 充電域を cubic+tetra の 2 相に限定 (「充電時に mono は存在しない」という仮定) すると、
  転移端で残留 monoclinic 強度を tetragonal が肩代わりし、tetra 分率が
  ``0.42 → 0.17 → 0.70 → 0.04 → 0.63`` と非物理的に振動した。**この間 Rwp は終始 ~8% で良好**
  — どの適合統計量からも検出できない。
- 全 3 相を同時投入すると、転移端は mono (frac→0)・深充電のみ tetra という**単一ドーム**
  (``0 → 0.58 → 0``) に収束した。これが正しい物理描像。
- 発見したのは人間の物理的直感であり、自動指標では拾えなかった。本モジュールはこの種の
  誤りを**規則で機械的に検出し、第3層 (人間/エージェント) へ再フィットの提案として上げる**。

本モジュールは numpy-only の純粋ロジック層 (GSAS 非依存)。**提案のみ (提案≠適用)**:
`SequentialRietveldResult` を読み取り専用で解析し、`SequentialConfig`/相集合や既存の精密化
結果を一切変更しない。採否の判断は第3層に委ねる。

信頼性: 🔵 Issue #84 (K₂Mn[Fe(CN)₆] 実データで実測された振動パターンを回帰テストとして固定)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from .model import SequentialRietveldResult


@dataclass(frozen=True)
class PhaseSetCompletionReport:
    """系列全体での相集合の完全性チェック結果。

    :param union: 系列全体で 1 度でも使われた相名の和集合 (フレーム順の初出順、安定)
    :param frames_with_missing: 相集合が `union` の**真部分集合**だったフレームの
        (フレーム番号, 欠けていた相名の列) のタプル。フレーム番号昇順
    :param is_complete: 全フレームが `union` と同じ相集合を使っていたか
        (`frames_with_missing` が空であることと同値)
    :param recommendation: 第3層への提案文。`is_complete=False` の場合、欠落フレームを
        `union` の全相で再フィットし分率を比較するよう促す (Rwp では検出できない旨を明記)
    """

    union: tuple[str, ...]
    frames_with_missing: tuple[tuple[int, tuple[str, ...]], ...]
    is_complete: bool
    recommendation: str


@dataclass(frozen=True)
class NonMonotonicReport:
    """相分率系列の非単調性 (振動) チェック結果。

    :param phase_name: 対象の相名
    :param turning_points: 振幅フィルタ後の方向転換 (turning point) 数
    :param flagged: `turning_points > max_turning_points` で振動疑いとして発火したか
    :param fractions: フレーム順の分率系列 (欠測相は 0.0)
    :param reason: 判定理由の説明文 (人間可読)
    """

    phase_name: str
    turning_points: int
    flagged: bool
    fractions: tuple[float, ...]
    reason: str


@dataclass(frozen=True)
class SeedPinnedFrame:
    """相分率が初期 seed に張り付いたまま動かなかったフレーム 1 つの記録。

    :param frame_index: 0 始まりのフレーム番号
    :param axis_value: 軸値 (温度/時間, None 可)
    :param rwp: そのフレームの Rwp (%)。**平凡な値である**ことが本欠陥の質の悪さ (実測 8.4-8.5%)
    :param n_phases: そのフレームの相数 (2 以上のみ判定対象)
    :param seed_value: 等分 seed の値 (= 1/n_phases)
    :param phase_fractions: そのフレームの相名→相分率 (全て seed_value に一致している)
    """

    frame_index: int
    axis_value: float | None
    rwp: float
    n_phases: int
    seed_value: float
    phase_fractions: Mapping[str, float]


@dataclass(frozen=True)
class SeedPinningReport:
    """系列全体の seed 張り付き検査結果 (**提案のみ**: 該当フレームを落としも直しもしない)。

    :param frames: 張り付きと判定されたフレーム (フレーム番号昇順)
    :param flagged: 1 つ以上該当したか
    :param recommendation: 第3層への提案文 (`flagged` 時は原因と再フィット手順を促す)
    """

    frames: tuple[SeedPinnedFrame, ...] = ()
    flagged: bool = False
    recommendation: str = ""


def is_seed_pinned(fractions: Mapping[str, float], *, tol: float = 1e-6) -> bool:
    """相分率が**厳密に**等分 seed (1/n) のままか判定する (= 分率精密化が一度も動いていない)。

    GSAS は多相の HAP Scale を等分 (和=1 制約下で 1/n) から始める。精密化が局所的に動かなかった
    フレームは分率が seed 値のまま返り、**Rwp は平凡なので統計量からは検出できない**
    (実測 K₂Mn[Fe(CN)₆]: 張り付き 9 フレームの Rwp は 8.4-8.5%、系列平均 7.29%)。
    「厳密に seed と一致する」ことだけが指紋である。

    - **単相 (n=1) は判定しない**: 1.0 は seed ではなく和=1 の物理的必然であり、偽陽性にしない。
    - **非有限が混じる分率は判定しない** (精密化失敗の別経路で可視化される)。
    - 許容差は既定 1e-6 = 「厳密一致」。実際に動いた分率が偶然この幅で 1/n に一致する確率は
      無視できる (逆に緩めると正常な等分近傍のフレームを偽陽性にする)。

    :param fractions: 相名→相分率 (和=1 正規化済みの HAP Scale)
    :param tol: seed との一致とみなす許容差
    :returns: 全相が |w − 1/n| < tol なら True
    """
    n = len(fractions)
    if n < 2:
        return False
    values = [float(v) for v in fractions.values()]
    if not all(math.isfinite(v) for v in values):
        return False
    seed = 1.0 / n
    return all(abs(v - seed) < tol for v in values)


def flag_seed_pinned_frames(
    result: SequentialRietveldResult, *, tol: float = 1e-6
) -> SeedPinningReport:
    """系列から相分率が seed に張り付いたフレームを検出する (**提案のみ・自動修正しない**)。

    実測動機 (Issue #96): K₂Mn[Fe(CN)₆] の M10 実行 (247 フレーム) で 9 フレーム
    (`[34, 35, 125, 126, 127, 128, 129, 130, 206]`) が 2 相の seed 値 50/50 に張り付いた。
    **うち 125-130 の 6 連続が tetragonal ドーム頂点の直前**にあり、報告した頂点の位置と高さが
    信用できなくなった。原因は相分率ウォームスタート (Issue #82) が M10 双方向パス/repair に
    配線されておらず、分率が毎フレーム seed から再出発していたこと。

    **黙って落とさない** (提案≠適用): 張り付きフレームは「精密化が動かなかった」証拠であって
    データが悪いとは限らない。可視化して第3層 (人間/エージェント) の判断に委ねる。

    :param result: 検査対象の逐次精密化結果 (変更しない)
    :param tol: `is_seed_pinned` の許容差
    :returns: `SeedPinningReport`
    """
    pinned: list[SeedPinnedFrame] = []
    for f in result.frames:
        # 失敗フレームは refine_failed で既に可視 (張り付きとして二重に報告しない)
        if f.refine_failed:
            continue
        if not is_seed_pinned(f.phase_fractions, tol=tol):
            continue
        n = len(f.phase_fractions)
        pinned.append(
            SeedPinnedFrame(
                frame_index=f.frame_index,
                axis_value=f.axis_value,
                rwp=f.rwp,
                n_phases=n,
                seed_value=1.0 / n,
                phase_fractions=dict(f.phase_fractions),
            )
        )

    if not pinned:
        return SeedPinningReport(
            frames=(),
            flagged=False,
            recommendation="相分率が初期 seed に張り付いたフレームはありません。",
        )

    indices = [f.frame_index for f in pinned]
    recommendation = (
        f"{len(pinned)} フレームの相分率が等分 seed (1/相数) に**厳密に**一致しています "
        f"(フレーム {indices})。これは分率精密化がそのフレームで一度も動かなかった (局所解/"
        "ウォームスタート欠落) 徴候であり、**Rwp は平凡なままなので統計量からは検出できません** "
        "(実測 K2Mn[Fe(CN)6]: 張り付き 9 フレームの Rwp は 8.4-8.5%、うち 6 連続が転移ドーム頂点の"
        "直前にあり頂点の位置と高さを信用できなくした)。該当フレームの分率は**採用せず**、"
        "近傍の良好フレームからウォームスタートして再フィットしてください "
        "(repair_frames、または相分率ウォームスタートを有効にした系列の再実行)。"
    )
    return SeedPinningReport(frames=tuple(pinned), flagged=True, recommendation=recommendation)


def suggest_phase_set_completion(result: SequentialRietveldResult) -> PhaseSetCompletionReport:
    """系列全体でフレーム毎の相集合が統一されているか調べ、非統一なら再フィットを提案する。

    ある領域だけ相集合が狭められている (例: 「充電時に mono は存在しない」という仮定で mono を
    除外) 解析は、除外相の強度を計量の近い残存相が肩代わりするリスクパターンである。系列全体の
    相名の**和集合** (`union`) を基準に、各フレームが `union` の真部分集合しか使っていないかを
    調べ、欠けていた相名を報告する。**提案のみ**: どのフレームも変更しない。

    :param result: 検査対象の逐次精密化結果
    :returns: `PhaseSetCompletionReport`
    """
    union: list[str] = []
    seen: set[str] = set()
    for f in result.frames:
        for name in f.phase_names:
            if name not in seen:
                seen.add(name)
                union.append(name)
    union_t = tuple(union)

    frames_with_missing: list[tuple[int, tuple[str, ...]]] = []
    for f in result.frames:
        present = set(f.phase_names)
        missing = tuple(name for name in union_t if name not in present)
        if missing:
            frames_with_missing.append((f.frame_index, missing))

    is_complete = not frames_with_missing

    if is_complete:
        recommendation = (
            "全フレームが同じ相集合を使用しています。追加の再フィットは不要です。"
        )
    else:
        n_affected = len(frames_with_missing)
        recommendation = (
            f"{n_affected} フレームが相集合 {union_t} の真部分集合でフィットされています。"
            "計量が近い相は互いの強度を吸収し合い、除外相の強度が残存相に肩代わりされても"
            "Rwp は良好なまま変化しないため検出できません (Issue #84 実測: K2Mn[Fe(CN)6] で"
            "Rwp ~8% のまま tetra 分率が非物理的に振動)。該当フレームを union の全相で再フィットし、"
            "分率の変化を比較することを推奨します。"
        )

    return PhaseSetCompletionReport(
        union=union_t,
        frames_with_missing=tuple(frames_with_missing),
        is_complete=is_complete,
        recommendation=recommendation,
    )


def _count_turning_points(values: tuple[float, ...], min_amplitude: float) -> int:
    """振幅フィルタ付き turning point (方向転換) 数を数える (zigzag 方式)。

    **振幅フィルタの規則**: 直近の確定極値から `min_amplitude` 未満しか戻っていない反転は
    ノイズとみなし方向転換にカウントしない。具体的には、現在の進行方向 (上昇/下降) の間は
    その方向での極値 (最大/最小) を追跡し続け、逆方向への戻りが `min_amplitude` 以上になった
    時点で初めて 1 回の turning point として確定し、その戻り値を新しい極値として反対方向の
    追跡を再開する (株価チャートの zigzag インジケータと同じ考え方)。系列全体が
    `min_amplitude` 未満のノイズ帯に留まる間は方向未確定のまま進む。

    単純なドーム型 (単調増加 → 単調減少) は turning point = 1、appear-then-disappear の
    物理的に単純な過程はこれに相当する。振動 (肩代わり) パターンは turning point が
    多くなる。

    :param values: フレーム順の値系列
    :param min_amplitude: 方向転換とみなす最小の戻り幅 (ピーク-トラフ振幅)
    :returns: turning point 数
    """
    n = len(values)
    if n < 3:
        return 0

    direction = 0  # 0=未確定, 1=上昇追跡中, -1=下降追跡中
    extreme = values[0]
    count = 0

    for i in range(1, n):
        v = values[i]
        if direction == 0:
            diff = v - extreme
            if diff >= min_amplitude:
                direction = 1
                extreme = v
            elif -diff >= min_amplitude:
                direction = -1
                extreme = v
            # else: まだノイズ帯 (方向未確定のまま次へ)
        elif direction == 1:
            if v > extreme:
                extreme = v
            elif extreme - v >= min_amplitude:
                count += 1
                direction = -1
                extreme = v
            # else: 振幅未満の戻り (ノイズ) は無視、extreme は保持
        else:  # direction == -1
            if v < extreme:
                extreme = v
            elif v - extreme >= min_amplitude:
                count += 1
                direction = 1
                extreme = v
            # else: 振幅未満の戻り (ノイズ) は無視

    return count


def flag_nonmonotonic_fraction(
    result: SequentialRietveldResult,
    phase_name: str,
    *,
    min_amplitude: float = 0.1,
    max_turning_points: int = 2,
) -> NonMonotonicReport:
    """相分率系列の非単調性 (振動) を検出し、物理的妥当性の確認を第3層へ促す。

    ある相の分率が系列を通じて振動 (増減を繰り返す) するのは、多くの場合「出現して消える」
    という物理的に単純な過程 (単一ドーム = 単調増加 + 単調減少の 2 区間 = turning point 1) から
    外れている。ノイズによる小刻みな増減を `min_amplitude` の振幅フィルタで無視した上で
    turning point 数を数え、`max_turning_points` を超えたら `flagged=True` とする。

    :param result: 検査対象の逐次精密化結果
    :param phase_name: 対象の相名 (存在しないフレームは分率 0.0 として扱う)
    :param min_amplitude: ノイズ抑制用の振幅フィルタ閾値 (ピーク-トラフ振幅)。既定 0.1
    :param max_turning_points: これを超える turning point 数で発火。既定 2
        (単一ドーム = 1 turning point までは正常とみなす)
    :returns: `NonMonotonicReport`
    """
    fractions = tuple(float(f.phase_fractions.get(phase_name, 0.0)) for f in result.frames)

    if len(fractions) < 3:
        return NonMonotonicReport(
            phase_name=phase_name,
            turning_points=0,
            flagged=False,
            fractions=fractions,
            reason="フレーム数が 3 未満のため振動判定を行いません。",
        )

    turning_points = _count_turning_points(fractions, min_amplitude)
    flagged = turning_points > max_turning_points

    if flagged:
        reason = (
            f"turning point 数 {turning_points} が上限 {max_turning_points} を超えました"
            f" (振幅フィルタ {min_amplitude})。計量が近い相が互いの強度を肩代わりしている"
            "非物理的な振動の可能性があります。相集合の完全性 (除外相がないか) と"
            "物理的妥当性を確認してください。"
        )
    else:
        reason = (
            f"turning point 数 {turning_points} は上限 {max_turning_points} 以内です"
            f" (振幅フィルタ {min_amplitude})。"
        )

    return NonMonotonicReport(
        phase_name=phase_name,
        turning_points=turning_points,
        flagged=flagged,
        fractions=fractions,
        reason=reason,
    )
