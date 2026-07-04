"""TASK-0041 joint/verification の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/joint/verification.py``: ``JointVerificationResult`` と
  ``verify_survivors(backend, search_result, histograms, *, evidence=None,
  weighting=HistogramWeighting(), contrast=ContrastConfig(), ledger=None)
  -> JointVerificationResult``
- ``src/tsumugin/joint/__init__.py``: 上記 2 シンボルの re-export (__all__ 昇順)

契約は ``docs/design/m4-joint-mcp/interfaces.py`` の joint/verification 節に依拠。
完了条件 5 項目 (TC-405-01/02/03 / REQ-006/011 / REQ-401/402) に 1:1 対応する。

方針:
- プライマリ探索は ``HypothesisTreeSearch`` を 1 本 (プライマリ 1 ヒスト) で実行し
  ``SearchResult`` を得る (既存 test_tree_search.py のフィクスチャ流用)。
- 検証精密化は ``SimulatedBackend`` + 合成 ``JointHistogram`` (X 線 + 中性子) で行う。
- 決定論は種固定 (SimulatedBackend は乱数不使用) で ``==`` ビット同一を検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.joint import (
    ContrastConfig,
    JointHistogram,
    JointRefinementResult,
    JointVerificationResult,
    verify_survivors,
)
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.search.tree import HypothesisTreeSearch, SearchConfig, SearchResult
from tsumugin.store.ledger import Ledger

# ---------------------------------------------------------------------------
# 共通テストデータ (test_tree_search.py の観測グリッド較正を踏襲)
# ---------------------------------------------------------------------------

GRID = np.arange(15.0, 60.0, 0.02)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


PHASE_A = _phase(5.0, "A")
PHASE_B = _phase(6.0, "B")
PHASE_C = _phase(4.5, "C")


def _primary_search() -> tuple[SearchResult, SimulatedBackend]:
    """プライマリ 1 ヒストで木探索を実行し SearchResult を返す (TC-405-01)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    # 真の相 A で観測を生成 → A が良好解 (生存仮説) に入る。
    intensity = backend.simulate((PHASE_A,), GRID)
    search = HypothesisTreeSearch(backend, config=SearchConfig())
    candidates = [PhaseCandidate(phase=PHASE_A), PhaseCandidate(phase=PHASE_B), PhaseCandidate(phase=PHASE_C)]
    result = search.search(GRID, intensity, candidates)
    return result, backend


def _joint_histograms(backend: SimulatedBackend) -> tuple[JointHistogram, ...]:
    """検証用の joint ヒスト (X 線 + 中性子 CW) を合成する。"""
    y_xray = backend.simulate((PHASE_A,), GRID)
    y_neutron = backend.simulate((PHASE_A,), GRID)
    return (
        JointHistogram(two_theta=GRID, intensity=y_xray, probe="xray"),
        JointHistogram(two_theta=GRID, intensity=y_neutron, probe="neutron_cw"),
    )


def _survivor_ids(result: SearchResult) -> tuple[str, ...]:
    """SearchResult の生存仮説 (良好解) ID 集合。"""
    return result.good_cluster_ids


# ---------------------------------------------------------------------------
# (1) HypothesisTreeSearch がプライマリ 1 本で出した SearchResult を入力に取れる [TC-405-01]
# ---------------------------------------------------------------------------


