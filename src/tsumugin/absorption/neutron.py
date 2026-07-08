"""中性子の線減弱係数・μR を組成から算出する (物理ベース吸収補正)。

試料組成 (元素→単位胞あたり原子数) + セル体積 + 充填率から、中性子の線吸収/散乱係数 μ [1/cm] と
円柱試料の μR を計算する。GSAS-II の吸収補正パラメータ (Sample Parameters Absorption) を**組成から
物理的に決める**ための純関数 (numpy 非依存, 標準断面積表を内蔵)。

断面積は 2200 m/s (λ=1.798 Å) の束縛断面積 (barn)。吸収は 1/v 則で λ に比例するため、TOF (可変 λ) では
GSAS-II が μR(1.8Å) を基準に λ スケールする。散乱 (coh+inc) は概ね λ 非依存。

μ[1/cm] = Σ(n_i · σ_i[barn]) / V[Å³]  (結晶) × 充填率(粉末/結晶密度)。μR = μ · R[cm]。
"""

from __future__ import annotations

from typing import Mapping

__all__ = [
    "NEUTRON_XS",
    "crystal_density",
    "neutron_mu",
    "neutron_mu_r",
]

# 元素 → (σ_abs[barn] @1.798Å, σ_scatt_total[barn])。標準値 (Sears 1992 / NIST)。
NEUTRON_XS: dict[str, tuple[float, float]] = {
    "H": (0.3326, 82.02), "D": (0.000519, 7.64),
    "Li": (70.5, 1.37), "B": (767.0, 5.24), "C": (0.0035, 5.551),
    "N": (1.90, 11.51), "O": (0.00019, 4.232), "F": (0.0096, 4.018),
    "Na": (0.530, 3.28), "Mg": (0.063, 3.71), "Al": (0.231, 1.503),
    "Si": (0.171, 2.167), "P": (0.172, 3.312), "S": (0.53, 1.026),
    "Cl": (33.5, 16.8), "K": (2.1, 1.96), "Ca": (0.43, 2.83),
    "Ti": (6.09, 4.35), "V": (5.08, 5.10), "Cr": (3.05, 3.49),
    "Mn": (13.3, 2.15), "Fe": (2.56, 11.62), "Co": (37.18, 5.6),
    "Ni": (4.49, 18.5), "Cu": (3.78, 8.03), "Zn": (1.11, 4.131),
}

# 原子量 (amu)。
_MASS: dict[str, float] = {
    "H": 1.008, "D": 2.014, "Li": 6.94, "B": 10.81, "C": 12.011, "N": 14.007,
    "O": 15.999, "F": 18.998, "Na": 22.990, "Mg": 24.305, "Al": 26.982,
    "Si": 28.085, "P": 30.974, "S": 32.06, "Cl": 35.45, "K": 39.098,
    "Ca": 40.078, "Ti": 47.867, "V": 50.942, "Cr": 51.996, "Mn": 54.938,
    "Fe": 55.845, "Co": 58.933, "Ni": 58.693, "Cu": 63.546, "Zn": 65.38,
}

_AMU_G = 1.660539e-24  # amu → g


def crystal_density(composition: Mapping[str, float], cell_volume_a3: float) -> float:
    """単位胞組成 (元素→原子数) とセル体積 [Å³] から結晶密度 [g/cm³] を返す。🔵"""
    mass_g = sum(n * _MASS[e] for e, n in composition.items()) * _AMU_G
    return mass_g / (cell_volume_a3 * 1e-24)


def neutron_mu(
    composition: Mapping[str, float],
    cell_volume_a3: float,
    *,
    packing_fraction: float = 1.0,
) -> tuple[float, float]:
    """組成から中性子の線吸収/散乱係数 ``(mu_abs, mu_scat)`` [1/cm] @1.798Å を返す。🔵

    :param composition: 単位胞あたりの元素→原子数 (占有率×多重度)
    :param cell_volume_a3: セル体積 [Å³]
    :param packing_fraction: 粉末充填率 (粉末密度/結晶密度)。1.0 で結晶密度相当
    :returns: ``(mu_abs, mu_scat)`` [1/cm]

    Raises:
        KeyError: 断面積表に無い元素が含まれるとき。
    """
    sig_abs = sum(n * NEUTRON_XS[e][0] for e, n in composition.items())
    sig_scat = sum(n * NEUTRON_XS[e][1] for e, n in composition.items())
    mu_abs = sig_abs / cell_volume_a3 * packing_fraction
    mu_scat = sig_scat / cell_volume_a3 * packing_fraction
    return mu_abs, mu_scat


def neutron_mu_r(
    composition: Mapping[str, float],
    cell_volume_a3: float,
    radius_cm: float,
    *,
    packing_density: float | None = None,
    include_scattering: bool = False,
) -> float:
    """円柱試料の μR を組成から算出する (GSAS Absorption 固定値の物理決定用)。🔵

    :param composition: 単位胞あたりの元素→原子数
    :param cell_volume_a3: セル体積 [Å³]
    :param radius_cm: 試料 (キャピラリ/缶) 半径 [cm]
    :param packing_density: 粉末充填密度 [g/cm³] (None なら結晶密度=充填率1.0)
    :param include_scattering: True で散乱も含む総減弱 μR (既定は吸収のみ)
    :returns: μR (無次元)
    """
    pack = 1.0
    if packing_density is not None:
        pack = packing_density / crystal_density(composition, cell_volume_a3)
    mu_abs, mu_scat = neutron_mu(composition, cell_volume_a3, packing_fraction=pack)
    mu = mu_abs + (mu_scat if include_scattering else 0.0)
    return mu * radius_cm
