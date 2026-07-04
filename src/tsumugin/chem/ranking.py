"""ChemPlausibility 降格を素の evidence rank へ配線する (M4 / REQ-019/105 / FR-412)。

``rank_with_plausibility``: まず ``evidence.ranking.rank`` で素の順位・確率 p を得る。
ChemPlausibility モジュール未登録 (空) なら素の rank をそのまま返す (REQ-105/EDGE-006)。
非空なら各仮説の各相を評価し ``combine_plausibility`` で相スコア s∈[0,1] を合成、相スコアを
幾何平均して仮説スコア s_hyp を得て p' = p·s_hyp で確率補正し再正規化・並べ替える。

【最重要不変条件 (Dara 教訓 / REQ-019/EDGE-005)】: スコアは降格のみに使い、候補の除外・
rejected 化は一切行わない。低スコア相も rank から消えず出力件数 = 入力件数で不変。s=0 でも
p'=0 になるだけで rank からは消えない (最下位に残る)。evidence 値 (BIC) 自体は書き換えない
(BIC 比較の一貫性)。補正は確率 p のみ。
"""

from __future__ import annotations

from dataclasses import replace
from typing import Mapping, Sequence

from ..evidence.base import EvidenceBackend
from ..evidence.ranking import RankedHypothesis, rank
from ..model import Hypothesis
from ..model.phase import PhaseRef
from ..store.ledger import Ledger
from .base import ChemPlausibility, PlausibilityResult, SynthesisContext
from .compose import combine_plausibility


def _resolve_phase_ref(phase_ref: str, phase_refs: Mapping[str, PhaseRef] | None) -> PhaseRef:
    """相の str phase_ref を PhaseRef へ解決する。

    phase_refs マッピングに登録があればそれを使い、無ければ PhaseRef.from_phase_ref で生成する。
    """
    if phase_refs is not None and phase_ref in phase_refs:
        return phase_refs[phase_ref]
    return PhaseRef.from_phase_ref(phase_ref)


def _phase_score(
    phase_ref: str,
    *,
    modules: Sequence[ChemPlausibility],
    context: SynthesisContext,
    phase_refs: Mapping[str, PhaseRef] | None,
    weights: Mapping[str, float] | None,
) -> PlausibilityResult:
    """1 相を全モジュールで評価し combine_plausibility で相スコアへ合成する。

    【決定論】: module id (name) 昇順で score を呼ぶ (REQ-402)。combine_plausibility 内部でも
    source 昇順で合成順を固定する。
    """
    ref = _resolve_phase_ref(phase_ref, phase_refs)
    ordered_modules = sorted(modules, key=lambda m: m.name)
    results = [m.score(ref, context) for m in ordered_modules]
    return combine_plausibility(results, weights=weights)


def _hypothesis_score(phase_scores: Sequence[float]) -> float:
    """相スコア列を幾何平均して仮説スコア s_hyp∈[0,1] を得る。

    【合成方針 (D5)】: 仮説の妥当性は含有相の妥当性の合成。相スコアの幾何平均を用いる
    (combine_plausibility の module 合成と整合し [0,1] に収まり相数に依存しにくい)。相順は
    入力順で決定論だが幾何平均は順序不変。相が 0 個の仮説は降格なし (s=1.0) とする。
    s_phase=0 が 1 つでもあれば幾何平均も 0 (降格伝播・除外はしない)。
    """
    if not phase_scores:
        return 1.0
    product = 1.0
    for s in phase_scores:
        base = max(s, 0.0)  # 負値混入は 0 クランプで安全化
        if base == 0.0:
            return 0.0
        product *= base
    return product ** (1.0 / len(phase_scores))


