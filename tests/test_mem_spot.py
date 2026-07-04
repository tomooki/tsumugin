"""mem/spot.py の失敗テスト (TASK-0056 / REQ-032/405 / FR-606)。

対象実装:
- ``src/tsumugin/mem/spot.py``:
  ``run_mem_spot(backend, mem_backend, series, verification, hypothesis_id, frame_index,
  probe, *, grid_shape=(64,64,64), ledger=None) -> MEMResult``。
- ``src/tsumugin/mem/__init__.py``: re-export (__all__ 昇順)。

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の mem/spot 節に依拠。

【不変条件】指定単一フレームの joint 検証済み仮説に MEM をスポット実行。全フレーム自動反復
  しない (spot 単位完結, REQ-405)。check_mem_applicability の警告を MEMResult.warnings に伝播
  (除外しない, REQ-031)。MEMBackend はモック。
"""

from __future__ import annotations

import numpy as np

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.joint import JointHistogram, verify_survivors
from tsumugin.mem.base import MEMDensityMap, MEMResult
from tsumugin.mem.spot import run_mem_spot
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.search.tree import HypothesisTreeSearch, SearchConfig
from tsumugin.sequential.series import FrameSeries
from tsumugin.store.ledger import Ledger

GRID = np.arange(15.0, 50.0, 0.05)


def _phase(a: float, ref: str) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a))


PHASE_A = _phase(5.0, "A")
PHASE_B = _phase(6.0, "B")


class _MockMEMBackend:
    """呼び出しごとに決定論的 MEMResult を返すモック MEMBackend。"""

    name = "mock-mem"

    def __init__(self):
        self.calls = 0

    def run(self, mem_input):
        self.calls += 1
        dm = MEMDensityMap(
            path="spot-mock.grd",
            density_kind=mem_input.density_kind,
            grid_shape=mem_input.grid_shape,
            min_density=0.0,
            max_density=10.0,
        )
        return MEMResult(density_map=dm)


def _verification():
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate((PHASE_A,), GRID)
    search = HypothesisTreeSearch(backend, config=SearchConfig())
    result = search.search(
        GRID, y, [PhaseCandidate(phase=PHASE_A), PhaseCandidate(phase=PHASE_B)]
    )
    histograms = (
        JointHistogram(two_theta=GRID, intensity=y, probe="xray"),
        JointHistogram(two_theta=GRID, intensity=y, probe="neutron_cw"),
    )
    verification = verify_survivors(backend, result, histograms)
    return backend, verification


def _series(n_frames: int = 4) -> FrameSeries:
    backend = SimulatedBackend(peak_fwhm=0.2)
    rows = [backend.simulate((PHASE_A,), GRID) for _ in range(n_frames)]
    intensities = np.vstack(rows)
    return FrameSeries(
        two_theta=GRID,
        intensities=intensities,
        axis_values=tuple(float(i) for i in range(n_frames)),
        axis_kind="time",
    )


def _survivor_id(verification):
    return verification.verified[0].id


# ---------------------------------------------------------------------------
# (A) 指定フレームに MEM 実行し MEMResult を返す [TC-510-01/REQ-032]
# ---------------------------------------------------------------------------


def test_spot_runs_mem_on_specified_frame_returns_result():
    backend, verification = _verification()
    series = _series()
    mem = _MockMEMBackend()
    sid = _survivor_id(verification)

    result = run_mem_spot(backend, mem, series, verification, sid, 1, "xray")

    assert isinstance(result, MEMResult)
    assert isinstance(result.density_map, MEMDensityMap)


# ---------------------------------------------------------------------------
# (B) 全フレーム自動反復しない — 1 フレームのみ処理 [TC-510-02/REQ-405]
# ---------------------------------------------------------------------------


def test_spot_processes_single_frame_not_all():
    """MEMBackend.run は 1 回のみ呼ばれる (全フレーム反復しない)。"""
    backend, verification = _verification()
    series = _series(n_frames=5)
    mem = _MockMEMBackend()
    sid = _survivor_id(verification)

    run_mem_spot(backend, mem, series, verification, sid, 2, "xray")

    assert mem.calls == 1


def test_spot_frame_index_selects_frame():
    """異なる frame_index でも 1 フレーム完結 (反復せず MEMResult を返す)。"""
    backend, verification = _verification()
    series = _series(n_frames=3)
    sid = _survivor_id(verification)

    for idx in range(series.n_frames):
        mem = _MockMEMBackend()
        result = run_mem_spot(backend, mem, series, verification, sid, idx, "xray")
        assert isinstance(result, MEMResult)
        assert mem.calls == 1


# ---------------------------------------------------------------------------
# (C) guard 警告を warnings に伝播・除外しない [REQ-031]
# ---------------------------------------------------------------------------


def test_spot_propagates_guard_warnings_without_exclusion():
    """多相/非推奨仮説でも実行を止めず guard 警告を MEMResult.warnings に伝播する。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    # 拮抗多相仮説を検証結果へ載せるため、複数相の観測で探索させる。
    multi = (
        PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0), scale=1.0),
        PhaseInstance(phase_ref="B", lattice=LatticeParams(6.0, 6.0, 6.0), scale=1.0),
    )
    y = backend.simulate(multi, GRID)
    search = HypothesisTreeSearch(backend, config=SearchConfig())
    result = search.search(
        GRID, y, [PhaseCandidate(phase=multi[0]), PhaseCandidate(phase=multi[1])]
    )
    histograms = (JointHistogram(two_theta=GRID, intensity=y, probe="xray"),)
    verification = verify_survivors(backend, result, histograms)
    series = _series()
    mem = _MockMEMBackend()

    # 拮抗多相の生存仮説を探す。
    target = None
    for h in verification.verified:
        if len(h.phases) >= 2:
            target = h.id
            break
    if target is None:
        target = verification.verified[0].id

    res = run_mem_spot(backend, mem, series, verification, target, 0, "xray")

    # 実行は止まらない (MEMResult が返る)。仮説除外は起きず verified の status は不変。
    assert isinstance(res, MEMResult)
    for h in verification.verified:
        assert h.status != "rejected"
    # target が多相なら guard 警告が MEMResult.warnings へ伝播している。
    target_hyp = next(h for h in verification.verified if h.id == target)
    if len(target_hyp.phases) >= 2:
        assert len(res.warnings) >= 1


def test_spot_unknown_hypothesis_id_raises_value_error():
    """未知 hypothesis_id は素の KeyError でなく明示メッセージの ValueError を上げる (MEDIUM-2)。

    frame_index 範囲外の ValueError 方針と統一する (fail-loud・非一貫の解消)。
    """
    import pytest

    backend, verification = _verification()
    series = _series()
    mem = _MockMEMBackend()
    with pytest.raises(ValueError) as exc:
        run_mem_spot(backend, mem, series, verification, "NO_SUCH_ID", 0, "xray")
    # 明示メッセージ (対象 ID を含む) を持つ。
    assert "NO_SUCH_ID" in str(exc.value)
    # MEMBackend は呼ばれない (入力生成前に弾く)。
    assert mem.calls == 0


def test_spot_ledger_verify_stays_true():
    backend, verification = _verification()
    series = _series()
    mem = _MockMEMBackend()
    ledger = Ledger()
    sid = _survivor_id(verification)

    run_mem_spot(backend, mem, series, verification, sid, 0, "xray", ledger=ledger)

    assert ledger.verify() is True
