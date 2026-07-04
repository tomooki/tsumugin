"""oed (proposal / pyboed) の失敗テスト (TASK-0058 / REQ-035〜038/105/304 / EDGE-010/011)。

対象実装:
- ``src/tsumugin/oed/proposal.py``:
  ``MeasurementKind`` (Literal) / ``OEDProposal`` (frozen dataclass) /
  ``propose_measurements(ranked, *, close_threshold=10.0, ledger=None) -> tuple[OEDProposal, ...]`` /
  ``proposals_to_json(proposals) -> list[dict]``。
- ``src/tsumugin/oed/pyboed.py``:
  ``acquire(proposals, *, config=None) -> tuple[OEDProposal, ...]`` (pyboed 遅延 import・未導入で
  ``OEDUnavailableError``)。
- ``src/tsumugin/oed/__init__.py``: re-export (__all__ 昇順)。

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の oed/proposal.py・oed/pyboed.py 節に依拠。

【最重要不変条件 (REQ-037/P2)】: propose_measurements は非破壊 (提案のみ・仮説を accepted/rejected 化
  せず・データ改変しない・ledger 非 None のとき追記記録のみ)。僅差競合が無ければ空 tuple (EDGE-010)。
"""

from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json
import math

import pytest

from tsumugin.evidence.base import EvidenceResult
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.model import Hypothesis, RefinementMetrics
from tsumugin.oed.proposal import (
    MeasurementKind,
    OEDProposal,
    propose_measurements,
    proposals_to_json,
)
from tsumugin.oed.pyboed import acquire
from tsumugin.store.ledger import Ledger


# ---------------------------------------------------------------------------
# ヘルパ: RankedHypothesis ファクトリ (rank の出力を模す)
# ---------------------------------------------------------------------------


def _ranked(
    hid: str, evidence_value: float, *, close: bool, probability: float = 0.5
) -> RankedHypothesis:
    """close_competitor フラグと evidence 値を制御した RankedHypothesis を組む。"""
    h = Hypothesis(
        id=hid,
        phases=(),
        metrics=RefinementMetrics(
            rwp=5.0, gof=1.1, chi2=evidence_value, n_obs=1000, n_params=8
        ),
    )
    ev = EvidenceResult(backend="bic", value=evidence_value)
    return RankedHypothesis(
        hypothesis=h, evidence=ev, probability=probability, close_competitor=close
    )


def _close_competition() -> tuple[RankedHypothesis, ...]:
    """僅差競合を含む ranked (best + 僅差 1 件 + 遠い 1 件)。"""
    return (
        _ranked("h1", 100.0, close=True),  # best
        _ranked("h2", 103.0, close=True),  # ΔBIC=3 < 10 → 僅差競合
        _ranked("h3", 200.0, close=False),  # 遠い
    )


def _no_close_competition() -> tuple[RankedHypothesis, ...]:
    """僅差競合の無い ranked (best のみ close、他は遠い)。"""
    return (
        _ranked("h1", 100.0, close=True),  # best は自明に close
        _ranked("h2", 200.0, close=False),
        _ranked("h3", 300.0, close=False),
    )


# ---------------------------------------------------------------------------
# import / 型
# ---------------------------------------------------------------------------


def test_import_core_only():
    """import tsumugin.oed / oed.proposal / oed.pyboed がコア (numpy) のみで成功する。"""
    for name in ("tsumugin.oed", "tsumugin.oed.proposal", "tsumugin.oed.pyboed"):
        mod = importlib.import_module(name)
        assert mod is not None


def test_reexport_from_oed_package():
    """oed パッケージ __init__ から re-export される (同一実体)。"""
    from tsumugin.oed import MeasurementKind as MK  # noqa: PLC0415
    from tsumugin.oed import OEDProposal as OP  # noqa: PLC0415
    from tsumugin.oed import acquire as ac  # noqa: PLC0415
    from tsumugin.oed import propose_measurements as pm  # noqa: PLC0415
    from tsumugin.oed import proposals_to_json as pj  # noqa: PLC0415

    assert MK is MeasurementKind
    assert OP is OEDProposal
    assert pm is propose_measurements
    assert pj is proposals_to_json
    assert ac is acquire


