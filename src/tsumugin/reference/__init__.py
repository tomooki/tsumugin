"""相ライブラリ + 単一/多相相同定 (仕様 §5 FR-100/110/117)。

コアは numpy のみに依存し常時 import 可能。Materials Project / CIF (COD/ICSD/ユーザー) 等の
外部供給元は ``ReferenceProvider`` Protocol の背後に隔離する (実体の遅延 import は各供給元側)。
"""

from __future__ import annotations

from .background import estimate_snip_background, subtract_background
from .cache import CachedReferenceProvider
from .cif import cif_to_reference_phases
from .engine import filter_references, identify_phases
from .grouping import PhaseMatchGroup, group_by_composition
from .iterative import (
    AcceptedPhase,
    IdentifyConfig,
    IterativeIdentification,
    RietveldRefiner,
    identify_pattern,
    refine_polymorphs,
    subtract_known_phases,
)
from .io import (
    load_fxye,
    load_gsas_powder,
    load_xy,
    parse_fxye,
    parse_gsas_powder,
    parse_xy,
)
from .kalpha import KAlpha2, add_kalpha2_satellites
from .mixture import ReferenceBackend, identify_phase_mixtures
from .model import PhaseIdentification, PhaseMatch, ReferencePhase
from .provider import ReferenceProvider
from .providers import CODProvider, ICSDProvider, UserCIFProvider
from .rietveld import LatticeAlignment, align_peaks
from .scoring import DaraScore, dara_peak_score
from .serialization import reference_phase_from_dict, reference_phase_to_dict
from .threshold import inflection_threshold

__all__: list[str] = [
    "AcceptedPhase",
    "CODProvider",
    "CachedReferenceProvider",
    "DaraScore",
    "IdentifyConfig",
    "IterativeIdentification",
    "RietveldRefiner",
    "ICSDProvider",
    "KAlpha2",
    "LatticeAlignment",
    "PhaseIdentification",
    "PhaseMatch",
    "PhaseMatchGroup",
    "ReferenceBackend",
    "ReferencePhase",
    "ReferenceProvider",
    "UserCIFProvider",
    "add_kalpha2_satellites",
    "align_peaks",
    "cif_to_reference_phases",
    "dara_peak_score",
    "estimate_snip_background",
    "filter_references",
    "group_by_composition",
    "identify_pattern",
    "identify_phase_mixtures",
    "identify_phases",
    "inflection_threshold",
    "load_fxye",
    "load_gsas_powder",
    "load_xy",
    "parse_fxye",
    "parse_gsas_powder",
    "parse_xy",
    "reference_phase_from_dict",
    "reference_phase_to_dict",
    "refine_polymorphs",
    "subtract_background",
    "subtract_known_phases",
]
