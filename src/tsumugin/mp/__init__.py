"""Materials Project 相ライブラリ供給元 (仕様 §5 FR-100〜105)。

コア (numpy) のみで import 可能。pymatgen / mp-api (optional extra ``mp``) は各処理の
呼び出し時点で遅延 import し、未導入なら ``MPUnavailableError`` へ縮退する。相同定コア
(``tsumugin.reference``) はこの供給元を ``ReferenceProvider`` として受け取る。
"""

from __future__ import annotations

from .client import MPClient, MPEntry, MPRestClient
from .provider import MPReferenceProvider
from .xrd import group_equivalent, simulate_reference_peaks

__all__: list[str] = [
    "MPClient",
    "MPEntry",
    "MPReferenceProvider",
    "MPRestClient",
    "group_equivalent",
    "simulate_reference_peaks",
]
