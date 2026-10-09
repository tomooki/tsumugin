"""M8: 残差診断 → ActionProposal (提案のみ・適用しない) + 保守的初期リミット。

フィット結果と残差シグネチャ (`ResidualFeatures`) から次手候補を **決定論・安定順**で提案する。
規則が実行してよい SafeAction (背景増項/パラメータ解放) と ③ 専用の ModelAction (リミット/相追加/
構造改訂) を `safe` フラグで区別する。適用は行わない (Dara/OED 教訓, §1)。

`propose_initial_limits` は setup 段階の保守的初期リミット (低 S/N 端を切る) のみを出す。ループ内の
可変アクションではない (§4.3: 範囲を変えると Rwp 比較不能・切り位置は判断のため)。

信頼性: 🔵 architecture.md §5 の残差シグネチャ→提案表と 1:1。純 numpy (GSAS 非依存)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

import numpy as np

from tsumugin.autorietveld import AutoRietveldResult, PhaseSpec
from tsumugin.autorietveld.model import resolve_uiso_release
from .action import (
    AddPhase,
    AdjustBackground,
    AnalysisAction,
    ReleaseParams,
    RestrictUiso,
    ReviseStructure,
    SetAbsorption,
    SetLimits,
)


@dataclass(frozen=True)
class ResidualFeatures:
    """ヒストグラム 1 本の残差シグネチャ (診断入力)。

    :param hist_id: ヒストグラム索引
    :param low_freq_bg_residual: 低周波系統背景残差の大きさ (正規化, 0=なし)
    :param fwhm_ratio: obs/calc FWHM 比 (1.0 が理想。ずれは size/mustrain 不足)
    :param unindexed_peak_frac: 未指数 obs ピーク強度の割合 (相不足の徴候)
    :param edge_low_snr: 端に低 S/N 領域があるか (リミット候補)
    :param n_background_coeffs: 現在の背景係数数
    """

    hist_id: int
    low_freq_bg_residual: float = 0.0
    fwhm_ratio: float = 1.0
    unindexed_peak_frac: float = 0.0
    edge_low_snr: bool = False
    n_background_coeffs: int = 6
    # 【拡張シグナル (refine-loop-diagnostics)】: すべて既定 0/空 = シグナルなし (EDGE-001 縮退)。
    asymmetry_residual: float = 0.0
    """残差の左右非対称度 (0=対称)。>tol でシフト(Zero)と非対称の**別々の**候補を出す (REQ-101)。"""
    intensity_bias: float = 0.0
    """系統的 obs>calc 度 (>tol で選択配向候補, REQ-102)。"""
    bg_extrema_count: int = 0
    """背景プロファイルの極値数 (過多で背景減項候補, REQ-104)。"""
    diverged_uiso_labels: tuple[str, ...] = ()
    """発散/負値の Uiso 原子ラベル (RestrictUiso 候補, REQ-105)。**相を畳んだ見え方**で、
    同名ラベル (両相の "O1" など) がどの相で発散したかは区別できない — 相の帰属は
    `diverged_uiso_atoms` が運ぶ。"""
    absorption_uncertain: bool = False
    """吸収寄与が不確実か (free/物理/0 の SetAbsorption 三択候補, REQ-106)。"""
    radiation_is_tof: bool = False
    """TOF ヒストか (非対称候補を SH/L[X線] と alpha/beta[TOF] で分岐, REQ-101)。"""
    radiation_is_neutron: bool = False
    """中性子ヒストか (CW 中性子は X 線専用 Lorentzian/SH-L が engine で無効 → 該当候補を出さない)。"""
    diverged_uiso_atoms: tuple[tuple[str, str], ...] = ()
    """発散/負値の Uiso 原子の (相名, 原子ラベル) 組 (昇順)。原子ラベルは相の中でしか意味を
    持たないので、RestrictUiso はこれを使って相ごとに提案する。空でラベルだけある場合
    (旧形式・注入 diagnose) の帰属は `propose_next_actions` を参照。"""

    def __post_init__(self) -> None:
        """発散の 2 つの見え方を 1 つの事実に揃える。相付きの組があればラベル列はそこから
        導き (省略可)、食い違うラベル列は拒む — 提案は相付きを、読み手はラベル列を見るので、
        黙って受けると両者が別のことを言う。"""
        if not self.diverged_uiso_atoms:
            return
        derived = tuple(sorted({lab for _, lab in self.diverged_uiso_atoms}))
        if not self.diverged_uiso_labels:
            object.__setattr__(self, "diverged_uiso_labels", derived)
        elif set(self.diverged_uiso_labels) != set(derived):
            raise ValueError(
                f"diverged_uiso_labels {self.diverged_uiso_labels} が diverged_uiso_atoms "
                f"{self.diverged_uiso_atoms} のラベル {derived} と食い違います"
            )


@dataclass(frozen=True)
class ActionProposal:
    """次手 1 候補。適用はしない (規則ポリシー / ③ が採否を判断)。

    :param action: 提案する AnalysisAction
    :param rationale: 提案根拠 (自然言語)
    :param priority: 優先度 (大きいほど先; 決定論ソートのキー)
    :param evidence: 数値的根拠 (MCP で ③ に露出)
    :param safe: 規則が実行してよい安全手か (= action.is_safe)
    """

    action: AnalysisAction
    rationale: str
    priority: float
    evidence: Mapping[str, object] = field(default_factory=dict)
    safe: bool = False


def propose_next_actions(
    result: AutoRietveldResult,
    features: Sequence[ResidualFeatures],
    *,
    background_max: int = 12,
    background_step: int = 3,
    bg_residual_tol: float = 0.1,
    fwhm_tol: float = 0.1,
    unindexed_tol: float = 0.05,
    asymmetry_tol: float = 0.05,
    intensity_bias_tol: float = 0.05,
    background_min: int = 6,
    bg_extrema_max: int = 6,
    phases: Sequence[PhaseSpec] | None = None,
) -> tuple[ActionProposal, ...]:
    """残差シグネチャと妥当性から次手候補を決定論・安定順で返す (§5)。

    順序: safe 優先 → 優先度降順 → Action 型名昇順 (NFR-102 決定論)。適用はしない。

    :param phases: 結果を出した入力の相仕様。**RestrictUiso はこれが無いと提案しない** —
        Uiso の解放集合は相の指定 (`free_uiso_labels=()` の相凍結・`frozen_uiso_labels`) の
        上に張るもので、指定を知らずに書き換えると凍結した相を解除してしまう
    """
    proposals: list[ActionProposal] = []

    for f in features:
        # 低周波系統背景残差 → 背景増項 (SafeAction)
        if f.low_freq_bg_residual > bg_residual_tol and f.n_background_coeffs < background_max:
            new_n = min(f.n_background_coeffs + background_step, background_max)
            proposals.append(
                ActionProposal(
                    action=AdjustBackground(new_n),
                    rationale=f"hist{f.hist_id}: 低周波系統残差 {f.low_freq_bg_residual:.2f} "
                    f"→ 背景 {f.n_background_coeffs}→{new_n} 項",
                    priority=float(f.low_freq_bg_residual),
                    evidence={
                        "signal": "background",
                        "low_freq_bg_residual": f.low_freq_bg_residual,
                        "hist_id": f.hist_id,
                    },
                    safe=True,
                )
            )
        # 背景の過剰 wiggle (極値過多) → 背景減項 (REQ-104)。増項規則と両立・下限ガード。
        if f.bg_extrema_count > bg_extrema_max and f.n_background_coeffs > background_min:
            reduced_n = max(f.n_background_coeffs - background_step, background_min)
            proposals.append(
                ActionProposal(
                    action=AdjustBackground(reduced_n),
                    rationale=f"hist{f.hist_id}: 背景極値 {f.bg_extrema_count} 過多 "
                    f"→ 背景 {f.n_background_coeffs}→{reduced_n} 項 (過適合抑制)",
                    priority=float(f.bg_extrema_count),
                    evidence={
                        "signal": "background_overfit",
                        "bg_extrema_count": f.bg_extrema_count,
                        "hist_id": f.hist_id,
                    },
                    safe=True,
                )
            )
        # obs/calc FWHM 比の系統ずれ → 幅パラメータを「別々の」候補で提案 (REQ-103)。放射源に応じた
        # 有効候補のみ出す (非対称規則と整合; engine が TOF でスキップする X 線専用フラグの no-op を避ける)。
        if abs(f.fwhm_ratio - 1.0) > fwhm_tol:
            if f.radiation_is_tof:
                width_cands = (
                    ("tof_sig", {"tof_profile": ["sig-1", "sig-2"]}, "TOF Gaussian 幅 (sig)"),
                    ("size_strain", {"size_strain": True}, "結晶子サイズ/微小歪み"),
                )
            elif f.radiation_is_neutron:
                # CW 中性子: Lorentzian(X,Y) は engine で無効。Gaussian(U,V,W) + size のみ。
                width_cands = (
                    ("profile_uvw", {"profile": ["U", "V", "W"]}, "Gaussian U,V,W"),
                    ("size_strain", {"size_strain": True}, "結晶子サイズ/微小歪み"),
                )
            else:
                width_cands = (
                    ("profile_uvw", {"profile": ["U", "V", "W"]}, "Gaussian U,V,W"),
                    ("profile_xy", {"profile_lorentzian": True}, "Lorentzian X,Y"),
                    ("size_strain", {"size_strain": True}, "結晶子サイズ/微小歪み"),
                )
            for lbl, flags, note in width_cands:
                proposals.append(
                    ActionProposal(
                        action=ReleaseParams(lbl, flags),
                        rationale=f"hist{f.hist_id}: obs/calc FWHM 比 {f.fwhm_ratio:.2f} "
                        f"→ {note}を別々に解放して観察",
                        priority=float(abs(f.fwhm_ratio - 1.0)),
                        evidence={
                            "signal": "fwhm",
                            "fwhm_ratio": f.fwhm_ratio,
                            "hist_id": f.hist_id,
                            "candidate": lbl,
                        },
                        safe=True,
                    )
                )
        # 系統的 obs>calc のピーク強度 → 選択配向 (preferred orientation) を提案 (REQ-102)。
        if f.intensity_bias > intensity_bias_tol:
            proposals.append(
                ActionProposal(
                    action=ReleaseParams("preferred_orientation", {"preferred_orientation": 4}),
                    rationale=f"hist{f.hist_id}: 系統的 obs>calc {f.intensity_bias:.2f} "
                    f"→ 選択配向 (SH order 4) を解放して観察",
                    priority=float(f.intensity_bias),
                    evidence={
                        "signal": "intensity_bias",
                        "intensity_bias": f.intensity_bias,
                        "hist_id": f.hist_id,
                    },
                    safe=True,
                )
            )
        # 非対称/位置ズレ → シフト(Zero)と非対称を「別々の」候補として提案 (REQ-101)。
        # どちらが効くかは焼き込まず (REQ-405/DD-2)、policy が個別に試し _accept が採否を決める。
        # CW 中性子は X 線専用の Lorentzian/SH-L が engine で無効なため候補を出さない (適用可能な
        # 位置/非対称フラグがない → no-op トライを避ける)。TOF/X 線のみ提案する。
        if f.asymmetry_residual > asymmetry_tol and not (
            f.radiation_is_neutron and not f.radiation_is_tof
        ):
            if f.radiation_is_tof:
                cands = (
                    ("tof_zero", {"tof_profile": ["Zero", "sig-1", "sig-2"]}, "位置(Zero)シフト"),
                    ("tof_asymmetry",
                     {"tof_profile": ["alpha", "beta-1", "sig-1", "sig-2"]}, "ピーク非対称(alpha/beta)"),
                )
            else:
                cands = (
                    ("xray_zero", {"profile_lorentzian": True}, "位置(Zero)シフト"),
                    ("xray_asymmetry", {"profile_asymmetry": True}, "ピーク非対称(SH/L)"),
                )
            for lbl, flags, note in cands:
                proposals.append(
                    ActionProposal(
                        action=ReleaseParams(lbl, flags),
                        rationale=f"hist{f.hist_id}: 非対称残差 {f.asymmetry_residual:.2f} "
                        f"→ {note}を別々に解放して観察",
                        priority=float(f.asymmetry_residual),
                        evidence={
                            "signal": "asymmetry",
                            "asymmetry_residual": f.asymmetry_residual,
                            "hist_id": f.hist_id,
                            "candidate": lbl,
                        },
                        safe=True,
                    )
                )
        # Uiso 発散/負値 → 解放対象を安定原子に限定 (RestrictUiso, REQ-105)。相ごとに出す。
        proposals.extend(_restrict_uiso_proposals(result, f, phases))
        # 吸収寄与が不確実 → free / 物理(現値固定) / 0 の三択を「別々に」試す (SetAbsorption, REQ-106)。
        if f.absorption_uncertain:
            cur = (
                result.hist_absorption[f.hist_id]
                if f.hist_id < len(result.hist_absorption)
                else 0.0
            )
            cands = [("abs_free", 0.0, True)]
            if abs(cur) > 1e-6:
                cands.append(("abs_fixed", cur, False))
            cands.append(("abs_zero", 0.0, False))
            for lbl, val, ref in cands:
                proposals.append(
                    ActionProposal(
                        action=SetAbsorption(f.hist_id, val, ref),
                        rationale=f"hist{f.hist_id}: 吸収不確実 → {lbl} を試して観察",
                        priority=0.4,
                        evidence={
                            "signal": "absorption",
                            "candidate": lbl,
                            "hist_id": f.hist_id,
                        },
                        safe=True,
                    )
                )
        # 未指数 obs ピーク → 相追加 (ModelAction, 提案のみ)
        if f.unindexed_peak_frac > unindexed_tol:
            proposals.append(
                ActionProposal(
                    action=AddPhase(),
                    rationale=f"hist{f.hist_id}: 未指数ピーク強度 {f.unindexed_peak_frac:.2f} "
                    f"→ 相追加候補 (相同定へハンドオフ; ③ が判断)",
                    priority=float(f.unindexed_peak_frac),
                    evidence={
                        "signal": "unindexed",
                        "unindexed_peak_frac": f.unindexed_peak_frac,
                        "hist_id": f.hist_id,
                    },
                    safe=False,
                )
            )
        # 端の低 S/N → データリミット (ModelAction, 提案のみ; 採否は ③)
        if f.edge_low_snr:
            proposals.append(
                ActionProposal(
                    action=SetLimits(f.hist_id, None, None),  # 切り位置未定のプレースホルダ提案
                    rationale=f"hist{f.hist_id}: 端に低 S/N 領域 → データ範囲制限候補 "
                    f"(切り位置は ③ が判断)",
                    priority=0.5,
                    evidence={"signal": "edge_snr", "hist_id": f.hist_id},
                    safe=False,
                )
            )

    # validity fail → 構造改訂 (ModelAction, 提案のみ)。ヒストグラム非依存で 1 度だけ。
    if not result.validity.passed:
        failed = [name for name, ok, _ in result.validity.checks if not ok]
        # 相名でソートして決定論的に選ぶ (Mapping の反復順に依存しない, NFR-102)。
        target_phase = min(result.refined_cells, default="")
        proposals.append(
            ActionProposal(
                action=ReviseStructure(target_phase, {}),
                rationale=f"物理妥当性 fail ({', '.join(failed) or '不明'}) "
                f"→ 構造改訂/制約追加候補 (③ が判断)",
                priority=1.0,
                evidence={"signal": "validity", "failed_checks": tuple(failed)},
                safe=False,
            )
        )

    # 決定論・安定順: safe 優先 → 優先度降順 → Action 型名昇順
    proposals.sort(key=lambda p: (not p.safe, -p.priority, type(p.action).__name__))
    return tuple(proposals)


def _phase_atom_labels(result: AutoRietveldResult, phase: str) -> set[str]:
    """相の原子ラベル全体。`atom_uiso` だけでは足りない — 異方性原子は Uiso を持たないので
    そこに現れないが、未指定 (全原子解放) の相では解放されている。占有率は全原子が持つ。"""
    return set(result.atom_uiso.get(phase, {})) | set(result.atom_occupancy.get(phase, {}))


def _diverged_by_phase(result: AutoRietveldResult, f: ResidualFeatures) -> dict[str, set[str]]:
    """発散原子を相へ帰属させる。

    相付きの `diverged_uiso_atoms` があればそれに従う。ラベルだけの旧形式 (注入 diagnose 等) は
    **そのラベルを持つ全相に帰属させる** — 同名ラベルがどの相で発散したかは判別できないので、
    両相で解放を止める (発散しうる原子を解放し続けるより保守的で、採否は受理基準が決める)。
    """
    by_phase: dict[str, set[str]] = {}
    if f.diverged_uiso_atoms:
        for phase, label in f.diverged_uiso_atoms:
            by_phase.setdefault(phase, set()).add(label)
        return by_phase
    labels = set(f.diverged_uiso_labels)
    for phase in set(result.atom_uiso) | set(result.atom_occupancy):
        hit = labels & _phase_atom_labels(result, phase)
        if hit:
            by_phase[phase] = hit
    return by_phase


def _restrict_uiso_proposals(
    result: AutoRietveldResult,
    f: ResidualFeatures,
    phases: Sequence[PhaseSpec] | None,
) -> list[ActionProposal]:
    """Uiso 発散/負値 → 発散原子を除いた残りに解放を限定する (RestrictUiso, REQ-105)。

    **相ごとに 1 つ**、その相自身のラベルだけで張る。全相のラベルを混ぜた 1 つの限定を全相に
    掛けると、各相が他相のラベルを抱え (GSAS は ``No such atom`` で uiso 段ごと revert =
    Uiso が 1 つも精密化されない)、同名ラベルは発散していない相でも止まり、凍結した相が
    解除される。

    限定は相の指定の**内側**に張る (広げない): 現在の解放集合 (engine と同じ規則
    `resolve_uiso_release` — 未指定なら相の全原子・明示の解放集合ならその集合、から
    `frozen_uiso_labels` を引いたもの) から発散原子を除く。
    発散原子が現在解放されていない相 (`free_uiso_labels=()` の凍結相・凍結原子の初期値が
    範囲外なだけ) は限定しても何も変わらないので提案しない。解放中の原子が全て発散した相は
    ``()`` = 相ごと凍結を提案する (#189 以降 ``()`` は「1 原子も解放しない」)。
    """
    if phases is None:
        return []
    specs = {p.phase_name: p for p in phases}
    proposals: list[ActionProposal] = []
    for name, diverged in sorted(_diverged_by_phase(result, f).items()):
        spec = specs.get(name)
        if spec is None:
            continue  # 指定の無い相は凍結状態を知れない
        released = set(resolve_uiso_release(
            spec.free_uiso_labels, spec.frozen_uiso_labels, _phase_atom_labels(result, name)
        ))
        hit = tuple(sorted(diverged & released))
        if not hit:
            continue
        keep = tuple(sorted(released - set(hit)))
        then = f"解放を {keep} に限定" if keep else "相の Uiso を凍結"
        proposals.append(
            ActionProposal(
                action=RestrictUiso(keep, phase=name),
                rationale=f"hist{f.hist_id}: 相 {name} の Uiso 発散 {hit} → {then}",
                priority=float(len(hit)),
                evidence={
                    "signal": "uiso_diverged",
                    "phase": name,
                    "diverged": hit,
                    "hist_id": f.hist_id,
                },
                safe=True,
            )
        )
    return proposals


def propose_initial_limits(
    hist_ids: Sequence[int],
    patterns: Mapping[int, tuple[np.ndarray, np.ndarray]],
    *,
    snr_factor: float = 3.0,
) -> dict[int, tuple[float, float]]:
    """低 S/N 端を切る保守的初期リミットを setup 用に提案する (§4.3)。

    ノイズ床 (下位分位) の `snr_factor` 倍を閾値に、信号がそれを超える x の最小/最大を範囲とする。
    全域が信号なら全域を返す。切り位置の精密化・微調整は ③/人間 (これは保守的初期値のみ)。

    :param hist_ids: 対象ヒストグラム索引列
    :param patterns: hist_id → (x, y) 観測パターン
    :returns: hist_id → (low, high)
    """
    limits: dict[int, tuple[float, float]] = {}
    for hid in hist_ids:
        x, y = patterns[hid]
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        if x.size == 0:
            continue
        noise = float(np.quantile(y, 0.1))
        threshold = noise * snr_factor if noise > 0 else float(np.median(y))
        above = y > threshold
        if not above.any():
            limits[hid] = (float(x.min()), float(x.max()))
            continue
        idx = np.flatnonzero(above)
        limits[hid] = (float(x[idx[0]]), float(x[idx[-1]]))
    return limits
