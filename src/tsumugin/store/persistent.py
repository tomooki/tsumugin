"""JSONL 永続版の追記専用ハッシュチェーン台帳 (TASK-0013 / REQ-010 / REQ-012 / EDGE-003)。

in-memory の Ledger と同一契約 (append / entries / verify) を持つ永続版。
書き込みは追記モード ("a") による 1 行追記のみ (NFR-203)。オープン時に既存 JSONL の
全ハッシュチェーンを検証し、破損は LedgerIntegrityError で明示エラー化する
（修復・上書き・切り詰めは一切しない — P2 / NFR-105）。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping

from ..errors import LedgerIntegrityError
from ..model import PhaseInstance
from .ledger import GENESIS_HASH, Ledger, LedgerEntry, _compute_hash, verify_entries
from .serialization import phase_from_dict, phase_to_dict
from .snapshot import Snapshot


class PersistentLedger:
    """【機能概要】: 追記専用ハッシュチェーン台帳の JSONL 永続版。

    【実装方針】: ハッシュ計算 (_compute_hash) と検証 (verify_entries) を ledger.py と
    共有し、in-memory Ledger と hash 列がビット同一になる決定論を保証する (NFR-102)。
    削除・上書き・改変 API は一切持たない (P2 / REQ-401)。
    【テスト対応】: tests/test_persistent_store.py 全 14 件。
    🔵 信頼性レベル: 要件定義 §2.1-2.4 / interfaces.py L269-281 に直接依拠
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        """【機能概要】: JSONL パスを開き、既存エントリを復元して全チェーンを検証する。

        【実装方針】: 読み取りのみ（新規パスではファイルを作らず、初回 append で作成）。
        破損検出時は LedgerIntegrityError を送出し、ファイルには一切書き込まない。
        【テスト対応】: TC-106-01/04、新規パス境界・空 ledger・末尾空行スキップ。
        🔵 信頼性レベル: 要件定義 §2.1（PathLike 許容は 🟡 拡張）
        """
        # 【状態初期化】: パスと内部エントリリストを準備（in-memory Ledger と同じ保持形式）🔵
        self._path = Path(path)
        self._entries: list[LedgerEntry] = []
        # 【既存ファイル読込】: 存在する場合のみ復元＋検証。不在なら空 ledger（GENESIS 起点）🔵
        if self._path.exists():
            self._load_and_verify()

    def _load_and_verify(self) -> None:
        """【機能概要】: JSONL 各行を LedgerEntry に再構築し、チェーン全体を検証する。

        【実装方針】: ファイルの値をそのまま使い hash を再計算で埋め直さない
        （1 バイトの改竄も verify_entries の再計算突合で検出するため）。
        【テスト対応】: 改竄 hash / 改竄 payload / 不正 JSON 行 / 末尾空行の各テスト。
        🔵 信頼性レベル: 要件定義 §2.1 動作 1-4（不正 JSON を包む方式・空行スキップは 🟡）
        """
        text = self._path.read_text(encoding="utf-8")
        for line in text.splitlines():
            # 【空行スキップ】: 末尾の空行・改行のみの行は正常な追記の副産物として許容 🟡
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                # 【エラー処理】: 壊れた JSON 行も破損として明示エラー化（握り潰さない）🟡
                raise LedgerIntegrityError(
                    f"ledger 行が不正な JSON です（無修復・ファイル無変更）: {self._path}"
                ) from exc
            # 【エントリ再構築】: ファイルの値そのままで LedgerEntry を復元（改竄検出のため）🔵
            self._entries.append(
                LedgerEntry(
                    index=row["index"],
                    kind=row["kind"],
                    payload=row["payload"],
                    prev_hash=row["prev_hash"],
                    hash=row["hash"],
                )
            )
        # 【全チェーン検証】: hash 不整合・prev_hash 断裂・index 不連続を検出したら明示エラー 🔵
        if not verify_entries(self._entries):
            raise LedgerIntegrityError(
                f"ledger のハッシュチェーンが破損しています（無修復・ファイル無変更）: {self._path}"
            )

    def append(self, kind: str, payload: Mapping[str, Any]) -> LedgerEntry:
        """【機能概要】: エントリを 1 件構築し、JSONL へ 1 行を追記モードで書き込む。

        【実装方針】: in-memory Ledger.append と同一意味論 + "a" モード追記 I/O のみ
        （"w" / "r+" / seek+write / truncate は使わない — NFR-203）。
        【テスト対応】: TC-106-01/02/07、初回 append でのファイル新規作成、決定論。
        🔵 信頼性レベル: 要件定義 §2.2 / ledger.py Ledger.append と同一規約
        """
        # 【チェーン連結】: index 連番と直前 hash（空なら GENESIS）を決定 🔵
        index = len(self._entries)
        prev_hash = self._entries[-1].hash if self._entries else GENESIS_HASH
        # 【隔離コピー】: 呼び出し側の後続変更から payload を隔離（in-memory 版と同一）🔵
        payload = dict(payload)
        entry = LedgerEntry(
            index=index,
            kind=kind,
            payload=payload,
            prev_hash=prev_hash,
            hash=_compute_hash(index, kind, payload, prev_hash),
        )
        # 【追記 I/O】: "a" モードで to_dict() の JSON 1 行 + 改行のみを書く（既存バイト列不変）🔵
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry.to_dict()) + "\n")
        self._entries.append(entry)
        return entry

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        """【機能概要】: 全エントリの不変タプル（in-memory Ledger.entries と同一契約）。🔵"""
        return tuple(self._entries)

    def verify(self) -> bool:
        """【機能概要】: ハッシュチェーンの整合性を検証する。

        【実装方針】: ledger.py の verify_entries へ委譲し in-memory 版と単一ロジック共有。🔵
        """
        return verify_entries(self._entries)


