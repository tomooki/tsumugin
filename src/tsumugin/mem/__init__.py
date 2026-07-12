"""MEM (Maximum Entropy Method) サブパッケージ (M5 / REQ-018/027〜031 / FR-601〜606)。

MEM ソルバの交換可能境界 (``MEMBackend`` Protocol) と結果型 (``MEMDensityMap`` /
``DensityCrossSection`` / ``BondPathDensity`` / ``MEMResult``) を提供する。実密度グリッドは
ファイル参照でメモリには要約統計のみ持ち、適用ガード警告は積むが仮説除外はしない
(Dara 教訓, REQ-031)。MEM 実行系 (適用ガード / 密度出力 / MEM-Rietveld 反復 / スポット解析) も
本サブパッケージから公開する。トップレベル ``tsumugin`` __all__ への統合は TASK-0058。
"""

from __future__ import annotations

from .base import (
    BondPathDensity,
    DensityCrossSection,
    MEMBackend,
    MEMDensityMap,
    MEMResult,
)
from .dysnomia import DysnomiaBackend
from .gsas import (
    DensityPeak,
    MEMDensityResult,
    MEMRunConfig,
    assign_peaks_to_atoms,
    density_kind_from_type,
    resolve_dysnomia_binary,
    run_dysnomia_mem,
)
from .guard import MEMApplicabilityReport, check_mem_applicability
from .inputgen import (
    MEMInput,
    StructureFactor,
    build_mem_input,
    extract_structure_factors,
)
from .iterate import (
    MEMRietveldConfig,
    MEMRietveldCycle,
    MEMRietveldResult,
    run_mem_rietveld,
)
from .output import (
    bond_path_min_density,
    extract_cross_section,
    load_density_grid,
    save_density_grid,
    write_density_map,
)
from .spot import run_mem_spot

__all__ = [
    "BondPathDensity",
    "DensityCrossSection",
    "DensityPeak",
    "DysnomiaBackend",
    "MEMApplicabilityReport",
    "MEMBackend",
    "MEMDensityMap",
    "MEMDensityResult",
    "MEMInput",
    "MEMResult",
    "MEMRietveldConfig",
    "MEMRietveldCycle",
    "MEMRietveldResult",
    "MEMRunConfig",
    "StructureFactor",
    "assign_peaks_to_atoms",
    "bond_path_min_density",
    "build_mem_input",
    "check_mem_applicability",
    "density_kind_from_type",
    "extract_cross_section",
    "extract_structure_factors",
    "load_density_grid",
    "resolve_dysnomia_binary",
    "run_dysnomia_mem",
    "run_mem_rietveld",
    "run_mem_spot",
    "save_density_grid",
    "write_density_map",
]
