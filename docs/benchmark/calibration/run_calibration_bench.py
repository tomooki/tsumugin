"""較正ベンチ (仕様 §12-5 / Issue #72 前半): reliability diagram / ECE。

``bic`` と ``nested`` の確率較正を別々に評価する。既存の較正評価ユーティリティ
(``tsumugin.nested.calibration.calibrate_by_backend``) は「予測確率 + 正解フラグ」のサンプル列を
受け取って ECE / reliability ビンを返すだけの評価専用関数であり、温度較正 (T のフィット) 自体は
行わない。本スクリプトは (1) 合成の多仮説選択問題を決定論的に生成し、(2) ``evidence.ranking.rank``
(bic 系列) と 2 段構え裁定 (nested 系列, ``tsumugin.nested.arbitration.arbitrate`` と同一のロジック)
で予測確率を得て、(3) 温度 T=1 (較正前) と in-sample ECE 最小化でフィットした T (較正後) の双方を
``calibrate_by_backend`` で評価する。

問題設計 (§12-5 用の多仮説選択問題)
-----------------------------------
各問題は「主相 (常に存在) + 微弱な副相 (存在するか未知)」を真の構造として合成パターンを作り、
以下 2 種の仮説を候補にする:

- 真仮説 (``hyp-0000``): 主相+副相の両方を提案 (格子/scale は僅かにずらした初期値から精密化)。
- 偽仮説 (``hyp-0001``): 副相を見落とした主相単独モデル。
- 追加の偽仮説 (0〜2 個): 主相の格子を大きくずらした「明らかに違う」モデル (収束不能で確実に
  負ける。候補数を 2〜4 個に増やすためのノイズ役で確率質量にはほぼ影響しない)。

難易度パラメータは副相の scale (主相比の ``minor_frac``)。素朴に対数一様分布で振ると、BIC の
n_params·ln(n_obs) 罰則が離散的に効くせいで遷移帯 (ΔBIC が小さくなる領域) をほぼ外し、予測確率が
0/1 近傍に偏ってしまう (実測で確認済み)。そこで各問題ごとに「予測確率がちょうど 0.5 になる
minor_frac (決定境界)」を二分探索 (``_locate_decision_boundary``/``_locate_nested_boundary``) で
特定し、そこからの対数正規オフセット (``_BOUNDARY_LOG_OFFSET_SIGMA``) で minor_frac を選ぶ。
境界を直接ねらうのは中立的な基準点探索であり正解を強制しない — オフセットの符号次第で真仮説が
勝つことも負けることも自然に起こる。観測ノイズも問題ごとに混ぜる。

nested 系列の評価方法
----------------------
``nested.arbitration.arbitrate`` と同じ 2 段構え (bic 一次 → ΔBIC<10 の僅差競合のみ再裁定) を、
``nested.laplace.LaplaceBackend.score_problem`` で直接評価する形で再現する (``_laplace_rearbitrate``)。
各仮説について「その仮説の各相の (scale, 格子定数 a)」を局所パラメータとした尤度関数 + 数値 Hessian
から ``EvidenceProblem`` (MAP 点 + Hessian) を構成し、Laplace evidence
(``logZ_laplace ≈ logL_map + (k/2)ln(2π) − (1/2)ln|H|``) を得る。

bic の決定境界と nested の決定境界は一致しない — Laplace の Occam 因子 (-0.5·ln|H|) は BIC の
n_params·ln(n_obs) 罰則よりずっと弱く効くため、nested は僅かな副相でも「存在する」と確信しやすい。
bic 境界だけを中心にサンプリングすると nested 系列の予測確率がほぼ 1.0 の 1 ビンに縮退してしまう
ため、問題の一部 (``_NESTED_BOUNDARY_FRACTION``, 既定 30%) は nested 自身の決定境界を中心にする。

本環境には実サンプラ dynesty が導入済みだが、既定では起動しない —
較正ベンチは「決定論・数分以内の実行」を優先し、Laplace 経路 (``tsumugin.nested.laplace``) を既定に
採用する (仕様上も nested 裁定は Laplace 代替が既定路線、実 dynesty はコスト次第のオプション)。
実 dynesty で裁定したい場合は ``tsumugin.nested.sampler.NestedBackend`` +
``tsumugin.nested.arbitration.arbitrate(nested=...)`` を直接使うこと。

温度較正について
-----------------
``rank()``/``arbitrate()`` の softmax は ``softmax(-value/(2T))`` で、T は argmax を変えない
(順序不変)。よって「どの仮説が top-1 か」「正解かどうか」は T に依存せず、T は top-1 確率の
大きさのみを変える。本スクリプトはこの top-1 確率を対象に、reliability diagram 上の ECE を直接
最小化する T をグリッドサーチで求める (in-sample 較正。T=1 も探索点に含むため較正後 ECE は
較正前 ECE を超えない)。

乱数は ``np.random.default_rng(seed)`` で固定し、決定論を保証する (NFR-102)。

実行:
    ``uv run python docs/benchmark/calibration/run_calibration_bench.py``
    ``uv run python docs/benchmark/calibration/run_calibration_bench.py --n-problems 20 --seed 1``
"""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.evidence.ic import BICBackend
from tsumugin.evidence.ranking import rank
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance
from tsumugin.nested.base import EvidenceProblem, PriorSpec
from tsumugin.nested.calibration import CalibrationReport, CalibrationSample, calibrate_by_backend
from tsumugin.nested.laplace import LaplaceBackend
from tsumugin.pipeline import analyze_single_pattern

