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

from .absorption import AbsorberLayer


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

    @property
    def is_xray(self) -> bool:
        return self in (Radiation.XRAY_LAB, Radiation.XRAY_SYNCHROTRON)


class Geometry(Enum):
    """回折計ジオメトリ。試料変位パラメータの種別選択に用いる。"""

    BRAGG_BRENTANO = "bragg_brentano"  # 反射: sample displacement (Shift)
    DEBYE_SCHERRER = "debye_scherrer"  # 透過/毛細管: sample X,Y displacement


@dataclass(frozen=True)
class InstrumentProfile:
    """標準試料 (NIST SRM 674b CeO2 等) から実測した CW 装置分解能関数 (不変)。

    試料精密化で装置プロファイル (U,V,W/X,Y/SH·L) を固定するための値。装置由来と試料由来の広がりが
    相関して分離できない問題 (Issue #38) への対処で、`HistogramSpec.instrument_profile` に与える。

    :param values: GSAS キー→値 (U,V,W,X,Y,SH/L,Zero の部分集合)
    :param source_rwp: 抽出精密化の最終 Rwp (出典の質; 既定 NaN)
    :param wavelength: 波長 Å (任意・記録用)
    """

    values: Mapping[str, float]
    source_rwp: float = float("nan")
    wavelength: float | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "values": {str(k): float(v) for k, v in self.values.items()},
            "source_rwp": self.source_rwp,
            "wavelength": self.wavelength,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "InstrumentProfile":
        raw = d.get("values", {}) or {}
        return cls(
            values={str(k): float(v) for k, v in dict(raw).items()},  # type: ignore[union-attr]
            source_rwp=float(d.get("source_rwp", float("nan"))),  # type: ignore[arg-type]
            wavelength=(float(d["wavelength"]) if d.get("wavelength") is not None else None),
        )


