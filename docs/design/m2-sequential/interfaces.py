"""m2-sequential 型定義 (設計文書)

作成日: 2026-07-03 / 関連設計: architecture.md
言語: Python 3.12 (frozen dataclass + Protocol — CLAUDE.md 規約)
信頼性レベル: 🔵 要件・仕様・M0/M1 実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測
このファイルは設計時の契約書。実装は src/tsumugin/ 配下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Sequence

import numpy as np

# M0/M1 実装済み型 (再利用) 🔵
from tsumugin.backends.base import RefinementBackend
from tsumugin.evidence.base import EvidenceBackend
from tsumugin.model import Hypothesis, PhaseInstance, RefinementMetrics
from tsumugin.refinement.staged import RefinementReport
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.search.tree import SearchConfig, SearchResult
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# ========================================
# model 拡張 (REQ-404: 全て既定値付き非破壊追加)
# ========================================


@dataclass(frozen=True)
class PhaseLifecycle:
    """相ライフサイクル。🔵 §4 PhaseInstance.lifecycle / FR-305"""

    birth_frame: int | None = None  # 🔵
    death_frame: int | None = None  # 🔵
    confidence: float = 1.0  # 存在確信度 [0,1] 🔵 (算出式は 🟡: 存在フレーム率)


# PhaseInstance に追加: lifecycle: PhaseLifecycle | None = None 🔵
# Hypothesis に追加: frame_range: tuple[int, int] | None = None 🔵


@dataclass(frozen=True)
class ExternalChannel:
    """外部チャネル同期。🔵 §4 ExternalChannel (M2 は temperature 中心)"""

    kind: Literal["temperature", "time", "pressure", "custom"]  # echem は M3 🔵
    sync_map: Mapping[int, float]  # frame_index -> value 🔵
    label: str | None = None  # 🟡

    def value_for(self, frame_index: int) -> float | None:
        """欠損フレームは None (EDGE-102、例外にしない)。🟡"""
        ...


# ========================================
# sequential/series.py
# ========================================


@dataclass(frozen=True)
class FrameSeries:
    """シーケンシャル入力。🟡 D-Q2 (Dataset/HistogramRef 接続は M3 FR-501 で)"""

    two_theta: np.ndarray  # 共通グリッド (n_points,) 🔵
    intensities: np.ndarray  # (n_frames, n_points) 🟡
    axis_values: tuple[float, ...] = ()  # フレーム軸値 (空なら index) 🔵 §4 sequence_axis
    axis_kind: Literal["time", "temperature", "index", "custom"] = "index"  # 🔵
    channels: tuple[ExternalChannel, ...] = ()  # 🔵 REQ-006

    @property
    def n_frames(self) -> int: ...


# ========================================
# sequential/changepoint.py
# ========================================


@dataclass(frozen=True)
class ChangepointConfig:
    """複合指標の設定。🔵 FR-303 (値は 🟡 interview Q5)"""

    window: int = 5  # ローリング窓 🟡
    z_threshold: float = 5.0  # ロバスト z 閾値 🟡
    min_new_peaks: int = 1  # 新規未マッチピークの下限 🟡


@dataclass(frozen=True)
class ChangepointSignal:
    """1 フレームの検出結果 (どの指標が発火したか)。🔵 FR-303/REQ-402 説明可能性"""

    frame_index: int
    triggered: bool
    z_rwp: float
    z_lattice: float
    new_unmatched: int
    reasons: tuple[str, ...]  # "rwp_jump"|"lattice_jump"|"new_peaks" 🔵


def detect_changepoint(
    rwp_history: Sequence[float],
    lattice_history: Sequence[Mapping[str, float]],
    new_unmatched: int,
    *,
    config: ChangepointConfig = ChangepointConfig(),
) -> ChangepointSignal:
    """直近窓のロバスト統計 (中央値/MAD) に対する現フレームの逸脱判定。純関数・決定論。🟡"""
    ...


# ========================================
# sequential/lifecycle.py
# ========================================


@dataclass(frozen=True)
class LifecycleConfig:
    hysteresis: int = 3  # 連続 N フレームで birth/death 確定 🔵 FR-305 (N は 🟡)
    presence_wt_frac: float = 1e-3  # 存在判定の下限 🟡


class LifecycleTracker:
    """相ごとの出現/消滅をヒステリシス付きで追跡する (REQ-004/201)。🔵

    observe(frame_index, present_refs) を毎フレーム呼び、finalize() で
    {phase_ref: PhaseLifecycle} を返す。death 後の窓内再出現は連続扱い。
    """

    def __init__(self, *, config: LifecycleConfig = LifecycleConfig()) -> None: ...
    def observe(self, frame_index: int, present_refs: Sequence[str]) -> None: ...
    def finalize(self) -> Mapping[str, PhaseLifecycle]: ...


# ========================================
# sequential/trajectory.py
# ========================================


@dataclass(frozen=True)
class FrameRecord:
    """トラジェクトリ 1 行。🔵 FR-306/REQ-005"""

    frame_index: int
    axis_value: float | None
    temperature: float | None  # channel 由来 (なければ None) 🔵
    phases: tuple[PhaseInstance, ...]  # 当該フレームの確定 phases 🔵
    rwp: float | None  # 失敗フレームは None (非有限を漏らさない) 🔵 M1 教訓
    chi2: float | None
    changepoint: bool
    changepoint_reasons: tuple[str, ...]
    refine_failed: bool  # EDGE-002 🟡


@dataclass(frozen=True)
class Trajectory:
    """時系列出力。🔵 FR-306"""

    records: tuple[FrameRecord, ...]
    lifecycles: Mapping[str, PhaseLifecycle]

    def to_csv(self, path: str) -> str:
        """stdlib csv で書き出しパスを返す。非有限値は空欄。🔵 REQ-005/TC-104-03"""
        ...


# ========================================
# sequential/thermal.py
# ========================================


@dataclass(frozen=True)
class ThermalBaseline:
    """格子 vs T の多項式ベースライン。🔵 FR-322 (次数既定 1 は 🟡)"""

    parameter: str  # "lattice.a" 等
    coefficients: tuple[float, ...]  # 低次から 🟡
    residuals: tuple[float, ...]
    outlier_frames: tuple[int, ...]  # ベースライン逸脱 (転移候補) 🔵


@dataclass(frozen=True)
class TransitionEstimate:
    """転移温度推定。🔵 FR-323"""

    phase_ref: str
    onset: float | None  # 10% 交差 🟡 interview Q6
    midpoint: float | None  # 50% 交差の線形補間 🟡
    sigma: float | None  # 隣接フレーム間隔ベース 🟡
    direction: Literal["appearing", "disappearing"]  # 🟡


def fit_thermal_baseline(
    temperatures: Sequence[float], values: Sequence[float], *, degree: int = 1
) -> ThermalBaseline: ...


def estimate_transition(
    temperatures: Sequence[float], fractions: Sequence[float], *, phase_ref: str
) -> TransitionEstimate | None:
    """遷移が無い場合は None。決定論 (補間ベース)。🔵 FR-323"""
    ...


# ========================================
# sequential/engine.py
# ========================================


@dataclass(frozen=True)
class SequentialConfig:
    """逐次エンジン設定。既定は仕様の既定に一致。"""

    orchestration: Literal["independent", "native"] = "independent"  # 🔵 FR-302 (native は M-later)
    inherit: Literal["phases", "lattice_only"] = "phases"  # warm start 継承対象 🔵 FR-301 (選択肢 🟡)
    seq_max_cycles: int = 10  # 後続フレームの精密化サイクル 🟡 D2
    first_frame_staged: bool = True  # 初回フレームのフル確立 🟡 D2
    changepoint: ChangepointConfig = ChangepointConfig()  # 🔵
    lifecycle: LifecycleConfig = LifecycleConfig()  # 🔵
    search: SearchConfig = SearchConfig()  # 局所木探索設定 🔵 REQ-101


@dataclass(frozen=True)
class SequentialResult:
    """シーケンシャル解析の出力。🔵 REQ-001/005"""

    trajectory: Trajectory
    hypotheses: Mapping[str, Hypothesis]  # 採択構成の系譜 (frame_range 付き) 🔵
    search_results: Mapping[int, SearchResult]  # changepoint フレームの局所探索結果 🔵
    first_frame_report: RefinementReport | None  # 🟡 D2
    ledger: Ledger
    snapshots: SnapshotStore
    warnings: tuple[str, ...] = ()


class SequentialEngine:
    """時系列逐次精密化エンジン。🔵 FR-301〜306"""

    def __init__(
        self,
        backend: RefinementBackend,
        *,
        candidates: Sequence[PhaseCandidate | PhaseInstance] = (),  # 局所探索プール 🔵 REQ-101
        evidence: EvidenceBackend | None = None,  # 既定 BIC 🔵
        config: SequentialConfig = SequentialConfig(),
        ledger: Ledger | None = None,  # Persistent 版を注入可能 🔵 REQ-012
        snapshots: SnapshotStore | None = None,
    ) -> None: ...

    def run(
        self, series: FrameSeries, initial_phases: Sequence[PhaseInstance]
    ) -> SequentialResult: ...


# ========================================
# store/serialization.py + store/persistent.py
# ========================================


def phase_to_dict(phase: PhaseInstance) -> dict: ...  # 🟡 JSON 可換
def phase_from_dict(data: Mapping) -> PhaseInstance: ...  # 🟡 roundtrip 保証


class LedgerIntegrityError(Exception):  # 実装では TsumuginError 派生 🔵 EDGE-003
    """永続 ledger の破損 (ハッシュ不整合) を検出。修復・上書きはしない。"""


class PersistentLedger:
    """Ledger と同一契約の JSONL 永続版。🔵 REQ-010/012/401

    - __init__(path): 既存ファイルを読込み全チェーン検証 (破損で LedgerIntegrityError)
    - append/entries/verify: in-memory 版と同一意味論。append は 1 行追記 ("a" のみ)
    - 削除・上書き API は実装しない (P2)
    """

    def __init__(self, path: str) -> None: ...
    def append(self, kind: str, payload: Mapping) -> object: ...
    @property
    def entries(self) -> tuple: ...
    def verify(self) -> bool: ...


class PersistentSnapshotStore:
    """SnapshotStore と同一契約の JSONL 永続版。🔵 REQ-011/012/401"""

    def __init__(self, path: str, ledger: Ledger | None = None) -> None: ...
    def save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> object: ...
    def load(self, snapshot_id: str) -> object: ...
    def revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]: ...
    @property
    def snapshots(self) -> tuple: ...


# ========================================
# selection/review_queue.py + selection/engine.py
# ========================================

EscalationReason = Literal[
    "all_high_r", "unknown_phase", "close_competitor", "guard_escalated"
]  # 🔵 FR-403 (M2 で利用可能な 4 条件。吸収補正は M3)


@dataclass(frozen=True)
class ReviewItem:
    """Review Queue の 1 件。🔵 FR-403/REQ-015"""

    item_id: str  # "rq-0000" 連番 🟡
    reason: EscalationReason
    hypothesis_id: str | None
    frame_index: int | None
    detail: str
    resolved: bool = False  # resolve は追記で表現 🔵 P2


class ReviewQueue:
    """追記型キュー。削除 API なし。🔵 FR-403/P2"""

    def __init__(self, ledger: Ledger | None = None) -> None: ...
    def add(self, reason: EscalationReason, *, hypothesis_id=None, frame_index=None, detail="") -> ReviewItem: ...
    def resolve(self, item_id: str, *, note: str = "") -> ReviewItem: ...  # 解決マーク追記 🔵
    @property
    def items(self) -> tuple[ReviewItem, ...]: ...
    @property
    def unresolved(self) -> tuple[ReviewItem, ...]: ...


@dataclass(frozen=True)
class Decision:
    """1 回の裁定結果。🔵 FR-402"""

    mode: Literal["agent", "human"]
    accepted: Hypothesis | None  # accepted 化された新インスタンス 🔵
    provisional_id: str | None  # 暫定裁定 (agent+エスカレーション時) 🔵 FR-403
    recommended_id: str | None  # human モードの推奨 🔵
    escalations: tuple[EscalationReason, ...]
    rationale: str  # 自然言語 + 定量根拠 🔵 FR-402


def detect_escalations(
    result: SearchResult, *, staged_escalated: bool = False, high_r_threshold: float = 30.0
) -> tuple[EscalationReason, ...]: ...  # 🔵 D6 純粋関数


class FinalSelectionEngine:
    """最終選択 2 モード。🔵 FR-402/403"""

    def __init__(
        self,
        *,
        mode: Literal["agent", "human"] = "agent",
        ledger: Ledger | None = None,
        queue: ReviewQueue | None = None,
    ) -> None: ...

    def set_mode(self, mode: Literal["agent", "human"]) -> None: ...  # ledger 記録 🔵 REQ-104
    def decide(self, result: SearchResult, *, frame_index: int | None = None) -> Decision: ...
    def accept(self, result: SearchResult, hypothesis_id: str, *, by: Literal["agent", "human"]) -> Hypothesis: ...
    def revert(self, hypothesis_id: str, *, note: str = "") -> Hypothesis: ...  # superseded 化 🔵 REQ-202
    @property
    def accepted(self) -> Mapping[str, Hypothesis]: ...  # 裁定レジストリ (追記のみ) 🔵


# ========================================
# 信頼性レベルサマリー
# ========================================
# 🔵: 38 / 🟡: 21 / 🔴: 0 — 品質評価: 高品質
# (🟡 はチューニング既定値・入力界面・シリアライズ詳細に集中。要件へ遡及可能)
