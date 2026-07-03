"""状態スナップショットストア (P2: 非破壊 revert)。

save/revert のみを提供し、削除・上書き API を持たない。revert は前方履歴を消さず、
指定スナップショットの状態を返して「現在位置」を移すだけ。全操作は任意で ledger に記録する。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..model import PhaseInstance
from .ledger import Ledger


@dataclass(frozen=True)
class Snapshot:
    id: str
    label: str
    phases: tuple[PhaseInstance, ...]
    parent_id: str | None


class SnapshotStore:
    def __init__(self, ledger: Ledger | None = None) -> None:
        self._snaps: list[Snapshot] = []
        self._index: dict[str, Snapshot] = {}
        self._current_id: str | None = None
        self._ledger = ledger

    def save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> Snapshot:
        snap_id = f"snap-{len(self._snaps):04d}"
        snap = Snapshot(
            id=snap_id, label=label, phases=tuple(phases), parent_id=self._current_id
        )
        self._snaps.append(snap)
        self._index[snap_id] = snap
        self._current_id = snap_id
        if self._ledger is not None:
            self._ledger.append(
                "snapshot_save",
                {
                    "snapshot_id": snap_id,
                    "label": label,
                    "parent_id": snap.parent_id,
                    "n_phases": len(snap.phases),
                },
            )
        return snap

    def load(self, snapshot_id: str) -> Snapshot:
        return self._index[snapshot_id]

    def revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]:
        snap = self._index[snapshot_id]  # KeyError if missing
        self._current_id = snapshot_id
        if self._ledger is not None:
            self._ledger.append(
                "snapshot_revert",
                {"snapshot_id": snapshot_id, "label": snap.label},
            )
        return snap.phases

    @property
    def snapshots(self) -> tuple[Snapshot, ...]:
        return tuple(self._snaps)

    @property
    def current_id(self) -> str | None:
        return self._current_id
