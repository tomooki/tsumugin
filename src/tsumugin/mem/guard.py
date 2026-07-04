"""MEM 適用ガード (M5 / REQ-030/031/103 / EDGE-007 / D7)。

MEM (最大エントロピー法) の推奨条件 (joint 検証済み・単相 or 主相支配的) を判定する。

【最重要不変条件 (REQ-031/Dara 教訓)】: 推奨条件を満たさない (多相/低統計) 場合でも MEM 実行を
  中止せず、``recommended=False`` + ``warnings`` を返すのみ。仮説の除外・rejected 化は一切
  行わない (``MEMApplicabilityReport`` は excluded/rejected フィールドを持たない)。

【判定入力】``JointVerificationResult.verified`` の該当仮説 (``hypothesis_id``) から:
  - 単相判定: 相数 (``len(phases)``) が 1 か。
  - 主相支配判定: 相分率 (``wt_frac`` 優先、無ければ ``scale``) の最大割合が閾値以上か。
  - 低統計警告: 検証後 metrics (chi2 / n_obs) から統計不足の目安を警告に積む。

本モジュールは numpy 不要のコアのみ (REQ-403) で、joint/verification の型のみに依存する。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from ..joint.verification import JointVerificationResult
from ..model import Hypothesis, PhaseInstance

# 【主相支配の閾値 (相分率)】: 最大相の相分率がこの割合以上なら主相支配的とみなす。🔵 REQ-030
_DOMINANT_FRACTION = 0.8

# 【低統計警告の目安】: gof の代理として chi2/n_obs が過大 (統計不足の疑い) なら警告する。🔵 REQ-103
#   n_obs あたり chi2 が大きすぎる場合、フィット品質不足として信頼性警告を積む (除外はしない)。
_LOW_STAT_CHI2_PER_OBS = 5.0


@dataclass(frozen=True)
class MEMApplicabilityReport:
    """MEM 適用推奨条件の判定結果 (警告のみ・除外しない)。🔵 REQ-030/031

    【最重要不変条件 (REQ-031/Dara 教訓)】: recommended=False でも MEM 実行を止めず、警告を
      返すのみ。仮説の除外・rejected 化は一切行わない (excluded/rejected フィールドを持たない)。
    """

    recommended: bool  # 【推奨条件 (joint 済み単相/主相支配) を満たすか】 🔵 REQ-030
    is_single_phase: bool  # 【単相か】 🔵
    is_dominant_phase: bool  # 【主相支配的か】 🔵
    warnings: tuple[str, ...] = ()  # 【多相/低統計の信頼性警告 (除外はしない)】 🔵 REQ-031/103


def _phase_fraction(phase: PhaseInstance) -> float:
    """1 相の相分率代理を返す。``wt_frac`` があればそれを、無ければ ``scale`` を用いる。🔵 REQ-030"""
    if phase.wt_frac is not None:
        return max(float(phase.wt_frac), 0.0)
    return max(float(phase.scale), 0.0)


def _is_dominant(phases: tuple[PhaseInstance, ...]) -> bool:
    """相分率 (wt_frac 優先 / scale 代替) から主相が支配的かを判定する。🔵 REQ-030"""
    if not phases:
        return False
    fractions = [_phase_fraction(p) for p in phases]
    total = sum(fractions)
    if total <= 0.0:
        return False
    return (max(fractions) / total) >= _DOMINANT_FRACTION


def _find_hypothesis(
    verification: JointVerificationResult, hypothesis_id: str
) -> Hypothesis | None:
    """検証結果から該当仮説を線形探索する。未知 ID は None (fail-soft)。🔵 EDGE-007"""
    for hyp in verification.verified:
        if hyp.id == hypothesis_id:
            return hyp
    return None


def check_mem_applicability(
    verification: JointVerificationResult, hypothesis_id: str
) -> MEMApplicabilityReport:
    """MEM 適用の推奨条件を判定し、非充足でも警告のみ返す (除外しない)。🔵 REQ-030/031/103/EDGE-007

    【判定 (REQ-030)】: joint 検証済みかつ単相 or 主相支配的なら recommended=True。
    【警告のみ (REQ-031/103/EDGE-007)】: 多相/低統計は warnings に信頼性警告を積むが
      recommended=False を返すのみで MEM 実行を中止しない (Dara 教訓)。仮説除外もしない。
    【未知 ID (EDGE-007)】: 検証結果に無い仮説 ID は例外化せず、警告付き非推奨で返す (fail-soft)。
    """
    hyp = _find_hypothesis(verification, hypothesis_id)
    if hyp is None:
        # 【fail-soft】: 未知 ID は例外化せず非推奨 + 警告で返す (解析を止めない)。
        return MEMApplicabilityReport(
            recommended=False,
            is_single_phase=False,
            is_dominant_phase=False,
            warnings=(
                f"仮説 {hypothesis_id!r} は joint 検証結果に存在しません。"
                "MEM 適用推奨条件を判定できません (実行は妨げません)。",
            ),
        )

    phases = hyp.phases
    is_single = len(phases) == 1
    is_dominant = _is_dominant(phases)

    warnings: list[str] = []

    # 【多相・非支配の信頼性警告】: 単相でも主相支配でもない多相は MEM の解釈に注意 (除外しない)。🔵 REQ-031
    if not is_single and not is_dominant:
        warnings.append(
            f"仮説 {hypothesis_id!r} は多相かつ主相が支配的でないため、MEM 密度の相帰属に"
            "曖昧性があります (信頼性警告・MEM 実行は継続・仮説除外はしません)。"
        )

    # 【低統計の信頼性警告】: 検証後 metrics から統計不足の目安を警告する (recommended へは影響させない)。🔵 REQ-103
    metrics = hyp.metrics
    if metrics is not None:
        chi2 = float(metrics.chi2)
        n_obs = int(metrics.n_obs)
        if n_obs <= 0 or not math.isfinite(chi2):
            warnings.append(
                f"仮説 {hypothesis_id!r} の検証統計が不足/非有限のため MEM 密度の信頼性が"
                "低い可能性があります (信頼性警告・除外はしません)。"
            )
        elif n_obs > 0 and (chi2 / n_obs) >= _LOW_STAT_CHI2_PER_OBS:
            warnings.append(
                f"仮説 {hypothesis_id!r} は観測点あたり χ² が大きく (低統計の疑い)、MEM 密度の"
                "信頼性が低い可能性があります (信頼性警告・除外はしません)。"
            )

    recommended = is_single or is_dominant
    return MEMApplicabilityReport(
        recommended=recommended,
        is_single_phase=is_single,
        is_dominant_phase=is_dominant,
        warnings=tuple(warnings),
    )
