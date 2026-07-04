"""mem/guard.py の失敗テスト (TASK-0056 / REQ-030/031/103 / EDGE-007)。

対象実装:
- ``src/tsumugin/mem/guard.py``:
  ``MEMApplicabilityReport`` (frozen dataclass) と
  ``check_mem_applicability(verification, hypothesis_id) -> MEMApplicabilityReport``。
- ``src/tsumugin/mem/__init__.py``: re-export (__all__ 昇順)。

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の mem/guard 節に依拠。

【最重要不変条件 (REQ-031/Dara 教訓)】: recommended=False でも MEM 実行を止めず警告を返すのみ。
  仮説の除外・rejected 化は一切行わない (verified の status 不変・report に除外フィールドなし)。
"""

from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError

import pytest

from tsumugin.joint.verification import JointVerificationResult
from tsumugin.mem.guard import MEMApplicabilityReport, check_mem_applicability
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance, RefinementMetrics


def _metrics(chi2: float = 10.0, n_obs: int = 2000) -> RefinementMetrics:
    return RefinementMetrics(rwp=5.0, gof=1.1, chi2=chi2, n_obs=n_obs, n_params=10)


def _phase(ref: str, *, scale: float = 1.0, wt: float | None = None) -> PhaseInstance:
    return PhaseInstance(
        phase_ref=ref, lattice=LatticeParams(5.0, 5.0, 5.0), scale=scale, wt_frac=wt
    )


def _hyp(hid: str, phases: tuple[PhaseInstance, ...], *, chi2: float = 10.0) -> Hypothesis:
    return Hypothesis(id=hid, phases=phases, metrics=_metrics(chi2=chi2), status="refined")


def _verification(*hyps: Hypothesis) -> JointVerificationResult:
    return JointVerificationResult(
        verified=tuple(hyps), joint_results={}, recommendations={}
    )


# ---------------------------------------------------------------------------
# (A) dataclass 形状
# ---------------------------------------------------------------------------


def test_report_is_frozen_dataclass():
    rep = MEMApplicabilityReport(
        recommended=True, is_single_phase=True, is_dominant_phase=True
    )
    assert dataclasses.is_dataclass(MEMApplicabilityReport)
    with pytest.raises(FrozenInstanceError):
        rep.recommended = False  # type: ignore[misc]


def test_report_fields_match_interface():
    rep = MEMApplicabilityReport(
        recommended=False,
        is_single_phase=False,
        is_dominant_phase=False,
        warnings=("多相",),
    )
    assert rep.recommended is False
    assert rep.is_single_phase is False
    assert rep.is_dominant_phase is False
    assert rep.warnings == ("多相",)
    # 除外/rejected フィールドを一切持たない (Dara 教訓)。
    field_names = {f.name for f in dataclasses.fields(MEMApplicabilityReport)}
    assert not (field_names & {"excluded", "rejected", "reject", "exclude"})


# ---------------------------------------------------------------------------
# (B) 推奨条件: joint 済み単相/主相支配 [TC-509-01/REQ-030]
# ---------------------------------------------------------------------------


def test_single_phase_is_recommended():
    v = _verification(_hyp("h0", (_phase("A"),)))
    rep = check_mem_applicability(v, "h0")
    assert rep.is_single_phase is True
    assert rep.recommended is True
    assert rep.warnings == ()


def test_dominant_phase_is_recommended():
    """主相が相分率で支配的な多相仮説は recommended=True (単相ではない)。"""
    phases = (_phase("A", scale=9.0), _phase("B", scale=1.0))
    v = _verification(_hyp("h0", phases))
    rep = check_mem_applicability(v, "h0")
    assert rep.is_single_phase is False
    assert rep.is_dominant_phase is True
    assert rep.recommended is True


def test_dominant_phase_uses_wt_frac_when_present():
    """wt_frac があればそれを相分率として支配判定に使う。"""
    phases = (_phase("A", wt=0.92), _phase("B", wt=0.08))
    v = _verification(_hyp("h0", phases))
    rep = check_mem_applicability(v, "h0")
    assert rep.is_dominant_phase is True
    assert rep.recommended is True


# ---------------------------------------------------------------------------
# (C) 多相/低統計は警告のみ・除外しない [TC-509-02/REQ-031/103/EDGE-007]
# ---------------------------------------------------------------------------


def test_multiphase_non_dominant_warns_but_not_recommended():
    """相分率が拮抗する多相は recommended=False + 警告 (MEM 実行は止めない)。"""
    phases = (_phase("A", scale=1.0), _phase("B", scale=1.0), _phase("C", scale=1.0))
    v = _verification(_hyp("h0", phases))
    rep = check_mem_applicability(v, "h0")
    assert rep.is_single_phase is False
    assert rep.is_dominant_phase is False
    assert rep.recommended is False
    assert len(rep.warnings) >= 1


def test_low_statistics_warns():
    """低統計 (chi2 大 / n_obs 少) でも警告のみ・recommended へ影響し除外しない。"""
    phases = (_phase("A"),)
    v = _verification(_hyp("h0", phases, chi2=1e6))
    rep = check_mem_applicability(v, "h0")
    assert len(rep.warnings) >= 1


def test_guard_does_not_mutate_or_exclude_hypothesis():
    """(最重要) guard は verified の Hypothesis を書き換えず status も不変にする (REQ-031)。"""
    phases = (_phase("A", scale=1.0), _phase("B", scale=1.0))
    hyp = _hyp("h0", phases)
    v = _verification(hyp)
    status_before = hyp.status
    id_before = id(hyp)

    check_mem_applicability(v, "h0")

    # verified のオブジェクト同一性・status が不変 (rejected 化しない)。
    assert v.verified[0] is hyp
    assert id(v.verified[0]) == id_before
    assert v.verified[0].status == status_before
    assert v.verified[0].status != "rejected"


def test_unknown_hypothesis_id_warns_without_crash():
    """検証結果に無い仮説 ID は例外化せず警告付き非推奨で返す (fail-soft)。"""
    v = _verification(_hyp("h0", (_phase("A"),)))
    rep = check_mem_applicability(v, "missing")
    assert rep.recommended is False
    assert len(rep.warnings) >= 1
