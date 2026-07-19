"""M10 双方向区間解析 — 隣接アンカー区間の内側フレームを前方/後方に独立 warm-start 逐次精密化 (FR-333)。

各アンカー区間 `[L, R]` の内側フレームを、L の相集合/セルで前方 (L→R)・R の相集合/セルで後方 (R→L) に
**独立** (共有状態なし) に解く。全内側フレームが 2 回精密化され、`select` が bic で最良経路を選ぶ。
端点区間 (先頭アンカー以前 / 末尾アンカー以降) は bracket がある側のみで片方向解析。runner は注入
(GSAS は内部)、本モジュールは numpy-only。

信頼性: 🔵 architecture.md §4 / REQ-1005〜1008。
"""

from __future__ import annotations

from ...autorietveld.model import PhaseSpec, coerce_cell_esd
from .._warmstart import call_runner, seed_fractions
from ..charge import alkali_fields
from ..model import Cell, ChargeConstraintConfig, FrameRietveldResult, FrameSpec
from .extract import AnchorRunner
from .model import Anchor, Segment, SegmentPass

__all__ = ["build_segments", "refine_segment_forward", "refine_segment_backward"]


def build_segments(anchors: "tuple[Anchor, ...]", n_frames: int) -> tuple[Segment, ...]:
    """フレーム順アンカー列から区間列を構成する (内側フレームのみ; アンカーフレームは除外)。

    - 先頭アンカー以前 (frame < 最初のアンカー): `left=None` の片側区間 (後方のみ)。
    - 隣接アンカー間 `[L, R]`: 両側区間 (前方 + 後方)。
    - 末尾アンカー以降 (frame > 最後のアンカー): `right=None` の片側区間 (前方のみ)。

    内側フレームが空の区間 (隣接アンカーが連続) は省略する。
    """
    if not anchors or n_frames <= 0:
        return ()
    segs: list[Segment] = []
    first = anchors[0]
    # 先頭端点区間
    if first.frame_index > 0:
        inner = tuple(range(0, first.frame_index))
        segs.append(Segment(left=None, right=first, frame_indices=inner, one_sided=True))
    # アンカー間区間
    for a, b in zip(anchors[:-1], anchors[1:]):
        inner = tuple(range(a.frame_index + 1, b.frame_index))
        if inner:
            segs.append(Segment(left=a, right=b, frame_indices=inner, one_sided=False))
    # 末尾端点区間
    last = anchors[-1]
    if last.frame_index < n_frames - 1:
        inner = tuple(range(last.frame_index + 1, n_frames))
        segs.append(Segment(left=last, right=None, frame_indices=inner, one_sided=True))
    return tuple(segs)


