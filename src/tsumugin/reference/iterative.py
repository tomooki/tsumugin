"""M11 逐次減算同定 — 単相/多相を区別しない統一エントリ (FR-118)。

未知パターンは単相か多相か事前に分からないため、残差に対する反復同定 (search-match-subtract) で単一
エントリに統一する。相数を入力に要求せず、単相は k=1 で自然停止する。

反復1周:
- **提案** — 現残差に `identify_phases` (異方 rerank 既定 on) を実行し次の1相候補を得る。
- **整合** — 候補の計算ピークを**現残差の観測ピークへ格子整合**してから減算プロファイルを合成する
  (異方優先・不可なら等方; 下記「減算整合」参照)。参照未整合ピークで減算すると、実データの DFT 格子
  誤差 (MP 構造の緩和ズレ) がそのまま残差に位置ミスマッチとして残り、次相の検出を汚染するため。
- **受理 (高速段)** — 全採用相 + 候補を `fit_nonneg_scales` で原パターンへ joint 非負スケール再フィットし、
  未説明強度が相対 `eps_gain` 超減り候補スケール > `scale_min` の候補のみ採る。
- **減算** — 残差 = 原パターン − Σ 採用相モデル (毎回原パターンから; 貪欲減算の誤差蓄積を断つ)。
- **停止** — 残差 S/N (`residual_significance`) < `snr_stop`、または全候補棄却。

decoy (既説明ピークのみの元素部分集合相等) は joint fit でスケール≈0 → `eps_gain` 未達で自然棄却される
(hard 化学ガードに依らない)。化学的妥当性はコアに含めず第3層に委ねる (opt-in `require_elements` のみ)。
多形判別は**注入した実 Rietveld (`refiner`)** を相同定内で呼んで確定する (深段, FR-118-5)。

**減算整合 (Issue 実データ頑健化)**: `identify_phases` は候補ランキングの内側で格子整合 (`refine_lattice`/
`rerank_top_k`) 済みスコアを使うが、その整合済みピーク位置は `PhaseMatch` には残らず (`reference` は生
ピークのまま)、減算モデル構築 (`_peaklist`) は素の参照ピークを使っていた。実データでは MP 参照構造の
DFT 格子/原子位置誤差により計算ピークが観測より最大で数 σ 分ずれ、その状態で強スケール減算すると
「ピーク位置ミスマッチ」の巨大な系統残差が残り、次相の同定 (S/N ベース停止・提案) を汚染する
(実測: CandAt で 1 相減算後の残差 S/N ~560 → 次相検出が破綻)。本モジュールは受理判定・最終減算の両方で
**現在の残差に対して**候補を整合 (`_candidate_peaklists`: 異方 `align_peaks_anisotropic` 優先、cell/hkl
不足時のみ等方 `align_peaks` にフォールバック) してからプロファイルを合成する。整合は決定論的最小二乗
(乱数なし) で、identify_phases の内部整合と同じアルゴリズムを再利用するのみ (二重の解釈を導入しない)。
整合は少数ピークだとグリッド量子化/ノイズにまで「フィット」して真の相の適合度を悪化させ得るため
(実測回帰)、生ピーク版と整合版の両方を実際に joint フィットし、**残差 (ss) が小さい方を採用**する
(`_best_peaklist_and_fit`) — 事前の閾値判断ではなく実測適合度で決める。

**FWHM 自動推定 (層2)**: 固定 `cfg.fwhm` は実データの実測ピーク幅と系統的に食い違い得る (装置分解能は
試料非依存だが未知)。既定は `cfg.fwhm` を使うが `cfg.auto_fwhm=True` (既定 on) なら初回残差の観測強
ピーク群から半値全幅を実測し (`_estimate_fwhm_deg`)、以降のプロファイル合成に使う。推定は決定論 (乱数
なし)・観測ピーク不足時は `cfg.fwhm` にフォールバックする。

numpy-only コア。`identify_phases` の rerank / provider / refiner の内側で pymatgen/GSAS が遅延 import される。
信頼性: 🔵 `docs/design/m11-iterative-identification/architecture.md`。
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from ..search.peaks import Peak, find_peaks
from ..store.ledger import Ledger
from .engine import identify_phases, preprocess_intensity
from .grouping import PhaseMatchGroup, group_by_composition
from .model import PhaseMatch, ReferencePhase
from .provider import ReferenceProvider
from .rietveld import align_peaks, align_peaks_anisotropic
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
    "subtract_known_phases",
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
    max_strain: float = 0.01     # 提案時 (identify_phases) の等方格子整合の歪み上限 (Dara 準拠 1%)
    hull_cutoff_ev: float | None = 0.1  # 提案時の MP 安定性フィルタ (identify_phases へ転送)
    kalpha2: object | None = None  # 提案時の Kα2 サテライト設定 (identify_phases へ転送; None=単色)
    rerank_top_k: int = 5        # 提案時の異方 rerank (層1 既定)
    rerank_wavelength: float = 1.5406  # 提案時の異方 rerank 線源波長 (Å, 既定 Cu Kα1)
    require_elements: Sequence[str] | None = None  # opt-in 全元素系 hard ガード (第3層; 既定なし)
    always_refine: bool = False  # 深段 Rietveld を常時適用 (既定は僅差多形時のみ)
    polymorph_margin: float = 0.05  # 同組成 score 差がこれ未満なら深段裁定対象
    align_subtraction: bool = True  # 減算モデル合成前に候補を現残差へ格子整合する (実データ頑健化)
    align_max_strain: float = 0.01  # 減算整合 (等方フォールバック) の歪み上限 (Dara 準拠 1%)
    align_wavelength: float = 1.5406  # 減算整合 (異方) の線源波長 (Å, 既定 Cu Kα1)
    auto_fwhm: bool = True       # True で初回残差の観測ピーク幅から fwhm を自動推定 (層2)


@dataclass(frozen=True)
class AcceptedPhase:
    """受理された1相 (参照相 + joint スケール + 提案スコア)。"""

    reference: ReferencePhase
    scale: float
    score: float
    source: str = "iterative"
    # 提案時に refine_lattice が求めた等方格子歪み ε (PhaseMatch.strain 由来)。物質化の格子補正に使う
    # (operando 一本化で `insitu.phaseid` が materialize(strain=) へ渡す)。既定 0.0 (known_phases も 0)。
    strain: float = 0.0

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


#  等方整合 (ε, z の2自由度) を信頼するのに要る最小一致ピーク数。少数ピークでは2自由度が数点の
#  グリッド量子化/ノイズ由来のサブピクセルなジッタにまで「フィット」してしまい (実測: 4 ピークの真の
#  相ですら noise>0 で ss が悪化する)、ピーク数の少ない decoy が近傍ノイズへスナップして過剰適合し得る
#  回帰が起きた。自由度に対し十分な余剰 (>>2) を要求し、真に系統的な格子ズレ (実データで数十ピークが
#  一貫してズレる) と、少数ピークの偶然一致/ジッタを区別する。
_MIN_ALIGN_MATCHES = 8


def _candidate_peaklists(
    ref: ReferencePhase,
    observed: Sequence[Peak],
    cfg: IdentifyConfig,
) -> list[list[tuple[float, float]]]:
    """候補の減算プロファイル合成に使う peaklist 候補群 (生 + 整合版) を返す。

    参照相の生ピーク (DFT 格子/原子位置に由来する系統ズレを含む) をそのまま減算すると、実データでは
    ピーク位置ミスマッチの巨大な残差が残り次相検出を汚染する (`_peaklist` の元バグ)。一方で整合
    (`align_peaks`/`align_peaks_anisotropic`) を無条件に適用すると、少数ピークではグリッド量子化/
    ノイズ由来のジッタにまで「フィット」して**真の相の適合度を悪化させる**副作用がある (実測回帰:
    ノイズ付き4ピーク相で ss が整合により +19% 悪化 → decoy の偽陽性受理を誘発)。

    どちらが実際に良い適合かは試料/候補次第で事前に決められないため、**両方候補として返し、
    呼び出し側が実際の joint フィット結果 (ss) で選ぶ** (identify_pattern が既に候補同士を ss 比較で
    選ぶのと同じ decision principle)。整合が縮退・情報不足・`align_subtraction=False` の場合は生の
    みを返す。決定論 (乱数なし)。
    """
    raw = _peaklist(ref)
    if not cfg.align_subtraction or not observed:
        return [raw]
    out = [raw]
    aniso = align_peaks_anisotropic(ref, observed, wavelength=cfg.align_wavelength)
    if aniso is not None and aniso.aligned_peaks and aniso.n_used >= _MIN_ALIGN_MATCHES:
        out.append([(float(p.position), float(p.height)) for p in aniso.aligned_peaks])
    alignment = align_peaks(ref.peaks, observed, max_strain=cfg.align_max_strain)
    if alignment.n_matched >= _MIN_ALIGN_MATCHES:
        out.append([(float(p.position), float(p.height)) for p in alignment.aligned_peaks])
    return out


def _best_peaklist_and_fit(
    base_peaklists: Sequence[list[tuple[float, float]]],
    ref: ReferencePhase,
    observed: Sequence[Peak],
    cfg: IdentifyConfig,
    tt: np.ndarray,
    obs: np.ndarray,
    fwhm: float,
) -> tuple[list[tuple[float, float]], np.ndarray, np.ndarray, float]:
    """候補の生/整合 peaklist 版のうち、`base_peaklists` に加えたときの joint フィット残差 (ss) が
    最小の版を選び、その peaklist と `(scales, model, ss)` を返す。

    整合が真に系統的なズレを吸収するのか、単にノイズへ過剰適合しているだけなのかは事前に判別できない
    (等方 (ε,z) は 2 自由度しかなく、少数ピークではグリッド量子化/ノイズのジッタにまで「フィット」して
    真の相の適合度を悪化させ得る; 実測回帰: 4 ピーク真相で整合により ss が +19% 悪化)。よって各版を
    実際に試し、**joint フィット後の残差 (ss) が最小の版を選ぶ** — identify_pattern が候補同士を
    ss 比較で選ぶのと同じ decision principle をここでも適用する (決定論・同点は生ピーク優先)。
    """
    variants = _candidate_peaklists(ref, observed, cfg)
    best: tuple[list[tuple[float, float]], np.ndarray, np.ndarray, float] | None = None
    for variant in variants:
        s, model, _r, ss = _fit(tt, obs, list(base_peaklists) + [variant], fwhm)
        if best is None or ss < best[3] - 1e-12:
            best = (variant, s, model, ss)
    assert best is not None  # variants は常に非空 (最低 raw を含む)
    return best


#  自動推定 fwhm を cfg.fwhm の何倍まで許すか (下限/上限)。推定はノイズの多い実データで暴走し得るため
#  (谷探索がノイズの凹凸で早期停止/二次モーメントが遠方ノイズを拾って過大化)、既定値からの逸脱に
#  常識的な上限を掛け、暴走時は自動推定を諦めて cfg.fwhm 側へ丸める安全網とする (過剰適合の抑制)。
_FWHM_ESTIMATE_MIN_RATIO = 0.3
_FWHM_ESTIMATE_MAX_RATIO = 3.0


def _estimate_fwhm_deg(
    tt: np.ndarray, obs: np.ndarray, peaks: Sequence[Peak], *, fallback: float
) -> float | None:
    """観測の強ピーク群から半値全幅 (度) を実測する (層2 自動 fwhm)。

    各ピーク位置周りでピーク高さの半分まで両側に辿り、その幅を FWHM とする (局所ベースライン=谷底を
    引いてから半値を取る簡易実装)。強度上位のピークのみ使い (弱いサテライト/ノイズ起源は除外)、
    複数ピークの中央値を取ることで単一ピークのノイズ/近接反射重なりの影響を抑える。決定論 (乱数なし)。

    ノイズの多い実データでは谷探索がノイズの小さな凹凸で早期停止し系統的に幅を過小評価し得るため
    (実測回帰: noise=3% で真 0.15° を 0.09° 前後と誤推定 → 幅の狭い decoy が過剰適合)、最終推定値を
    `fallback` (通常 ``cfg.fwhm``) の `[_FWHM_ESTIMATE_MIN_RATIO, _FWHM_ESTIMATE_MAX_RATIO]` 倍域へ
    クランプする安全網を掛ける。真に系統的なズレ (実データの装置分解能差) は数十%程度に収まる想定で、
    暴走 (例: 40% 超の過小/過大評価) を防ぐ。十分な有効測定が無ければ ``None`` を返し、呼び出し側は
    `fallback` を使う。
    """
    if len(peaks) == 0 or tt.size < 3:
        return None
    n = tt.size
    # 最強ピークの一定比率未満は「弱いサテライト/ノイズ起源」として除外する (中央値の歪み防止)。
    max_height = max(p.height for p in peaks)
    strong = [p for p in peaks if p.height >= 0.3 * max_height]
    ranked = sorted(strong, key=lambda p: (-p.height, p.position))
    widths: list[float] = []
    for p in ranked[:8]:
        i = int(np.searchsorted(tt, p.position))
        i = min(max(i, 0), n - 1)
        h = float(obs[i])
        if h <= 0:
            continue
        # 直近の局所極小 (谷) をベースラインとして半値を谷底基準に取る (背景オフセットに頑健)。
        lo = i
        while lo > 0 and obs[lo - 1] < obs[lo]:
            lo -= 1
        hi = i
        while hi < n - 1 and obs[hi + 1] < obs[hi]:
            hi += 1
        base = min(float(obs[lo]), float(obs[hi]))
        half = base + 0.5 * (h - base)
        if half <= base:
            continue
        # 左側: half を下回る最初の点への線形補間
        left = tt[lo]
        for j in range(i, lo, -1):
            if obs[j - 1] <= half <= obs[j] or (obs[j] <= half <= obs[j - 1]):
                denom = obs[j] - obs[j - 1]
                frac = (half - obs[j - 1]) / denom if denom != 0 else 0.0
                left = tt[j - 1] + frac * (tt[j] - tt[j - 1])
                break
        right = tt[hi]
        for j in range(i, hi):
            if obs[j] >= half >= obs[j + 1] or (obs[j] <= half <= obs[j + 1]):
                denom = obs[j + 1] - obs[j]
                frac = (half - obs[j]) / denom if denom != 0 else 0.0
                right = tt[j] + frac * (tt[j + 1] - tt[j])
                break
        width = float(right - left)
        if width > 0:
            widths.append(width)
    if not widths:
        return None
    estimated = float(np.median(widths))
    lo_bound = _FWHM_ESTIMATE_MIN_RATIO * fallback
    hi_bound = _FWHM_ESTIMATE_MAX_RATIO * fallback
    return float(min(max(estimated, lo_bound), hi_bound))


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

    # 【初回観測ピーク】: FWHM 自動推定・known_phases 整合の共通入力 (観測検出のみ、候補マッチ不要)。
    initial_peaks = find_peaks(tt, obs) if (cfg.auto_fwhm or known_phases) else ()

    # 【FWHM 自動推定 (層2)】: 初回の観測強ピーク群から実測する。失敗時は cfg.fwhm にフォールバック。
    fwhm = cfg.fwhm
    if cfg.auto_fwhm:
        estimated = _estimate_fwhm_deg(tt, obs, initial_peaks, fallback=cfg.fwhm)
        if estimated is not None and estimated > 0:
            fwhm = estimated

    accepted_refs: list[ReferencePhase] = list(known_phases)
    accepted_scores: list[float] = [0.0] * len(accepted_refs)
    # known_phases は既知格子 (これから精密化する初期値) なので提案 strain を持たない → 0.0。
    accepted_strains: list[float] = [0.0] * len(accepted_refs)
    accepted_ids: set[str] = {r.phase_id for r in accepted_refs}
    # known_phases はまだ残差が無いため、生パターンの観測ピークへ整合する (以降はループ内で残差へ整合)。
    # 各 known phase は逐次 (これまで積んだ peaklists に対し) ss 最小の版 (生/整合) を選んで積む。
    known_observed = initial_peaks if known_phases else ()
    peaklists, s, model, ss_prev = _build_best_peaklists(
        accepted_refs, known_observed, cfg, tt, obs, fwhm
    )
    seen_matches: list[PhaseMatch] = []
    iterations: list[IterationRecord] = []
    resid_observed: tuple[Peak, ...] = known_observed  # ループ未実行時のフォールバック整合先

    for k in range(cfg.max_phases):
        resid = obs - model
        sig = residual_significance(tt, resid, sigma, smooth_window=cfg.smooth_window)
        if not sig.warrants_new_phase(cfg.snr_stop):
            break  # 全て説明済 (単相は k=1 で停止)

        ident = identify_phases(
            tt, resid, provider, elements=elements, subtract_bg=False,
            hull_cutoff_ev=cfg.hull_cutoff_ev,
            refine_lattice=cfg.refine_lattice, max_strain=cfg.max_strain,
            kalpha2=cfg.kalpha2,  # type: ignore[arg-type]
            rerank_top_k=cfg.rerank_top_k, rerank_wavelength=cfg.rerank_wavelength,
            require_elements=cfg.require_elements,
        )
        # 残差の観測ピーク: 減算モデル合成の整合先 (identify_phases が既に計算済のものを再利用)。
        resid_observed = ident.observed_peaks
        best: tuple | None = None  # (cand_ref, match, cand_peaks, s2, ss2, model2, gain)
        for match in ident.matches[: cfg.try_k]:
            cand = match.reference
            seen_matches.append(match)
            if cand.phase_id in accepted_ids:
                continue
            cand_peaks, s2, model2, ss2 = _best_peaklist_and_fit(
                peaklists, cand, resid_observed, cfg, tt, obs, fwhm
            )
            gain = (ss_prev - ss2) / ss_prev if ss_prev > 0 else 0.0
            cscale = float(s2[-1])
            improves = cscale > cfg.scale_min and gain > cfg.eps_gain
            wins = best is None or ss2 < best[4]
            ledger.append("m11_trial", {
                "k": k, "phase": cand.phase_id, "scale": cscale, "gain": gain,
                "accepted": bool(improves and wins),
            })
            if improves and wins:
                best = (cand, match, cand_peaks, s2, ss2, model2, gain)
        if best is None:
            break  # 全候補棄却で停止

        cand, match, cand_peaks, s2, ss2, model2, gain = best
        accepted_refs.append(cand)
        peaklists.append(cand_peaks)
        accepted_ids.add(cand.phase_id)
        accepted_scores.append(float(match.score))
        accepted_strains.append(float(match.strain))
        ss_prev, model = ss2, model2
        iterations.append(IterationRecord(k, cand.phase_id, gain, float(s2[-1]), sig.max_snr))

    # 最終 joint フィットで全相スケールを確定
    s_final, model_final, _rf, _ss = _fit(tt, obs, peaklists, fwhm)
    accepted = tuple(
        AcceptedPhase(reference=r, scale=float(sc), score=float(scr), strain=float(st))
        for r, sc, scr, st in zip(
            accepted_refs, _scales(s_final, len(accepted_refs)), accepted_scores, accepted_strains
        )
    )

    refined = False
    if refiner is not None and accepted:
        # 多形 swap の再整合先: 直近の残差観測ピーク (ループ未実行なら known_phases 起点の観測ピーク)。
        accepted, refined, model_final = _refine_and_remodel(
            tt, obs, accepted, seen_matches, refiner, cfg, ledger, fwhm, resid_observed
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


def subtract_known_phases(
    two_theta: np.ndarray,
    intensity: np.ndarray,
    known_phases: Sequence[ReferencePhase],
    *,
    cfg: IdentifyConfig = IdentifyConfig(),
) -> np.ndarray:
    """既知相の joint 非負モデルを差し引いた**残差パターン**を返す (Issue #20 続き)。

    `identify_pattern` が known_phases 起点で内部的に行っている減算 (観測ピークへ整合した peaklist を
    非負スケールで joint フィット → 差し引き) を、同定を回さずに**残差だけ**取り出せる形で公開する。

    【なぜ要るか】 異方セルプリアラインの目的関数 `lattice._peak_match_fom` は**観測ピーク基準**

        FoM = Σ_obs h_obs · min(|2θ_obs − 2θ_calc|, 1°) / Σ h_obs

    で「全ての観測ピークが計算ピークで覆われるか」を測る。少数相ではこの和が**支配相のピーク**に
    占められるため、FoM は「少数相の反射を支配相のピーク位置へばら撒くセル」を積極的に選ぶ =
    最適化の失敗ではなく**目的関数が誤っている**。実測 (CaTeO3 frame180, delta ~28%): 真セルより
    誤セルの方が FoM が良い (0.268 < 0.290) ため `require_improvement` ガードも素通りし、
    delta の最大軸誤差が出発点の 3.42% から **4.21% へ悪化**した。既知相を引いた残差では候補が
    支配的になるので同じ目的関数が正しく効く (同条件で最大軸誤差 **0.51%**)。

    :param two_theta: 観測 2θ (度, 昇順)
    :param intensity: 観測強度 (生)
    :param known_phases: 差し引く既知相 (精密化格子で生成したピーク列を持つもの)。空なら減算しない
    :param cfg: 減算に使う設定 (`subtract_bg`/`auto_fwhm`/`fwhm`/`align_subtraction` を参照)
    :returns: 残差強度 (`two_theta` と同長)。**cfg.subtract_bg なら背景も落ちている**ため、
        後段 (プリアライン/ピーク検出) には ``subtract_bg=False`` で渡すこと。**非負にクリップ**する
        (過剰減算を負のピークとして下流へ持ち込まない)。決定論 (乱数なし)。
    """
    tt = np.asarray(two_theta, dtype=float)
    obs = preprocess_intensity(
        np.asarray(intensity, dtype=float),
        subtract_bg=cfg.subtract_bg,
        bg_max_window=cfg.bg_max_window,
    )
    refs = list(known_phases)
    if not refs:
        return np.clip(obs, 0.0, None)

    observed = find_peaks(tt, obs)
    fwhm = cfg.fwhm
    if cfg.auto_fwhm:
        estimated = _estimate_fwhm_deg(tt, obs, observed, fallback=cfg.fwhm)
        if estimated is not None and estimated > 0:
            fwhm = estimated
    _peaklists, _s, model, _ss = _build_best_peaklists(refs, observed, cfg, tt, obs, fwhm)
    return np.clip(obs - model, 0.0, None)


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
    # swap した相 (r != a.reference) は別格子ゆえ旧 strain は無意味 → 0 リセット。未 swap は保持。
    new_accepted = tuple(
        AcceptedPhase(
            reference=r, scale=a.scale, score=a.score, source="iterative+rietveld",
            strain=a.strain if r.phase_id == a.reference.phase_id else 0.0,
        )
        for r, a in zip(best_refs, accepted)
    )
    return new_accepted, True


def _build_best_peaklists(
    refs: Sequence[ReferencePhase],
    observed: Sequence[Peak],
    cfg: IdentifyConfig,
    tt: np.ndarray,
    obs: np.ndarray,
    fwhm: float,
) -> tuple[list[list[tuple[float, float]]], np.ndarray, np.ndarray, float]:
    """相集合を逐次 joint フィットしつつ、各相ごとに ss 最小の peaklist 版 (生/整合) を選んで積む。

    `_best_peaklist_and_fit` を先頭から順に適用する (各相の選択はそれ以前に積んだ peaklists との
    joint 適合で決まるため、入力順に依存するが本モジュールでは常に同じ順序 (accepted 順) で呼ぶため
    決定論)。
    """
    peaklists: list[list[tuple[float, float]]] = []
    for r in refs:
        variant, _s, _m, _ss = _best_peaklist_and_fit(peaklists, r, observed, cfg, tt, obs, fwhm)
        peaklists.append(variant)
    s, model, _r, ss = _fit(tt, obs, peaklists, fwhm)
    return peaklists, s, model, ss


def _refine_and_remodel(tt, obs, accepted, seen_matches, refiner, cfg, ledger, fwhm, observed):
    """深段裁定を実行し、差し替え後に model を再合成して返す。

    整合 (`_build_best_peaklists`) は組成同一の多形間で共通の観測ピークへの対応がほぼ変わらないため、
    swap 後もループ最終盤の観測ピーク集合へ再整合して減算モデルを合成する (旧生ピークバグの再導入回避)。
    各相は生/整合版のうち joint 適合が良い方を選ぶ (過剰適合ガード、`_best_peaklist_and_fit` 参照)。
    """
    new_accepted, refined = refine_polymorphs(accepted, seen_matches, refiner, cfg, ledger)
    if not refined:
        _peaklists, _s, model, _ss = _build_best_peaklists(
            [a.reference for a in accepted], observed, cfg, tt, obs, fwhm
        )
        return accepted, False, model
    _peaklists, s, model, _ss = _build_best_peaklists(
        [a.reference for a in new_accepted], observed, cfg, tt, obs, fwhm
    )
    # スケールを再フィット値で更新
    rescaled = tuple(
        AcceptedPhase(
            reference=a.reference, scale=float(sc), score=a.score, source=a.source, strain=a.strain
        )
        for a, sc in zip(new_accepted, _scales(s, len(new_accepted)))
    )
    return rescaled, True, model
