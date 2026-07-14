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
全フィールドがビット同一になる。バックエンド失敗は例外化せず chi2=inf の結果として縮退処理する。片仮説が
区間全域で失敗する / 両仮説が異なるフレーム部分集合で Σbic を計上する場合は、比較可能性ガードにより
``undecided`` + ``incomparable_evidence`` へ縮退して誤確定を防ぐ (Σbic は有限フレームのみの和で、除外が
多いほど不当に小さくなるため)。

制限 (M3 v1): 仮説 B の evidence 用モデル DOF を仮説 A と釣り合わせる設計 (``_TWO_PHASE_MODEL_SUFFIXES``)
のため、ΔBIC からペナルティ項が相殺し判別は実質 chi2 差 (適合度差) に帰着する。この釣り合わせは合成ベンチで
較正した M3 v1 の暫定仕様であり、実データでの妥当性 (端成分 DOF の数え方) は要検証。

**nested 裁定の配線 (Issue #65 / FR-313 / FR-122)**: ``config.nested_arbitration`` (既定 None) を
``ArbitrationConfig`` で与えるとオプトインで発動する。bic 一次判定が close_competitor (僅差) と
判定したときのみ ``nested.arbitration.arbitrate`` (``full_nested=True`` 強制) で仮説 A/B のみを
再裁定し、暫定 verdict・``adjudicated_by``・``nested_delta_evidence`` を結果へ反映する。非僅差では
一切呼ばない (コスト抑制)。ReviewQueue への close_competitor 通知は再裁定後も維持する
(FR-403「暫定裁定+要確認フラグ」・処理はブロックしない)。nested/EvidenceProblem は Σbic を
BIC 対応値 (chi2=Σbic, k=0) として渡す v1 サロゲートで、実 nested サンプラでの evidence は
このサロゲートの粗い近似 (restraint 由来の物理事前分布/尤度の配線は M-later)。裁定が例外で完全に
失敗しても bic 一次の close_competitor エスカレーションへ縮退する (例外化しない)。

🔵 信頼性レベル: 契約は ``docs/design/m3-operando/interfaces.py`` L252-284、設計 D4
  (``docs/design/m3-operando/architecture.md`` L71-76)、``dataflow.md`` FR-313 シーケンス (L53-77)、
  REQ-010/101/102・EDGE-002/005・NFR-102 に依拠。🟡 verdict 符号規約・仮説 B の free_suffixes・
  代表 rwp の集約・ledger kind は実装裁量 (いずれも要件へ遡及可能)。nested 裁定配線 (Issue #65) は
  M5 ``nested.arbitration`` の既存契約に依拠しつつ、EvidenceProblem サロゲート化は実装裁量 🟡。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

from ..backends.base import RefinementBackend, RefinementModel, RefinementResult, param_name
from ..evidence.ic import BICBackend
from ..model import Hypothesis, PhaseInstance, RefinementMetrics
from ..multistart import MultistartConfig, MultistartEngine, MultistartResult
from ..nested.arbitration import ArbitrationConfig, ArbitrationResult, arbitrate
from ..nested.base import EvidenceProblem, PriorSpec
from ..nested.sampler import NestedBackend
from ..selection.review_queue import ReviewQueue
from ..sequential.series import FrameSeries
from ..store.ledger import Ledger
from .cell_phases import FixedPhaseSpec, fixed_free_suffixes

__all__ = ["DiscriminationConfig", "DiscriminationResult", "discriminate_interval"]

# 【bic 算出源】: 区間 Σbic は各フレーム RefinementResult を RefinementMetrics 化し同一 BICBackend で
#   評価する (segmentation._frame_bic と同一の単一情報源)。bic 式の重複実装を避けバックエンド間で統一 🔵
_BIC = BICBackend()

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
    # 【nested 裁定オプトイン (Issue #65 / FR-313 / FR-122)】: None (既定) は現行挙動不変。
    #   ArbitrationConfig を与えると close_competitor (僅差) のときのみ nested/Laplace 再裁定を発動する。🟡
    nested_arbitration: ArbitrationConfig | None = None


@dataclass(frozen=True)
class DiscriminationResult:
    """FR-313 判別結果 (frozen・非破壊)。契約は interfaces.py L260-271。

    【機能概要】: verdict・ΔBIC・両仮説 (multistart 記録付き)・両仮説の端点マルチスタート結果・
      エスカレーション/警告を保持する不変の結果契約。
    【テスト対応】: TC-N01〜N08 / TC-E01〜E04 / TC-BV01〜BV05 の全 17 件。
    🔵 信頼性レベル: interfaces.py L260-271 に直接依拠。
    """

    verdict: Literal["solid_solution", "two_phase", "undecided"]  # 【判別】: 3 値のいずれか 🔵
    # 【ΔBIC】: Σbic_A − Σbic_B (bic は小さいほど良い)。符号を「暫定優位側」と読めるのは close_competitor
    #   (僅差) の undecided のみ。incomparable_evidence / all_high_r の undecided では Σbic が異なるフレーム
    #   集合の和 / 高 R 由来で符号に意味がないため、優位側の指標に用いてはならない 🔵
    delta_evidence: float
    hypothesis_single: Hypothesis  # 【仮説 A】: 単相 (metrics.multistart 付き) 🔵
    hypothesis_two_phase: Hypothesis  # 【仮説 B】: 端成分 2 相 (metrics.multistart 付き) 🔵
    multistart_single: MultistartResult  # 【A 端点マルチスタート】🔵
    multistart_two_phase: MultistartResult  # 【B 端点マルチスタート】🔵
    escalations: tuple[str, ...]  # 【エスカレーション】: 僅差/高 R の説明文字列 (REQ-101/EDGE-005) 🔵
    warnings: tuple[str, ...] = ()  # 【警告】: 発散除外/全滅縮退の伝播 (REQ-102/EDGE-002) 🔵
    # 【nested 裁定由来 (Issue #65 / FR-313 / FR-122)】: nested_arbitration 未設定 / 非僅差では
    #   "bic" のまま・nested_delta_evidence/nested_arbitration は None (既定・後方互換) 🟡
    adjudicated_by: Literal["bic", "nested", "laplace"] = "bic"
    nested_delta_evidence: float | None = None  # 【nested/Laplace 裁定後の ΔBIC 相当】 🟡
    nested_arbitration: ArbitrationResult | None = None  # 【nested 裁定の生結果 (詳細監査用)】 🟡


@dataclass(frozen=True)
class _IntervalOutcome:
    """区間内 warm-start 逐次 direct refine の内部結果束 (非公開・frozen)。

    【機能概要】: 1 仮説の区間逐次精密化の Σbic・代表 rwp・区間端点の精密化済み相/結果・警告を保持し、
      ``discriminate_interval`` 本体のフェーズ分解を読みやすく保つ。
    🔵 信頼性レベル: dataflow.md FR-313 シーケンス (仮説 A/B の Σbic 算出) に依拠。
    """

    sum_bic: float  # 【Σbic】: 有限フレームの bic 合計 (非有限は混ぜない)
    representative_rwp: float  # 【代表 rwp】: 区間内有限フレームの最大 rwp (両仮説高 R 判定の基準)
    endpoint_phases: dict[int, tuple[PhaseInstance, ...]]  # 【端点相】: frame -> 精密化済み phases
    endpoint_results: dict[int, RefinementResult]  # 【端点結果】: frame -> RefinementResult
    warnings: tuple[str, ...]  # 【警告】: 非有限フレーム除外の警告
    # 【有限フレーム集合】: Σbic に寄与した有限フレーム index の集合。件数だけでなく「どのフレームが有限か」を
    #   保持し、両仮説が異なるフレーム部分集合で Σbic を計上する非対称比較を検出できるようにする 🔵
    finite_frames: frozenset[int]


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
    nested_backend: NestedBackend | None = None,
) -> DiscriminationResult:
    """operando 1 区間の固溶体 vs 二相判別を実行し ``DiscriminationResult`` を返す (FR-313)。

    【機能概要】: 仮説 A (単相 warm-start 逐次 direct refine) と仮説 B (端成分 2 相・格子固定) を同区間で
      精密化して Σbic を求め、両仮説の区間端点でマルチスタートを必須適用し、ΔBIC の符号/大きさで verdict を
      決める。僅差/高 R は自動確定せず ReviewQueue へ通知しエスカレーションする (処理をブロックしない)。
    【nested 裁定 (Issue #65 / FR-313 / FR-122)】: ``config.nested_arbitration`` (既定 None) を与えた
      ときのみ、bic 一次判定が close_competitor (僅差) と判定した場合に限り
      ``nested.arbitration.arbitrate`` で仮説 A/B を再裁定する (非僅差では絶対に呼ばない)。再裁定が
      解消できれば verdict を暫定的に確定するが、ReviewQueue への close_competitor 通知は維持する
      (FR-403「暫定裁定+要確認フラグ」)。裁定が完全に失敗しても例外化せず bic 一次のエスカレーションへ
      縮退する。
    【実装方針】: 下位部品 (逐次 refine / MultistartEngine / BIC 評価 / ReviewQueue / Ledger / nested
      裁定) を束ねる薄いオーケストレータ。乱数・時刻・集合反復順に依存せず 2 回実行でビット同一
      (NFR-102。ただし nested_backend に実サンプラを注入した場合はサンプラ自身の再現性契約に従う)。
    【テスト対応】: tests/test_discrimination.py。
    🔵 信頼性レベル: 設計 D4 / dataflow.md FR-313 (L53-77) / interfaces.py L274-284 に直接依拠。
      nested 裁定配線 (Issue #65) は実装裁量 🟡。

    @param backend: 精密化バックエンド (RefinementBackend Protocol: name + refine)。
    @param series: 共通 2θ グリッド + (n_frames, n_points) 強度行列を持つ FrameSeries。
    @param frame_range: 判別対象区間 (start, end)。両端 inclusive・0<=start<=end<n_frames を要求する。
    @param initial_phases: 活物質の初期相 (仮説 A の単相起点)。
    @param config: 判別設定 (閾値・マルチスタート・逐次サイクル・nested 裁定オプトイン)。
    @param fixed_phases: セル固定相 (両仮説に常駐・構造固定・scale のみ解放)。
    @param ledger: 追記専用台帳 (None なら記録スキップ・結果不変)。
    @param queue: エスカレーション通知先 (None なら通知スキップ・結果不変)。
    @param nested_backend: nested 裁定に用いる ``NestedBackend`` 互換オブジェクト (テスト注入用)。
      None かつ ``config.nested_arbitration`` が非 None のときのみ既定 ``NestedBackend()`` を構築する。
    @returns: verdict・ΔBIC・両仮説・両マルチスタート・エスカレーション/警告・nested 裁定由来を含む
      DiscriminationResult。
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
    #   端成分 α/β は phase_ref を継承し共有する (改名しない): 二相反応の端成分は同一結晶構造の 2 格子で、
    #   phase_ref をキーに hkl/構造を引く backend (SimulatedBackend.hkl_table 等) が両端成分に正しい構造を
    #   割り当てるには ref 一致が必要。改名すると hkl 引きが既定 hkl へ落ちて Σbic_B が偏り verdict を歪める。🟡
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
    #   REQ-004「判別時マルチスタート必須」を両端点で満たすため start/end 両方で適用する。B の端成分格子は
    #   A 端点で既に固定済みのため、代表として end 端点結果のみ result へ格納する (start 側は必須適用の
    #   充足が目的で結果は保持しない)。🟡
    _, multistart_two_phase = _endpoint_multistarts(
        engine, two_theta, series, start, end, seq_b.endpoint_phases, _TWO_PHASE_REFINE_SUFFIXES
    )

    # ---- 判別: ΔBIC = Σbic_A − Σbic_B と両仮説高 R でエスカレーション判定 --------------------
    delta = seq_a.sum_bic - seq_b.sum_bic
    # 【全失敗判定】: 有限フレーム皆無 = その仮説は区間全域で精密化に失敗 (高 R とは区別すべき別事象) 🔵
    a_failed = len(seq_a.finite_frames) == 0
    b_failed = len(seq_b.finite_frames) == 0
    # 【両仮説高 R (EDGE-005)】: 両仮説とも「精密化は成立したが rwp が高い」ときのみ未知相を疑う。片仮説でも
    #   全失敗しているときは高 R でなく backend 失敗として比較可能性ガードで扱う (rwp=inf の誤ラベル回避)。🔵
    both_high_r = (
        not a_failed and not b_failed
        and seq_a.representative_rwp > config.high_r_threshold
        and seq_b.representative_rwp > config.high_r_threshold
    )
    # 【比較可能性ガード】: bic はフレームあたり chi2 + k·ln(n) >= 0 のため、非有限フレームを Σbic から除外
    #   するほど和が小さく (= 良く) なる。両仮説が「異なるフレーム部分集合」で Σbic を計上する (片仮説の失敗
    #   や食い違う発散) と、除外フレームの bic 分だけ ΔBIC が偏り誤確定しうる (CLAUDE.md「backend 失敗
    #   =chi2=inf」経路)。有限フレーム集合が両仮説で完全一致し双方非空のときのみ Σbic 比較を信頼する
    #   (件数一致は必要条件であって十分条件ではない / segmentation の全滅=inf と対称)。🔵
    #   【設計判断 (保守側)】: 単相 A が二相領域フレームで「発散 (chi2=inf)」すると集合不一致で undecided へ
    #   倒れ、two_phase を取り逃す過保護面がある。ただし発散 (inf) は数値破綻であり「モデル不適合」とは別事象で、
    #   二相の真のシグナルは A が当該フレームで「高いが有限な chi2」を返す形で現れ、それは Σbic に正しく計上
    #   されて two_phase 判別に効く。よって発散フレームは自動確定せず人間レビューへ回す保守側が Dara 教訓
    #   (過剰主張を避ける) に整合する。発散フレームへ有限ペナルティを与える Σbic 化 (交差集合比較) は M-later
    #   の精緻化候補 (ペナルティ量の仕様確定が要る)。🟡
    comparable = seq_a.finite_frames == seq_b.finite_frames and not a_failed
    verdict, escalations, queue_reason = _decide_verdict(
        delta, config.close_threshold, both_high_r,
        seq_a.representative_rwp, seq_b.representative_rwp,
        comparable=comparable,
        n_finite_single=len(seq_a.finite_frames),
        n_finite_two_phase=len(seq_b.finite_frames),
    )

    # ---- 両仮説 Hypothesis を metrics.multistart 付きで構築 (単一 basin でも付与) -----------
    #   両仮説の構築は id・区間結果・端点マルチスタートだけが異なる同形処理のため共通ヘルパへ集約する。
    #   nested 裁定 (下記) が仮説 id を EvidenceProblem のキーに用いるため、ここで先に構築する 🔵
    hyp_single = _build_endpoint_hypothesis(
        "discrimination-single", seq_a, multistart_single, start, end
    )
    hyp_two_phase = _build_endpoint_hypothesis(
        "discrimination-two-phase", seq_b, multistart_two_phase, start, end
    )

    # ---- FR-313/FR-122: 僅差競合のみ nested 裁定 (オプトイン・非僅差では絶対に呼ばない) ------------
    #   既存 close_competitor 判定 (queue_reason) を発動条件として再利用し、arbitrate 内部の rank()
    #   による close 再判定 (異なる閾値設定の可能性) には委ねない (要件2 / コスト抑制)。nested
    #   未導入/タイムアウトは run_with_fallback の既存フォールバック (Laplace 代替 + truncated 警告)
    #   に任せる。裁定実行そのものが例外で完全に失敗しても bic 一次の close_competitor エスカレー
    #   ションへ縮退し、判別処理は止めない (要件3/4)。
    adjudicated_by: Literal["bic", "nested", "laplace"] = "bic"
    nested_delta_evidence: float | None = None
    nested_arbitration_result: ArbitrationResult | None = None
    nested_warnings: tuple[str, ...] = ()
    if config.nested_arbitration is not None and queue_reason == "close_competitor":
        try:
            active_nested_backend = (
                nested_backend if nested_backend is not None else NestedBackend()
            )
            nested_outcome = _run_nested_arbitration(
                hyp_single, hyp_two_phase, seq_a, seq_b,
                config.close_threshold, config.nested_arbitration, active_nested_backend, ledger,
            )
        except Exception as exc:  # noqa: BLE001 【防御】: nested 裁定が完全不能でも判別を止めない
            nested_warnings = (
                f"discrimination nested_arbitration: 裁定実行が例外で失敗したため bic 一次の "
                f"close_competitor エスカレーションへ縮退しました ({exc!r})。",
            )
        else:
            adjudicated_by = nested_outcome.adjudicated_by
            nested_delta_evidence = nested_outcome.delta
            nested_arbitration_result = nested_outcome.result
            if nested_outcome.provisional_verdict != "undecided":
                # 【暫定裁定 (FR-403)】: nested/Laplace が僅差を解消できたら verdict を更新する。
                #   ReviewQueue への通知 (下記) は維持し「要確認フラグ」として人間に残す
                #   (処理はブロックしない・close_competitor エスカレーションは取り下げない)。
                verdict = nested_outcome.provisional_verdict
            escalations = escalations + (
                f"nested_arbitration: {adjudicated_by} 裁定 (ΔBIC_nested="
                f"{nested_delta_evidence:.4g}) により暫定 verdict={verdict} としました。"
                f"close_competitor のため引き続き人間の確認を要求します。",
            )

    # ---- ReviewQueue 通知 (提供時のみ・ブロックしない) -----------------------------------
    if queue is not None and queue_reason is not None:
        queue.add(queue_reason, detail=escalations[0] if escalations else "")

    # ---- 警告の集約 (発散除外/全滅縮退/nested 裁定失敗を判別結果へ伝播) --------------------
    warnings = (
        seq_a.warnings + seq_b.warnings
        + multistart_single.warnings + multistart_two_phase.warnings
        + nested_warnings
    )

    # ---- ledger 記録 (提供時のみ・"discrimination." 前置。nested 経路は arbitrate/nested 自身も追記) --
    _record(
        ledger, "discrimination.hypothesis_single",
        {"sum_bic": seq_a.sum_bic, "n_finite": len(seq_a.finite_frames)},
    )
    _record(
        ledger, "discrimination.hypothesis_two_phase",
        {"sum_bic": seq_b.sum_bic, "n_finite": len(seq_b.finite_frames)},
    )
    _record(ledger, "discrimination.verdict", {"verdict": verdict, "delta_evidence": delta})
    if escalations:
        _record(ledger, "discrimination.escalation", {"reasons": list(escalations)})
    if nested_arbitration_result is not None:
        _record(
            ledger, "discrimination.nested_arbitration",
            {
                "adjudicated_by": adjudicated_by,
                "nested_delta_evidence": nested_delta_evidence,
                "provisional_verdict": verdict,
                "nested_ids": list(nested_arbitration_result.nested_ids),
            },
        )

    return DiscriminationResult(
        verdict=verdict,
        delta_evidence=delta,
        hypothesis_single=hyp_single,
        hypothesis_two_phase=hyp_two_phase,
        multistart_single=multistart_single,
        multistart_two_phase=multistart_two_phase,
        escalations=escalations,
        warnings=warnings,
        adjudicated_by=adjudicated_by,
        nested_delta_evidence=nested_delta_evidence,
        nested_arbitration=nested_arbitration_result,
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
    finite_frames: set[int] = set()

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
            finite_frames.add(i)  # 【有限フレーム記録】: どのフレームが Σbic に寄与したかを集合で保持 🔵
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
        finite_frames=frozenset(finite_frames),
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
    *,
    comparable: bool,
    n_finite_single: int,
    n_finite_two_phase: int,
) -> tuple[Literal["solid_solution", "two_phase", "undecided"], tuple[str, ...], str | None]:
    """ΔBIC と両仮説高 R から verdict・エスカレーション文字列・Queue 通知 reason を決める。

    【実装方針】: (1) Σbic の比較可能性ガードを最優先で判定 (有限フレーム集合の不一致/皆無 → undecided +
      incomparable_evidence)。片仮説が一部フレームで発散し rwp も高い場合を「未知相 (高 R)」でなく
      「backend 失敗 (比較不能)」として正しくラベルするため both_high_r より先に置く。
      (2) 両仮説高 R (EDGE-005 / 両仮説が全フレーム有限だが rwp 高) → undecided + all_high_r、
      (3) ΔBIC ≤ −閾値 → solid_solution、(4) ΔBIC ≥ +閾値 → two_phase (いずれも閉境界 >=/<=)、
      (5) |ΔBIC| < 閾値 → 僅差 undecided + close_competitor。verdict Literal は 3 値のみのため両仮説高 R /
      比較不能の「判別しない」は undecided + エスカレーションで表現する (contract 整合)。
    【テスト対応】: TC-N01/N02 (明瞭判別・escalations 空) / TC-E01 (僅差) / TC-E02 (両仮説高 R) /
      TC-E05 (片仮説の部分/全失敗で Σbic 比較不能) / TC-BV01 (閉境界)。
    🟡 信頼性レベル: note.md §6-1/6-2 (verdict 符号規約・EDGE-005 表現) に依拠。比較可能性ガードは
      CLAUDE.md「backend 失敗=chi2=inf」不変条件 + segmentation の全滅=inf 対称から導出 🔵。

    @returns: (verdict, escalations タプル, Queue 通知 reason または None)。
    """
    # 【比較可能性ガード優先】: 有限フレーム集合が両仮説で食い違う/皆無だと、非有限フレーム除外が Σbic を
    #   不当に下げて誤確定を招く。両仮説高 R より先に判定し、部分失敗 (集合不一致) を高 R (未知相) と
    #   取り違えず「backend 失敗 (比較不能)」として正しくラベルする 🔵
    if not comparable:
        message = (
            f"incomparable_evidence: 両仮説の有限フレーム集合が一致しない、またはいずれかが皆無 "
            f"(single_finite={n_finite_single}, two_phase_finite={n_finite_two_phase}) のため Σbic 比較が "
            f"信頼できず判別を確定しません (backend の精密化失敗の疑い。除外フレームは warnings 参照)。"
        )
        return "undecided", (message,), "incomparable_evidence"

    # 【EDGE-005】: 両仮説とも全フレーム有限だが rwp が高い = 未知相の疑いで判別しない 🔵
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
    """釣り合いモデル DOF で bic を算出する (BICBackend へ委譲し bic 式を単一情報源化)。

    【機能概要】: BIC のペナルティ次数 k を、バックエンドが報告する実解放数ではなく設計モデル DOF で数える:
      活物質相は各 ``len(model_suffixes)`` 個、固定相は各 1 個 (scale のみ / fixed_free_suffixes) とする。
      k を n_params に載せた RefinementMetrics を組み ``BICBackend.score().value`` を返す (式は evidence/ic.py
      の単一実装、segmentation._frame_bic と同一パターン)。
    【実装方針】: 仮説 A (相あたり scale+格子 3 = 4) と 2 相 B (2 端成分 × (scale,wt) = 4) の複雑度を釣り合わせ、
      ΔBIC = Σbic_A − Σbic_B からペナルティ項を相殺させて判別を適合度 (chi2) ベースにする (設計の意図)。
      wt は参照バックエンドで不活性だが端成分分率という実モデル DOF のため evidence 上は 1 自由度と数える。
      gof は sequential/engine.py と同式で補完 (BICBackend は使わないが RefinementMetrics 契約を満たす)。
      有限 chi2 のフレームでのみ呼ばれる (呼び側が非有限を除外)。
    🔵 信頼性レベル: evidence/ic.py BICBackend (BIC = chi2 + k·ln(max(n_obs,1))) / note.md §6-2 に依拠。
    """
    n_fixed = max(len(result.phases) - active_count, 0)
    # 【モデル DOF】: 活物質は model_suffixes 個 / 固定相は scale の 1 個 (fixed_free_suffixes) 🔵
    k = active_count * len(model_suffixes) + n_fixed
    chi2 = float(result.chi2)
    dof = max(int(result.n_obs) - k, 1)
    gof = math.sqrt(chi2 / dof) if math.isfinite(chi2) and chi2 >= 0.0 else float("inf")
    metrics = RefinementMetrics(
        rwp=float(result.rwp), gof=gof, chi2=chi2, n_obs=int(result.n_obs), n_params=k
    )
    # 【単一情報源】: bic 式は BICBackend にのみ存在させ、ΔBIC 比較の一貫性を担保する 🔵
    return float(_BIC.score(metrics).value)


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


# ===========================================================================
# nested 裁定配線 (Issue #65 / FR-313 / FR-122)
# ===========================================================================


@dataclass(frozen=True)
class _NestedArbitrationOutcome:
    """close_competitor 2 仮説の nested 裁定 1 回分の内部結果束 (非公開・frozen)。

    【機能概要】: ``arbitrate`` の生結果 (``ArbitrationResult``)・nested/Laplace 裁定後の
      ΔBIC 相当 (single−two_phase)・統合 adjudicated_by・その ΔBIC から導いた暫定 verdict を束ねる。
    🟡 信頼性レベル: 実装裁量 (Issue #65 の要件3「裁定結果を判別結果に反映」を満たす内部表現)。
    """

    result: ArbitrationResult  # 【nested 裁定の生結果】: nested_ids・両仮説の再ランキングを保持
    delta: float  # 【ΔBIC(nested)】: single の evidence − two_phase の evidence (bic と同一符号規約)
    adjudicated_by: Literal["bic", "nested", "laplace"]  # 【裁定の由来 (両仮説で集約)】
    provisional_verdict: Literal["solid_solution", "two_phase", "undecided"]  # 【暫定 verdict】


def _build_evidence_problem(outcome: _IntervalOutcome, *, label: str) -> EvidenceProblem:
    """区間 Σbic から nested/Laplace 裁定用の ``EvidenceProblem`` を組む (M3-nested v1 サロゲート)。

    【機能概要】: ``outcome.sum_bic`` (モデル DOF 込みの区間 Σbic) を ``chi2``・``n_params=0``・
      ``n_obs=1`` の ``RefinementMetrics`` に載せ、``BICBackend``/``LaplaceBackend.score`` が
      Σbic をそのまま再現するようにする (map_point/hessian 無しの Laplace フォールバック経路で
      bic 一次判定と厳密に一致させる)。1 次元ダミー一様事前分布 + 定数対数尤度
      (``logL=-Σbic/2``, BIC の -2logL_max=Σbic 対応) の flat problem とし、実 nested サンプラでも
      評価可能にする。
    【制限 (v1)】: 実 nested サンプラ (単位一様事前分布 = 体積1・定数尤度) では
      -logZ=-logL=Σbic/2 となり、Laplace フォールバック (=Σbic そのもの) とスケールが factor-2 で
      異なりうる。restraint 由来の真の物理事前分布/尤度配線は M-later (discrimination には現状
      連続自由パラメータの事後分布が無いための暫定サロゲート)。
    🟡 信頼性レベル: 実装裁量 (nested/laplace 既存契約 ``EvidenceProblem`` への Σbic 写像)。
    """
    sum_bic = outcome.sum_bic
    is_finite = math.isfinite(sum_bic)
    metrics = RefinementMetrics(
        rwp=outcome.representative_rwp,
        gof=math.sqrt(sum_bic) if is_finite and sum_bic >= 0.0 else float("inf"),
        chi2=sum_bic,
        n_obs=1,
        n_params=0,
    )
    priors = (PriorSpec(param_name=f"discrimination.{label}.quality"),)

    def log_likelihood(theta: np.ndarray) -> float:
        # 【定数尤度サロゲート】: θ に依存せず Σbic の BIC 対応 logL_max=-Σbic/2 を返す (docstring 参照)。
        return -0.5 * sum_bic

    return EvidenceProblem(
        metrics=metrics, log_likelihood=log_likelihood, priors=priors, label=label
    )


def _nested_verdict_from_delta(
    delta: float, close_threshold: float
) -> Literal["solid_solution", "two_phase", "undecided"]:
    """nested/Laplace 裁定後の ΔBIC(nested) を discrimination 自身の close_threshold と比較する。

    【実装方針】: bic 一次判定 (``_decide_verdict``) と同一の閉境界規約 (>=/<=) を用いる。
      both_high_r / 比較可能性ガードは close_competitor 到達時点で既に確認済み (呼び側が保証) の
      ためここでは扱わない。
    🟡 信頼性レベル: _decide_verdict の閉境界規約を nested 裁定へ再利用する実装裁量。
    """
    if delta <= -close_threshold:
        return "solid_solution"
    if delta >= close_threshold:
        return "two_phase"
    return "undecided"


def _combine_adjudicated_by(
    single: Literal["bic", "nested", "laplace"], two_phase: Literal["bic", "nested", "laplace"]
) -> Literal["bic", "nested", "laplace"]:
    """両仮説の ``adjudicated_by`` を判別レベルの単一値へ集約する (保守側: 純 nested 以外は laplace)。

    ``_run_nested_arbitration`` は ``full_nested=True`` を強制し両仮説に必ず problem を供給するため、
    通常は両方とも "nested" か両方とも "laplace" に揃う。想定外の混在 (例: 片方のみ problem 欠損)
    は「nested で完全には裁定し切れなかった」ことを示すため、保守側に倒し "laplace" とする。
    🟡 信頼性レベル: 実装裁量 (REQ-015 の adjudicated_by 明示を 2 仮説の集約値として表現)。
    """
    if single == "nested" and two_phase == "nested":
        return "nested"
    return "laplace"


def _run_nested_arbitration(
    hyp_single: Hypothesis,
    hyp_two_phase: Hypothesis,
    seq_a: _IntervalOutcome,
    seq_b: _IntervalOutcome,
    close_threshold: float,
    arbitration_config: ArbitrationConfig,
    nested_backend: NestedBackend,
    ledger: Ledger | None,
) -> _NestedArbitrationOutcome:
    """close_competitor の 2 仮説 (A/B) のみを対象に nested/Laplace 裁定を実行する (FR-122/313)。

    【実装方針】: discrimination 側で既に close_competitor と判定済み (呼び側の発動条件) のため、
      ``arbitrate`` 内部の ``rank()`` ベース close 再判定 (``ArbitrationConfig.close_threshold`` が
      discrimination 側の ``close_threshold`` と異なる可能性がある) には委ねず、
      ``full_nested=True`` を強制して両仮説を確実に nested 裁定対象にする (要件2「既存
      close_competitor 判定の再利用」)。``ledger`` は ``arbitrate`` へそのまま渡し、
      "arbitration"/"nested_run"/"nested_fallback" 記録は既存契約に委ねる (呼び側が別途
      "discrimination.nested_arbitration" を追記する)。
    🟡 信頼性レベル: 実装裁量 (nested/arbitration.arbitrate 既存契約への配線)。

    @returns: nested 裁定の生結果・ΔBIC(nested)・集約 adjudicated_by・暫定 verdict を束ねた結果。
    """
    problems = {
        hyp_single.id: _build_evidence_problem(seq_a, label="single"),
        hyp_two_phase.id: _build_evidence_problem(seq_b, label="two_phase"),
    }
    # 【full_nested 強制】: close_threshold/temperature は呼び出し側設定を尊重しつつ、対象抽出だけを
    #   full_nested で上書きする 🟡
    effective_config = ArbitrationConfig(
        full_nested=True,
        close_threshold=arbitration_config.close_threshold,
        temperature=arbitration_config.temperature,
    )
    arb = arbitrate(
        (hyp_single, hyp_two_phase),
        problems=problems,
        nested=nested_backend,
        config=effective_config,
        ledger=ledger,
    )
    by_id = {a.ranked.hypothesis.id: a for a in arb.arbitrated}
    single_arb = by_id[hyp_single.id]
    two_phase_arb = by_id[hyp_two_phase.id]
    delta = single_arb.ranked.evidence.value - two_phase_arb.ranked.evidence.value
    adjudicated_by = _combine_adjudicated_by(single_arb.adjudicated_by, two_phase_arb.adjudicated_by)
    provisional_verdict = _nested_verdict_from_delta(delta, close_threshold)
    return _NestedArbitrationOutcome(
        result=arb, delta=delta, adjudicated_by=adjudicated_by,
        provisional_verdict=provisional_verdict,
    )