def test_accepts_search_result_from_primary_single_histogram_search():
    """プライマリ 1 ヒストの SearchResult を入力に取り JointVerificationResult を返す。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)

    verification = verify_survivors(backend, result, histograms)

    assert isinstance(verification, JointVerificationResult)
    # 生存仮説が 1 件以上あり、verified に反映される。
    assert len(_survivor_ids(result)) >= 1
    assert len(verification.verified) == len(_survivor_ids(result))


# ---------------------------------------------------------------------------
# (2) 生存仮説のみが joint 検証精密化に渡る (探索段は joint 化されない) [TC-405-02/REQ-014]
# ---------------------------------------------------------------------------


def test_only_survivors_are_joint_verified_not_all_nodes():
    """joint_results は生存仮説 ID のみを持ち、非生存ノードは現れない (REQ-014)。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)

    survivors = set(_survivor_ids(result))
    all_ids = set(result.hypotheses)
    # 前提: 生存仮説は全ノードの真部分集合 (探索段全体を joint 化しない意味がある構図)。
    assert survivors, "生存仮説が空だとテストが無意味"
    assert survivors <= all_ids

    verification = verify_survivors(backend, result, histograms)

    # joint_results / recommendations のキーは生存仮説 ID に厳密一致する。
    assert set(verification.joint_results) == survivors
    assert set(verification.recommendations) == survivors
    # 非生存ノードは joint 検証に現れない。
    non_survivors = all_ids - survivors
    for nid in non_survivors:
        assert nid not in verification.joint_results


def test_joint_verification_uses_refine_joint_detailed(monkeypatch):
    """生存仮説のみが refine_joint_detailed に渡る (探索呼び出し回数=生存仮説数)。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)
    survivors = _survivor_ids(result)

    import tsumugin.joint.verification as verification_mod

    calls: list = []
    real = verification_mod.refine_joint_detailed

    def _spy(be, model, **kwargs):
        calls.append(model)
        return real(be, model, **kwargs)

    monkeypatch.setattr(verification_mod, "refine_joint_detailed", _spy)
    verify_survivors(backend, result, histograms)

    # 探索の再実行はせず、生存仮説の検証精密化のみ joint 化する。
    assert len(calls) == len(survivors)
    # 各 joint モデルは与えた histograms を使う (探索の 1 ヒストではない)。
    for model in calls:
        assert model.histograms == histograms


# ---------------------------------------------------------------------------
# (3) 検証中もプライマリ SearchResult が不変 [TC-405-03/REQ-202]
# ---------------------------------------------------------------------------


def test_primary_search_result_is_immutable_during_verification():
    """入力 SearchResult のオブジェクト同一性と値が検証前後で不変。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)

    # 検証前スナップショット (オブジェクト同一性 + metrics 値)。
    hypotheses_before = result.hypotheses
    good_before = result.good_cluster_ids
    ranked_before = result.ranked
    ledger_len_before = len(result.ledger.entries)
    metrics_before = {
        hid: (h.metrics.rwp, h.metrics.chi2) for hid, h in result.hypotheses.items()
    }
    id_map_before = {hid: id(h) for hid, h in result.hypotheses.items()}

    verification = verify_survivors(backend, result, histograms)

    # 同一性: hypotheses マッピングと各 Hypothesis オブジェクトが差し替わっていない。
    assert result.hypotheses is hypotheses_before
    assert result.good_cluster_ids is good_before
    assert result.ranked is ranked_before
    for hid, h in result.hypotheses.items():
        assert id(h) == id_map_before[hid]
        assert (h.metrics.rwp, h.metrics.chi2) == metrics_before[hid]
    # 探索段 ledger は書き換えられない (verify_survivors は探索 ledger に追記しない)。
    assert len(result.ledger.entries) == ledger_len_before

    # verified は新インスタンス (元 SearchResult のオブジェクトとは別物)。
    for h in verification.verified:
        assert id(h) not in id_map_before.values() or h is result.hypotheses.get(h.id)