def _frame_result(
    res, frame: FrameSpec, j: int, phase_names: tuple[str, ...],
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> FrameRietveldResult:
    """runner 結果 → FrameRietveldResult (内側フレーム j 用)。"""
    cells: dict[str, Cell] = {k: tuple(v) for k, v in res.refined_cells.items()}  # type: ignore[misc]
    fracs = {n: float(res.phase_fractions.get(n, 0.0)) for n in phase_names}
    # 出版値 (重量分率 + esd) を phase_names へキーイングして貫通させる。GSAS が算出した相のみ含め
    # (present-guard)、非対応 runner/スタブは空 dict に縮退する (0.0 の偽 esd を捏造しない)。
    wfr = getattr(res, "phase_weight_fractions", {})
    wfr_esd = getattr(res, "phase_weight_fraction_esd", {})
    cesd_src = getattr(res, "cell_esd", {})
    weight_fracs = {n: float(wfr[n]) for n in phase_names if n in wfr}
    # 重量分率 esd は ``None`` (多相で未決定 = 捏造回避) を潰さず貫通させる (レビュー第6巡)。
    weight_frac_esd = {
        n: (None if wfr_esd[n] is None else float(wfr_esd[n]))
        for n in phase_names
        if n in wfr_esd
    }
    # 要素 None (格子未解放 = 値が決まっていない) を潰さない (`coerce_cell_esd` の docstring 参照)。
    cell_esd = {n: coerce_cell_esd(cesd_src[n]) for n in phase_names if n in cesd_src}
    # FR-318: alkali 診断 (機能無効なら空 = 既定値のまま)。
    alkali, _ = alkali_fields(frame.target_composition, charge_constraint, phase_names, res)
    return FrameRietveldResult(
        frame_index=j, axis_value=frame.axis_value, data_path=frame.data_path,
        rwp=float(res.final_rwp), gof=float(res.final_gof), refined_cells=cells,
        phase_fractions=fracs, phase_names=tuple(phase_names),
        validity_passed=res.validity.passed,
        refine_failed=not (float(res.final_rwp) < float("inf")),
        n_obs=int(getattr(res, "n_obs", 0)),
        phase_weight_fractions=weight_fracs, phase_weight_fraction_esd=weight_frac_esd,
        cell_esd=cell_esd,
        **alkali,  # type: ignore[arg-type]
    )


def _run_directional(
    anchor: Anchor, order: "list[int]", frames: "list[FrameSpec]", runner: AnchorRunner,
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> dict[int, FrameRietveldResult]:
    """アンカーの相集合/セル/**相分率**を初期値に order 順で warm-start 逐次精密化する。

    **セルと相分率は同時に進む** (Issue #96): 本パスは長らくセルしか運んでおらず、相分率は毎フレーム
    GSAS の等分 seed (2 相なら 0.50/0.50) から再出発していた。実測 (K₂Mn[Fe(CN)₆] 247 フレーム) では
    9 フレームが seed に**厳密に**張り付き (Rwp は 8.4-8.5% と平凡なので統計量には出ない)、うち 6 連続が
    tetragonal ドーム頂点の直前にあった。種はアンカーの `phase_fractions`、以降は直前フレームの精密化
    分率。分率を持たない runner (3 引数スタブ) には渡らない (`call_runner` が縮退, 非破壊)。
    """
    phases: tuple[PhaseSpec, ...] = anchor.phase_specs
    names = anchor.phase_names
    warm: dict[str, Cell] = dict(anchor.refined_cells)
    warm_fracs = seed_fractions(anchor.phase_fractions, names)
    out: dict[int, FrameRietveldResult] = {}
    for j in order:
        res = call_runner(runner, frames[j], phases, dict(warm), warm_fracs)
        fr = _frame_result(res, frames[j], j, names, charge_constraint)
        out[j] = fr
        if not fr.refine_failed:
            # 次フレームへ引き継ぎ (warm-start)。失敗フレームは据え置き (M9 逐次と同じ規律)。
            if fr.refined_cells:
                warm = {**warm, **fr.refined_cells}
            warm_fracs = seed_fractions(fr.phase_fractions, names) or warm_fracs
    return out


def refine_segment_forward(
    seg: Segment, frames: "list[FrameSpec] | tuple[FrameSpec, ...]", runner: AnchorRunner,
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> SegmentPass:
    """区間内側を左アンカーの相集合/セルで前方 (L→R, 昇順) に warm-start 逐次精密化する。

    左アンカーが無い先頭端点区間では前方パスは空 (bracket が右のみ)。
    """
    frames = list(frames)
    if seg.left is None or not seg.frame_indices:
        return SegmentPass(direction="forward", results={})
    order = sorted(seg.frame_indices)
    return SegmentPass(
        direction="forward",
        results=_run_directional(seg.left, order, frames, runner, charge_constraint),
    )


def refine_segment_backward(
    seg: Segment, frames: "list[FrameSpec] | tuple[FrameSpec, ...]", runner: AnchorRunner,
    charge_constraint: "ChargeConstraintConfig | None" = None,
) -> SegmentPass:
    """区間内側を右アンカーの相集合/セルで後方 (R→L, 降順) に warm-start 逐次精密化する。

    右アンカーが無い末尾端点区間では後方パスは空 (bracket が左のみ)。
    """
    frames = list(frames)
    if seg.right is None or not seg.frame_indices:
        return SegmentPass(direction="backward", results={})
    order = sorted(seg.frame_indices, reverse=True)
    return SegmentPass(
        direction="backward",
        results=_run_directional(seg.right, order, frames, runner, charge_constraint),
    )
