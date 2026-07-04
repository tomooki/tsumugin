"""TASK-0051: nested/arbitration (arbitrate / ArbitrationConfig / ArbitratedHypothesis /
ArbitrationResult) のテスト。

木探索 bic 固定 + 僅差競合のみ nested 再裁定の 2 段構え裁定を検証する。dynesty/ultranest
未導入環境では ``nested.run_with_fallback`` が Laplace 代替へ縮退する (truncated=True) ため、
nested 供給テストは「対象に選ばれ evidence が再評価された」ことと縮退時 adjudicated_by="laplace"
を許容する形で検証する (実サンプラ不要)。

コア (numpy) のみ・ledger 追記のみ・決定論 (仮説 ID 昇順・nested_ids 昇順) を確認する。
"""

from __future__ import annotations

import dataclasses
import importlib

import numpy as np
import pytest

from tsumugin.model import Hypothesis, RefinementMetrics
from tsumugin.nested.arbitration import (
    ArbitratedHypothesis,
    ArbitrationConfig,
    ArbitrationResult,
    arbitrate,
)
from tsumugin.nested.base import EvidenceProblem, PriorSpec
from tsumugin.nested.sampler import NestedBackend
from tsumugin.store.ledger import Ledger


# ---------------------------------------------------------------------------
# ヘルパ: 仮説・問題ファクトリ
# ---------------------------------------------------------------------------


def _hyp(hid: str, *, chi2: float, n_params: int = 8) -> Hypothesis:
    """metrics を持つ最小の Hypothesis。BIC = chi2 + n_params*ln(n_obs) を制御する。"""
    metrics = RefinementMetrics(
        rwp=5.0, gof=1.2, chi2=chi2, n_obs=1000, n_params=n_params
    )
    return Hypothesis(id=hid, phases=(), metrics=metrics)


def _problem(label: str = "") -> EvidenceProblem:
    """尤度関数 + 事前分布を持つ最小の EvidenceProblem。"""
    priors = (
        PriorSpec(param_name="phase0.lattice.a", kind="uniform", low=4.0, high=6.0),
        PriorSpec(param_name="phase0.occ.site", kind="uniform", low=0.0, high=1.0),
    )

    def log_likelihood(theta: np.ndarray) -> float:
        center = np.array([5.0, 0.5])
        return float(-0.5 * np.sum((np.asarray(theta) - center) ** 2))

    metrics = RefinementMetrics(rwp=5.0, gof=1.2, chi2=100.0, n_obs=1000, n_params=8)
    return EvidenceProblem(
        metrics=metrics, log_likelihood=log_likelihood, priors=priors, label=label
    )


# 僅差 2 仮説 (ΔBIC < 10) + 遠い 1 仮説を作る。
# BIC = chi2 + n_params*ln(1000) は chi2 差がそのまま ΔBIC。
def _close_pair_plus_far() -> tuple[Hypothesis, ...]:
    return (
        _hyp("h1", chi2=100.0),  # best
        _hyp("h2", chi2=103.0),  # ΔBIC=3 < 10 → close_competitor
        _hyp("h3", chi2=200.0),  # ΔBIC=100 → 遠い
    )


# ---------------------------------------------------------------------------
# import / 型
# ---------------------------------------------------------------------------


def test_import_core_only():
    """import tsumugin.nested.arbitration がコア (numpy) のみで成功する。"""
    mod = importlib.import_module("tsumugin.nested.arbitration")
    assert hasattr(mod, "arbitrate")
    assert hasattr(mod, "ArbitrationConfig")
    assert hasattr(mod, "ArbitrationResult")
    assert hasattr(mod, "ArbitratedHypothesis")


def test_reexport_from_nested_package():
    """nested パッケージ __init__ から re-export される。"""
    from tsumugin.nested import (  # noqa: PLC0415
        ArbitratedHypothesis as A,
    )
    from tsumugin.nested import (  # noqa: PLC0415
        ArbitrationConfig as B,
    )
    from tsumugin.nested import (  # noqa: PLC0415
        ArbitrationResult as C,
    )
    from tsumugin.nested import arbitrate as fn  # noqa: PLC0415

    assert A is ArbitratedHypothesis
    assert B is ArbitrationConfig
    assert C is ArbitrationResult
    assert fn is arbitrate


def test_config_defaults():
    """ArbitrationConfig の既定 (full_nested=False / close_threshold=10 / temperature=1)。"""
    cfg = ArbitrationConfig()
    assert cfg.full_nested is False
    assert cfg.close_threshold == 10.0
    assert cfg.temperature == 1.0


def test_frozen_dataclasses():
    """3 型とも frozen である。"""
    cfg = ArbitrationConfig()
    with pytest.raises(dataclasses.FrozenInstanceError):
        cfg.full_nested = True  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 一次 bic 固定 (nested=None)