TWO_THETA = np.arange(15.0, 80.0, 0.02)
_SCALE_MAIN = 2.0
_CLOSE_THRESHOLD = 10.0  # rank()/arbitrate() の既定 ΔBIC 閾値と一致させる


# ---------------------------------------------------------------------------
# 問題生成
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Problem:
    """1 つの合成仮説選択問題 (真の主相+副相パターン + 候補仮説群)。"""

    idx: int
    intensity: np.ndarray
    candidates: tuple[tuple[PhaseInstance, ...], ...]
    correct_id: str
    minor_scale_fraction: float  # 【難易度メタ】: 副相 scale / 主相 scale (README 集計用)
    noise_fraction: float


def _phase(a: float, scale: float, ref: str) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _true_prob_for_minor_frac(
    minor_frac: float,
    *,
    a_main: float,
    a_minor: float,
    noise: np.ndarray,
    main_pattern: np.ndarray,
    start_main: float,
    start_minor: float,
    backend: SimulatedBackend,
) -> float:
    """指定 minor_frac での真仮説 (両相) の予測確率 (T=1)。minor_frac の単調増加関数。

    ``true_candidate`` vs ``missing_minor_candidate`` の 2 択部分問題のみで評価する (探索用の
    軽量な代理問題。最終問題は追加の「明らかに違う」偽仮説を混ぜるが、それらは BIC で圧倒的に
    負けるため確率質量に事実上影響しない)。
    """
    s_minor = minor_frac * _SCALE_MAIN
    y_clean = main_pattern + backend.simulate((_phase(a_minor, s_minor, "m"),), TWO_THETA)
    intensity = np.clip(y_clean + noise, 0.0, None)
    true_candidate = (
        _phase(start_main, 1.0, "M"),
        _phase(start_minor, s_minor * 0.7, "m"),
    )
    missing_minor_candidate = (_phase(start_main, 1.0, "M"),)
    result = analyze_single_pattern(
        TWO_THETA, intensity, [true_candidate, missing_minor_candidate], backend=backend
    )
    by_id = {r.hypothesis.id: r for r in result.ranked}
    return float(by_id["hyp-0000"].probability)


