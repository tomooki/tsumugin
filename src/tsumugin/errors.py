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
