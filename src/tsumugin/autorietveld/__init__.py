"""M7 実構造自動 Rietveld 解析 (GSAS-II 駆動)。

実 CIF/相ファイル + 実データ + 装置パラメータを入力に、段階解放レシピで自動 Rietveld
精密化を実行し、Rwp/GOF と物理的妥当性レポートを返す。GSAS-II はエンジン層で遅延 import
するため、コア import は numpy のみを維持する (CLAUDE.md 不変条件)。
"""

from __future__ import annotations

from .absorption import (
    AbsorberLayer,
    apply_absorption_correction,
    mu_from_composition,
    transmission_correction,
    wavelength_to_energy_kev,
)
from .model import (
    AutoRietveldResult,
    CalibrationResult,
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
from .dataquality import (
    BackgroundScanReport,
    BackgroundSubtractedReport,
    detect_background_subtracted,
    scan_background_coeffs,
    suggest_two_theta_limit,
)
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
from .cell_refine import (
    CellRefinementResult,
    prealign_cell_from_structure,
    refine_structure_cell,
)
from .recipe import build_recipe
from .residual_report import (
    ResidualFeature,
    ResidualReport,
    residual_report,
    residual_report_from_result,
)
from .resolution import (
    NONNEG_PROFILE_BOUNDS,
    STANDARD_CELL_A,
    build_calibration_recipe,
    build_resolution_recipe,
    calibrate_instrument_from_standard,
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
    "AbsorberLayer",
    "AutoRietveldBackend",
    "AutoRietveldResult",
    "BackgroundScanReport",
    "BackgroundSubtractedReport",
    "CalibrationResult",
    "CellRefinementResult",
    "Geometry",
    "HistogramSpec",
    "InstrumentProfile",
    "LatticeSolution",
    "MultistartStart",
    "NONNEG_PROFILE_BOUNDS",
    "PhaseSpec",
    "ResidualFeature",
    "ResidualReport",
    "STANDARD_CELL_A",
    "Radiation",
    "RefinementStage",
    "RietveldMultistartResult",
    "StageResult",
    "ValidityReport",
    "apply_absorption_correction",
    "build_calibration_recipe",
    "build_recipe",
    "build_resolution_recipe",
    "calibrate_instrument_from_standard",
    "candidate_profiles",
    "cell_from_reciprocal_metric",
    "check_bond_validity",
    "check_profile_physicality",
    "check_validity",
    "detect_background_subtracted",
    "extract_instrument_profile",
    "extract_instrument_profile_from_standard",
    "generate_cell_scales",
    "mu_from_composition",
    "prealign_cell_from_structure",
    "profile_fwhm_min",
    "profile_total_fwhm",
    "reciprocal_metric_from_cell",
    "refine_cell_from_indexed_peaks",
    "refine_structure_cell",
    "refine_cell_robust",
    "residual_report",
    "residual_report_from_result",
    "run_auto_rietveld",
    "run_multistart_rietveld",
    "scan_background_coeffs",
    "search_instrument_profile",
    "solve_cell_from_dspacings",
    "standard_reference_cif",
    "suggest_two_theta_limit",
    "summarize_multistart",
    "transmission_correction",
    "two_theta_of_hkls",
    "wavelength_to_energy_kev",
]
