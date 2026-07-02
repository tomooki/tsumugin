"""仮説ランキング: softmax + 温度較正確率と僅差競合フラグ (FR-122 / FR-124)。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from ..model import Hypothesis
from .base import EvidenceBackend, EvidenceResult


@dataclass(frozen=True)
class RankedHypothesis:
    hypothesis: Hypothesis
    evidence: EvidenceResult
    probability: float
    close_competitor: bool


def rank(
    hypotheses: Sequence[Hypothesis],
    backend: EvidenceBackend,
    *,
    temperature: float = 1.0,
    close_threshold: float = 10.0,
) -> tuple[RankedHypothesis, ...]:
    """evidence 値の昇順(良い順)に並べ、softmax 確率と僅差競合フラグを付与する。

    確率は softmax(-value / (2T))。BIC 近似では exp(-BIC/2) が相対事後確率に対応する。
    close_competitor は、最良仮説との evidence 差が close_threshold 未満であること。
    """
    if not hypotheses:
        return ()

    scored: list[tuple[Hypothesis, EvidenceResult]] = []
    for h in hypotheses:
        if h.metrics is None:
            raise ValueError(f"hypothesis {h.id!r} has no metrics; cannot score evidence")
        scored.append((h, backend.score(h.metrics)))

    scored.sort(key=lambda pair: pair[1].value)
    best_value = scored[0][1].value

    # softmax(-value / (2T)) with max-subtraction for numerical stability
    logits = [-(res.value) / (2.0 * temperature) for _, res in scored]
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    denom = sum(exps)
    probs = [e / denom for e in exps]

    ranked: list[RankedHypothesis] = []
    for (h, res), p in zip(scored, probs):
        close = (res.value - best_value) < close_threshold
        ranked.append(
            RankedHypothesis(
                hypothesis=h, evidence=res, probability=p, close_competitor=close
            )
        )
    return tuple(ranked)