class PersistentSnapshotStore:
    """【機能概要】: 非破壊 revert 対応スナップショットストアの JSONL 永続版。

    【実装方針】: in-memory SnapshotStore (store/snapshot.py) と同一契約
    (save / load / revert / snapshots / current_id) を持ち、phases は同層 serialization
    の phase_to_dict / phase_from_dict で相互変換する。書き込みは追記モード ("a") による
    1 snapshot = 1 行の JSONL 追記のみ (NFR-203)。削除・上書き・改変 API は一切持たない
    (P2 / REQ-401)。revert は前方履歴を消さず現在位置を移すだけで JSONL へは追記しない。
    【テスト対応】: tests/test_persistent_store.py の PersistentSnapshotStore 13 件
    (N-01〜N-06 / E-01〜E-02 / B-01〜B-05)。
    🔵 信頼性レベル: 要件定義 §2.1-2.7 / interfaces.py L284-292 / snapshot.py に直接依拠
    """

    def __init__(
        self, path: str | os.PathLike[str], ledger: Ledger | None = None
    ) -> None:
        """【機能概要】: JSONL パスを開き、既存 snapshot 行を復元して内部状態を再構築する。

        【実装方針】: 読み取りのみ（新規パスではファイルを作らず、初回 save で作成）。
        各行を phase_from_dict で復元し、current_id は最後に save された snapshot の id
        （=最新）に設定して後続 save の連番継続・parent_id 連結を成立させる。
        【テスト対応】: 再オープン roundtrip / 連番継続 / 空・新規パス / current_id 復元。
        🔵 信頼性レベル: 要件定義 §2.1（PathLike 許容・current_id を最新 save に設定は 🟡）
        """
        # 【状態初期化】: in-memory SnapshotStore と同じ保持形式（list + index + current_id）🔵
        self._path = Path(path)
        self._snaps: list[Snapshot] = []
        self._index: dict[str, Snapshot] = {}
        self._current_id: str | None = None
        self._ledger = ledger
        # 【既存ファイル読込】: 存在する場合のみ復元。不在なら空ストア（初回 save で作成）🔵
        if self._path.exists():
            self._load()

    def _load(self) -> None:
        """【機能概要】: JSONL 各行を Snapshot に再構築し内部状態・current_id を復元する。

        【実装方針】: 1 行 = 1 snapshot。phases を phase_from_dict で型復元し、末尾空行は
        正常な追記の副産物としてスキップする。ファイルへは一切書き込まない（読み取りのみ）。
        【テスト対応】: save → 再オープン → load/revert の等価復元、連番継続、id 列復元。
        🔵 信頼性レベル: 要件定義 §2.1 動作 1-4（末尾空行スキップは 🟡）
        """
        text = self._path.read_text(encoding="utf-8")
        for line in text.splitlines():
            # 【空行スキップ】: 末尾の空行・改行のみの行は破損扱いにせず無視 🟡
            if not line.strip():
                continue
            row = json.loads(line)
            # 【phases 型復元】: dict 配列を phase_from_dict で PhaseInstance タプルへ 🔵
            phases = tuple(phase_from_dict(p) for p in row["phases"])
            snap = Snapshot(
                id=row["id"],
                label=row["label"],
                phases=phases,
                parent_id=row["parent_id"],
            )
            self._snaps.append(snap)
            self._index[snap.id] = snap
            # 【current_id 継続】: 最後まで回ると最新 save の id が残る（連番・親連結の起点）🟡
            self._current_id = snap.id

    def save(self, phases: tuple[PhaseInstance, ...], *, label: str) -> Snapshot:
        """【機能概要】: Snapshot を構築し JSONL へ 1 行を追記モードで書き込む。

        【実装方針】: in-memory SnapshotStore.save と同一意味論 + "a" モード追記 I/O のみ
        （"w" / "r+" / seek+write / truncate は使わない — NFR-203）。phases は phase_to_dict
        で dict 化して 1 行にまとめる。ledger 注入時は snapshot_save を記録する。
        【テスト対応】: roundtrip / 連番継続 / ledger 記録 / 追記のみ成長 / 空 phases。
        🔵 信頼性レベル: 要件定義 §2.2 / snapshot.py L30-48 と同一契約
        """
        # 【連番採番】: 復元数 + 新規から snap-{i:04d} を発番、親は現在位置 🔵
        snap_id = f"snap-{len(self._snaps):04d}"
        snap = Snapshot(
            id=snap_id, label=label, phases=tuple(phases), parent_id=self._current_id
        )
        # 【行スキーマ】: 1 snapshot = 1 行。phases を phase_to_dict で JSON-safe dict 化 🔵
        row = {
            "id": snap_id,
            "label": label,
            "parent_id": snap.parent_id,
            "phases": [phase_to_dict(p) for p in snap.phases],
        }
        # 【追記 I/O】: "a" モードで 1 行 + 改行のみ書く（既存バイト列不変 / 不在なら新規作成）🔵
        with open(self._path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        self._snaps.append(snap)
        self._index[snap_id] = snap
        self._current_id = snap_id
        # 【監査記録】: ledger 注入時は in-memory SnapshotStore と同一 payload を記録 🔵
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
        """【機能概要】: 復元済み Snapshot を返す（未知 id は KeyError）。

        🔵 信頼性レベル: 要件定義 §2.3 / snapshot.py L50-51 と同一。
        """
        return self._index[snapshot_id]

    def revert(self, snapshot_id: str) -> tuple[PhaseInstance, ...]:
        """【機能概要】: 現在位置を指定 snapshot へ移し phases を返す（非破壊）。

        【実装方針】: 前方履歴を消さず current_id を移すだけで、snapshot JSONL へは
        追記しない（revert は状態遷移でありデータ追加ではない）。ledger 注入時のみ
        snapshot_revert を記録する。未知 id は KeyError（in-memory と同一縮退）。
        【テスト対応】: 再オープン revert / ファイル無変更 / ledger 記録 / 前方履歴保持。
        🔵 信頼性レベル: 要件定義 §2.4 / snapshot.py L53-61 と同一契約
        """
        snap = self._index[snapshot_id]  # 未知 id は KeyError
        self._current_id = snapshot_id
        # 【監査記録】: ledger 注入時のみ snapshot_revert を記録（snapshot JSONL は無変更）🔵
        if self._ledger is not None:
            self._ledger.append(
                "snapshot_revert",
                {"snapshot_id": snapshot_id, "label": snap.label},
            )
        return snap.phases

    @property
    def snapshots(self) -> tuple[Snapshot, ...]:
        """【機能概要】: 現在の全 Snapshot の不変タプル（in-memory と同一）。🔵"""
        return tuple(self._snaps)

    @property
    def current_id(self) -> str | None:
        """【機能概要】: 現在位置の snapshot id（未 save/未 revert なら None）。🔵"""
        return self._current_id
