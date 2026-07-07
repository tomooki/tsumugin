"""M10 crossover 経路選定 — 区間の前方/後方フィットを IC (bic) で比較し最良経路を選ぶ (FR-334)。

**設計判断①**: 相集合が異なる前方 (少数相) / 後方 (多相) の比較は **Rwp 生値でなく bic** で行う。
Rwp は自由パラメータ増で単調減少するため、相数の多い後方が必ず勝ち偽相を全域へ広げてしまう。bic は
パラメータ数を罰するので、真に説明力がある転移後のフレームでのみ後方 (新相あり) が勝つ。

- **同一相集合**の区間: パラメータ数が同じ → Rwp 比較は公平 → 毎フレーム Rwp 最小を採用。
- **異相集合**の区間: 区間の**総 bic を最小化する crossover 点**を全探索。L..k は前方 (新相なし)・
  k+1..R は後方 (新相あり) を採用 → 相分率が単調な転移経路。同点は単調性で tie-break。
- **片方向** (端点区間 or 片パス空): 存在する方を全採用。

bic は `AutoRietveldResult` に n_params/chi2 が無いため `chi2 ≈ gof²·(n_obs−n_params)` と相数ベースの
n_params 推定 (base + per_phase·相数) で再構成する (operando `_frame_bic` と同式)。相数ペナルティのみが
前方/後方比較を分けるため、n_params の絶対精度は不要。numpy-only。

信頼性: 🔵 architecture.md §5 / REQ-1009〜1011。
"""

from __future__ import annotations

import math

from ..model import FrameRietveldResult
from .model import AnchorConfig, CrossoverChoice, Segment, SegmentPass

__all__ = ["frame_bic", "select_crossover", "assemble_path"]


def frame_bic(fr: FrameRietveldResult, cfg: AnchorConfig) -> float:
    """フレーム結果の bic = chi2 + n_params·ln(n_obs)。chi2=gof²·(n_obs−n_params)。

    n_params = base_params + per_phase_params·相数。n_obs=0 (未設定) or gof 非有限は inf に縮退させず
    penalty=0 の縮退 bic (=chi2) を返す (テストスタブは n_obs を設定して相数ペナルティを効かせる)。
    """
    if not math.isfinite(fr.gof) or fr.refine_failed:
        return float("inf")
    n_obs = max(int(fr.n_obs), 1)
    n_params = cfg.base_params + cfg.per_phase_params * max(len(fr.phase_names), 1)
    dof = max(n_obs - n_params, 1)
    chi2 = fr.gof * fr.gof * dof
    return chi2 + n_params * math.log(n_obs)


def _new_phase_fraction(fr: FrameRietveldResult, new_phases: "frozenset[str]") -> float:
    return sum(float(fr.phase_fractions.get(p, 0.0)) for p in new_phases)


def _is_monotonic(
    inner: "list[int]", s: int, fwd: "dict[int, FrameRietveldResult]",
    bwd: "dict[int, FrameRietveldResult]", new_phases: "frozenset[str]",
) -> bool:
    """crossover 位置 s で組んだ経路の新相分率が非減少 (転移方向に単調増加) か。"""
    fracs = []
    for idx, j in enumerate(inner):
        src = fwd if idx < s else bwd
        fr = src.get(j)
        fracs.append(_new_phase_fraction(fr, new_phases) if fr is not None else 0.0)
    return all(fracs[i] <= fracs[i + 1] + 1e-9 for i in range(len(fracs) - 1))


def select_crossover(
    seg: Segment, fwd: SegmentPass, bwd: SegmentPass, cfg: AnchorConfig = AnchorConfig(),
) -> CrossoverChoice:
    """区間の前方/後方パスから採用経路 (crossover) を決める。"""
    inner = list(seg.frame_indices)
    fr_, br_ = dict(fwd.results), dict(bwd.results)
    have_f = any(j in fr_ for j in inner)
    have_b = any(j in br_ for j in inner)

    if not inner or (not have_f and not have_b):
        return CrossoverChoice(None, float("inf"), reason="empty")

    # 片方向のみ (端点区間 or 片パス空) → 存在する方を全採用
    if have_f != have_b:
        src = fr_ if have_f else br_
        tb = sum(frame_bic(src[j], cfg) for j in inner if j in src)
        return CrossoverChoice(None, tb, reason="single_direction")

    left_names = frozenset(seg.left.phase_names) if seg.left is not None else frozenset()
    right_names = frozenset(seg.right.phase_names) if seg.right is not None else frozenset()

    # 同一相集合 → 毎フレーム Rwp 最小 (パラメータ数同一で公平)
    if left_names == right_names:
        tb = sum(min(fr_[j].rwp, br_[j].rwp) for j in inner)
        return CrossoverChoice(None, tb, reason="rwp_per_frame")

    # 異相集合 → 総 bic 最小の crossover を全探索 (s = 前方採用する先頭フレーム数)
    new_phases = right_names - left_names
    fb = [frame_bic(fr_[j], cfg) for j in inner]
    bb = [frame_bic(br_[j], cfg) for j in inner]
    m = len(inner)
    best_tb = float("inf")
    best_s = 0
    best_mono = False
    for s in range(0, m + 1):
        tb = sum(fb[:s]) + sum(bb[s:])
        mono = _is_monotonic(inner, s, fr_, br_, new_phases)
        if tb < best_tb - 1e-9:
            best_tb, best_s, best_mono = tb, s, mono
        elif tb <= best_tb + cfg.bic_tie and mono and not best_mono:
            best_s, best_mono = s, mono  # 同点内は単調な s を優先 (best_tb は据え置き)
    crossover_frame = inner[best_s - 1] if best_s > 0 else None
    onset_frame = inner[best_s] if best_s < m else None
    return CrossoverChoice(
        crossover_frame=crossover_frame, total_bic=best_tb, onset_frame=onset_frame,
        monotonic=best_mono, reason="bic_crossover",
    )


def assemble_path(
    seg: Segment, fwd: SegmentPass, bwd: SegmentPass, choice: CrossoverChoice,
) -> dict[int, FrameRietveldResult]:
    """選定結果に従い内側フレーム番号→採用 FrameRietveldResult を組む。"""
    inner = list(seg.frame_indices)
    fr_, br_ = dict(fwd.results), dict(bwd.results)
    out: dict[int, FrameRietveldResult] = {}

    if choice.reason == "single_direction":
        src = fr_ if any(j in fr_ for j in inner) else br_
        for j in inner:
            if j in src:
                out[j] = src[j]
        return out
    if choice.reason == "rwp_per_frame":
        for j in inner:
            f, b = fr_[j], br_[j]
            out[j] = f if f.rwp <= b.rwp else b
        return out
    if choice.reason == "bic_crossover":
        s = 0 if choice.crossover_frame is None else inner.index(choice.crossover_frame) + 1
        for idx, j in enumerate(inner):
            out[j] = fr_[j] if idx < s else br_[j]
        return out
    return out
