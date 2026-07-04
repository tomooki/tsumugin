"""階層的裁定 (2 段構え): 木探索 bic 固定 + 僅差競合のみ nested 再裁定。REQ-010〜013/102/201/EDGE-003。

D4 の実装。まず ``evidence.ranking.rank`` (BICBackend) で一次順位・確率・close_competitor を得る
(木探索/枝刈りは bic のまま・nested で書き換えない, REQ-010/201)。次に close_competitor=True
(ΔBIC<close_threshold) の群のみを nested 再裁定対象とし (full_nested=True なら全生存仮説, REQ-012/
EDGE-004)、対象仮説の ``EvidenceProblem`` を ``nested.run_with_fallback`` にかけて value=-logZ を得て
evidence を差し替え、統合ランキングを再構成する (確率再計算)。

僅差競合が無い / problems・nested 未供給なら nested を発動せず bic 一次を最終結果とする
(2 段構えの下段スキップ, REQ-102/EDGE-003)。どの仮説を bic 一次で確定し、どの競合を nested で再裁定
したかを理由付きで ledger に追記する (REQ-013/NFR-105)。

**human モード非破壊 (REQ-203/D10)**: arbitrate は **評価のみ** で、仮説を accepted 化しない。
``ArbitrationResult`` は推奨提示に留まる型で、既存 ``FinalSelectionEngine`` の人間操作経路を新設しない。

**確率再計算 (統合ランキング)**: 既存 ``rank`` と同一の softmax(-value/(2T)) を用いる。nested で evidence
を差し替えた後、対象+非対象を合わせた全仮説の (差し替え後) value で再ソートし確率を再計算する。差し替えは
**hypothesis.id → EvidenceResult** の写像で行い ``_rerank_with_replaced`` が ``rank`` と同一式で確率を
再計算する (異なる仮説が同一 RefinementMetrics オブジェクトを共有しても写像が衝突しない)。

**決定論 (NFR-102/REQ-402)**: nested 再裁定は仮説 ID 昇順で処理し、``nested_ids`` は昇順で返す。

コア依存は numpy のみ (実サンプラ非依存。未導入環境では run_with_fallback が Laplace 代替へ縮退する)。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

from ..evidence.base import EvidenceResult
from ..evidence.ic import BICBackend
from ..evidence.ranking import RankedHypothesis, rank
from ..model import Hypothesis
from ..store.ledger import Ledger
from .base import EvidenceProblem
from .sampler import NestedBackend


@dataclass(frozen=True)
class ArbitrationConfig:
    """階層的裁定の設定 (2 段構え / フル nested)。REQ-011/012/014。

    既定は 2 段構え (bic 一次 + close_competitor 群のみ nested 再裁定)。``full_nested=True`` で全生存
    仮説を nested 裁定する (REQ-012/EDGE-004)。``close_threshold`` は既存 ``rank`` と同一既定
    (ΔBIC < 10)、``temperature`` も ``rank`` と共有する (softmax 温度較正)。
    """

    full_nested: bool = False  # 【全生存仮説を nested 裁定 (既定は 2 段構え)】 REQ-012
    close_threshold: float = 10.0  # 【僅差競合閾値 ΔBIC (rank と共有)】 REQ-011
    temperature: float = 1.0  # 【softmax 温度較正 (rank と共有)】 REQ-014


@dataclass(frozen=True)
class ArbitratedHypothesis:
    """階層的裁定後の 1 仮説 (裁定に用いた evidence backend を明示)。REQ-013/015。

    ``RankedHypothesis`` を包み、bic 一次確定か nested 再裁定 (打ち切り時は laplace 代替) かを
    ``adjudicated_by`` で示す (レポート明示)。``logz_err`` は nested の logZ 誤差 (bic 一次は None)。
    """

    ranked: RankedHypothesis  # 【裁定後の順位・確率・evidence】
    adjudicated_by: Literal["bic", "nested", "laplace"]  # 【裁定に用いた backend (REQ-015)】
    logz_err: float | None = None  # 【nested の logZ 誤差 (bic 一次は None)】 REQ-006


@dataclass(frozen=True)
class ArbitrationResult:
    """階層的裁定の統合結果。REQ-010〜013。

    bic 一次で確定した仮説と nested 再裁定した競合群を統合した最終ランキング (evidence 昇順)。
    どの仮説をどの backend で裁定したかを型付きで保持し、確率較正・レポート・OED 発動へ渡す。
    """

    arbitrated: tuple[ArbitratedHypothesis, ...]  # 【統合ランキング (evidence 昇順)】
    nested_ids: tuple[str, ...]  # 【nested 再裁定した仮説 ID (決定論・昇順)】 REQ-013/402
    primary_backend: str = "bic"  # 【一次探索/裁定の backend 名 (REQ-015)】
    warnings: tuple[str, ...] = ()  # 【打ち切り等の警告伝播】 REQ-101


def _rerank_with_replaced(
    hypotheses: Sequence[Hypothesis],
    results_by_hypothesis_id: Mapping[str, EvidenceResult],
    *,
    temperature: float,
    close_threshold: float,
) -> tuple[RankedHypothesis, ...]:
    """hypothesis.id → 差し替え後 EvidenceResult の写像で統合ランキングを再構成する。

    確率式は既存 ``evidence.ranking.rank`` と厳密に一致させる (softmax(-value/(2T))・max 減算安定化・
    close_competitor は best との差 < close_threshold)。``rank`` が ``score(metrics)`` 経由で
    metrics オブジェクトをキーにするのと異なり、hypothesis.id を直接キーにするため、異なる仮説が
    同一 ``RefinementMetrics`` オブジェクトを共有しても写像が衝突しない (LOW-7)。決定論維持。
    """
    scored: list[tuple[Hypothesis, EvidenceResult]] = [
        (h, results_by_hypothesis_id[h.id]) for h in hypotheses
    ]
    scored.sort(key=lambda pair: pair[1].value)
    best_value = scored[0][1].value

    logits = [-(res.value) / (2.0 * temperature) for _, res in scored]
    m = max(logits)
    exps = [math.exp(x - m) for x in logits]
    denom = sum(exps)
    probs = [e / denom for e in exps]

    ranked: list[RankedHypothesis] = []
    for (h, res), p in zip(scored, probs):
        close = (res.value - best_value) < close_threshold
        ranked.append(
            RankedHypothesis(
                hypothesis=h, evidence=res, probability=p, close_competitor=close
            )
        )
    return tuple(ranked)


def arbitrate(
    hypotheses: Sequence[Hypothesis],
    *,
    problems: Mapping[str, EvidenceProblem] | None = None,
    nested: NestedBackend | None = None,
    config: ArbitrationConfig = ArbitrationConfig(),
    ledger: Ledger | None = None,
) -> ArbitrationResult:
    """木探索を bic のまま維持し、僅差競合のみ nested で再裁定する 2 段構え裁定。REQ-010〜013/102/201。

    【一次 (REQ-010/201)】: まず ``rank`` (BICBackend) で順位・確率・close_competitor を得る。木探索/
      枝刈りは bic のまま・nested で書き換えない (探索段は不変)。
    【再裁定対象抽出 (REQ-011)】: close_competitor=True (ΔBIC<close_threshold) の群のみを nested 対象と
      する。full_nested=True なら全生存仮説を対象にする (REQ-012/EDGE-004)。
    【nested 再裁定】: 対象仮説 ID の ``EvidenceProblem`` を problems から引き、``run_with_fallback`` で
      value=-logZ を得て evidence を差し替え、統合ランキングを再構成 (確率再計算) する。未導入環境では
      run_with_fallback が Laplace 代替へ縮退し (truncated=True), adjudicated_by="laplace"、警告を伝播。
    【僅差なし (REQ-102/EDGE-003)】: close_competitor が無い / problems・nested 未供給なら nested を発動
      せず bic 一次を最終結果とする (下段スキップ, 全 adjudicated_by="bic")。
    【記録 (REQ-013)】: どの仮説を bic 一次で確定し、どの競合を nested で再裁定したかを理由付きで
      ``ledger.append("arbitration", {...})`` に記録する (NFR-105)。決定論: 仮説 ID 昇順で処理 (REQ-402)。
    【非破壊 (REQ-203/D10)】: 評価のみで仮説を accepted 化しない。ArbitrationResult は推奨提示に留まる。
    """
    # 【空入力】: 何も裁定しない。ledger 記録も行わない (状態変更なし)。
    if not hypotheses:
        return ArbitrationResult(arbitrated=(), nested_ids=(), primary_backend="bic")

    # 【一次 bic (REQ-010/201)】: rank で順位・確率・close_competitor を得る (木探索は bic 固定)。
    primary = rank(
        hypotheses,
        BICBackend(),
        temperature=config.temperature,
        close_threshold=config.close_threshold,
    )

    # 【再裁定対象抽出 (REQ-011/012/EDGE-004)】: full_nested なら全生存仮説、既定は close_competitor 群。
    #   決定論のため対象仮説 ID は昇順で処理する (REQ-402)。
    if config.full_nested:
        candidate_ids = sorted(r.hypothesis.id for r in primary)
        # full_nested は 1 仮説でも全生存仮説を nested 裁定する。
        genuine_competition = bool(candidate_ids)
    else:
        close_group = [r for r in primary if r.close_competitor]
        candidate_ids = sorted(r.hypothesis.id for r in close_group)
        # 【僅差競合の成立 (REQ-102/EDGE-003)】: best は常に自分自身と close になるため、
        #   競合が「有る」と言えるのは best 以外にも close な仮説が居るとき (>=2 件) のみ。
        #   1 件 (best のみ) は僅差競合なし扱いにして下段をスキップする。
        genuine_competition = len(close_group) >= 2

    # 【僅差なし / 供給欠如 (REQ-102/EDGE-003)】: nested を発動できない場合は bic 一次を最終結果とする。
    nested_active = (
        genuine_competition and problems is not None and nested is not None
    )
    if not nested_active:
        return _finalize_primary(primary, ledger=ledger, reason="no_nested")

    assert problems is not None and nested is not None  # nested_active が保証

    # 【nested 再裁定】: 対象 ID 昇順で run_with_fallback を回し evidence を差し替える。
    #   problem が欠損している対象はスキップ (bic のまま)。
    replaced: dict[str, EvidenceResult] = {}
    logz_err_by_id: dict[str, float | None] = {}
    adjudicated_by: dict[str, Literal["bic", "nested", "laplace"]] = {}
    warnings: list[str] = []
    nested_ids: list[str] = []

    for hid in candidate_ids:
        problem = problems.get(hid)
        if problem is None:
            # 【欠損 (供給不足)】: problem が無い対象は nested 再裁定できず bic のまま残す。
            continue
        outcome = nested.run_with_fallback(problem, ledger=ledger)
        replaced[hid] = outcome.result
        logz_err_by_id[hid] = outcome.result.logz_err
        # 【縮退 (truncated)】: Laplace 代替なら laplace、成功なら nested として明示する (REQ-015)。
        adjudicated_by[hid] = "laplace" if outcome.truncated else "nested"
        warnings.extend(outcome.warnings)
        nested_ids.append(hid)

    # 【全 target が problem 欠損】: 実質再裁定なし → bic 一次を最終結果とする (下段スキップ相当)。
    if not nested_ids:
        return _finalize_primary(primary, ledger=ledger, reason="no_nested_problem")

    # 【統合ランキング再構成 (確率再計算)】: 対象は差し替え後 evidence、非対象は bic の evidence を用い、
    #   全仮説を差し替え後 value で再ソート + softmax 再計算する (rank と同一式で一貫させる)。
    #   キーは hypothesis.id (metrics オブジェクト共有時の写像衝突を避ける, LOW-7)。
    results_by_hypothesis_id: dict[str, EvidenceResult] = {}
    for r in primary:
        hid = r.hypothesis.id
        results_by_hypothesis_id[hid] = replaced.get(hid, r.evidence)

    reranked = _rerank_with_replaced(
        hypotheses,
        results_by_hypothesis_id,
        temperature=config.temperature,
        close_threshold=config.close_threshold,
    )

    arbitrated = tuple(
        ArbitratedHypothesis(
            ranked=r,
            adjudicated_by=adjudicated_by.get(r.hypothesis.id, "bic"),
            logz_err=logz_err_by_id.get(r.hypothesis.id),
        )
        for r in reranked
    )
    nested_ids_tuple = tuple(sorted(nested_ids))

    # 【記録 (REQ-013/NFR-105)】: bic 一次確定 ID と nested 再裁定 ID を理由付きで追記する。
    if ledger is not None:
        primary_ids = tuple(
            sorted(
                a.ranked.hypothesis.id
                for a in arbitrated
                if a.adjudicated_by == "bic"
            )
        )
        ledger.append(
            "arbitration",
            {
                "primary_backend": "bic",
                "full_nested": config.full_nested,
                "close_threshold": config.close_threshold,
                "temperature": config.temperature,
                "nested_ids": list(nested_ids_tuple),
                "primary_ids": list(primary_ids),
                "reason": "close_competitors_readjudicated_by_nested",
                "warnings": list(warnings),
            },
        )

    return ArbitrationResult(
        arbitrated=arbitrated,
        nested_ids=nested_ids_tuple,
        primary_backend="bic",
        warnings=tuple(warnings),
    )


def _finalize_primary(
    primary: tuple[RankedHypothesis, ...],
    *,
    ledger: Ledger | None,
    reason: str,
) -> ArbitrationResult:
    """bic 一次判定をそのまま最終結果にする (2 段構えの下段スキップ)。REQ-102/EDGE-003。

    全仮説を adjudicated_by="bic"・logz_err=None で包み、nested_ids は空にする。ledger 非 None のとき
    「nested 非発動」を理由付きで追記する (REQ-013)。
    """
    arbitrated = tuple(
        ArbitratedHypothesis(ranked=r, adjudicated_by="bic", logz_err=None)
        for r in primary
    )
    if ledger is not None:
        ledger.append(
            "arbitration",
            {
                "primary_backend": "bic",
                "nested_ids": [],
                "primary_ids": sorted(r.hypothesis.id for r in primary),
                "reason": reason,
                "warnings": [],
            },
        )
    return ArbitrationResult(
        arbitrated=arbitrated, nested_ids=(), primary_backend="bic"
    )
