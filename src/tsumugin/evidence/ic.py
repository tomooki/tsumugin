"""情報量規準ベースの evidence (FR-121: bic 既定 / aic)。

Gaussian 残差・既知分散の仮定下では -2 ln L = chi2 + const。よって
  BIC = chi2 + k ln n,  AIC = chi2 + 2k
(定数項は仮説間比較で相殺するため省略)。いずれも小さいほど良い。
"""

from __future__ import annotations

import math

from ..model import RefinementMetrics
from .base import EvidenceResult


class BICBackend:
    name = "bic"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        # n_obs=0 (空パターン等の縮退) は log(1)=0 として非例外化する
        value = metrics.chi2 + metrics.n_params * math.log(max(metrics.n_obs, 1))
        return EvidenceResult(backend=self.name, value=value)


class AICBackend:
    name = "aic"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        value = metrics.chi2 + 2.0 * metrics.n_params
        return EvidenceResult(backend=self.name, value=value)
