"""absorption.neutron (組成→中性子 μ/μR) の決定論テスト。"""

from __future__ import annotations

import pytest

from tsumugin.absorption.neutron import crystal_density, neutron_mu, neutron_mu_r

# NaCuHCF·nD2O model6 の単位胞組成 (占有率×多重度)。
_COMP = {"Cu": 2.0, "Fe": 2.0, "C": 12.0, "N": 12.0, "Na": 3.96, "O": 4.74, "D": 9.48}
_V = 565.2  # Å³


def test_crystal_density_nacuhcf():
    rho = crystal_density(_COMP, _V)
    assert rho == pytest.approx(2.165, abs=0.02)


def test_neutron_mu_nacuhcf():
    # 充填率 = 1.014/2.165 ≈ 0.468。
    pack = 1.014 / crystal_density(_COMP, _V)
    mu_abs, mu_scat = neutron_mu(_COMP, _V, packing_fraction=pack)
    assert mu_abs == pytest.approx(0.031, abs=0.003)
    assert mu_scat == pytest.approx(0.29, abs=0.03)


def test_neutron_mu_r_small_for_d2o():
    # D2O 試料は中性子吸収が小さい。R=4mm で μR_abs ~0.01。
    mu_r = neutron_mu_r(_COMP, _V, 0.4, packing_density=1.014)
    assert 0.008 < mu_r < 0.02
    # 散乱込みは大きい。
    mu_r_tot = neutron_mu_r(_COMP, _V, 0.4, packing_density=1.014, include_scattering=True)
    assert mu_r_tot > mu_r


def test_neutron_mu_dominated_by_nitrogen():
    # N が中性子吸収の主寄与 (σ_abs=1.9 barn × 12 原子)。
    from tsumugin.absorption.neutron import NEUTRON_XS

    contribs = {e: n * NEUTRON_XS[e][0] for e, n in _COMP.items()}
    assert max(contribs, key=contribs.get) == "N"


def test_neutron_mu_unknown_element_raises():
    with pytest.raises(KeyError):
        neutron_mu({"Xx": 1.0}, 100.0)
