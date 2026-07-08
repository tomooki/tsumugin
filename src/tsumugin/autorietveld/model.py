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
    weight: float = 1.0
    """ヒストグラム重み係数 (GSAS-II wtFactor)。joint 精密化で相対重みを調整する (既定 1.0)。
    XRD 支配の joint で中性子を上げ重みする等に用いる (>1 で当該ヒストグラムを優先)。"""
    absorption: float = 0.0
    """試料吸収係数の初期値 (GSAS-II Sample Parameters Absorption)。TOF 中性子は λ(=TOF) 依存吸収を
    与える (μR 相当)。recipe の "absorption" 段階で解放する。既定 0.0 (無補正)。"""

    def to_dict(self) -> dict[str, object]:
        """MCP JSON 露出用に素の型 dict へ写像する (Enum→値文字列, tuple→list)。"""
        return {
            "data_path": self.data_path,
            "instrument_path": self.instrument_path,
            "radiation": self.radiation.value,
            "geometry": self.geometry.value,
            "data_format": self.data_format,
            "bank": self.bank,
            "two_theta_limits": list(self.two_theta_limits)
            if self.two_theta_limits is not None
            else None,
            "temperature": self.temperature,
            "weight": self.weight,
            "absorption": self.absorption,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "HistogramSpec":
        """to_dict の逆写像 (往復同型)。未知の余分キーは無視する。"""
        limits = d.get("two_theta_limits")
        return cls(
            data_path=str(d["data_path"]),
            instrument_path=str(d["instrument_path"]),
            radiation=Radiation(d["radiation"]),
            geometry=Geometry(d["geometry"]),
            data_format=str(d.get("data_format", "GSAS")),
            bank=d.get("bank"),  # type: ignore[arg-type]
            two_theta_limits=(float(limits[0]), float(limits[1])) if limits is not None else None,
            temperature=d.get("temperature"),  # type: ignore[arg-type]
            weight=float(d.get("weight", 1.0)),
            absorption=float(d.get("absorption", 0.0)),
        )


@dataclass(frozen=True)
class PhaseSpec:
    """相 1 つの入力仕様 (実構造)。

    :param structure_path: 構造ファイル (CIF / GSAS .EXP)
    :param phase_name: プロジェクト内の相名
    :param format_hint: GSAS-II importer ヒント ("CIF"/"EXP")
    :param mixed_occupancy_groups: 混合占有サイトを共有する原子ラベルの組の列。
        例: (("Fe1","Al1"), ("Al2","Fe2")) — 各組で占有率和=1 制約と Uiso 等価制約を張る
    :param free_occupancy_labels: 単独で占有率を解放する原子ラベル (和=1 制約なし)。
        例: ("Ow",) — 部分占有のゼオライト水など、共有サイトでない部分占有サイトの占有率精密化に用いる
    :param occupancy_equiv_groups: 占有率を等値拘束する原子ラベルの組の列 (add_EquivConstr)。
        例: (("O1","DO11","DO12"),) — D₂O の D 占有率を親水 O に等値し 1 変数として精密化する
        (水フラクションと D 量を連動させる)
    :param free_uiso_labels: Uiso を解放する原子ラベルを限定する (空なら uiso 段階で全原子を解放)。
        例: ("Cu","Na1","Na2","O1","O3","Ow") — 重原子/可動陽イオン/水のみ Uiso 解放し、軽元素
        framework (C/N) や占有率 0 のゴースト原子の Uiso 発散/負値を防ぐ (heavy-atom + 無秩序構造の定石)
    :param temperature: 相の想定温度 (K)。ヒストグラム間温度差の吸収判定に用いる
    """

    structure_path: str
    phase_name: str
    format_hint: str = "CIF"
    mixed_occupancy_groups: tuple[tuple[str, ...], ...] = ()
    free_occupancy_labels: tuple[str, ...] = ()
    occupancy_equiv_groups: tuple[tuple[str, ...], ...] = ()
    free_uiso_labels: tuple[str, ...] = ()
    position_equiv_groups: tuple[tuple[str, ...], ...] = ()
    temperature: float | None = None

    def to_dict(self) -> dict[str, object]:
        """MCP JSON 露出用に素の型 dict へ写像する (tuple 組→list of list)。"""
        return {
            "structure_path": self.structure_path,
            "phase_name": self.phase_name,
            "format_hint": self.format_hint,
            "mixed_occupancy_groups": [list(g) for g in self.mixed_occupancy_groups],
            "free_occupancy_labels": list(self.free_occupancy_labels),
            "occupancy_equiv_groups": [list(g) for g in self.occupancy_equiv_groups],
            "free_uiso_labels": list(self.free_uiso_labels),
            "position_equiv_groups": [list(g) for g in self.position_equiv_groups],
            "temperature": self.temperature,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "PhaseSpec":
        """to_dict の逆写像 (往復同型)。未知の余分キーは無視する。"""
        groups = d.get("mixed_occupancy_groups") or ()
        free_occ = d.get("free_occupancy_labels") or ()
        equiv = d.get("occupancy_equiv_groups") or ()
        free_uiso = d.get("free_uiso_labels") or ()
        return cls(
            structure_path=str(d["structure_path"]),
            phase_name=str(d["phase_name"]),
            format_hint=str(d.get("format_hint", "CIF")),
            mixed_occupancy_groups=tuple(tuple(str(a) for a in g) for g in groups),
            free_occupancy_labels=tuple(str(a) for a in free_occ),
            occupancy_equiv_groups=tuple(tuple(str(a) for a in g) for g in equiv),
            free_uiso_labels=tuple(str(a) for a in free_uiso),
            position_equiv_groups=tuple(
                tuple(str(a) for a in g) for g in (d.get("position_equiv_groups") or ())
            ),
            temperature=d.get("temperature"),  # type: ignore[arg-type]
        )


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
    # 【観測点数】: 精密化に用いた実観測点数 (全ヒストグラム総和, レンジ制限反映)。chi2/BIC の
    #   dof・n 罰に用いる。末尾・既定 0 で後方互換 (0=未設定; 利用側は代替源へフォールバック) 🔵 Issue #16
    n_obs: int = 0
    # 【相分率】: 相名→相分率 (先頭ヒストグラムの HAP Scale 和=1 正規化)。単相は {name: 1.0}。
    #   逐次解析 (M9) が新相の有意性判定・転移推定に用いる。末尾・既定空 dict で後方互換 🔵 M9
    phase_fractions: Mapping[str, float] = field(default_factory=dict)
    # 【残差パターン】: 先頭ヒストグラムの (2θ, Yobs−Ycalc, σ)。精密化レンジ内のみ。既存相で説明でき
    #   ない未モデル強度 = 未同定の少数相の寄与。σ は計数統計の標準偏差 (GSAS 重み由来)。逐次解析の
    #   **残差 S/N による2相目追加判定** (ノイズと本物の未説明ピークを区別) に用いる。既定空で後方互換 🔵
    residual_two_theta: tuple[float, ...] = ()
    residual_intensity: tuple[float, ...] = ()
    residual_sigma: tuple[float, ...] = ()
