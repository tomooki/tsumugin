"""M10 アンカー基準双方向逐次解析のオーケストレーション (FR-337)。

`extract_anchors` → `build_segments` → 各区間 `refine_segment_forward/backward` → `select_crossover`
→ `assemble_path` を束ね、M9 と互換の `SequentialRietveldResult` を返す。両パスと選定理由を ledger に
追記し (提案≠適用・P2)、採用経路を組み立てる。numpy-only コア (runner は GSAS を内部で駆動)。

`_consolidate_phase_cells` (M9) はこの方式に包含される (支配フレームのアンカー = 新相アンカー、その
相集合/セルが後方パスの warm-start 種)。決定論 (NFR-102): 乱数を用いず同一入力でビット同一経路。

信頼性: 🔵 architecture.md §7 / REQ-1014〜1019。
"""

from __future__ import annotations

from ...autorietveld.model import PhaseSpec
from ...store.ledger import Ledger
from ..model import (
    ChargeConstraintConfig,
    FrameRietveldResult,
    FrameSpec,
    PhaseAppearance,
    SequentialRietveldResult,
)
from .extract import AnchorRunner, Identifier, extract_anchors
from .model import Anchor, AnchorConfig
from .segment import build_segments, refine_segment_backward, refine_segment_forward
from .select import assemble_path, select_crossover

__all__ = ["run_anchored_sequential"]


def _anchor_frame_result(anchor: Anchor) -> FrameRietveldResult:
    """確定アンカーの段階 B 結果を FrameRietveldResult に写す。"""
    return FrameRietveldResult(
        frame_index=anchor.frame_index, axis_value=anchor.axis_value,
        data_path="", rwp=anchor.rwp, gof=anchor.gof,
        refined_cells=dict(anchor.refined_cells),
        phase_fractions=dict(anchor.phase_fractions), phase_names=anchor.phase_names,
        validity_passed=anchor.validity_passed,
        refine_failed=not (anchor.rwp < float("inf")), n_obs=anchor.n_obs,
        phase_weight_fractions=dict(anchor.phase_weight_fractions),
        phase_weight_fraction_esd=dict(anchor.phase_weight_fraction_esd),
        cell_esd={k: tuple(v) for k, v in anchor.cell_esd.items()},
        # FR-318: 段階 B で事前計算した alkali 診断を展開 (機能無効なら空 = 既定値)。
        **dict(anchor.alkali),  # type: ignore[arg-type]
    )


def _failed_frame(frame: FrameSpec, i: int) -> FrameRietveldResult:
    return FrameRietveldResult(
        frame_index=i, axis_value=frame.axis_value, data_path=frame.data_path,
        rwp=float("inf"), gof=float("inf"), refined_cells={}, phase_fractions={},
        phase_names=(), refine_failed=True,
    )


def _structure_path_of(anchors: "tuple[Anchor, ...]", phase_name: str) -> str:
    """相 phase_name の構造ファイルをアンカー群から引く (appearance 記録用)。"""
    for a in anchors:
        for spec in a.phase_specs:
            if spec.phase_name == phase_name:
                return spec.structure_path
    return ""


