"""生存仮説の joint 検証精密化 (M4 / REQ-013/014/202 / interfaces.py joint/verification 節)。

プライマリ探索 (``SearchResult``) を **不変** の入力とし、その生存仮説 (良好解) のみを
与えられた joint ヒストグラム群で ``refine_joint_detailed`` により検証精密化する。探索段
そのものを joint 化しない (探索は書き換えず・再実行しない, REQ-202)。各生存仮説に
コントラスト駆動の占有率解放推奨 (``recommend_occupancy_release``) も付す。

【生存仮説の取り出し】``SearchResult.good_cluster_ids`` (Jenks 良好解群 / FR-116) を生存仮説
とみなし、``SearchResult.hypotheses`` から当該 ID の ``Hypothesis`` を取り出す。探索段の
オブジェクトは一切書き換えず、``verified`` は joint 検証後 metrics を反映した **新** Hypothesis
インスタンスの tuple を返す (元 SearchResult は不変, P2 / REQ-202)。

【決定論】生存仮説は ID 昇順で処理し、各 joint モデルのヒスト順は入力順を保つ。SimulatedBackend
は乱数を使わないため、同一入力の 2 回実行でビット同一の結果を返す (NFR-102/REQ-402)。

【非破壊記録】``ledger`` 非 None のとき要所を理由付き記録する。探索段の ledger
(``SearchResult.ledger``) には一切追記せず、渡された検証用 ledger にのみ append するため
探索の監査記録は不変で ``verify()`` は True を維持する (NFR-105)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Mapping

from ..backends.base import RefinementBackend, RefinementResult, param_name
from ..evidence.base import EvidenceBackend
from ..model import Hypothesis, RefinementMetrics
from ..search.tree import SearchResult
from ..store.ledger import Ledger
from .contrast import (
    ContrastConfig,
    OccupancyReleaseRecommendation,
    recommend_occupancy_release,
)
from .engine import refine_joint_detailed
from .model import JointHistogram, JointRefinementModel, JointRefinementResult
from .weights import HistogramWeighting


@dataclass(frozen=True)
class JointVerificationResult:
    """生存仮説の joint 検証精密化結果。🔵 REQ-014

    - ``verified``: joint 検証後 metrics を更新した Hypothesis の tuple (ID 昇順)。元
      SearchResult のオブジェクトは変更せず、新インスタンスで返す (P2 / REQ-202)。
    - ``joint_results``: 仮説 ID → ``JointRefinementResult`` (集約 + ヒスト別詳細, REQ-006)。
    - ``recommendations``: 仮説 ID → コントラスト占有率解放推奨 tuple (提案のみ, REQ-011)。
    - ``warnings``: 生存仮説ゼロ等の縮退警告。
    """

    verified: tuple[Hypothesis, ...]
    joint_results: Mapping[str, JointRefinementResult]
    recommendations: Mapping[str, tuple[OccupancyReleaseRecommendation, ...]]
    warnings: tuple[str, ...] = ()


def _metrics_from_aggregate(
    aggregate: RefinementResult,
    evidence: EvidenceBackend | None,
    prior: RefinementMetrics | None,
) -> RefinementMetrics:
    """joint 集約 ``RefinementResult`` から検証後 ``RefinementMetrics`` を構成する。

    gof は tree.py / staged.py と同式 ``sqrt(chi2 / max(n_obs - n_params, 1))``。evidence 非
    None なら集約 metrics を再評価して evidence を差し替え、None なら探索段の evidence を保持する
    (rank 経路互換, D1)。
    """
    chi2 = float(aggregate.chi2)
    n_obs = int(aggregate.n_obs)
    n_params = int(aggregate.n_params)
    if math.isfinite(chi2):
        gof = math.sqrt(chi2 / max(n_obs - n_params, 1))
    else:
        gof = float("inf")
    base = RefinementMetrics(
        rwp=float(aggregate.rwp),
        gof=gof,
        chi2=chi2,
        n_obs=n_obs,
        n_params=n_params,
        evidence=dict(prior.evidence) if prior is not None else {},
    )
    if evidence is not None:
        ev = evidence.score(base)
        return replace(base, evidence={ev.backend: ev.value})
    return base


def verify_survivors(
    backend: RefinementBackend,
    search_result: SearchResult,
    histograms: tuple[JointHistogram, ...],
    *,
    evidence: EvidenceBackend | None = None,
    weighting: HistogramWeighting = HistogramWeighting(),
    contrast: ContrastConfig = ContrastConfig(),
    ledger: Ledger | None = None,
) -> JointVerificationResult:
    """探索の生存仮説のみを joint 検証精密化する。探索段は書き換えない。🔵 REQ-013/014/202

    【FR-245】プライマリ探索 (``SearchResult``) は不変。生存仮説 (良好解=``good_cluster_ids``)
      を与えられた ``histograms`` で ``JointRefinementModel`` に組み、``refine_joint_detailed``
      で検証精密化し、``recommend_occupancy_release`` でコントラスト推奨も付す。探索を joint 化
      しない・再実行しない (REQ-202)。
    【生存仮説の取り出し】``good_cluster_ids`` を ID 昇順で処理し、``hypotheses`` から取り出す。
      未知 ID (通常あり得ない) はスキップする。
    【共有 free】各生存仮説の全相 scale + 格子 a/b/c を共有 free として解放する (検証精密化)。
      per-histogram free は空 (ヒスト独立 scale は共有相 scale に相乗り, 検証段の簡易化)。
    【非破壊】``verified`` は metrics を差し替えた **新** Hypothesis (id/parent_id/status/phases
      は保持)。元 SearchResult のオブジェクトは一切変更しない (P2)。
    【決定論】生存仮説 ID 昇順・ヒスト入力順固定で 2 回実行ビット同一 (NFR-102/REQ-402)。
    【記録】``ledger`` 非 None のとき要所を append する。探索段の ledger には追記しないため
      探索の ``verify()`` は不変で True を維持する (NFR-105)。
    """
    # 【生存仮説の取り出し】good_cluster_ids (良好解) を ID 昇順で確定する (決定論) 🔵 FR-116
    survivor_ids = tuple(
        sorted(sid for sid in search_result.good_cluster_ids if sid in search_result.hypotheses)
    )

    if ledger is not None:
        ledger.append(
            "verify_survivors_start",
            {
                "n_survivors": len(survivor_ids),
                "survivor_ids": list(survivor_ids),
                "n_histograms": len(histograms),
            },
        )

    verified: list[Hypothesis] = []
    joint_results: dict[str, JointRefinementResult] = {}
    recommendations: dict[str, tuple[OccupancyReleaseRecommendation, ...]] = {}
    warnings: list[str] = []

    if not survivor_ids:
        warnings.append(
            "生存仮説 (良好解) が空のため joint 検証をスキップしました。"
        )

    for sid in survivor_ids:
        # 【探索段オブジェクトの読み取り (書き換えない)】元 Hypothesis から phases を取る 🔵 REQ-202
        original = search_result.hypotheses[sid]
        phases = original.phases

        # 【検証 joint モデル】: 与えられた histograms で共有構造 (全相 scale+格子) を解放する 🔵
        shared_free = frozenset(
            param_name(pos, key)
            for pos in range(len(phases))
            for key in ("scale", "lattice.a", "lattice.b", "lattice.c")
        )
        model = JointRefinementModel(
            phases=phases,
            histograms=histograms,
            shared_free_params=shared_free,
        )

        # 【検証精密化】: 生存仮説のみ refine_joint_detailed に渡す (探索は再実行しない) 🔵 REQ-014
        joint_res = refine_joint_detailed(
            backend, model, weighting=weighting, ledger=ledger
        )
        joint_results[sid] = joint_res

        # 【コントラスト推奨】: 占有率解放を提案する (自動適用しない) 🔵 REQ-011
        recs = recommend_occupancy_release(
            phases, model, config=contrast, ledger=ledger
        )
        recommendations[sid] = recs

        # 【非破壊反映】: metrics を joint 集約で更新した新 Hypothesis を作る (元は不変) 🔵 REQ-202
        new_metrics = _metrics_from_aggregate(
            joint_res.aggregate, evidence, original.metrics
        )
        verified.append(replace(original, metrics=new_metrics))

        if ledger is not None:
            ledger.append(
                "verify_survivor",
                {
                    "id": sid,
                    "rwp": float(joint_res.aggregate.rwp),
                    "chi2": float(joint_res.aggregate.chi2),
                    "n_recommendations": len(recs),
                },
            )

    return JointVerificationResult(
        verified=tuple(verified),
        joint_results=joint_results,
        recommendations=recommendations,
        warnings=tuple(warnings),
    )
