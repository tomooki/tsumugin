"""TASK-0032 operando/discrimination — 固溶体 vs 二相判別 (FR-313 / 設計 D4)。

operando 時系列の 1 区間 (フレーム範囲) に対し、同一データを説明する 2 つの競合仮説を構築し、
Evidence Engine (bic 一次) で **固溶体 vs 二相反応** を判別するオーケストレーション純関数を提供する。

- **仮説 A (固溶体)**: 区間フレームを**単相 warm-start 逐次 direct refine (格子解放)** し、区間合計
  ``Σbic_A`` を得る。
- **仮説 B (二相)**: **端成分 2 相** を区間端点の A 仮説格子で初期化 (**格子固定**)、``scale``/``wt_frac``
  のみ解放で逐次精密化して区間合計 ``Σbic_B`` を得る。
- 両仮説の**区間端点フレームでマルチスタート必須適用** (TASK-0028 ``MultistartEngine``、N=8 既定)。
  basin 情報を ``Hypothesis.metrics.multistart`` に記録する。
- ``ΔBIC = Σbic_A − Σbic_B`` を閾値 (既定 10.0) と比較して verdict を決める。僅差は自動確定せず
  ``ReviewQueue`` へ通知 (処理をブロックしない)。両仮説とも高 R はエスカレーションし判別しない。
- 固定相 (``FixedPhaseSpec``) は両仮説に常駐・構造固定・scale のみ解放。全操作を ``Ledger`` へ追記する。

決定論 (NFR-102): 乱数・時刻・集合反復順に依存しない。同一入力の 2 回実行で ``DiscriminationResult`` の
全フィールドがビット同一になる。バックエンド失敗は例外化せず chi2=inf の結果として縮退処理する。

🔵 信頼性レベル: 契約は ``docs/design/m3-operando/interfaces.py`` L252-284、設計 D4
  (``docs/design/m3-operando/architecture.md`` L71-76)、``dataflow.md`` FR-313 シーケンス (L53-77)、
  REQ-010/101/102・EDGE-002/005・NFR-102 に依拠。🟡 verdict 符号規約・仮説 B の free_suffixes・
  代表 rwp の集約・ledger kind は実装裁量 (いずれも要件へ遡及可能)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..backends.base import RefinementBackend, RefinementModel, RefinementResult, param_name
from ..model import Hypothesis, PhaseInstance, RefinementMetrics
from ..multistart import MultistartConfig, MultistartEngine, MultistartResult
from ..selection.review_queue import ReviewQueue
from ..sequential.series import FrameSeries
from ..store.ledger import Ledger
from .cell_phases import FixedPhaseSpec, fixed_free_suffixes

__all__ = ["DiscriminationConfig", "DiscriminationResult", "discriminate_interval"]

# 【仮説 A の解放 suffix】: 単相 warm-start 逐次 direct refine は scale + 格子 a/b/c を解放する
#   (逐次エンジンの探索モード相当 / 設計 D4)。A の evidence 用モデル DOF もこの 4 個。🔵
_SINGLE_FREE_SUFFIXES = ("scale", "lattice.a", "lattice.b", "lattice.c")
# 【仮説 B の解放 suffix (数値精密化)】: 端成分 2 相は**格子固定**で相分率のみ解放する (D4)。格子を
#   free_params に含めないことが binding な契約 (D4 / TC-N05)。数値参照バックエンド (SimulatedBackend)
#   では ``wt_frac`` が前方モデルに寄与しない不活性パラメータであり、これを解放すると勾配 0 の列が正規方程式
#   を悪条件化して LM の scale 収束を妨げる (端成分分率が過少収束し Σbic_B が誤って増大する)。よって精密化は
#   格子固定を保ったまま ``("scale",)`` のみ解放する。🟡 note.md §6-3
_TWO_PHASE_REFINE_SUFFIXES = ("scale",)
# 【仮説 B のモデル DOF (evidence 用)】: BIC ペナルティは端成分 2 相の設計 DOF「scale/wt」= 相あたり 2 個で
#   数える。これにより A (相あたり scale+格子 3 = 4 個) と 2 相 B (2 端成分 × 2 = 4 個) の複雑度が釣り合い、
#   ΔBIC = Σbic_A − Σbic_B からペナルティ項が相殺して判別が**適合度 (chi2) ベース**になる (設計が
#   意図した釣り合い。wt は参照バックエンドで不活性だが端成分分率という実モデル DOF)。🟡 note.md §6-2
_TWO_PHASE_MODEL_SUFFIXES = ("scale", "wt_frac")


@dataclass(frozen=True)
class DiscriminationConfig:
    """固溶体 vs 二相判別の設定 (frozen)。既定は interfaces.py L252-257 の契約に一致する。

    【機能概要】: ΔBIC 僅差閾値・必須マルチスタート設定・両仮説高 R 判定閾値・区間内逐次サイクル上限を束ねる。
    【テスト対応】: TC-BV04 (既定値 10.0 / 30.0 / 10 / MultistartConfig() と frozen 不変性)。
    🔵 信頼性レベル: interfaces.py L252-257 に直接依拠 (high_r_threshold / seq_max_cycles の既定は 🟡)。
    """

    close_threshold: float = 10.0  # 【僅差閾値】: |ΔBIC| がこの値未満なら僅差 = undecided (FR-122) 🔵
    multistart: MultistartConfig = MultistartConfig()  # 【必須適用】: 端点マルチスタート設定 (FR-233) 🔵
    high_r_threshold: float = 30.0  # 【高 R 閾値】: 両仮説の代表 rwp[%] がこれを超えたら未知相 (EDGE-005) 🟡
    seq_max_cycles: int = 10  # 【逐次サイクル上限】: 区間内 direct refine の max_cycles 🟡


@dataclass(frozen=True)
class DiscriminationResult:
    """FR-313 判別結果 (frozen・非破壊)。契約は interfaces.py L260-271。

    【機能概要】: verdict・ΔBIC・両仮説 (multistart 記録付き)・両仮説の端点マルチスタート結果・
      エスカレーション/警告を保持する不変の結果契約。
    【テスト対応】: TC-N01〜N08 / TC-E01〜E04 / TC-BV01〜BV05 の全 17 件。
    🔵 信頼性レベル: interfaces.py L260-271 に直接依拠。
    """

    verdict: Literal["solid_solution", "two_phase", "undecided"]  # 【判別】: 3 値のいずれか 🔵
    delta_evidence: float  # 【ΔBIC】: Σbic_A − Σbic_B (bic は小さいほど良い) 🔵
    hypothesis_single: Hypothesis  # 【仮説 A】: 単相 (metrics.multistart 付き) 🔵
    hypothesis_two_phase: Hypothesis  # 【仮説 B】: 端成分 2 相 (metrics.multistart 付き) 🔵
    multistart_single: MultistartResult  # 【A 端点マルチスタート】🔵
    multistart_two_phase: MultistartResult  # 【B 端点マルチスタート】🔵
    escalations: tuple[str, ...]  # 【エスカレーション】: 僅差/高 R の説明文字列 (REQ-101/EDGE-005) 🔵
    warnings: tuple[str, ...] = ()  # 【警告】: 発散除外/全滅縮退の伝播 (REQ-102/EDGE-002) 🔵


@dataclass
class _IntervalOutcome:
    """区間内 warm-start 逐次 direct refine の内部結果束 (非公開・非 frozen)。

    【機能概要】: 1 仮説の区間逐次精密化の Σbic・代表 rwp・区間端点の精密化済み相/結果・警告を保持し、
      ``discriminate_interval`` 本体のフェーズ分解を読みやすく保つ。
    🔵 信頼性レベル: dataflow.md FR-313 シーケンス (仮説 A/B の Σbic 算出) に依拠。
    """

    sum_bic: float  # 【Σbic】: 有限フレームの bic 合計 (非有限は混ぜない)
    representative_rwp: float  # 【代表 rwp】: 区間内有限フレームの最大 rwp (両仮説高 R 判定の基準)
    endpoint_phases: dict[int, tuple[PhaseInstance, ...]]  # 【端点相】: frame -> 精密化済み phases
    endpoint_results: dict[int, RefinementResult]  # 【端点結果】: frame -> RefinementResult
    warnings: tuple[str, ...]  # 【警告】: 非有限フレーム除外の警告
    n_finite: int  # 【有限数】: Σbic に寄与した有限フレーム数


def discriminate_interval(
    backend: RefinementBackend,
    series: FrameSeries,
    frame_range: tuple[int, int],
    initial_phases: tuple[PhaseInstance, ...],
    *,
    config: DiscriminationConfig = DiscriminationConfig(),
    fixed_phases: tuple[FixedPhaseSpec, ...] = (),
    ledger: Ledger | None = None,
    queue: ReviewQueue | None = None,
) -> DiscriminationResult:
    """operando 1 区間の固溶体 vs 二相判別を実行し ``DiscriminationResult`` を返す (FR-313)。

    【機能概要】: 仮説 A (単相 warm-start 逐次 direct refine) と仮説 B (端成分 2 相・格子固定) を同区間で
      精密化して Σbic を求め、両仮説の区間端点でマルチスタートを必須適用し、ΔBIC の符号/大きさで verdict を
      決める。僅差/高 R は自動確定せず ReviewQueue へ通知しエスカレーションする (処理をブロックしない)。
    【実装方針】: 下位部品 (逐次 refine / MultistartEngine / BIC 評価 / ReviewQueue / Ledger) を束ねる
      薄いオーケストレータ。乱数・時刻・集合反復順に依存せず 2 回実行でビット同一 (NFR-102)。
    【テスト対応】: tests/test_discrimination.py の 17 件すべて。
    🔵 信頼性レベル: 設計 D4 / dataflow.md FR-313 (L53-77) / interfaces.py L274-284 に直接依拠。

    @param backend: 精密化バックエンド (RefinementBackend Protocol: name + refine)。
    @param series: 共通 2θ グリッド + (n_frames, n_points) 強度行列を持つ FrameSeries。
    @param frame_range: 判別対象区間 (start, end)。両端 inclusive・0<=start<=end<n_frames を要求する。
    @param initial_phases: 活物質の初期相 (仮説 A の単相起点)。
    @param config: 判別設定 (閾値・マルチスタート・逐次サイクル)。
    @param fixed_phases: セル固定相 (両仮説に常駐・構造固定・scale のみ解放)。
    @param ledger: 追記専用台帳 (None なら記録スキップ・結果不変)。
    @param queue: エスカレーション通知先 (None なら通知スキップ・結果不変)。
    @returns: verdict・ΔBIC・両仮説・両マルチスタート・エスカレーション/警告を含む DiscriminationResult。
    """
    # 【フェイルファスト検証】: 器の契約違反 (範囲外/start>end/負値) は refine 開始前に ValueError にする 🟡 TC-E04
    start, end = _validate_frame_range(frame_range, series.n_frames)

    two_theta = np.asarray(series.two_theta, dtype=float)
    fixed_instances = tuple(spec.phase for spec in fixed_phases)

    engine = MultistartEngine(backend, config=config.multistart, ledger=ledger)

    # ---- 仮説 A: 単相 warm-start 逐次 direct refine (格子解放) --------------------------
    #   格子が連続変化する固溶体を追従するため warm start (直近成功フレームの確定 phases を継承)。🔵
    active_count_a = len(initial_phases)
    init_a = tuple(initial_phases) + fixed_instances
    seq_a = _refine_interval(
        backend, two_theta, series, start, end, init_a, active_count_a,
        refine_suffixes=_SINGLE_FREE_SUFFIXES, model_suffixes=_SINGLE_FREE_SUFFIXES,
        fixed_specs=fixed_phases, seq_max_cycles=config.seq_max_cycles,
        warm_start=True, label="hypothesis_a",
    )

    # ---- 仮説 A の区間端点フレームでマルチスタート必須適用 (start/end) ----------------------
    #   必須適用 (REQ-004) に加え、その basin 代表を「端点で十分収束させた A 格子」として仮説 B の端成分
    #   初期化に用いる。warm-start 逐次の端点は中間フレーム由来の格子劣化 (縮退非立方解) を持ちうるため、
    #   端点で独立探索・十分サイクル精密化するマルチスタート代表の方が端成分格子として正確 (D4「端点の A 格子で
    #   初期化」の忠実な実現)。🟡 note.md §6
    ms_a_start, ms_a_end = _endpoint_multistarts(
        engine, two_theta, series, start, end, seq_a.endpoint_phases, _SINGLE_FREE_SUFFIXES
    )
    multistart_single = ms_a_end

    # ---- 仮説 B: 区間端点の A 格子で端成分 2 相を初期化 (格子固定・scale のみ解放) ----------
    #   α = start 端点 / β = end 端点の A 格子 (マルチスタート代表、無ければ逐次端点へフォールバック)。🟡
    #   格子固定 B は warm start しない (フレームごとに端成分テンプレートから相分率を独立に精密化する):
    #   scale を warm 継承すると参照バックエンドの早期停止で相分率が累積的に過少収束し Σbic_B が誤って
    #   増大するため、各フレーム独立の相分率推定 (fresh init) を採る (数値安定・より正しい分率推定)。🟡
    alpha = _endpoint_lattice_source(ms_a_start, seq_a.endpoint_phases[start], active_count_a)
    beta = _endpoint_lattice_source(ms_a_end, seq_a.endpoint_phases[end], active_count_a)
    b_active = alpha + beta
    active_count_b = len(b_active)
    init_b = b_active + fixed_instances
    seq_b = _refine_interval(
        backend, two_theta, series, start, end, init_b, active_count_b,
        refine_suffixes=_TWO_PHASE_REFINE_SUFFIXES, model_suffixes=_TWO_PHASE_MODEL_SUFFIXES,
        fixed_specs=fixed_phases, seq_max_cycles=config.seq_max_cycles,
        warm_start=False, label="hypothesis_b",
    )

    # ---- 仮説 B の区間端点フレームでマルチスタート必須適用 (格子固定を破らない scale のみ) --------
    _, multistart_two_phase = _endpoint_multistarts(
        engine, two_theta, series, start, end, seq_b.endpoint_phases, _TWO_PHASE_REFINE_SUFFIXES
    )

    # ---- 判別: ΔBIC = Σbic_A − Σbic_B と両仮説高 R でエスカレーション判定 --------------------
    delta = seq_a.sum_bic - seq_b.sum_bic
    both_high_r = (
        seq_a.representative_rwp > config.high_r_threshold
        and seq_b.representative_rwp > config.high_r_threshold
    )
    verdict, escalations, queue_reason = _decide_verdict(
        delta, config.close_threshold, both_high_r, seq_a.representative_rwp, seq_b.representative_rwp
    )

    # ---- ReviewQueue 通知 (提供時のみ・ブロックしない) -----------------------------------
    if queue is not None and queue_reason is not None:
        queue.add(queue_reason, detail=escalations[0] if escalations else "")

    # ---- 両仮説 Hypothesis を metrics.multistart 付きで構築 (単一 basin でも付与) -----------
    #   両仮説の構築は id・区間結果・端点マルチスタートだけが異なる同形処理のため共通ヘルパへ集約する 🔵
    hyp_single = _build_endpoint_hypothesis(
        "discrimination-single", seq_a, multistart_single, start, end
    )
    hyp_two_phase = _build_endpoint_hypothesis(
        "discrimination-two-phase", seq_b, multistart_two_phase, start, end
    )

    # ---- 警告の集約 (発散除外/全滅縮退を判別結果へ伝播) ----------------------------------
    warnings = (
        seq_a.warnings + seq_b.warnings
        + multistart_single.warnings + multistart_two_phase.warnings
    )

    # ---- ledger 記録 (提供時のみ・全 kind は "discrimination." 前置) --------------------
    _record(ledger, "discrimination.hypothesis_single", {"sum_bic": seq_a.sum_bic, "n_finite": seq_a.n_finite})
    _record(ledger, "discrimination.hypothesis_two_phase", {"sum_bic": seq_b.sum_bic, "n_finite": seq_b.n_finite})
    _record(ledger, "discrimination.verdict", {"verdict": verdict, "delta_evidence": delta})
    if escalations:
        _record(ledger, "discrimination.escalation", {"reasons": list(escalations)})

    return DiscriminationResult(
        verdict=verdict,
        delta_evidence=delta,
        hypothesis_single=hyp_single,
        hypothesis_two_phase=hyp_two_phase,
        multistart_single=multistart_single,
        multistart_two_phase=multistart_two_phase,
        escalations=escalations,
        warnings=warnings,
    )


# ===========================================================================
# 内部ヘルパ (純関数的・決定論)
# ===========================================================================


def _validate_frame_range(frame_range: tuple[int, int], n_frames: int) -> tuple[int, int]:
    """区間契約 (0 <= start <= end < n_frames) を検証し int 正規化した (start, end) を返す。

    【機能概要】: 器の契約違反 (範囲外/start>end/負値) を refine 開始前に ValueError で弾く
      フェイルファスト検証 (sequential/series.py の明示 ValueError 慣習)。フレーム 1 本も精密化しない。
    【設計方針】: 両端 inclusive・end < n_frames を要求する (dataflow「区間端点」の自然な解釈)。
    【テスト対応】: TC-E04 (start>end / 範囲外 / 負値 の 3 パターンで ValueError・refine 未開始)。
    🟡 信頼性レベル: requirements §2.2 / series.py 慣習に依拠 (両端 inclusive は妥当推測)。

    @param frame_range: 判別対象区間 (start, end)。両端 inclusive。
    @param n_frames: 系列のフレーム数 (end はこれ未満を要求する)。
    @returns: int 正規化した (start, end)。
    """
    start, end = int(frame_range[0]), int(frame_range[1])
    if start < 0 or end < 0 or start > end or end >= n_frames:
        raise ValueError(
            f"invalid frame_range {frame_range} for series with n_frames={n_frames} "
            f"(require 0 <= start <= end < n_frames)"
        )
    return start, end


def _interval_free_params(
    phases: tuple[PhaseInstance, ...],
    active_count: int,
    active_suffixes: tuple[str, ...],
    fixed_specs: tuple[FixedPhaseSpec, ...],
) -> frozenset[str]:
    """区間逐次 refine の free_params を構築する (活物質は active_suffixes・固定相は scale のみ)。

    【実装方針】: index < active_count の活物質相には active_suffixes を、以降の固定相には
      ``fixed_free_suffixes(spec) == ("scale",)`` を割り当てて ``param_name(i, suffix)`` へ展開する。
    🔵 信頼性レベル: FR-312 / REQ-009 (固定相は scale のみ解放) / cell_phases.py に依拠。
    """
    free: set[str] = set()
    for i in range(len(phases)):
        if i < active_count:
            # 【活物質解放】: 仮説種別の suffix (A=scale+格子 / B=scale+wt) を解放する 🔵
            for suffix in active_suffixes:
                free.add(param_name(i, suffix))
        else:
            # 【固定相解放】: 構造固定・scale のみ (fixed_free_suffixes は常に ("scale",)) 🔵
            for suffix in fixed_free_suffixes(fixed_specs[i - active_count]):
                free.add(param_name(i, suffix))
    return frozenset(free)


def _refine_interval(
    backend: RefinementBackend,
    two_theta: np.ndarray,
    series: FrameSeries,
    start: int,
    end: int,
    init_phases: tuple[PhaseInstance, ...],
    active_count: int,
    *,
    refine_suffixes: tuple[str, ...],
    model_suffixes: tuple[str, ...],
    fixed_specs: tuple[FixedPhaseSpec, ...],
    seq_max_cycles: int,
    warm_start: bool,
    label: str,
) -> _IntervalOutcome:
    """区間 [start, end] を逐次 direct refine し Σbic・端点相・代表 rwp を返す。

    【機能概要】: 区間の各フレームを 1 回 direct refine し、有限フレームの bic を合計する (非有限は Σbic に
      混ぜず警告する / M1 教訓)。``warm_start`` が真なら直近成功フレームの確定 phases を次フレームの初期値に
      継承し (仮説 A: 格子連続変化の追従)、偽なら毎フレーム ``init_phases`` から精密化する (仮説 B:
      格子固定端成分の相分率を独立推定)。
    【実装方針】: sequential/engine.py の warm-start 逐次パターン (changepoint/木探索なしの軽量版) を踏襲。
      max_cycles=seq_max_cycles で direct refine (マルチスタートの ms_max_cycles と識別可能)。bic ペナルティ
      は ``refine_suffixes`` (実解放数) ではなく ``model_suffixes`` (設計モデル DOF) で数え、両仮説の複雑度を
      釣り合わせる (ΔBIC からペナルティ相殺 → 適合度ベース判別)。
    【テスト対応】: TC-N01/N02 (Σbic 比較で verdict) / TC-N05 (B は格子非解放) / TC-E03 (非有限縮退)。
    🔵 信頼性レベル: dataflow.md FR-313 (Σbic 算出) / sequential/engine.py warm-start に依拠。

    @returns: Σbic・代表 rwp・区間端点の精密化済み相/結果・警告・有限フレーム数を束ねた _IntervalOutcome。
    """
    warm = init_phases  # 【逐次源】: warm_start 時は直近成功フレームの確定 phases (初期は init_phases) 🔵
    sum_bic = 0.0
    rwps: list[float] = []
    warnings: list[str] = []
    endpoint_phases: dict[int, tuple[PhaseInstance, ...]] = {}
    endpoint_results: dict[int, RefinementResult] = {}
    n_finite = 0

    for i in range(start, end + 1):
        intensity = np.asarray(series.intensities[i], dtype=float)
        # 【初期値選択】: warm_start=真は前フレーム継承、偽は毎回 init_phases (格子固定の独立分率推定) 🔵
        base = warm if warm_start else init_phases
        free = _interval_free_params(base, active_count, refine_suffixes, fixed_specs)
        model = RefinementModel(
            phases=base, free_params=free, two_theta=two_theta, intensity=intensity
        )
        # 【direct refine】: staged 解放ループなし、seq_max_cycles で 1 回だけ精密化する 🔵
        result = backend.refine(model, max_cycles=seq_max_cycles)
        chi2 = float(result.chi2)
        if math.isfinite(chi2):
            # 【有限フレーム】: 釣り合いモデル DOF の bic を加算する 🔵
            sum_bic += _model_bic(result, active_count, model_suffixes)
            rwps.append(float(result.rwp))
            if warm_start:
                warm = result.phases  # 【warm 更新】: 成功フレームのみ継承 (失敗は据え置き) 🔵
            n_finite += 1
        else:
            # 【非有限縮退】: Σbic に inf を混ぜず警告する (非有限を漏らさない) 🔵
            warnings.append(
                f"discrimination {label}: frame {i} の精密化が非有限 chi2 のため Σbic から除外しました。"
            )
        # 【端点捕捉】: start/end フレームの精密化済み相と結果を保持する (マルチスタート/B 初期化に用いる) 🔵
        if i == start or i == end:
            endpoint_phases[i] = result.phases if math.isfinite(chi2) else base
            endpoint_results[i] = result

    # 【代表 rwp】: 区間内有限フレームの最大 rwp。有限フレーム皆無なら inf (EDGE-005 経路へ縮退) 🟡
    representative_rwp = max(rwps) if rwps else float("inf")
    return _IntervalOutcome(
        sum_bic=sum_bic,
        representative_rwp=representative_rwp,
        endpoint_phases=endpoint_phases,
        endpoint_results=endpoint_results,
        warnings=tuple(warnings),
        n_finite=n_finite,
    )


def _endpoint_multistarts(
    engine: MultistartEngine,
    two_theta: np.ndarray,
    series: FrameSeries,
    start: int,
    end: int,
    endpoint_phases: dict[int, tuple[PhaseInstance, ...]],
    free_suffixes: tuple[str, ...],
) -> tuple[MultistartResult, MultistartResult]:
    """区間端点 (start/end) の両フレームでマルチスタートを適用し (start 結果, end 結果) を返す。

    【機能概要】: REQ-004 の「判別時マルチスタート必須適用」を区間端点 2 フレームで満たすため、start と
      end の両方で ``MultistartEngine.run`` を呼ぶ (全フレームには掛けない / 性能 NFR-001)。判別結果には
      end 端点を代表として格納し (呼び側)、両端点の代表は仮説 B の端成分格子源に用いる。
    【実装方針】: start==end の縮退区間でも両端点で 2 回実行し、呼び出し本数 (端点2×n_starts) を安定させる。
    【テスト対応】: TC-N03 (端点2×仮説2×n_starts 本) / TC-N04 (basin 整合) / TC-E03 (全滅縮退)。
    🔵 信頼性レベル: 設計 D4 / dataflow.md FR-313 (端点マルチスタート必須) / REQ-004 に依拠。
    """
    ms_start = engine.run(
        endpoint_phases[start],
        two_theta,
        np.asarray(series.intensities[start], dtype=float),
        free_suffixes=free_suffixes,
    )
    ms_end = engine.run(
        endpoint_phases[end],
        two_theta,
        np.asarray(series.intensities[end], dtype=float),
        free_suffixes=free_suffixes,
    )
    return ms_start, ms_end


def _endpoint_lattice_source(
    multistart: MultistartResult,
    fallback_phases: tuple[PhaseInstance, ...],
    active_count: int,
) -> tuple[PhaseInstance, ...]:
    """端点の端成分格子源となる活物質相を返す (マルチスタート最良 basin 代表 / 無ければ逐次端点)。

    【機能概要】: 端点マルチスタートの最良 basin (evidence 昇順先頭) 代表 phases の活物質部分を返す。
      basin が空 (全滅) なら逐次端点の phases へフォールバックする。仮説 B の端成分は格子のみ用いる
      (scale は B 側で再精密化) ため、ここでは活物質相の格子を確定させることが目的。
    【実装方針】: 代表 phases は活物質 + 固定相を含むため先頭 active_count 相 (活物質) を切り出す。
    🔵 信頼性レベル: multistart/basin.py (basins は evidence 昇順・代表は chi2 最小) / REQ-102 に依拠。
    """
    # 【最良 basin 代表 / フォールバック】: 全滅時は逐次端点を用いて端成分格子を確保する 🔵
    source = multistart.basins[0].representative.phases if multistart.basins else fallback_phases
    return tuple(source[:active_count])


def _decide_verdict(
    delta: float,
    close_threshold: float,
    both_high_r: bool,
    rwp_single: float,
    rwp_two_phase: float,
) -> tuple[Literal["solid_solution", "two_phase", "undecided"], tuple[str, ...], str | None]:
    """ΔBIC と両仮説高 R から verdict・エスカレーション文字列・Queue 通知 reason を決める。

    【実装方針】: (1) 両仮説高 R (EDGE-005) を最優先で判定し「判別なし」= undecided + all_high_r へ縮退、
      (2) ΔBIC ≤ −閾値 → solid_solution、(3) ΔBIC ≥ +閾値 → two_phase (いずれも閉境界 >=/<=)、
      (4) |ΔBIC| < 閾値 → 僅差 undecided + close_competitor。verdict Literal は 3 値のみのため両仮説高 R
      の「判別しない」は undecided + エスカレーションで表現する (contract 整合)。
    【テスト対応】: TC-N01/N02 (明瞭判別・escalations 空) / TC-E01 (僅差) / TC-E02 (両仮説高 R) /
      TC-BV01 (閉境界)。
    🟡 信頼性レベル: note.md §6-1/6-2 (verdict 符号規約・EDGE-005 表現) に依拠。

    @returns: (verdict, escalations タプル, Queue 通知 reason または None)。
    """
    # 【EDGE-005 優先】: 両仮説とも高 R は chi2 差に依らず判別しない (未知相の疑い) 🔵
    if both_high_r:
        message = (
            f"all_high_r: 両仮説の代表 rwp (single={rwp_single:.4g}%, two_phase={rwp_two_phase:.4g}%) が "
            f"高 R 閾値を超過しました。未知相の疑いがあり判別を確定しません。"
        )
        return "undecided", (message,), "all_high_r"

    # 【明瞭判別】: ΔBIC = Σbic_A − Σbic_B。bic は小さいほど良く、閉境界 (>=/<=) で確定側とする 🔵
    if delta <= -close_threshold:
        return "solid_solution", (), None
    if delta >= close_threshold:
        return "two_phase", (), None

    # 【僅差 (REQ-101)】: |ΔBIC| < 閾値 は自動確定せず undecided + Review Queue 通知 (ブロックしない) 🔵
    message = (
        f"close_competitor: |ΔBIC|={abs(delta):.4g} < close_threshold={close_threshold:.4g} のため "
        f"判別を確定せず暫定 undecided とします (暫定優位側は delta_evidence の符号で読めます)。"
    )
    return "undecided", (message,), "close_competitor"


def _model_bic(
    result: RefinementResult, active_count: int, model_suffixes: tuple[str, ...]
) -> float:
    """釣り合いモデル DOF で bic (= chi2 + k·ln(max(n_obs,1))) を算出する (BICBackend と同一算法)。

    【機能概要】: BIC のペナルティ次数 k を、バックエンドが報告する実解放数ではなく設計モデル DOF で数える:
      活物質相は各 ``len(model_suffixes)`` 個、固定相は各 1 個 (scale のみ / fixed_free_suffixes) とする。
    【実装方針】: 仮説 A (相あたり scale+格子 3 = 4) と 2 相 B (2 端成分 × (scale,wt) = 4) の複雑度を釣り合わせ、
      ΔBIC = Σbic_A − Σbic_B からペナルティ項を相殺させて判別を適合度 (chi2) ベースにする (設計の意図)。
      wt は参照バックエンドで不活性だが端成分分率という実モデル DOF のため evidence 上は 1 自由度と数える。
    🔵 信頼性レベル: evidence/ic.py BICBackend (BIC = chi2 + k·ln(max(n_obs,1))) / note.md §6-2 に依拠。
    """
    n_fixed = max(len(result.phases) - active_count, 0)
    # 【モデル DOF】: 活物質は model_suffixes 個 / 固定相は scale の 1 個 (fixed_free_suffixes) 🔵
    k = active_count * len(model_suffixes) + n_fixed
    return float(result.chi2) + k * math.log(max(int(result.n_obs), 1))


def _build_endpoint_hypothesis(
    hyp_id: str,
    outcome: _IntervalOutcome,
    multistart: MultistartResult,
    start: int,
    end: int,
) -> Hypothesis:
    """区間 end 端点の精密化結果から metrics.multistart 付き Hypothesis を組む (両仮説共通)。

    【機能概要】: 仮説 A/B の Hypothesis 構築は id・区間結果・端点マルチスタートだけが異なる同形処理のため、
      共通ヘルパに集約して重複を除く (DRY)。phases/metrics は区間 end 端点の精密化結果から導出する。
    【実装方針】: metrics には _metrics_with_multistart で basin メタ ({"n","n_basins","n_diverged"}) を付す。
    🔵 信頼性レベル: interfaces.py L266 / D4「basin 情報を metrics に記録」に依拠。

    @param hyp_id: 決定論的な Hypothesis id ("discrimination-single" / "discrimination-two-phase")。
    @param outcome: 当該仮説の区間逐次 refine 結果 (端点相/結果を保持)。
    @param multistart: 当該仮説の end 端点マルチスタート結果 (metrics に basin メタとして畳む)。
    @param start: 区間始点 (frame_range 記録用)。
    @param end: 区間終点 (端点相/結果の参照キー兼 frame_range 記録用)。
    @returns: metrics.multistart 付き Hypothesis (frame_range=(start, end))。
    """
    return Hypothesis(
        id=hyp_id,
        phases=outcome.endpoint_phases[end],
        metrics=_metrics_with_multistart(outcome.endpoint_results[end], multistart),
        frame_range=(start, end),
    )


def _metrics_with_multistart(
    result: RefinementResult, multistart: MultistartResult
) -> RefinementMetrics:
    """端点 refine 結果に端点マルチスタートの basin メタ (multistart={"n","n_basins","n_diverged"}) を付す。

    【実装方針】: multistart 記録は引数の ``MultistartResult`` からのみ導出するため、
      ``metrics.multistart["n_basins"] == len(multistart.basins)`` 等が構造的に整合する (TC-N04)。
    🔵 信頼性レベル: interfaces.py L266 / multistart/engine.py _promote と同一スキーマに依拠。
    """
    dof = max(int(result.n_obs) - int(result.n_params), 1)
    chi2 = float(result.chi2)
    # 【GoF 変換】: sequential/engine.py と同式。非有限 chi2 は inf へ縮退する 🔵
    gof = math.sqrt(chi2 / dof) if math.isfinite(chi2) else float("inf")
    return RefinementMetrics(
        rwp=float(result.rwp),
        gof=gof,
        chi2=chi2,
        n_obs=int(result.n_obs),
        n_params=int(result.n_params),
        multistart={
            "n": int(multistart.n_starts),
            "n_basins": len(multistart.basins),
            "n_diverged": int(multistart.n_diverged),
        },
    )


def _record(ledger: Ledger | None, kind: str, payload: dict) -> None:
    """ledger 提供時のみ判別操作を追記する (append-only / verify() 維持)。

    【実装方針】: ledger=None なら記録スキップ (結果は ledger 有無で不変 / TC-BV02)。kind は必ず
      "discrimination." 前置で、payload は canonical JSON 可能な素の型に限る (TC-N07)。
    🔵 信頼性レベル: NFR-105 / store/ledger.py append / multistart/engine.py _record 先例に依拠。
    """
    if ledger is not None:
        ledger.append(kind, payload)
