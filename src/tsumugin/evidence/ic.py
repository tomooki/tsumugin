"""情報量規準ベースの evidence (FR-121: bic 既定 / aic)。

Gaussian 残差・既知分散の仮定下では -2 ln L = chi2 + const。よって
  BIC = chi2 + k ln n,  AIC = chi2 + 2k
(定数項は仮説間比較で相殺するため省略)。いずれも小さいほど良い。

【FR-123 ノイズスケール補正】: ``metrics.noise_scale`` (EM 推定した s、
``evidence.noise.estimate_noise_em`` 参照) が設定されているとき、分散モデルを
``Var(ε_i) = s²/w_i`` へ一般化した -2 ln L 補正を適用する:

    -2 ln L = n·ln(s²) + chi2/s² + const(w)   (const(w) は s に依らないため省略)

よって
    BIC = chi2/s² + n·ln(s²) + k·ln(n)
    AIC = chi2/s² + n·ln(s²) + 2k

``s=1`` を代入すると ``ln(1)=0`` かつ ``chi2/1=chi2`` で上式は厳密に既定式へ一致する。
``noise_scale is None`` (既定・後方互換) のときは s に触れる計算を一切行わず、
従来どおり chi2 をそのまま使う経路を通るため、既存呼び出しはビット同一の結果を返す。
"""

from __future__ import annotations

import math

from ..model import RefinementMetrics
from .base import EvidenceResult


def _scaled_chi2_term(metrics: RefinementMetrics) -> tuple[float, float]:
    """``(chi2 補正項, n·ln(s²) 補正項)`` を返す。noise_scale 無効時は ``(chi2, 0.0)``。

    【機能概要】: BIC/AIC 双方が共有するノイズスケール補正の中核 (chi2/s² と n·ln(s²))
      を単一実装へ集約する (Issue #64 / FR-123)。
    【後方互換ガード (s と s² の両方を判定, レビュー対応)】: ``noise_scale`` が ``None`` の
      ときは補正なし。``s <= 0.0`` (負値・ゼロ = 数学的に無効なスケール) も補正なし —
      負の s は ``s*s > 0`` になるため s² だけの判定では素通りし、誤った補正込み BIC を
      返してしまう (実測: s=-2.0 で chi2/4 補正が適用される)。さらに ``s2 = s*s`` を計算
      してから ``s2`` の有限性・正値性も検証する: 極小 s (例 ``noise_scale=1e-200``) は
      ``s`` 自体は有限かつ正だが ``s*s`` が float64 の下限を割ってちょうど 0.0 へ
      アンダーフローし、``chi2 / s2`` が ``ZeroDivisionError`` を送出してしまう (実測)。
      両方を判定基準にすることで「s=1 で既定式に厳密一致」の保証を壊れた s 値からも守る。
    🔵 信頼性レベル: モジュール docstring の式に直接対応 (ガード対象は Issue #64 レビュー対応)。
    """
    s = metrics.noise_scale
    if s is None or not math.isfinite(s) or s <= 0.0:
        return metrics.chi2, 0.0
    s2 = s * s
    if not math.isfinite(s2) or s2 <= 0.0:
        return metrics.chi2, 0.0
    return metrics.chi2 / s2, metrics.n_obs * math.log(s2)


class BICBackend:
    name = "bic"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        # n_obs=0 (空パターン等の縮退) は log(1)=0 として非例外化する
        chi2_term, scale_term = _scaled_chi2_term(metrics)
        value = chi2_term + scale_term + metrics.n_params * math.log(max(metrics.n_obs, 1))
        return EvidenceResult(backend=self.name, value=value)


class AICBackend:
    name = "aic"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        chi2_term, scale_term = _scaled_chi2_term(metrics)
        value = chi2_term + scale_term + 2.0 * metrics.n_params
        return EvidenceResult(backend=self.name, value=value)
