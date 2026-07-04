"""mem/iterate.py の失敗テスト (TASK-0056 / REQ-024/025/026/107/202 / EDGE-008/009)。

対象実装:
- ``src/tsumugin/mem/iterate.py``:
  ``MEMRietveldConfig`` / ``MEMRietveldCycle`` / ``MEMRietveldResult`` +
  ``run_mem_rietveld(backend, mem_backend, joint_result, parent_phases, probe, *,
  config, snapshots, ledger=None) -> MEMRietveldResult``。
- ``src/tsumugin/mem/__init__.py``: re-export (__all__ 昇順)。

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の mem/iterate 節に依拠。

【不変条件】既定オフ (enabled=False→stop_reason="disabled")。有効時は各サイクルを
  SnapshotStore.save の子スナップショットとして追記 (親 phases 不変・削除/上書きしない, P2)。
  収束/max_iter/発散の停止理由を ledger 記録し verify() True 維持。MEMBackend はモック。
"""

from __future__ import annotations

import dataclasses

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.joint import JointHistogram, JointRefinementModel
from tsumugin.joint.engine import refine_joint_detailed
from tsumugin.mem.base import MEMDensityMap, MEMResult
from tsumugin.mem.iterate import (
    MEMRietveldConfig,
    MEMRietveldCycle,
    MEMRietveldResult,
    run_mem_rietveld,
)
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

import numpy as np

GRID = np.arange(15.0, 40.0, 0.05)


def _phase(ref: str = "A", a: float = 5.0) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a))


def _joint_result():
    backend = SimulatedBackend(peak_fwhm=0.2)
    phases = (_phase(),)
    y = backend.simulate(phases, GRID)
    model = JointRefinementModel(
        phases=phases,
        histograms=(JointHistogram(two_theta=GRID, intensity=y, probe="xray"),),
        shared_free_params=frozenset({"phase0.scale"}),
    )
    return backend, phases, refine_joint_detailed(backend, model)


class _MockMEMBackend:
    """決定論的な MEMResult を返すモック MEMBackend。

    r_factors 列で各サイクルの R を制御し、収束/発散シナリオを再現する。
    min_density を負にすると発散 (密度負値) を模せる。
    """

    name = "mock-mem"

    def __init__(self, r_factors=None, min_densities=None):
        self._r = list(r_factors) if r_factors is not None else None
        self._min = list(min_densities) if min_densities is not None else None
        self.calls = 0

    def run(self, mem_input):
        i = self.calls
        self.calls += 1
        r = self._r[i] if self._r is not None and i < len(self._r) else 0.1
        min_d = self._min[i] if self._min is not None and i < len(self._min) else 0.0
        dm = MEMDensityMap(
            path=f"mock-{i}.grd",
            density_kind=mem_input.density_kind,
            grid_shape=mem_input.grid_shape,
            min_density=min_d,
            max_density=10.0,
        )
        return MEMResult(density_map=dm, r_factor=r)


# ---------------------------------------------------------------------------
# (A) dataclass 形状 + 既定オフ [TC-507-01/REQ-024]
# ---------------------------------------------------------------------------


def test_config_defaults_off():
    cfg = MEMRietveldConfig()
    assert cfg.enabled is False
    assert cfg.max_iter == 5
    assert cfg.r_tol > 0.0
    assert cfg.density_tol > 0.0


def test_result_dataclasses_are_frozen():
    assert dataclasses.is_dataclass(MEMRietveldConfig)
    assert dataclasses.is_dataclass(MEMRietveldCycle)
    assert dataclasses.is_dataclass(MEMRietveldResult)


def test_disabled_returns_disabled_stop_reason_without_snapshots():
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    mem = _MockMEMBackend()
    res = run_mem_rietveld(
        backend, mem, jr, phases, "xray", config=MEMRietveldConfig(), snapshots=snaps
    )
    assert isinstance(res, MEMRietveldResult)
    assert res.stop_reason == "disabled"
    assert res.cycles == ()
    # 既定オフでは子スナップショットを一切追記しない。
    assert len(snaps.snapshots) == 0
    assert mem.calls == 0


# ---------------------------------------------------------------------------
# (B) 有効時: 子スナップショット追記・親不変 [TC-507-02/REQ-025/202/NFR-005]
# ---------------------------------------------------------------------------


