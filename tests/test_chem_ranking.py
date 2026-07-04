"""chem/ranking.rank_with_plausibility のテスト (M4 / REQ-019/105 / EDGE-005/006 / REQ-402)。

最重要不変条件: ChemPlausibility スコアは降格のみに使い、候補の除外・rejected 化を行わない
(Dara 教訓)。低スコア相の仮説も rank から消えず件数不変。modules 空なら素の rank と同一。
"""

from __future__ import annotations

import pytest

from tsumugin.chem import rank_with_plausibility
from tsumugin.chem.base import PlausibilityResult, SynthesisContext
from tsumugin.evidence import BICBackend, rank
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance, RefinementMetrics
from tsumugin.model.phase import PhaseRef
from tsumugin.store.ledger import Ledger


def _metrics(chi2: float, k: int = 5, n: int = 1000) -> RefinementMetrics:
    return RefinementMetrics(rwp=0.0, gof=1.0, chi2=chi2, n_obs=n, n_params=k)


def _hyp(hid: str, chi2: float, *, phase_refs: tuple[str, ...] = ("p",)) -> Hypothesis:
    phases = tuple(
        PhaseInstance(phase_ref=f"{hid}:{pr}", lattice=LatticeParams(5, 5, 5), scale=1.0)
        for pr in phase_refs
    )
    return Hypothesis(id=hid, phases=phases, metrics=_metrics(chi2))


class _ConstModule:
    """指定 phase_ref id 集合に低スコアを付す決定論モジュール (テスト用)。"""

    def __init__(self, name: str, low_ids: frozenset[str], low: float = 0.1) -> None:
        self.name = name
        self._low_ids = low_ids
        self._low = low

    def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult:
        s = self._low if phase.id in self._low_ids else 1.0
        return PlausibilityResult(score=s, rationale=f"{phase.id}->{s}", source=self.name)


# ---- (1) 最重要: 低スコア相の仮説は順位が下がるが候補から除外されない ----
def test_low_score_phase_demoted_but_not_excluded():
    # a が最良 evidence だが a の相を強く降格 → 順位は下がるが件数は不変で a は残る。
    # evidence 差を小さく (僅差競合) して確率が比較可能な領域にし、降格が順位を動かせるようにする。
    hyps = [_hyp("a", 100.0), _hyp("b", 101.0), _hyp("c", 103.0)]
    module = _ConstModule("m", frozenset({"a:p"}), low=0.01)
    ranked = rank_with_plausibility(hyps, BICBackend(), modules=(module,))
    ids = [r.hypothesis.id for r in ranked]
    assert len(ranked) == len(hyps)  # 件数不変 (除外しない)
    assert "a" in ids  # 降格された a も残る
    # 素の rank では a が首位だが降格で首位ではなくなる
    plain = rank(hyps, BICBackend())
    assert plain[0].hypothesis.id == "a"
    assert ranked[0].hypothesis.id != "a"


# ---- (2) modules 空なら素の evidence 順位をそのまま返す ----
def test_empty_modules_returns_plain_rank():
    hyps = [_hyp("c", 300.0), _hyp("a", 100.0), _hyp("b", 150.0)]
    ranked = rank_with_plausibility(hyps, BICBackend(), modules=())
    plain = rank(hyps, BICBackend())
    assert [r.hypothesis.id for r in ranked] == [r.hypothesis.id for r in plain]
    assert [r.probability for r in ranked] == [r.probability for r in plain]
    assert [r.evidence.value for r in ranked] == [r.evidence.value for r in plain]


# ---- (3) 全仮説が低スコアでも全件 rank に残る ----
def test_all_low_score_all_survive():
    hyps = [_hyp("a", 100.0), _hyp("b", 150.0), _hyp("c", 300.0)]
    # 全相を score=0 に降格 (最悪ケース)
    module = _ConstModule("m", frozenset({"a:p", "b:p", "c:p"}), low=0.0)
    ranked = rank_with_plausibility(hyps, BICBackend(), modules=(module,))
    assert len(ranked) == len(hyps)  # 全件残る
    assert {r.hypothesis.id for r in ranked} == {"a", "b", "c"}