def test_oed_proposal_is_frozen_dataclass():
    """OEDProposal は frozen dataclass で parameters は既定空 dict。"""
    p = OEDProposal(
        kind="high_statistics_remeasure",
        target_hypothesis_ids=("h1", "h2"),
        rationale="判別のため",
        estimated_information_gain=1.5,
    )
    assert dataclasses.is_dataclass(OEDProposal)
    assert p.parameters == {}
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.rationale = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 発動条件: 僅差競合が有るときのみ提案 [TC-512-01/REQ-035/038]
# ---------------------------------------------------------------------------


def test_proposes_when_close_competitor_exists():
    """僅差競合が存在するとき判別測定提案を生成する (非空)。REQ-035。"""
    proposals = propose_measurements(_close_competition())
    assert isinstance(proposals, tuple)
    assert len(proposals) >= 1
    assert all(isinstance(p, OEDProposal) for p in proposals)


def test_proposal_kinds_are_valid_measurement_kinds():
    """生成される提案 kind は 4 種の MeasurementKind のいずれか。REQ-035。"""
    valid = {
        "high_statistics_remeasure",
        "additional_temperature_point",
        "neutron_for_joint",
        "composition_analysis",
    }
    proposals = propose_measurements(_close_competition())
    for p in proposals:
        assert p.kind in valid


def test_proposals_target_close_competitors_sorted():
    """提案の target_hypothesis_ids は僅差競合の ID 群で昇順。REQ-038/402。"""
    proposals = propose_measurements(_close_competition())
    for p in proposals:
        assert list(p.target_hypothesis_ids) == sorted(p.target_hypothesis_ids)
        # 僅差競合 (h1/h2) のみが対象。遠い h3 は含まれない。
        assert "h3" not in p.target_hypothesis_ids
        assert set(p.target_hypothesis_ids) <= {"h1", "h2"}


# ---------------------------------------------------------------------------
# 僅差競合なし → 空 tuple [TC-512-03/REQ-038/EDGE-010]
# ---------------------------------------------------------------------------


def test_no_close_competitor_returns_empty_tuple():
    """僅差競合が無ければ空 tuple を返す (状態変更なし)。EDGE-010。"""
    proposals = propose_measurements(_no_close_competition())
    assert proposals == ()


def test_empty_ranked_returns_empty_tuple():
    """空 ranked も空 tuple を返す (縮退・例外化しない)。"""
    assert propose_measurements(()) == ()


def test_single_hypothesis_returns_empty_tuple():
    """単一仮説 (競合相手なし) は空 tuple を返す。"""
    single = (_ranked("h1", 100.0, close=True),)
    assert propose_measurements(single) == ()


# ---------------------------------------------------------------------------
# 情報利得順 + 決定論 [TC-512-05/REQ-304/402/NFR-102]
# ---------------------------------------------------------------------------


def test_proposals_sorted_by_information_gain_descending():
    """提案は estimated_information_gain 降順で並ぶ (同点は kind 昇順)。REQ-035/304/402。"""
    proposals = propose_measurements(_close_competition())
    gains = [p.estimated_information_gain for p in proposals]
    assert gains == sorted(gains, reverse=True)


def test_proposals_stable_order_gain_then_kind():
    """同一利得の提案は kind 昇順で安定ソートされる (決定論)。REQ-402。"""
    proposals = propose_measurements(_close_competition())
    # (利得降順, kind 昇順) の安定順であることを検証する。
    keyed = [(-p.estimated_information_gain, p.kind) for p in proposals]
    assert keyed == sorted(keyed)


def test_proposals_deterministic_bitwise_identical():
    """同一入力で 2 回ビット同一 (乱数不使用・提案順固定)。NFR-102/REQ-402。"""
    ranked = _close_competition()
    p1 = propose_measurements(ranked)
    p2 = propose_measurements(ranked)
    assert p1 == p2


def test_information_gain_is_finite_scalar():
    """推定情報利得は有限スカラ (v1 簡易近似・乱数禁止)。REQ-304。"""
    proposals = propose_measurements(_close_competition())
    for p in proposals:
        assert isinstance(p.estimated_information_gain, float)
        assert math.isfinite(p.estimated_information_gain)


# ---------------------------------------------------------------------------
# 非破壊性 [TC-512-02/REQ-037/P2]
# ---------------------------------------------------------------------------


def test_propose_is_non_destructive_on_hypotheses():
    """提案生成は仮説を accepted/rejected 化せず status/metrics を書き換えない。REQ-037/P2。"""
    ranked = _close_competition()
    before_status = [r.hypothesis.status for r in ranked]
    before_metrics = [r.hypothesis.metrics for r in ranked]
    propose_measurements(ranked)
    assert [r.hypothesis.status for r in ranked] == before_status
    assert [r.hypothesis.metrics for r in ranked] == before_metrics
    for r in ranked:
        assert r.hypothesis.status != "accepted"
        assert r.hypothesis.accepted_by is None


