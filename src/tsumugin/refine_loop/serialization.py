"""M8: AnalysisAction / ActionProposal / ResidualFeatures の素の型 JSON シリアライズ。

MCP が ③ (Claude Code) と Action を JSON でやり取りするための往復同型シリアライズ。Action は
``{"type": <クラス名>, ...フィールド}`` へ写像し、`action_from_dict` が型でディスパッチする。
PhaseSpec/tuple は素の型へ再帰的に落とす (json.dumps allow_nan=False 安全)。

信頼性: 🔵 architecture.md §6 (MCP 3 ツールの JSON 契約)。GSAS 非依存。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from tsumugin.autorietveld import PhaseSpec
from .action import (
    AddPhase,
    AdjustBackground,
    AnalysisAction,
    ReleaseParams,
    RemovePhase,
    ReviseStructure,
    SetLimits,
    SetMixedOccupancy,
    Stop,
)
from .diagnostics import ActionProposal, ResidualFeatures


def _jsonable(value: object) -> object:
    """tuple→list を再帰適用して JSON 安全な素の型へ落とす。"""
    if isinstance(value, (tuple, list)):
        return [_jsonable(v) for v in value]
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    return value


def action_to_dict(action: AnalysisAction) -> dict[str, object]:
    """AnalysisAction を ``{"type": クラス名, ...}`` の素の型 dict へ写像する。"""
    name = type(action).__name__
    if isinstance(action, AdjustBackground):
        return {"type": name, "n_coeffs": action.n_coeffs}
    if isinstance(action, ReleaseParams):
        return {"type": name, "label": action.label, "flags": _jsonable(action.flags)}
    if isinstance(action, Stop):
        return {"type": name, "reason": action.reason}
    if isinstance(action, SetLimits):
        return {"type": name, "hist_id": action.hist_id, "low": action.low, "high": action.high}
    if isinstance(action, AddPhase):
        return {
            "type": name,
            "spec": action.spec.to_dict() if action.spec is not None else None,
            "element_hint": list(action.element_hint),
        }
    if isinstance(action, RemovePhase):
        return {"type": name, "name": action.name}
    if isinstance(action, ReviseStructure):
        return {"type": name, "phase": action.phase, "edits": _jsonable(action.edits)}
    if isinstance(action, SetMixedOccupancy):
        return {"type": name, "phase": action.phase, "groups": _jsonable(action.groups)}
    raise ValueError(f"未知の Action 型: {name}")


def action_from_dict(d: Mapping[str, object]) -> AnalysisAction:
    """action_to_dict の逆写像。``type`` でディスパッチする。"""
    t = d.get("type")
    if t == "AdjustBackground":
        return AdjustBackground(int(d["n_coeffs"]))
    if t == "ReleaseParams":
        return ReleaseParams(str(d["label"]), dict(d["flags"]))  # type: ignore[arg-type]
    if t == "Stop":
        return Stop(str(d["reason"]))
    if t == "SetLimits":
        return SetLimits(int(d["hist_id"]), float(d["low"]), float(d["high"]))
    if t == "AddPhase":
        spec = d.get("spec")
        return AddPhase(
            spec=PhaseSpec.from_dict(spec) if spec else None,
            element_hint=tuple(str(e) for e in (d.get("element_hint") or ())),
        )
    if t == "RemovePhase":
        return RemovePhase(str(d["name"]))
    if t == "ReviseStructure":
        return ReviseStructure(str(d["phase"]), dict(d["edits"]))  # type: ignore[arg-type]
    if t == "SetMixedOccupancy":
        groups = tuple(tuple(str(a) for a in g) for g in (d.get("groups") or ()))
        return SetMixedOccupancy(str(d["phase"]), groups)
    raise ValueError(f"未知の Action 型: {t!r}")


def proposal_to_dict(proposal: ActionProposal) -> dict[str, object]:
    """ActionProposal を素の型 dict へ写像する (MCP 露出用)。"""
    return {
        "action": action_to_dict(proposal.action),
        "rationale": proposal.rationale,
        "priority": proposal.priority,
        "evidence": _jsonable(proposal.evidence),
        "safe": proposal.safe,
    }


def features_from_dicts(dicts: Sequence[Mapping[str, object]]) -> tuple[ResidualFeatures, ...]:
    """残差シグネチャの dict 列を ResidualFeatures へ復元する。"""
    return tuple(
        ResidualFeatures(
            hist_id=int(d["hist_id"]),
            low_freq_bg_residual=float(d.get("low_freq_bg_residual", 0.0)),
            fwhm_ratio=float(d.get("fwhm_ratio", 1.0)),
            unindexed_peak_frac=float(d.get("unindexed_peak_frac", 0.0)),
            edge_low_snr=bool(d.get("edge_low_snr", False)),
            n_background_coeffs=int(d.get("n_background_coeffs", 6)),
        )
        for d in dicts
    )