def run_anchored_sequential(
    frames: "list[FrameSpec] | tuple[FrameSpec, ...]",
    base_phases: "list[PhaseSpec] | tuple[PhaseSpec, ...]",
    *,
    runner: AnchorRunner,
    identifier: Identifier | None = None,
    cfg: AnchorConfig = AnchorConfig(),
    ledger: Ledger | None = None,
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> SequentialRietveldResult:
    """アンカー基準双方向解析を実行し `SequentialRietveldResult` を返す。

    1. `extract_anchors` で確定アンカー (2 段ゲート)。
    2. `build_segments` で区間列。
    3. 各区間で前方/後方パス → `select_crossover` (bic) → `assemble_path`。
    4. アンカー + 採用内側フレームを frame 順に組み立て、新相 onset を `PhaseAppearance` に記録。

    ``charge_constraint`` (FR-318): 有効なら (1) アンカーで制約有無 A/B を実施し ΔRwp が
    ``anchor_ab_threshold`` 超のアンカーに**不可逆容量疑いの警告 + x₀ 校正の提案** (提案≠適用,
    ledger 追記のみ — 採用判断は第3層)、(2) 内側フレームに alkali 診断を付す。
    """
    frames = list(frames)
    base = tuple(base_phases)
    ledger = ledger if ledger is not None else Ledger()
    n = len(frames)
    if n == 0:
        return SequentialRietveldResult(frames=())

    base_names = frozenset(p.phase_name for p in base)
    warnings: list[str] = []
    # FR-318 (H1): runner が charge_constraint を消費する保証の照合 (不一致は 1 回警告)。
    from ..engine import _warn_runner_constraint_mismatch

    _warn_runner_constraint_mismatch(runner, charge_constraint, warnings)

    anchors = extract_anchors(
        frames, base, runner=runner, identifier=identifier, cfg=cfg,
        charge_constraint=charge_constraint, warn_sink=warnings,
    )
    for a in anchors:
        ledger.append("m10_anchor", {
            "frame": a.frame_index, "phases": list(a.phase_names), "rwp": a.rwp,
            "confidence": a.confidence, "fallback": a.fallback,
        })
        if a.fallback:
            warnings.append(f"fallback_anchor@{a.frame_index}")
        # FR-318 REQ-318-006: アンカー A/B の ΔRwp 検証 → 不可逆容量疑いの警告 + x₀ 校正提案。
        if a.ab_check is not None and charge_constraint is not None:
            ledger.append("fr318_anchor_ab", {"frame": a.frame_index, **dict(a.ab_check)})
            delta = float(a.ab_check.get("delta_rwp", 0.0))
            if abs(delta) > charge_constraint.anchor_ab_threshold:
                # x の由来 (レビュー M2): "x_refined" = A の占有率が実際に精密化された (esd 付き)
                # 場合のみ。既定 (占有率固定) は "x_model" = CIF 由来のモデル値であり、
                # **x₀ 校正の根拠にはならない** — 提案は精密化済みのときだけ出す。
                refined = "x_refined" in a.ab_check
                x_val = a.ab_check.get("x_refined", a.ab_check.get("x_model"))
                x_ech = a.ab_check.get("x_echem")
                if refined:
                    warnings.append(
                        f"anchor@{a.frame_index}: 制約有無の ΔRwp={delta:+.2f}%pt が閾値"
                        f" {charge_constraint.anchor_ab_threshold} を超過 — 不可逆容量/副反応で"
                        f" echem 由来組成 (x={x_ech}) が回折 (精密化 x={x_val}) とずれている疑い。"
                        "x₀ を精密化値で校正する提案を ledger (fr318_x0_calibration_proposal) に"
                        "記録しました (提案≠適用 — 採用は第3層判断)"
                    )
                    ledger.append("fr318_x0_calibration_proposal", {
                        "frame": a.frame_index,
                        "x_echem": x_ech,
                        "x_refined": x_val,
                        "delta_rwp": delta,
                        "applied": False,  # 提案のみ (P2 非破壊)
                    })
                else:
                    warnings.append(
                        f"anchor@{a.frame_index}: 制約有無の ΔRwp={delta:+.2f}%pt が閾値"
                        f" {charge_constraint.anchor_ab_threshold} を超過 (echem x={x_ech} vs "
                        f"モデル固定値 x={x_val})。**この x は精密化値ではない** (占有率固定) ため"
                        " x₀ 校正の提案はしません — 校正するにはアンカー相の PhaseSpec に"
                        " free_occupancy_labels を設定して占有率を精密化してください"
                    )

    segments = build_segments(anchors, n)

    # frame_index → FrameRietveldResult (アンカー + 採用内側フレーム)
    assembled: dict[int, FrameRietveldResult] = {a.frame_index: _anchor_frame_result(a) for a in anchors}
    onsets: dict[str, int] = {}  # 新相 → onset フレーム (crossover 由来)

    for seg in segments:
        fwd = refine_segment_forward(seg, frames, runner, charge_constraint, warnings)
        bwd = refine_segment_backward(seg, frames, runner, charge_constraint, warnings)
        choice = select_crossover(seg, fwd, bwd, cfg)
        path = assemble_path(seg, fwd, bwd, choice)
        assembled.update(path)
        ledger.append("m10_segment_choice", {
            "left": seg.left.frame_index if seg.left else None,
            "right": seg.right.frame_index if seg.right else None,
            "inner": list(seg.frame_indices), "reason": choice.reason,
            "crossover_frame": choice.crossover_frame, "total_bic": choice.total_bic,
            "onset_frame": choice.onset_frame, "monotonic": choice.monotonic,
        })
        if choice.onset_frame is not None and seg.right is not None:
            for p in frozenset(seg.right.phase_names) - frozenset(
                seg.left.phase_names if seg.left else ()
            ):
                onsets[p] = min(onsets.get(p, choice.onset_frame), choice.onset_frame)

    # frame 順に組み立て (欠測は失敗フレーム)
    frame_results = tuple(
        assembled[i] if i in assembled else _failed_frame(frames[i], i) for i in range(n)
    )

    # 新相 appearances: 最終経路で非 base 相が初めて現れるフレーム (crossover onset を優先)
    appearances = _collect_appearances(frame_results, anchors, base_names, onsets)

    all_names: list[str] = []
    for fr in frame_results:
        for nm in fr.phase_names:
            if nm not in all_names:
                all_names.append(nm)

    ledger.append("m10_anchored_done", {
        "anchors": [a.frame_index for a in anchors], "phases": all_names,
        "appearances": len(appearances),
    })

    return SequentialRietveldResult(
        frames=frame_results, appearances=tuple(appearances),
        phase_names=tuple(all_names), warnings=tuple(warnings), ledger=ledger,
    )


def _collect_appearances(
    frame_results: "tuple[FrameRietveldResult, ...]", anchors: "tuple[Anchor, ...]",
    base_names: "frozenset[str]", onsets: "dict[str, int]",
) -> "list[PhaseAppearance]":
    """非 base 相ごとに、最終経路で初めて有意分率で現れるフレームを onset として記録する。"""
    appearances: list[PhaseAppearance] = []
    seen: set[str] = set()
    for fr in frame_results:
        for nm in fr.phase_names:
            if nm in base_names or nm in seen:
                continue
            if float(fr.phase_fractions.get(nm, 0.0)) <= 0.0:
                continue
            seen.add(nm)
            onset = onsets.get(nm, fr.frame_index)
            onset_fr = frame_results[onset] if 0 <= onset < len(frame_results) else fr
            appearances.append(PhaseAppearance(
                phase_name=nm, frame_index=onset, axis_value=onset_fr.axis_value,
                structure_path=_structure_path_of(anchors, nm), source="anchor",
                rwp_before=onset_fr.rwp, rwp_after=onset_fr.rwp,
                evidence={"onset_from_crossover": nm in onsets},
            ))
    return appearances
