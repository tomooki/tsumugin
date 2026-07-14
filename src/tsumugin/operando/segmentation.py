"""operando/segmentation — IC 区間自動分割 (FR-316 / 設計 D5/D6)。

operando (充放電/高温 in-situ) の粉末回折フレーム列 (``FrameSeries``) を、IC (情報量規準 = bic)
ペナルティ付きで区間自動分割するオーケストレーション純関数 ``segment_series`` を提供する。

- **区間コスト** = 区間内の**軽量 warm-start 逐次 direct refine (格子 scale/a/b/c 解放) の Σbic**
  (changepoint・木探索なし)。``(start, end)`` をキーに**メモ化**し、貪欲挿入・細密スキャンでの
  再評価を回避する (設計 D-Q5)。
- **探索順序 (貪欲挿入)** (設計 D5 / §15-1): k=1 (境界なし) を基準に、既存分割へ境界 1 本を追加する
  粗グリッド (``coarse_step``) の全候補を評価し、**合計コスト = Σ(区間 bic) + β·(境界数)·ln(n_frames)**
  最小の挿入を採用。直前 k からの改善が ``improvement_threshold`` 未満で打ち切り
  (``max_segments`` まで走らない)。採用境界を ±``coarse_step`` の細密スキャンで再配置 (粗→細 2 段)。
- **分割仮説の保存** (設計 D6 / REQ-014): 各 k の分割を 1 個の ``Hypothesis``
  (id=``"seg-k{K}-..."``, ``frame_range``=全区間) として ``partitions`` に保存し代替閲覧可。
  境界・evidence は ledger payload と ``SegmentationResult.evidence_by_k`` (k -> 合計コスト) に保持。
- **固定相 (``FixedPhaseSpec``)**: 区間逐次 refine に常駐・構造固定・scale のみ解放 (FR-312 連携)。
- **全操作 ledger 記録** (追記専用・kind は ``"segmentation."`` 前置・``verify()`` 常に True)。

決定論 (NFR-102): 乱数・時刻・集合反復順に依存しない。同一入力の 2 回実行で ``SegmentationResult`` の
(ledger インスタンス以外の) 全フィールドがビット同一になる。バックエンド失敗は例外化せず chi2=inf の
結果として縮退処理し、非有限を Σbic・合計コストへ混ぜない (M1 教訓)。

🔵 信頼性レベル: 契約は ``docs/design/m3-operando/interfaces.py`` L287-321、設計 D5/D6
  (``architecture.md`` L78-86)、``design-interview.md`` D-Q5/D-Q6、REQ-013/014・EDGE-004・NFR-102 に依拠。
  🟡 ``coarse_step``/``max_segments``/``seq_max_cycles``/β の較正値と縮退派生 (n<2 / 全滅) は設計裁量。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

import numpy as np

from ..backends.base import RefinementBackend, RefinementModel, RefinementResult, param_name
from ..evidence.ic import BICBackend
from ..model import Hypothesis, PhaseInstance, RefinementMetrics
from ..sequential.series import FrameSeries
from ..store.ledger import Ledger
from .cell_phases import FixedPhaseSpec, fixed_free_suffixes

__all__ = ["SegmentationConfig", "SegmentationResult", "segment_series"]

# 【区間コストの解放 suffix】: 単相 warm-start 逐次 direct refine は scale + 格子 a/b/c を解放する
#   (固溶体の連続格子変化を追従する探索モード相当 / 設計 D5・discrimination._SINGLE_FREE_SUFFIXES と同一)。🔵
_ACTIVE_SUFFIXES = ("scale", "lattice.a", "lattice.b", "lattice.c")

# 【bic 算出源】: 区間 Σbic は各フレーム RefinementResult を RefinementMetrics 化して同一 BICBackend で
#   スコアリングする (バックエンド間で bic セマンティクス統一 / evidence/ic.py と単一算法)。🔵
_BIC = BICBackend()


@dataclass(frozen=True)
class SegmentationConfig:
    """区間自動分割の設定 (frozen)。既定は interfaces.py L292-298 の契約に一致する。

    【機能概要】: 合計コストの境界数ペナルティ係数・改善打ち切り閾値・粗グリッド刻み・セグメント数の
      安全上限・区間 direct refine のサイクル上限を束ねる不変設定。
    【テスト対応】: test_config_and_result_are_frozen (既定 5.0/10.0/5/6/10 と frozen 不変性)。
    🔵 信頼性レベル: interfaces.py L292-298 に直接依拠 (β 較正・G/上限/サイクルの値は 🟡)。
    """

    penalty_beta: float = 5.0  # 【ペナルティ β】: 合計コストの β·(境界数)·ln(n_frames) 係数 🔵 (β は 🟡 較正)
    improvement_threshold: float = 10.0  # 【打ち切り閾値】: k 増加の改善がこれ未満で貪欲挿入を停止 🔵 §15-1
    coarse_step: int = 5  # 【粗グリッド G】: 境界候補のフレーム刻み (細密は ±G) 🟡
    max_segments: int = 6  # 【安全上限】: セグメント数 k の上限 (到達前に閾値で止まるのが正常) 🟡
    seq_max_cycles: int = 10  # 【逐次サイクル上限】: 区間 direct refine の max_cycles 🟡


@dataclass(frozen=True)
class SegmentationResult:
    """FR-316 分割結果 (frozen・非破壊)。契約は interfaces.py L301-310。

    【機能概要】: 採択境界・セグメント数・k 別合計コスト (代替閲覧)・各 k の分割仮説・記録済み ledger・
      縮退/打ち切り警告を保持する不変の結果契約。
    【テスト対応】: 正常系 9 / 異常系 2 / 境界値 6 の全 17 件。
    🔵 信頼性レベル: interfaces.py L301-310 に直接依拠。
    """

    boundaries: tuple[int, ...]  # 【採択境界】: セグメント境界フレーム index (昇順・端 0/n は含めない) 🔵
    n_segments: int  # 【セグメント数】: k = len(boundaries) + 1 🔵
    evidence_by_k: Mapping[int, float]  # 【k 別合計コスト】: k -> その k の最良合計コスト (代替閲覧用) 🔵
    partitions: tuple[Hypothesis, ...]  # 【分割仮説】: 各 k の分割を 1 個の Hypothesis 化 (D6) 🔵 REQ-014
    ledger: Ledger  # 【台帳】: 記録済み ledger (入力 or 内部新規生成) 🔵
    warnings: tuple[str, ...] = ()  # 【警告】: 縮退 (n<2/全滅) ・非有限フレーム除外の理由 🔵


def segment_series(
    backend: RefinementBackend,
    series: FrameSeries,
    initial_phases: tuple[PhaseInstance, ...],
    *,
    config: SegmentationConfig = SegmentationConfig(),
    fixed_phases: tuple[FixedPhaseSpec, ...] = (),
    ledger: Ledger | None = None,
) -> SegmentationResult:
    """operando フレーム列を IC ペナルティ付きで区間自動分割し ``SegmentationResult`` を返す (FR-316)。

    【機能概要】: k=1 (境界なし) を基準に、粗グリッドの境界候補を貪欲挿入して合計コスト
      (Σ区間 bic + β·境界数·ln n) を最小化し、改善が閾値未満になった k で打ち切る。採択境界は
      ±coarse_step で細密再配置する (粗→細 2 段)。各 k の分割を Hypothesis 化し、境界/evidence を
      ledger と evidence_by_k に記録する。
    【実装方針】: 区間コスト = 区間内 warm-start 逐次 direct refine の Σbic を ``(start, end)`` キーで
      メモ化し、貪欲挿入・細密スキャンでの再評価を回避する (discrimination._refine_interval と同型)。
      乱数・時刻・集合反復順に依存せず 2 回実行でビット同一 (NFR-102)。バックエンド失敗は例外化せず
      chi2=inf の結果として縮退し、非有限を Σbic へ混ぜない (M1 教訓)。
    【テスト対応】: tests/test_segmentation.py の 17 件すべて。
    🔵 信頼性レベル: 設計 D5/D6 / design-interview.md D-Q5/D-Q6 / interfaces.py L313-321 に直接依拠。

    @param backend: 精密化バックエンド (RefinementBackend Protocol: name + refine)。
    @param series: 共通 2θ グリッド + (n_frames, n_points) 強度行列を持つ FrameSeries。
    @param initial_phases: 区間逐次 refine の初期相 (活物質)。空不可 (相なしは分割対象外)。
    @param config: 分割設定 (ペナルティ β・打ち切り閾値・粗グリッド・安全上限・サイクル)。
    @param fixed_phases: セル固定相 (区間 refine に常駐・構造固定・scale のみ解放)。
    @param ledger: 追記専用台帳 (None なら内部で新規生成し記録・数値結果は不変)。
    @returns: 採択境界・k・evidence_by_k・分割仮説・ledger・警告を含む SegmentationResult。
    """
    n = int(series.n_frames)
    # 【依存注入の省略安全性】: None なら内部で新規 Ledger を生成する (結果は ledger 有無で不変 / TC-BV05)。🔵
    active_ledger = ledger if ledger is not None else Ledger()
    two_theta = np.asarray(series.two_theta, dtype=float)
    fixed_instances = tuple(spec.phase for spec in fixed_phases)
    active_count = len(initial_phases)
    # 【逐次源の初期構成】: 活物質 + 固定相を連結 (固定相は末尾・構造固定・scale のみ解放)。🔵
    init_phases = tuple(initial_phases) + fixed_instances
    ln_n = math.log(n) if n > 0 else 0.0

    # 【区間コストのメモ】: (start, end) -> (Σbic, n_finite)。warm-start 逐次は区間先頭から一意に定まるため
    #   同一 (start, end) は同一 Σbic となり、貪欲挿入・±G 細密スキャンでの再評価を安全に回避できる。🔵
    memo: dict[tuple[int, int], tuple[float, int]] = {}
    # 【警告の決定論的集約】: 非有限フレーム除外の警告を first-seen 順で重複排除する (集合反復順非依存)。🔵
    seen_warnings: set[str] = set()
    warnings_list: list[str] = []

    def _remember(messages: list[str]) -> None:
        # 【重複排除】: 同一フレーム除外が複数区間で再出するため first-seen 順で 1 度だけ残す 🔵
        for message in messages:
            if message not in seen_warnings:
                seen_warnings.add(message)
                warnings_list.append(message)

    def interval_cost(start: int, end: int) -> tuple[float, int]:
        # 【メモ化】: 同一区間の再評価はキャッシュヒットで backend.refine を呼ばない (NFR-002 / TC-206-05) 🔵
        cached = memo.get((start, end))
        if cached is not None:
            return cached
        # 【warm-start 逐次 direct refine】: 区間先頭は init_phases から、以降は直近成功フレームの確定相を継承 🔵
        warm = init_phases
        sum_bic = 0.0
        n_finite = 0
        local_warnings: list[str] = []
        for i in range(start, end + 1):
            intensity = np.asarray(series.intensities[i], dtype=float)
            free = _interval_free_params(warm, active_count, fixed_phases)
            model = RefinementModel(
                phases=warm, free_params=free, two_theta=two_theta, intensity=intensity
            )
            # 【direct refine】: staged 解放ループなし、seq_max_cycles で 1 回だけ精密化する 🔵
            result = backend.refine(model, max_cycles=config.seq_max_cycles)
            chi2 = float(result.chi2)
            if math.isfinite(chi2):
                # 【有限フレーム】: bic を加算し、成功相のみ次フレームへ warm 継承する 🔵
                sum_bic += _frame_bic(result)
                warm = result.phases
                n_finite += 1
            else:
                # 【非有限縮退】: Σbic に inf を混ぜず警告する (非有限を漏らさない / M1 教訓) 🔵
                local_warnings.append(
                    f"segmentation: frame {i} の精密化が非有限 chi2 のため Σbic から除外しました。"
                )
        _remember(local_warnings)
        value = (sum_bic, n_finite)
        memo[(start, end)] = value
        return value

    def total_cost(boundaries: tuple[int, ...]) -> float:
        # 【合計コスト】: Σ(区間 bic) + β·(境界数)·ln(n_frames)。ペナルティは境界数 (= k-1) に比例 🔵 D5
        total = 0.0
        for seg_start, seg_end in _segments(boundaries, n):
            seg_bic, seg_finite = interval_cost(seg_start, seg_end)
            if seg_finite == 0:
                # 【全滅区間の無効化】: 有限フレーム皆無の区間を安く見せない (Σbic=0 の詐称を防ぐ) 🔵
                return float("inf")
            total += seg_bic
        return total + config.penalty_beta * len(boundaries) * ln_n

    evidence_by_k: dict[int, float] = {}
    partitions: list[Hypothesis] = []
    representative = tuple(initial_phases)  # 【区間代表相】: 分割仮説 phases は代表相で足りる (D6) 🔵

    # ---- k=1 (境界なし) 基準の評価と記録 -------------------------------------------------
    _base_bic, base_finite = interval_cost(0, n - 1)
    cost_k1 = total_cost(())
    evidence_by_k[1] = cost_k1
    partitions.append(_make_partition(1, (), representative, n))
    _record(active_ledger, "segmentation.baseline", {"k": 1, "total_cost": _num(cost_k1)})

    # ---- 縮退判定 (n<2 / 全フレーム非有限) → k=1 のみで確定 --------------------------------
    degrade_message = None
    if n < 2:
        degrade_message = f"n_frames={n} (<2) のため分割不能。k=1 のみ返します。"
    elif base_finite == 0:
        degrade_message = "全フレームの精密化が非有限のため分割できません。k=1 へ縮退します。"
    if degrade_message is not None:
        warnings_list.append(degrade_message)
        # 【縮退確定】: 境界なし (k=1) で最終化する (貪欲挿入経路と同一の finalize を共用) 🔵
        return _finalize_result(active_ledger, (), evidence_by_k, partitions, warnings_list)

    # ---- 貪欲挿入 (粗グリッド → ±G 細密スキャン)・改善閾値打ち切り ---------------------------
    current_boundaries: tuple[int, ...] = ()
    current_cost = cost_k1
    current_k = 1
    # 【粗グリッド候補】: coarse_step 刻みの内部境界 index。coarse_step>=n_frames なら空 (候補ゼロ) 🟡
    coarse_candidates = tuple(range(config.coarse_step, n, config.coarse_step))

    while current_k < config.max_segments:
        next_k = current_k + 1
        # 【粗→細 2 段挿入】: 粗グリッドで境界 1 本を選び、採択境界の周囲 ±coarse_step を細密再配置する 🔵
        insertion = _best_insertion(
            current_boundaries, coarse_candidates, n, config.coarse_step, total_cost
        )
        if insertion is None:
            # 【候補ゼロ】: 挿入できる粗候補が無い (coarse_step>=n_frames 等) → 現 k で確定 🟡
            break
        best_cost, best_boundaries = insertion

        # 【各 k の記録】: 採否によらず評価した k の合計コスト・分割仮説を残す (代替閲覧 / 打ち切り可視化) 🔵
        evidence_by_k[next_k] = best_cost
        partitions.append(_make_partition(next_k, best_boundaries, representative, n))
        _record(
            active_ledger,
            "segmentation.candidate",
            {"k": next_k, "boundaries": list(best_boundaries), "total_cost": _num(best_cost)},
        )

        # 【打ち切り判定】: 改善量 == 閾値は採択、改善量 < 閾値は直前 k で打ち切り (厳密 < で打ち切り) 🔵
        improvement = current_cost - best_cost
        if math.isfinite(best_cost) and improvement >= config.improvement_threshold:
            current_boundaries, current_cost, current_k = best_boundaries, best_cost, next_k
            _record(
                active_ledger,
                "segmentation.adopt",
                {"k": next_k, "boundaries": list(best_boundaries), "improvement": _num(improvement)},
            )
        else:
            break

    # 【採択確定】: 貪欲挿入で確定した境界で最終化する (縮退経路と同一の finalize を共用) 🔵
    return _finalize_result(
        active_ledger, current_boundaries, evidence_by_k, partitions, warnings_list
    )


# ===========================================================================
# 内部ヘルパ (純関数的・決定論)
# ===========================================================================


def _scan_insertions(
    current_boundaries: tuple[int, ...],
    candidates: tuple[int, ...],
    total_cost,
) -> tuple[float, tuple[int, ...], int] | None:
    """境界候補を昇順に走査し、既存分割へ 1 本追加した最小合計コストの (コスト, 境界集合, 新境界) を返す。

    【機能概要】: 各候補 ``b`` を ``current_boundaries`` に加えた分割の合計コストを評価し、最小を選ぶ。
      既存境界と重複する候補や無効候補は除外する。有効候補が無ければ ``None`` を返す。
    【実装方針】: 候補を昇順に走査し**厳密 <** でのみ更新するため、同コストの tie-break は
      小さい index が優先される (決定論 / TC-206-07 ビット同一の要)。
    🔵 信頼性レベル: 設計 D5 (貪欲挿入) / NFR-102 (安定 tie-break) に依拠。

    @param current_boundaries: 現在採択済みの境界集合 (昇順)。
    @param candidates: 追加を試す境界 index の候補列 (昇順前提)。
    @param total_cost: 境界集合 -> 合計コストを返す評価関数 (メモ化済み)。
    @returns: (最小合計コスト, その境界集合, 追加した新境界) / 有効候補が無ければ None。
    """
    best: tuple[float, tuple[int, ...], int] | None = None
    for boundary in candidates:
        if boundary in current_boundaries:
            continue
        candidate = tuple(sorted(current_boundaries + (boundary,)))
        cost = total_cost(candidate)
        # 【厳密 < 更新】: 昇順走査 + 厳密 < で同コスト時は小さい index を保持する (決定論) 🔵
        if best is None or cost < best[0]:
            best = (cost, candidate, boundary)
    return best


def _best_insertion(
    current_boundaries: tuple[int, ...],
    coarse_candidates: tuple[int, ...],
    n: int,
    coarse_step: int,
    total_cost,
) -> tuple[float, tuple[int, ...]] | None:
    """既存分割へ境界 1 本を粗→細 2 段で挿入し、最良 (合計コスト, 境界集合) を返す (候補ゼロは None)。

    【機能概要】: 粗グリッド候補で最小合計コストの挿入境界を選び (粗スキャン)、その採択境界の周囲
      ±coarse_step を 1 刻みで再走査 (細密スキャン) してより良い位置があれば置き換える (粗→細 2 段 / D5)。
    【改善内容】: segment_series 本体の貪欲挿入ループから 2 段スキャンを純関数へ切り出し、ループ本体を
      「挿入 → 記録 → 打ち切り判定」の 3 意図に絞って可読性を上げた (機能・決定論はビット等価)。
    【設計方針】: total_cost はメモ化クロージャを受け取り、粗・細で同一 (start,end) 区間コストを共有する
      (再評価なし / NFR-002)。細密採択は厳密 < のみで更新し、粗と同コストなら粗境界を保つ (安定 tie-break)。
    🔵 信頼性レベル: 設計 D5 (粗→細 2 段) / design-interview.md D-Q5 (メモ化) / NFR-102 に依拠。

    @param current_boundaries: 現在採択済みの境界集合 (昇順)。
    @param coarse_candidates: 粗グリッド刻みの境界候補列 (昇順)。空なら挿入不能 (None)。
    @param n: フレーム数 (細密スキャン上端を n-1 にクリップするのに用いる)。
    @param coarse_step: 粗グリッド刻み G (細密再走査の半径 ±G を兼ねる)。
    @param total_cost: 境界集合 -> 合計コストを返す評価関数 (メモ化済み)。
    @returns: (最良合計コスト, その境界集合) / 有効な粗候補が無ければ None。
    """
    # 【粗スキャン】: 既存分割へ境界 1 本を追加する全候補を評価し最小合計コストの挿入を選ぶ 🔵
    coarse_best = _scan_insertions(current_boundaries, coarse_candidates, total_cost)
    if coarse_best is None:
        return None
    best_cost, best_boundaries, new_boundary = coarse_best
    # 【細密スキャン】: 採択した新境界の周囲 ±coarse_step を 1 刻みで再配置 (端 1..n-1 にクリップ) 🔵
    fine_lo = max(1, new_boundary - coarse_step)
    fine_hi = min(n - 1, new_boundary + coarse_step)
    fine_best = _scan_insertions(
        current_boundaries, tuple(range(fine_lo, fine_hi + 1)), total_cost
    )
    if fine_best is not None and fine_best[0] < best_cost:
        # 【厳密 < 更新】: 粗と同コストなら粗境界を保持し決定論的な安定 tie-break を守る 🔵
        best_cost, best_boundaries = fine_best[0], fine_best[1]
    return best_cost, best_boundaries


def _segments(boundaries: tuple[int, ...], n: int) -> tuple[tuple[int, int], ...]:
    """境界集合から (start, end) inclusive のセグメント列を生成する (端 0/n は補う)。

    【機能概要】: 昇順境界 ``(b1, b2, ...)`` を ``(0, b1, b2, ..., n)`` の境界で区切り、各セグメントを
      両端 inclusive の ``(start, end)`` として返す。``n_segments == len(boundaries) + 1`` を常に満たす。
    🔵 信頼性レベル: 設計 D5 (境界 = セグメント先頭フレーム) / note.md §6-5 (半開規約) に依拠。
    """
    edges = (0, *boundaries, n)
    return tuple((edges[i], edges[i + 1] - 1) for i in range(len(edges) - 1))


def _interval_free_params(
    phases: tuple[PhaseInstance, ...],
    active_count: int,
    fixed_specs: tuple[FixedPhaseSpec, ...],
) -> frozenset[str]:
    """区間逐次 refine の free_params を構築する (活物質は scale+格子・固定相は scale のみ)。

    【機能概要】: index < active_count の活物質相に ``_ACTIVE_SUFFIXES`` (scale + lattice.a/b/c) を、
      以降の固定相に ``fixed_free_suffixes(spec) == ("scale",)`` を割り当て ``param_name`` へ展開する。
    🔵 信頼性レベル: FR-312 / REQ-009 (固定相は scale のみ解放) / cell_phases.py に依拠。
    """
    free: set[str] = set()
    for i in range(len(phases)):
        if i < active_count:
            # 【活物質解放】: 単相格子解放 (scale + a/b/c) で固溶体の連続格子変化を追従する 🔵
            for suffix in _ACTIVE_SUFFIXES:
                free.add(param_name(i, suffix))
        else:
            # 【固定相解放】: 構造固定・scale のみ (fixed_free_suffixes は常に ("scale",)) 🔵
            for suffix in fixed_free_suffixes(fixed_specs[i - active_count]):
                free.add(param_name(i, suffix))
    return frozenset(free)


def _frame_bic(result: RefinementResult) -> float:
    """1 フレームの RefinementResult から bic (= chi2 + n_params·ln(max(n_obs,1))) を算出する。

    【機能概要】: BICBackend と同一算法で bic を求める単一情報源。RefinementMetrics を組んで
      ``BICBackend.score().value`` を返し、バックエンド間で bic セマンティクスを統一する。
    【実装方針】: 有限 chi2 のフレームでのみ呼ぶ (非有限は Σbic へ混ぜない)。gof は sequential/engine.py と
      同式 sqrt(chi2/dof) で補完 (bic 自体は使わないが RefinementMetrics 契約を満たす)。
    🔵 信頼性レベル: evidence/ic.py BICBackend / discrimination._model_bic と同一算法に依拠。
    """
    dof = max(int(result.n_obs) - int(result.n_params), 1)
    chi2 = float(result.chi2)
    gof = math.sqrt(chi2 / dof) if math.isfinite(chi2) and chi2 >= 0.0 else float("inf")
    metrics = RefinementMetrics(
        rwp=float(result.rwp),
        gof=gof,
        chi2=chi2,
        n_obs=int(result.n_obs),
        n_params=int(result.n_params),
        # 【Issue #64 / FR-123 写像】: backend が推定した noise_scale を metrics へ伝播する 🔵
        noise_scale=result.noise_scale,
    )
    return float(_BIC.score(metrics).value)


def _make_partition(
    k: int, boundaries: tuple[int, ...], phases: tuple[PhaseInstance, ...], n: int
) -> Hypothesis:
    """k セグメント分割を 1 個の Hypothesis (id="seg-k{K}-...", frame_range=全区間) として組む (D6)。

    【機能概要】: 各 k の分割を代替閲覧可能な Hypothesis 化する。id は ``"seg-k{K}-{境界}"``
      (境界なしは ``"seg-k{K}-root"``) の決定論的採番、frame_range は全区間 ``(0, n-1)``。
    【実装方針】: 区間ごとの相構成は判別 (FR-313) 側の仮説が持つため、分割仮説は境界情報が主。
      phases には区間代表相 (initial_phases) を据える (D6「分割仮説は境界情報が主」)。
    🔵 信頼性レベル: 設計 D6 / design-interview.md D-Q6 / note.md §3.8 に依拠。
    """
    # 【決定論的 id】: 境界を "-" 連結して採番 (集合反復順非依存・2 回実行でビット同一) 🔵
    suffix = "-".join(str(b) for b in boundaries) if boundaries else "root"
    return Hypothesis(id=f"seg-k{k}-{suffix}", phases=phases, frame_range=(0, n - 1))


def _finalize_result(
    ledger: Ledger,
    boundaries: tuple[int, ...],
    evidence_by_k: Mapping[int, float],
    partitions: list[Hypothesis],
    warnings_list: list[str],
) -> SegmentationResult:
    """採択境界から最終 result を組み、"segmentation.result" を ledger 記録して返す (2 経路共通)。

    【機能概要】: 縮退経路 (k=1 固定) と貪欲挿入経路の 2 つの return を単一化する。n_segments を
      ``len(boundaries)+1`` で導き、結果 kind を追記してから frozen な SegmentationResult を構築する。
    【改善内容】: 2 箇所に重複していた「segmentation.result 追記 + SegmentationResult 構築 + 防御コピー」を
      1 箇所へ DRY 化し、経路差 (境界の有無) だけを引数で受ける形に整理した (機能はビット等価)。
    【設計方針】: evidence_by_k は dict() で、partitions/warnings は tuple() で防御コピーし、呼び側の
      可変リスト/辞書を frozen 契約の内側へ閉じ込める (非破壊 P2)。
    🔵 信頼性レベル: interfaces.py L301-310 (結果契約) / NFR-105 (result 追記) に依拠。

    @param ledger: 記録先の追記専用台帳 (呼び側は常に非 None で渡す)。
    @param boundaries: 採択境界 (縮退時は空 tuple)。n_segments はこの本数 +1。
    @param evidence_by_k: k 別合計コスト (dict 化して格納)。
    @param partitions: 各 k の分割仮説リスト (tuple 化して格納)。
    @param warnings_list: 縮退/非有限除外の警告リスト (tuple 化して格納)。
    @returns: 全フィールド設定済みの frozen な SegmentationResult。
    """
    n_segments = len(boundaries) + 1
    _record(
        ledger,
        "segmentation.result",
        {"boundaries": list(boundaries), "n_segments": n_segments},
    )
    return SegmentationResult(
        boundaries=boundaries,
        n_segments=n_segments,
        evidence_by_k=dict(evidence_by_k),
        partitions=tuple(partitions),
        ledger=ledger,
        warnings=tuple(warnings_list),
    )


def _num(value: float) -> float | str:
    """ledger payload 用に数値を正準化する (非有限は canonical JSON 安全な文字列へ)。

    【実装方針】: 有限値はそのまま float、inf/nan は "inf"/"nan" 文字列にして payload を厳密 JSON 安全に保つ
      (縮退経路のみ非有限が現れる)。verify() は格納 payload を再シリアライズするためチェーン整合は不変。
    🟡 信頼性レベル: store/ledger.py (canonical JSON) / NFR-105 に依拠 (非有限表現は設計裁量)。
    """
    if math.isfinite(value):
        return float(value)
    return "inf" if value > 0 else ("-inf" if value < 0 else "nan")


def _record(ledger: Ledger | None, kind: str, payload: dict) -> None:
    """ledger 提供時のみ分割操作を追記する (append-only / verify() 維持 / kind は "segmentation." 前置)。

    【実装方針】: payload は canonical JSON 可能な素の型 (int/float/str/list) に限る。ledger=None なら記録
      スキップ (本関数の呼び側は内部生成 ledger を渡すため実質常に記録)。
    🔵 信頼性レベル: NFR-105 / store/ledger.py append / discrimination._record 先例に依拠。
    """
    if ledger is not None:
        ledger.append(kind, payload)