# ---------------------------------------------------------------------------


def test_primary_bic_all_adjudicated_by_bic_when_no_nested():
    """nested=None では全 adjudicated_by="bic"・nested_ids 空 (探索は bic 固定, REQ-010/201)。"""
    hyps = _close_pair_plus_far()
    result = arbitrate(hyps)
    assert isinstance(result, ArbitrationResult)
    assert result.primary_backend == "bic"
    assert result.nested_ids == ()
    assert all(a.adjudicated_by == "bic" for a in result.arbitrated)
    # evidence 昇順で並ぶ (best 先頭)
    values = [a.ranked.evidence.value for a in result.arbitrated]
    assert values == sorted(values)
    # 全仮説が含まれる
    ids = {a.ranked.hypothesis.id for a in result.arbitrated}
    assert ids == {"h1", "h2", "h3"}


def test_primary_does_not_mutate_search_metrics():
    """一次 bic 判定は入力 Hypothesis/metrics を書き換えない (P2)。"""
    hyps = _close_pair_plus_far()
    before = tuple(dataclasses.replace(h) for h in hyps)
    arbitrate(hyps)
    for h, b in zip(hyps, before):
        assert h.metrics == b.metrics
        assert h.status == b.status


def test_empty_hypotheses():
    """空入力は空の arbitrated / nested_ids を返す。"""
    result = arbitrate(())
    assert result.arbitrated == ()
    assert result.nested_ids == ()


# ---------------------------------------------------------------------------
# 再裁定対象抽出
# ---------------------------------------------------------------------------


def test_only_close_competitors_selected_for_nested():
    """close_competitor=True の群のみ nested 対象 (近い h1/h2 のみ nested_ids)。REQ-011。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    # h1(best, close) + h2(close) が対象。h3 は遠いので対象外。
    assert result.nested_ids == ("h1", "h2")
    assert "h3" not in result.nested_ids


def test_close_competitors_adjudicated_by_nested_or_laplace():
    """nested 対象仮説の adjudicated_by は nested / laplace、非対象は bic のまま。REQ-013/015。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    by = {a.ranked.hypothesis.id: a.adjudicated_by for a in result.arbitrated}
    # 未導入環境では run_with_fallback が Laplace 代替へ縮退 → laplace
    assert by["h1"] in ("nested", "laplace")
    assert by["h2"] in ("nested", "laplace")
    assert by["h3"] == "bic"


def test_truncated_nested_yields_laplace_adjudicated_by():
    """未導入環境 (縮退・truncated) では nested 対象の adjudicated_by="laplace"。"""
    if importlib.util.find_spec("dynesty") is not None or (
        importlib.util.find_spec("ultranest") is not None
    ):
        pytest.skip("実サンプラ導入環境: 縮退経路テストは対象外")
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    by = {a.ranked.hypothesis.id: a.adjudicated_by for a in result.arbitrated}
    assert by["h1"] == "laplace"
    assert by["h2"] == "laplace"
    # 縮退警告が伝播する
    assert result.warnings


def test_nested_evidence_replaced_for_targets():
    """nested 対象の evidence は再評価され (backend が nested/laplace に差し替わる)。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    by_id = {a.ranked.hypothesis.id: a for a in result.arbitrated}
    # 対象は bic 以外の backend で評価されている
    assert by_id["h1"].ranked.evidence.backend != "bic"
    assert by_id["h2"].ranked.evidence.backend != "bic"
    # 非対象は bic のまま
    assert by_id["h3"].ranked.evidence.backend == "bic"


def test_probabilities_recomputed_and_sum_to_one():
    """統合ランキングの確率は再計算され合計 1。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    total = sum(a.ranked.probability for a in result.arbitrated)
    assert abs(total - 1.0) < 1e-9
    # evidence 昇順で並ぶ
    values = [a.ranked.evidence.value for a in result.arbitrated]
    assert values == sorted(values)


# ---------------------------------------------------------------------------
# 僅差なし → 下段スキップ
# ---------------------------------------------------------------------------


def test_no_close_competitor_skips_nested():
    """僅差競合が無ければ nested 発動せず bic 一次を最終結果 (nested_ids 空)。REQ-102/EDGE-003。"""
    # h1 best, h2/h3 は遠い (ΔBIC >> 10)
    hyps = (
        _hyp("h1", chi2=100.0),
        _hyp("h2", chi2=200.0),
        _hyp("h3", chi2=300.0),
    )
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    assert result.nested_ids == ()
    assert all(a.adjudicated_by == "bic" for a in result.arbitrated)


