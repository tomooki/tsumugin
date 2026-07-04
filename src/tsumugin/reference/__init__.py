"""相ライブラリ + 単一パターン相同定 (仕様 §5 FR-100/110/117)。

コアは numpy のみに依存し常時 import 可能。Materials Project 等の外部供給元は
``ReferenceProvider`` Protocol の背後に隔離する (実体の遅延 import は各供給元モジュール側)。
"""

from __future__ import annotations

from .engine import identify_phases
from .model import PhaseIdentification, PhaseMatch, ReferencePhase
from .provider import ReferenceProvider

__all__: list[str] = [
    "PhaseIdentification",
    "PhaseMatch",
    "ReferencePhase",
    "ReferenceProvider",
    "identify_phases",
]
