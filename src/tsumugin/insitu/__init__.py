"""M9 高温 in situ 逐次 Rietveld 自動解析。

温度/時間系列の実構造 Rietveld をウォームスタートで逐次精密化し、系列途中で出現する新相を
自動同定 (Materials Project) して相集合に追加する。M7 (`autorietveld`, 単一フレーム実構造) と
M8 (`refine_loop`, agentic 閉ループ 3 層) の系列版。パラメトリック解析 (格子 vs 温度・相転移) を含む。

コア (`model`/`parametric`/`phaseid` の numpy 部) は numpy のみに依存。GSAS 駆動は `engine` 内、
MP/pymatgen は `phaseid` の遅延 import 境界に隔離する (コア import は numpy のみを維持)。

信頼性: 🔵 docs/design/m9-insitu-sequential/architecture.md
"""

from __future__ import annotations

from .model import (
    Cell,
    FractionBasis,
    FractionBasisUnavailableError,
    FrameRietveldResult,
    FrameSpec,
    PhaseAppearance,
    PhaseIdConfig,
    SequentialConfig,
    SequentialRietveldResult,
)
from .engine import make_gsas_runner, run_sequential_rietveld
from .parametric import (
    ParametricAnalysis,
    analyze_phase,
    lattice_baseline,
    pseudo_variable_series,
    transition_from_fractions,
)
from .phaseid import IdentifiedPhase, identify_new_phases, phasespec_to_reference
from .anchor import AnchorConfig, run_anchored_sequential
from .repair import (
    Discontinuity,
    FrameRepair,
    RepairReport,
    classify,
    detect_discontinuities,
    discontinuities_from_frames,
    repair_isolated,
)
from .phaseset import (
    FrozenFractionFrame,
    FrozenFractionReport,
    NonMonotonicReport,
    PhaseSetCompletionReport,
    SeedPinnedFrame,
    SeedPinningReport,
    flag_frozen_fraction_frames,
    flag_nonmonotonic_fraction,
    flag_seed_pinned_frames,
    is_seed_pinned,
    suggest_phase_set_completion,
)

__all__ = [
    "AnchorConfig",
    "Cell",
    "Discontinuity",
    "FractionBasis",
    "FractionBasisUnavailableError",
    "FrameRepair",
    "FrameRietveldResult",
    "FrameSpec",
    "FrozenFractionFrame",
    "FrozenFractionReport",
    "IdentifiedPhase",
    "NonMonotonicReport",
    "ParametricAnalysis",
    "PhaseAppearance",
    "PhaseIdConfig",
    "PhaseSetCompletionReport",
    "RepairReport",
    "SeedPinnedFrame",
    "SeedPinningReport",
    "SequentialConfig",
    "SequentialRietveldResult",
    "analyze_phase",
    "classify",
    "detect_discontinuities",
    "discontinuities_from_frames",
    "flag_frozen_fraction_frames",
    "flag_nonmonotonic_fraction",
    "flag_seed_pinned_frames",
    "identify_new_phases",
    "is_seed_pinned",
    "lattice_baseline",
    "make_gsas_runner",
    "phasespec_to_reference",
    "pseudo_variable_series",
    "repair_isolated",
    "run_anchored_sequential",
    "run_sequential_rietveld",
    "suggest_phase_set_completion",
    "transition_from_fractions",
]