# ---- (4) p'=p·s 補正後に再正規化され並べ替えられる ----
def test_reweight_and_renormalize():
    hyps = [_hyp("a", 100.0), _hyp("b", 110.0)]
    # a のみ降格 (s=0.2)、b は s=1.0
    module = _ConstModule("m", frozenset({"a:p"}), low=0.2)
    ranked = rank_with_plausibility(hyps, BICBackend(), modules=(module,))
    total = sum(r.probability for r in ranked)
    assert total == pytest.approx(1.0)  # 再正規化
    # 確率降順で並ぶ
    probs = [r.probability for r in ranked]
    assert probs == sorted(probs, reverse=True)
    # 素の p に対し a は p·0.2、b は p·1.0 を再正規化した比になる
    plain = {r.hypothesis.id: r.probability for r in rank(hyps, BICBackend())}
    raw = {"a": plain["a"] * 0.2, "b": plain["b"] * 1.0}
    denom = raw["a"] + raw["b"]
    by_id = {r.hypothesis.id: r.probability for r in ranked}
    assert by_id["a"] == pytest.approx(raw["a"] / denom)
    assert by_id["b"] == pytest.approx(raw["b"] / denom)


def test_evidence_value_not_rewritten():
    # BIC 一貫性: evidence 値自体は補正しない (確率のみ)
    hyps = [_hyp("a", 100.0), _hyp("b", 150.0)]
    module = _ConstModule("m", frozenset({"a:p"}), low=0.1)
    ranked = rank_with_plausibility(hyps, BICBackend(), modules=(module,))
    plain = {r.hypothesis.id: r.evidence.value for r in rank(hyps, BICBackend())}
    for r in ranked:
        assert r.evidence.value == pytest.approx(plain[r.hypothesis.id])


# ---- (5) ledger 記録・module id 昇順・相順入力順で決定論ビット同一 ----
def test_ledger_records_demotion_and_verify_ok():
    hyps = [_hyp("a", 100.0), _hyp("b", 150.0)]
    module = _ConstModule("m", frozenset({"a:p"}), low=0.1)
    ledger = Ledger()
    rank_with_plausibility(hyps, BICBackend(), modules=(module,), ledger=ledger)
    assert ledger.verify() is True
    assert len(ledger.entries) >= 1
    # スコアと理由が記録される
    payload_blob = str([e.to_dict() for e in ledger.entries])
    assert "a" in payload_blob


def test_deterministic_bit_identical():
    hyps = [_hyp("a", 100.0, phase_refs=("x", "y")), _hyp("b", 150.0, phase_refs=("z",))]
    m1 = _ConstModule("z_mod", frozenset({"a:x"}), low=0.3)
    m2 = _ConstModule("a_mod", frozenset({"b:z"}), low=0.5)
    ctx = SynthesisContext(atmosphere="air")
    l1, l2 = Ledger(), Ledger()
    r1 = rank_with_plausibility(hyps, BICBackend(), modules=(m1, m2), context=ctx, ledger=l1)
    r2 = rank_with_plausibility(hyps, BICBackend(), modules=(m2, m1), context=ctx, ledger=l2)
    # module 順を入れ替えても結果ビット同一 (module id 昇順で評価)
    assert [(r.hypothesis.id, r.probability) for r in r1] == [
        (r.hypothesis.id, r.probability) for r in r2
    ]
    # ledger の payload も同一 (決定論)
    assert [e.payload for e in l1.entries] == [e.payload for e in l2.entries]


def test_module_id_ascending_order_records():
    # 相スコアは module id 昇順評価 → combine_plausibility の source が昇順連結
    hyps = [_hyp("a", 100.0)]
    m_b = _ConstModule("b_mod", frozenset(), low=1.0)
    m_a = _ConstModule("a_mod", frozenset(), low=1.0)
    ledger = Ledger()
    rank_with_plausibility(hyps, BICBackend(), modules=(m_b, m_a), ledger=ledger)
    blob = str([e.to_dict() for e in ledger.entries])
    # a_mod が b_mod より先に現れる (昇順)
    assert blob.index("a_mod") < blob.index("b_mod")


def test_phase_refs_mapping_used():
    # phase_refs マッピングがあれば formula/element_system 付き PhaseRef が渡る
    hyps = [_hyp("a", 100.0)]
    seen: list[PhaseRef] = []

    class _Recorder:
        name = "rec"

        def score(self, phase: PhaseRef, context: SynthesisContext) -> PlausibilityResult:
            seen.append(phase)
            return PlausibilityResult(score=1.0, rationale="", source=self.name)

    mapping = {"a:p": PhaseRef.from_phase_ref("a:p", formula="LiFePO4")}
    rank_with_plausibility(hyps, BICBackend(), modules=(_Recorder(),), phase_refs=mapping)
    assert seen and seen[0].formula == "LiFePO4"


def test_missing_metrics_raises():
    bad = Hypothesis(id="x", phases=())
    module = _ConstModule("m", frozenset())
    with pytest.raises(ValueError):
        rank_with_plausibility([bad], BICBackend(), modules=(module,))
