"""相ライブラリ + 単一/多相相同定 (仕様 §5 FR-100/110/117)。

コアは numpy のみに依存し常時 import 可能。Materials Project / CIF (COD/ICSD/ユーザー) 等の
外部供給元は ``ReferenceProvider`` Protocol の背後に隔離する (実体の遅延 import は各供給元側)。
"""

from __future__ import annotations

from .cache import CachedReferenceProvider
from .cif import cif_to_reference_phases
from .engine import filter_references, identify_phases
from .io import load_gsas_powder, parse_gsas_powder
from .mixture import ReferenceBackend, identify_phase_mixtures
from .model import PhaseIdentification, PhaseMatch, ReferencePhase
from .provider import ReferenceProvider
from .providers import CODProvider, ICSDProvider, UserCIFProvider
from .serialization import reference_phase_from_dict, reference_phase_to_dict

__all__: list[str] = [
    "CODProvider",
    "CachedReferenceProvider",
    "ICSDProvider",
    "PhaseIdentification",
    "PhaseMatch",
    "ReferenceBackend",
    "ReferencePhase",
    "ReferenceProvider",
    "UserCIFProvider",
    "cif_to_reference_phases",
    "filter_references",
    "identify_phase_mixtures",
    "identify_phases",
    "load_gsas_powder",
    "parse_gsas_powder",
    "reference_phase_from_dict",
    "reference_phase_to_dict",
]
