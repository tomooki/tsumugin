"""M7 自動 Rietveld の入出力データモデル (frozen dataclass / Enum)。

GSAS-II 非依存の純データ層。実 CIF/相ファイル + 実データ + 装置パラメータを記述する
入力仕様 (HistogramSpec/PhaseSpec) と、段階解放レシピ (RefinementStage)、
実行結果 (StageResult/AutoRietveldResult/ValidityReport) を提供する。

信頼性: 🔵 設計 architecture.md §2.1、T1 プロトタイプで駆動確認済み。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


class Radiation(Enum):
    """放射源。背景/プロファイル既定と前方計算の分岐に用いる。"""

    XRAY_LAB = "xray_lab"
    XRAY_SYNCHROTRON = "xray_synchrotron"
    NEUTRON_CW = "neutron_cw"
    NEUTRON_TOF = "neutron_tof"

    @property
    def is_neutron(self) -> bool:
        return self in (Radiation.NEUTRON_CW, Radiation.NEUTRON_TOF)

    @property
    def is_tof(self) -> bool:
        return self is Radiation.NEUTRON_TOF


class Geometry(Enum):
    """回折計ジオメトリ。試料変位パラメータの種別選択に用いる。"""

    BRAGG_BRENTANO = "bragg_brentano"  # 反射: sample displacement (Shift)
    DEBYE_SCHERRER = "debye_scherrer"  # 透過/毛細管: sample X,Y displacement


@dataclass(frozen=True)
class HistogramSpec:
    """観測ヒストグラム 1 本の入力仕様。

    :param data_path: 観測データファイル (.xra/.gsa/.fxye/.xye 等)
    :param instrument_path: 装置パラメータファイル (.prm/.instprm)
    :param radiation: 放射源
    :param geometry: 回折計ジオメトリ
    :param data_format: GSAS-II importer 種別 ("GSAS"/"FXYE"/"XYE")
    :param bank: TOF の複数フレーム/バンク選択 (1 始まり, None なら既定)
    :param two_theta_limits: 精密化に用いる下限/上限 (None なら全域)
    :param temperature: 測定温度 (K)。複数ヒストグラム間の温度差吸収判定に用いる
    """

    data_path: str
    instrument_path: str
    radiation: Radiation
    geometry: Geometry
    data_format: str = "GSAS"
    bank: int | None = None
    two_theta_limits: tuple[float, float] | None = None
    temperature: float | None = None


@dataclass(frozen=True)
class PhaseSpec:
    """相 1 つの入力仕様 (実構造)。

    :param structure_path: 構造ファイル (CIF / GSAS .EXP)
    :param phase_name: プロジェクト内の相名
    :param format_hint: GSAS-II importer ヒント ("CIF"/"EXP")
    :param mixed_occupancy_sites: 占有率制約対象のサイトラベル群 (例 ("Fe2","Al3"))
    :param temperature: 相の想定温度 (K)。ヒストグラム間温度差の吸収判定に用いる
    """

    structure_path: str
    phase_name: str
    format_hint: str = "CIF"
    mixed_occupancy_sites: tuple[str, ...] = ()
    temperature: float | None = None


@dataclass(frozen=True)
class RefinementStage:
    """段階解放 1 段の宣言的記述。

    :param label: 段階ラベル (例 "S1 cell+shift")
    :param flags: GSAS-II への解放指示 (宣言的辞書、engine が解釈)
    :param note: 補足 (ジオメトリ/制約由来など)
    """

    label: str
    flags: Mapping[str, object] = field(default_factory=dict)
    note: str = ""


@dataclass(frozen=True)
class StageResult:
    """段階実行の結果メトリクス。"""

    label: str
    rwp: float
    gof: float
    n_params: int
    converged: bool
    reverted: bool = False
    note: str = ""


@dataclass(frozen=True)
class ValidityReport:
    """物理的妥当性ゲートの判定結果。

    :param passed: 全必須チェック合格か
    :param checks: (項目名, 合格, 詳細) のタプル列
    :param warnings: 非致命の警告
    """

    passed: bool
    checks: tuple[tuple[str, bool, str], ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class AutoRietveldResult:
    """自動 Rietveld 解析の総合結果。"""

    stage_results: tuple[StageResult, ...]
    final_rwp: float
    final_gof: float
    refined_cells: Mapping[str, tuple[float, float, float, float, float, float]]
    validity: ValidityReport
    gpx_path: str = ""
