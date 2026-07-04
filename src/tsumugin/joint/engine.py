"""joint 精密化エンジン (REQ-005/006/007 / interfaces.py joint/engine 節)。

``refine_joint`` は複数ヒストグラムを 1 つの共有構造で精密化し、集約 ``RefinementResult``
(rank/evidence 経路と互換, D1) を返す。``refine_joint_detailed`` はヒスト別
``PerHistogramMetrics`` を付した ``JointRefinementResult`` を返す。

【SimulatedBackend 経路】各ヒストを ``backend.refine`` でヒスト独立 free 解放して精密化し
χ² を得る。共有構造 (``shared_free_params``) は χ² 和で更新する簡易ブロック座標降下 (D2):
1 サイクル内で各ヒストを順に精密化し、更新された共有相 phases を次ヒストへ伝播する。
共有構造がビット同一で安定した時点で収束とみなす (max_cycles で打ち切り)。

【失敗の非例外化】1 ヒストの refine 失敗 (例外 or chi2=inf) を捕捉して当該ヒスト chi2=inf
に変換し、集約 chi2=inf へ伝播、warnings に失敗ヒスト index を明示する (EDGE-001/REQ-007)。
joint 全体は例外を投げない (staged.py の chi2=inf 非例外化の流儀を踏襲)。

【決定論】ヒスト順 (入力順=index 昇順)・パラメータ順を固定し、2 回実行でビット同一
(NFR-102)。SimulatedBackend は乱数を使わず、weighting.resolve も入力順タプルを返す。

【GSASIIBackend 経路】v1 は SimulatedBackend と同一のヒスト独立 refine → χ² 合算経路で
起動する接続点 (@gsas smoke)。GSAS-II ネイティブのマルチヒストグラム 1-gpx 精密化への
本格接続は後続タスク (TC-409-02) で扱う。
"""

from __future__ import annotations

import math

import numpy as np

from ..backends.base import (
    RefinementBackend,
    RefinementModel,
    RefinementResult,
)
from ..model import PhaseInstance
from ..store.ledger import Ledger
from .model import (
    JointHistogram,
    JointRefinementModel,
    JointRefinementResult,
    PerHistogramMetrics,
)
from .weights import HistogramWeighting


def _histogram_free(model: JointRefinementModel, hist_index: int) -> frozenset[str]:
    """ヒスト ``hist_index`` の実効 free_params (共有 + ヒスト独立)。

    共有構造 free とヒスト独立 free (scale/bg/profile) を合わせて 1 ヒストの
    ``RefinementModel.free_params`` とする。決定論のため frozenset を返す。
    """
    per = model.per_histogram_free_params.get(hist_index, frozenset())
    return model.shared_free_params | per


def _extract_scale(result: RefinementResult) -> float:
    """精密化後の相 0 の scale をヒスト独立 scale として取り出す。

    共有相 phases の先頭 (相 0) の scale を採用する。失敗 (phases 空) 時は 1.0。
    """
    if result.phases:
        return float(result.phases[0].scale)
    return 1.0


def _is_failure(result: RefinementResult) -> bool:
    """当該ヒスト結果が失敗 (chi2 非有限) か。"""
    return not math.isfinite(result.chi2)


def _refine_one(
    backend: RefinementBackend,
    phases: tuple[PhaseInstance, ...],
    hist: JointHistogram,
    free: frozenset[str],
    *,
    max_cycles: int,
) -> RefinementResult:
    """1 ヒストを精密化する。例外は chi2=inf 結果へ変換する (非例外化, EDGE-001)。

    staged.py / gsasii.py の「失敗は例外でなく chi2=inf の結果に変換」する流儀を踏襲し、
    バックエンド例外を捕捉して発散結果へ落とす。ガードは呼び出し側 (_is_failure) が担う。
    """
    n_obs = int(np.asarray(hist.intensity).size)
    model = RefinementModel(
        phases=phases,
        free_params=free,
        two_theta=hist.two_theta,
        intensity=hist.intensity,
        weights=hist.weights,
    )
    try:
        return backend.refine(model, max_cycles=max_cycles)
    except Exception:
        return RefinementResult(
            phases=phases,
            chi2=float("inf"),
            rwp=float("inf"),
            n_obs=n_obs,
            n_params=0,
            converged=False,
            n_cycles=max_cycles,
            free_params=free,
        )


