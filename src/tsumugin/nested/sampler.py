"""nested sampling evidence バックエンド (dynesty / ultranest 遅延 import)。REQ-004〜009/101/301。

``NestedBackend`` は拡張 Protocol ``ProblemAwareEvidenceBackend`` (``name`` + ``score(metrics)`` +
``score_problem(problem)``) に準拠する。実サンプラ (dynesty / ultranest) は **score_problem 実行時
にのみ遅延 import** し、``import tsumugin.nested.sampler`` 自体はコア (numpy) のみで成功する
(TC-502-02 / REQ-403)。

3 経路:

- ``score(metrics)``: 尤度関数を持たない狭い経路。nested は EvidenceProblem 必須のため、metrics のみ
  の場合は ``laplace.score(metrics)`` (BIC 近似) へ委譲して縮退する (REQ-007/101)。
- ``score_problem(problem)``: dynesty / ultranest を遅延 import し nested sampling を実行して
  ``EvidenceResult(backend="nested", value=-logZ, logz_err=<誤差>)`` を返す。未導入なら
  ``NestedUnavailableError`` を送出し extra 導入手順を案内する (REQ-004/005/006/007/EDGE-001)。
  seed は ``config.seed`` で固定し、2 回実行で logZ が logz_err 範囲内一致する (REQ-009/EDGE-014)。
- ``run_with_fallback(problem, *, ledger)``: 時間上限 (``config.time_limit_sec``) 超過や
  ``NestedUnavailableError`` を **例外化せず** truncated=True + Laplace 代替 value + 警告として返す
  (解析を止めない, REQ-101/405/EDGE-002)。ledger 非 None のとき打ち切り/実行を理由付き append する
  (REQ-013/NFR-105)。

**時間上限の実装 (設計判断)**: 実サンプラ実行 (``_run_nested``) を計時ラップし、経過時間が
``time_limit_sec`` を超えたら ``TimeoutError`` として扱って Laplace へ縮退する。決定論テストでは実行
フックを差し替えられる ``_run_with_fallback_using`` を内部に用意し、``TimeoutError`` /
``NestedUnavailableError`` の縮退経路を実サンプラ非依存で検証可能にする (未導入環境が主戦場)。

コア依存は numpy のみ (dynesty / ultranest は optional extra ``nested``, 遅延 import)。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Literal

import numpy as np

from ..errors import NestedUnavailableError
from ..evidence.base import EvidenceResult
from ..model import RefinementMetrics
from ..store.ledger import Ledger
from .base import EvidenceProblem
from .laplace import LaplaceBackend

# 未導入 (dynesty / ultranest) 時の案内文言 (extra 導入手順)。REQ-005/EDGE-001
_INSTALL_HINT = (
    "nested sampling には optional extra 'nested' (dynesty / ultranest) が必要です。"
    "`uv sync --extra nested` で導入してください。"
)

# 実サンプラ実行フックの型 (EvidenceProblem → EvidenceResult)。差し替え可能にしてテストを容易にする。
NestedRun = Callable[[EvidenceProblem], EvidenceResult]


@dataclass(frozen=True)
class NestedConfig:
    """nested sampling 実行設定。REQ-009/012/101/303。

    【再現性】: ``seed`` 固定でサンプラ種を固定し、logZ を誤差併記で再現可能にする (NFR-102 の nested 例外)。
    【時間上限】: ``time_limit_sec`` 超過で打ち切り + Laplace 代替 (REQ-101/NFR-103, 既定 30 分)。
    【実装選択】: ``sampler`` で dynesty / ultranest を選択する (REQ-303, いずれも optional extra ``nested``)。
    """

    sampler: Literal["dynesty", "ultranest"] = "dynesty"  # REQ-303
    seed: int = 0  # 【サンプラ乱数種 (固定・再現性)】 REQ-009/NFR-102
    n_live: int = 400  # 【live point 数】
    time_limit_sec: float = 1800.0  # 【時間上限 (既定 30 分)】 REQ-101/NFR-103
    max_calls: int | None = None  # 【尤度評価回数上限 (任意の追加安全弁)】


@dataclass(frozen=True)
class NestedOutcome:
    """nested 実行の詳細 (evidence + 打ち切り/フォールバック情報)。REQ-006/007/101。

    ``EvidenceResult`` (value=-logZ, logz_err) に加え、打ち切り・Laplace 代替の有無を型付きで保持する。
    ``truncated=True`` のとき ``result`` は Laplace 代替の値 (符号統一), ``logz`` は None。
    """

    result: EvidenceResult  # 【evidence (value=-logZ 相当, logz_err 併記)】 REQ-006/007
    logz: float | None  # 【logZ 生値 (付随情報・打ち切り時 None)】 REQ-007
    truncated: bool = False  # 【時間上限打ち切り (Laplace 代替へ縮退)】 REQ-101/EDGE-002
    warnings: tuple[str, ...] = ()  # 【打ち切り/フォールバック警告】 REQ-101


@dataclass(frozen=True)
class NestedBackend:
    """nested sampling evidence バックエンド (dynesty / ultranest 遅延 import)。REQ-004〜009/101。

    【ProblemAwareEvidenceBackend 準拠】: ``name`` + ``score(metrics)`` + ``score_problem(problem)``。
      ``score(metrics)`` は尤度関数を持たないため Laplace 代替へ委譲して縮退する (REQ-007/101)。
    【遅延 import (REQ-004/403)】: dynesty / ultranest は ``score_problem`` 実行時にのみ import。
      未導入なら ``NestedUnavailableError`` を送出し extra 導入手順を案内する。
    【logZ±誤差 (REQ-006/009/EDGE-014)】: ``EvidenceResult.value=-logZ``、``logz_err`` に誤差を格納。
      seed 固定で 2 回実行し logZ が logz_err 範囲内で一致する (ビット同一でなく誤差範囲一致)。
    【時間上限 (REQ-101/EDGE-002)】: ``run_with_fallback`` が time_limit 超過 / 未導入を検知したら
      打ち切り、``laplace`` を代替に用いた NestedOutcome (truncated=True, 警告付き) を返す (例外化しない)。
    """

    config: NestedConfig = field(default_factory=NestedConfig)
    laplace: LaplaceBackend = field(default_factory=LaplaceBackend)  # 【打ち切り代替先】 REQ-101
    name: str = "nested"

    # ------------------------------------------------------------------
    # ProblemAwareEvidenceBackend 準拠
    # ------------------------------------------------------------------

    def score(self, metrics: RefinementMetrics) -> EvidenceResult:
        """metrics のみの縮退経路。尤度関数を欠くため Laplace 代替へ委譲する。REQ-007/101。"""
        return self.laplace.score(metrics)

    def score_problem(self, problem: EvidenceProblem) -> EvidenceResult:
        """nested を起動し value=-logZ + logz_err を返す。未導入は NestedUnavailableError。REQ-004〜009。

        【遅延 import】: ``config.sampler`` に応じ dynesty / ultranest を関数内で import する。
          未導入なら ``NestedUnavailableError`` を送出して extra 導入手順を案内する (EDGE-001)。
        【打ち切り】: 時間上限は ``run_with_fallback`` 経由で扱う。本メソッドは実サンプラの評価窓 (@nested)。
        """
        return self._run_nested(problem)

    def run_with_fallback(
        self, problem: EvidenceProblem, *, ledger: Ledger | None = None
    ) -> NestedOutcome:
        """nested 実行を時間上限付きで回し、超過 / 未導入なら Laplace 代替へ縮退した NestedOutcome を返す。

        REQ-101/EDGE-002。時間上限超過 / ``NestedUnavailableError`` を例外化せず truncated=True +
        Laplace 代替 value + 警告として返す (解析全体を止めない, REQ-101/405)。ledger 非 None のとき
        打ち切り / 実行を理由付きで append する (REQ-013/NFR-105)。
        """
        return self._run_with_fallback_using(problem, run=self._run_nested_timed, ledger=ledger)

    # ------------------------------------------------------------------
    # 内部 (テスト差し替え可能な実行フック)
    # ------------------------------------------------------------------

    def _run_nested_timed(self, problem: EvidenceProblem) -> EvidenceResult:
        """実サンプラ実行を計時ラップし、``time_limit_sec`` 超過なら TimeoutError を送出する。REQ-101。

        実サンプラは長時間走り得るため、実行後に経過時間を評価し上限超過を打ち切り扱いにする
        (協調的な時間監視)。実サンプラ非依存の決定論テストは ``_run_with_fallback_using`` の
        ``run`` 差し替えで超過 / 未導入を模す。
        """
        start = time.monotonic()
        result = self._run_nested(problem)
        elapsed = time.monotonic() - start
        if elapsed > self.config.time_limit_sec:
            raise TimeoutError(
                f"nested sampling が時間上限 {self.config.time_limit_sec}s を超過しました "
                f"(経過 {elapsed:.1f}s)。"
            )
        return result

    def _run_nested(self, problem: EvidenceProblem) -> EvidenceResult:
        """dynesty / ultranest を遅延 import して nested sampling を実行する。REQ-004〜009/EDGE-001。

        未導入なら ``NestedUnavailableError`` を送出する。事前分布は ``problem.priors`` の
        ``PriorSpec.transform`` を prior transform に使い、尤度は ``problem.log_likelihood``。
        seed は ``config.seed`` で固定する。
        """
        if self.config.sampler == "ultranest":
            return self._run_ultranest(problem)
        return self._run_dynesty(problem)

    def _prior_transform(self, problem: EvidenceProblem) -> Callable[[np.ndarray], np.ndarray]:
        """単位超立方体 [0,1]^d の点を各次元の ``PriorSpec.transform`` で物理量へ写す関数を返す。REQ-008。"""
        priors = problem.priors

        def transform(u: np.ndarray) -> np.ndarray:
            arr = np.asarray(u, dtype=float)
            return np.array(
                [priors[i].transform(float(arr[i])) for i in range(len(priors))], dtype=float
            )

        return transform

    def _run_dynesty(self, problem: EvidenceProblem) -> EvidenceResult:
        """dynesty を遅延 import して nested sampling を実行する。REQ-004/006/009。"""
        try:
            import dynesty  # noqa: PLC0415  (遅延 import: REQ-403)
        except ImportError as exc:
            raise NestedUnavailableError(_INSTALL_HINT) from exc

        ndim = len(problem.priors)
        prior_transform = self._prior_transform(problem)
        rng = np.random.default_rng(self.config.seed)

        def loglike(theta: np.ndarray) -> float:
            return float(problem.log_likelihood(np.asarray(theta, dtype=float)))

        sampler = dynesty.NestedSampler(
            loglike,
            prior_transform,
            ndim,
            nlive=self.config.n_live,
            rstate=rng,
        )
        run_kwargs: dict[str, object] = {}
        if self.config.max_calls is not None:
            run_kwargs["maxcall"] = self.config.max_calls
        sampler.run_nested(print_progress=False, **run_kwargs)
        results = sampler.results
        logz = float(results.logz[-1])
        logz_err = float(results.logzerr[-1])
        # 符号統一: value = -logZ (小さいほど良い)
        return EvidenceResult(backend=self.name, value=-logz, logz_err=logz_err)

    def _run_ultranest(self, problem: EvidenceProblem) -> EvidenceResult:
        """ultranest を遅延 import して nested sampling を実行する。REQ-004/006/009/303。"""
        try:
            import ultranest  # noqa: PLC0415  (遅延 import: REQ-403)
        except ImportError as exc:
            raise NestedUnavailableError(_INSTALL_HINT) from exc

        prior_transform = self._prior_transform(problem)
        param_names = [p.param_name for p in problem.priors]

        def loglike(theta: np.ndarray) -> float:
            return float(problem.log_likelihood(np.asarray(theta, dtype=float)))

        np.random.seed(self.config.seed)  # ultranest は numpy 大域 RNG を用いる (種固定)
        sampler = ultranest.ReactiveNestedSampler(param_names, loglike, prior_transform)
        result = sampler.run(min_num_live_points=self.config.n_live, show_status=False)
        logz = float(result["logz"])
        logz_err = float(result["logzerr"])
        return EvidenceResult(backend=self.name, value=-logz, logz_err=logz_err)

    def _run_with_fallback_using(
        self,
        problem: EvidenceProblem,
        *,
        run: NestedRun,
        ledger: Ledger | None,
    ) -> NestedOutcome:
        """``run`` フックで nested を実行し、TimeoutError / NestedUnavailableError を縮退する共通実装。

        REQ-101/EDGE-002。実行フックを引数化することで、実サンプラ非依存の決定論テストが超過 / 未導入を
        模せる (未導入環境が主戦場)。成功時は nested 値、縮退時は Laplace 代替値を返す。
        """
        try:
            result = run(problem)
        except (NestedUnavailableError, TimeoutError) as exc:
            fallback = self.laplace.score_problem(problem)
            reason = "nested_unavailable" if isinstance(exc, NestedUnavailableError) else "time_limit"
            warning = (
                f"nested sampling を打ち切り Laplace 代替へ縮退しました (理由={reason}): {exc}"
            )
            if ledger is not None:
                ledger.append(
                    "nested_fallback",
                    {
                        "label": problem.label,
                        "sampler": self.config.sampler,
                        "reason": reason,
                        "time_limit_sec": self.config.time_limit_sec,
                        "fallback_backend": self.laplace.name,
                        "fallback_value": fallback.value,
                        "message": str(exc),
                    },
                )
            return NestedOutcome(
                result=fallback, logz=None, truncated=True, warnings=(warning,)
            )

        # 成功: value = -logZ から logZ を復元 (符号統一)
        logz = -result.value
        if ledger is not None:
            ledger.append(
                "nested_run",
                {
                    "label": problem.label,
                    "sampler": self.config.sampler,
                    "seed": self.config.seed,
                    "backend": result.backend,
                    "value": result.value,
                    "logz": logz,
                    "logz_err": result.logz_err,
                },
            )
        return NestedOutcome(result=result, logz=logz, truncated=False)