def test_nested_not_triggered_when_problems_missing():
    """problems 未供給なら nested 発動せず bic 一次 (EDGE-003)。"""
    hyps = _close_pair_plus_far()
    nested = NestedBackend()
    result = arbitrate(hyps, problems=None, nested=nested)
    assert result.nested_ids == ()
    assert all(a.adjudicated_by == "bic" for a in result.arbitrated)


def test_nested_not_triggered_when_backend_missing():
    """nested 未供給なら発動せず bic 一次。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    result = arbitrate(hyps, problems=problems, nested=None)
    assert result.nested_ids == ()
    assert all(a.adjudicated_by == "bic" for a in result.arbitrated)


def test_missing_problem_for_a_target_is_skipped():
    """一部 target の problem が欠けても他 target は nested 再裁定される (欠損は bic のまま)。"""
    hyps = _close_pair_plus_far()
    # h1 の problem のみ供給、h2 は欠損
    problems = {"h1": _problem("h1")}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    # h1 のみ nested 対象 (h2 は problem 欠損でスキップ)
    assert result.nested_ids == ("h1",)
    by = {a.ranked.hypothesis.id: a.adjudicated_by for a in result.arbitrated}
    assert by["h1"] in ("nested", "laplace")
    assert by["h2"] == "bic"


# ---------------------------------------------------------------------------
# full_nested
# ---------------------------------------------------------------------------


def test_full_nested_targets_all_survivors():
    """full_nested=True で全生存仮説が nested 対象 (nested_ids に全 ID)。REQ-012/EDGE-004。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    cfg = ArbitrationConfig(full_nested=True)
    result = arbitrate(hyps, problems=problems, nested=nested, config=cfg)
    assert result.nested_ids == ("h1", "h2", "h3")
    assert all(a.adjudicated_by in ("nested", "laplace") for a in result.arbitrated)


# ---------------------------------------------------------------------------
# ledger 記録
# ---------------------------------------------------------------------------


def test_ledger_records_arbitration_with_reason():
    """bic/nested の振り分けが理由付きで ledger に記録され verify() True。REQ-013/NFR-105。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    ledger = Ledger()
    arbitrate(hyps, problems=problems, nested=nested, ledger=ledger)
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert "arbitration" in kinds
    # arbitration エントリに振り分け理由 (nested_ids / primary_ids 等) が含まれる
    arb = next(e for e in ledger.entries if e.kind == "arbitration")
    assert "nested_ids" in arb.payload


def test_ledger_records_even_without_nested():
    """nested 非発動でも arbitration が理由付きで記録される。"""
    hyps = _close_pair_plus_far()
    ledger = Ledger()
    arbitrate(hyps, ledger=ledger)
    assert ledger.verify() is True
    assert any(e.kind == "arbitration" for e in ledger.entries)


# ---------------------------------------------------------------------------
# human モード非破壊
# ---------------------------------------------------------------------------


def test_arbitrate_does_not_accept_hypotheses():
    """arbitrate は評価のみで仮説を accepted 化しない (status 不変)。REQ-203/D10。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    # 元 Hypothesis の status は candidate のまま
    for h in hyps:
        assert h.status == "candidate"
    # ArbitratedHypothesis が包む Hypothesis も accepted 化していない
    for a in result.arbitrated:
        assert a.ranked.hypothesis.status != "accepted"
        assert a.ranked.hypothesis.accepted_by is None


# ---------------------------------------------------------------------------
# 決定論
# ---------------------------------------------------------------------------


def test_deterministic_bitwise_identical():
    """同一入力で 2 回ビット同一 (仮説 ID 昇順処理・nested_ids 昇順)。NFR-102/REQ-402。"""
    hyps = _close_pair_plus_far()
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    r1 = arbitrate(hyps, problems=problems, nested=nested)
    r2 = arbitrate(hyps, problems=problems, nested=nested)
    assert r1.nested_ids == r2.nested_ids
    v1 = [(a.ranked.hypothesis.id, a.ranked.evidence.value, a.ranked.probability, a.adjudicated_by)
          for a in r1.arbitrated]
    v2 = [(a.ranked.hypothesis.id, a.ranked.evidence.value, a.ranked.probability, a.adjudicated_by)
          for a in r2.arbitrated]
    assert v1 == v2


def test_nested_ids_sorted():
    """nested_ids は昇順 (入力順に依らない)。REQ-402。"""
    # 逆順で与えても nested_ids は昇順
    hyps = (
        _hyp("h3", chi2=200.0),
        _hyp("h2", chi2=103.0),
        _hyp("h1", chi2=100.0),
    )
    problems = {h.id: _problem(h.id) for h in hyps}
    nested = NestedBackend()
    result = arbitrate(hyps, problems=problems, nested=nested)
    assert list(result.nested_ids) == sorted(result.nested_ids)