def _combined_rwp(
    per_results: tuple[RefinementResult, ...],
    weights: tuple[float, ...],
) -> float:
    """重み付き結合 Rwp を各ヒストの Rwp から再構成する。

    各ヒスト Rwp[%] は Rwp² ∝ (重み付き残差二乗和) / (重み付き Yobs 二乗和) を表す。
    結合 Rwp は分子・分母をヒスト重みで加重合算した比の平方根とする:
      Rwp_joint = 100·sqrt(Σ w_k·num_k / Σ w_k·den_k)。
    ここでは den_k を n_obs_k で代理 (合成データでは Rwp のみを保持) せず、Rwp を
    そのまま二乗平均する簡易結合 (den 一様仮定) を採る。失敗ヒストがあれば inf。
    決定論: ヒスト順 (入力順) で合算する (NFR-102)。
    """
    num = 0.0
    den = 0.0
    for res, w in zip(per_results, weights):
        if not math.isfinite(res.rwp):
            return float("inf")
        num += w * (res.rwp ** 2)
        den += w
    if den <= 0:
        return 0.0
    return math.sqrt(num / den)


def _run_joint(
    backend: RefinementBackend,
    model: JointRefinementModel,
    weighting: HistogramWeighting,
    max_cycles: int,
    ledger: Ledger | None,
) -> tuple[
    tuple[PhaseInstance, ...],
    tuple[RefinementResult, ...],
    tuple[float, ...],
    tuple[int, ...],
]:
    """簡易ブロック座標降下で joint 精密化を回す共通コア (D2)。

    共有構造を χ² 和で更新する: 1 サイクルで各ヒストを入力順に精密化し、更新された
    共有相 phases を次サイクルへ持ち越す。共有相がビット同一で安定したら収束打ち切り。
    失敗ヒストは chi2=inf のまま伝播し、当該ヒストでは共有相を更新しない。

    :returns: (最終共有相, 各ヒスト最終結果 (入力順), 実効重み, 失敗ヒスト index 列)
    """
    weights = weighting.resolve(model)
    n_hist = len(model.histograms)
    phases = model.phases

    per_results: list[RefinementResult] = [None] * n_hist  # type: ignore[list-item]

    if ledger is not None:
        ledger.append(
            "joint_refine_start",
            {
                "n_hist": n_hist,
                "weights": list(weights),
                "shared_free": sorted(model.shared_free_params),
            },
        )

    for cycle in range(1, max_cycles + 1):
        prev_phases = phases
        for k in range(n_hist):
            hist = model.histograms[k]
            free = _histogram_free(model, k)
            res = _refine_one(backend, phases, hist, free, max_cycles=max_cycles)
            per_results[k] = res
            # 共有相の χ² 和更新: 成功ヒストのみ更新結果を次へ伝播する (失敗ヒストは据え置き)。
            if not _is_failure(res):
                phases = res.phases
            if ledger is not None:
                ledger.append(
                    "joint_hist_refine",
                    {
                        "cycle": cycle,
                        "hist_index": k,
                        "probe": hist.probe,
                        "chi2": res.chi2,
                        "rwp": res.rwp,
                        "free": sorted(free),
                    },
                )
        # 収束判定: 共有相がビット同一で安定したら打ち切り (決定論)。
        if _phases_identical(prev_phases, phases):
            break

    failed = tuple(k for k in range(n_hist) if _is_failure(per_results[k]))
    return phases, tuple(per_results), weights, failed


