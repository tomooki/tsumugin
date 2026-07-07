"""M11 逐次減算同定 — 単相/多相を区別しない統一エントリ (FR-118)。

未知パターンは単相か多相か事前に分からないため、残差に対する反復同定 (search-match-subtract) で単一
エントリに統一する。相数を入力に要求せず、単相は k=1 で自然停止する。

反復1周:
- **提案** — 現残差に `identify_phases` (異方 rerank 既定 on) を実行し次の1相候補を得る。
- **受理 (高速段)** — 全採用相 + 候補を `fit_nonneg_scales` で原パターンへ joint 非負スケール再フィットし、
  未説明強度が相対 `eps_gain` 超減り候補スケール > `scale_min` の候補のみ採る。
- **減算** — 残差 = 原パターン − Σ 採用相モデル (毎回原パターンから; 貪欲減算の誤差蓄積を断つ)。
- **停止** — 残差 S/N (`residual_significance`) < `snr_stop`、または全候補棄却。

decoy (既説明ピークのみの元素部分集合相等) は joint fit でスケール≈0 → `eps_gain` 未達で自然棄却される
(hard 化学ガードに依らない)。化学的妥当性はコアに含めず第3層に委ねる (opt-in `require_elements` のみ)。
多形判別は**注入した実 Rietveld (`refiner`)** を相同定内で呼んで確定する (深段, FR-118-5)。

numpy-only コア。`identify_phases` の rerank / provider / refiner の内側で pymatgen/GSAS が遅延 import される。
信頼性: 🔵 `docs/design/m11-iterative-identification/architecture.md`。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from ..store.ledger import Ledger
from .engine import identify_phases, preprocess_intensity
from .grouping import PhaseMatchGroup, group_by_composition
from .model import PhaseMatch, ReferencePhase
from .provider import ReferenceProvider
from .scale import fit_nonneg_scales
from .significance import residual_significance

__all__ = [
    "IdentifyConfig",
    "AcceptedPhase",
    "IterationRecord",
    "IterativeIdentification",
    "RietveldRefiner",
    "identify_pattern",
    "refine_polymorphs",
]

# 注入 Rietveld backend: 相集合 (ReferencePhase 列) → 真 Rwp。深段の多形裁定 (FR-118-5, GSAS は内側)。
RietveldRefiner = Callable[[Sequence[ReferencePhase]], float]


@dataclass(frozen=True)
class IdentifyConfig:
    """逐次減算同定の設定 (第1/2層の決定論パラメータのみ; 第3層の判断は含まない)。"""

    max_phases: int = 5          # 反復上限 (安全網; 実際は snr_stop が停止を決める)
    snr_stop: float = 5.0        # 残差 S/N がこの未満で停止 (5σ = 結晶学の標準検出閾値)
    eps_gain: float = 0.02       # 受理に要する未説明強度の相対減少 (過剰適合ガード)
    scale_min: float = 1e-3      # 受理に要する候補の最小スケール (decoy=0 を弾く)
    try_k: int = 3               # 各周で試す提案候補数
    fwhm: float = 0.15           # プロファイル合成の半値幅 (度)
    smooth_window: int = 5       # 残差 S/N の移動平均窓
    subtract_bg: bool = True     # SNIP 背景減算
    bg_max_window: int = 50
    refine_lattice: bool = True  # 提案時の等方格子整合
    rerank_top_k: int = 5        # 提案時の異方 rerank (層1 既定)
    require_elements: Sequence[str] | None = None  # opt-in 全元素系 hard ガード (第3層; 既定なし)
    always_refine: bool = False  # 深段 Rietveld を常時適用 (既定は僅差多形時のみ)
    polymorph_margin: float = 0.05  # 同組成 score 差がこれ未満なら深段裁定対象


@dataclass(frozen=True)
class AcceptedPhase:
    """受理された1相 (参照相 + joint スケール + 提案スコア)。"""

    reference: ReferencePhase
    scale: float
    score: float
    source: str = "iterative"

    @property
    def phase_id(self) -> str:
        return self.reference.phase_id

    @property
    def formula(self) -> str:
        return self.reference.formula


@dataclass(frozen=True)
class IterationRecord:
    """1 反復の記録 (受理相 + 未説明強度の減少 + 残差 S/N)。"""

    k: int
    accepted_id: str | None
    gain: float
    scale: float
    max_snr: float


@dataclass(frozen=True)
class IterativeIdentification:
    """逐次減算同定の結果。"""

    accepted: tuple[AcceptedPhase, ...]
    residual_two_theta: tuple[float, ...]
    residual_intensity: tuple[float, ...]
    groups: tuple[PhaseMatchGroup, ...]
    refined: bool
    iterations: tuple[IterationRecord, ...]
    final_max_snr: float
    ledger: object | None = None

    @property
    def phase_ids(self) -> tuple[str, ...]:
        return tuple(a.phase_id for a in self.accepted)


def _peaklist(ref: ReferencePhase) -> list[tuple[float, float]]:
    return [(float(p.position), float(p.height)) for p in ref.peaks]


def _as_matches(accepted: Sequence[AcceptedPhase]) -> tuple[PhaseMatch, ...]:
    return tuple(
        PhaseMatch(reference=a.reference, score=a.score, matched_observed=(), extra_calculated=())
        for a in accepted
    )


def identify_pattern(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    provider: ReferenceProvider,
    *,
    elements: Sequence[str],
    known_phases: Sequence[ReferencePhase] = (),
    refiner: RietveldRefiner | None = None,
    cfg: IdentifyConfig = IdentifyConfig(),
    ledger: Ledger | None = None,
) -> IterativeIdentification:
    """未知パターン + 元素から相集合を逐次減算同定する (単相/多相統一, FR-118)。"""
    ledger = ledger if ledger is not None else Ledger()
    tt = np.asarray(two_theta, dtype=float)
    raw = np.asarray(intensity, dtype=float)
    # 計数統計 σ (背景減算前の生強度から)。停止判定 (残差 S/N) に使う。
    sigma = np.sqrt(np.clip(raw, 1.0, None))
    obs = preprocess_intensity(raw, subtract_bg=cfg.subtract_bg, bg_max_window=cfg.bg_max_window)

    accepted_refs: list[ReferencePhase] = list(known_phases)
    accepted_scores: list[float] = [0.0] * len(accepted_refs)
    accepted_ids: set[str] = {r.phase_id for r in accepted_refs}
    peaklists: list[list[tuple[float, float]]] = [_peaklist(r) for r in accepted_refs]
    seen_matches: list[PhaseMatch] = []

    s, model, _resid, ss_prev = _fit(tt, obs, peaklists, cfg.fwhm)
    iterations: list[IterationRecord] = []

    for k in range(cfg.max_phases):
        resid = obs - model
        sig = residual_significance(tt, resid, sigma, smooth_window=cfg.smooth_window)
        if not sig.warrants_new_phase(cfg.snr_stop):
            break  # 全て説明済 (単相は k=1 で停止)

        ident = identify_phases(
            tt, resid, provider, elements=elements, subtract_bg=False,
            refine_lattice=cfg.refine_lattice, rerank_top_k=cfg.rerank_top_k,
            require_elements=cfg.require_elements,
        )
        best: tuple | None = None  # (cand_ref, match, s2, ss2, model2, gain)
        for match in ident.matches[: cfg.try_k]:
            cand = match.reference
            seen_matches.append(match)
            if cand.phase_id in accepted_ids:
                continue
            s2, model2, _r2, ss2 = _fit(tt, obs, peaklists + [_peaklist(cand)], cfg.fwhm)
            gain = (ss_prev - ss2) / ss_prev if ss_prev > 0 else 0.0
            cscale = float(s2[-1])
            improves = cscale > cfg.scale_min and gain > cfg.eps_gain
            wins = best is None or ss2 < best[3]
            ledger.append("m11_trial", {
                "k": k, "phase": cand.phase_id, "scale": cscale, "gain": gain,
                "accepted": bool(improves and wins),
            })
            if improves and wins:
                best = (cand, match, s2, ss2, model2, gain)
        if best is None:
            break  # 全候補棄却で停止

        cand, match, s2, ss2, model2, gain = best
        accepted_refs.append(cand)
        peaklists.append(_peaklist(cand))
        accepted_ids.add(cand.phase_id)
        accepted_scores.append(float(match.score))
        ss_prev, model = ss2, model2
        iterations.append(IterationRecord(k, cand.phase_id, gain, float(s2[-1]), sig.max_snr))

    # 最終 joint フィットで全相スケールを確定
    s_final, model_final, _rf, _ss = _fit(tt, obs, peaklists, cfg.fwhm)
    accepted = tuple(
        AcceptedPhase(reference=r, scale=float(sc), score=float(scr))
        for r, sc, scr in zip(accepted_refs, _scales(s_final, len(accepted_refs)), accepted_scores)
    )

    refined = False
    if refiner is not None and accepted:
        accepted, refined, model_final = _refine_and_remodel(
            tt, obs, accepted, seen_matches, refiner, cfg, ledger
        )

    groups = group_by_composition(_as_matches(accepted))
    final_sig = residual_significance(tt, obs - model_final, sigma, smooth_window=cfg.smooth_window)
    ledger.append("m11_done", {"phases": [a.phase_id for a in accepted], "refined": refined})
    return IterativeIdentification(
        accepted=accepted, residual_two_theta=tuple(map(float, tt)),
        residual_intensity=tuple(map(float, obs - model_final)), groups=groups,
        refined=refined, iterations=tuple(iterations), final_max_snr=float(final_sig.max_snr),
        ledger=ledger,
    )


def _fit(tt, obs, peaklists, fwhm):
    if not peaklists:
        resid = obs.copy()
        return (np.zeros(0), np.zeros_like(obs), resid, float(np.sum(np.clip(resid, 0.0, None) ** 2)))
    return fit_nonneg_scales(tt, obs, peaklists, fwhm)


def _scales(s: np.ndarray, n: int) -> list[float]:
    return [float(s[i]) for i in range(n)] if s.size == n else [0.0] * n


def refine_polymorphs(
    accepted: Sequence[AcceptedPhase],
    seen_matches: Sequence[PhaseMatch],
    refiner: RietveldRefiner,
    cfg: IdentifyConfig,
    ledger: Ledger,
) -> tuple[tuple[AcceptedPhase, ...], bool]:
    """同組成多形を注入 Rietveld で裁定し、真 Rwp 最良の多形へ受理相を差し替える (深段, FR-118-5)。

    各受理相について、同一組成で score 差 < `polymorph_margin` の代替候補 (seen_matches 由来) を集め、
    その相を代替へ swap した相集合の真 Rwp を `refiner` で評価。base より低 Rwp の swap を採用する。
    `always_refine=False` なら代替がある相のみ評価 (コスト配慮)。決定論・Rietveld 失敗は inf で無視。
    """
    base_refs = [a.reference for a in accepted]
    groups = group_by_composition(tuple(seen_matches))
    # 各相の同組成代替候補 (score 差 < polymorph_margin) を前計算 (決定論順・重複 id 除去)
    alts_by_i: list[list[ReferencePhase]] = []
    for a in accepted:
        alts = [
            m.reference
            for g in groups if g.formula == a.formula
            for m in g.members
            if m.reference.phase_id != a.phase_id
            and abs(float(m.score) - float(a.score)) < cfg.polymorph_margin
        ]
        seen_ids: set[str] = set()
        alts_by_i.append([r for r in alts if not (r.phase_id in seen_ids or seen_ids.add(r.phase_id))])

    best_refs = list(base_refs)

    def _rwp(refs) -> float:
        try:
            return float(refiner(refs))
        except Exception:
            return float("inf")

    best_rwp = _rwp(best_refs)
    changed = False
    # 【固定点反復】: ある相の swap 判定は他相の暫定選択に依存する (flaky refiner や相互作用)。
    #   1 パスでは順序依存で取りこぼすため、改善が無くなるまで繰り返す (best_rwp 単調減で必ず停止)。
    improved = True
    while improved:
        improved = False
        for i in range(len(accepted)):
            if not alts_by_i[i] and not cfg.always_refine:
                continue
            for alt in alts_by_i[i]:
                if best_refs[i].phase_id == alt.phase_id:
                    continue
                trial = list(best_refs)
                trial[i] = alt
                rwp = _rwp(trial)
                ledger.append("m11_refine", {
                    "swap_from": best_refs[i].phase_id, "swap_to": alt.phase_id,
                    "rwp": rwp, "base_rwp": best_rwp, "accepted": bool(rwp < best_rwp - 1e-9),
                })
                if rwp < best_rwp - 1e-9:
                    best_rwp = rwp
                    best_refs[i] = alt
                    changed = True
                    improved = True
    if not changed:
        return tuple(accepted), False
    new_accepted = tuple(
        AcceptedPhase(reference=r, scale=a.scale, score=a.score, source="iterative+rietveld")
        for r, a in zip(best_refs, accepted)
    )
    return new_accepted, True


def _refine_and_remodel(tt, obs, accepted, seen_matches, refiner, cfg, ledger):
    """深段裁定を実行し、差し替え後に model を再合成して返す。"""
    new_accepted, refined = refine_polymorphs(accepted, seen_matches, refiner, cfg, ledger)
    if not refined:
        s, model, _r, _ss = _fit(tt, obs, [_peaklist(a.reference) for a in accepted], cfg.fwhm)
        return accepted, False, model
    s, model, _r, _ss = _fit(tt, obs, [_peaklist(a.reference) for a in new_accepted], cfg.fwhm)
    # スケールを再フィット値で更新
    rescaled = tuple(
        AcceptedPhase(reference=a.reference, scale=float(sc), score=a.score, source=a.source)
        for a, sc in zip(new_accepted, _scales(s, len(new_accepted)))
    )
    return rescaled, True, model
