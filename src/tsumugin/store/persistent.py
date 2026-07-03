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
from .ledger import GENESIS_HASH, LedgerEntry, _compute_hash, verify_entries


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
