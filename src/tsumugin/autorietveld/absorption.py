"""固定吸収体レイヤー補正 (operando/in-situ セルの電解液層・窓材)。

operando/in-situ セルでは電解液層・窓材など固定の吸収体がビーム路に入り、その透過率が
2θ 依存になる (平板配置: 回折ビーム路長 ∝ t/cos2θ)。Rietveld のスケール因子と縮退する
**定数部** (μt) を除き、**角度依存部**のみを観測強度の補正として与える (Issue #54)。

numpy コアのみで完結する (`transmission_correction`/`apply_absorption_correction`)。組成から
線減衰係数 μ を求める `mu_from_composition` のみ `periodictable` を遅延 import する境界。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np


@dataclass(frozen=True)
class AbsorberLayer:
    """固定吸収体 1 層の仕様 (不変)。

    :param thickness_cm: 層厚 t [cm]
    :param mu_cm: 線減衰係数 μ [1/cm] (`mu_from_composition` 等で求める)
    :param geometry: 補正ジオメトリ。既定 "transmission" (平板透過: 回折ビーム路長 ∝ t/cos2θ)。
        現状は "transmission" のみ対応 (他値は `transmission_correction` が ValueError)。
    """

    thickness_cm: float
    mu_cm: float
    geometry: str = "transmission"

    def to_dict(self) -> dict[str, object]:
        return {
            "thickness_cm": self.thickness_cm,
            "mu_cm": self.mu_cm,
            "geometry": self.geometry,
        }

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> "AbsorberLayer":
        return cls(
            thickness_cm=float(d["thickness_cm"]),  # type: ignore[arg-type]
            mu_cm=float(d["mu_cm"]),  # type: ignore[arg-type]
            geometry=str(d.get("geometry", "transmission")),
        )


def transmission_correction(
    two_theta_deg: "float | Sequence[float] | np.ndarray",
    layers: Sequence[AbsorberLayer],
) -> np.ndarray:
    """2θ [deg] における吸収体レイヤー群の透過率補正係数 (角度依存部のみ)。

    各層について ``exp( μ·t·(1/cos(2θ) − 1) )`` を計算し、全層の積を返す。定数部 (μt) は
    スケール因子と縮退するため含めない (2θ=0 で厳密に 1)。多層は積で合成する。

    :param two_theta_deg: 2θ [deg] (スカラーまたは配列)
    :param layers: 吸収体レイヤーの列 (空なら補正なし=1)
    :returns: 補正係数 (``two_theta_deg`` と同形の ndarray)
    :raises ValueError: 未対応の geometry を含む場合
    """
    tt = np.asarray(two_theta_deg, dtype=float)
    factor = np.ones_like(tt)
    rad = np.deg2rad(tt)
    inv_cos_minus_1 = 1.0 / np.cos(rad) - 1.0
    for layer in layers:
        if layer.geometry != "transmission":
            raise ValueError(f"未対応の吸収体ジオメトリ: {layer.geometry!r}")
        factor = factor * np.exp(layer.mu_cm * layer.thickness_cm * inv_cos_minus_1)
    return factor


def apply_absorption_correction(
    x: "Sequence[float] | np.ndarray",
    y: "Sequence[float] | np.ndarray",
    w: "Sequence[float] | np.ndarray",
    layers: Sequence[AbsorberLayer],
) -> tuple[np.ndarray, np.ndarray]:
    """観測強度 y と GSAS-II 重み w (=1/σ²) へ吸収体補正を適用する。

    強度を係数 f で乗じるとσも f 倍されるため、重みは 1/f² 倍する。

    :param x: 2θ [deg] 配列
    :param y: 観測強度 (Yobs)
    :param w: GSAS-II 重み (1/σ²)
    :param layers: 吸収体レイヤーの列
    :returns: (補正後 y, 補正後 w)
    """
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    w_arr = np.asarray(w, dtype=float)
    f = transmission_correction(x_arr, layers)
    return y_arr * f, w_arr / f**2


def wavelength_to_energy_kev(lam_angstrom: float) -> float:
    """波長 [Å] から X 線光子エネルギー [keV] を求める (E = 12.39842 / λ)。"""
    return 12.39842 / lam_angstrom


def mu_from_composition(
    elements_mol: Mapping[str, float],
    volume_cm3: float,
    energy_kev: float,
) -> float:
    """組成 (元素→モル数) と体積から線減衰係数 μ [1/cm] を求める (periodictable 遅延 import)。

    ``μ = 2·r_e·λ_cm·Σ_i (n_i·N_A/V)·f''_i`` (原子散乱因子の虚部 f'' による吸収)。

    :param elements_mol: 元素記号→モル数 (体積 ``volume_cm3`` 中の全量)
    :param volume_cm3: 体積 [cm³]
    :param energy_kev: X 線光子エネルギー [keV] (`wavelength_to_energy_kev` で波長から変換可)
    :returns: μ [1/cm]
    :raises ImportError: periodictable 未導入 (`pip install periodictable` / extra "absorption")
    """
    try:
        import periodictable
    except ImportError as exc:  # pragma: no cover - 導入依存のみで分岐
        raise ImportError(
            "mu_from_composition には periodictable が必要です。"
            ' `uv sync --extra absorption` (または `pip install periodictable`) で'
            "インストールしてください。"
        ) from exc

    r_e_cm = 2.8179403e-13  # 古典電子半径 [cm]
    n_a = 6.02214e23  # アボガドロ数 [1/mol]
    lam_angstrom = 12.39842 / energy_kev
    lam_cm = lam_angstrom * 1e-8

    total = 0.0
    for symbol, n_mol in elements_mol.items():
        element = getattr(periodictable, symbol)
        _f1, f2 = element.xray.scattering_factors(energy=energy_kev)
        number_density = n_mol * n_a / volume_cm3  # [1/cm^3]
        total += number_density * float(f2)

    return 2.0 * r_e_cm * lam_cm * total
