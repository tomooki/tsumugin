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
from dataclasses import dataclass, field
from typing import Mapping, Sequence

from ..autorietveld.model import AutoRietveldResult, CellEsd, PhaseSpec
from ..store.ledger import Ledger
from ._warmstart import call_runner, seed_fractions
from ..gpxstore import gpx_context, group_context
from .engine import Runner, _publication_of
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
    :param phase_fractions: 修復後の相名→相分率 (**Scale**)。相対比較専用 — 出版値ではない
    :param phase_weight_fractions: 相名→**重量 (質量) 分率** (`AutoRietveldResult.phase_weight_fractions`
        由来, GSAS-II `calcMassFracs`)。**修復後の定量相分析の出版値はこちら**。

        **修復フレームでこそ要る** (Issue #96 レビュー 第2巡): ③ は `check_phase_set` が名指しした
        フレーム (張り付き/凍結) を `target_frames` で修復する。**張り付きは相転移の途中で起きやすく**
        (分率が動く区間ほど前フレームの seed から遠い)、そこは定量相分析の要求が最も高い区間でもある。
        Scale しか持ち帰らなければ、③ は「wt% として誤って報告する」か「直したばかりのフレームの
        出版値が無い」の二択になる (`skills/operando-diagnose` 禁止事項は前者を禁じている)。
        Scale と重量分率の差は相の単位胞質量比と各フレームの分率で決まり、**フレーム毎に異なる**
        (実測 K₂Mn[Fe(CN)₆]: 1.39-1.62 倍。**単一の換算係数は存在しない**ので Scale に係数を掛けて
        wt% にはできない。`AutoRietveldResult.phase_weight_fractions` の docstring 参照)。
        既定空 dict で後方互換 (重量分率を持たない runner/スタブ・共分散なしの精密化は空)。
    :param phase_weight_fraction_esd: 相名→重量分率の esd。出版には esd 必須。要素 ``None`` = 多相なのに
        この精密化から決まっていない (レビュー第6巡)・単相は ``0.0`` (自明)。既定空 dict
    :param cell_esd: 相名→格子 esd (a,b,c,α,β,γ)。要素 ``None`` = 格子を解放していない
        (凍結セル/未精密化) ので値が決まっていない。``0.0`` は対称拘束で厳密に固定。既定空 dict
    :param gpx_path: 採用した修復 fit の成果物パス ("" = 未保存)。修復は**元の系列結果を
        置き換える**ので、③ が修復後のフレームを MEM/再プロットに掛けるにはこちらを見る
        (2026-08-20 規定「全解析で保存する」)
    """

    frame_index: int
    rwp_before: float
    rwp_after: float
    source: str
    phase_fractions: Mapping[str, float]
    phase_weight_fractions: Mapping[str, float] = field(default_factory=dict)
    phase_weight_fraction_esd: Mapping[str, float | None] = field(default_factory=dict)
    cell_esd: Mapping[str, CellEsd] = field(default_factory=dict)
    gpx_path: str = ""


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

    **⚠ 3 つ目の基準は `phase_fractions` (Scale) から発火する — 格子を見る基準は無い**
    (Issue #96 レビュー第4巡 HIGH: 「不連続の検出は Rwp/格子で行う」という記述は**偽**だった)。
    `frac_delta` は **Scale 単位の絶対閾値**であり、Scale→wt% は相ごとの単位胞質量で伸縮する
    非線形写像なので、**同じ系列でも basis を替えると選ばれるフレーム集合が変わる**
    (実測: Scale `[0.10, 0.12, 0.45, 0.16, 0.18]` は 3 フレーム、同じ系列の wt% は 1 フレーム)。

    **Scale を基準にするのは意図的**: (a) 検出したいのは「そのフレームの**精密化**が近傍と
    食い違う」ことで、Scale は GSAS が実際に動かすパラメータそのものである。(b) `repair_isolated`
    は近傍の **Scale** を warm-start の種として GSAS へ戻す (`_warmstart.seed_fractions`) ため、
    検出器と作動器は同じ座標で喋る必要がある。(c) 重量分率は共分散の無い精密化では空であり、
    wt% 基準の検出器は定義できない系列が多い。

    :param result: 検査対象の逐次精密化結果
    :param rwp_abs: Rwp 絶対閾値 (None なら無効)
    :param rwp_delta: 局所中央値からの許容超過幅 (%ポイント)
    :param frac_delta: 相分率 (**Scale**) の両隣補間からの許容乖離。**絶対値であり basis 依存**
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


def discontinuities_from_frames(
    result: SequentialRietveldResult,
    frame_indices: Sequence[int],
    *,
    reason: str = "targeted",
) -> tuple[Discontinuity, ...]:
    """フレーム番号を明示して `Discontinuity` を組む (**検出統計に映らない欠陥**の修復経路)。

    `detect_discontinuities` は Rwp/相分率の**ジャンプ**でしか発火しない。しかし修復を要する
    欠陥がすべてジャンプとして現れるとは限らない — **seed 張り付き (`phaseset.is_seed_pinned`) と
    分率凍結 (`phaseset.flag_frozen_fraction_frames`) は定義上「平坦」**であり、

    - Rwp は平凡なまま (実測 8.4-8.5%) なので ``rwp_abs`` では拾えない、
    - 張り付き区間内では局所中央値が当該フレームの Rwp そのものになるため ``rwp_delta`` を
      どれだけ下げても内側に到達できない、
    - 分率も平坦なので ``frac_delta`` は逆に**健全な**近傍フレームの方を拾ってしまう

    という三重の理由で、**どの閾値を選んでも検出できない**。よって「何を直すか」を呼び出し側
    (③ が `check_phase_set` の `seed_pinned_frames[].frame` / `frozen_fraction_frames[].frame`
    から組む) が指定する経路が要る。

    **`flagged` 集合としての役割**: 返した `Discontinuity` のフレーム番号は `repair_isolated` で
    warm-start 元から除外される (`_nearest_good`)。**疑わしいフレームは 1 回の呼び出しで全て渡すこと** —
    1 フレームずつ呼ぶと、両隣も同じ欠陥を持つ場合 (実測 125-130 の 6 連続) に**欠陥を持つ隣から
    warm-start して欠陥を引き継ぐ**。

    :param result: 対象の逐次精密化結果 (変更しない)
    :param frame_indices: 修復対象のフレーム番号 (重複・順不同可; 昇順に正規化する)
    :param reason: 記録する判定理由名 (既定 "targeted"; 例 "seed_pinned")
    :returns: フレーム番号昇順の `Discontinuity` タプル
    :raises ValueError: `frame_indices` が空・整数でない・範囲外のとき (② は error dict へ縮退する)
    """
    n = len(result.frames)
    if not frame_indices:
        raise ValueError(
            "frame_indices が空です。修復対象が無い呼び出しは「不連続なし」と区別できないため"
            "打ち切ります (自動検出に任せるなら target_frames を渡さないでください)。"
        )
    indices: set[int] = set()
    for raw in frame_indices:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError(
                f"frame_indices の要素は整数のフレーム番号です: {raw!r} ({type(raw).__name__})"
            )
        if not (0 <= raw < n):
            raise ValueError(
                f"frame_indices のフレーム番号が範囲外です: {raw} (系列は 0..{n - 1} の {n} フレーム)"
            )
        indices.add(raw)

    return tuple(
        Discontinuity(
            frame_index=i,
            axis_value=result.frames[i].axis_value,
            rwp=result.frames[i].rwp,
            reasons=(reason,),
        )
        for i in sorted(indices)
    )


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
    # 【修復 1 実行 = run ディレクトリ 1 つ】: 試行ごとに ambient が無いと `child_context` が
    #   None を返し、各試行が別々の run ディレクトリを作って散らばる (設計 §3 の
    #   「1 実行 = 1 run ディレクトリ」に反し、索引も 1 行ずつに割れる)。系列の内側から
    #   呼ばれたときは既存 ambient をそのまま使う (`group_context` の契約)。
    group, _gpx_reason = group_context(frames[0].data_path if frames else "")

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
            # 【修復試行も残す (規定 2026-08-20)】: 採用は「Rwp が改善したときのみ」なので、
            #   棄却された修復の fit は ledger の数字にしか残らない — 開けないと原因を見られない。
            with gpx_context(group.child(role="repair", index=i, label=str(source))):
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
                    # 【出版値も持ち帰る (Issue #96 レビュー 第2巡)】: 試行結果は重量分率 ± esd と
                    #   格子 esd を持っているのに、ここで Scale だけ写して捨てていた。修復対象は
                    #   ③ が `check_phase_set` で名指ししたフレーム = 定量相分析の要求が最も高い
                    #   転移域であり、Scale だけでは相の単位胞質量比の分だけ誤る。抽出は
                    #   `engine._publication_of` に一元化する (M9 逐次 / 修復の 2 経路で同一の規律 —
                    #   相名フィルタも 0.0 埋めもしない: 部分集合の重量分率は和=1 にならず、0.0 埋めは
                    #   「その相は 0 wt%」という測定していない主張になる)。
                    **_publication_of(trial),  # type: ignore[arg-type]
                    gpx_path=str(getattr(trial, "gpx_path", "") or ""),
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