def _phases_identical(
    a: tuple[PhaseInstance, ...], b: tuple[PhaseInstance, ...]
) -> bool:
    """共有相列がビット同一か (scale/lattice/占有率)。収束打ち切り判定用。"""
    if len(a) != len(b):
        return False
    for pa, pb in zip(a, b):
        if pa.scale != pb.scale:
            return False
        la, lb = pa.lattice, pb.lattice
        if (la.a, la.b, la.c, la.alpha, la.beta, la.gamma) != (
            lb.a,
            lb.b,
            lb.c,
            lb.alpha,
            lb.beta,
            lb.gamma,
        ):
            return False
        if dict(pa.occupancies) != dict(pb.occupancies):
            return False
    return True


def _build_aggregate(
    phases: tuple[PhaseInstance, ...],
    per_results: tuple[RefinementResult, ...],
    weights: tuple[float, ...],
    failed: tuple[int, ...],
) -> RefinementResult:
    """ヒスト別結果を単一集約 RefinementResult へまとめる (D1 / REQ-006)。

    - chi2 = Σ (w_k · chi2_k)。失敗ヒストがあれば inf へ伝播。
    - rwp  = 重み付き結合 Rwp。

    【chi2 規約 (F12)】: 集約 chi2 = Σ(w_k·chi2_k) は GSAS 慣行 (ヒスト重み hist_weight を chi2 に
    加重) に従う。一方 rwp は各ヒスト Rwp を分母正規化した比として結合する (重みで加重した比)。
    hist_weight は chi2 側に効き、rwp は分母正規化で吸収されるため二者の役割は分離している。
    **同一 weighting 下では** 全仮説が同じ w_k を共有するため、BIC = chi2 + k·ln(n) の比較は
    chi2 の順序を保存し、weighting に対して決定論・一貫である (BIC 比較の一貫性)。
    - phases = 共有構造 (±σ はバックエンドが phases に持たせた LatticeParams.sigma を保持)。
    - globals = "hist{k}.rwp"/"hist{k}.scale"/"hist{k}.chi2" (ヒスト別値, REQ-006)。
    - warnings = 失敗ヒスト index を明示 (EDGE-001)。

    【0 ヒストグラム (F11)】: histograms 空 (n_hist==0) は精密化対象が無く、chi2=0/converged=True
    の「沈黙成功」は誤り。chi2=inf + warning + converged=False の非成功結果へ落とし、ガードレール
    (chi2 非有限を失敗として扱う下流) に処理させる (staged.py の chi2=inf 非例外化と整合)。
    """
    # 【0 ヒストグラム防御 (F11)】: 対象無しは成功でなく非成功 (chi2=inf) として扱う 🔵
    if not per_results:
        return RefinementResult(
            phases=phases,
            chi2=float("inf"),
            rwp=float("inf"),
            n_obs=0,
            n_params=0,
            converged=False,
            n_cycles=1,
            free_params=frozenset(),
            globals={},
            warnings=("joint: histograms が空 (n_hist=0)。精密化対象が無く chi2=inf へ落とす",),
        )

    any_failed = bool(failed)
    if any_failed:
        chi2 = float("inf")
    else:
        chi2 = float(sum(w * res.chi2 for res, w in zip(per_results, weights)))
    rwp = _combined_rwp(per_results, weights)

    n_obs = sum(res.n_obs for res in per_results)
    n_params = sum(res.n_params for res in per_results)
    converged = all(res.converged for res in per_results) and not any_failed
    n_cycles = max((res.n_cycles for res in per_results), default=1)

    globals_out: dict[str, float] = {}
    for k, res in enumerate(per_results):
        globals_out[f"hist{k}.rwp"] = float(res.rwp)
        globals_out[f"hist{k}.scale"] = _extract_scale(res)
        globals_out[f"hist{k}.chi2"] = float(res.chi2)

    warnings_out: list[str] = []
    for k in failed:
        warnings_out.append(
            f"hist{k}: 精密化失敗 (chi2=inf へ変換, joint 全体は継続 EDGE-001)"
        )

    free_out: frozenset[str] = frozenset()
    for res in per_results:
        free_out = free_out | res.free_params

    return RefinementResult(
        phases=phases,
        chi2=chi2,
        rwp=rwp,
        n_obs=n_obs,
        n_params=n_params,
        converged=converged,
        n_cycles=n_cycles,
        free_params=free_out,
        globals=globals_out,
        warnings=tuple(warnings_out),
    )


