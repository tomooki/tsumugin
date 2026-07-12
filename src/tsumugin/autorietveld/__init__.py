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
    InstrumentProfile,
    PhaseSpec,
    Radiation,
    RefinementStage,
    StageResult,
    ValidityReport,
)
from .backend_adapter import AutoRietveldBackend
from .engine import run_auto_rietveld
from .mem import (
    DensityPeak,
    MEMDensityResult,
    MEMRunConfig,
    assign_peaks_to_atoms,
    density_kind_from_type,
    resolve_dysnomia_binary,
    run_dysnomia_mem,
)
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
from .cell_refine import (
    CellRefinementResult,
    prealign_cell_from_structure,
    refine_structure_cell,
)
from .recipe import build_recipe
from .resolution import (
    NONNEG_PROFILE_BOUNDS,
    build_resolution_recipe,
    candidate_profiles,
    extract_instrument_profile,
    extract_instrument_profile_from_standard,
    profile_fwhm_min,
    profile_total_fwhm,
    search_instrument_profile,
    standard_reference_cif,
)
from .validity import check_bond_validity, check_profile_physicality, check_validity

__all__ = [
    "AutoRietveldBackend",
    "AutoRietveldResult",
    "CellRefinementResult",
    "DensityPeak",
    "Geometry",
    "HistogramSpec",
    "InstrumentProfile",
    "LatticeSolution",
    "MEMDensityResult",
    "MEMRunConfig",
    "MultistartStart",
    "NONNEG_PROFILE_BOUNDS",
    "PhaseSpec",
    "Radiation",
    "RefinementStage",
    "RietveldMultistartResult",
    "StageResult",
    "ValidityReport",
    "assign_peaks_to_atoms",
    "build_recipe",
    "build_resolution_recipe",
    "candidate_profiles",
    "cell_from_reciprocal_metric",
    "check_bond_validity",
    "check_profile_physicality",
    "check_validity",
    "density_kind_from_type",
    "extract_instrument_profile",
    "extract_instrument_profile_from_standard",
    "generate_cell_scales",
    "prealign_cell_from_structure",
    "profile_fwhm_min",
    "profile_total_fwhm",
    "reciprocal_metric_from_cell",
    "refine_cell_from_indexed_peaks",
    "refine_structure_cell",
    "refine_cell_robust",
    "resolve_dysnomia_binary",
    "run_auto_rietveld",
    "run_dysnomia_mem",
    "run_multistart_rietveld",
    "search_instrument_profile",
    "solve_cell_from_dspacings",
    "standard_reference_cif",
    "summarize_multistart",
    "two_theta_of_hkls",
]
