"""分解能プロファイル物理候補探索 型・シグネチャ設計 (契約)。docs 配下・非実行。

信頼性: 🔵 GSAS getFWHM + CeO2 実測 + PR #40 instrument_profile 再利用。
"""

from __future__ import annotations

from typing import Mapping, Sequence

from tsumugin.autorietveld.model import HistogramSpec, InstrumentProfile, PhaseSpec


def profile_total_fwhm(values: Mapping[str, float], two_theta):
    """GSAS getFWHM (CW) 準拠の総 pseudo-Voigt FWHM [deg] を 2θ 配列で返す (numpy)。

    sig=sqrt(max(0.001, U·tan²θ+V·tanθ+W)) (GSAS はガウス分散をクランプ)、gam=X/cosθ+Y·tanθ、
    総 FWHM=getgamFW(2.35482·sig, gam)/100。poly≤0 (発散) は NaN。物理性=全域で有限かつ>0。
    """
    ...


def profile_fwhm_min(
    values: Mapping[str, float], lo_deg: float = 5.0, hi_deg: float = 120.0, n: int = 64
) -> float:
    """総 FWHM のレンジ区間最小 (>0 なら全域物理・転写可能)。NaN があれば -inf を返す (非物理)。"""
    ...


def candidate_profiles(
    anchor: Mapping[str, float],
    *,
    x_factors: Sequence[float] = (0.6, 0.8, 1.0, 1.2, 1.4),
    w_factors: Sequence[float] = (0.7, 1.0, 1.3),
    y_offsets: Sequence[float] = (0.0,),
) -> list[dict[str, float]]:
    """アンカー周辺の候補プロファイル群を生成する (grid, numpy)。

    X (Lorentzian 主成分)・W (Gaussian) を係数で、Y をオフセットで摂動。U,V,SH/L,Zero はアンカー据置。
    決定論 (係数の直積順)。
    """
    ...


def search_instrument_profile(
    standard: HistogramSpec,
    structure: PhaseSpec,
    *,
    anchor: InstrumentProfile | None = None,
    candidates: Sequence[Mapping[str, float]] | None = None,
    fwhm_range: tuple[float, float] = (5.0, 120.0),
    refine_sh_l: bool = False,
    optimizer=None,
    runner=None,
) -> InstrumentProfile:
    """物理候補を探索し最良フィットの装置分解能を返す (境界クランプ回避)。

    手順: (1) anchor 未指定なら extract_instrument_profile(constrain_nonneg=True) で物理アンカー。
    (2) candidate_profiles でアンカー周辺候補 (または注入 candidates/optimizer)。
    (3) 各候補: profile_fwhm_min>0 の物理候補のみ、instrument_profile 固定 + recipe=[bg,cell] で評価→Rwp。
    (4) 物理候補のうち Rwp 最小を InstrumentProfile(values, source_rwp, wavelength) で返す。無ければ anchor。

    :param optimizer: 候補提案器 (既定 grid; Bayesian 差し替え用, 未使用なら grid)
    :param runner: 精密化関数 (既定 run_auto_rietveld; テストは stub)
    """
    ...


# extract_instrument_profile_from_standard に search="grid" を追加し、生データから本探索を呼ぶ。
