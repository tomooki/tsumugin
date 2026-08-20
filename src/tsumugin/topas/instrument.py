"""装置パラメータ + 観測データの TOPAS 向け変換 (M12 T4) — 純関数。

GSAS-II の装置ファイル 2 形式を読む:

- **``.instprm``** (新形式): ``Key:value`` 行。``Lam``/``Lam1``/``Lam2``・``Zero``・
  ``U,V,W,X,Y,SH/L``・TOF の ``difC``/``difA``/``Zero``・``Type`` (``PXC``/``PNC``/``PNT``)。
- **``.PRM``** (旧形式): 固定桁。``INS   HTYPE`` で種別、``INS  1 ICONS`` に λ1/λ2/Zero。

観測データは `reference.io.load_pattern` で読み、TOPAS が確実に読める ``.xye``
(2θ, 強度, σ の 3 列) へ書き出す。これで ``.XRA``/``.fxye``/``.gsa``/``.xrdml`` などの
入力形式差を TOPAS へ持ち込まない。

**【プロファイル係数の換算】**: TOPAS の ``TCHZ_Peak_Type(u,v,w,z,x,y)`` は GSAS と同じ
Thompson-Cox-Hastings 擬 Voigt だが、**同名の係数が同じ意味とは限らない**。両者の定義を
突き合わせると (GSAS-II ``GSASIImath.getCWsig``/``getCWgam`` 対 ``topas.inc`` の
``TCHZ_Peak_Type``):

======================  ===========================  ===========================
量                      GSAS-II                      TOPAS
======================  ===========================  ===========================
ガウス                  σ² = U tan²θ + V tanθ + W    FWHM² = u tan²θ + v tanθ + w + z/cos²θ
(単位)                  センチ度² の**分散**         度² の **FWHM²**
ローレンツ              FWHM = X/cosθ + Y tanθ + Z   FWHM = x tanθ + y/cosθ
(単位)                  センチ度                     度
======================  ===========================  ===========================

したがって ``u,v,w = U,V,W × 8ln2/10⁴`` (分散→FWHM² と センチ度→度)、
``x = Y/100`` かつ ``y = X/100`` — **X と Y は入れ替わる** (size 由来と歪み由来が逆)。
GSAS の ``Z`` はローレンツ幅の定数項、TOPAS の ``z`` はガウスの 1/cos²θ 項で**別物**なので
写さない。:func:`gsas_cw_profile_to_tchz` がこの換算を持つ。

**種付けは opt-in (既定 off)**: 換算そのものは検証済みだが、実測では既定にする根拠が無い。
TCHZ マクロの箱 ``min = Max(-1, Val-.1); max = Min(2, Val+.1)`` は **``Val`` を毎回評価する
移動する箱**なので、汎用初期値 (w=0.003) から出発しても十分遠くまで歩ける (実 garnet で
w 0.003 → 0.143)。一方 GSAS が配る装置ファイルは "DUMMY" と自称する**公称値**のことがあり、
実 D1A では較正値 w=0.361 が実データの好む 0.143 の 2.5 倍だった。そこから出発すると
移動箱が届かず、種付けの方が悪くなる (garnet 12.3% → 14.9%)。ラボ X 線 (T1/T3) は
公称値が汎用初期値とほぼ同じで差が出ない。**較正済みの実装置ファイルを持つ呼び出し側が
明示的に有効化する**のが正しい使い方。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np

from ..autorietveld.model import Geometry, HistogramSpec, Radiation
from .inp import Param, TopasHistogram

__all__ = [
    "GSAS_SIGMA_TO_TCHZ",
    "ZERO_POINT_LIMIT_DEG",
    "InstrumentSpec",
    "TOF_RELATIVE_RESOLUTION",
    "gsas_cw_profile_to_tchz",
    "histogram_to_topas",
    "read_instrument",
    "tof_peak_type",
    "write_xye",
]

TOF_RELATIVE_RESOLUTION: float = 1.4e-3
"""TOF の初期ピーク幅を置くための相対分解能 Δd/d。

