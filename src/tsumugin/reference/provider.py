"""相ライブラリ供給元の境界 (``ReferenceProvider`` Protocol)。🔵 FR-100/101

元素系を受け取り候補 ``ReferencePhase`` 群を返す供給元を抽象化する。実装は Materials Project
境界 (``tsumugin.mp``) / ユーザー CIF / テストダブル (in-memory) など。コアの相同定エンジン
(``identify_phases``) は本 Protocol にのみ依存し、供給元の実体 (mp-api/pymatgen) を引き込まない。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from .model import ReferencePhase


@runtime_checkable
class ReferenceProvider(Protocol):
    """相ライブラリ供給元。元素系 → 候補相群。🔵 FR-101"""

    def fetch(self, elements: Sequence[str]) -> Sequence[ReferencePhase]:
        """``elements`` を含み得る候補相群を返す。

        Args:
            elements: 探索対象の元素記号列 (例 ``["Li", "Fe", "P", "O"]``)。

        Returns:
            候補 ``ReferencePhase`` の並び。元素系 / hull による絞り込みは供給元側で
            前処理してもよいが、``identify_phases`` 側でも冪等に再適用される。
        """
        ...
