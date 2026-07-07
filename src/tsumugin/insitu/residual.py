"""残差 S/N 判定の後方互換シム (実体は `tsumugin.reference.significance` へ昇格, M11)。

M11 で `residual_significance` を `reference.significance` へ移設した (単相/多相統一同定 `identify_pattern`
が使うため; import 方向 reference ⇏ insitu を保つ)。既存の `from tsumugin.insitu.residual import ...`
呼び出しを壊さないよう本モジュールが re-export する。
"""

from __future__ import annotations

from ..reference.significance import ResidualSignificance, residual_significance

__all__ = ["ResidualSignificance", "residual_significance"]
