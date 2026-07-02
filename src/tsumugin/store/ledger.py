"""追記専用ハッシュチェーン台帳 (P2 / NFR-101 / NFR-105)。

破壊的操作(削除・改変)の API を一切持たないことで、構造的非破壊性を実装保証する。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

GENESIS_HASH = "0" * 64


def _canonical_json(payload: Mapping[str, Any]) -> str:
    """キーソート済みの正準 JSON。dict の順序差を吸収し決定論的ハッシュを保証。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _compute_hash(index: int, kind: str, payload: Mapping[str, Any], prev_hash: str) -> str:
    material = f"{prev_hash}|{index}|{kind}|{_canonical_json(payload)}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LedgerEntry:
    index: int
    kind: str
    payload: Mapping[str, Any]
    prev_hash: str
    hash: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "kind": self.kind,
            "payload": dict(self.payload),
            "prev_hash": self.prev_hash,
            "hash": self.hash,
        }


class Ledger:
    """追記専用の台帳。書き込みは append のみ、読み取りは不変タプル。"""

    def __init__(self) -> None:
        self._entries: list[LedgerEntry] = []

    def append(self, kind: str, payload: Mapping[str, Any]) -> LedgerEntry:
        """新しいエントリを追記してハッシュチェーンを伸ばす。"""
        index = len(self._entries)
        prev_hash = self._entries[-1].hash if self._entries else GENESIS_HASH
        payload = dict(payload)  # 呼び出し側の後続変更から隔離
        entry = LedgerEntry(
            index=index,
            kind=kind,
            payload=payload,
            prev_hash=prev_hash,
            hash=_compute_hash(index, kind, payload, prev_hash),
        )
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def verify(self) -> bool:
        """ハッシュチェーンの整合性を検証する。"""
        prev_hash = GENESIS_HASH
        for i, entry in enumerate(self._entries):
            if entry.index != i or entry.prev_hash != prev_hash:
                return False
            expected = _compute_hash(entry.index, entry.kind, entry.payload, entry.prev_hash)
            if entry.hash != expected:
                return False
            prev_hash = entry.hash
        return True
