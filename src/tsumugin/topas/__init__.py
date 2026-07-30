"""Bruker TOPAS を第 2 の精密化バックエンドとして駆動する境界 (M12)。

`tsumugin.autorietveld` が GSAS-II を駆動するのに対し、本パッケージは同じ中立入力
(`PhaseSpec` / `HistogramSpec` / `RefinementStage`) から **TOPAS の INP を生成し、コンソール
実行体 ``tc.exe`` を起動し、出力を `AutoRietveldResult` へ写像する**。段の受理/revert 方針は
`autorietveld.stagepolicy` を GSAS 経路と共用するため、ガードレールの改善は両バックエンドに効く。

TOPAS には COM/OLE も Python API も存在しない (実測) ため、自動化経路は
``tc <INP のベース名> ["macro Name { value }"]`` のバッチ実行のみである。

コアは stdlib + numpy のみで、TOPAS 未導入でも ``import tsumugin.topas`` は成功する。
``tc.exe`` を実際に起動する経路のみが :class:`~tsumugin.errors.TopasUnavailableError` を送出する。
"""

from __future__ import annotations

from .availability import (
    TOPAS_ENV_VARS,
    describe,
    require_tc_exe,
    resolve_tc_exe,
    topas_available,
    topas_home,
)

__all__ = [
    "TOPAS_ENV_VARS",
    "describe",
    "require_tc_exe",
    "resolve_tc_exe",
    "topas_available",
    "topas_home",
]
