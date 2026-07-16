"""operando 逐次解析の不連続点検出と近傍 warm-start 修復 (第2層, Issue #81)。

実測 (K₂Mn[Fe(CN)₆], 63 フレーム) で確立: 少数フレームが局所解にトラップされ Rwp/相分率が
不連続に飛ぶ。これらは 2 種に分かれる:

- **局所トラップ**: 良好な近傍フレームからの warm-start で解消できる
  (実測: Rwp 10.8-12.0% → 7.5-8.3%、偽相の相分率も同時に消滅)。
- **モデル欠陥**: warm-start では解消しない (近傍も同じ欠陥を持つため)。モデル再構成が要る
  → **第3層 (`refine_loop` の ModelAction) へエスカレーション**。

**この 2 分類は事前に決め打ちできない (実データで反証済)。** 当初は「連続してフラグが立つ =
系統ブロック = 修復不可」という run-length プロキシを用いたが、実測 63 フレームで**両方向に失敗**した:

- f160,f164,f168,f172 は**連続**だが、外側の良好フレーム f156/f176 から warm-start して
  実際に修復できた (11.9→8.3 / 10.8→8.2 / 12.0→8.2%)。run-length で門前払いしていた。
- f12 は**単独**フラグ (run-length 上は「孤立」) だが、実体は凍結 mono セルのモデル欠陥で、
  近傍も同じ欠陥を共有するため warm-start では直らない。

したがって分類は **経験的 (empirical)** に行う: **フラグが立った全フレームに対し近傍 warm-start を
試し**、改善しなければ「warm-start に機会を与えた上で失敗した」= モデルが誤っている証拠として
エスカレーションする。これは実際の診断手順そのものである。連続長は `classify` で**参考情報**として
報告するのみで、修復の可否を**ゲートしない**。

本モジュールは numpy-only コア。精密化は `runner` (`insitu.engine.Runner` と同シグネチャ:
``(frame, phases, initial_cells) -> AutoRietveldResult``) を注入して駆動し、GSAS には依存しない。
提案≠適用 (Rwp が改善した場合のみ採用) + ledger 追記で非破壊・監査可能性を保つ (P2/NFR-105 準拠)。

信頼性: 🔵 Issue #81 (K₂Mn[Fe(CN)₆] 実データ 63 フレームで検証済; run-length ゲートは反証され撤回)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Sequence

from ..autorietveld.model import AutoRietveldResult, PhaseSpec
from ..store.ledger import Ledger
from ._warmstart import call_runner, seed_fractions
from .engine import Runner
from .model import Cell, FrameRietveldResult, FrameSpec, SequentialRietveldResult


@dataclass(frozen=True)
class Discontinuity:
    """不連続と判定されたフレーム 1 つの記録。

    :param frame_index: 0 始まりのフレーム番号
    :param axis_value: そのフレームの軸値 (温度/時間, None 可)
    :param rwp: そのフレームの Rwp (%)
    :param reasons: 発火した判定基準名の列 ("rwp_abs"/"rwp_local_median"/"fraction_deviation")
    """

    frame_index: int
    axis_value: float | None
    rwp: float
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class FrameRepair:
    """孤立スパイク 1 フレームの修復記録 (採用された場合)。

    :param frame_index: 修復したフレーム番号
    :param rwp_before: 修復前 (元系列) の Rwp
    :param rwp_after: warm-start 再精密化後の Rwp (採用値)
    :param source: warm-start の起点方向 ("L"=左隣/"R"=右隣)
    :param phase_fractions: 修復後の相名→相分率
    """

    frame_index: int
    rwp_before: float
    rwp_after: float
    source: str
    phase_fractions: Mapping[str, float]


@dataclass(frozen=True)
class RepairReport:
    """`repair_isolated` の総合結果 (非破壊: 元の `SequentialRietveldResult` は変更しない)。

    :param repairs: 採用された修復 (Rwp 改善が確認できたもの)
    :param needs_model_revision: **第3層へエスカレーションすべき**フレーム番号 (昇順)。
        内訳は 2 通りで、いずれも「warm-start では直らない = モデルが誤っている」ことの経験的証拠:

        1. 近傍 warm-start を**試したが改善しなかった** (元のまま据え置き) フレーム。
        2. 左右どちらにも良好な近傍が無く**試せなかった**フレーム。

        当初あった `not_improved` は本フィールドと実質同義 (1. がそれ) だったため統合した
        (Issue #81 のレビュー指摘)。個別の試行結果 (試したか/Rwp がどう動いたか) は ledger の
        ``insitu_repair_rejected`` / ``insitu_repair_no_neighbour`` エントリで追える。
    :param systematic_hint: 連続してフラグが立ったフレーム番号の run (長さ >= min_block)。
        **参考情報のみ** — 修復可否をゲートしない (実測 f160-172 は連続だが修復可能だった)。
        人間/エージェントが「同じモデル欠陥がこの区間に広がっているかも」と当たりを付ける材料。
    """

    repairs: tuple[FrameRepair, ...] = ()
    needs_model_revision: tuple[int, ...] = ()
    systematic_hint: tuple[tuple[int, ...], ...] = ()


def _local_median(values: Sequence[float], i: int) -> float | None:
    """values[i] を中心とする幅 3 (境界は 2) の局所中央値。有限値のみで算出、全欠測なら None。"""
    lo = max(0, i - 1)
    hi = min(len(values), i + 2)
    window = sorted(v for v in values[lo:hi] if math.isfinite(v))
    if not window:
        return None
    m = len(window)
    if m % 2 == 1:
        return window[m // 2]
    return 0.5 * (window[m // 2 - 1] + window[m // 2])


def detect_discontinuities(
    result: SequentialRietveldResult,
    *,
    rwp_abs: float | None = None,
    rwp_delta: float = 1.8,
    frac_delta: float = 0.15,
) -> tuple[Discontinuity, ...]:
    """系列から不連続フレームを検出する (Rwp 絶対/局所中央値超過・相分率の両隣補間乖離)。

    判定基準 (いずれか 1 つでも該当すればそのフレームを検出、複数該当は reasons に列挙):

    - ``rwp_abs`` 指定時: ``rwp > rwp_abs``
    - ``rwp > local_median(3) + rwp_delta`` (局所中央値は当該フレーム含む幅3、境界は幅2)
    - いずれかの相分率が両隣 2 フレームの平均から ``frac_delta`` 超乖離 (先頭/末尾フレームは
      両隣が揃わないため本基準は適用しない — Rwp 系の基準のみ)

    :param result: 検査対象の逐次精密化結果
    :param rwp_abs: Rwp 絶対閾値 (None なら無効)
    :param rwp_delta: 局所中央値からの許容超過幅 (%ポイント)
    :param frac_delta: 相分率の両隣補間からの許容乖離
    :returns: フレーム順の `Discontinuity` タプル
    """
    frames = result.frames
    n = len(frames)
    rwps = [f.rwp for f in frames]
    out: list[Discontinuity] = []
    for i, f in enumerate(frames):
        reasons: list[str] = []
        if rwp_abs is not None and (not math.isfinite(f.rwp) or f.rwp > rwp_abs):
            reasons.append("rwp_abs")

        med = _local_median(rwps, i)
        if med is not None and (not math.isfinite(f.rwp) or f.rwp > med + rwp_delta):
            reasons.append("rwp_local_median")

        if 0 < i < n - 1:
            left, right = frames[i - 1], frames[i + 1]
            names = set(f.phase_fractions) | set(left.phase_fractions) | set(right.phase_fractions)
            for name in sorted(names):
                cur = float(f.phase_fractions.get(name, 0.0))
                lf = float(left.phase_fractions.get(name, 0.0))
                rf = float(right.phase_fractions.get(name, 0.0))
                neighbour_mean = 0.5 * (lf + rf)
                if abs(cur - neighbour_mean) > frac_delta:
                    reasons.append("fraction_deviation")
                    break

        if reasons:
            out.append(
                Discontinuity(
                    frame_index=i, axis_value=f.axis_value, rwp=f.rwp, reasons=tuple(reasons)
                )
            )
    return tuple(out)


def classify(
    discontinuities: tuple[Discontinuity, ...],
    n_frames: int,
    *,
    min_block: int = 2,
) -> tuple[tuple[Discontinuity, ...], tuple[tuple[Discontinuity, ...], ...]]:
    """検出済み不連続点を連続長で区分する — **参考情報 (weak hint) 専用のヘルパ**。

    フレーム番号が連続して `min_block` 個以上並ぶ run を切り出して返す。「同じモデル欠陥が区間に
    広がっているかも」という当たりを付ける材料にはなるが、**修復可否の判定に使ってはならない**。

    **⚠ run-length は修復可能性のプロキシとして反証済 (Issue #81, 実測 63 フレーム)。両方向に外れる**:

    - **連続 ≠ 修復不可**: f160,f164,f168,f172 は連続してフラグが立ったが、run の外側の良好フレーム
      f156/f176 から warm-start して実際に修復できた (Rwp 11.9→8.3 / 10.8→8.2 / 12.0→8.2%)。
      run-length でゲートすると、これらを門前払いしてしまう。
    - **単独 ≠ 修復可能**: f12 は単独フラグ (run-length 上は「孤立」) だが、実体は凍結 mono セルの
      モデル欠陥で近傍も同じ欠陥を共有するため warm-start では直らない。

    よって真の分類は `repair_isolated` が**経験的に** (実際に warm-start を試して改善するか) 行う。

    :param discontinuities: `detect_discontinuities` の出力
    :param n_frames: 系列全体のフレーム数 (フレーム番号の範囲チェック用に保持; 現状の区分ロジック
        自体は連続性のみで完結するため未使用だが、将来の境界拡張のためシグネチャに残す)
    :param min_block: run とみなす最小連続長
    :returns: (単発の `Discontinuity` タプル, 連続 run 毎の `Discontinuity` タプルの列)。
        あくまで連続長による区分であり、修復可能性の判定ではない
    """
    del n_frames  # 現状は連続性のみで判定 (将来の境界拡張用に受け取るのみ)
    by_index = {d.frame_index: d for d in discontinuities}
    indices = sorted(by_index)

    isolated: list[Discontinuity] = []
    blocks: list[tuple[Discontinuity, ...]] = []
    run: list[int] = []

    def _flush() -> None:
        if not run:
            return
        if len(run) >= min_block:
            blocks.append(tuple(by_index[j] for j in run))
        else:
            isolated.extend(by_index[j] for j in run)

    for idx in indices:
        if run and idx == run[-1] + 1:
            run.append(idx)
        else:
            _flush()
            run = [idx]
    _flush()

    return tuple(isolated), tuple(blocks)


def _nearest_good(
    frame_results: Sequence[FrameRietveldResult], i: int, step: int, flagged: set[int]
) -> FrameRietveldResult | None:
    """i から step 方向 (+1/-1) へ辿り、フラグなし・精密化成功の最初のフレームを返す。"""
    j = i + step
    while 0 <= j < len(frame_results):
        fr = frame_results[j]
        if j not in flagged and not fr.refine_failed:
            return fr
        j += step
    return None


def repair_isolated(
    frames: Sequence[FrameSpec],
    result: SequentialRietveldResult,
    phases: Sequence[PhaseSpec],
    runner: Runner,
    discontinuities: tuple[Discontinuity, ...],
    *,
    rwp_tol: float = 0.1,
    min_block: int = 2,
    ledger: Ledger | None = None,
) -> RepairReport:
    """不連続フレームを近傍 warm-start で修復する (非破壊・Rwp 改善時のみ採用・経験的分類)。

    **フラグが立った全フレームに対し、連続長に関わらず修復を試みる**。左右それぞれ外向きに歩いて
    最近傍の良好フレーム (フラグなし ∧ 精密化成功) を探し、その `refined_cells` を `initial_cells`
    として warm-start 再精密化し (`phases` からその近傍フレームの `phase_names` に対応する相集合を
    引いて使う)、左右両方を試して Rwp が最良の側を採る。元の Rwp より `rwp_tol` 超改善した場合のみ
    採用する (提案≠適用)。

    **連続してフラグが立った区間も必ず試す**: 外向きの歩行が run の外側の良好フレームを見つけるため
    (実測 f160-172 は連続だが f156/f176 から修復できた)。run-length で門前払いしない (Issue #81)。

    エスカレーション (`needs_model_revision`) は**経験的**に決まる: 「warm-start に機会を与えた上で
    改善しなかった」or「良好な近傍が左右どちらにも無く試せなかった」フレーム。前者は近傍が同じ欠陥を
    共有している (= モデルが誤っている) ことの直接証拠であり、第3層 (`refine_loop` の ModelAction) が
    扱うべき対象になる。

    :param frames: フレーム列 (`result.frames` と同順・同数)
    :param result: 検査対象の逐次精密化結果 (変更しない)
    :param phases: 系列で使われている全相の `PhaseSpec` (相名で引く辞書のソース)。`initial_phases`
        と、系列途中で採用された `PhaseAppearance` に対応する相を合わせたもの
    :param runner: `(frame, phases, initial_cells) -> AutoRietveldResult` (`insitu.engine.Runner` 同型)
    :param discontinuities: `detect_discontinuities` の出力
    :param rwp_tol: 採用に要する最小 Rwp 改善幅 (%ポイント)
    :param min_block: `systematic_hint` (参考情報) の run 判定の最小連続長。**修復可否には影響しない**
    :param ledger: 追記台帳 (None なら記録しない)
    :returns: `RepairReport` (元の `result`/`frames` は変更しない)
    """
    frame_results = result.frames
    n = len(frame_results)
    _, blocks = classify(discontinuities, n, min_block=min_block)
    flagged = {d.frame_index for d in discontinuities}
    name_to_spec = {p.phase_name: p for p in phases}

    repairs: list[FrameRepair] = []
    needs_model_revision: list[int] = []

    # 【全フラグフレームを試す】: 連続長でゲートしない (run-length プロキシは実データで反証済)。
    #   外向きの歩行が run の外側の良好フレームを見つけるため、連続ブロックも修復機会を得る。
    for disc in sorted(discontinuities, key=lambda d: d.frame_index):
        i = disc.frame_index
        base = frame_results[i]
        rwp_before = base.rwp

        best: tuple[str, AutoRietveldResult] | None = None
        for source, step in (("L", -1), ("R", 1)):
            neighbour = _nearest_good(frame_results, i, step, flagged)
            if neighbour is None:
                continue
            neighbour_phases = tuple(
                name_to_spec[nm] for nm in neighbour.phase_names if nm in name_to_spec
            )
            if not neighbour_phases:
                continue
            initial_cells: dict[str, Cell] = dict(neighbour.refined_cells)
            # 【分率も warm-start する (Issue #96)】: セルだけを引き継ぐと相分率は GSAS の等分 seed
            #   (2 相なら 0.50/0.50) から再出発し、修復試行そのものが seed に張り付いて Rwp が改善
            #   しない → 採用されない。近傍の分率を種にすると実測で修復採用が 0/14 → 8/14 になった。
            #   渡す分率は**実際に渡す相集合の分だけ** (name_to_spec で引けなかった相は除かれる)。
            initial_fractions = seed_fractions(
                neighbour.phase_fractions, [p.phase_name for p in neighbour_phases]
            )
            trial = call_runner(
                runner, frames[i], neighbour_phases, initial_cells, initial_fractions
            )
            if math.isfinite(float(trial.final_rwp)) and (
                best is None or float(trial.final_rwp) < float(best[1].final_rwp)
            ):
                best = (source, trial)

        if best is None:
            # 良好な近傍が左右どちらにも無い → 試せない。これも第3層送り (経験的に修復不能)。
            needs_model_revision.append(i)
            if ledger is not None:
                ledger.append(
                    "insitu_repair_no_neighbour",
                    {"frame": i, "rwp": rwp_before, "reasons": list(disc.reasons)},
                )
            continue

        source, trial = best
        rwp_after = float(trial.final_rwp)
        if rwp_after < rwp_before - rwp_tol:
            repairs.append(
                FrameRepair(
                    frame_index=i,
                    rwp_before=rwp_before,
                    rwp_after=rwp_after,
                    source=source,
                    phase_fractions=dict(trial.phase_fractions),
                )
            )
            if ledger is not None:
                ledger.append(
                    "insitu_repair_adopted",
                    {
                        "frame": i,
                        "rwp_before": rwp_before,
                        "rwp_after": rwp_after,
                        "source": source,
                    },
                )
        else:
            # warm-start に機会を与えたが改善せず → 近傍が同じ欠陥を共有している経験的証拠。
            needs_model_revision.append(i)
            if ledger is not None:
                ledger.append(
                    "insitu_repair_rejected",
                    {
                        "frame": i,
                        "rwp_before": rwp_before,
                        "rwp_after": rwp_after,
                        "source": source,
                    },
                )

    return RepairReport(
        repairs=tuple(repairs),
        needs_model_revision=tuple(sorted(needs_model_revision)),
        systematic_hint=tuple(tuple(d.frame_index for d in block) for block in blocks),
    )
