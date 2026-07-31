"""GSAS-II 装置パラメータ (``.instprm``) の書き出し (interop.instrument)。

ベンダー非依存の薄い writer。:class:`~tsumugin.interop.zrietveld.ZDiffractometer` を入力に、GSAS-II が
読める ``.instprm`` を生成する:

- **X 線 (``Type:PXC``)**: 波長 ``Lam`` / ゼロ ``Zero`` / Caglioti ``U,V,W`` / Lorentzian ``X,Y`` /
  非対称 ``SH/L``。放射光は偏光 ``Polariz.`` を高めに採る。プロファイル初期値は妥当な既定で置き、
  実 GSAS-II 精密化 (recipe) で解放する。
- **TOF 中性子 (``Type:PNT``)**: 変換係数を直写像 (``difC=c1, difA=c2, Zero=c0, difB=0``)。バンク角と
  difC から飛行距離 ``fltPath`` を導出。ガウス幅 ``sig-0/1/2`` は Z-Code の ``SigmaSquare0/1/2`` を初期値に
  採り (体系が近い)、非対称 ``alpha/beta`` は妥当な既定 (精密化しないので概略で可、size/mustrain で吸収)。

TOF プロファイル (sig/alpha/beta) の体系は Z-Code と GSAS-II で厳密には一致しない。ピーク位置を決める
``difC/difA/Zero`` は厳密写像であり、形状の残差は recipe の size/mustrain と背景で吸収する設計 (T4 教訓)。
"""

from __future__ import annotations

import math
from pathlib import Path

from tsumugin.instprm import build_instprm_text
from tsumugin.interop.zrietveld import ZDiffractometer

__all__ = ["write_gsas_instprm"]

# GSAS difC[μs/Å] = 2·252.816·L[m]·sin(θ)。fltPath 逆算に使う。
_DIFC_CONST = 252.816


def _instprm_pxc(
    zd: ZDiffractometer,
    *,
    wavelength: float | None,
    polarization: float | None,
) -> str:
    """X 線 (PXC) instprm テキストを組む (``tsumugin.instprm`` へ委譲)。"""
    lam = wavelength if wavelength is not None else zd.wavelength
    if lam is None:
        raise ValueError("X 線 instprm には波長が必要です (wavelength 引数か config.wavelength)。")
    # 放射光は水平偏光でほぼ完全偏光。既定を高めに採る。
    is_synchrotron = "synchrotron" in zd.method.lower()
    zero = zd.zero if zd.zero is not None else 0.0
    return build_instprm_text(
        radiation="xray_synchrotron" if is_synchrotron else "xray_lab",
        wavelength=lam,
        zero=zero,
        polarization=polarization,
        creator="tsumugin.interop",
    )


def _instprm_pnt(zd: ZDiffractometer) -> str:
    """TOF 中性子 (PNT) instprm テキストを組む (``tsumugin.instprm`` へ委譲)。"""
    if len(zd.conversion_params) < 2:
        raise ValueError("TOF instprm には変換係数 (c0,c1[,c2]) が必要です。")
    c0 = zd.conversion_params[0]
    difc = zd.conversion_params[1]
    difa = zd.conversion_params[2] if len(zd.conversion_params) >= 3 else 0.0

    bank_2t = zd.bank_two_theta if zd.bank_two_theta is not None else 90.0
    theta = math.radians(bank_2t / 2.0)
    sin_t = math.sin(theta)
    # difC = 2·252.816·L·sinθ → L[m]。sinθ≈0 の縮退は既定飛行距離。
    flt_path = difc / (2.0 * _DIFC_CONST * sin_t) if sin_t > 1.0e-6 else 20.0

    # ガウス幅初期値: Z-Code SigmaSquare0/1/2 を採る (体系が近い)。無ければ 0。
    prof = zd.profile
    return build_instprm_text(
        radiation="neutron_tof",
        tof={
            "difC": difc,
            "difA": difa,
            "Zero": c0,
            "fltPath": flt_path,
            "two_theta": bank_2t,
            "sig-0": prof.get("SigmaSquare0", 0.0),
            "sig-1": prof.get("SigmaSquare1", 0.0),
            "sig-2": prof.get("SigmaSquare2", 0.0),
        },
        creator="tsumugin.interop",
    )


def write_gsas_instprm(
    config: ZDiffractometer,
    path: str | Path,
    *,
    wavelength: float | None = None,
    polarization: float | None = None,
) -> Path:
    """:class:`ZDiffractometer` から GSAS-II ``.instprm`` を書き出す。🔵

    放射源に応じて PXC (X 線) / PNT (TOF 中性子) を出力する。

    :param config: Z-Code 回折計設定 (``parse_zdiffractometer`` の出力)
    :param path: 出力 ``.instprm`` パス
    :param wavelength: X 線波長 [Å] の上書き (別較正ファイルの波長を無視したいとき)。TOF では無視。
    :param polarization: X 線偏光係数の上書き (既定は放射光 0.95 / それ以外 0.7)
    :returns: 書き出した ``.instprm`` の :class:`~pathlib.Path`

    Raises:
        ValueError: 放射源が判別不能 / 必須パラメータ (波長・変換係数) が欠けるとき。
    """
    if config.is_tof:
        text = _instprm_pnt(config)
    elif "x-ray" in config.beam_type.lower() or config.wavelength or wavelength:
        text = _instprm_pxc(config, wavelength=wavelength, polarization=polarization)
    else:
        raise ValueError(
            f"instprm の放射源を判別できません (beam_type={config.beam_type!r}, method={config.method!r})。"
        )
    out = Path(path)
    out.write_text(text, encoding="utf-8")
    return out
