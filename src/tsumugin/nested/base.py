"""nested evidence 拡張の型基盤 (拡張 Protocol + 補助 dataclass)。REQ-008/D1/FR-125。

既存 ``EvidenceBackend`` Protocol (``score(metrics)`` の狭いシグネチャ) は **不変** に保つ (D1)。
nested/laplace が必要とする追加入力 (尤度評価関数・事前分布・MAP 点・Hessian) を補助 dataclass
``EvidenceProblem`` に束ね、別メソッド ``score_problem`` を持つ拡張 Protocol
``ProblemAwareEvidenceBackend`` で受け渡す。既存 ``score(metrics)`` 経路を壊さない。

事前分布 ``PriorSpec`` は単位超立方体 [0,1]^d 上の点を各次元で物理量へ写す逆 CDF (prior transform)
を持つ。nested サンプラはこの ``transform`` で単位区間サンプルを物理量に変換する。逆 CDF は
**numpy のみ** で実装する (コア依存は numpy — scipy 不可)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Literal, Protocol, runtime_checkable

import numpy as np

from ..evidence.base import EvidenceResult
from ..model import RefinementMetrics

# θ ベクトル → 対数尤度 (nested/laplace が評価する尤度関数の型)。REQ-006
LogLikelihood = Callable[[np.ndarray], float]

# 単位区間 [0,1] の端点で逆 CDF が ±inf に飛ぶのを避けるためのクリップ幅。
# u をこの微小量だけ内側に寄せて有限値へ写す (nested 次元の端点で inf を出さない)。
_UNIT_EPS = 1e-12


def _norm_ppf(p: float) -> float:
    """標準正規分布の逆 CDF (分位点関数) を numpy のみで近似する。REQ-008/FR-125。

    Acklam の有理式近似 (相対誤差 ~1.15e-9) を用い、scipy に依存せず標準正規の
    Φ^{-1}(p) を返す。p は (0,1) にクリップして端点の発散を避ける。
    """
    p = min(max(p, _UNIT_EPS), 1.0 - _UNIT_EPS)

    # Acklam 係数 (下側・中央・上側領域)
    a = (
        -3.969683028665376e01,
        2.209460984245205e02,
        -2.759285104469687e02,
        1.383577518672690e02,
        -3.066479806614716e01,
        2.506628277459239e00,
    )
    b = (
        -5.447609879822406e01,
        1.615858368580409e02,
        -1.556989798598866e02,
        6.680131188771972e01,
        -1.328068155288572e01,
    )
    c = (
        -7.784894002430293e-03,
        -3.223964580411365e-01,
        -2.400758277161838e00,
        -2.549732539343734e00,
        4.374664141464968e00,
        2.938163982698783e00,
    )
    d = (
        7.784695709041462e-03,
        3.224671290700398e-01,
        2.445134137142996e00,
        3.754408661907416e00,
    )

    p_low = 0.02425
    p_high = 1.0 - p_low
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        x = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    elif p <= p_high:
        q = p - 0.5
        r = q * q
        x = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
        )
    else:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        x = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0
        )
    return x


def _norm_cdf(x: float) -> float:
    """標準正規分布の CDF Φ(x) を ``math.erf`` (numpy 相当・標準ライブラリ) で計算する。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass(frozen=True)
class PriorSpec:
    """1 パラメータの事前分布 (単位区間 → 物理量の逆 CDF 変換で表現)。REQ-008/FR-125。

    nested サンプラは単位超立方体 [0,1]^d 上の点を各次元の ``transform`` で物理量へ写す。
    restraint 由来の区間 (格子シフト上限・占有率 [0,1] 拘束等) から自動構成し、手動上書きも
    受理する (REQ-301)。逆 CDF は numpy のみで実装し scipy に依存しない。
    """

    param_name: str  # 【パラメータ名】: "phase0.lattice.a" / "global.occ.site" 等
    kind: Literal["uniform", "normal", "truncated_normal"] = "uniform"
    low: float = 0.0  # 【下限 (uniform / truncated)】
    high: float = 1.0  # 【上限 (uniform / truncated)】
    loc: float = 0.0  # 【中心 (normal 系)】
    scale: float = 1.0  # 【幅 (normal 系)】

    def transform(self, u: float) -> float:
        """単位区間 [0,1] の u を物理量へ写す逆 CDF 変換 (prior transform)。REQ-008/FR-125。

        - uniform: ``low + (high - low) * u``。
        - normal: 平均 ``loc``・標準偏差 ``scale`` の正規分布の逆 CDF。
        - truncated_normal: 区間 ``[low, high]`` に切断した正規分布の逆 CDF。

        u=0/1 の端点は有限値へクリップし ±inf を避ける (nested 次元端点の安定化)。
        """
        uc = min(max(u, 0.0), 1.0)
        if self.kind == "uniform":
            return self.low + (self.high - self.low) * uc
        if self.kind == "normal":
            return self.loc + self.scale * _norm_ppf(uc)
        # truncated_normal: [low, high] 切断正規の逆 CDF
        # 切断区間を標準化し、CDF 空間で線形補間してから逆 CDF を取る。
        alpha = (self.low - self.loc) / self.scale
        beta = (self.high - self.loc) / self.scale
        cdf_a = _norm_cdf(alpha)
        cdf_b = _norm_cdf(beta)
        if cdf_b - cdf_a <= 0.0:
            # 数値縮退 (区間が事実上ゼロ幅) は uniform 端点補間へ縮退
            return self.low + (self.high - self.low) * uc
        p = cdf_a + uc * (cdf_b - cdf_a)
        z = _norm_ppf(p)
        value = self.loc + self.scale * z
        # 数値誤差で境界を僅かに越える場合に備え区間へクランプ
        return min(max(value, self.low), self.high)


@dataclass(frozen=True)
class EvidenceProblem:
    """nested/laplace が evidence を評価するのに必要な追加入力の束。REQ-008/D1。

    【D1 の核】: ``EvidenceBackend.score(metrics)`` の狭いシグネチャでは尤度関数/事前分布/
      MAP/Hessian を渡せない。これらを本 dataclass に束ね ``score_problem(problem)`` で受け渡す。
      ``metrics`` も同梱し、縮退時に BIC/Laplace フォールバックへ渡せるようにする (REQ-002/101)。
    【決定論】: ``priors`` は param_name 昇順で保持し nested の次元順を固定する (NFR-102)。
    """

    metrics: RefinementMetrics  # 【フォールバック用 metrics (chi2/n_params/n_obs)】
    log_likelihood: LogLikelihood  # 【θ ベクトル → 対数尤度】
    priors: tuple[PriorSpec, ...]  # 【事前分布 (param_name 昇順)】
    map_point: np.ndarray | None = None  # 【MAP 推定点 (Laplace の展開中心)】
    hessian: np.ndarray | None = None  # 【負対数尤度の Hessian (Laplace)】
    label: str = ""  # 【問題識別 (ledger 記録用)】


@runtime_checkable
class ProblemAwareEvidenceBackend(Protocol):
    """尤度関数を要する evidence バックエンドの拡張境界。REQ-004/D1。

    既存 ``EvidenceBackend`` (``score(metrics)``) を **構造的に包含** し、追加で ``score_problem``
    を要求する。bic/aic は本 Protocol を実装しない (``score_problem`` を持たないため後方互換)。
    laplace/nested のみ実装し、階層的裁定はこの型で受ける。
    """

    name: str

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        ...

    def score_problem(self, problem: EvidenceProblem) -> EvidenceResult:
        ...