def rank_with_plausibility(
    hypotheses: Sequence[Hypothesis],
    backend: EvidenceBackend,
    *,
    modules: Sequence[ChemPlausibility] = (),
    context: SynthesisContext = SynthesisContext(),
    phase_refs: Mapping[str, PhaseRef] | None = None,
    weights: Mapping[str, float] | None = None,
    temperature: float = 1.0,
    close_threshold: float = 10.0,
    ledger: Ledger | None = None,
) -> tuple[RankedHypothesis, ...]:
    """素の evidence rank に ChemPlausibility 降格を配線する (候補除外しない)。🔵 REQ-019/105/FR-412

    【配線 (D5)】: まず evidence.ranking.rank で素の順位・確率 p を得る。modules 非空なら各仮説の
    各相を score → combine_plausibility で相スコア s∈[0,1] を合成し、相スコアの幾何平均を仮説
    スコア s_hyp として p' = p·s_hyp で確率補正 → 全仮説で再正規化 (Σp'=1) → 確率降順に並べ替え。
    modules 空なら素の rank をそのまま返す (REQ-105/EDGE-006)。

    【最重要不変条件】: 降格のみ。候補の除外・rejected 化は行わない。低スコア相・低スコア仮説も
    rank に残り出力件数 = 入力件数で不変 (REQ-019/EDGE-005)。全仮説が低スコアでも全件残る。

    【BIC 一貫性】: evidence 値 (BIC) 自体は補正しない。RankedHypothesis.evidence は素の値のまま。
    【決定論】: module id 昇順・相順は入力順 (REQ-402)。降格スコアと理由を ledger 記録。
    """
    # 【素の rank】: 順位・確率 p・evidence 値・close_competitor を取得 (metrics None は ValueError) 🔵
    plain = rank(
        hypotheses, backend, temperature=temperature, close_threshold=close_threshold
    )

    # 【EDGE-006 / REQ-105】: modules 空なら降格なしで素の rank をそのまま返す 🔵
    if not modules or not plain:
        return plain

    # 【降格スコア算出】: 各仮説の相スコアを合成し仮説スコア s_hyp を得る。相順は入力順で決定論 🔵
    reweighted: list[tuple[RankedHypothesis, float]] = []
    ledger_records: list[dict[str, object]] = []
    for rh in plain:
        phase_results = [
            _phase_score(
                ph.phase_ref,
                modules=modules,
                context=context,
                phase_refs=phase_refs,
                weights=weights,
            )
            for ph in rh.hypothesis.phases
        ]
        phase_scores = [pr.score for pr in phase_results]
        s_hyp = _hypothesis_score(phase_scores)
        reweighted.append((rh, rh.probability * s_hyp))
        ledger_records.append(
            {
                "hypothesis_id": rh.hypothesis.id,
                "plausibility_score": s_hyp,
                "prior_probability": rh.probability,
                "posterior_probability_unnormalized": rh.probability * s_hyp,
                "phases": [
                    {"phase_ref": ph.phase_ref, "score": pr.score, "rationale": pr.rationale}
                    for ph, pr in zip(rh.hypothesis.phases, phase_results)
                ],
            }
        )

    # 【再正規化】: Σp'=1 に正規化する。全 p'=0 の縮退時は素の確率へフォールバック (件数不変) 🔵
    denom = sum(p_prime for _, p_prime in reweighted)
    if denom > 0.0:
        normalized = [
            replace(rh, probability=p_prime / denom) for rh, p_prime in reweighted
        ]
    else:
        # 全仮説が s=0 でも除外しない。素の相対確率を保持して全件残す (EDGE-005) 🔵
        normalized = [replace(rh, probability=rh.probability) for rh, _ in reweighted]

    # 【並べ替え】: 確率降順。同確率は素の rank 順 (evidence 昇順) を保つ安定ソートで tie-break 🔵
    #   Python の sort は安定なので、既に evidence 昇順の normalized を確率降順キーで並べれば
    #   同確率時は元の順序 (良い evidence 順) が維持される (REQ-402)。
    ordered = sorted(normalized, key=lambda rh: -rh.probability)

    # 【ledger 記録】: 降格スコアと理由を追記 (追記のみ・verify() True 維持) 🔵 REQ-402
    if ledger is not None:
        ledger.append(
            "chem_plausibility_demotion",
            {
                "backend": backend.name,
                "modules": sorted(m.name for m in modules),
                "records": ledger_records,
            },
        )

    return tuple(ordered)
