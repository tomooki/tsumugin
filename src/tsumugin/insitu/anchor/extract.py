"""M10 アンカー抽出 — 相同定信頼度 (段階 A) → 実構造 Rietveld 確認 (段階 B) の 2 段ゲート (FR-331)。

信頼できるフレームを起点にするために、各フレームの相同定信頼度を合成スコアで評価し、高信頼フレームのみ
実構造 Rietveld で **Rwp 低 + 物理妥当性 pass** を確認して確定アンカーにする。単に「同定できた」と
「実際に良く精密化できる」は別物 (peak-rich 誤マッチ対策)。numpy-only コア (runner/identifier は注入)。

信頼性: 🔵 architecture.md §3 / REQ-1001〜1004。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from ...autorietveld.model import AutoRietveldResult, PhaseSpec, coerce_cell_esd
from ..model import Cell, FrameSpec
from .model import Anchor, AnchorConfig

if TYPE_CHECKING:  # 型注釈のみ (実行時 import を避け reference 依存を持たない)
    from ...reference.model import PhaseIdentification

__all__ = ["anchor_confidence", "extract_anchors", "Identifier", "AnchorRunner"]

# identifier: フレーム → (合成信頼度, 相集合 specs)。None は同定不可 (base 相のみ・信頼度 0)。
Identifier = Callable[[FrameSpec], "tuple[float, tuple[PhaseSpec, ...]] | None"]
# runner: (frame, phases, initial_cells) → AutoRietveldResult (M9 と同一契約)
AnchorRunner = Callable[[FrameSpec, tuple[PhaseSpec, ...], "dict[str, Cell] | None"], AutoRietveldResult]


def anchor_confidence(ident: "PhaseIdentification", cfg: AnchorConfig) -> float:
    """相同定結果の合成信頼度 = w_score·score + w_margin·margin − w_strain·strain − w_unknown·unknown。

    - score: 首位候補の Dara スコア (絶対品質)
    - margin: 首位−次点のスコア差を margin_cap で飽和 (一意性; 単相域ほど大)
    - strain: 首位候補の格子乖離 (小=良; DFT 参照との齟齬)
    - unknown: 未マッチで未知相フラグが立つ場合のペナルティ

    matches が空なら 0.0。duck-typing で reference 型に実行時依存しない。
    """
    matches = tuple(getattr(ident, "matches", ()))
    if not matches:
        return 0.0
    top = matches[0]
    score = float(getattr(top, "score", 0.0))
    if len(matches) > 1:
        margin = score - float(getattr(matches[1], "score", 0.0))
    else:
        margin = score
    margin = max(0.0, min(margin, cfg.margin_cap))
    strain = abs(float(getattr(top, "strain", 0.0)))
    unmatched = getattr(ident, "unmatched", None)
    unknown = 1.0 if getattr(unmatched, "has_unknown", False) else 0.0
    return (
        cfg.w_score * score
        + cfg.w_margin * margin
        - cfg.w_strain * strain
        - cfg.w_unknown * unknown
    )


def _refine_anchor(
    i: int, frame: FrameSpec, specs: tuple[PhaseSpec, ...], runner: AnchorRunner,
    *, confidence: float, fallback: bool = False,
) -> Anchor:
    """段階 B: フレーム i を specs で実構造 Rietveld し Anchor 値を組む。"""
    res = runner(frame, specs, None)
    cells: dict[str, Cell] = {k: tuple(v) for k, v in res.refined_cells.items()}  # type: ignore[misc]
    fracs = {k: float(v) for k, v in res.phase_fractions.items()}
    # 出版値 (重量分率 + esd) は段階 B の AutoRietveldResult から Anchor へ貫通させる
    # (Anchor 経由でしか出力フレームに届かないため; 空/非対応 runner は既定空 dict に縮退)。
    wfracs = {k: float(v) for k, v in getattr(res, "phase_weight_fractions", {}).items()}
    # esd の ``None`` (多相で未決定 = 捏造回避) を潰さず貫通させる (レビュー第6巡)。
    wfrac_esd = {
        k: (None if v is None else float(v))
        for k, v in getattr(res, "phase_weight_fraction_esd", {}).items()
    }
    # 要素 None (格子未解放 = 値が決まっていない) を潰さない (`coerce_cell_esd` の docstring 参照)。
    cesd = {k: coerce_cell_esd(v) for k, v in getattr(res, "cell_esd", {}).items()}
    return Anchor(
        frame_index=i, axis_value=frame.axis_value, phase_specs=tuple(specs),
        refined_cells=cells, rwp=float(res.final_rwp), gof=float(res.final_gof),
        phase_fractions=fracs, confidence=float(confidence), validity_passed=res.validity.passed,
        n_obs=int(getattr(res, "n_obs", 0)), fallback=fallback,
        phase_weight_fractions=wfracs, phase_weight_fraction_esd=wfrac_esd, cell_esd=cesd,
    )


def extract_anchors(
    frames: "list[FrameSpec] | tuple[FrameSpec, ...]",
    base_phases: "list[PhaseSpec] | tuple[PhaseSpec, ...]",
    *,
    runner: AnchorRunner,
    identifier: Identifier | None = None,
    cfg: AnchorConfig = AnchorConfig(),
) -> tuple[Anchor, ...]:
    """確定アンカー列 (フレーム順) を返す。

    - **identifier=None** (相同定無効, REQ-1004): frame 0 を単一 fallback アンカーとし M9 前方単一パスに縮退。
    - **段階 A**: 各フレームの (信頼度, 相集合) を identifier で得る。
    - **段階 B**: 信頼度 ≥ `anchor_confidence_min` の候補のみ実構造 Rietveld し、`Rwp ≤ anchor_rwp_max`
      ∧ 妥当性 pass のフレームを確定アンカーに (REQ-1001/1002)。段階 B は候補のみ精密化 (全 refine を回避)。
    - **fallback** (REQ-1003): 確定 0 個なら最高信頼フレームを 1 個精密化して単一アンカーにする (全フレーム
      refine で最小 Rwp を厳密探索する代わりの代理; 系列は常に解析可能)。
    """
    frames = list(frames)
    base = tuple(base_phases)
    if not frames:
        return ()

    # REQ-1004: 相同定無効 → frame 0 単一アンカー (M9 相当)
    if identifier is None:
        return (_refine_anchor(0, frames[0], base, runner, confidence=0.0, fallback=True),)

    # 段階 A: 全フレームの信頼度 + 相集合
    screened: list[tuple[int, float, tuple[PhaseSpec, ...]]] = []
    for i, frame in enumerate(frames):
        out = identifier(frame)
        if out is None:
            conf, specs = 0.0, base
        else:
            conf = float(out[0])
            specs = tuple(out[1]) or base
        screened.append((i, conf, specs))

    # 段階 B: 高信頼候補のみ実構造 Rietveld で確認
    anchors: list[Anchor] = []
    for i, conf, specs in screened:
        if conf < cfg.anchor_confidence_min:
            continue
        a = _refine_anchor(i, frames[i], specs, runner, confidence=conf)
        # 高温/時間系列では室温 CIF 基準の validity が正当な格子伸長を fail するため既定で課さない
        # (M9 H1 と同根)。Rwp + 信頼度でアンカーを確定する。
        if a.rwp <= cfg.anchor_rwp_max and (not cfg.require_anchor_validity or a.validity_passed):
            anchors.append(a)
    if anchors:
        return tuple(anchors)

    # fallback: 最高信頼フレーム 1 個 (確定 0 でも系列を解析可能に)
    best_i, best_conf, best_specs = max(screened, key=lambda t: t[1])
    return (
        _refine_anchor(best_i, frames[best_i], best_specs, runner,
                       confidence=best_conf, fallback=True),
    )
