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

信頼性: 🔵 architecture.md §5 (経路選定, REQ-1009〜1011) / §6 (結合距離ゲート, FR-335/REQ-1013)。
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Callable

from ..model import FrameRietveldResult
from .model import AnchorConfig, CrossoverChoice, Segment, SegmentPass

if TYPE_CHECKING:  # 型注釈専用 — 実行時 import は遅延させ numpy-only を保つ
    from typing import Mapping

    from ...autorietveld.model import PhaseSpec, ValidityReport

    BondChecker = Callable[..., "ValidityReport"]

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


def _bond_ok_frame(
    fr: FrameRietveldResult,
    specs: "Mapping[str, PhaseSpec]",
    cfg: AnchorConfig,
    checker: "BondChecker",
    cache: dict[tuple[str, int], bool],
    direction: str,
) -> bool:
    """フレームの全相の結合距離/配位数が妥当か (相ごとに精密化セルで検査)。

    構造パス不明の相は検査不能として skip する (偽陰性で経路を落とさない)。1 相でも fail なら False。
    メモ化する — pymatgen 構造読込は高価で、同じフレームが複数の crossover 候補で再評価されるため。
    **キーは (方向, frame_index)**: 同一フレームでも前方 (相少) と後方 (相多) は相集合もセルも
    別物なので、frame_index だけでメモ化すると一方の判定を他方に誤用して健全な経路を棄却する。
    """
    key = (direction, fr.frame_index)
    if key in cache:
        return cache[key]
    ok = True
    for name in fr.phase_names:
        spec = specs.get(name)
        if spec is None:
            continue
        report = checker(
            spec.structure_path, fr.refined_cells.get(name),
            bond_tol_lo=cfg.bond_tol_lo, bond_tol_hi=cfg.bond_tol_hi,
        )
        if not report.passed:
            ok = False
            break
    cache[key] = ok
    return ok


def select_crossover(
    seg: Segment, fwd: SegmentPass, bwd: SegmentPass, cfg: AnchorConfig = AnchorConfig(),
    bond_checker: "BondChecker | None" = None,
) -> CrossoverChoice:
    """区間の前方/後方パスから採用経路 (crossover) を決める。

    :param bond_checker: 結合妥当性判定の注入 (**テスト注入専用**)。None なら
        `autorietveld.validity.check_bond_validity` (pymatgen 遅延 import)。実運用の設定経路は
        `AnchorConfig.require_bond_validity` / `bond_tol_lo` / `bond_tol_hi` で、② `anchored_sequential`
        の `anchor_config` JSON から到達する (callable を ③ に要求しない)。
    """
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
    cands: list[tuple[int, float, bool]] = []
    for s in range(0, m + 1):
        tb = sum(fb[:s]) + sum(bb[s:])
        mono = _is_monotonic(inner, s, fr_, br_, new_phases)
        cands.append((s, tb, mono))
        if tb < best_tb - 1e-9:
            best_tb, best_s, best_mono = tb, s, mono
        elif tb <= best_tb + cfg.bic_tie and mono and not best_mono:
            best_s, best_mono = s, mono  # 同点内は単調な s を優先 (best_tb は据え置き)

    # --- FR-335 結合距離/配位数ゲート (REQ-1013) ---
    # bic は「相を増やせば残差は下がる」を罰するが、**増やした相の構造が物理的に有り得るか**は見ない。
    # 崩壊セルの偽相が僅差で勝つ実データ病理 (K₂Mn[Fe(CN)₆]) を、crossover 近傍フレームの
    # 結合距離で棄却する。異相集合 crossover 限定 — 相集合が同一な区間には偽相の混入余地が無い。
    bond_gate = ""
    if cfg.require_bond_validity:
        checker = bond_checker
        if checker is None:
            from ...autorietveld.validity import check_bond_validity as checker  # 遅延 import
        specs = {}
        for anc in (seg.left, seg.right):
            if anc is not None:
                for sp in anc.phase_specs:
                    specs.setdefault(sp.phase_name, sp)
        cache: dict[tuple[str, int], bool] = {}

        def _ok(s: int) -> bool:
            """crossover 近傍 (直前の前方採用フレーム / 直後の後方採用フレーム) が結合妥当か。"""
            frames: list[tuple[str, object]] = []
            if s > 0 and inner[s - 1] in fr_:
                frames.append(("forward", fr_[inner[s - 1]]))
            if s < m and inner[s] in br_:
                frames.append(("backward", br_[inner[s]]))
            return all(
                _bond_ok_frame(f, specs, cfg, checker, cache, direction=d) for d, f in frames
            )

        if _ok(best_s):
            bond_gate = "kept"
        else:
            # 僅差帯 (bic_tie 以内) を走査し最初に結合妥当な候補を採る。
            # **並び順は「単調 → bic 昇順 → s 昇順」**: bic だけで並べると、僅差帯に非単調だが
            # bic 最小の候補があるとそれを掴み、相分率が増減を繰り返す非物理な経路を
            # ゲート ON のときだけ再導入してしまう (REQ-1011 の単調性 tie-break の回帰)。
            band = sorted(
                ((tb, s, mono) for s, tb, mono in cands if tb <= best_tb + cfg.bic_tie),
                key=lambda t: (not t[2], t[0], t[1]),
            )
            bond_gate = "no_valid_candidate"
            for tb, s, mono in band:
                if _ok(s):
                    best_s, best_mono = s, mono
                    bond_gate = "moved"
                    break

    crossover_frame = inner[best_s - 1] if best_s > 0 else None
    onset_frame = inner[best_s] if best_s < m else None
    # total_bic は**採用経路**の bic を報告する。`best_tb` は僅差帯の基準点 (raw bic 最小) として
    # 走査中ずっと据え置く必要があるので、報告値とは別物 — 単調性 tie-break や結合ゲートで採用 s が
    # 動いたとき、best_tb をそのまま返すと**棄却した別経路の bic** を渡すことになる。③ は
    # `crossovers[].total_bic` で相数選定を検算すると教わっているため、食い違うと検算が狂う。
    adopted_tb = cands[best_s][1]
    return CrossoverChoice(
        crossover_frame=crossover_frame, total_bic=adopted_tb, onset_frame=onset_frame,
        monotonic=best_mono, reason="bic_crossover", bond_gate=bond_gate,
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
