"""相ライブラリ / 相同定の data model (仕様 §5 FR-100/117)。

未知パターンの相同定に使う不変値オブジェクト群を定義する。参照相 (``ReferencePhase``) は
自前のシミュレートピーク列を持ち、既存 ``PhaseInstance`` (格子 + 占有率のみ) には手を入れない。
すべて frozen dataclass で、numpy にも GSAS-II にも依存しない (NFR-102 決定論の器)。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..search.matcher import UnmatchedPeakReport
from ..search.peaks import Peak


@dataclass(frozen=True)
class ReferencePhase:
    """相ライブラリの 1 候補相。🔵 FR-100/105

    実構造から生成したシミュレートピーク列 (``peaks``) を保持する。強度計算源 (pymatgen
    XRDCalculator / GSAS-II 等) に依らず、``Peak.height`` は相対強度を表す。``energy_above_hull``
    が ``None`` の相は MP 未登録 / 不明を意味し、hull フィルタ (FR-103) で除外されない。
    """

    phase_id: str  # 相 ID (例 "mp-19017")。ランキング同点時の決定論的タイブレークキー 🔵
    formula: str  # 組成式 (例 "LiFePO4") 🔵
    element_system: tuple[str, ...]  # 構成元素 (昇順を想定)。元素系フィルタの単位 🔵
    peaks: tuple[Peak, ...]  # シミュレートピーク列 (2θ + 相対強度)。位置昇順を想定 🔵
    spacegroup: str | None = None  # 空間群記号。不明は None 🟡
    energy_above_hull: float | None = None  # hull 上エネルギー (eV/atom)。None=未登録/保持 🔵


@dataclass(frozen=True)
class PhaseMatch:
    """1 参照相の観測パターンへのマッチ結果。🔵 FR-111/114"""

    reference: ReferencePhase  # マッチ対象の参照相 🔵
    score: float  # [0,1]。``match_score`` の一致率 + 被覆率の等重み平均 🔵
    matched_observed: tuple[int, ...]  # マッチした観測ピーク index (昇順) 🔵
    extra_calculated: tuple[float, ...]  # 観測に無い計算ピーク位置 (昇順) 🔵 FR-117


@dataclass(frozen=True)
class PhaseIdentification:
    """相同定の結果 (ランキング + 未知相レポート + 観測ピーク)。🔵 FR-110/117"""

    matches: tuple[PhaseMatch, ...]  # score 降順・同点 phase_id 昇順 🔵
    unmatched: UnmatchedPeakReport  # 全生存候補で説明できない観測 + 未知相フラグ 🔵 FR-117
    observed_peaks: tuple[Peak, ...]  # 検出した観測ピーク (位置昇順) 🔵
