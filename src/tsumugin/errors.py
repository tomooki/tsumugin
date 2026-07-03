"""ドメイン例外階層。"""

from __future__ import annotations


class TsumuginError(Exception):
    """Tsumugin 由来の例外の基底。"""


class GuardrailError(TsumuginError):
    """ガードレール(FR-210)が回復不能な状態を検知したときに送出。"""


class EscalationRequired(TsumuginError):
    """自動リトライ上限(FR-212, 既定3回)に達し人間/Triage へのエスカレーションが必要。"""


class GSASUnavailableError(TsumuginError):
    """GSAS-II (GSASIIscriptable) が未導入の環境で GSASIIBackend を要求したとき。"""


class LedgerIntegrityError(TsumuginError):
    """永続 ledger (JSONL) の破損を検出したときに送出 (EDGE-003 / NFR-105)。

    ハッシュ不整合・prev_hash 断裂・index 不連続・不正 JSON 行を再オープン時に検出する。
    検出時にファイルの修復・上書き・切り詰めは一切行わない（無修復 / P2）。
    """


class SnapshotIntegrityError(TsumuginError):
    """永続 snapshot (JSONL) の破損 (不正 JSON 行・必須キー欠落) を検出したときに送出。

    ``LedgerIntegrityError`` と対称の fail-loud。検出時にファイルの修復・上書き・
    切り詰めは一切行わない (無修復 / P2)。
    """


class WebUIUnavailableError(TsumuginError):
    """optional extra ``web`` (fastapi/uvicorn) 未導入の環境で Web UI を要求したとき。

    ``GSASUnavailableError`` と対称の「available + 専用例外」パターン。``create_app`` /
    ``serve`` の遅延 import 契約 (D6): ``import tsumugin.webui.app`` 自体は web 未導入でも成功し、
    ``create_app`` / ``serve`` の呼び出し時点でのみ本例外を送出して extra 導入手順を案内する。
    """