def _locate_decision_boundary(
    *,
    a_main: float,
    a_minor: float,
    noise: np.ndarray,
    main_pattern: np.ndarray,
    start_main: float,
    start_minor: float,
    backend: SimulatedBackend,
    iters: int = 10,
) -> float:
    """真仮説の予測確率がちょうど 0.5 になる minor_frac (決定境界) を対数空間の二分探索で求める。

    ``_true_prob_for_minor_frac`` は minor_frac の単調増加関数 (副相が強いほど真仮説が勝つ) なので
    二分探索が成立する。この境界を基準に対数オフセットを振ることで、正解/不正解が自然に (=強制せず)
    両方生じつつ、較正前確率が 0.5〜1.0 の範囲へ分布するようにする (境界近傍ほど ΔBIC が小さく
    確率が中間値をとる。BIC のオッカム項は離散的に効くため、素朴な対数一様サンプルでは境界を
    ほぼ外してしまい極端な値に偏る — §12-5 のベンチ要件を満たすための工夫)。
    """
    lo, hi = math.log(0.02), math.log(4.0)
    kwargs = dict(
        a_main=a_main, a_minor=a_minor, noise=noise, main_pattern=main_pattern,
        start_main=start_main, start_minor=start_minor, backend=backend,
    )
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        p_mid = _true_prob_for_minor_frac(math.exp(mid), **kwargs)
        if p_mid < 0.5:
            lo = mid
        else:
            hi = mid
    return math.exp(0.5 * (lo + hi))


# 決定境界からの対数オフセットの標準偏差。遷移帯が急峻 (相対 4〜8% のずれで確率が 0.5→0.9 に
# 達する) なため小さめに取り、境界近傍 (僅差競合・中間確率) と遠方 (明確な正解/不正解) の両方が
# 自然に混ざるようにする (実測: sigma=0.035 で予測確率が概ね 0.5〜1.0 全域に分布する)。
_BOUNDARY_LOG_OFFSET_SIGMA = 0.035

# 問題のうち nested (Laplace) 自身の決定境界を中心にサンプリングする割合。nested の遷移帯は bic の
# それよりずっと急峻・かつ位置が異なるため (Laplace の Occam 罰則は BIC の n_params·ln(n_obs) より
# 弱く効くため副相をより少量でも信じやすい)、bic 境界だけでは nested 系列がほぼ確率 1.0 の 1 ビンに
# 縮退してしまう。全問題を nested 境界にすると逆に bic 系列が縮退する (nested が僅差でも bic は
# 確信している領域) ため、少数派 (実測で調整した既定 30%) だけ nested 境界を使う。
_NESTED_BOUNDARY_FRACTION = 0.3