@dataclass(frozen=True)
class CalibrationResult:
    """標準試料からの波長・ゼロ点較正の結果 (Issue #61)。

    格子を認証値に固定した標準試料精密化で得た**実効波長** (Lam)・ゼロ点・装置プロファイルを保持する。
    実効波長は装置ラインシェイプ (非対称) のバイアスを吸収した値で、同一光学系の試料に適用すると
    系統シフトが相殺し正しい格子定数を与える。

    :param wavelength: 較正後の実効波長 [Å]
    :param wavelength_init: 入力波長 [Å]
    :param zero: 較正後のゼロ点 [°2θ]
    :param profile: 装置プロファイル (U,V,W,X,Y,SH/L の部分集合)
    :param reference_cell: 固定した認証格子 (a,b,c,α,β,γ)
    :param source_rwp: 較正精密化の最終 Rwp [%]
    """

    wavelength: float
    wavelength_init: float
    zero: float
    profile: Mapping[str, float]
    reference_cell: tuple[float, float, float, float, float, float]
    source_rwp: float = float("nan")

    @property
    def ppm_shift(self) -> float:
        """入力波長からの相対シフト [ppm] (実効波長 − 入力) / 入力 × 1e6。"""
        if self.wavelength_init == 0.0:
            return float("nan")
        return 1e6 * (self.wavelength - self.wavelength_init) / self.wavelength_init

    def to_instrument_profile(self) -> "InstrumentProfile":
        """装置プロファイル + Zero を `InstrumentProfile` に写す (試料精密化での固定用)。"""
        vals = {str(k): float(v) for k, v in self.profile.items()}
        vals["Zero"] = float(self.zero)
        return InstrumentProfile(values=vals, source_rwp=self.source_rwp,
                                 wavelength=self.wavelength)

    def to_dict(self) -> dict[str, object]:
        return {
            "wavelength": self.wavelength,
            "wavelength_init": self.wavelength_init,
            "zero": self.zero,
            "profile": {str(k): float(v) for k, v in self.profile.items()},
            "reference_cell": list(self.reference_cell),
            "source_rwp": self.source_rwp,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "CalibrationResult":
        cell = tuple(float(v) for v in d["reference_cell"])  # type: ignore[arg-type]
        return cls(
            wavelength=float(d["wavelength"]),  # type: ignore[arg-type]
            wavelength_init=float(d["wavelength_init"]),  # type: ignore[arg-type]
            zero=float(d["zero"]),  # type: ignore[arg-type]
            profile={str(k): float(v) for k, v in dict(d.get("profile", {})).items()},  # type: ignore[union-attr]
            reference_cell=cell,  # type: ignore[arg-type]
            source_rwp=float(d.get("source_rwp", float("nan"))),  # type: ignore[arg-type]
        )


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
    :param excluded_regions: 使用域内部で除外する 2θ 区間の列 (Issue #53)。寄生線/アーチファクト等、
        データファイル自体を事前マスクせずに内部区間を精密化から除外したい場合に用いる。GSAS-II の
        ``hist.data['Limits']`` は ``[(orig_min, orig_max), [used_lo, used_hi], *excluded_pairs]`` の
        構造を持ち、``set_refinements({'Exclude': ...})`` キーは存在しない (実測で例外)。本フィールドは
        engine が使用域設定後に ``[lo, hi]`` を直接 append する。既定 () (除外なし; 後方互換)。
    :param temperature: 測定温度 (K)。複数ヒストグラム間の温度差吸収判定に用いる
    """

    data_path: str
    instrument_path: str
    radiation: Radiation
    geometry: Geometry
    data_format: str = "GSAS"
    bank: int | None = None
    two_theta_limits: tuple[float, float] | None = None
    excluded_regions: tuple[tuple[float, float], ...] = ()
    temperature: float | None = None
    weight: float = 1.0
    """ヒストグラム重み係数 (GSAS-II wtFactor)。joint 精密化で相対重みを調整する (既定 1.0)。
    XRD 支配の joint で中性子を上げ重みする等に用いる (>1 で当該ヒストグラムを優先)。"""
    absorption: float = 0.0
    """試料吸収係数の初期値 (GSAS-II Sample Parameters Absorption)。TOF 中性子は λ(=TOF) 依存吸収を
    与える (μR 相当)。recipe の "absorption" 段階で解放する。既定 0.0 (無補正)。"""
    instrument_profile: "InstrumentProfile | None" = None
    """標準試料から実測した装置分解能関数 (Issue #38)。指定時、engine は値を instprm に seed し、
    段階解放で U,V,W/X,Y/SH·L を**解放しない** (固定)。試料広がりは size/mustrain が担う。既定 None
    (未指定なら従来どおり装置プロファイルを解放; 後方互換)。"""
    profile_bounds: "Mapping[str, tuple[float | None, float | None]] | None" = None
    """装置パラメータの物理拘束 {GSAS キー: (min, max)} (None で片側自由)。指定時、engine が
    GSAS parmMin/parmMax を登録する (占有率 [0,1] 拘束と同機構)。分解能抽出で U,W,X,Y≥0 を課し、
    相関非物理解 (負の Lorentzian) を避け**転写可能** (全域 FWHM 正) な分解能を得るのに用いる。
    既定 None (拘束なし; 後方互換)。"""
    absorber_layers: tuple[AbsorberLayer, ...] = ()
    """固定吸収体レイヤー (operando/in-situ セルの電解液層・窓材, Issue #54)。ビーム路に固定
    厚みの吸収体があると回折ビーム路長が 2θ 依存 (平板透過: t/cos2θ) になり、高角ほど強く
    吸収される。engine がヒストグラム読込直後に `absorption.apply_absorption_correction` で
    Yobs/weight へ角度依存の補正を掛ける (定数部はスケール因子と縮退するため含めない)。
    既定 () (補正なし; 後方互換)。"""

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
            "excluded_regions": [list(r) for r in self.excluded_regions]
            if self.excluded_regions
            else [],
            "temperature": self.temperature,
            "weight": self.weight,
            "absorption": self.absorption,
            "instrument_profile": self.instrument_profile.to_dict()
            if self.instrument_profile is not None
            else None,
            "profile_bounds": {k: [lo, hi] for k, (lo, hi) in self.profile_bounds.items()}
            if self.profile_bounds is not None
            else None,
            "absorber_layers": [layer.to_dict() for layer in self.absorber_layers],
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
            excluded_regions=tuple(
                (float(r[0]), float(r[1])) for r in (d.get("excluded_regions") or ())
            ),
            temperature=d.get("temperature"),  # type: ignore[arg-type]
            weight=float(d.get("weight", 1.0)),
            absorption=float(d.get("absorption", 0.0)),
            instrument_profile=(
                InstrumentProfile.from_dict(d["instrument_profile"])  # type: ignore[arg-type]
                if d.get("instrument_profile") is not None
                else None
            ),
            profile_bounds=(
                {
                    str(k): (
                        (None if v[0] is None else float(v[0])),
                        (None if v[1] is None else float(v[1])),
                    )
                    for k, v in dict(d["profile_bounds"]).items()  # type: ignore[arg-type]
                }
                if d.get("profile_bounds") is not None
                else None
            ),
            absorber_layers=tuple(
                AbsorberLayer.from_dict(x) for x in (d.get("absorber_layers") or ())  # type: ignore[arg-type]
            ),
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
    occupancy_sum_groups: tuple[tuple[str, ...], ...] = ()
    frozen_coord_labels: tuple[str, ...] = ()
    """座標を**解放しない**原子ラベル (coords 段で除外)。剛体的に理想幾何へ固定したい原子
    (例: 無秩序水の D/H を O–D=0.96Å の初期幾何に据置き orientation のみを別途評価する) に用いる。
    占有率/Uiso の解放とは独立 (座標だけ凍結)。既定 () (従来どおり一般位置は全解放)。"""
    refine_cell: bool = True
    """当該相の格子 (単位胞) を精密化するか (Issue #47)。``False`` なら engine の "cell" 段で
    Cell 解放をスキップし、格子を初期値に固定する。副相/不純物相の相分率が 0 近傍に落ちると
    無拘束の格子が発散し、``_cells_physical`` ガードが段全体を revert して主相の格子精密化まで
    巻き添えにする問題を回避する。格子が既知参照と一致する副相 (例 hollandite 不純物) に用いる。
    既定 True (全相解放; 後方互換)。"""
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
            "occupancy_sum_groups": [list(g) for g in self.occupancy_sum_groups],
            "frozen_coord_labels": list(self.frozen_coord_labels),
            "refine_cell": self.refine_cell,
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
            occupancy_sum_groups=tuple(
                tuple(str(a) for a in g) for g in (d.get("occupancy_sum_groups") or ())
            ),
            frozen_coord_labels=tuple(str(a) for a in (d.get("frozen_coord_labels") or ())),
            refine_cell=bool(d.get("refine_cell", True)),
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
    # 【相分率】: 相名→**HAP Scale を和=1 に正規化した値** (先頭ヒストグラム)。単相は {name: 1.0}。
    #   ⚠ これは**重量分率ではない**。Scale は単位胞の散乱能に対する比例係数であり、相間で単位胞質量
    #   が異なると重量分率と大きく乖離する (例 K₂Mn[Fe(CN)₆] の cubic 1103.4 vs tetra 517.8 で ~2.1x)。
    #   **出版値には `phase_weight_fractions` (GSAS-II calcMassFracs 由来の質量重み分率) を使うこと**。
    #   本フィールドは逐次解析 (M9) の新相の有意性判定・転移推定という**相対比較**用途に限る 🔵 M9
    phase_fractions: Mapping[str, float] = field(default_factory=dict)
    # 【残差パターン】: 先頭ヒストグラムの (2θ, Yobs−Ycalc, σ)。精密化レンジ内のみ。既存相で説明でき
    #   ない未モデル強度 = 未同定の少数相の寄与。σ は計数統計の標準偏差 (GSAS 重み由来)。逐次解析の
    #   **残差 S/N による2相目追加判定** (ノイズと本物の未説明ピークを区別) に用いる。既定空で後方互換 🔵
    residual_two_theta: tuple[float, ...] = ()
    residual_intensity: tuple[float, ...] = ()
    residual_sigma: tuple[float, ...] = ()
    # 【内省フィールド (refine-loop-diagnostics REQ-001)】: 残差以外の系統誤差を診断が「見える」ように
    #   露出する。すべて末尾追加・既定空で後方互換 (旧構築/スタブは空 → diagnose は該当シグナルを立てない,
    #   EDGE-001 縮退)。GSAS runner が gpx から算出して詰める。numpy コアは値を消費するのみ。🔵
    # per-atom: 相名→原子ラベル→値。Uiso 発散/負値 (REQ-105)・占有率 [0,1] 逸脱の検出源。
    atom_uiso: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    atom_occupancy: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    # per-histogram (索引順): 現吸収値・現プロファイル値 (Zero/alpha/X/Y/U/V/W 等)。
    hist_absorption: tuple[float, ...] = ()
    hist_profile: tuple[Mapping[str, float], ...] = ()
    # per-histogram メトリクス: obs/calc FWHM 比 (幅ずれ REQ-103)・残差左右非対称度 (非対称 REQ-101)・
    #   系統 obs>calc 度 (選択配向 REQ-102)・背景極値数 (背景 overfit REQ-104)。
    peak_width_ratio: tuple[float, ...] = ()
    asymmetry_metric: tuple[float, ...] = ()
    intensity_bias_metric: tuple[float, ...] = ()
    bg_extrema: tuple[int, ...] = ()
    # 【出版用の標準不確かさ (esd)】: esd を伴わない精密化値は出版できないため、GSAS-II が共分散行列
    #   から算出した su を露出する。すべて末尾追加・既定空 dict で後方互換 (旧構築サイトは空に縮退)。
    #   共分散が得られない場合 (未収束/精密化未実行) も空 dict へ縮退し**例外を送出しない**
    #   (「バックエンド失敗は例外でなく結果に縮退」の不変条件)。🔵
    # 相名→格子 esd。`refined_cells` と**同一レイアウト** (a,b,c,α,β,γ の 6 要素; 体積は含まない)。
    #   出典 `G2Phase.get_cell_and_esd()` (第 2 要素)。固定パラメータ (対称拘束された角度等) は 0.0。
    cell_esd: Mapping[str, tuple[float, float, float, float, float, float]] = field(
        default_factory=dict
    )
    # 相名→**重量 (質量) 分率**。出典 `G2PwdrData.ComputeMassFracs()` → GSAS-II
    #   `GSASIIstrMath.calcMassFracs` (wtSum=Σ mass[p]*Scale[p]; WgtFrac[j]=mass[j]*Scale[j]/wtSum)。
    #   mass は精密化された占有率を反映するため**フレーム毎に GSAS が算出**する (静的 CIF 質量では不可)。
    #   単相は {name: 1.0} (自明)。定量相分析の**出版値はこちら** (`phase_fractions` ではない)。
    phase_weight_fractions: Mapping[str, float] = field(default_factory=dict)
    # 相名→重量分率の esd。calcMassFracs が Jacobian + 共分散行列から伝播した値。単相は {name: 0.0}
    #   (自明な 1.0 に不確かさはない)。分率非精密化/共分散なしなら空 dict。
    phase_weight_fraction_esd: Mapping[str, float] = field(default_factory=dict)
