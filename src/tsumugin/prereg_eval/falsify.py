"""P0 §7.1: 1B の反証条件 (R1-1〜R1-4・R3)。

- 各条件は点推定で判定する (U13)。状態は ``fired`` / ``not_fired`` / ``indeterminate``。
- H 単独と H ∪ 準 hold-out の両方で評価し、**どちらかで発火したら発火** (§2.2)。どちらも発火せず、どちらかが判定不能なら
  判定不能 (`either`) — 片方で発火しなかったことを、もう片方の判定不能を隠す理由にしない。
- 率の分母が 0 の成分は判定不能 (「発火しない」にしない)。
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from .case import (
    CHI2_RATIO_MARGIN,
    D_MARGIN,
    N_OUT_MARGIN,
    SHORT_BOND_MARGIN,
    CaseInput,
    Judgment,
)
from .structure import deviations, metrics

__all__ = [
    "Falsification",
    "ProbeRow",
    "SplitRow",
    "either",
    "exceeds_equivalence",
    "r1_1",
    "r1_2",
    "r1_3",
    "r1_4",
    "r3",
]

_RATE_R1 = 0.10
_MIN_EVALUABLE = 11
_HALF = 0.5
_R3_MAIN_FLOOR = 0.8
_R3_MINOR_FLOOR = 0.5
_R3_FALSE_FIRE = 0.10
_R3_POWER_FLOOR = 0.8


@dataclass(frozen=True)
class Falsification:
    rid: str
    state: str  # fired / not_fired / indeterminate
    detail: str


def either(holdout: Falsification, combined: Falsification) -> Falsification:
    """H 単独と H ∪ 準 hold-out の結果を合わせる (§2.2)。"""
    states = (holdout.state, combined.state)
    detail = f"H: {holdout.state} ({holdout.detail}); H+quasi: {combined.state} ({combined.detail})"
    if "fired" in states:
        return Falsification(holdout.rid, "fired", detail)
    if "indeterminate" in states:
        return Falsification(holdout.rid, "indeterminate", detail)
    return Falsification(holdout.rid, "not_fired", detail)


def _structure_rate(judgments: Sequence[Judgment]) -> tuple[float | None, bool]:
    """(構造の劣化の率, 判定不能か)。分母は失敗で決まった事例・両方失敗を除く (criteria と同じ)。"""
    pool = [j.structure for j in judgments if j.status != "both_failed" and j.structure != "n/a"]
    if not pool:
        return None, True
    if pool.count("unevaluated") / len(pool) > _HALF:
        return None, True
    judged = [s for s in pool if s != "unevaluated"]
    return judged.count("degraded") / len(judged), False


def r1_1(single: Sequence[Judgment], ab: Sequence[Judgment]) -> Falsification:
    """R1-1: 比較相手のどちらかで、構造 ((c)(d)(e)) だけで数えた劣化の率が 0.10 を超える。"""
    parts: list[str] = []
    indeterminate = False
    fired = False
    for name, js in (("single", single), ("AB", ab)):
        rate, unk = _structure_rate(js)
        if unk:
            indeterminate = True
            parts.append(f"{name}: indeterminate")
            continue
        parts.append(f"{name}: {rate:.3f}")
        if rate is not None and rate > _RATE_R1:
            fired = True
    state = "fired" if fired else ("indeterminate" if indeterminate else "not_fired")
    return Falsification("R1-1", state, "; ".join(parts))


def r1_2(transplant_vs_template: Sequence[Judgment]) -> Falsification:
    """R1-2: X-transplant を「テンプレート」、テンプレートを比較相手にした劣化の率が 0.10 以下なら発火 (1B の縮小)。"""
    st = [j.status for j in transplant_vs_template]
    n = st.count("degraded") + st.count("not_degraded")
    if n < _MIN_EVALUABLE:
        return Falsification("R1-2", "indeterminate", f"N={n}<{_MIN_EVALUABLE}")
    rate = st.count("degraded") / n
    return Falsification("R1-2", "fired" if rate <= _RATE_R1 else "not_fired", f"rate={rate:.3f}, N={n}")


def exceeds_equivalence(case: CaseInput, arm_a: str, arm_b: str) -> bool | None:
    """R1-3: 2 アームの差が §2.1 の同値幅を**どちらの向きにでも**超えるか。判定できなければ None。"""
    a = case.arms[arm_a]
    b = case.arms[arm_b]
    if a.failed and b.failed:
        return None
    if a.failed != b.failed:
        return True
    checks: list[bool] = []
    if (a.chi2 is not None and b.chi2 is not None and math.isfinite(a.chi2) and math.isfinite(b.chi2)
            and b.chi2 > 0.0 and a.obs_hash is not None and a.obs_hash == b.obs_hash):
        ratio = a.chi2 / b.chi2
        checks.append(ratio > CHI2_RATIO_MARGIN or ratio < 1.0 / CHI2_RATIO_MARGIN)
    if case.reference is not None and case.lattice is not None:
        lattice = np.asarray(case.lattice, dtype=float)
        da = deviations(case.reference, a.values, lattice=lattice, other=b.values)
        db = deviations(case.reference, b.values, lattice=lattice, other=a.values)
        ma = metrics(da.values, unevaluated=da.unevaluated)
        mb = metrics(db.values, unevaluated=db.unevaluated)
        if ma.d is not None and mb.d is not None:
            checks.append(abs(ma.d - mb.d) > D_MARGIN or abs((ma.n_out or 0) - (mb.n_out or 0)) >= N_OUT_MARGIN)
    if a.fail_count is not None and b.fail_count is not None:
        checks.append(a.fail_count != b.fail_count)
    if case.reference is None and a.short_bonds is not None and b.short_bonds is not None:
        checks.append(abs(a.short_bonds - b.short_bonds) >= SHORT_BOND_MARGIN)
    if not checks:
        return None
    return any(checks)


def r1_3(per_permutation: Mapping[str, Sequence[bool | None]]) -> Falsification:
    """R1-3: どれかの置換 j で、同値幅を超える事例の率が 0.10 を超えたら発火 (固定順の前提の撤回)。"""
    parts: list[str] = []
    fired = False
    any_judged = False
    for name, flags in per_permutation.items():
        judged = [f for f in flags if f is not None]
        if not judged:
            parts.append(f"{name}: no evaluable case")
            continue
        any_judged = True
        rate = sum(judged) / len(judged)
        parts.append(f"{name}: {rate:.3f} (N={len(judged)})")
        if rate > _RATE_R1:
            fired = True
    state = "fired" if fired else ("not_fired" if any_judged else "indeterminate")
    return Falsification("R1-3", state, "; ".join(parts))


@dataclass(frozen=True)
class SplitRow:
    """R1-4 の 1 事例。``both_perturbed``: 両アームで Phase B が走り摂動が実際に掛かった。"""

    both_perturbed: bool
    t_split: bool
    b_split: bool


def r1_4(rows: Sequence[SplitRow]) -> Falsification:
    """R1-4: ``(b − c) / N₄ > 0.10`` (b = T-AB だけ割れた・c = B-AB だけ割れた)。N₄ < 11 なら判定不能。"""
    pool = [r for r in rows if r.both_perturbed]
    n4 = len(pool)
    if n4 < _MIN_EVALUABLE:
        return Falsification("R1-4", "indeterminate", f"N4={n4}<{_MIN_EVALUABLE}")
    b = sum(1 for r in pool if r.t_split and not r.b_split)
    c = sum(1 for r in pool if r.b_split and not r.t_split)
    rate = (b - c) / n4
    return Falsification("R1-4", "fired" if rate > _RATE_R1 else "not_fired", f"(b={b} - c={c})/N4={n4} = {rate:.3f}")


@dataclass(frozen=True)
class ProbeRow:
    """反証プローブ 1 回 (§5.1 の行から R3 に要る列だけ)。``injected`` は S-eval の注入の有無 (hold-out は None)。"""

    probe_id: str
    phase_role: str  # main / minor
    injected: bool | None
    outcome: str  # refuted / not_refuted / not_refuted_low_power / unevaluated(...)
    power: float | None


def _detection(rows: Sequence[ProbeRow]) -> tuple[float | None, int, int]:
    judged = [r for r in rows if not r.outcome.startswith("unevaluated")]
    unev = len(rows) - len(judged)
    if not judged:
        return None, 0, unev
    return sum(1 for r in judged if r.outcome == "refuted") / len(judged), len(judged), unev


def r3(rows: Sequence[ProbeRow], *, holdout_power: Sequence[float]) -> Falsification:
    """R3: (i) S-eval の注入事例での検出率 (主相 < 0.8・副相 < 0.5) / (ii) 無注入での誤発火率 > 0.10 /
    (iii) hold-out の主相プローブの検出力の中央値 < 0.8。プローブの unevaluated > 50% なら判定不能。"""
    seval = [r for r in rows if r.injected is not None]
    unev = sum(1 for r in seval if r.outcome.startswith("unevaluated"))
    if not seval or unev / len(seval) > _HALF:
        return Falsification("R3", "indeterminate", f"unevaluated {unev}/{len(seval)}")
    parts: list[str] = []
    fired = False
    missing = False
    for label, subset, floor, below in (
        ("main detection", [r for r in seval if r.injected and r.phase_role == "main"], _R3_MAIN_FLOOR, True),
        ("minor detection", [r for r in seval if r.injected and r.phase_role == "minor"], _R3_MINOR_FLOOR, True),
        ("false fire", [r for r in seval if not r.injected], _R3_FALSE_FIRE, False),
    ):
        rate, n, _ = _detection(subset)
        if rate is None:
            missing = True
            parts.append(f"{label}: no rows")
            continue
        parts.append(f"{label}: {rate:.3f} (N={n})")
        if (rate < floor) if below else (rate > floor):
            fired = True
    if holdout_power:
        med = statistics.median(holdout_power)
        parts.append(f"holdout power median: {med:.3f}")
        if med < _R3_POWER_FLOOR:
            fired = True
    else:
        missing = True
        parts.append("holdout power: no rows")
    state = "fired" if fired else ("indeterminate" if missing else "not_fired")
    return Falsification("R3", state, "; ".join(parts))
