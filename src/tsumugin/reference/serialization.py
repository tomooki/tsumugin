"""ReferencePhase の JSON シリアライズ (仕様 §5 FR-105 キャッシュ永続化の基盤)。

``ReferencePhase`` (Peak タプルを含む frozen dataclass) を素の型 dict へ双方向変換する。
numpy 非依存・決定論的で、``json.dumps(allow_nan=False)`` で永続化可能な形へ写す。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..search.peaks import Peak
from .model import ReferencePhase

__all__ = ["reference_phase_from_dict", "reference_phase_to_dict"]


def reference_phase_to_dict(phase: ReferencePhase) -> dict[str, Any]:
    """``ReferencePhase`` を JSON 可能な素の dict へ変換する。🔵 FR-105"""
    return {
        "phase_id": phase.phase_id,
        "formula": phase.formula,
        "element_system": list(phase.element_system),
        "peaks": [{"position": float(p.position), "height": float(p.height)} for p in phase.peaks],
        "spacegroup": phase.spacegroup,
        "energy_above_hull": phase.energy_above_hull,
    }


def reference_phase_from_dict(data: Mapping[str, Any]) -> ReferencePhase:
    """素の dict から ``ReferencePhase`` を復元する (``reference_phase_to_dict`` の逆)。🔵 FR-105"""
    peaks = tuple(
        Peak(position=float(p["position"]), height=float(p["height"]))
        for p in data.get("peaks", ())
    )
    return ReferencePhase(
        phase_id=str(data["phase_id"]),
        formula=str(data["formula"]),
        element_system=tuple(data.get("element_system", ())),
        peaks=peaks,
        spacegroup=data.get("spacegroup"),
        energy_above_hull=data.get("energy_above_hull"),
    )
