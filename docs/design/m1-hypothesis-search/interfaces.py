"""m1-hypothesis-search 型定義 (設計文書)

作成日: 2026-07-03
関連設計: architecture.md
言語: Python 3.12 (frozen dataclass + Protocol — CLAUDE.md 規約)

信頼性レベル: 🔵 要件・仕様・M0 実装に依拠 / 🟡 妥当な推測 / 🔴 根拠なし推測
このファイルは設計時の契約書であり、実装は src/tsumugin/ 配下に置く。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

# M0 実装済み型 (再利用) 🔵
from tsumugin.backends.base import RefinementBackend, RefinementResult
from tsumugin.evidence.base import EvidenceBackend
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.model import Hypothesis, PhaseInstance
from tsumugin.refinement.staged import RefinementReport
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# ========================================
# search/peaks.py
# ========================================


@dataclass(frozen=True)
class Peak:
    """観測 or 計算ピーク。🔵 FR-111 のマッチング単位"""

    position: float  # 2θ (deg) 🔵
    height: float  # 強度 🔵


def find_peaks(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    min_height_frac: float = 0.05,  # 最大強度に対する検出下限 🟡 実装式は推測
) -> tuple[Peak, ...]:
    """局所極大 + 高さ閾値による観測ピーク検出。numpy のみ。🟡"""
    ...


# ========================================
# search/matcher.py
# ========================================


@dataclass(frozen=True)
class MatchResult:
    """1 候補相のマッチング結果。🔵 FR-111"""

    candidate_index: int  # 🔵
    score: float  # [0,1]。候補ピーク一致率と観測強度被覆率の等重み平均 🟡
    matched_observed: tuple[int, ...]  # マッチした観測ピーク index 🔵 FR-117 用
    unmatched_candidate: tuple[float, ...]  # 観測に無い計算ピーク位置 (extra) 🔵 FR-117


def match_score(
    candidate_peaks: Sequence[Peak],
    observed_peaks: Sequence[Peak],
    *,
    tol_deg: float = 0.15,  # 位置一致許容 (deg) 🟡
) -> MatchResult:
    ...


@dataclass(frozen=True)
class UnmatchedPeakReport:
    """未マッチピークの構造化出力。🔵 FR-117 (REQ-005)"""

    unmatched_observed: tuple[Peak, ...]  # どの仮説相でも説明できない観測ピーク 🔵
    extra_calculated: tuple[float, ...]  # 観測に現れない計算ピーク位置 🔵
    unknown_phase_flag: bool  # 🔵 FR-117/REQ-106


# ========================================
# search/pruning.py
# ========================================


def dynamic_threshold(
    scores: Sequence[float],
    *,
    min_candidates: int = 4,  # これ未満は枝刈り無効 🟡 interview Q8
) -> float:
    """スコア降順の累積分布の変曲点 (二階差分最大) で枝刈り閾値を返す。
    縮退時 (全同値等) は -inf (全展開)。🔵 FR-112 (実装式は 🟡)"""
    ...


# ========================================
# search/clustering.py
# ========================================


@dataclass(frozen=True)
class PhaseCandidate:
    """候補相 + 探索メタ。🔵 §4 / FR-114 (delta_u の M1 既定 0 は 🟡)"""

    phase: PhaseInstance  # 🔵
    delta_u: float = 0.0  # hull エネルギー ΔU (eV/atom)。M1 では常に 0 🟡
    label: str | None = None  # 🟡


@dataclass(frozen=True)
class ClusterResult:
    """等構造クラスタ。🔵 FR-114"""

    representative: int  # 代表候補 index (FoM 最大) 🔵
    members: tuple[int, ...]  # クラスタ全 index 🔵
    # 代表以外は代替解として保持 — 削除しない (REQ-103)


def jaccard_clusters(
    peak_sets: Sequence[Sequence[Peak]],
    fits: Sequence[float],
    delta_us: Sequence[float],
    *,
    similarity_threshold: float = 0.85,  # 🟡 実装時較正
    bin_width_deg: float = 0.2,  # ピーク位置の離散化幅 🟡
) -> tuple[ClusterResult, ...]:
    """ピーク位置集合の Jaccard 類似で候補をクラスタし FoM=1/((1-fit)+ΔU) で代表選出。🔵"""
    ...


def jenks_breaks(values: Sequence[float], *, n_classes: int = 2) -> tuple[float, ...]:
    """1 次元 Jenks natural breaks の境界値を返す (DP 実装, numpy)。🔵 FR-116"""
    ...


# ========================================
# search/tree.py
# ========================================


@dataclass(frozen=True)
class SearchConfig:
    """木探索設定。既定値は仕様の既定に一致させる。"""

    max_phases: int = 5  # 🔵 FR-115
    r_improve_pct: float = 2.0  # Rwp 改善打ち切り閾値 (ポイント) 🔵 FR-115 (絶対点解釈は 🟡)
    match_tol_deg: float = 0.15  # 🟡
    min_peak_height_frac: float = 0.05  # 🟡
    prune_min_candidates: int = 4  # 🟡
    jaccard_threshold: float = 0.85  # 🟡
    explore_max_cycles: int = 5  # 🔵 FR-113 保守的設定 (値は 🟡)
    final_full_refine: bool = True  # 良好解の段階フル精密化 🟡 D3
    max_final_refine: int = 3  # 🟡
    high_r_threshold: float = 30.0  # 全仮説高 R 判定 (Rwp%) 🟡 REQ-106
    close_threshold: float = 10.0  # ΔBIC 僅差競合 🔵 FR-122


@dataclass(frozen=True)
class SearchResult:
    """木探索の出力。🔵 REQ-001/005/202/402"""

    ranked: tuple[RankedHypothesis, ...]  # refined のみ、良い順 🔵
    hypotheses: Mapping[str, Hypothesis]  # 全評価ノード (parent_id で系譜) 🔵
    good_cluster_ids: tuple[str, ...]  # Jenks 良好クラスタ 🔵 FR-116
    alternatives: Mapping[int, tuple[int, ...]]  # 代表候補idx -> 代替候補idx 🔵 FR-114
    unmatched: UnmatchedPeakReport  # 🔵 FR-117
    final_reports: Mapping[str, RefinementReport]  # フル精密化した仮説のみ 🟡 D3
    ledger: Ledger  # 🔵 REQ-402
    snapshots: SnapshotStore  # 🔵
    warnings: tuple[str, ...] = ()  # EDGE-003 等 🟡

    def to_summary(self) -> dict:
        """Web UI / JSON 出力用の純 dict。🟡 D6"""
        ...


class HypothesisTreeSearch:
    """多仮説木探索エンジン。🔵 FR-110"""

    def __init__(
        self,
        backend: RefinementBackend,
        *,
        evidence: EvidenceBackend | None = None,  # 既定 BICBackend 🔵 FR-121
        config: SearchConfig = SearchConfig(),
        ledger: Ledger | None = None,
        snapshots: SnapshotStore | None = None,
    ) -> None: ...

    def search(
        self,
        two_theta: np.ndarray,
        intensity: np.ndarray,
        candidates: Sequence[PhaseCandidate | PhaseInstance],
        *,
        weights: np.ndarray | None = None,
    ) -> SearchResult: ...


# ========================================
# export/gpx.py
# ========================================


def export_gpx(
    path: str,  # 出力 .gpx パス 🔵 FR-505
    phases: Sequence[PhaseInstance],
    two_theta: np.ndarray,
    intensity: np.ndarray,
    *,
    weights: np.ndarray | None = None,
    wavelength: float = 1.5406,  # 🔵 M0 GSASIIBackend と同一既定
) -> str:
    """GSAS-II GUI で開ける .gpx を書き出しパスを返す。
    未導入環境では GSASUnavailableError。🔵 REQ-006/105"""
    ...


# ========================================
# webui/app.py (optional extra `web`)
# ========================================


def create_app(result: "SearchResult"):  # -> fastapi.FastAPI 🟡 D6
    """read-only アプリ。GET / (HTML), GET /api/result, GET /api/hypotheses/{id} のみ。"""
    ...


def serve(result: "SearchResult", *, host: str = "127.0.0.1", port: int = 8765) -> None:
    """uvicorn でローカル配信。🟡 NFR-101"""
    ...


# ========================================
# 信頼性レベルサマリー
# ========================================
# 🔵: 24 / 🟡: 16 / 🔴: 0 — 品質評価: 高品質
# (推測はチューニング既定値と Web UI 詳細に集中。要件への遡及リンクを各所に記載)
