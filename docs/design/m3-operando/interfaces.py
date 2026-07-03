"""m3-operando 型定義 (設計文書)

作成日: 2026-07-03 / 関連設計: architecture.md
言語: Python 3.12 (frozen dataclass + Protocol — CLAUDE.md 規約)
信頼性レベル: 🔵 要件・仕様・M0〜M2 実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測
このファイルは設計時の契約書。実装は src/tsumugin/ 配下。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping, Protocol, Sequence

import numpy as np

# M0〜M2 実装済み型 (再利用) 🔵
from tsumugin.backends.base import RefinementBackend, RefinementResult
from tsumugin.model import Hypothesis, PhaseInstance
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.sequential.series import FrameSeries
from tsumugin.selection.review_queue import ReviewQueue
from tsumugin.store.ledger import Ledger

# ========================================
# _json.py (Issue #5)
# ========================================


def finite_or_none(value: float | None) -> float | None:
    """非有限 (inf/NaN)/None を None へ純化する共有ユーティリティ。🔵 Issue #5
    tree.py (センチネル処理は tree 側に残す)・webui・serialization が委譲。挙動不変。"""
    ...


# ========================================
# model/cell.py (REQ-016, §4 CellConfig)
# ========================================


@dataclass(frozen=True)
class CellLayer:
    """セル構成 1 層。🔵 §4"""

    role: Literal["window", "electrode", "electrolyte", "separator", "collector"]
    material: str  # 組成式 or 物質名 🔵
    thickness_mm: float
    density: float | None = None  # g/cm3 🟡


@dataclass(frozen=True)
class BeamConfig:
    """ビーム条件。🔵 §4 (energy か wavelength の一方必須は 🟡)"""

    wavelength: float | None = None  # Å
    energy_kev: float | None = None
    size_mm: tuple[float, float] | None = None


@dataclass(frozen=True)
class CellConfig:
    """セル構成。層状セルは透過法のみ (v0.3 確定)。🔵 §4/FR-317"""

    geometry: Literal["transmission", "capillary"]
    layers: tuple[CellLayer, ...] = ()
    beam: BeamConfig | None = None
    mu_t_calc: float | None = None  # 組成計算済み μt (MuCalculator or 手入力) 🟡 D8


class MuCalculator(Protocol):
    """組成→μt のエネルギー依存計算 (xraylib 等)。M3 は Protocol のみ。🔵 REQ-019"""

    def mu_t(self, config: CellConfig) -> float: ...


class XraylibMuCalculator:
    """xraylib 連携の実装予定スタブ。M3 では NotImplementedError。🔵 REQ-019"""


# ========================================
# model 拡張 (非破壊)
# ========================================

# ExternalChannel.kind に追加 (Literal 拡張・後方互換 🟡 D-Q4):
#   "voltage" | "current" | "capacity" | "composition"
# RefinementMetrics に追加 (既定 None 🔵 REQ-006/§4):
#   multistart: Mapping[str, int] | None = None   # {"n": 8, "n_basins": 1, "n_diverged": 0}


# ========================================
# backends 拡張 (D8, 非破壊)
# ========================================

# parse_param("global.mu_t") -> (-1, "mu_t") を追加 (既存 "phase{i}.*" は不変) 🔵 D8
# RefinementResult に追加: globals: Mapping[str, float] = {}  (fitted μt 等) 🔵 D8


@dataclass(frozen=True)
class AbsorptionConfig:
    """透過吸収補正 v1。🔵 FR-317/D8"""

    mu_t_initial: float = 0.0  # 初期実効 μt 🔵
    mu_t_calc: float | None = None  # restraint 中心 (CellConfig 由来 or None=経験推定) 🔵
    restraint_weight: float = 100.0  # w_r。経験推定モードでは弱 (既定 1.0) 🟡
    empirical_mode: bool = False  # CellConfig 未提供 (警告出力) 🔵 REQ-018

    @staticmethod
    def from_cell_config(config: CellConfig) -> "AbsorptionConfig": ...  # 🔵
    @staticmethod
    def empirical() -> "AbsorptionConfig": ...  # 弱 restraint + empirical_mode 🔵


def transmission_factor(two_theta_deg: np.ndarray, mu_t: float) -> np.ndarray:
    """平板透過の吸収因子 A(θ; μt) = exp(-μt / cos θ)。μt=0 で 1。🟡 D8 (式形)"""
    ...


# SimulatedBackend.__init__(..., absorption: AbsorptionConfig | None = None) 🔵 D8
#   simulate: I × transmission_factor / refine: "global.mu_t" 認識 + restraint ペナルティ


# ========================================
# multistart/ (FR-230〜234)
# ========================================


@dataclass(frozen=True)
class PerturbationSpec:
    """決定論摂動幅。🔵 FR-231 (幅の既定は 🟡)"""

    lattice_frac: float = 0.02  # 格子 ±2% 🟡
    scale_log_range: float = 0.5  # log10 スケール幅 🟡
    occupancy_delta: float = 0.1  # LHS 幅 🟡


@dataclass(frozen=True)
class MultistartConfig:
    n_starts: int = 8  # 🔵 FR-231 (8-16)
    spec: PerturbationSpec = PerturbationSpec()
    basin_rel_tol: float = 1e-2  # 正規化距離閾値 🟡 D3
    ms_max_cycles: int = 15  # 🟡 D2


@dataclass(frozen=True)
class BasinInfo:
    """1 つの basin。🔵 FR-232"""

    representative: RefinementResult  # chi2 最小解 🔵
    member_starts: tuple[int, ...]  # start index 群 🔵
    chi2: float
    evidence: float  # bic 🔵


@dataclass(frozen=True)
class MultistartResult:
    """マルチスタート実行結果。🔵 FR-232/REQ-102"""

    basins: tuple[BasinInfo, ...]  # evidence 昇順 🔵
    n_starts: int
    n_diverged: int  # 除外数 🟡
    promoted: tuple[Hypothesis, ...]  # 複数 basin 時の昇格仮説 (単一なら空) 🔵
    is_global_corroborated: bool  # n_basins==1 🔵
    warnings: tuple[str, ...] = ()


def generate_starts(
    phases: tuple[PhaseInstance, ...], *, config: MultistartConfig
) -> tuple[tuple[PhaseInstance, ...], ...]:
    """start index ごとの決定論摂動 phases 列 (i=0 は無摂動)。🔵 D1"""
    ...


class MultistartEngine:
    """N 本独立精密化 + basin クラスタ。🔵 FR-230"""

    def __init__(
        self,
        backend: RefinementBackend,
        *,
        config: MultistartConfig = MultistartConfig(),
        ledger: Ledger | None = None,
    ) -> None: ...

    def run(
        self,
        phases: tuple[PhaseInstance, ...],
        two_theta: np.ndarray,
        intensity: np.ndarray,
        *,
        free_suffixes: tuple[str, ...] = ("scale", "lattice.a", "lattice.b", "lattice.c"),
        weights: np.ndarray | None = None,
    ) -> MultistartResult: ...


# ========================================
# operando/echem.py (FR-311)
# ========================================


@dataclass(frozen=True)
class EchemData:
    """フレーム同期済み電気化学量。欠損は None。🔵 FR-311/§4"""

    voltage: tuple[float | None, ...]
    current: tuple[float | None, ...] = ()
    capacity: tuple[float | None, ...] = ()
    composition_x: tuple[float | None, ...] = ()  # 換算済み x 🔵

    def to_channels(self) -> tuple: ...  # ExternalChannel 群へ 🟡


def read_echem_csv(
    path: str,
    *,
    column_map: Mapping[str, str],  # {"frame": "index", "voltage": "Ewe/V", ...} 🔵
    capacity_to_x: tuple[float, float] | None = None,  # (slope, intercept): x = a·Q + b 🔵
) -> EchemData:
    """stdlib csv。列欠損は列名を示す ValueError、行数不一致は None+警告。🔵 REQ-007/EDGE-003"""
    ...


class EchemLoader(Protocol):
    """機種別ローダの交換境界。🔵 REQ-008"""

    def load(self, path: str) -> EchemData: ...


class BiologicMprLoader:
    """Biologic .mpr。M3 では NotImplementedError。🔵 REQ-008"""


# ========================================
# operando/cell_phases.py (FR-312)
# ========================================


@dataclass(frozen=True)
class FixedPhaseSpec:
    """セル固定相: 構造固定・scale のみ解放・探索常駐。🔵 FR-312 (粒度は 🟡 Q5)"""

    phase: PhaseInstance
    label: str


CELL_PHASE_PRESETS: Mapping[str, FixedPhaseSpec]  # "Be" | "Al" | "graphite" 🔵 (格子値 🟡)


# ========================================
# operando/discrimination.py (FR-313)
# ========================================


@dataclass(frozen=True)
class DiscriminationConfig:
    close_threshold: float = 10.0  # ΔBIC 🔵 FR-122
    multistart: MultistartConfig = MultistartConfig()  # 必須適用 🔵 FR-233
    high_r_threshold: float = 30.0  # 🟡
    seq_max_cycles: int = 10  # 区間内逐次 refine 🟡


@dataclass(frozen=True)
class DiscriminationResult:
    """FR-313 判別結果。🔵"""

    verdict: Literal["solid_solution", "two_phase", "undecided"]
    delta_evidence: float  # bic_A - bic_B 🔵
    hypothesis_single: Hypothesis  # 仮説A (multistart 記録付き) 🔵
    hypothesis_two_phase: Hypothesis  # 仮説B 🔵
    multistart_single: MultistartResult
    multistart_two_phase: MultistartResult
    escalations: tuple[str, ...]  # 僅差/高R 🔵 REQ-101/EDGE-005
    warnings: tuple[str, ...] = ()


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
) -> DiscriminationResult: ...


# ========================================
# operando/segmentation.py (FR-316)
# ========================================


@dataclass(frozen=True)
class SegmentationConfig:
    penalty_beta: float = 5.0  # β·境界数·ln(n_frames) 🔵 FR-316 (β は 🟡 較正)
    improvement_threshold: float = 10.0  # 打ち切り 🔵 §15-1
    coarse_step: int = 5  # 粗グリッド G 🟡
    max_segments: int = 6  # 安全上限 🟡
    seq_max_cycles: int = 10  # 🟡


@dataclass(frozen=True)
class SegmentationResult:
    """FR-316 分割結果。🔵"""

    boundaries: tuple[int, ...]  # 採択境界 (フレーム index、昇順) 🔵
    n_segments: int
    evidence_by_k: Mapping[int, float]  # k -> 合計コスト 🔵
    partitions: tuple[Hypothesis, ...]  # 各 k の分割仮説 (代替閲覧) 🔵 REQ-014
    ledger: Ledger
    warnings: tuple[str, ...] = ()


def segment_series(
    backend: RefinementBackend,
    series: FrameSeries,
    initial_phases: tuple[PhaseInstance, ...],
    *,
    config: SegmentationConfig = SegmentationConfig(),
    fixed_phases: tuple[FixedPhaseSpec, ...] = (),
    ledger: Ledger | None = None,
) -> SegmentationResult: ...


# ========================================
# operando/hysteresis.py (FR-315) / output.py (FR-314)
# ========================================


@dataclass(frozen=True)
class BranchComparison:
    """同一 x での充電/放電枝差分。片枝欠損は None。🟡 FR-315"""

    x: float
    charge_value: float | None
    discharge_value: float | None
    difference: float | None


def split_branches(x_values: Sequence[float | None]) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """dx 符号で充電枝/放電枝の frame index を分離。🟡 REQ-104"""
    ...


def branch_differences(
    x_values: Sequence[float | None], values: Sequence[float | None], *, n_grid: int = 20
) -> tuple[BranchComparison, ...]: ...


def combined_csv(trajectory, echem: EchemData, path: str) -> str:
    """trajectory + echem 列 (V/I/Q/x) を frame_index で結合して CSV 出力。🟡 D9"""
    ...


@dataclass(frozen=True)
class TransitionPoint:
    """転移点の電気化学量表現。🔵 FR-314"""

    frame_index: int
    x: float | None
    voltage: float | None
    sigma_x: float | None
    sigma_v: float | None


# ========================================
# sequential 拡張 (Issue #3/#4)
# ========================================

# ChangepointConfig に追加 (既定値付き非破壊 🔵 Issue #3):
#   new_peak_min_height_frac: float = 0.05
#   new_peak_persistence: int = 2   # 連続 M フレームで発火
# estimate_transition (Issue #4 🔵):
#   disappearing の onset = 90% 交差 (遷移開始側)。direction 不変。


# ========================================
# 信頼性レベルサマリー
# ========================================
# 🔵: 42 / 🟡: 24 / 🔴: 0 — 品質評価: 高品質
# (🟡 は摂動幅・閾値等のチューニング既定値と出力詳細に集中。要件へ遡及可能)
