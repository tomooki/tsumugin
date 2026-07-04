"""ヒストグラム重み方式 (REQ-008/009/301 / interfaces.py joint/weights 節)。

既定は統計重み (全ヒスト 1.0・σ は covariance 由来)、経験重みはオプションで
``empirical_weights`` により該当 index を上書きする。``resolve`` は必ず入力ヒスト順
(index 昇順) のタプルを返し、``dict`` 反復順に依存しない決定論を保証する (NFR-102/REQ-402)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .model import JointRefinementModel


@dataclass(frozen=True)
class HistogramWeighting:
    """ヒストグラム重み方式。既定は統計重み、経験重みはオプション。🔵 REQ-008/301"""

    mode: Literal["statistical", "empirical"] = "statistical"  # (REQ-008)
    empirical_weights: Mapping[int, float] = field(default_factory=dict)  # 【index→信頼度】 (REQ-301)

    def resolve(self, model: JointRefinementModel) -> tuple[float, ...]:
        """各ヒストの実効重みを決定論順 (入力ヒスト順) で返す。🔵 REQ-008/REQ-402

        統計モードは全ヒスト 1.0。経験モードは ``empirical_weights`` で該当 index を
        上書きし、未指定 index は 1.0 とする。反復は ``model.histograms`` の並び (index 昇順)
        で行い、``dict`` 反復順に依存しない (NFR-102 ビット同一)。
        """
        n = len(model.histograms)
        if self.mode == "statistical":
            return tuple(1.0 for _ in range(n))
        return tuple(float(self.empirical_weights.get(index, 1.0)) for index in range(n))

    def sigma_source(self, hist_index: int) -> Literal["covariance", "hist_weight"]:
        """当該ヒストの σ 由来を返す (レポート明示用)。🔵 REQ-009/NFR-107

        統計モードは常に covariance。経験モードは当該 index に重み指定があるときのみ
        hist_weight、未指定なら統計 σ のまま covariance を返す。
        """
        if self.mode == "empirical" and hist_index in self.empirical_weights:
            return "hist_weight"
        return "covariance"
