"""M7 自動 Rietveld の入出力データモデル (frozen dataclass / Enum)。

GSAS-II 非依存の純データ層。実 CIF/相ファイル + 実データ + 装置パラメータを記述する
入力仕様 (HistogramSpec/PhaseSpec) と、段階解放レシピ (RefinementStage)、
実行結果 (StageResult/AutoRietveldResult/ValidityReport) を提供する。

信頼性: 🔵 設計 architecture.md §2.1、T1 プロトタイプで駆動確認済み。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Mapping

from .._json import finite_or_none
from .absorption import AbsorberLayer
from .diagnostics import WeakVariable


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


def _opt_float(value: object) -> "float | None":
    """``None`` を保ったまま float 化する (JSON spec の「無効」と「0」を潰さない)。"""
    return None if value is None else float(value)  # type: ignore[arg-type]


@dataclass(frozen=True)
class StabilityOptions:
    """安定性最優先の自動 Rietveld で使う**診断ゲート**の設定 (WS-1, stable-auto-rietveld)。

    **既定はすべて無効 = 現行と完全に同一の挙動**。`run_auto_rietveld(stability=...)` に明示的に
    渡したときだけ有効になる (T1〜T4/CaTeO3/NaCuHCF の既存 gated テストを壊さないため)。
    情報源はすべて `autorietveld.diagnostics.read_diagnostics` の 1 箇所 (REQ-SAR-105)。

    :param require_convergence: 段の受理条件に**収束判定**を加える (REQ-SAR-101)。
        GSAS の「改善した」は ``Max shft/sig`` が 258 でも成立する (実測) ため、Rwp の改善だけを
        受理条件にすると**収束していない段**が通過する。未収束なら追加サイクルで回し直し、
        それでも収束しなければ revert する。判定材料が無い (共分散なし) 場合は
        `RefinementDiagnostics.is_converged` が ``None`` を返し、**fail open** で受理する
        (情報が無いことを「未収束」と断じない)。
    :param max_shift_esd: 収束とみなす ``max |shift| / esd`` の上限 (既定 1.0)。
    :param extra_cycles: 未収束時に**同じ段のまま**追加で回す精密化の最大回数 (既定 1)。
        0 なら追加サイクルなしで即 revert 判定。
    :param detect_noop_stages: 段の適用後に ``n_params`` が増えず rwp/gof が**ビット同一**なら
        「この段は何もしていない」と ledger に警告を残す (REQ-SAR-102)。**revert はしない** —
        検出のみ。Rwp が動かないことを「改善しなかった」と解釈すると無言失敗と区別が付かない
        (P-SAR-2) ので、区別できる形で台帳に残すのが目的。
    ---- 弱い変数 (``esd >= |値|``) の扱い (REQ-SAR-103) ----

    **軸は「凍結は判断、記録は観測」** (P-SAR-3 の「提案 ≠ 適用」と同じ規律)。⚠ 旧版はこれを
    ``prune_weak_vars`` 1 個で表し、**受理された段のたびに永続凍結**していた。それは誤りだった:

    1. **途中段階の esd は「決定不能」の証拠ではなく「まだ決まっていない」だけ**である。座標が
       まだずれている段階で Uiso を解放すれば esd が大きいのは当然で、そこで凍結すると
       後段で座標が正しくなり Uiso が本来決まるようになっても**二度と解放されない**
       (不可逆なラチェット。実測: 拘束下で ``n_params`` が S2 で 7 → 3 まで落ちた)。
    2. **発火条件が逆だった** — ``not reverted`` = 物事がうまく行っている段でだけ刈っていた。
       プルーニングが要るのは悪条件で収束しない/特異行列のときである。
    3. 毎段凍結を必須にしていた根拠 (「``dlg`` スタブで GSAS 自身の自動パラメータ削除を失う」)
       は WS-2 の実測で**誤り**と判明した (requirements.md F5 / architecture.md D4-b:
       その再試行は ``'Hessian' not in deriv type`` の分岐にしかなく既定では到達しない。
       弱い変数のドロップは ``HessianLSQ.dropTerms`` にあり ``dlg`` を見ない)。

    :param record_weak_vars: **各段**で弱い変数を ledger (``m7_stage_weak_vars``) に
        **記録するだけ** — 凍結しない (観測)。revert された段でも記録する (その段が壊れた
        理由の一次証拠だから)。
    :param report_undetermined: **最終収束後**に残った弱い変数を「**決まらなかったパラメータ**」
        として結果 (`AutoRietveldResult.undetermined_parameters`) と ledger
        (``m7_undetermined``) に載せる。**弱い変数はそれ自体が価値ある所見**である
        (「このデータではこのパラメータは決まらない」= NaCuHCF の占有率発散が Ow 必要性の
        決め手になったのと同じ種類の診断信号)。**凍結して隠すのではなく報告する。**
    :param polish_frozen_undetermined: **最終研磨** (opt-in)。``report_undetermined`` が拾った
        変数を凍結して**もう 1 回だけ**精密化し、再報告する。要 ``report_undetermined``。
        ⚠ 有効にすると**出版値が「一部を凍結した fit」のものになる**ので、結果からそれと
        判別できるようにしてある (`AutoRietveldResult.final_polish` / `frozen_parameters` /
        末尾に付く ``final polish`` 段)。既定 False。
    :param prune_weak_vars_each_stage: **旧 ``prune_weak_vars``** — 受理された段のたびに弱い
        変数を永続凍結する (上記 1.2. の不可逆ラチェット)。削除ではなく **opt-in の逃げ道**
        として残す: 条件数が本当に進行を妨げるデータでは母数を毎段落とすしかないことがある。
        **既定 False で、通常は使わない** (まず ``rescue_freeze_on_failure`` を試すこと)。
        ⚠ 名前を変えたのは意味を変えたからである (旧名の JSON は未知キーとして大声で落ちる)。
    :param rescue_freeze_on_failure: **救済** — 段が (追加サイクルを使っても) 収束しない、
        または ``Rvals['SVD0'] > 0`` (特異な変数があった = 悪条件の直接証拠) のときに限り、
        **最弱の変数を凍結して再試行**する。GSAS 自身の ``HessianLSQ.dropTerms`` と同じ思想で、
        「うまく行っている段では刈らず、行き詰まったときだけ母数を落とす」。既定 False。
    :param rescue_max_freeze: 救済 1 回あたりに凍結する変数の最大数 (既定 1 = 最弱のみ)。
        まとめて刈ると「本当はどれが効いたのか」が分からなくなるので既定は 1。
    :param rescue_max_rounds: 1 段あたりの救済の最大回数 (既定 2)。0 で救済なし。
    :param esd_ratio_exempt_tokens: ``esd/|値|`` の比が**意味を持たない**変数名トークン
        (部分一致)。既定の ``dAx/dAy/dAz`` は座標そのものではなく**そのサイクルでのシフト量**
        で、GSAS は精密化のたびに 0 へ初期化する (``GSASIIstrIO``:1732) ため、
        **収束するほど分母が 0 に近づき比が発散する** = 「よく決まっている座標ほど
        『決まらなかった』と報告される」構造的な偽陽性になる。**最終判定だけにしても消えない**
        (むしろ収束点で最も強く出る) ので除外は維持する。除外された変数は捨てずに
        `AutoRietveldResult.undetermined_exempt` に別列で載る (何を見なかったかを隠さない)。
        ⚠ 旧名 ``prune_exempt_tokens`` — 凍結だけでなく**報告**からも外すので改名した。
    :param record_correlations: 共分散から測った ``|r| >= corr_threshold`` の変数ペアを ledger に
        記録する (REQ-SAR-104)。**この段階では検出と記録のみ**で自動凍結はしない (同時解放の
        回避はレシピ側の判断: Phase 2)。
    :param corr_threshold: 高相関とみなす ``|r|`` の閾値 (既定 0.9)。
    :param max_recorded_pairs: ledger に載せる相関ペアの上限。ペア数は O(n²) で増えるため、
        大きい配列を台帳へ流さない (② 境界の「大きい配列は ① 側で報告に畳む」と同じ規律)。

    ---- WS-2 拘束・境界 (REQ-SAR-201/202/203) ----

    ⚠ **構造パラメータ (占有率・Uiso・座標) に箱拘束を張るフィールドは意図的に存在しない**
    (P-SAR-1)。異常値は「モデルの誤り」の診断信号であり、クランプすると握り潰す。実証:
    NaCuHCF の model5 は占有率が Na>1 / O<0 に発散したこと自体が「Ow が必要」の決め手で、
    [0,1] に拘束していれば model5/model6 を判別できなかった。ここへ構造パラメータを足さないこと。

    :param bound_cell: 格子を**初期値の ±この割合**に閉じ込める (例 0.05 = ±5%)。GSAS が
        精密化するのは逆格子計量成分 ``A0..A5`` なので、常に正である対角 3 成分 ``A0,A1,A2``
        (= a*², b*², c*²) にのみ箱を張る (`bounds.cell_box_bounds`)。None (既定) で無効。
    :param bound_displacement: 試料変位 (``Shift`` / ``DisplaceX,Y``, µm) の絶対値上限。
        変位は格子と強く相関し、暴走すると「格子が変位を吸収した自己整合な誤解」を作る
        (Rwp には現れない)。None (既定) で無効。
    :param bound_size_strain: 等方 Size/Mustrain に**正値性**と十分緩い上限を張る。
        ``Size;i`` は幅の式で分母に入るため 0/負は発散 = 数値的事故。異方成分 (``;a`` /
        generalized) は符号が物理的に自由なので**対象にしない**。既定 False。
    :param min_size: 等方サイズ下限 (µm)。既定 1e-3 µm = 10 Å (結晶と呼べる下限を更に下回る)。
    :param max_size: 等方サイズ上限 (µm)。既定 1e4 µm = 1 cm — 粉末回折で分離できるサイズ
        (< 数 µm) を**桁で上回る**。低い cap は境界不安定を生み偽の「改善せず」を作るため
        (NaCuHCF 実測: ADP cap を上げたら ND 18.0→14.7%)、上限は必ず余裕を持たせる。
    :param min_mustrain: 等方微小歪み下限 (×10⁻⁶)。既定 1e-3。
    :param max_mustrain: 等方微小歪み上限 (×10⁻⁶)。既定 1e5 = 10% 歪み (実在値の桁上)。
    :param enable_restraints: restraint (bond/ChemComp) を **``dlg`` スタブ経由で χ² に入れる**
        (REQ-SAR-203)。既定 False。本バージョンの GSAS-II は headless で penalty を目的関数から
        外す (`restraint_dlg` docstring) ため、有効にしない限り登録した拘束は**効かない**。
        ⚠ **``report_undetermined`` との併用が必須**: 拘束は実質的に母数を増やすので、
        「どのパラメータが決まらなかったか」を**見ないまま**回すことは認めない。単独指定は
        ``ValueError``。**旧版は ``prune_weak_vars`` (毎段凍結) を必須にしていたが、その根拠
        (GSAS の自動削除を失う) は D4-b の実測で誤りと判明したため、必須要件を「見ること」
        だけに落とした** — 拘束下で毎段凍結すると母数が不可逆に痩せる実害の方が大きい。

        **有効時の Rwp の扱い**: GSAS の ``Rvals['Rwp']`` は penalty 込みの値になるが、engine は
        `diagnostics.data_term_rwp` で**データ項だけの Rwp** を復元し、段の受理/revert も
        `StageResult.rwp` / `AutoRietveldResult.final_rwp` もそちらを使う。penalty 込みの生値は
        `rwp_penalized` / `final_rwp_penalized` に分けて載る。拘束は「引く力」であって適合の
        悪化ではないので、penalty の増減で段を revert してはならない (分離前は bond weight 1e5 で
        Rwp 3558 = **全段 revert** した)。
    """

    require_convergence: bool = False
    max_shift_esd: float = 1.0
    extra_cycles: int = 1
    detect_noop_stages: bool = False
    # --- 弱い変数 (esd >= |値|) の扱い: 記録 (観測) / 報告 / 凍結 (判断) を分ける ---
    record_weak_vars: bool = False
    report_undetermined: bool = False
    polish_frozen_undetermined: bool = False
    prune_weak_vars_each_stage: bool = False
    rescue_freeze_on_failure: bool = False
    rescue_max_freeze: int = 1
    rescue_max_rounds: int = 2
    esd_ratio_exempt_tokens: tuple[str, ...] = ("dAx", "dAy", "dAz")
    record_correlations: bool = False
    corr_threshold: float = 0.9
    max_recorded_pairs: int = 10
    # --- WS-2 拘束・境界 ---
    bound_cell: "float | None" = None
    bound_displacement: "float | None" = None
    bound_size_strain: bool = False
    min_size: float = 1.0e-3
    max_size: float = 1.0e4
    min_mustrain: float = 1.0e-3
    max_mustrain: float = 1.0e5
    enable_restraints: bool = False

    def __post_init__(self) -> None:
        """「見ないまま処置する」構成を**大声で**拒む (黙って片肺運転させない)。

        * ``enable_restraints``: 拘束は実質的に母数を増やすので、**決まらなかったパラメータを
          報告しない**まま回すことは認めない (REQ-SAR-203)。
        * ``polish_frozen_undetermined``: 研磨は「報告された変数を凍結する」操作なので、
          報告そのものが無効なら**凍結対象が定義されない**。

        いずれも ② では `StabilityOptions.from_dict` の ``ValueError`` → error dict に落ちる。
        """
        if self.enable_restraints and not self.report_undetermined:
            raise ValueError(
                "enable_restraints=True には report_undetermined=True が必須です "
                "(REQ-SAR-203: 拘束で増えた母数のうち何が決まらなかったかを必ず報告する)"
            )
        if self.polish_frozen_undetermined and not self.report_undetermined:
            raise ValueError(
                "polish_frozen_undetermined=True には report_undetermined=True が必須です "
                "(凍結対象は報告された『決まらなかったパラメータ』そのものである)"
            )

    @property
    def needs_diagnostics(self) -> bool:
        """**段ごとに**共分散を読む必要があるか。

        全部無効なら `read_diagnostics` を **1 度も呼ばない** — 既定経路に新しい失敗点を
        持ち込まないため (非回帰契約)。最終判定だけの項目 (`needs_final_diagnostics`) は
        **含めない** — 毎段の読み出しを要さないものを混ぜると、報告を足しただけで段ごとの
        コストと失敗点が増える。
        """
        return bool(
            self.require_convergence
            or self.record_correlations
            or self.record_weak_vars
            or self.prune_weak_vars_each_stage
            or self.rescue_freeze_on_failure
        )

    @property
    def needs_final_diagnostics(self) -> bool:
        """**最終収束後に 1 度だけ**共分散を読む必要があるか (REQ-SAR-103 の報告/研磨)。"""
        return bool(self.report_undetermined or self.polish_frozen_undetermined)

    @property
    def has_box_bounds(self) -> bool:
        """箱拘束 (REQ-SAR-201) を 1 つでも張るか。

        共分散 (`needs_diagnostics`) とは**別の情報源** (``Controls['parmFrozen']``) を使うので
        独立に判定する。全部無効なら Controls を 1 度も触らない = 現行と同一。
        """
        return bool(
            self.bound_cell is not None
            or self.bound_displacement is not None
            or self.bound_size_strain
        )

    def to_dict(self) -> dict[str, object]:
        """JSON spec へ (② 境界の往復用)。"""
        return {
            "require_convergence": self.require_convergence,
            "max_shift_esd": self.max_shift_esd,
            "extra_cycles": self.extra_cycles,
            "detect_noop_stages": self.detect_noop_stages,
            "record_weak_vars": self.record_weak_vars,
            "report_undetermined": self.report_undetermined,
            "polish_frozen_undetermined": self.polish_frozen_undetermined,
            "prune_weak_vars_each_stage": self.prune_weak_vars_each_stage,
            "rescue_freeze_on_failure": self.rescue_freeze_on_failure,
            "rescue_max_freeze": self.rescue_max_freeze,
            "rescue_max_rounds": self.rescue_max_rounds,
            "esd_ratio_exempt_tokens": list(self.esd_ratio_exempt_tokens),
            "record_correlations": self.record_correlations,
            "corr_threshold": self.corr_threshold,
            "max_recorded_pairs": self.max_recorded_pairs,
            "bound_cell": self.bound_cell,
            "bound_displacement": self.bound_displacement,
            "bound_size_strain": self.bound_size_strain,
            "min_size": self.min_size,
            "max_size": self.max_size,
            "min_mustrain": self.min_mustrain,
            "max_mustrain": self.max_mustrain,
            "enable_restraints": self.enable_restraints,
        }

    @classmethod
    def from_dict(cls, d: "Mapping[str, object] | None") -> "StabilityOptions":
        """JSON spec から組み立てる (② 到達可能性: ③ は JSON しか送れない)。

        **未知キーは ``ValueError``** — 黙って無視すると「有効にしたつもりのゲートが効いて
        いない」という最悪の静かな失敗になる (② ツールは例外を error dict へ縮退させる)。
        ``None``/空 dict は「診断ゲートなし」= 既定 (現行と同一挙動)。
        """
        if not d:
            return cls()
        known = {f.name for f in fields(cls)}
        unknown = sorted(set(d) - known)
        if unknown:
            raise ValueError(
                f"stability に未知のキーがあります: {unknown} (既知: {sorted(known)})"
            )
        tokens = d.get("esd_ratio_exempt_tokens")
        return cls(
            require_convergence=bool(d.get("require_convergence", False)),
            max_shift_esd=float(d.get("max_shift_esd", 1.0)),  # type: ignore[arg-type]
            extra_cycles=int(d.get("extra_cycles", 1)),  # type: ignore[arg-type]
            detect_noop_stages=bool(d.get("detect_noop_stages", False)),
            record_weak_vars=bool(d.get("record_weak_vars", False)),
            report_undetermined=bool(d.get("report_undetermined", False)),
            polish_frozen_undetermined=bool(d.get("polish_frozen_undetermined", False)),
            prune_weak_vars_each_stage=bool(d.get("prune_weak_vars_each_stage", False)),
            rescue_freeze_on_failure=bool(d.get("rescue_freeze_on_failure", False)),
            rescue_max_freeze=int(d.get("rescue_max_freeze", 1)),  # type: ignore[arg-type]
            rescue_max_rounds=int(d.get("rescue_max_rounds", 2)),  # type: ignore[arg-type]
            esd_ratio_exempt_tokens=(
                cls.esd_ratio_exempt_tokens  # type: ignore[union-attr]
                if tokens is None
                else tuple(str(t) for t in tokens)  # type: ignore[union-attr]
            ),
            record_correlations=bool(d.get("record_correlations", False)),
            corr_threshold=float(d.get("corr_threshold", 0.9)),  # type: ignore[arg-type]
            max_recorded_pairs=int(d.get("max_recorded_pairs", 10)),  # type: ignore[arg-type]
            # WS-2: None (無効) と 0.0 (「幅ゼロの箱」= 誤設定) を潰さないため float() は
            # 値がある場合のみ通す。
            bound_cell=_opt_float(d.get("bound_cell")),
            bound_displacement=_opt_float(d.get("bound_displacement")),
            bound_size_strain=bool(d.get("bound_size_strain", False)),
            min_size=float(d.get("min_size", 1.0e-3)),  # type: ignore[arg-type]
            max_size=float(d.get("max_size", 1.0e4)),  # type: ignore[arg-type]
            min_mustrain=float(d.get("min_mustrain", 1.0e-3)),  # type: ignore[arg-type]
            max_mustrain=float(d.get("max_mustrain", 1.0e5)),  # type: ignore[arg-type]
            enable_restraints=bool(d.get("enable_restraints", False)),
        )


@dataclass(frozen=True)
class StageResult:
    """段階実行の結果メトリクス。

    :param rwp: **データ項のみの Rwp** — 「観測パターンにどれだけ合っているか」。段の受理/revert
        判定に使うのもこの値である。拘束を χ² に入れていない既定経路では GSAS の
        ``Rvals['Rwp']`` と**ビット同一**なので、従来の意味は一切変わらない。
    :param rwp_penalized: restraint penalty を**含む** GSAS 生の ``Rvals['Rwp']``。
        ``StabilityOptions.enable_restraints`` で拘束を χ² に入れたときだけ非 ``None`` になる
        (``None`` = penalty なし = ``rwp`` と同義)。**出版値ではない** — 拘束の重みに依存する
        目的関数の値であって、データへの合わなさではない。拘束がどれだけ引いているかを
        ``rwp_penalized`` と ``rwp`` の差として読むための診断値として残す。
    """

    label: str
    rwp: float
    gof: float
    n_params: int
    converged: bool
    reverted: bool = False
    note: str = ""
    rwp_penalized: "float | None" = None


@dataclass(frozen=True)
class FinalPolish:
    """最終研磨 (opt-in, REQ-SAR-103) の記録 — **出版値がどう作られたか**を明示する。

    研磨は「決まらなかったパラメータを凍結して 1 回だけ精密化し直す」操作なので、有効にすると
    ``final_rwp`` 以下は**一部の変数を凍結した fit** の値になる。黙って値だけ変えると、
    拘束なしの run と同じ列に並べて比較できなくなるため、**何を凍結して Rwp がどう動いたか**を
    結果に必ず残す。

    :param applied: 研磨後の状態を採用したか (False = 研磨しなかった / revert した)
    :param frozen: 研磨のために凍結した変数名 (= 研磨前に「決まらなかった」と報告された変数)
    :param rwp_before: 研磨前のデータ項 Rwp (段列の最終値)
    :param rwp_after: 研磨後のデータ項 Rwp。**凍結は自由度を減らすので普通わずかに悪化する** —
        悪化を理由に revert しないのが研磨の目的であり、コストはこの 2 値の差として見せる
    :param reverted: 研磨を試みたが破棄したか (非有限 Rwp / 格子崩壊 / GSAS 失敗)
    :param reason: revert あるいは非実施の理由 (空文字 = 通常適用)
    """

    applied: bool
    frozen: tuple[str, ...] = ()
    rwp_before: float = float("inf")
    rwp_after: float = float("inf")
    reverted: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "applied": self.applied,
            "frozen": list(self.frozen),
            "rwp_before": finite_or_none(self.rwp_before),
            "rwp_after": finite_or_none(self.rwp_after),
            "reverted": self.reverted,
            "reason": self.reason,
        }


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


#: 格子の標準不確かさ (a,b,c,α,β,γ)。``refined_cells`` と同一レイアウト (体積は含まない)。
#: **要素の `None` は「この精密化では決まっていない」** (格子を解放していない相・非有限値) を意味し、
#: ``0.0`` は「対称拘束で厳密に固定」(mono の α/γ = 90°) を意味する — 両者を潰さないための `| None`。
CellEsd = tuple[
    float | None, float | None, float | None, float | None, float | None, float | None
]


def coerce_cell_esd(values: object) -> CellEsd:
    """任意の 6 要素列を `CellEsd` へ正規化する (``None`` と非有限を潰さない共有ヘルパ)。

    **`float(x)` を直接使わないための関数**: `cell_esd` の要素は「格子を解放していない/値が無い」を
    表す ``None`` を取り得るため、素朴な ``tuple(float(x) for x in esd)`` は ``TypeError`` になる。
    貫通経路 (M10 `anchor.extract`/`anchor.segment`) が各自で float 化していると、**その TypeError を
    避けるために 0.0 へ丸める**誘惑が生まれる — それが本 esd の捏造そのものである。

    :param values: 6 要素の数値/None 列 (長さ 6 以外・非数値は `ValueError`/`TypeError`)
    :returns: 有限値は float、``None``/非有限は ``None``
    """
    items = list(values)  # type: ignore[call-overload]
    if len(items) != 6:
        raise ValueError(f"cell_esd は 6 要素 (a,b,c,α,β,γ) である必要があります: {values!r}")
    out = tuple(finite_or_none(x) for x in items)
    return out  # type: ignore[return-value]


#: 分率座標 (x,y,z)。**GSAS 原子行から読んだ値**であって ``dAx`` (シフト) ではない。
CoordTriple = tuple[float, float, float]

#: 座標の標準不確かさ (x,y,z)。``CellEsd`` と**同型の 3 状態**:
#: ``>0.0`` = ``dA{axis}`` の sig 由来の su / ``0.0`` = **対称拘束で厳密に固定** /
#: ``None`` = **この精密化では決まっていない**。三者を潰さないための ``| None``。
CoordEsd = tuple["float | None", "float | None", "float | None"]


def coerce_coord_esd(values: object) -> CoordEsd:
    """任意の 3 要素列を `CoordEsd` へ正規化する (`coerce_cell_esd` の 3 要素版)。

    存在理由も同じ: 要素が ``None`` を取り得るため素朴な ``tuple(float(x) for x in esd)`` は
    ``TypeError`` になり、**それを避けるために 0.0 へ丸める誘惑**が生まれる。0.0 は既に
    「対称拘束で固定」という別の意味を持っているので、丸めた瞬間に情報が壊れる。
    """
    items = list(values)  # type: ignore[call-overload]
    if len(items) != 3:
        raise ValueError(f"coord_esd は 3 要素 (x,y,z) である必要があります: {values!r}")
    out = tuple(finite_or_none(x) for x in items)
    return out  # type: ignore[return-value]


@dataclass(frozen=True)
class AutoRietveldResult:
    """自動 Rietveld 解析の総合結果。

    :param final_rwp: **データ項のみの Rwp** (= ``stage_results[-1].rwp``)。**これが出版値**であり、
        restraint の有無に関わらず「観測パターンへの合わなさ」だけを表す。拘束を χ² に入れて
        いない既定経路では GSAS の ``Rvals['Rwp']`` と**ビット同一** (意味は変わっていない)。
        penalty 込みの値が要るときは `final_rwp_penalized` を見ること。
    :param final_gof: GSAS の ``Rvals['GOF']`` を**そのまま**。拘束を χ² に入れた場合は
        ``√(χ²/(Nobs + RestraintTerms − Nvars))`` = **penalty 込みのまま**である。

        **これは分離し忘れではなく意図した非対称**である。Rwp は定義上「観測プロファイルとの
        一致度」なので拘束項を混ぜてはならないが、GOF は拘束付き精密化では**拘束項を観測と
        自由度の双方に数えるのが慣行**であり、GSAS の式 (分母に ``RestraintTerms`` を足す)
        はその慣行どおりに書かれている。加えて、GOF を penalty 込みで残すと**拘束がデータと
        争っている状態が値に現れる** (実測: S–O ターゲットを 2.3 Å に誤設定 + weight 1e5 で
        ``final_rwp`` 33.07 に対し ``final_gof`` 1641.8)。データ項 Rwp だけを見ていると
        見落とすこの警報を、わざと潰さない。
    """

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
    #   が異なると重量分率と乖離する。乖離の**大きさ**は単位胞質量比 (例 K₂Mn[Fe(CN)₆] の
    #   cubic 1103.4 / tetra 517.8 amu = 2.13 倍) と**各フレームの分率**で決まるため**フレーム毎に
    #   違い**、単一の換算係数は無い (実測 tetra: 65.6 Scale% → 47.2 wt% [1.39 倍]、系列全体で
    #   1.39-1.62 倍)。**Scale に係数を掛けて wt% にはできない**。
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
    # 【ヒストグラム別の格子オフセット ε】: 相名 → ``"<軸>_h<索引>"`` → 値 (TOPAS の
    #   `hydrostatic_strain` / GSAS の HStrain Dij に相当)。**構造としての格子は 1 つ**
    #   (`refined_cells`) で、ε は「このヒストグラムでの実効セルは共有セルの (1+ε) 倍」を表す。
    #   温度差の吸収がどれだけ働いたかは**この値でしか読めない** — 出さないと段が効いた理由も、
    #   ε が箱に張り付いた (非物理) ことも結果から見えない。既定空 (張っていない/未対応経路)。
    cell_strain: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
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
    #   出典 `G2Phase.get_cell_and_esd()` (第 2 要素)。**3 状態を区別する** (レビュー第5巡 HIGH):
    #   ``>0.0`` = 解放して精密化した項の su / ``0.0`` = **対称拘束で厳密に固定** (mono の α/γ=90°;
    #   真の陳述) / ``None`` = **この精密化では決まっていない** (格子を解放していない相 —
    #   `PhaseSpec.refine_cell=False`・`auto_freeze_minor_cells`・セル段の revert・未精密化)。
    #   相ごと欠落 = 抽出できなかった。**凍結セルに 0.0 を捏造しない** — GSAS は凍結セルでも例外を
    #   出さず 0.0 を返すため、素通しすると `a = 10.5200(0)` と読める値が出版経路へ流れる。
    cell_esd: Mapping[str, CellEsd] = field(default_factory=dict)
    # 相名→**重量 (質量) 分率**。出典 `G2PwdrData.ComputeMassFracs()` → GSAS-II
    #   `GSASIIstrMath.calcMassFracs` (wtSum=Σ mass[p]*Scale[p]; WgtFrac[j]=mass[j]*Scale[j]/wtSum)。
    #   mass は精密化された占有率を反映するため**フレーム毎に GSAS が算出**する (静的 CIF 質量では不可)。
    #   単相は {name: 1.0} (自明)。定量相分析の**出版値はこちら** (`phase_fractions` ではない)。
    phase_weight_fractions: Mapping[str, float] = field(default_factory=dict)
    # 相名→重量分率の esd。calcMassFracs が Jacobian + 共分散行列から伝播した値。**3 状態を区別する**
    #   (レビュー第6巡 HIGH; cell_esd と同型): ``>0.0`` = 分率を精密化した相の su / 単相は {name: 0.0}
    #   (自明な 1.0 に不確かさはない) / ``None`` = **多相なのにこの精密化から決まっていない**
    #   (相 Scale が最終共分散に無い = 全段 revert 等 → calcMassFracs が全相 su を厳密 0.0 にする)。
    #   相ごと欠落/空 dict = 分率非精密化・共分散なし。**多相の 0.0 を捏造しない** (無限精度の偽 su)。
    phase_weight_fraction_esd: Mapping[str, float | None] = field(default_factory=dict)
    # 【FR-318 電気化学制約向け (末尾追加・既定空で後方互換)】
    # 相名→原子ラベル→サイト多重度 (GSAS 原子行 cs+1)。`MobileSiteSpec.multiplicities` の照合材料
    #   (REQ-318-008: 呼び出し側指定の mult と GSAS 実値の不一致は静かに誤った x を作るため必ず照合する)。
    atom_multiplicity: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    # 相名→原子ラベル→占有率 esd。**2 状態を区別する** (cell_esd と同型の規律):
    #   ``>0.0`` = Afrac が最終共分散 varyList に載り精密化された su / ``None`` = この精密化では
    #   決まっていない (F フラグ無し・段 revert・共分散なし)。**0.0 を捏造しない**。
    atom_occupancy_esd: Mapping[str, Mapping[str, float | None]] = field(default_factory=dict)
    # 【restraint penalty 込みの Rwp (末尾追加・既定 None で後方互換)】: `StabilityOptions.
    #   enable_restraints` で拘束を χ² に入れたときだけ非 None。``None`` = penalty なし =
    #   `final_rwp` と同義。**`final_rwp` の意味は決して penalty 込みにしない** — 出版される
    #   数値の意味をオプションで切り替えると、同じ列に載った 2 つの Rwp が比較できなくなる。
    final_rwp_penalized: "float | None" = None
    # 【決まらなかったパラメータ (REQ-SAR-103, 末尾追加・既定空で後方互換)】: 最終収束後に残った
    #   ``esd >= |値|`` の変数。**これは失敗ではなく所見**である — 「このデータではこのパラメータは
    #   決まらない」という情報であり、握り潰すと NaCuHCF の Ow 判別 (占有率が Na>1/O<0 に発散した
    #   こと自体が決め手だった) と同種の診断信号を失う。`StabilityOptions.report_undetermined`
    #   を立てたときだけ埋まる (既定は空 = 診断を要求していない、であって「無かった」ではない)。
    undetermined_parameters: tuple[WeakVariable, ...] = ()
    # 上と同じ検出をしたが ``esd/|値|`` の比が**構造的に意味を持たない**ため判定対象外にした変数
    #   (既定 ``dAx/dAy/dAz`` = 座標シフト。`StabilityOptions.esd_ratio_exempt_tokens` 参照)。
    #   捨てずに別列で返すのは、報告が**何を見なかったか**を隠さないため。
    undetermined_exempt: tuple[WeakVariable, ...] = ()
    # この結果の fit で**凍結されていた**変数 (救済凍結 + 毎段プルーニング + 最終研磨の総和)。
    #   出版値がどの母数集合の上に載っているかを示す (空 = 何も凍結していない)。
    frozen_parameters: tuple[str, ...] = ()
    # 最終研磨 (opt-in) の記録。None = 研磨を要求していない。`FinalPolish` 参照。
    final_polish: "FinalPolish | None" = None
    # 拘束の χ² 寄与 (``Rvals['RestraintSum']`` = pSum) の最終値。拘束が「どれだけ引いているか」を
    #   絶対量で見る唯一の窓 (0.0 = 拘束なし/無効)。
    #   【どの状態の値か】: `final_rwp` / `final_rwp_penalized` と**同じ「採用状態」**
    #   (最後の段が revert されたなら revert 後、最終研磨が適用されたならその後) の値であり、
    #   最終 gpx の ``Rvals`` から読む。
    #   **なぜ試行値ではなく採用状態なのか**: この 3 つは「出版される fit を説明する数字」の
    #   組であり、1 つだけ捨てた試行の値だと**存在しない状態**を報告してしまう。実測 (誤った
    #   S–O ターゲットで座標段が revert された run): ``final_rwp_penalized`` は penalty 込みの
    #   3876 (= penalty 3.687e9 の状態) なのに ``final_restraint_penalty`` は試行が最小化した
    #   後の 0.0845 で、この 2 つが両立する状態は存在しない。捨てた試行で拘束がどう振る舞ったかは
    #   ledger ``m7_stage_restraint_split`` の ``trial_*`` に段ごとに残る — 報告を混ぜるのではなく
    #   層を分けて両方見えるようにする。
    final_restraint_penalty: float = 0.0
    # 【構造の一致判定に必要な精密化座標 (末尾追加・既定空で後方互換)】: 2 つの精密化手順が
    #   **同じ解に収束したか**は Rwp では判定できない (T3 実測: Rwp 差 0.361 で格子 0.161% 違い)。
    #   座標は今まで結果に一切載っておらず、`_extract_state` は validity 用の位置リストを作って
    #   捨てていたため、③ は構造を報告することも比較することもできなかった。
    # 相名→原子ラベル→(x,y,z) 分率座標。出典は GSAS 原子行 ``row[cx..cx+2]``
    #   (`atomrows.atom_row`)。**``dAx`` の値ではない** — あれは精密化ごとに 0 へ再初期化される
    #   シフトである (`GSASIIstrIO.py:1732`)。
    atom_coords: Mapping[str, Mapping[str, CoordTriple]] = field(default_factory=dict)
    # 相名→原子ラベル→座標 esd。**3 状態を区別する** (`cell_esd` と同型):
    #   ``>0.0`` = ``dA{axis}`` の sig (独立軸と、``depSigDict`` 経由の結束軸の双方) /
    #   ``0.0`` = **対称拘束で厳密に固定** (GSAS は変数にすらしない = 真の陳述) /
    #   ``None`` = この精密化では決まっていない (座標段未解放・段 revert・共分散なし)。
    #   **0.0 を捏造しない** — 0.0 は既に「対称固定」の意味を持つため、混同すると
    #   「厳密に固定された座標」と「決まらなかった座標」が区別できなくなる。
    atom_coord_esd: Mapping[str, Mapping[str, CoordEsd]] = field(default_factory=dict)
    # 相名→原子ラベル→``GetCSxinel(sytsym)[0]`` の生値 (`atomrows.FreeIndex`)。
    #   ``0``=対称固定 / 三つ組内で一意な正値=独立 / 他軸と一致する正値=**結束**。
    #   bool へ潰すと結束軸が独立に見えるので生の整数で運ぶ (一致判定が「片方だけ対称固定」を
    #   `INCOMPARABLE` と言い切るための根拠)。
    atom_coord_free_index: Mapping[str, Mapping[str, tuple[int, int, int]]] = field(
        default_factory=dict
    )
    # 相名→原子ラベル→Uiso esd。**2 状態** (`atom_occupancy_esd` と同型): ``>0.0`` / ``None``。
    #   異方性原子 (``row[cia] == "A"``) はキーごと欠落する (`atom_uiso` と同じ規律)。
    atom_uiso_esd: Mapping[str, Mapping[str, "float | None"]] = field(default_factory=dict)
    # per-histogram (索引順): プロファイル項の**解放フラグ**。`_extract_profile` が既に読みながら
    #   捨てていた第 3 要素 (`inst[key][2]`)。esd の有無とは別の問いに答える —
    #   esd は「最後の精密化で決まったか」、フラグは「この手順がそもそも解放を試みたか」。
    #   手順ごとに解放集合が違う (default と serious) ため、両方ないと「凍結していた」と
    #   「試したが決まらなかった」が区別できない。
    hist_profile_refined: tuple[Mapping[str, bool], ...] = ()
    # per-histogram (索引順): プロファイル項の esd。**2 状態** (``>0.0`` / ``None``)。
    #   装置パラメータに対称固定は無いので ``0.0`` 状態は存在しない。
    hist_profile_esd: tuple[Mapping[str, "float | None"], ...] = ()
    # 【微細構造 (結晶子サイズ / 微小歪み)】: 相名 → ``"hist{i}"`` → 値。HAP パラメータなので
    #   `hist_profile` (装置パラメータ) には入らず、これまで結果に一切載っていなかった。
    #   **収束の判定対象は「構造 + 歪」**であり、Caglioti U/V/W のような装置側の nuisance とは
    #   区別する必要がある (プロファイルは最良フィットを選べば足りるが、歪は物理量)。
    #   異方 (uniaxial/generalized) の場合は代表成分 (等方相当) のみを載せる。
    hap_size: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    hap_mustrain: Mapping[str, Mapping[str, float]] = field(default_factory=dict)
    # 同型の 2 状態 esd (``>0.0`` / ``None``)。
    hap_size_esd: Mapping[str, Mapping[str, "float | None"]] = field(default_factory=dict)
    hap_mustrain_esd: Mapping[str, Mapping[str, "float | None"]] = field(default_factory=dict)
    # 【どのエンジンで精密化したか】: "gsasii" (既定) / "topas" (M12)。**Rwp や BIC を跨いで
    #   比較するときの前提条件**なので結果に常設する。両バックエンドは rwp/chi2 のセマンティクスを
    #   揃えてあるが (TOPAS は背景込みの `r_wp` を採る — `r_wp_dash` は背景差引きで非互換)、
    #   出所を隠すと「同じ数字だから同じ条件」と読まれてしまう。
    backend: str = "gsasii"
    # 【バックエンド中立の成果物ハンドル】: GSAS は `gpx_path` と同じ .gpx、TOPAS は
    #   INP/.out/results.txt を残したディレクトリ。`gpx_path` は GSAS 専用のまま残す
    #   (MEM 経路が .gpx を要求するため; TOPAS では空文字となり MEM は適用できない)。
    project_path: str = ""
    # 【ヒストグラム別 Rwp】: 索引順の (2θ ヒストグラムごとの) Rwp。joint では放射源ごとに
    #   当てはまりが大きく違うのが普通なので、総合値だけでは**どちらが悪いのか分からない**。
    #   総合値 (`final_rwp`) と混同しないこと — TOPAS 経路では `.out` の総合値を `final_rwp`
    #   に採り、ここには各 `xdd` の値を入れる。空 = 未計測 (バックエンドが出さない)。
    histogram_rwp: tuple[float, ...] = ()
