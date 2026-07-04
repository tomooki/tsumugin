"""Laplace 近似 evidence バックエンド (M5 / REQ-001/002/003/EDGE-005/FR-121)。

``LaplaceBackend`` は既存 ``EvidenceBackend`` Protocol (``name`` + ``score(metrics)``) に準拠し、
既存 ``rank``/``evidence`` 経路に混在可能 (符号規約: value 小さいほど良い, REQ-003)。加えて
拡張 Protocol ``ProblemAwareEvidenceBackend`` の ``score_problem(problem)`` を実装し、尤度関数 +
MAP 点 + Hessian が渡せる場合に Laplace 近似 evidence を計算する (D1)。

2 つの経路:

- ``score(metrics)``: Hessian を持たない狭い経路。BIC 近似 (chi2 + k ln max(n_obs,1)) へ縮退し
  ``EvidenceResult(backend="laplace", value=<BIC値>)`` を返す。BIC 式は ``evidence.ic.BICBackend``
  と同一 (符号統一・BIC 比較の一貫性, REQ-002/003)。
- ``score_problem(problem)``: MAP 点 + Hessian があれば Laplace 近似 evidence を計算する。
    log Z_laplace ≈ logL_map + (k/2) ln(2π) − (1/2) ln|H|
  (k = パラメータ数, H = 負対数尤度の Hessian)。符号統一で ``value = -log Z_laplace`` を返す。
  Hessian が特異/取得不能 (map_point/hessian が None・det≤0・非正定値・数値エラー) なら例外化せず
  ``score(metrics)`` の BIC 近似へフォールバックする (EDGE-005/REQ-002)。

**フォールバックの表現 (設計判断)**: ``EvidenceResult`` は M0 定義の ``(backend, value, logz_err)``
のみで警告フィールドを持たない。後方互換のため本型は変更しない。Laplace は点推定で誤差を持たないため
成功時・フォールバック時とも ``logz_err=None`` とし、**フォールバックしたことは value が BIC 値
(= ``score(metrics).value``) に一致することで呼び出し側から検証可能**にする (成功時は Laplace 式の値、
特異時は BIC 式の値で区別できる)。

コア依存は numpy のみ (行列式・正定値判定は ``np.linalg.slogdet`` / ``np.linalg.eigvalsh``。
scipy 非依存, REQ-403)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from ..evidence.base import EvidenceResult
from ..model import RefinementMetrics
from .base import EvidenceProblem


def _bic_value(metrics: RefinementMetrics) -> float:
    """BIC 近似値 chi2 + k ln max(n_obs,1) (``evidence.ic.BICBackend`` と同一式)。REQ-002/003。

    n_obs=0 (空パターン等の縮退) は log(max(0,1))=log(1)=0 として非例外化する (BICBackend と統一)。
    """
    return metrics.chi2 + metrics.n_params * math.log(max(metrics.n_obs, 1))


@dataclass(frozen=True)
class LaplaceBackend:
    """Hessian 由来の Laplace 近似 evidence バックエンド。REQ-001/002/003/EDGE-005/FR-121。

    【EvidenceBackend 準拠】: ``name`` + ``score(metrics)`` を持ち、既存 rank/evidence 経路に混在可能
      (符号規約: value 小さいほど良い, REQ-003)。metrics のみで呼ばれた場合は BIC 近似へ縮退する。
    【Laplace 近似】: ``EvidenceProblem`` (尤度関数 + MAP 点 + Hessian) が渡せる場合は
      value = -log Z_laplace ≈ -( logL_map + (k/2)ln(2π) - (1/2)ln|H| ) を返す (符号統一で -logZ)。
    【縮退フォールバック (EDGE-005)】: Hessian が特異/取得不能なら BIC 近似 (chi2 + k ln n) へ縮退し、
      value が ``score(metrics).value`` に一致することでフォールバックを表現する (例外化しない, REQ-002)。
      nested 打ち切り時の代替先でもある (REQ-101)。
    """

    name: str = "laplace"

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        """metrics のみの狭い経路。Hessian が無いため BIC 近似で縮退する。REQ-002/003。

        符号規約は既存 IC 系と統一 (value 小さいほど良い)。BIC 式は ``BICBackend`` と同一値。
        """
        return EvidenceResult(backend=self.name, value=_bic_value(metrics))

    def score_problem(self, problem: EvidenceProblem) -> EvidenceResult:
        """尤度 + Hessian を用いた Laplace evidence。特異時は score(metrics) へフォールバック。REQ-002/EDGE-005。

        log Z_laplace ≈ logL_map + (k/2)ln(2π) - (1/2)ln|H| を計算し、符号統一で value=-logZ を返す。
        map_point/hessian が None・Hessian が非正定値/特異 (det≤0)・数値エラーのときは例外を上げず
        ``score(problem.metrics)`` の BIC 近似へフォールバックする (value が BIC 値に一致)。
        """
        map_point = problem.map_point
        hessian = problem.hessian

        # 取得不能: MAP 点または Hessian が無い → BIC フォールバック
        if map_point is None or hessian is None:
            return self.score(problem.metrics)

        try:
            h = np.asarray(hessian, dtype=float)
            theta = np.asarray(map_point, dtype=float)

            # パラメータ数 k: priors があれば len(priors)、無ければ map_point 次元
            k = len(problem.priors) if problem.priors else int(theta.size)

            # 正定値判定: 対称固有値がすべて正であること (非正定値・特異は縮退)
            # np.linalg.eigvalsh は対称行列を仮定するため対称化してから評価する。
            h_sym = 0.5 * (h + h.T)
            eigvals = np.linalg.eigvalsh(h_sym)
            if not np.all(eigvals > 0.0):
                return self.score(problem.metrics)

            # 行列式 (対数)。正定値なら slogdet の符号は +1・logdet は有限。
            sign, logdet = np.linalg.slogdet(h_sym)
            if sign <= 0.0 or not math.isfinite(logdet):
                return self.score(problem.metrics)

            logl_map = float(problem.log_likelihood(theta))
            if not math.isfinite(logl_map):
                return self.score(problem.metrics)

            logz = logl_map + (k / 2.0) * math.log(2.0 * math.pi) - 0.5 * float(logdet)
            if not math.isfinite(logz):
                return self.score(problem.metrics)

            return EvidenceResult(backend=self.name, value=-logz)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            # 数値エラー全般 (特異・非有限入力等) は例外化せず BIC フォールバック (EDGE-005)
            return self.score(problem.metrics)
