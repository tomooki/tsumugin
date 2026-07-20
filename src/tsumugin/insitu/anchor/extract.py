"""M10 アンカー抽出 — 相同定信頼度 (段階 A) → 実構造 Rietveld 確認 (段階 B) の 2 段ゲート (FR-331)。

信頼できるフレームを起点にするために、各フレームの相同定信頼度を合成スコアで評価し、高信頼フレームのみ
実構造 Rietveld で **Rwp 低 + 物理妥当性 pass** を確認して確定アンカーにする。単に「同定できた」と
「実際に良く精密化できる」は別物 (peak-rich 誤マッチ対策)。numpy-only コア (runner/identifier は注入)。

信頼性: 🔵 architecture.md §3 / REQ-1001〜1004。
"""

from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, Callable

from ...autorietveld.model import AutoRietveldResult, PhaseSpec, coerce_cell_esd
from ..model import Cell, ChargeConstraintConfig, FrameSpec
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
    charge_constraint: "ChargeConstraintConfig | None" = None,
    warn_sink: "list[str] | None" = None,
) -> Anchor:
    """段階 B: フレーム i を specs で実構造 Rietveld し Anchor 値を組む。

    FR-318 (REQ-318-006): `charge_constraint` 有効かつ frame に組成目標があるとき、
    **アンカー本体は制約なし (A)** で精密化し (精密化占有率 = x₀ 校正の情報源)、単相アンカーでは
    追加で**占有率を echem 目標に凍結した B** を精密化して ΔRwp を `ab_check` に記録する。
    ΔRwp 大 = クーロメトリー由来組成と回折の不整合 = 不可逆容量/x₀ 誤りの疑い (警告は engine 層)。
    """
    tc = frame.target_composition
    use_charge = (
        charge_constraint is not None and charge_constraint.enabled and tc is not None
    )
    # A (本アンカー): 制約なし — 目標を剥がして精密化する (アンカーの占有率を echem で汚さない)。
    frame_free = dataclasses.replace(frame, target_composition=None) if use_charge else frame
    res = runner(frame_free, specs, None)
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

    # FR-318: alkali 診断 (A 結果に対して) + 単相 A/B 検証
    alkali: dict[str, object] = {}
    ab_check: dict[str, float] | None = None
    if use_charge:
        from ..charge import alkali_fields, plan_frame_constraint  # 遅延 import (numpy-only)

        names = tuple(s.phase_name for s in specs)
        # A は**制約なし**で精密化した — 報告もそれに合わせ mode=diagnose で作る (レビュー M1:
        # tc.mode が fix/lock だと plan 再計算が「適用済み」を立て、docstring と矛盾する嘘になる)。
        tc_report = dataclasses.replace(tc, mode="diagnose")
        alkali, warns = alkali_fields(tc_report, charge_constraint, names, res)
        if warn_sink is not None:
            for w in warns:
                if w not in warn_sink:
                    warn_sink.append(w)
        if len(specs) == 1 and float(res.final_rwp) < float("inf"):
            tc_fix = dataclasses.replace(tc, mode="fix")
            # B の fix 計画が実際に組める場合のみ A/B を実施する (レビュー #8: 計画が縮退
            # [x 範囲外→占有率不能等] すると B ≡ A の空比較を「実施済み」と記録してしまう)。
            plan_b = plan_frame_constraint(tc_fix, charge_constraint, names)
            if plan_b.applied == "fix":
                frame_fixed = dataclasses.replace(frame, target_composition=tc_fix)
                res_b = runner(frame_fixed, specs, None)
                if float(res_b.final_rwp) < float("inf"):
                    ab_check = {
                        "rwp_free": float(res.final_rwp),
                        "rwp_constrained": float(res_b.final_rwp),
                        "delta_rwp": float(res_b.final_rwp) - float(res.final_rwp),
                    }
                    x_a = alkali.get("alkali_x_xrd")
                    if isinstance(x_a, (int, float)):
                        # 【x の由来を偽らない】(レビュー M2): A の占有率が実際に精密化された
                        # (esd が付いた) ときのみ "x_refined"。既定 (占有率グループ非宣言) では
                        # 占有率は CIF 固定値なので "x_model" — x₀ 校正の根拠にはならない
                        # (校正したいなら anchor 相の PhaseSpec に free_occupancy_labels を設定)。
                        refined = alkali.get("alkali_x_xrd_esd") is not None
                        ab_check["x_refined" if refined else "x_model"] = float(x_a)
                    ab_check["x_echem"] = float(tc.total)
            elif warn_sink is not None:
                for w in plan_b.warnings:
                    if w not in warn_sink:
                        warn_sink.append(w)

    return Anchor(
        frame_index=i, axis_value=frame.axis_value, phase_specs=tuple(specs),
        refined_cells=cells, rwp=float(res.final_rwp), gof=float(res.final_gof),
        phase_fractions=fracs, confidence=float(confidence), validity_passed=res.validity.passed,
        n_obs=int(getattr(res, "n_obs", 0)), fallback=fallback,
        phase_weight_fractions=wfracs, phase_weight_fraction_esd=wfrac_esd, cell_esd=cesd,
        alkali=alkali, ab_check=ab_check,
    )


def extract_anchors(
    frames: "list[FrameSpec] | tuple[FrameSpec, ...]",
    base_phases: "list[PhaseSpec] | tuple[PhaseSpec, ...]",
    *,
    runner: AnchorRunner,
    identifier: Identifier | None = None,
    cfg: AnchorConfig = AnchorConfig(),
    charge_constraint: "ChargeConstraintConfig | None" = None,
    warn_sink: "list[str] | None" = None,
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
        return (
            _refine_anchor(
                0, frames[0], base, runner, confidence=0.0, fallback=True,
                charge_constraint=charge_constraint, warn_sink=warn_sink,
            ),
        )

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
        a = _refine_anchor(
            i, frames[i], specs, runner, confidence=conf,
            charge_constraint=charge_constraint, warn_sink=warn_sink,
        )
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
                       confidence=best_conf, fallback=True,
                       charge_constraint=charge_constraint, warn_sink=warn_sink),
    )
