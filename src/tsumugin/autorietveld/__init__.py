"""M7 実構造自動 Rietveld 解析 (GSAS-II 駆動)。

実 CIF/相ファイル + 実データ + 装置パラメータを入力に、段階解放レシピで自動 Rietveld
精密化を実行し、Rwp/GOF と物理的妥当性レポートを返す。GSAS-II はエンジン層で遅延 import
するため、コア import は numpy のみを維持する (CLAUDE.md 不変条件)。
"""

from __future__ import annotations

from .model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from .recipe import build_recipe
from .validity import check_validity

__all__ = [
    "AutoRietveldResult",
    "Geometry",
    "HistogramSpec",
    "PhaseSpec",
    "Radiation",
    "RefinementStage",
    "StageResult",
    "ValidityReport",
    "build_recipe",
    "check_validity",
]