def generate_problem(rng: np.random.Generator, idx: int, *, backend: SimulatedBackend) -> Problem:
    """真の主相+副相パターンと、真仮説/偽仮説群を決定論的に合成する。

    副相 scale (難易度) は、各問題の決定境界 (予測確率=0.5 となる minor_frac, 二分探索で特定)
    からの対数正規オフセットで選ぶ。境界を直接ねらうのは中立的な基準点探索であり正解を強制しない —
    オフセットの符号次第で真仮説が勝つことも負けることも自然に起こるため、reliability diagram に
    必要な「予測確率 vs 実際の正解率」の非自明な変動が得られる (§12-5)。

    bic の決定境界と nested (Laplace) の決定境界は一致しない (Laplace の Occam 因子は BIC の
    n_params·ln(n_obs) 罰則と異なるスケールで効く)。問題の一部 (``_NESTED_BOUNDARY_FRACTION``) は
    nested 境界を中心にすることで、bic 系列・nested 系列の双方が予測確率 0.5〜1.0 に分布する
    ようにする (bic 境界だけを使うと nested は常に高確信・高正解率の 1 ビンに縮退してしまう)。
    """
    a_main = float(rng.uniform(4.0, 6.0))
    a_minor = a_main * float(rng.uniform(1.35, 1.55))
    noise_frac = float(rng.choice([0.005, 0.01, 0.02]))

    main_phase = _phase(a_main, _SCALE_MAIN, "M")
    main_pattern = backend.simulate((main_phase,), TWO_THETA)
    noise = rng.normal(0.0, noise_frac * float(np.max(main_pattern)), size=main_pattern.shape)

    start_main = a_main * (1.0 + float(rng.uniform(0.0005, 0.0015)))
    start_minor = a_minor * (1.0 + float(rng.uniform(0.0005, 0.0015)))

    boundary_kwargs = dict(
        a_main=a_main, a_minor=a_minor, noise=noise, main_pattern=main_pattern,
        start_main=start_main, start_minor=start_minor, backend=backend,
    )
    use_nested_boundary = bool(rng.random() < _NESTED_BOUNDARY_FRACTION)
    if use_nested_boundary:
        boundary_frac = _locate_nested_boundary(**boundary_kwargs)
    else:
        boundary_frac = _locate_decision_boundary(**boundary_kwargs)
    log_offset = float(rng.normal(0.0, _BOUNDARY_LOG_OFFSET_SIGMA))
    minor_frac = boundary_frac * math.exp(log_offset)
    s_minor = minor_frac * _SCALE_MAIN

    y_clean = main_pattern + backend.simulate((_phase(a_minor, s_minor, "m"),), TWO_THETA)
    intensity = np.clip(y_clean + noise, 0.0, None)

    true_candidate = (
        _phase(start_main, 1.0, "M"),
        _phase(start_minor, s_minor * 0.7, "m"),
    )
    missing_minor_candidate = (_phase(start_main, 1.0, "M"),)

    candidates: list[tuple[PhaseInstance, ...]] = [true_candidate, missing_minor_candidate]
    n_extra = int(rng.integers(0, 3))
    for _ in range(n_extra):
        sign = 1.0 if rng.random() < 0.5 else -1.0
        offset = sign * float(rng.uniform(0.05, 0.15))
        candidates.append((_phase(a_main * (1.0 + offset), 1.0, "M"),))

    return Problem(
        idx=idx,
        intensity=intensity,
        candidates=tuple(candidates),
        correct_id="hyp-0000",
        minor_scale_fraction=minor_frac,
        noise_fraction=noise_frac,
    )


# ---------------------------------------------------------------------------
# nested (Laplace) EvidenceProblem 構成
# ---------------------------------------------------------------------------


def _numeric_hessian(fn, x0: np.ndarray, steps: np.ndarray) -> np.ndarray:
    """``fn`` の ``x0`` における数値 Hessian (中心差分)。"""
    n = x0.size
    h = np.zeros((n, n))
    f0 = fn(x0)
    for i in range(n):
        xp, xm = x0.copy(), x0.copy()
        xp[i] += steps[i]
        xm[i] -= steps[i]
        h[i, i] = (fn(xp) - 2.0 * f0 + fn(xm)) / (steps[i] ** 2)
    for i in range(n):
        for j in range(i + 1, n):
            xpp, xpm, xmp, xmm = x0.copy(), x0.copy(), x0.copy(), x0.copy()
            xpp[i] += steps[i]
            xpp[j] += steps[j]
            xpm[i] += steps[i]
            xpm[j] -= steps[j]
            xmp[i] -= steps[i]
            xmp[j] += steps[j]
            xmm[i] -= steps[i]
            xmm[j] -= steps[j]
            val = (fn(xpp) - fn(xpm) - fn(xmp) + fn(xmm)) / (4.0 * steps[i] * steps[j])
            h[i, j] = h[j, i] = val
    return h


# 相ごとに Laplace の局所パラメータとする 2 属性 (scale + 立方晶格子定数 a、b=c=a で連動)。
# 候補相はすべて立方晶 (a=b=c) として構成されるため、この 2 次元が「その相が存在するか・どの
# 大きさか」を表す実質的な物理自由度になる。StagedRefinementEngine は a/b/c を技術的に独立
# パラメータとして解放するが、真に立方晶な合成データではそれらはほぼ縮退 (強く相関) しており、
# 3 つとも Hessian の次元に含めると縮退方向の固有値が極端に小さくなり Occam 因子 (-0.5*ln|H|)
# が数値的に不安定化する (実測で検証済み)。scale+a の 2 次元に絞ることで安定した局所 Laplace
# 近似になる。
def _phase_theta(phase: PhaseInstance) -> tuple[float, float]:
    return (phase.scale, phase.lattice.a)