def test_verified_hypotheses_are_new_instances_with_updated_metrics():
    """verified は joint 検証後 metrics を更新した新 Hypothesis (元は不変)。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)

    verification = verify_survivors(backend, result, histograms)

    for h in verification.verified:
        original = result.hypotheses[h.id]
        # 元インスタンスは変更されない (frozen ゆえ別インスタンス)。
        assert h is not original
        # metrics は joint 集約結果に更新されている。
        joint_res = verification.joint_results[h.id]
        assert h.metrics.rwp == pytest.approx(joint_res.aggregate.rwp)
        # id / parent_id は保持。
        assert h.id == original.id
        assert h.parent_id == original.parent_id


# ---------------------------------------------------------------------------
# (4) 生存仮説ごとに joint_results / recommendations が id キーで返る [REQ-006/011]
# ---------------------------------------------------------------------------


def test_joint_results_and_recommendations_keyed_by_hypothesis_id():
    """生存仮説ごとに joint_results (JointRefinementResult) と recommendations が返る。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)
    survivors = _survivor_ids(result)

    verification = verify_survivors(backend, result, histograms)

    for sid in survivors:
        assert sid in verification.joint_results
        assert isinstance(verification.joint_results[sid], JointRefinementResult)
        assert sid in verification.recommendations
        assert isinstance(verification.recommendations[sid], tuple)


def test_recommendations_fire_for_joint_contrast_sites():
    """占有元素対をコントラスト設定で供給すると生存仮説に推奨が付く (REQ-011)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    # 占有率サイトを持つ相で観測を生成し良好解に載せる。
    occ_phase = PhaseInstance(
        phase_ref="A",
        lattice=LatticeParams(5.0, 5.0, 5.0),
        occupancies={"M1": 0.5},
    )
    intensity = backend.simulate((occ_phase,), GRID)
    search = HypothesisTreeSearch(backend, config=SearchConfig())
    result = search.search(GRID, intensity, [PhaseCandidate(phase=occ_phase)])
    histograms = _joint_histograms(backend)

    # Mn/Fe は X線/中性子コントラストが十分 (|f_norm-b_norm|=0.207 >= 0.15)。
    contrast = ContrastConfig(site_elements={"M1": ("Mn", "Fe")})
    verification = verify_survivors(backend, result, histograms, contrast=contrast)

    survivors = _survivor_ids(result)
    assert survivors
    # いずれかの生存仮説にコントラスト推奨が付く。
    total = sum(len(verification.recommendations[s]) for s in survivors)
    assert total >= 1


# ---------------------------------------------------------------------------
# (5) ledger.verify() True 維持・決定論ビット同一 [REQ-401/402]
# ---------------------------------------------------------------------------


def test_ledger_verify_stays_true_after_verification():
    """ledger 非 None なら要所記録し verify() True を維持する。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)
    ledger = Ledger()

    verify_survivors(backend, result, histograms, ledger=ledger)

    assert ledger.verify() is True
    # 何らかの検証記録が積まれている。
    assert len(ledger.entries) >= 1


def test_verification_is_deterministic_bitwise_identical():
    """同一入力の 2 回実行で verified metrics が ビット同一 (NFR-102/REQ-402)。"""
    result1, backend1 = _primary_search()
    result2, backend2 = _primary_search()
    hist1 = _joint_histograms(backend1)
    hist2 = _joint_histograms(backend2)

    v1 = verify_survivors(backend1, result1, hist1)
    v2 = verify_survivors(backend2, result2, hist2)

    # verified の id 列 (順序) が一致。
    assert [h.id for h in v1.verified] == [h.id for h in v2.verified]
    # metrics がビット同一。
    for h1, h2 in zip(v1.verified, v2.verified):
        assert h1.metrics.rwp == h2.metrics.rwp
        assert h1.metrics.chi2 == h2.metrics.chi2
    # joint_results の集約 chi2/rwp もビット同一。
    assert set(v1.joint_results) == set(v2.joint_results)
    for hid in v1.joint_results:
        assert v1.joint_results[hid].aggregate.chi2 == v2.joint_results[hid].aggregate.chi2
        assert v1.joint_results[hid].aggregate.rwp == v2.joint_results[hid].aggregate.rwp


def test_verified_ordering_is_deterministic_by_hypothesis_id():
    """verified は仮説 ID 昇順で決定論的に並ぶ (REQ-402)。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)

    verification = verify_survivors(backend, result, histograms)

    ids = [h.id for h in verification.verified]
    assert ids == sorted(ids)
