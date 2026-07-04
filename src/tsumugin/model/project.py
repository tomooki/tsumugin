"""プロジェクト・データセット・フレーム階層 (仕様 §4)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Probe = Literal["xray", "neutron_cw", "neutron_tof"]


@dataclass(frozen=True)
class TofBankParams:
    """TOF マルチバンクの DIFC/DIFA/ZERO 較正パラメータ (バンク単位, REQ-002/FR-241)。

    HistogramRef に ``bank_params`` として末尾追加される器。既存フィールドは不変 (後方互換)。
    """

    difc: float  # 【DIFC】: d 間隔→TOF 変換係数
    difa: float = 0.0  # 【DIFA】: 二次項 (既定 0)
    zero: float = 0.0  # 【ZERO】: TOF ゼロ点 (既定 0)


@dataclass(frozen=True)
class HistogramRef:
    """1 本のヒストグラム参照 (マルチヒストグラム対応の器, FR-241)。"""

    probe: Probe
    data_ref: str
    instprm_ref: str | None = None
    bank_id: int | None = None
    bank_params: TofBankParams | None = None


@dataclass(frozen=True)
class Frame:
    """時系列の 1 フレーム。single データセットでは 1 フレームのみ。"""

    id: str
    index: int
    histograms: tuple[HistogramRef, ...] = ()
    axis_value: float | None = None


@dataclass(frozen=True)
class Dataset:
    id: str
    kind: Literal["single", "sequence"]
    frames: tuple[Frame, ...] = ()
    sequence_axis: Literal[
        "none", "time", "temperature", "potential", "capacity", "custom"
    ] = "none"


@dataclass(frozen=True)
class Project:
    id: str
    datasets: tuple[Dataset, ...] = ()
    final_selection_mode: Literal["agent", "human"] = "agent"