GSAS の ``sig-1``/``sig-2`` は**分散**の d²/d⁴ 係数、TOPAS は **FWHM** の d/d² 係数で
**関数形が違う** (√の中の和 対 和)。加えて実 POWGEN の ``sig-1`` は**負** (-167.4) なので
平方根が取れず、素直な写像が存在しない。そこで物理的に意味のある量から置き直す:
``FWHM[µs] ≈ (Δd/d)·difC·d`` なので d の係数が ``(Δd/d)·difC`` になる。

0.14% は実 POWGEN の GSAS 係数から d≈1Å で復元した値 (FWHM 30.7 µs / difC 22600)。
以降は ``tof_profile`` 段が実測へ寄せる。
"""

GSAS_SIGMA_TO_TCHZ: float = 8.0 * math.log(2.0) / 1.0e4
"""GSAS の U,V,W (センチ度² の**分散**係数) → TOPAS の u,v,w (度² の **FWHM²** 係数)。

``FWHM = √(8ln2)·σ`` と センチ度 → 度 の ``/100`` を合わせて ``8ln2/10⁴``。
"""

ZERO_POINT_LIMIT_DEG: float = 0.5
"""2θ ゼロ点を装置の宣言値から動かしてよい幅 [度]。

``ZE`` マクロ内蔵の箱は ``±100 × データ刻み`` で、刻み 0.05° の CW 中性子では **±5°**。
実 garnet (プロファイル種付けを有効にした構成) ではこの緩さで格子解放段のゼロ点が **+1.16°**
まで暴走し Rwp 18.5 → 51.3 になった。1° を超える 2θ ゼロ点は「ゼロ点」ではなく波長か指数付けの
誤りであり、**数値的事故であって情報ではない** (GSAS 経路の
`autorietveld.bounds.displacement_box_bounds` と同じ論法)。

