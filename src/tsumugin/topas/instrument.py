"""装置パラメータ + 観測データの TOPAS 向け変換 (M12 T4) — 純関数。

GSAS-II の装置ファイル 2 形式を読む:

- **``.instprm``** (新形式): ``Key:value`` 行。``Lam``/``Lam1``/``Lam2``・``Zero``・
  ``U,V,W,X,Y,SH/L``・TOF の ``difC``/``difA``/``Zero``・``Type`` (``PXC``/``PNC``/``PNT``)。
- **``.PRM``** (旧形式): 固定桁。``INS   HTYPE`` で種別、``INS  1 ICONS`` に λ1/λ2/Zero。

観測データは `reference.io.load_pattern` で読み、TOPAS が確実に読める ``.xye``
(2θ, 強度, σ の 3 列) へ書き出す。これで ``.XRA``/``.fxye``/``.gsa``/``.xrdml`` などの
入力形式差を TOPAS へ持ち込まない。

**【プロファイルの単位は仮定しない】**: TOPAS の ``TCHZ_Peak_Type(u,v,w,z,x,y)`` は GSAS と
同じ Thompson-Cox-Hastings 擬 Voigt (ガウス幅² = u·tan²θ + v·tanθ + w + z/cos²θ、
ローレンツ幅 = x·tanθ + y/cosθ) だが、**GSAS の U,V,W はセンチ度² 系**であり係数のスケールが
一致する保証がない。誤った換算で幅を種付けすると「収束したのに幅が合わない」が静かに起きるため、
既定では**種付けせず TOPAS 側の既定値から精密化させる**。実測で換算係数を確定するまで
``seed_profile`` は opt-in のままにする。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..autorietveld.model import HistogramSpec, Radiation
from .inp import Param, TopasHistogram

__all__ = [
    "InstrumentSpec",
    "histogram_to_topas",
    "read_instrument",
    "write_xye",
]

_ICONS = re.compile(r"^INS\s+\d*\s*ICONS(.*)$")
_HTYPE = re.compile(r"^INS\s+HTYPE\s+(\S+)")


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
    """GSAS の U,V,W,X,Y,SH/L (**単位は未検証**; seed_profile=True のときのみ使う)。"""


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
    profile = {k: values[k] for k in ("U", "V", "W", "X", "Y", "SH/L") if k in values}
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
    """旧 GSAS ``.PRM``。``INS  1 ICONS  <λ1> <λ2> <Zero> …`` と ``INS   HTYPE  PXCR``。"""
    lam1 = lam2 = None
    zero = 0.0
    htype = ""
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
    return InstrumentSpec(
        lam1=lam1,
        lam2=lam2,
        zero=zero,
        is_neutron=htype.startswith("PN"),
        is_tof=htype.endswith("T"),
    )


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
    :param seed_profile: GSAS の U,V,W,X,Y を初期値として種付けするか。**既定 False** —
        係数のスケール等価が未検証のため (モジュール docstring 参照)。
    """
    from ..reference.io import load_pattern

    work = Path(workdir)
    instrument = read_instrument(spec.instrument_path)
    x, y = load_pattern(spec.data_path, spec.data_format)
    data_name = f"hist{index}.xye"
    write_xye(work / data_name, x, y)

    preamble = list(_emission_lines(instrument, spec.radiation))
    if not instrument.is_tof and not spec.radiation.is_neutron:
        # Bragg-Brentano の Lorentz-偏光因子。単結晶モノクロメータ角は既定値を用いる。
        preamble.append("LP_Factor(26.4)")
    if not instrument.is_tof:
        preamble.append(f"ZE(!ze{index}, {instrument.zero!r})")
        preamble.append(f"One_on_X(!oox{index}, 0)")
    tof_cal = None
    if instrument.is_tof and instrument.difc:
        tof_cal = {
            "difc": instrument.difc,
            "difa": instrument.difa,
            "zero": instrument.tof_zero,
        }

    return TopasHistogram(
        data_path=data_name,
        preamble=tuple(preamble),
        background=Param(0.0, refine=True),
        background_coeffs=background_coeffs,
        two_theta_limits=spec.two_theta_limits,
        excluded_regions=tuple(spec.excluded_regions),
        weight=spec.weight,
        is_neutron=spec.radiation.is_neutron,
        is_tof=spec.radiation.is_tof,
        tof_calibration=tof_cal,
    )


_TCHZ_KEYS = (("u", "U"), ("v", "V"), ("w", "W"), ("z", "Z"), ("x", "X"), ("y", "Y"))
_TCHZ_DEFAULTS = {"u": 0.0, "v": 0.0, "w": 0.003, "z": 0.0, "x": 0.0, "y": 0.03}


def tchz_line(
    index: int, seed: "dict[str, float] | None" = None, *, refine: bool = False
) -> str:
    """``TCHZ_Peak_Type`` 行 (名前付き 12 引数形) を組む。

    TOPAS の TCHZ は GSAS と同じ Thompson-Cox-Hastings 擬 Voigt
    (ガウス幅² = u·tan²θ + v·tanθ + w + z/cos²θ、ローレンツ幅 = x·tanθ + y/cosθ) で
    U,V,W,Z,X,Y が 1:1 に対応する。名前を付けておくと後段 (`topas.flags`) が ``!`` の
    有無だけで解放/凍結を切り替えられる。

    **この行は ``str`` ブロックの中に置くこと** — xdd 直下だと
    ``Cannot locate pk_type from gen_fit_obj`` で異常終了する (実測)。
    """
    parts: list[str] = []
    for topas_key, gsas_key in _TCHZ_KEYS:
        value = (seed or {}).get(gsas_key, _TCHZ_DEFAULTS[topas_key])
        name = f"pk{topas_key}{index}"
        prefix = "" if refine else "!"
        parts.append(f"{prefix}{name}, {float(value)!r}")
    return f"TCHZ_Peak_Type({', '.join(parts)})"
