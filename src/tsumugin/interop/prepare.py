"""SXRD + ND 同時解析用のヒストグラム仕様生成 (interop.prepare)。

RIETAN .int (放射光 X 線) と Z-Code Igor TOF (中性子) の実データ + 各回折計ファイルから、
GSAS-II が取り込める中間ファイル (.xye / TOF FXYE / .instprm) を書き出し、
:class:`~tsumugin.autorietveld.model.HistogramSpec` のペアを組む高水準ヘルパ。
``run_auto_rietveld([xray, nd], phases)`` へそのまま渡せる。

``autorietveld.model`` の import は関数内に閉じ込め、``import tsumugin.interop`` を軽量に保つ
(パーサのみ使う経路で autorietveld/engine を読み込まない)。
"""

from __future__ import annotations

from pathlib import Path

from tsumugin.interop.instrument import write_gsas_instprm
from tsumugin.interop.rietan import convert_rietan_int
from tsumugin.interop.zrietveld import convert_igor_tof, parse_zdiffractometer

__all__ = ["prepare_histograms"]

# 放射光 X 線の実波長 (別較正 CeO2 ファイルの 0.5 Å ではなく解析入力 XLMDX)。
_DEFAULT_XRAY_WAVELENGTH = 0.79958
# RIETAN 解析で除外した低角領域 (2θ≤5) を踏まえた既定の X 線精密化範囲。
_DEFAULT_XRAY_LIMITS = (5.0, 78.0)


def prepare_histograms(
    *,
    xray_int: str | Path,
    xray_diffractometer: str | Path,
    nd_igor: str | Path,
    nd_diffractometer: str | Path,
    out_dir: str | Path,
    xray_wavelength: float = _DEFAULT_XRAY_WAVELENGTH,
    xray_limits: tuple[float, float] | None = _DEFAULT_XRAY_LIMITS,
    nd_limits: tuple[float, float] | None = None,
):
    """SXRD + ND の ``(xray_spec, nd_spec)`` を生成する (中間ファイルを out_dir に書き出す)。🔵

    :param xray_int: RIETAN-FP ``.int`` (放射光 X 線)
    :param xray_diffractometer: X 線 ``.zDiffractometer`` (波長は ``xray_wavelength`` で上書き)
    :param nd_igor: Z-Code Igor TOF ``.histogramIgor`` (中性子)
    :param nd_diffractometer: TOF ``.zDiffractometer`` (変換係数 / bank 角 / fitting range)
    :param out_dir: 中間ファイル (.xye / .fxye / .instprm) の出力先
    :param xray_wavelength: X 線波長 [Å] (既定 0.79958 = 実解析入力)
    :param xray_limits: X 線精密化 2θ 範囲 [deg] (None で全域)
    :param nd_limits: TOF 精密化範囲 [μs] (None なら ND 回折計の fitting_range を採る)
    :returns: ``(HistogramSpec[X 線], HistogramSpec[中性子 TOF])``
    """
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # --- X 線 (放射光, Debye-Scherrer) ---
    xye = convert_rietan_int(xray_int, out / "xray.xye")
    zx = parse_zdiffractometer(
        Path(xray_diffractometer).read_text(encoding="utf-8", errors="replace")
    )
    x_instprm = write_gsas_instprm(zx, out / "xray.instprm", wavelength=xray_wavelength)
    xray_spec = HistogramSpec(
        data_path=str(xye),
        instrument_path=str(x_instprm),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=xray_limits,
    )

    # --- 中性子 (TOF) ---
    fxye = convert_igor_tof(nd_igor, out / "nd.fxye")
    zn = parse_zdiffractometer(
        Path(nd_diffractometer).read_text(encoding="utf-8", errors="replace")
    )
    n_instprm = write_gsas_instprm(zn, out / "nd.instprm")
    limits = nd_limits if nd_limits is not None else zn.fitting_range
    nd_spec = HistogramSpec(
        data_path=str(fxye),
        instrument_path=str(n_instprm),
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
        two_theta_limits=limits,
        absorption=float(zn.absorption) if zn.absorption else 0.0,  # Z-Code [Absorption]
    )
    return xray_spec, nd_spec