実測で ±0.1/±0.2/±0.5 はいずれも同じ解 (ze = −0.0406°, Rwp 19.384) に収束し、±1.0 だけが
暴走側の谷に落ちる。物理的に緩く、かつ事故を除ける側として 0.5 を採る。**既定構成
(種付け off) では現に binding していない** (T1/T2/T3 とも値が変わらない) が、束縛を外すと
再現する失敗経路が実在するので恒久的に張る。
"""

_ICONS = re.compile(r"^INS\s+\d*\s*ICONS(.*)$")
_HTYPE = re.compile(r"^INS\s+HTYPE\s+(\S+)")
_PRCF_HEAD = re.compile(r"^INS\s+\d*PRCF1\s+(.*)$")
_PRCF_LINE = re.compile(r"^INS\s+\d*PRCF1(\d)(.*)$")


@dataclass(frozen=True)
class InstrumentSpec:
    """装置記述 (放射源に依らない共通形)。"""

    lam1: "float | None" = None
    lam2: "float | None" = None
    lam_ratio: float = 0.5
    zero: float = 0.0
    difc: "float | None" = None
    difa: float = 0.0
    tof_zero: float = 0.0
    is_tof: bool = False
    is_neutron: bool = False
    profile: "dict[str, float] | None" = None
    """GSAS の U,V,W,X,Y,SH/L (**GSAS の単位系のまま**)。

    TOPAS へ渡す前に必ず :func:`gsas_cw_profile_to_tchz` を通すこと。
    """


def _read_instprm(text: str) -> InstrumentSpec:
    values: dict[str, float] = {}
    type_token = ""
    for raw in text.splitlines():
        key, sep, value = raw.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if key == "Type":
            type_token = value
            continue
        try:
            values[key] = float(value)
        except ValueError:
            continue
    is_tof = "difC" in values or type_token.endswith("T")
    is_neutron = type_token.startswith("PN")
    # 【TOF の係数も残す】: alpha/beta を捨てると TOPAS 側は汎用初期値からピーク形状を
    #   作ることになる。**ピークはどこかに立つので tc.exe は正常終了し Rwp だけが悪い**
    #   (#179 の T4 で TOF 側が 49% で頭打ちだった主因候補)。
    keys = ("U", "V", "W", "X", "Y", "SH/L", "alpha", "beta-0", "beta-1",
            "sig-0", "sig-1", "sig-2")
    profile = {k: values[k] for k in keys if k in values}
    return InstrumentSpec(
        lam1=values.get("Lam1", values.get("Lam")),
        lam2=values.get("Lam2"),
        lam_ratio=values.get("I(L2)/I(L1)", 0.5),
        zero=values.get("Zero", 0.0) if not is_tof else 0.0,
        difc=values.get("difC"),
        difa=values.get("difA", 0.0),
        tof_zero=values.get("Zero", 0.0) if is_tof else 0.0,
        is_tof=is_tof,
        is_neutron=is_neutron,
        profile=profile or None,
    )


def _read_prm(text: str) -> InstrumentSpec:
    """旧 GSAS ``.PRM``。``INS  1 ICONS  <λ1> <λ2> <Zero> …`` と ``INS   HTYPE  PXCR``。

    プロファイル係数は ``INS  1PRCF1 `` (型・係数個数) と ``INS  1PRCF11``/``12`` から拾う。
    写像は GSAS-II ``GSASIIfiles`` の CW 分岐に合わせる:

    - ``PRCF11`` の先頭 3 つが **GU, GV, GW** (常にここ)
    - ``PRCF12`` を **LX, LY, S, H** と読んでよいのは**型 3 のときだけ**。型 1/2 の
      ``PRCF12`` は別の量なので、読むとローレンツ幅を捏造することになる。
    """
    lam1 = lam2 = None
    zero = 0.0
    htype = ""
    profile_type: "int | None" = None
    coefficients: dict[int, list[float]] = {}
    for raw in text.splitlines():
        htype_match = _HTYPE.match(raw)
        if htype_match:
            htype = htype_match.group(1)
            continue
        icons = _ICONS.match(raw)
        if icons:
            numbers = [float(t) for t in icons.group(1).split() if _is_number(t)]
            if len(numbers) >= 1:
                lam1 = numbers[0]
            if len(numbers) >= 2 and numbers[1] > 0:
                lam2 = numbers[1]
            if len(numbers) >= 3:
                zero = numbers[2]
            continue
        line = _PRCF_LINE.match(raw)
        if line:
            coefficients[int(line.group(1))] = [
                float(t) for t in line.group(2).split() if _is_number(t)
            ]
            continue
        head = _PRCF_HEAD.match(raw)
        if head:
            tokens = [t for t in head.group(1).split() if _is_number(t)]
            if tokens:
                profile_type = abs(int(float(tokens[0])))
    return InstrumentSpec(
        lam1=lam1,
        lam2=lam2,
        zero=zero,
        is_neutron=htype.startswith("PN"),
        is_tof=htype.endswith("T"),
        profile=_prm_profile(profile_type, coefficients),
    )


def _prm_profile(
    profile_type: "int | None", coefficients: "dict[int, list[float]]"
) -> "dict[str, float] | None":
    """``PRCF11``/``PRCF12`` を GSAS の U,V,W,X,Y,SH/L へ写す。"""
    gaussian = coefficients.get(1, [])
    if len(gaussian) < 3:
        return None
    profile = {"U": gaussian[0], "V": gaussian[1], "W": gaussian[2]}
    lorentzian = coefficients.get(2, [])
    if profile_type == 3 and len(lorentzian) >= 4:
        profile["X"] = lorentzian[0]
        profile["Y"] = lorentzian[1]
        profile["SH/L"] = lorentzian[2] + lorentzian[3]
    return profile


_TCHZ_FROM_GSAS_GAUSSIAN = (("u", "U"), ("v", "V"), ("w", "W"))
#: ローレンツ項は**名前が入れ替わる** — GSAS は ``X/cosθ + Y tanθ``、TOPAS は
#: ``x tanθ + y/cosθ``。取り違えると size 由来と歪み由来が逆になる。
_TCHZ_FROM_GSAS_LORENTZIAN = (("x", "Y"), ("y", "X"))


def gsas_cw_profile_to_tchz(profile: "Mapping[str, float]") -> "dict[str, float]":
    """GSAS の CW プロファイル係数を TOPAS ``TCHZ_Peak_Type`` の単位系へ換算する。

    換算則はモジュール docstring の表を参照。装置ファイルに無い係数は**入れない**。
    GSAS の ``Z`` は TOPAS の ``z`` と別物なので写さない。

    **ローレンツ項が 0 のときも種にしない**: GSAS が配る DUMMY 装置ファイルは LX/LY を 0 で
    埋めているが、それは「測って 0 だった」ではなく**情報が無い**という意味である。0 を種に
    するとピークが純ガウスの初期形になり、既定値から始めるより悪い出発点になる
    (実 fluoroapatite で初期段 45.4 → 54.2)。ガウス項は 0 が意味を持つので区別しない。
    """
    seed: dict[str, float] = {}
    for topas_key, gsas_key in _TCHZ_FROM_GSAS_GAUSSIAN:
        if gsas_key in profile:
            seed[topas_key] = float(profile[gsas_key]) * GSAS_SIGMA_TO_TCHZ
    for topas_key, gsas_key in _TCHZ_FROM_GSAS_LORENTZIAN:
        if profile.get(gsas_key):
            seed[topas_key] = float(profile[gsas_key]) / 100.0
    return seed


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def read_instrument(path: "str | Path") -> InstrumentSpec:
    """``.instprm`` / ``.PRM`` を読み分けて装置記述を返す。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if "INS " in text and ":" not in text.split("\n")[0]:
        return _read_prm(text)
    return _read_instprm(text)


