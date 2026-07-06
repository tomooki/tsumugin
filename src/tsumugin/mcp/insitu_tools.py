"""薄い MCP 3 ツール (M9 要素3) — 高温 in situ 逐次 Rietveld の計器+アクチュエータ。

M8 の `rietveld_tools` と同じ設計 (二重反転回避): 閉ループ丸ごとは出さず、③ (Claude Code) が
以下を反復駆動して系列解析を進める。

- ``sequential_rietveld``: frames + initial_phases spec (JSON) を run_sequential_rietveld で実行 →
  フレーム別 Rwp/格子/相分率・変化点・自動出現相を構造化して返す。
- ``identify_and_add_phase``: 残差/生パターン + elements → MP で新相を同定・CIF 物質化し PhaseSpec を返す
  (相追加の候補提示; 実際の採否・再精密化は ③ が sequential_rietveld/refine で行う)。
- ``parametric_fit``: 系列結果 (JSON) + parameter/axis → 熱膨張多項式係数・転移 onset/midpoint±σ。

**SDK 非依存**: 素の型 dict のみ (json.dumps allow_nan=False 安全)。GSAS/MP は runner/finder 内で
遅延 import。runner/finder/provider/materializer は注入可能 (テストは決定論スタブ)。

信頼性: 🔵 architecture.md §6 の M9 3 ツール表と 1:1。
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from .._json import finite_or_none
from ..autorietveld import PhaseSpec
from ..insitu.model import (
    FrameSpec,
    PhaseIdConfig,
    SequentialConfig,
    SequentialRietveldResult,
)

__all__ = [
    "INSITU_TOOLS",
    "identify_and_add_phase",
    "parametric_fit",
    "sequential_rietveld",
]


def _cells_dict(cells: Mapping[str, Sequence[float]]) -> dict[str, list[float | None]]:
    return {name: [finite_or_none(v) for v in cell] for name, cell in cells.items()}


def seq_result_to_dict(result: SequentialRietveldResult) -> dict[str, object]:
    """SequentialRietveldResult を素の型 dict へ (③ の判断入力・parametric_fit 入力)。"""
    return {
        "phase_names": list(result.phase_names),
        "frames": [
            {
                "frame_index": f.frame_index,
                "axis_value": f.axis_value,
                "data_path": f.data_path,
                "rwp": finite_or_none(f.rwp),
                "gof": finite_or_none(f.gof),
                "phase_names": list(f.phase_names),
                "refined_cells": _cells_dict(f.refined_cells),
                "phase_fractions": {k: finite_or_none(v) for k, v in f.phase_fractions.items()},
                "changepoint": bool(f.changepoint),
                "changepoint_reasons": list(f.changepoint_reasons),
                "validity_passed": bool(f.validity_passed),
                "refine_failed": bool(f.refine_failed),
            }
            for f in result.frames
        ],
        "appearances": [
            {
                "phase_name": a.phase_name,
                "frame_index": a.frame_index,
                "axis_value": a.axis_value,
                "structure_path": a.structure_path,
                "source": a.source,
                "rwp_before": finite_or_none(a.rwp_before),
                "rwp_after": finite_or_none(a.rwp_after),
                "evidence": {k: _jsonable(v) for k, v in a.evidence.items()},
            }
            for a in result.appearances
        ],
        "warnings": list(result.warnings),
    }


def _jsonable(v: object) -> object:
    """evidence 値を json 安全化 (float は finite_or_none)。"""
    if isinstance(v, float):
        return finite_or_none(v)
    if isinstance(v, (str, int, bool)) or v is None:
        return v
    return str(v)


def _result_from_dict(d: Mapping[str, object]) -> SequentialRietveldResult:
    """seq_result_to_dict の逆写像 (parametric_fit が受け取る系列結果)。最小フィールドのみ復元。"""
    from ..insitu.model import FrameRietveldResult

    frames = []
    for fd in d.get("frames", []):  # type: ignore[union-attr]
        cells = {
            name: tuple(float(x) for x in cell)
            for name, cell in (fd.get("refined_cells") or {}).items()
            if all(x is not None for x in cell)
        }
        frames.append(
            FrameRietveldResult(
                frame_index=int(fd["frame_index"]),
                axis_value=fd.get("axis_value"),
                data_path=str(fd.get("data_path", "")),
                rwp=float(fd["rwp"]) if fd.get("rwp") is not None else float("inf"),
                gof=float(fd["gof"]) if fd.get("gof") is not None else float("inf"),
                refined_cells=cells,
                phase_fractions={
                    k: float(v) for k, v in (fd.get("phase_fractions") or {}).items() if v is not None
                },
                phase_names=tuple(fd.get("phase_names", ())),
                refine_failed=bool(fd.get("refine_failed", False)),
            )
        )
    return SequentialRietveldResult(
        frames=tuple(frames), phase_names=tuple(d.get("phase_names", ()))
    )


def sequential_rietveld(
    frames: Sequence[Mapping[str, object]],
    initial_phases: Sequence[Mapping[str, object]],
    *,
    phase_id: Mapping[str, object] | None = None,
    warm_start: bool = True,
    two_theta_limits: Sequence[float] | None = None,
    max_frames: int | None = None,
    workdir: str = ".",
    runner: Callable | None = None,
    phase_finder: Callable | None = None,
    reason: str = "",
) -> dict:
    """frames/initial_phases spec (JSON) を run_sequential_rietveld で実行し構造化結果を返す。

    :param frames: FrameSpec.to_dict の列
    :param initial_phases: PhaseSpec.to_dict の列 (フレーム 0 の既知相)
    :param phase_id: {"elements": [...], "frac_min": .., "top_k": .., ...} (新相自動同定, None で無効)
    :param runner/phase_finder: 注入可能 (既定 GSAS/MP 駆動)。テストは決定論スタブ
    """
    from ..insitu.engine import run_sequential_rietveld

    frame_specs = [FrameSpec.from_dict(f) for f in frames]
    phase_specs = [PhaseSpec.from_dict(p) for p in initial_phases]
    pid = None
    if phase_id is not None:
        pid = PhaseIdConfig(
            elements=tuple(str(e) for e in phase_id.get("elements", ())),
            frac_min=float(phase_id.get("frac_min", 0.02)),
            rwp_eps=float(phase_id.get("rwp_eps", 1e-6)),
            top_k=int(phase_id.get("top_k", 1)),
            hull_cutoff_ev=phase_id.get("hull_cutoff_ev", 0.1),  # type: ignore[arg-type]
            subtract_bg=bool(phase_id.get("subtract_bg", True)),
            trigger_rwp_ratio=float(phase_id.get("trigger_rwp_ratio", 1.25)),
        )
    config = SequentialConfig(
        warm_start=warm_start,
        two_theta_limits=(float(two_theta_limits[0]), float(two_theta_limits[1]))
        if two_theta_limits is not None
        else None,
        max_frames=max_frames,
        phase_id=pid,
    )
    result = run_sequential_rietveld(
        frame_specs, phase_specs, config=config, runner=runner,
        phase_finder=phase_finder, workdir=workdir,
    )
    out = seq_result_to_dict(result)
    out["reason"] = reason
    return out


def identify_and_add_phase(
    two_theta: Sequence[float],
    intensity: Sequence[float],
    elements: Sequence[str],
    workdir: str,
    *,
    exclude_formulas: Sequence[str] = (),
    top_k: int = 1,
    hull_cutoff_ev: float | None = 0.1,
    subtract_bg: bool = True,
    provider: object | None = None,
    materializer: object | None = None,
    reason: str = "",
) -> dict:
    """残差/生パターン + elements から新相を同定し CIF 物質化して PhaseSpec 候補を返す (相追加提示)。

    採否・再精密化は行わない (提案≠適用): ③ が返された PhaseSpec を initial_phases に足して
    sequential_rietveld/refine を再実行する。provider/materializer 未指定なら MP を遅延生成。
    """
    import numpy as np

    from ..insitu.phaseid import MPMaterializer, identify_new_phases

    if provider is None:
        from ..mp.provider import MPReferenceProvider

        provider = MPReferenceProvider()
    if materializer is None:
        materializer = MPMaterializer()

    found = identify_new_phases(
        np.asarray(two_theta, dtype=float),
        np.asarray(intensity, dtype=float),
        elements=list(elements),
        provider=provider,  # type: ignore[arg-type]
        materializer=materializer,  # type: ignore[arg-type]
        workdir=workdir,
        exclude_formulas=list(exclude_formulas),
        top_k=top_k,
        hull_cutoff_ev=hull_cutoff_ev,
        subtract_bg=subtract_bg,
    )
    return {
        "candidates": [
            {
                "phase_spec": ip.phase_spec.to_dict(),
                "phase_id": ip.phase_id,
                "formula": ip.formula,
                "score": finite_or_none(ip.score),
                "strain": finite_or_none(ip.strain),
                "source": ip.source,
            }
            for ip in found
        ],
        "n_candidates": len(found),
        "reason": reason,
    }


def parametric_fit(
    result: Mapping[str, object],
    phase: str,
    *,
    component: str = "a",
    degree: int = 1,
    reason: str = "",
) -> dict:
    """系列結果 (JSON) の相 phase について 格子 vs 軸の熱膨張多項式 + 相分率転移を返す。"""
    from ..insitu.parametric import analyze_phase

    seq = _result_from_dict(result)
    pa = analyze_phase(seq, phase, component=component, degree=degree)  # type: ignore[arg-type]
    tr = pa.transition
    return {
        "phase": phase,
        "component": component,
        "baseline": {
            "parameter": pa.baseline.parameter,
            "coefficients": [finite_or_none(c) for c in pa.baseline.coefficients],
            "outlier_frames": list(pa.baseline.outlier_frames),
        },
        "transition": None
        if tr is None
        else {
            "phase_ref": tr.phase_ref,
            "onset": finite_or_none(tr.onset) if tr.onset is not None else None,
            "midpoint": finite_or_none(tr.midpoint) if tr.midpoint is not None else None,
            "sigma": finite_or_none(tr.sigma) if tr.sigma is not None else None,
            "direction": tr.direction,
        },
        "reason": reason,
    }


# 【M9 ツールレジストリ】: MCP_TOOLS へマージする 3 ツール (architecture.md §6)。
INSITU_TOOLS: Mapping[str, object] = {
    "sequential_rietveld": sequential_rietveld,
    "identify_and_add_phase": identify_and_add_phase,
    "parametric_fit": parametric_fit,
}