def test_propose_without_ledger_does_not_change_state():
    """ledger=None のときは追記記録も無く純粋に提案を返すのみ。REQ-037。"""
    ranked = _close_competition()
    proposals = propose_measurements(ranked, ledger=None)
    assert isinstance(proposals, tuple)


def test_propose_records_only_appends_to_ledger():
    """ledger 非 None のとき oed_proposal を追記記録し verify() True。REQ-037/P2/NFR-101。"""
    ledger = Ledger()
    propose_measurements(_close_competition(), ledger=ledger)
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert "oed_proposal" in kinds


def test_propose_no_close_competitor_does_not_touch_ledger():
    """僅差競合が無ければ ledger へ一切追記しない (状態変更なし)。EDGE-010。"""
    ledger = Ledger()
    propose_measurements(_no_close_competition(), ledger=ledger)
    assert len(ledger.entries) == 0


# ---------------------------------------------------------------------------
# proposals_to_json [TC-512-01/REQ-035/402]
# ---------------------------------------------------------------------------


def test_proposals_to_json_shape_and_order():
    """JSON 化は list[dict] で情報利得順・全キーを含む。REQ-035/402。"""
    proposals = propose_measurements(_close_competition())
    rows = proposals_to_json(proposals)
    assert isinstance(rows, list)
    assert all(isinstance(row, dict) for row in rows)
    for row in rows:
        assert set(row) >= {
            "kind",
            "target_hypothesis_ids",
            "rationale",
            "estimated_information_gain",
        }
    # 情報利得順を保つ (非有限は None 化されうるので None を末尾扱いにしない素直な比較)。
    gains = [row["estimated_information_gain"] for row in rows]
    non_none = [g for g in gains if g is not None]
    assert non_none == sorted(non_none, reverse=True)


def test_proposals_to_json_is_json_dumps_safe():
    """proposals_to_json の出力は json.dumps(allow_nan=False) で安全に直列化できる。EDGE。"""
    proposals = propose_measurements(_close_competition())
    rows = proposals_to_json(proposals)
    # 非有限が None 化されているため allow_nan=False でクラッシュしない。
    json.dumps(rows, allow_nan=False)


def test_proposals_to_json_purifies_non_finite_gain():
    """非有限な情報利得は finite_or_none で None 化される。REQ-035。"""
    p = OEDProposal(
        kind="high_statistics_remeasure",
        target_hypothesis_ids=("h1", "h2"),
        rationale="r",
        estimated_information_gain=float("inf"),
    )
    rows = proposals_to_json((p,))
    assert rows[0]["estimated_information_gain"] is None


def test_proposals_to_json_empty():
    """空提案は空 list を返す。"""
    assert proposals_to_json(()) == []


# ---------------------------------------------------------------------------
# pyboed acquire 境界 [TC-512-04/REQ-036/105/EDGE-011]
# ---------------------------------------------------------------------------


def test_acquire_raises_oed_unavailable_when_pyboed_missing():
    """pyboed 未導入で acquire を呼ぶと OEDUnavailableError を送出する。REQ-036/EDGE-011。"""
    from tsumugin.errors import OEDUnavailableError  # noqa: PLC0415

    if importlib.util.find_spec("pyboed") is not None:
        pytest.skip("pyboed 導入環境: 未導入縮退テストは対象外")
    proposals = propose_measurements(_close_competition())
    with pytest.raises(OEDUnavailableError):
        acquire(proposals)


def test_import_pyboed_module_succeeds_without_pyboed():
    """import tsumugin.oed.pyboed はコア (numpy) のみで成功する (遅延 import)。REQ-036/105。"""
    mod = importlib.import_module("tsumugin.oed.pyboed")
    assert hasattr(mod, "acquire")


def test_propose_does_not_depend_on_pyboed():
    """propose_measurements (v1) は pyboed 非依存で動作する (import で pyboed を載せない)。REQ-105。"""
    import sys  # noqa: PLC0415

    if importlib.util.find_spec("pyboed") is None:
        # 提案生成を実行しても pyboed は sys.modules に載らない。
        propose_measurements(_close_competition())
        assert "pyboed" not in sys.modules