def refine_joint(
    backend: RefinementBackend,
    model: JointRefinementModel,
    *,
    weighting: HistogramWeighting = HistogramWeighting(),
    max_cycles: int = 20,
    ledger: Ledger | None = None,
) -> RefinementResult:
    """joint 精密化を実行し集約 ``RefinementResult`` を返す。🔵 REQ-005/006/FR-242

    【SimulatedBackend / GSASIIBackend】各ヒストを ``backend.refine`` (ヒスト独立 free) で
    精密化して χ² を得、共有構造を χ² 和で更新する簡易ブロック座標降下 (D2)。集約 chi2=Σχ²、
    rwp=結合 Rwp、共有構造 phases (±σ) を単一 RefinementResult へ集約する。
    【失敗の非例外化】1 ヒスト失敗は chi2=inf へ変換し集約 chi2=inf へ伝播、warnings に
    失敗ヒスト index を明示する (例外化しない, EDGE-001/REQ-007)。
    【決定論】ヒスト順・パラメータ順固定で 2 回実行ビット同一 (NFR-102)。
    """
    phases, per_results, weights, failed = _run_joint(
        backend, model, weighting, max_cycles, ledger
    )
    aggregate = _build_aggregate(phases, per_results, weights, failed)
    if ledger is not None:
        ledger.append(
            "joint_refine_result",
            {"chi2": aggregate.chi2, "rwp": aggregate.rwp, "failed": list(failed)},
        )
    return aggregate


def refine_joint_detailed(
    backend: RefinementBackend,
    model: JointRefinementModel,
    *,
    weighting: HistogramWeighting = HistogramWeighting(),
    max_cycles: int = 20,
    ledger: Ledger | None = None,
) -> JointRefinementResult:
    """``refine_joint`` のヒスト別詳細付きラッパ。🔵 REQ-006/009

    集約 RefinementResult に加え、各ヒストの ``PerHistogramMetrics``
    (hist_index/probe/rwp/chi2/scale/sigma_source) を入力順 tuple で返す。σ 由来は
    ``weighting.sigma_source`` から取り、warnings に σ 由来 / 失敗ヒストを明示する。
    """
    phases, per_results, weights, failed = _run_joint(
        backend, model, weighting, max_cycles, ledger
    )
    aggregate = _build_aggregate(phases, per_results, weights, failed)

    per_metrics: list[PerHistogramMetrics] = []
    sigma_warnings: list[str] = []
    for k, res in enumerate(per_results):
        hist = model.histograms[k]
        sigma_source = weighting.sigma_source(k)
        per_metrics.append(
            PerHistogramMetrics(
                hist_index=k,
                probe=hist.probe,
                rwp=float(res.rwp),
                chi2=float(res.chi2),
                scale=_extract_scale(res),
                sigma_source=sigma_source,
            )
        )
        if sigma_source == "hist_weight":
            sigma_warnings.append(f"hist{k}: σ 由来=hist_weight (経験重み上書き, NFR-107)")

    warnings_out = aggregate.warnings + tuple(sigma_warnings)

    if ledger is not None:
        ledger.append(
            "joint_refine_detailed",
            {
                "chi2": aggregate.chi2,
                "per_histogram": [
                    {"hist_index": m.hist_index, "chi2": m.chi2, "rwp": m.rwp}
                    for m in per_metrics
                ],
            },
        )

    return JointRefinementResult(
        aggregate=aggregate,
        per_histogram=tuple(per_metrics),
        warnings=warnings_out,
    )
