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
from .backend_adapter import AutoRietveldBackend
from .engine import run_auto_rietveld
from .lattice import (
    LatticeSolution,
    cell_from_reciprocal_metric,
    reciprocal_metric_from_cell,
    refine_cell_from_indexed_peaks,
    refine_cell_robust,
    solve_cell_from_dspacings,
    two_theta_of_hkls,
)
from .multistart import (
    MultistartStart,
    RietveldMultistartResult,
    generate_cell_scales,
    run_multistart_rietveld,
    summarize_multistart,
)
from .pawley import (
    PawleyCellResult,
    prealign_cell_from_structure,
    refine_cell_pawley,
)
from .recipe import build_recipe
from .validity import check_validity

__all__ = [
    "AutoRietveldBackend",
    "AutoRietveldResult",
    "Geometry",
    "HistogramSpec",
    "LatticeSolution",
    "MultistartStart",
    "PawleyCellResult",
    "PhaseSpec",
    "Radiation",
    "RefinementStage",
    "RietveldMultistartResult",
    "StageResult",
    "ValidityReport",
    "build_recipe",
    "cell_from_reciprocal_metric",
    "check_validity",
    "generate_cell_scales",
    "prealign_cell_from_structure",
    "reciprocal_metric_from_cell",
    "refine_cell_from_indexed_peaks",
    "refine_cell_pawley",
    "refine_cell_robust",
    "run_auto_rietveld",
    "run_multistart_rietveld",
    "solve_cell_from_dspacings",
    "summarize_multistart",
    "two_theta_of_hkls",
]