def _phase_from_theta(base: PhaseInstance, theta: Sequence[float]) -> PhaseInstance:
    scale, a = theta
    a_clamped = max(float(a), 1e-3)
    return base.with_updates(
        scale=max(float(scale), 1e-8),
        lattice=LatticeParams(a_clamped, a_clamped, a_clamped),
    )


def build_evidence_problem(
    hypothesis: Hypothesis,
    intensity: np.ndarray,
    weights: np.ndarray,
    backend: SimulatedBackend,
) -> EvidenceProblem:
    """精密化済み仮説の (scale, a) [相ごと] を局所パラメータとした ``EvidenceProblem`` を構成する。

    MAP 点 = 精密化で収束した値。尤度は ``-0.5*chi2(theta)``。Hessian は数値中心差分で求め、
    ``LaplaceBackend.score_problem`` の -logZ 近似 (Occam 因子 -0.5*ln|H|) に用いる。
    """
    phases = hypothesis.phases
    n_phases = len(phases)
    x0 = np.array([v for p in phases for v in _phase_theta(p)], dtype=float)
    sqrt_w = np.sqrt(weights)

    def chi2_of(x: np.ndarray) -> float:
        ph = tuple(
            _phase_from_theta(p, x[2 * i : 2 * i + 2]) for i, p in enumerate(phases)
        )
        y_calc = backend.simulate(ph, TWO_THETA)
        r = sqrt_w * (intensity - y_calc)
        return float(r @ r)

    def log_likelihood(theta: np.ndarray) -> float:
        return -0.5 * chi2_of(np.asarray(theta, dtype=float))

    steps = np.maximum(1e-3 * np.abs(x0), 1e-4)
    hessian = 0.5 * _numeric_hessian(chi2_of, x0, steps)
    priors = []
    for i in range(n_phases):
        scale0 = x0[2 * i]
        a0 = x0[2 * i + 1]
        priors.append(
            PriorSpec(param_name=f"phase{i}.scale", kind="uniform", low=0.0,
                      high=max(3.0 * float(scale0), 1.0))
        )
        priors.append(
            PriorSpec(param_name=f"phase{i}.lattice.a", kind="uniform",
                      low=a0 * 0.7, high=a0 * 1.3)
        )
    assert hypothesis.metrics is not None
    return EvidenceProblem(
        metrics=hypothesis.metrics,
        log_likelihood=log_likelihood,
        priors=tuple(priors),
        map_point=x0,
        hessian=hessian,
        label=hypothesis.id,
    )


def _laplace_rearbitrate(
    hypotheses: Sequence[Hypothesis],
    problems: dict[str, EvidenceProblem],
    *,
    close_threshold: float = _CLOSE_THRESHOLD,
) -> tuple[dict[str, float], tuple[str, ...]]:
    """``nested.arbitration.arbitrate`` と同じ 2 段構えを Laplace で再現する。

    bic 一次ランキング (``rank``) で ΔBIC<close_threshold の僅差競合群を抽出し、その仮説のみ
    ``LaplaceBackend.score_problem`` で evidence を差し替える。僅差競合が (best 以外に) 無ければ
    bic 値をそのまま返す (REQ-102/EDGE-003 相当の下段スキップ)。
    """
    primary = rank(hypotheses, BICBackend(), temperature=1.0, close_threshold=close_threshold)
    values: dict[str, float] = {r.hypothesis.id: r.evidence.value for r in primary}
    close_group = [r for r in primary if r.close_competitor]
    if len(close_group) < 2:
        return values, ()

    laplace = LaplaceBackend()
    close_ids = tuple(sorted(r.hypothesis.id for r in close_group))
    for hid in close_ids:
        problem = problems.get(hid)
        if problem is None:
            continue
        values[hid] = laplace.score_problem(problem).value
    return values, close_ids


