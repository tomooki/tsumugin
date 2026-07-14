"""追記専用ストア (Ledger / Snapshot)。"""

from __future__ import annotations

from .ledger import GENESIS_HASH, Ledger, LedgerEntry
from .persistent import PersistentLedger, PersistentSnapshotStore
from .serialization import phase_from_dict, phase_to_dict
from .snapshot import Snapshot, SnapshotStore

# 【Issue #64 レビュー対応】: metrics_to_dict/metrics_from_dict は本番永続化経路 (PersistentLedger/
# PersistentSnapshotStore、Snapshot は phases のみ永続化) から呼ばれておらず、パッケージ集約面
# (store の公開 API) へ昇格させる自然な配線先が無い。webui/将来の永続化用ユーティリティとして
# tsumugin.store.serialization モジュール内 API に留め、ここでは re-export しない
# (``from tsumugin.store.serialization import metrics_to_dict, metrics_from_dict`` で直接利用可能)。

__all__ = [
    "GENESIS_HASH",
    "Ledger",
    "LedgerEntry",
    "PersistentLedger",
    "PersistentSnapshotStore",
    "Snapshot",
    "SnapshotStore",
    "phase_from_dict",
    "phase_to_dict",
]