def test_enabled_appends_child_snapshots_per_cycle():
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    # 収束させず max_iter まで回す (毎サイクル R を十分に変化させる)。
    mem = _MockMEMBackend(r_factors=[0.5, 0.4, 0.3, 0.2, 0.1])
    res = run_mem_rietveld(
        backend,
        mem,
        jr,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=3, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
    )
    # 各サイクルが子スナップショットとして追記される。
    assert len(res.cycles) >= 1
    assert len(snaps.snapshots) == len(res.cycles)
    for cyc in res.cycles:
        assert isinstance(cyc, MEMRietveldCycle)
        # snapshot_id は実在する子スナップショット。
        assert snaps.load(cyc.snapshot_id).id == cyc.snapshot_id
    # 子スナップショットのラベルに mem_rietveld_iter が含まれる。
    assert all("mem_rietveld_iter" in s.label for s in snaps.snapshots)


def test_parent_phases_are_immutable():
    """親 phases / joint 結果を書き換えない (P2 / REQ-202)。"""
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    parent_before = phases
    parent_ids = [id(p) for p in phases]
    jr_agg_rwp = jr.aggregate.rwp

    mem = _MockMEMBackend(r_factors=[0.5, 0.4, 0.3])
    run_mem_rietveld(
        backend,
        mem,
        jr,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=2, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
    )
    # 親 phases タプルとオブジェクトが不変。
    assert phases is parent_before
    assert [id(p) for p in phases] == parent_ids
    # joint 結果も不変。
    assert jr.aggregate.rwp == jr_agg_rwp


# ---------------------------------------------------------------------------
# (C) 停止理由: 収束 / max_iter + ledger 記録 [TC-507-03/REQ-026/EDGE-009]
# ---------------------------------------------------------------------------


def test_converged_stop_reason_and_ledger():
    """R 変化が r_tol 未満なら stop_reason="converged" で停止し ledger 記録。"""
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    ledger = Ledger()
    # 同一 R を返し続ける → 2 サイクル目で変化 0 < r_tol で収束。
    mem = _MockMEMBackend(r_factors=[0.1, 0.1, 0.1, 0.1])
    res = run_mem_rietveld(
        backend,
        mem,
        jr,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=5, r_tol=1e-3, density_tol=1e-3),
        snapshots=snaps,
        ledger=ledger,
    )
    assert res.stop_reason == "converged"
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert any("mem_rietveld" in k for k in kinds)


def test_max_iter_stop_reason():
    """収束せず max_iter 到達で stop_reason="max_iter"。"""
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    ledger = Ledger()
    mem = _MockMEMBackend(r_factors=[0.9, 0.7, 0.5, 0.3, 0.1, 0.05])
    res = run_mem_rietveld(
        backend,
        mem,
        jr,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=3, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
        ledger=ledger,
    )
    assert res.stop_reason == "max_iter"
    assert len(res.cycles) == 3
    assert ledger.verify() is True


# ---------------------------------------------------------------------------
# (D) 発散: 密度負値/R 悪化で停止・子スナップショット残存 [TC-507-04/REQ-107/EDGE-008]
# ---------------------------------------------------------------------------


def test_diverged_on_negative_density_keeps_snapshot():
    """密度負値を検知したら stop_reason="diverged"、当該サイクルを子スナップショットに残す。"""
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    ledger = Ledger()
    # 2 サイクル目で min_density < 0 (発散)。
    mem = _MockMEMBackend(
        r_factors=[0.5, 0.4, 0.3], min_densities=[0.0, -1.0, 0.0]
    )
    res = run_mem_rietveld(
        backend,
        mem,
        jr,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=5, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
        ledger=ledger,
    )
    assert res.stop_reason == "diverged"
    assert len(res.warnings) >= 1
    # 発散サイクルも子スナップショットに残る (破壊しない)。
    assert len(snaps.snapshots) == len(res.cycles)
    assert len(res.cycles) >= 1
    assert ledger.verify() is True
    kinds = [e.kind for e in ledger.entries]
    assert any("mem_rietveld" in k for k in kinds)


def test_diverged_on_r_worsening():
    """R が悪化 (増加) したら発散として停止する。"""
    backend, phases, jr = _joint_result()
    snaps = SnapshotStore()
    # R が上がる (0.1 -> 0.5) → 発散。
    mem = _MockMEMBackend(r_factors=[0.1, 0.5, 0.9])
    res = run_mem_rietveld(
        backend,
        mem,
        jr,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=5, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
    )
    assert res.stop_reason == "diverged"