def _nested_prob_for_minor_frac(
    minor_frac: float,
    *,
    a_main: float,
    a_minor: float,
    noise: np.ndarray,
    main_pattern: np.ndarray,
    start_main: float,
    start_minor: float,
    backend: SimulatedBackend,
) -> float:
    """指定 minor_frac での真仮説の nested (Laplace) 予測確率 (T=1)。minor_frac の単調増加関数。

    ``_true_prob_for_minor_frac`` の nested 版。bic の決定境界と nested の決定境界は一致しない
    (Laplace の Occam 因子は BIC の n_params·ln(n_obs) 罰則と異なるスケールで効くため) — この関数は
    nested 自身の境界を探すのに使う (``_locate_nested_boundary``)。
    """
    s_minor = minor_frac * _SCALE_MAIN
    y_clean = main_pattern + backend.simulate((_phase(a_minor, s_minor, "m"),), TWO_THETA)
    intensity = np.clip(y_clean + noise, 0.0, None)
    true_candidate = (
        _phase(start_main, 1.0, "M"),
        _phase(start_minor, s_minor * 0.7, "m"),
    )
    missing_minor_candidate = (_phase(start_main, 1.0, "M"),)
    result = analyze_single_pattern(
        TWO_THETA, intensity, [true_candidate, missing_minor_candidate], backend=backend
    )
    weights = 1.0 / np.maximum(intensity, 1.0)
    by_id = {r.hypothesis.id: r.hypothesis for r in result.ranked}
    problems = {
        hid: build_evidence_problem(hyp, intensity, weights, backend) for hid, hyp in by_id.items()
    }
    values, _ = _laplace_rearbitrate(list(by_id.values()), problems)
    top_idx, prob = softmax_top1(
        [values["hyp-0000"], values["hyp-0001"]], 1.0
    )
    return prob if top_idx == 0 else 1.0 - prob


def _locate_nested_boundary(
    *,
    a_main: float,
    a_minor: float,
    noise: np.ndarray,
    main_pattern: np.ndarray,
    start_main: float,
    start_minor: float,
    backend: SimulatedBackend,
    iters: int = 8,
) -> float:
    """nested (Laplace) 予測確率がちょうど 0.5 になる minor_frac (nested 自身の決定境界)。

    ``_locate_decision_boundary`` の nested 版。bic の境界とはズレるため、bic 境界だけを中心に
    サンプリングすると nested 系列の予測確率が高確信側 (ほぼ 1.0) に偏ってしまう
    (Laplace は BIC よりオッカム罰則が弱く、bic が僅差でも副相の存在を確信しやすいため)。
    """
    lo, hi = math.log(0.02), math.log(4.0)
    kwargs = dict(
        a_main=a_main, a_minor=a_minor, noise=noise, main_pattern=main_pattern,
        start_main=start_main, start_minor=start_minor, backend=backend,
    )
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        p_mid = _nested_prob_for_minor_frac(math.exp(mid), **kwargs)
        if p_mid < 0.5:
            lo = mid
        else:
            hi = mid
    return math.exp(0.5 * (lo + hi))


# ---------------------------------------------------------------------------
# 問題の評価 (bic 系列 + nested 系列の value 抽出)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProblemOutcome:
    ids: tuple[str, ...]
    bic_values: tuple[float, ...]
    nested_values: tuple[float, ...]
    correct_index: int
    close_ids: tuple[str, ...]


