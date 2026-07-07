"""M10 アンカー基準双方向 operando 逐次解析 (`tsumugin.insitu.anchor`)。

信頼フレーム (アンカー) 起点の双方向精密化 + 区間総 bic 最小の crossover 選定で、転移域の少数相を
頑健に追跡する。M9 前方単一パス (`insitu.engine`) の脆さ (初期フレーム依存 + 転移域セル汚染) を
一般化して解消する。numpy-only コア + GSAS/pymatgen 遅延 import。FR-330。
"""

from __future__ import annotations

from .model import Anchor, AnchorConfig, CrossoverChoice, Segment, SegmentPass

__all__ = [
    "Anchor",
    "AnchorConfig",
    "CrossoverChoice",
    "Segment",
    "SegmentPass",
]
