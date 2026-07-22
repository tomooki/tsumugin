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
  (k = パラメータ数 = Hessian 次元 d, H = 負対数尤度の Hessian)。符号統一で
  ``value = -log Z_laplace`` を返す。Hessian が特異/取得不能 (map_point/hessian が None・det≤0・
  非正定値・数値エラー) や **次元不整合** (map_point 次元 / len(priors) が Hessian 次元 d と食い違う)
  なら例外化せず ``score(metrics)`` の BIC 近似へフォールバックする (EDGE-005/REQ-002)。

**数値レビュー補足 (v2, Issue #76 / FR-125)**: 元の Laplace evidence 式は事前分布項
  ``log p(θ_map)`` を省いた**相対 evidence** だった ((k/2)ln(2π) − (1/2)ln|H| + logL_map の形)。
  v2 では ``problem.priors`` が非空かつ次元が Hessian と一致するとき、事前密度項
  ``log_prior = Σ_j priors[j].log_pdf(θ_map[j])`` (``PriorSpec.log_pdf``) を加算し、
  ``logZ = logL_map + log_prior + (k/2)ln(2π) − (1/2)ln|H|`` として**真の logZ Laplace 近似**
  (nested サンプラの logZ と直接比較可能な絶対 evidence) を返す。``log_prior`` が非有限
  (MAP が事前分布の台の外・退化事前分布等) なら例外化せず BIC フォールバックへ縮退する。
  ``priors`` が空の場合は事前項を加算せず**従来通り相対 evidence のまま** (後方互換)。
  ``k`` は必ず Hessian 次元 ``d = H.shape[0]`` を用い、(k/2)ln(2π) の次元と ln|H| の次元を厳密に
  一致させる (len(priors) や map_point 次元との食い違いによる静かなバイアスを避ける)。

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
from ..evidence.ic import _scaled_chi2_term
from ..model import RefinementMetrics
from .base import EvidenceProblem


def _bic_value(metrics: RefinementMetrics) -> float:
    """BIC 近似値 chi2 + k ln max(n_obs,1) (``evidence.ic.BICBackend`` と同一式)。REQ-002/003。

    n_obs=0 (空パターン等の縮退) は log(max(0,1))=log(1)=0 として非例外化する (BICBackend と統一)。
    【Issue #64 / FR-123 レビュー対応】: noise_scale 補正の中核 (chi2/s² 項・n·ln(s²) 項・
      degenerate ガード) を ``evidence.ic._scaled_chi2_term`` と共有し、式の二重実装 (ドリフトの
      温床) を解消する。``metrics.noise_scale`` が ``None``/無効なら補正なしで従来式と一致する
      (BICBackend と厳密に同一の計算式・同一のガード条件)。
    """
    chi2_term, scale_term = _scaled_chi2_term(metrics)
    return chi2_term + scale_term + metrics.n_params * math.log(max(metrics.n_obs, 1))


@dataclass(frozen=True)
class LaplaceBackend:
    """Hessian 由来の Laplace 近似 evidence バックエンド。REQ-001/002/003/EDGE-005/FR-121。

    【EvidenceBackend 準拠】: ``name`` + ``score(metrics)`` を持ち、既存 rank/evidence 経路に混在可能
      (符号規約: value 小さいほど良い, REQ-003)。metrics のみで呼ばれた場合は BIC 近似へ縮退する。
    【Laplace 近似】: ``EvidenceProblem`` (尤度関数 + MAP 点 + Hessian) が渡せる場合は
      value = -log Z_laplace ≈ -( logL_map + log_prior + (k/2)ln(2π) - (1/2)ln|H| ) を返す
      (符号統一で -logZ)。``priors`` が非空かつ次元一致なら log_prior = Σ priors[j].log_pdf(θ_map[j])
      を加算し絶対 evidence になる (v2, Issue #76)。``priors`` が空なら log_prior=0 (従来の相対 evidence)。
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

        log Z_laplace ≈ logL_map + log_prior + (k/2)ln(2π) - (1/2)ln|H| を計算し、符号統一で
        value=-logZ を返す (``priors`` 非空かつ次元一致なら log_prior を加算、v2 / Issue #76)。
        map_point/hessian が None・Hessian が非正定値/特異 (det≤0)・log_prior が非有限
        (MAP が事前分布の台の外等)・数値エラーのときは例外を上げず ``score(problem.metrics)`` の
        BIC 近似へフォールバックする (value が BIC 値に一致)。
        """
        map_point = problem.map_point
        hessian = problem.hessian

        # 取得不能: MAP 点または Hessian が無い → BIC フォールバック
        if map_point is None or hessian is None:
            return self.score(problem.metrics)

        try:
            h = np.asarray(hessian, dtype=float)
            theta = np.asarray(map_point, dtype=float)

            # 正定値判定: 対称固有値がすべて正であること (非正定値・特異は縮退)
            # np.linalg.eigvalsh は対称行列を仮定するため対称化してから評価する。
            h_sym = 0.5 * (h + h.T)

            # パラメータ数 k は必ず Hessian 次元 d を使う ((k/2)ln(2π) と ln|H| の次元を一致させ、
            # len(priors)/map_point 次元との食い違いによる静かな evidence バイアスを避ける)。
            # 非正方 Hessian・map_point 次元不整合・len(priors) 不整合は次元不整合として BIC 縮退する。
            if h_sym.ndim != 2 or h_sym.shape[0] != h_sym.shape[1]:
                return self.score(problem.metrics)
            d = int(h_sym.shape[0])
            if int(theta.size) != d:
                return self.score(problem.metrics)
            if problem.priors and len(problem.priors) != d:
                return self.score(problem.metrics)
            k = d
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

            # 【事前密度項 (v2, Issue #76/FR-125)】: priors が非空なら (この時点で len(priors)==d
            #   は上のガードで保証済み) 事前密度を加算し絶対 evidence 化する。priors が空なら
            #   log_prior=0 のまま従来の相対 evidence を維持する (後方互換)。
            log_prior = 0.0
            if problem.priors:
                log_prior = sum(
                    problem.priors[j].log_pdf(float(theta[j])) for j in range(d)
                )
                if not math.isfinite(log_prior):
                    # MAP が事前分布の台の外・退化事前分布等 → BIC フォールバック (例外化しない)
                    return self.score(problem.metrics)

            logz = (
                logl_map + log_prior + (k / 2.0) * math.log(2.0 * math.pi) - 0.5 * float(logdet)
            )
            if not math.isfinite(logz):
                return self.score(problem.metrics)

            return EvidenceResult(backend=self.name, value=-logz)
        except (np.linalg.LinAlgError, ValueError, FloatingPointError):
            # 数値エラー全般 (特異・非有限入力等) は例外化せず BIC フォールバック (EDGE-005)
            return self.score(problem.metrics)