def evaluate_problem(problem: Problem, backend: SimulatedBackend) -> ProblemOutcome:
    result = analyze_single_pattern(
        TWO_THETA, problem.intensity, list(problem.candidates), backend=backend
    )
    ordered_ids = tuple(f"hyp-{i:04d}" for i in range(len(problem.candidates)))
    correct_index = ordered_ids.index(problem.correct_id)

    bic_by_id = {r.hypothesis.id: r.evidence.value for r in result.ranked}
    bic_values = tuple(bic_by_id[hid] for hid in ordered_ids)

    weights = 1.0 / np.maximum(problem.intensity, 1.0)
    hyps_by_id = {r.hypothesis.id: r.hypothesis for r in result.ranked}
    problems_dict = {
        hid: build_evidence_problem(hyps_by_id[hid], problem.intensity, weights, backend)
        for hid in ordered_ids
    }
    nested_by_id, close_ids = _laplace_rearbitrate(list(hyps_by_id.values()), problems_dict)
    nested_values = tuple(nested_by_id[hid] for hid in ordered_ids)

    return ProblemOutcome(
        ids=ordered_ids,
        bic_values=bic_values,
        nested_values=nested_values,
        correct_index=correct_index,
        close_ids=close_ids,
    )


# ---------------------------------------------------------------------------
# 温度較正 (in-sample ECE 最小化) + reliability サンプル構成
# ---------------------------------------------------------------------------


def softmax_top1(values: Sequence[float], temperature: float) -> tuple[int, float]:
    """``rank()`` と同一の softmax(-value/(2T)) から (top1 のインデックス, top1 確率) を返す。"""
    logits = [-v / (2.0 * temperature) for v in values]
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    denom = sum(exps)
    probs = [e / denom for e in exps]
    top_idx = min(range(len(values)), key=lambda i: values[i])
    return top_idx, probs[top_idx]


def _temperature_grid() -> np.ndarray:
    grid = np.concatenate([[1.0], np.geomspace(0.02, 50.0, 400)])
    return np.unique(grid)


def top1_samples(
    series: Sequence[tuple[Sequence[float], int]], *, temperature: float, backend: str
) -> tuple[CalibrationSample, ...]:
    samples = []
    for values, correct_index in series:
        top_idx, prob = softmax_top1(values, temperature)
        samples.append(
            CalibrationSample(
                predicted_probability=prob, correct=(top_idx == correct_index), backend=backend
            )
        )
    return tuple(samples)


def fit_temperature_by_ece(
    series: Sequence[tuple[Sequence[float], int]], *, backend: str, n_bins: int
) -> float:
    """reliability diagram 上の ECE を直接最小化する温度 T を決定論グリッドサーチで求める。

    T=1.0 を探索グリッドに含むため、フィット後の ECE は T=1.0 (較正前) の ECE を超えない
    (in-sample 較正であり、汎化性能の主張ではなく本ベンチの決定論的較正手続きとして採用する)。
    """
    best_t = 1.0
    best_ece = math.inf
    for t in _temperature_grid():
        samples = top1_samples(series, temperature=float(t), backend=backend)
        ece = calibrate_by_backend(samples, n_bins=n_bins)[0].ece
        if ece < best_ece:
            best_ece = ece
            best_t = float(t)
    return best_t


# ---------------------------------------------------------------------------
# ベンチ本体
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BenchResult:
    reports: dict[str, CalibrationReport]
    temperature_bic: float
    temperature_nested: float
    n_problems: int
    n_close_competitor_problems: int
    seed: int
    minor_scale_fractions: tuple[float, ...]


