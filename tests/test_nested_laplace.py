"""TASK-0048 nested/laplace の契約テスト (LaplaceBackend・score/score_problem・BIC フォールバック)。

検証 (AC: TC-501-01/02/03):
- LaplaceBackend が name="laplace"・EvidenceBackend/ProblemAwareEvidenceBackend として振る舞う
  (REQ-001/D1)
- score(metrics) が BIC 式 (chi2 + k ln max(n_obs,1)) と一致し、value 小さいほど良い符号規約で
  rank に混在できる (REQ-002/003)
- score_problem: 正定値 Hessian + MAP + log_likelihood のとき Laplace 近似 -logZ を返す (手計算一致)
- score_problem: hessian=None / 特異 (det<=0) / 非正定値 のとき BIC フォールバック
  (value == score(metrics).value, EDGE-005)
- score/score_problem が同一入力でビット同一 (決定論・NFR-102)
- コア (numpy) のみで import 成功 (REQ-403)
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.evidence.base import EvidenceBackend, EvidenceResult
from tsumugin.model import Hypothesis, RefinementMetrics
from tsumugin.model.phase import LatticeParams, PhaseInstance


def _metrics(chi2: float, n_params: int, n_obs: int) -> RefinementMetrics:
    return RefinementMetrics(
        rwp=1.0, gof=1.0, chi2=chi2, n_obs=n_obs, n_params=n_params
    )


def _bic_value(chi2: float, n_params: int, n_obs: int) -> float:
    return chi2 + n_params * math.log(max(n_obs, 1))


def test_import_core_only():
    import tsumugin.nested.laplace as laplace  # noqa: F401


def test_laplace_backend_name_and_protocols():
    from tsumugin.nested.base import ProblemAwareEvidenceBackend
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    assert backend.name == "laplace"
    # EvidenceBackend (score) と ProblemAwareEvidenceBackend (score + score_problem) の両方
    assert isinstance(backend, EvidenceBackend)
    assert isinstance(backend, ProblemAwareEvidenceBackend)


def test_laplace_backend_is_frozen():
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    with pytest.raises(Exception):
        backend.name = "other"  # type: ignore[misc]


def test_score_matches_bic_formula():
    # TC-501-01: score(metrics) は BIC 式と同一値・backend 名のみ "laplace"
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=12.0, n_params=4, n_obs=200)
    res = backend.score(metrics)
    assert isinstance(res, EvidenceResult)
    assert res.backend == "laplace"
    assert res.value == pytest.approx(_bic_value(12.0, 4, 200))
    assert res.logz_err is None


def test_score_bic_degenerate_n_obs_zero():
    # n_obs=0 は log(max(0,1))=0 で非例外化 (BICBackend と統一)
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    res = backend.score(_metrics(chi2=5.0, n_params=3, n_obs=0))
    assert res.value == pytest.approx(5.0)


def test_score_equals_bicbackend_value():
    # laplace の狭い経路は BICBackend と同値 (符号規約統一)
    from tsumugin.evidence.ic import BICBackend
    from tsumugin.nested.laplace import LaplaceBackend

    metrics = _metrics(chi2=7.5, n_params=2, n_obs=50)
    laplace_res = LaplaceBackend().score(metrics)
    bic_res = BICBackend().score(metrics)
    assert laplace_res.value == pytest.approx(bic_res.value)
    assert laplace_res.backend == "laplace"
    assert bic_res.backend == "bic"


def test_score_equals_bicbackend_value_with_noise_scale():
    # Issue #64 / FR-123 レビュー対応: LaplaceBackend._bic_value は evidence.ic の
    # _scaled_chi2_term を共有するため、noise_scale 設定時も BICBackend と厳密一致する
    # (以前は laplace 側が noise_scale を一切見ない独自の chi2 + k ln n 式だったため
    # noise_scale 設定 metrics で両者が乖離していた)。
    from tsumugin.evidence.ic import BICBackend
    from tsumugin.nested.laplace import LaplaceBackend

    metrics = RefinementMetrics(
        rwp=1.0, gof=1.0, chi2=90.0, n_obs=200, n_params=3, noise_scale=2.0
    )
    laplace_res = LaplaceBackend().score(metrics)
    bic_res = BICBackend().score(metrics)
    assert laplace_res.value == bic_res.value  # 厳密一致 (同一実装の共有)


def test_score_falls_back_correctly_for_invalid_noise_scale():
    # noise_scale が無効 (非有限/非正/アンダーフロー) でも従来式へ縮退し BICBackend と一致する。
    from tsumugin.evidence.ic import BICBackend
    from tsumugin.nested.laplace import LaplaceBackend

    for invalid in (0.0, float("nan"), float("inf"), 1e-200):
        metrics = RefinementMetrics(
            rwp=1.0, gof=1.0, chi2=42.0, n_obs=80, n_params=4, noise_scale=invalid
        )
        laplace_res = LaplaceBackend().score(metrics)
        bic_res = BICBackend().score(metrics)
        assert laplace_res.value == bic_res.value


def test_rank_mixes_laplace_ascending():
    # TC-501-02: value 小さいほど良い符号規約で rank に混在できる
    from tsumugin.evidence.ranking import rank
    from tsumugin.nested.laplace import LaplaceBackend

    phase = (
        PhaseInstance(phase_ref="p", lattice=LatticeParams(a=5.0, b=5.0, c=5.0)),
    )
    # h_good は chi2 小 → BIC 小 → 上位
    h_good = Hypothesis(id="good", phases=phase, metrics=_metrics(5.0, 2, 100))
    h_bad = Hypothesis(id="bad", phases=phase, metrics=_metrics(50.0, 2, 100))
    ranked = rank([h_bad, h_good], LaplaceBackend())
    assert [r.hypothesis.id for r in ranked] == ["good", "bad"]
    assert all(r.evidence.backend == "laplace" for r in ranked)
    # 昇順 (良い順)
    assert ranked[0].evidence.value < ranked[1].evidence.value


def test_score_problem_laplace_gaussian_2d():
    # TC-501-03: 正定値 Hessian + MAP + logL の Laplace -logZ が手計算と一致
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    # logL(theta) = -0.5 * theta^T H theta, H = diag(2, 8), MAP = 0 → logL_map = 0
    hessian = np.diag([2.0, 8.0])

    def loglike(theta: np.ndarray) -> float:
        return -0.5 * float(theta @ hessian @ theta)

    problem = EvidenceProblem(
        metrics=_metrics(10.0, 2, 100),
        log_likelihood=loglike,
        priors=(PriorSpec(param_name="a"), PriorSpec(param_name="b")),
        map_point=np.zeros(2),
        hessian=hessian,
    )
    res = LaplaceBackend().score_problem(problem)
    # logZ = logL_map + (k/2)ln(2pi) - 0.5 ln|H|
    k = 2
    logl_map = 0.0
    sign, logdet = np.linalg.slogdet(hessian)  # ln(16)
    logz = logl_map + (k / 2.0) * math.log(2.0 * math.pi) - 0.5 * logdet
    assert res.backend == "laplace"
    assert res.value == pytest.approx(-logz)
    assert res.logz_err is None


def test_score_problem_uses_priors_len_as_k_when_map_absent_but_present_here():
    # k はパラメータ数 = len(priors) or map_point 次元。両者一致する健全ケース
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    hessian = np.diag([4.0])  # 1D

    def loglike(theta: np.ndarray) -> float:
        return -0.5 * float(theta @ hessian @ theta) + 3.0  # logL_map = 3.0 at 0

    problem = EvidenceProblem(
        metrics=_metrics(10.0, 1, 100),
        log_likelihood=loglike,
        priors=(PriorSpec(param_name="a"),),
        map_point=np.zeros(1),
        hessian=hessian,
    )
    res = LaplaceBackend().score_problem(problem)
    logz = 3.0 + 0.5 * math.log(2.0 * math.pi) - 0.5 * math.log(4.0)
    assert res.value == pytest.approx(-logz)


def test_score_problem_fallback_hessian_none():
    # EDGE-005: hessian=None → BIC フォールバック (value == score(metrics).value)
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=9.0, n_params=2, n_obs=80)
    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(PriorSpec(param_name="a"), PriorSpec(param_name="b")),
        map_point=np.zeros(2),
        hessian=None,
    )
    res = backend.score_problem(problem)
    assert res.backend == "laplace"
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_score_problem_fallback_map_none():
    # map_point=None も取得不能扱いで BIC フォールバック
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=9.0, n_params=2, n_obs=80)
    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(PriorSpec(param_name="a"),),
        map_point=None,
        hessian=np.eye(1),
    )
    res = backend.score_problem(problem)
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_score_problem_fallback_singular_det_zero():
    # 特異行列 (det=0) → BIC フォールバック
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=11.0, n_params=2, n_obs=120)
    singular = np.array([[1.0, 1.0], [1.0, 1.0]])  # det = 0
    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(PriorSpec(param_name="a"), PriorSpec(param_name="b")),
        map_point=np.zeros(2),
        hessian=singular,
    )
    res = backend.score_problem(problem)
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_score_problem_fallback_non_positive_definite():
    # 非正定値 (負の固有値) → BIC フォールバック (det>0 でも非正定値は縮退)
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=13.0, n_params=2, n_obs=90)
    # 固有値 -1, -4 → det = 4 > 0 だが負定値
    indefinite = np.diag([-1.0, -4.0])
    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(PriorSpec(param_name="a"), PriorSpec(param_name="b")),
        map_point=np.zeros(2),
        hessian=indefinite,
    )
    res = backend.score_problem(problem)
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_score_problem_fallback_saddle_point():
    # 鞍点 (固有値 +2, -3 → det=-6<0) → 非正定値で BIC フォールバック
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=6.0, n_params=2, n_obs=70)
    saddle = np.diag([2.0, -3.0])
    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(PriorSpec(param_name="a"), PriorSpec(param_name="b")),
        map_point=np.zeros(2),
        hessian=saddle,
    )
    res = backend.score_problem(problem)
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_determinism_score_bitwise():
    # NFR-102: score が 2 回ビット同一
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=8.3, n_params=3, n_obs=137)
    a = backend.score(metrics)
    b = backend.score(metrics)
    assert a.value == b.value
    assert repr(a) == repr(b)


def test_determinism_score_problem_bitwise():
    # NFR-102: score_problem が 2 回ビット同一 (Laplace 経路)
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    hessian = np.diag([2.0, 8.0, 3.0])

    def loglike(theta: np.ndarray) -> float:
        return -0.5 * float(theta @ hessian @ theta)

    problem = EvidenceProblem(
        metrics=_metrics(10.0, 3, 100),
        log_likelihood=loglike,
        priors=(
            PriorSpec(param_name="a"),
            PriorSpec(param_name="b"),
            PriorSpec(param_name="c"),
        ),
        map_point=np.zeros(3),
        hessian=hessian,
    )
    backend = LaplaceBackend()
    a = backend.score_problem(problem)
    b = backend.score_problem(problem)
    assert a.value == b.value
    assert repr(a) == repr(b)


def test_score_problem_k_equals_hessian_dim_when_priors_mismatch_absent():
    # MEDIUM-3: priors 空 (len=0) でも k は Hessian 次元 d を使う (map_point 2D と一致)
    from tsumugin.nested.base import EvidenceProblem
    from tsumugin.nested.laplace import LaplaceBackend

    hessian = np.diag([2.0, 8.0])  # d=2

    def loglike(theta: np.ndarray) -> float:
        return -0.5 * float(theta @ hessian @ theta)

    problem = EvidenceProblem(
        metrics=_metrics(10.0, 2, 100),
        log_likelihood=loglike,
        priors=(),  # 空 priors: 旧実装は k=theta.size にフォールバックしていた
        map_point=np.zeros(2),
        hessian=hessian,
    )
    res = LaplaceBackend().score_problem(problem)
    # k は Hessian 次元 d=2 を使う (正しい Laplace 値)
    k = 2
    sign, logdet = np.linalg.slogdet(hessian)
    logz = 0.0 + (k / 2.0) * math.log(2.0 * math.pi) - 0.5 * logdet
    assert res.value == pytest.approx(-logz)


def test_score_problem_fallback_priors_len_mismatch_hessian_dim():
    # MEDIUM-3: len(priors)=3 ・ Hessian 2x2 の次元不整合 → BIC フォールバックへ縮退
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=14.0, n_params=2, n_obs=110)
    hessian = np.diag([2.0, 8.0])  # d=2

    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(
            PriorSpec(param_name="a"),
            PriorSpec(param_name="b"),
            PriorSpec(param_name="c"),
        ),  # len=3 != d=2
        map_point=np.zeros(2),
        hessian=hessian,
    )
    res = backend.score_problem(problem)
    # 次元不整合は静かにバイアスせず BIC フォールバック (value == score(metrics).value)
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_score_problem_fallback_map_point_dim_mismatch_hessian_dim():
    # MEDIUM-3: map_point 3D ・ Hessian 2x2 の不整合 → BIC フォールバック
    from tsumugin.nested.base import EvidenceProblem, PriorSpec
    from tsumugin.nested.laplace import LaplaceBackend

    backend = LaplaceBackend()
    metrics = _metrics(chi2=15.0, n_params=2, n_obs=130)
    hessian = np.diag([2.0, 8.0])  # d=2

    problem = EvidenceProblem(
        metrics=metrics,
        log_likelihood=lambda t: 0.0,
        priors=(PriorSpec(param_name="a"), PriorSpec(param_name="b")),
        map_point=np.zeros(3),  # 3D != d=2
        hessian=hessian,
    )
    res = backend.score_problem(problem)
    assert res.value == pytest.approx(backend.score(metrics).value)


def test_reexport_from_nested_package():
    from tsumugin.nested import LaplaceBackend

    assert LaplaceBackend().name == "laplace"
