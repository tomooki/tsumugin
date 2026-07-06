"""ReferencePhase の JSON シリアライズ (仕様 §5 FR-105 キャッシュ永続化の基盤)。

``ReferencePhase`` (Peak タプルを含む frozen dataclass) を素の型 dict へ双方向変換する。
numpy 非依存・決定論的で、``json.dumps(allow_nan=False)`` で永続化可能な形へ写す。
"""

from __future__ import annotations

from typing import Any, Mapping

from ..search.peaks import Peak
from .model import ReferencePhase

__all__ = ["reference_phase_from_dict", "reference_phase_to_dict"]


def _peak_to_dict(p: Peak) -> dict[str, Any]:
    d: dict[str, Any] = {"position": float(p.position), "height": float(p.height)}
    if p.hkl is not None:  # 異方整合用 hkl。無い (観測/hkl 不明) 相は省いて後方互換
        d["hkl"] = [int(p.hkl[0]), int(p.hkl[1]), int(p.hkl[2])]
    return d


def reference_phase_to_dict(phase: ReferencePhase) -> dict[str, Any]:
    """``ReferencePhase`` を JSON 可能な素の dict へ変換する。🔵 FR-105"""
    out: dict[str, Any] = {
        "phase_id": phase.phase_id,
        "formula": phase.formula,
        "element_system": list(phase.element_system),
        "peaks": [_peak_to_dict(p) for p in phase.peaks],
        "spacegroup": phase.spacegroup,
        "energy_above_hull": phase.energy_above_hull,
    }
    # 異方格子整合 (Issue #20 hybrid) 用の格子情報。無い相は省いて後方互換を保つ。
    if phase.cell is not None:
        out["cell"] = [float(x) for x in phase.cell]
    if phase.crystal_system is not None:
        out["crystal_system"] = phase.crystal_system
    return out


def _peak_from_dict(p: Mapping[str, Any]) -> Peak:
    raw_hkl = p.get("hkl")
    hkl = (int(raw_hkl[0]), int(raw_hkl[1]), int(raw_hkl[2])) if raw_hkl is not None else None
    return Peak(position=float(p["position"]), height=float(p["height"]), hkl=hkl)


def reference_phase_from_dict(data: Mapping[str, Any]) -> ReferencePhase:
    """素の dict から ``ReferencePhase`` を復元する (``reference_phase_to_dict`` の逆)。🔵 FR-105"""
    peaks = tuple(_peak_from_dict(p) for p in data.get("peaks", ()))
    raw_cell = data.get("cell")
    cell = tuple(float(x) for x in raw_cell) if raw_cell is not None else None
    return ReferencePhase(
        phase_id=str(data["phase_id"]),
        formula=str(data["formula"]),
        element_system=tuple(data.get("element_system", ())),
        peaks=peaks,
        spacegroup=data.get("spacegroup"),
        energy_above_hull=data.get("energy_above_hull"),
        cell=cell,  # type: ignore[arg-type]
        crystal_system=data.get("crystal_system"),
    )
