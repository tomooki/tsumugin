from __future__ import annotations

import pytest

from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore


def _phases(scale: float) -> tuple[PhaseInstance, ...]:
    return (PhaseInstance(phase_ref="P", lattice=LatticeParams(5, 5, 5), scale=scale),)


def test_save_and_load_roundtrip():
    store = SnapshotStore()
    snap = store.save(_phases(1.0), label="init")
    loaded = store.load(snap.id)
    assert loaded.phases == _phases(1.0)
    assert loaded.label == "init"


def test_ids_are_deterministic_and_sequential():
    s1 = SnapshotStore()
    ids1 = [s1.save(_phases(float(i)), label=f"s{i}").id for i in range(3)]
    s2 = SnapshotStore()
    ids2 = [s2.save(_phases(float(i)), label=f"s{i}").id for i in range(3)]
    assert ids1 == ids2
    assert ids1 == ["snap-0000", "snap-0001", "snap-0002"]


def test_revert_returns_old_state_and_keeps_forward_history():
    store = SnapshotStore()
    s0 = store.save(_phases(1.0), label="a")
    store.save(_phases(2.0), label="b")
    reverted = store.revert(s0.id)
    assert reverted == _phases(1.0)
    # forward history not deleted (P2): both snapshots still present
    assert len(store.snapshots) == 2


def test_revert_then_save_links_parent():
    store = SnapshotStore()
    s0 = store.save(_phases(1.0), label="a")
    store.save(_phases(2.0), label="b")
    store.revert(s0.id)
    s2 = store.save(_phases(3.0), label="c-from-a")
    assert s2.parent_id == s0.id


def test_ledger_records_save_and_revert():
    ledger = Ledger()
    store = SnapshotStore(ledger=ledger)
    s0 = store.save(_phases(1.0), label="a")
    store.revert(s0.id)
    kinds = [e.kind for e in ledger.entries]
    assert "snapshot_save" in kinds
    assert "snapshot_revert" in kinds
    assert ledger.verify()


def test_load_missing_id_raises():
    store = SnapshotStore()
    with pytest.raises(KeyError):
        store.load("snap-9999")


def test_no_destructive_methods():
    store = SnapshotStore()
    for name in ("delete", "clear", "pop", "remove", "overwrite"):
        assert not hasattr(store, name)
