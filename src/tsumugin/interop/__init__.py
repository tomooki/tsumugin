"""外部ソフト形式 ↔ GSAS-II 変換境界 (interop)。

RIETAN-FP / Z-Rietveld (Z-Code, J-PARC iMATERIA TOF) など外部粉末解析ソフトの回折計・データ形式を
読み取り、GSAS-II が取り込める形式 (``.xye`` / ``.instprm`` / TOF FXYE) へ**変換 (writer)** する。
ベンダー別サブモジュール構成で、将来 FullProf (``.pcr``) / GSAS (``.prm``) / Jana を ``interop.<vendor>``
として追加できる。numpy-only (GSAS-II 非依存) で決定論的。

公開 API:
    - RIETAN: :func:`parse_rietan_int` / :func:`load_rietan_int` / :func:`convert_rietan_int`
    - Z-Rietveld: :func:`parse_igor_tof` / :func:`load_igor_tof` / :func:`convert_igor_tof` /
      :func:`parse_zdiffractometer` / :class:`ZDiffractometer`
    - 装置: :func:`write_gsas_instprm`
"""

from __future__ import annotations

from tsumugin.interop.instrument import write_gsas_instprm
from tsumugin.interop.prepare import prepare_histograms
from tsumugin.interop.rietan import (
    convert_rietan_int,
    load_rietan_int,
    parse_rietan_int,
)
from tsumugin.interop.zrietveld import (
    ZDiffractometer,
    convert_igor_tof,
    load_igor_tof,
    parse_igor_tof,
    parse_zdiffractometer,
)

__all__ = [
    "ZDiffractometer",
    "convert_igor_tof",
    "convert_rietan_int",
    "load_igor_tof",
    "load_rietan_int",
    "parse_igor_tof",
    "parse_rietan_int",
    "parse_zdiffractometer",
    "prepare_histograms",
    "write_gsas_instprm",
]
