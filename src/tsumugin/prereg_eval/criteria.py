"""P0 §1.2 (50% 規則)・§2.2 (通過基準)・§2.3 (3 値の結論)。

- 比較相手ごとに、評価可能な件数 N (``degraded`` + ``not_degraded``) で ``Σ W_i ≤ c(N)``。N < N_min (24) なら判定不能。
- ``unevaluated`` が対象の 50% を超えた指標は判定不能。指標は **W_i 全体**と**構造の部分**の 2 つ
  (構造の部分の分母からは、失敗で決まった事例 = ``n/a`` と両方失敗を外す — 比べようがないのであって評価できなかったのではない)。
- 結論: はっきりした不通過 (どちらかの比較で ``fail``・反証の発火) があれば ``fail``。無くて判定不能が 1 つでもあれば
  ``indeterminate``。それ以外は ``pass`` (判定不能は通過ではない — §2.3)。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .case import Judgment
from .stats import allowed_failures

__all__ = ["N_MIN", "Comparison", "Conclusion", "compare", "conclude"]

#: P0 U1
N_MIN = 24
_HALF = 0.5


@dataclass(frozen=True)
class Comparison:
    n: int
    n_degraded: int
    n_unevaluated: int
    n_both_failed: int
    allowed: int | None
    verdict: str  # pass / fail / indeterminate
    indeterminate_because: tuple[str, ...]


@dataclass(frozen=True)
class Conclusion:
    verdict: str
    reasons: tuple[str, ...]


def compare(judgments: Sequence[Judgment], *, n_min: int = N_MIN) -> Comparison:
    """比較相手 1 つについての集計 (§2.2)。"""
    statuses = [j.status for j in judgments]
    n_deg = statuses.count("degraded")
    n = n_deg + statuses.count("not_degraded")
    n_unev = statuses.count("unevaluated")
    n_both = statuses.count("both_failed")
    because: list[str] = []
    targets = len(judgments) - n_both
    if targets == 0 or n_unev / targets > _HALF:
        because.append("W_i")
    structure = [j.structure for j in judgments if j.status != "both_failed" and j.structure != "n/a"]
    if structure and structure.count("unevaluated") / len(structure) > _HALF:
        because.append("structure")
    if n < n_min:
        because.append(f"N={n}<{n_min}")
    allowed = allowed_failures(n)
    if allowed is None:
        because.append("c(N) undefined")
    if because or allowed is None:
        verdict = "indeterminate"
    else:
        verdict = "pass" if n_deg <= allowed else "fail"
    return Comparison(n, n_deg, n_unev, n_both, allowed, verdict, tuple(because))


def conclude(
    single: Comparison, ab: Comparison, *, fired: Sequence[str], indeterminate: Sequence[str]
) -> Conclusion:
    """P2 の結論 (§2.3)。``fired``/``indeterminate`` は 1B の反証条件 (R1-1〜R1-4・R3) の id。"""
    pairs = (("T-single vs B-single", single), ("T-AB vs B-AB", ab))
    reasons = [f"{name}: fail ({c.n_degraded} > c(N)={c.allowed})" for name, c in pairs if c.verdict == "fail"]
    reasons.extend(f"{rid}: fired" for rid in fired)
    if reasons:
        return Conclusion("fail", tuple(reasons))
    reasons = [
        f"{name}: indeterminate ({', '.join(c.indeterminate_because)})"
        for name, c in pairs
        if c.verdict == "indeterminate"
    ]
    reasons.extend(f"{rid}: indeterminate" for rid in indeterminate)
    if reasons:
        return Conclusion("indeterminate", tuple(reasons))
    return Conclusion("pass", ())