def run_bench(*, n_problems: int = 200, seed: int = 0, n_bins: int = 10) -> BenchResult:
    """較正ベンチ本体。決定論 (同一 seed/n_problems で完全に同じ結果) を保証する。"""
    rng = np.random.default_rng(seed)
    backend = SimulatedBackend(peak_fwhm=0.2)

    problems = [generate_problem(rng, i, backend=backend) for i in range(n_problems)]
    outcomes = [evaluate_problem(p, backend) for p in problems]

    bic_series = [(o.bic_values, o.correct_index) for o in outcomes]
    nested_series = [(o.nested_values, o.correct_index) for o in outcomes]

    t_bic = fit_temperature_by_ece(bic_series, backend="bic", n_bins=n_bins)
    t_nested = fit_temperature_by_ece(nested_series, backend="nested", n_bins=n_bins)

    reports: dict[str, CalibrationReport] = {
        "bic_raw": calibrate_by_backend(
            top1_samples(bic_series, temperature=1.0, backend="bic"), n_bins=n_bins
        )[0],
        "bic_calibrated": calibrate_by_backend(
            top1_samples(bic_series, temperature=t_bic, backend="bic"), n_bins=n_bins
        )[0],
        "nested_raw": calibrate_by_backend(
            top1_samples(nested_series, temperature=1.0, backend="nested"), n_bins=n_bins
        )[0],
        "nested_calibrated": calibrate_by_backend(
            top1_samples(nested_series, temperature=t_nested, backend="nested"), n_bins=n_bins
        )[0],
    }
    n_close = sum(1 for o in outcomes if o.close_ids)

    return BenchResult(
        reports=reports,
        temperature_bic=t_bic,
        temperature_nested=t_nested,
        n_problems=n_problems,
        n_close_competitor_problems=n_close,
        seed=seed,
        minor_scale_fractions=tuple(p.minor_scale_fraction for p in problems),
    )


# ---------------------------------------------------------------------------
# 出力 (CSV + 標準出力サマリ)
# ---------------------------------------------------------------------------


def write_results(result: BenchResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    bins_path = output_dir / "reliability_bins.csv"
    with bins_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["series", "backend", "bin_index", "lower", "upper", "mean_predicted",
             "observed_frequency", "count"]
        )
        for series_name, report in result.reports.items():
            for i, b in enumerate(report.bins):
                writer.writerow(
                    [series_name, report.backend, i, f"{b.lower:.6f}", f"{b.upper:.6f}",
                     f"{b.mean_predicted:.6f}", f"{b.observed_frequency:.6f}", b.count]
                )

    summary_path = output_dir / "summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["series", "backend", "temperature", "ece", "n_samples", "probability_semantics"]
        )
        temperatures = {
            "bic_raw": 1.0,
            "bic_calibrated": result.temperature_bic,
            "nested_raw": 1.0,
            "nested_calibrated": result.temperature_nested,
        }
        for series_name, report in result.reports.items():
            writer.writerow(
                [series_name, report.backend, f"{temperatures[series_name]:.6f}",
                 f"{report.ece:.6f}", report.n_samples, report.probability_semantics]
            )

    meta_path = output_dir / "meta.csv"
    with meta_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["key", "value"])
        writer.writerow(["n_problems", result.n_problems])
        writer.writerow(["seed", result.seed])
        writer.writerow(["n_close_competitor_problems", result.n_close_competitor_problems])
        frac = result.n_close_competitor_problems / max(result.n_problems, 1)
        writer.writerow(["close_competitor_fraction", f"{frac:.4f}"])


def _print_summary(result: BenchResult) -> None:
    print(f"n_problems={result.n_problems} seed={result.seed}")
    print(
        f"close_competitor_problems={result.n_close_competitor_problems} "
        f"({result.n_close_competitor_problems / max(result.n_problems, 1):.1%}) "
        ": nested 系列で Laplace 再評価が実際に発動した問題数"
    )
    print(f"temperature_bic(calibrated)={result.temperature_bic:.4f}")
    print(f"temperature_nested(calibrated)={result.temperature_nested:.4f}")
    print()
    header = f"{'series':<18}{'backend':<10}{'ece':>10}{'n':>6}  probability_semantics"
    print(header)
    print("-" * len(header))
    for name, report in result.reports.items():
        print(
            f"{name:<18}{report.backend:<10}{report.ece:>10.4f}{report.n_samples:>6}  "
            f"{report.probability_semantics}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n-problems", type=int, default=200)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--n-bins", type=int, default=10)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "results",
    )
    args = parser.parse_args()

    result = run_bench(n_problems=args.n_problems, seed=args.seed, n_bins=args.n_bins)
    write_results(result, args.output_dir)
    _print_summary(result)
    print(f"\nCSV: {args.output_dir}")


if __name__ == "__main__":
    main()
