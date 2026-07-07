"""M10 アンカー基準双方向 operando 逐次解析 (`tsumugin.insitu.anchor`)。

信頼フレーム (アンカー) 起点の双方向精密化 + 区間総 bic 最小の crossover 選定で、転移域の少数相を
頑健に追跡する。M9 前方単一パス (`insitu.engine`) の脆さ (初期フレーム依存 + 転移域セル汚染) を
一般化して解消する。numpy-only コア + GSAS/pymatgen 遅延 import。FR-330。
"""

from __future__ import annotations

from .engine import run_anchored_sequential
from .extract import anchor_confidence, extract_anchors
from .model import Anchor, AnchorConfig, CrossoverChoice, Segment, SegmentPass
from .segment import build_segments, refine_segment_backward, refine_segment_forward
from .select import assemble_path, frame_bic, select_crossover

__all__ = [
    "Anchor",
    "AnchorConfig",
    "CrossoverChoice",
    "Segment",
    "SegmentPass",
    "anchor_confidence",
    "assemble_path",
    "build_segments",
    "extract_anchors",
    "frame_bic",
    "refine_segment_backward",
    "refine_segment_forward",
    "run_anchored_sequential",
    "select_crossover",
]
