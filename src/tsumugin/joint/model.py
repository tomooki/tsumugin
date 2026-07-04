"""joint 精密化の入力・結果型 (REQ-004/006/009 / interfaces.py joint/model 節)。

全て frozen dataclass。構造共有 (phases + shared_free_params) とヒスト独立
(per_histogram_free_params) を分離保持し、集約結果 (aggregate) は既存 rank/evidence
経路と互換な ``RefinementResult`` へ持たせる (D1)。

np.ndarray を持つ ``JointHistogram`` の等価比較は曖昧になりうるため、既存
``RefinementModel`` に倣い eq はデフォルト (eq=True) のまま。比較はフィールド個別か
``np.array_equal`` で行う運用とする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

import numpy as np

from ..backends.base import RefinementResult
from ..model import PhaseInstance
from ..model.project import Probe


@dataclass(frozen=True)
class JointHistogram:
    """joint 精密化 1 ヒスト分の入力 (2θ/I/w + probe + ヒスト重み)。🔵 REQ-004/FR-242"""

    two_theta: np.ndarray  # 【観測 2θ 軸】
    intensity: np.ndarray  # 【観測強度】
    probe: Probe = "xray"  # 【プローブ種別】: xray/neutron_cw/neutron_tof (REQ-001)
    weights: np.ndarray | None = None  # 【観測重み】: None は統計重み 1/σ² (REQ-008)
    hist_weight: float = 1.0  # 【ヒストグラム重み】: 経験重み上書き用スカラ (既定 統計 1.0)
    bank_id: int | None = None  # 【TOF バンク識別】: マルチバンク時 (REQ-002)


@dataclass(frozen=True)
class JointRefinementModel:
    """joint 精密化への入力。構造共有・ヒスト独立を分離保持する。🔵 REQ-004/FR-242

    【共有】: 構造パラメータ (格子/座標/占有率/ADP) は全ヒストで共有する ``phases`` +
      ``shared_free_params`` ("phase{i}.lattice.a" 等)。
    【独立】: scale/背景/プロファイルは ``per_histogram_free_params[k]`` でヒストごとに独立解放する。
    """

    phases: tuple[PhaseInstance, ...]  # 【共有構造相】
    histograms: tuple[JointHistogram, ...]  # 【ヒスト群・順序が決定論キー】 (REQ-402)
    shared_free_params: frozenset[str] = field(default_factory=frozenset)  # 【共有 free】
    # 【ヒスト独立 free】: index k -> 当該ヒストで解放する free_params (scale/bg/profile)
    per_histogram_free_params: Mapping[int, frozenset[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class PerHistogramMetrics:
    """joint 結果のヒスト別指標。🔵 REQ-006/009"""

    hist_index: int
    probe: Probe
    rwp: float  # 【ヒスト別 Rwp】
    chi2: float  # 【ヒスト別 χ² (失敗ヒストは inf)】 (EDGE-001)
    scale: float  # 【ヒスト独立 scale】
    sigma_source: Literal["covariance", "hist_weight"]  # 【σ 由来明示】 (REQ-009/NFR-107)


@dataclass(frozen=True)
class JointRefinementResult:
    """joint 精密化結果の型付き集約 (集約 RefinementResult + ヒスト別)。🔵 REQ-006

    【集約】: ``aggregate`` は共有構造 phases (±σ)・Σχ²・結合 Rwp を単一 RefinementResult に集約し、
      既存 rank/evidence 経路と互換にする (D1)。ヒスト別 Rwp/scale は ``per_histogram`` と
      ``aggregate.globals`` ("hist0.rwp" 等) の双方に持たせる。
    """

    aggregate: RefinementResult  # 【単一集約結果 (rank/evidence へ渡す)】 (REQ-006)
    per_histogram: tuple[PerHistogramMetrics, ...]  # 【ヒスト別指標 (順序=入力順)】 (REQ-402)
    warnings: tuple[str, ...] = ()  # 【σ 由来 / 失敗ヒスト明示】 (REQ-009/EDGE-001)