def write_xye(path: "str | Path", x: np.ndarray, y: np.ndarray) -> Path:
    """(x, y) を TOPAS が読む ``.xye`` (3 列) へ書き出す。σ は √max(y,1)。

    決定論的な書式で書く (NFR-102)。
    """
    out = Path(path)
    sigma = np.sqrt(np.maximum(np.asarray(y, dtype=float), 1.0))
    lines = [
        f"{float(xi):.6f} {float(yi):.6f} {float(si):.6f}"
        for xi, yi, si in zip(np.asarray(x, dtype=float), np.asarray(y, dtype=float), sigma)
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def _emission_lines(spec: InstrumentSpec, radiation: Radiation) -> list[str]:
    """放射源の記述行を組む。"""
    if spec.is_tof:
        return []
    lam1 = spec.lam1
    if lam1 is None or not math.isfinite(lam1) or lam1 <= 0.0:
        raise ValueError(
            "装置ファイルから波長を読めませんでした。Cu Kα で埋める既定は行いません "
            "(誤った波長はピーク位置を系統的にずらし、格子がそれを吸収してしまうため)。"
        )
    lines = ["lam", "   ymin_on_ymax 0.0001"]
    if radiation.is_neutron or spec.is_neutron or spec.lam2 is None:
        lines.append(f"   la 1 lo {lam1!r} lh 0.1")
    else:
        # Kα1/Kα2 の二重線。比は装置ファイルの I(L2)/I(L1) (既定 0.5)。
        lines.append(f"   la 1 lo {lam1!r} lh 0.1")
        lines.append(f"   la {spec.lam_ratio!r} lo {spec.lam2!r} lh 0.1")
    return lines


def histogram_to_topas(
    spec: HistogramSpec,
    *,
    workdir: "str | Path",
    index: int = 0,
    background_coeffs: int = 6,
    seed_profile: bool = False,
) -> TopasHistogram:
    """`HistogramSpec` を TOPAS 用に変換する (データを ``.xye`` へ落とし装置行を組む)。

    :param workdir: ``.xye`` を書き出す作業ディレクトリ (driver の cwd と同じ)
    :param seed_profile: 装置ファイルの Caglioti 係数を TCHZ の初期値へ換算して渡すか。
        **既定 False** — 公称値の装置ファイルでは種付けの方が悪い (モジュール docstring)。
        TOF は Caglioti でないので対象外。
    """
    from ..reference.io import load_pattern

    work = Path(workdir)
    instrument = read_instrument(spec.instrument_path)
    x, y = load_pattern(spec.data_path, spec.data_format)
    data_name = f"hist{index}.xye"
    write_xye(work / data_name, x, y)

    preamble = list(_emission_lines(instrument, spec.radiation))
    if instrument.is_tof:
        # 【TOF の Lorentz 因子は d⁴】: 固定検出器角なので sinθ は定数に吸収され、残るのが
        #   ``D_spacing^4``。落とすと長 d 側の強度が系統的に足りなくなる (CW 中性子で
        #   Lorentz を落としていたのと同じ病理)。Tutorial の ZrW2O8.inp と同じ式。
        preamble.append("TOF_LAM(0.001)")
        preamble.append("scale_pks = D_spacing^4;")
    if not instrument.is_tof:
        if spec.radiation is Radiation.XRAY_SYNCHROTRON:
            # 【放射光は Lorentz のみ】: 散乱面内でほぼ完全偏光しているので偏光因子は ~1。
            #   ラボ管球用の ``LP_Factor(26.4)`` (グラファイトモノクロメータの偏光項) を
            #   当てると強度の 2θ 依存が系統的に狂う。topas.inc の
            #   ``LP_Factor_Synchrotron_Simple`` はまさに ``Lorentz_Factor`` だけである。
            preamble.append("Lorentz_Factor")
        elif spec.radiation.is_neutron:
            # 【中性子にも Lorentz 因子は要る】: 無いのは**偏光**因子だけ。
            #   1/(sin²θ·cosθ) は 2θ=24° と 158° で 2 桁変わるので、落とすとピーク位置は
            #   合うのに強度の 2θ 依存が系統的にずれ、Rwp が 3 倍近く悪いところで頭打ちになる
            #   (実 garnet 12.3% 対 GSAS 4.33%、実 PbSO4 joint の中性子側 14.4%)。
            #   TOPAS Tutorial (Magnetic Refinement/lamno3.inp) は偏光項が消える
            #   ``LP_Factor(90)`` で同じ式を作っている。
            preamble.append("Lorentz_Factor")
        else:
            # Bragg-Brentano の Lorentz-偏光因子。単結晶モノクロメータ角は既定値を用いる。
            preamble.append("LP_Factor(26.4)")
    if not instrument.is_tof:
        # 【ZE マクロを使わず箱を自前で張る】: マクロ内蔵の箱 (±100 ステップ) は緩すぎて
        #   ゼロ点が暴走する (ZERO_POINT_LIMIT_DEG 参照)。マクロの実体は th2_offset への
        #   代入だけなので、束縛付きの prm を宣言して同じ式を書く。
        zero = float(instrument.zero)
        #   微分ステップ (``del``) は ``ZE`` マクロの中身をそのまま写す。**``X1`` であって
        #   ``Xo`` ではない** — TOF の ``x_calculation_step`` で使う ``Yobs_dx_at(Xo)`` とは
        #   別物で、こちらはデータ範囲の左端での刻み。topas.inc の ZE が
        #   ``del = .01 Yobs_dx_at(X1);`` と書いているのに合わせる (見た目が揃わないのは
        #   意図的)。
        preamble.append(
            f"prm !ze{index} {zero!r} "
            f"min {zero - ZERO_POINT_LIMIT_DEG!r} max {zero + ZERO_POINT_LIMIT_DEG!r} "
            f"del = .01 Yobs_dx_at(X1);"
        )
        preamble.append(f"th2_offset = ze{index};")
        preamble.append(f"One_on_X(!oox{index}, 0)")
    tof_cal = None
    if instrument.is_tof and instrument.difc:
        tof_cal = {
            "difc": instrument.difc,
            "difa": instrument.difa,
            "zero": instrument.tof_zero,
        }

    seed = None
    if seed_profile and not instrument.is_tof and instrument.profile:
        seed = gsas_cw_profile_to_tchz(instrument.profile) or None

    # 【計算格子は必ず明示する】: TOPAS の既定は
    #   ``x_calculation_step too small or not defined`` で異常終了することがある — 実測で
    #   11BM 放射光 (0.001° 刻み・鋭いピーク) と実 POWGEN TOF の双方が該当した。
    #   ``Yobs_dx_at(Xo)`` のような適応式も、計算ピークがデータ範囲の外へ出た瞬間に同じ
    #   エラーになるので使えない。データの**最小**ビン幅を採る (中央値だと SLOG ビンで
    #   FWHM あたり 1 点しか置けず形状が粗くなる)。
    step = _minimum_step(x)

    return TopasHistogram(
        data_path=data_name,
        preamble=tuple(preamble),
        profile_seed=seed,
        background=Param(0.0, refine=True),
        background_coeffs=background_coeffs,
        two_theta_limits=spec.two_theta_limits,
        excluded_regions=tuple(spec.excluded_regions),
        weight=spec.weight,
        is_neutron=spec.radiation.is_neutron,
        is_tof=spec.radiation.is_tof,
        is_bragg_brentano=spec.geometry is Geometry.BRAGG_BRENTANO,
        calculation_step=step,
        tof_calibration=tof_cal,
    )


_TCHZ_KEYS = ("u", "v", "w", "z", "x", "y")
_TCHZ_DEFAULTS = {"u": 0.0, "v": 0.0, "w": 0.003, "z": 0.0, "x": 0.0, "y": 0.03}


def tchz_line(
    index: int,
    seed: "Mapping[str, float] | None" = None,
    *,
    refine: bool = False,
    phase_key: str = "",
) -> str:
    """``TCHZ_Peak_Type`` 行 (名前付き 12 引数形) を組む。

    TOPAS の TCHZ は GSAS と同じ Thompson-Cox-Hastings 擬 Voigt
    (ガウス幅² = u·tan²θ + v·tanθ + w + z/cos²θ、ローレンツ幅 = x·tanθ + y/cosθ) で
    U,V,W,Z,X,Y が 1:1 に対応する。名前を付けておくと後段 (`topas.flags`) が ``!`` の
    有無だけで解放/凍結を切り替えられる。

    **この行は ``str`` ブロックの中に置くこと** — xdd 直下だと
    ``Cannot locate pk_type from gen_fit_obj`` で異常終了する (実測)。

    :param seed: 初期値。**キーは TOPAS 側の ``u,v,w,z,x,y``** であり GSAS の U,V,W,X,Y では
        ない (同名でも意味と単位が違う)。換算は `gsas_cw_profile_to_tchz` の責務。
    :param phase_key: パラメータ名に混ぜる相の識別子。**TOPAS のパラメータ名は大域**なので、
        多相で同じ名前を複数の ``str`` ブロックに宣言すると衝突する (エラーか、全相が 1 つの
        ピーク形状を強制的に共有する)。相ごとに別のピーク形状を持てるよう名前を分ける。
    """
    tag = f"{index}{'_' + phase_key if phase_key else ''}"
    parts: list[str] = []
    for topas_key in _TCHZ_KEYS:
        value = (seed or {}).get(topas_key, _TCHZ_DEFAULTS[topas_key])
        name = f"pk{topas_key}{tag}"
        prefix = "" if refine else "!"
        parts.append(f"{prefix}{name}, {float(value)!r}")
    return f"TCHZ_Peak_Type({', '.join(parts)})"


def tof_peak_type(
    index: int,
    *,
    difc: float,
    refine: bool = False,
    phase_key: str = "",
    lorentzian: float = 0.1,
    alpha: "float | None" = None,
    beta0: "float | None" = None,
    beta1: "float | None" = None,
) -> str:
    """TOF の ``peak_type`` ブロック (幅と立ち上がり/減衰の宣言を含む複数行)。

    TOPAS の TOF ピーク幅は ``FWHM = f1*d + f2*d^2`` (Tutorial ZrW2O8.inp と同じ形)。
    初期値は :data:`TOF_RELATIVE_RESOLUTION` から置く (GSAS の sig-1/sig-2 とは関数形が
    違い、しかも実測 sig-1 が負なので直接は写せない)。

    **α/β は写せる** (幅と違って関数形が解ける)。``topas.inc`` の実体は
    ``exp_conv_const = lr Constant(t1) / (a0 + a1 / d^wexp)`` = **時間定数**なので、
    GSAS の速度定数 (1/µs) の逆数として対応する (t1 = difC):

    - 減衰 (Tutorial ZrW2O8 と同じ ``+`` 側): ``β = β₀ + β₁/d⁴`` →
      ``a0 = difC*β₀``, ``a1 = difC*β₁``, ``wexp = 4``
    - 立ち上がり (``-`` 側): ``α = α₁/d`` → ``a0 = 0``, ``a1 = difC*α₁``, ``wexp = 1``

    係数が読めない装置ファイルでは**でっち上げず**幅だけを置く。

    :param phase_key: パラメータ名に混ぜる相の識別子。**TOPAS のパラメータ名は大域**なので、
        分けないと全相が 1 つのピーク幅を強制的に共有する。
    :param alpha: GSAS の ``alpha`` (立ち上がりの速度定数 α₁)。
    :param beta0: GSAS の ``beta-0``。
    :param beta1: GSAS の ``beta-1``。
    """
    tag = f"{index}{'_' + phase_key if phase_key else ''}"
    prefix = "" if refine else "!"
    first = float(difc) * TOF_RELATIVE_RESOLUTION
    lines = [
        f"prm {prefix}tofw1{tag} {first!r} min 0.0001 max = 2 Val + 1;",
        f"prm {prefix}tofw2{tag} 0.0001 min 0.0001 max = 2 Val + 1;",
    ]
    # 【difC が無ければ α/β は出さない】: 係数は difC 倍で時間定数へ写すので、difC=0 だと
    #   ``exp_conv_const = Constant(0)/(0 + 0/d^4)`` = 0 除算になり tc.exe が落ちる。
    #   装置ファイルが壊れているときは**幅だけ**置いて先へ進む (でっち上げない)。
    has_difc = float(difc) > 0.0
    if has_difc and beta0 is not None and beta1 is not None:
        lines.append(
            f"TOF_Exponential({prefix}tofb0{tag}, "
            f"{round(float(difc) * float(beta0), 4)!r}, "
            f"{prefix}tofb1{tag}, {round(float(difc) * float(beta1), 4)!r}, "
            f"4, difc_h{index}, +)"
        )
    if has_difc and alpha is not None:
        lines.append(
            f"TOF_Exponential({prefix}tofa0{tag}, 0.0, "
            f"{prefix}tofa1{tag}, {round(float(difc) * float(alpha), 4)!r}, "
            f"1, difc_h{index}, -)"
        )
    lines.append(
        f"peak_type pv pv_lor !tofl{tag} {float(lorentzian)!r} "
        f"pv_fwhm = tofw1{tag} D_spacing + tofw2{tag} D_spacing^2;"
    )
    return "\n".join(lines)


def _minimum_step(x: np.ndarray) -> float:
    """観測 x 軸の最小ビン幅 (計算格子の既定)。1 点以下なら 1.0 を返す。"""
    values = np.asarray(x, dtype=float)
    if values.size < 2:
        return 1.0
    widths = np.diff(values)
    positive = widths[widths > 0.0]
    return float(positive.min()) if positive.size else 1.0
