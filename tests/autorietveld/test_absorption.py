"""Issue #54: 固定吸収体レイヤー補正 (tsumugin.autorietveld.absorption) の numpy コアテスト。"""

from __future__ import annotations

import dataclasses
import math

import numpy as np
import pytest

from tsumugin.autorietveld.absorption import (
    AbsorberLayer,
    apply_absorption_correction,
    mu_from_composition,
    transmission_correction,
    wavelength_to_energy_kev,
)
from tsumugin.autorietveld.model import HistogramSpec, Geometry, Radiation
from tsumugin.insitu.model import FrameSpec


def test_transmission_correction_is_one_at_zero_two_theta():
    layers = (AbsorberLayer(thickness_cm=0.2, mu_cm=0.4),)
    f = transmission_correction([0.0], layers)
    assert f[0] == pytest.approx(1.0)


def test_transmission_correction_strictly_increasing_with_two_theta():
    layers = (AbsorberLayer(thickness_cm=0.2, mu_cm=0.4),)
    tt = np.array([0.0, 5.0, 10.0, 20.0, 30.0])
    f = transmission_correction(tt, layers)
    assert np.all(np.diff(f) > 0)


def test_transmission_correction_matches_formula_at_sample_angle():
    mu, t = 0.4, 0.2
    layers = (AbsorberLayer(thickness_cm=t, mu_cm=mu),)
    two_theta = 17.0
    f = transmission_correction([two_theta], layers)
    expected = math.exp(mu * t * (1.0 / math.cos(math.radians(two_theta)) - 1.0))
    assert f[0] == pytest.approx(expected, rel=1e-10)


def test_transmission_correction_empty_layers_is_ones():
    tt = np.array([0.0, 10.0, 20.0])
    f = transmission_correction(tt, ())
    assert np.allclose(f, 1.0)


def test_transmission_correction_two_layers_is_product():
    l1 = AbsorberLayer(thickness_cm=0.2, mu_cm=0.4)
    l2 = AbsorberLayer(thickness_cm=0.1, mu_cm=0.3)
    tt = np.array([10.0, 20.0])
    f_combined = transmission_correction(tt, (l1, l2))
    f1 = transmission_correction(tt, (l1,))
    f2 = transmission_correction(tt, (l2,))
    assert np.allclose(f_combined, f1 * f2)


def test_transmission_correction_unknown_geometry_raises():
    layer = AbsorberLayer(thickness_cm=0.2, mu_cm=0.4, geometry="reflection")
    with pytest.raises(ValueError):
        transmission_correction([10.0], (layer,))


def test_apply_absorption_correction_scales_y_and_w():
    x = np.array([0.0, 10.0, 20.0])
    y = np.array([100.0, 200.0, 300.0])
    w = np.array([1.0, 2.0, 3.0])
    layers = (AbsorberLayer(thickness_cm=0.2, mu_cm=0.4),)
    y2, w2 = apply_absorption_correction(x, y, w, layers)
    f = transmission_correction(x, layers)
    assert np.allclose(y2, y * f)
    assert np.allclose(w2, w / f**2)
    assert len(y2) == len(x)
    assert len(w2) == len(x)


def test_apply_absorption_correction_no_layers_is_identity():
    x = np.array([0.0, 10.0])
    y = np.array([100.0, 200.0])
    w = np.array([1.0, 2.0])
    y2, w2 = apply_absorption_correction(x, y, w, ())
    assert np.allclose(y2, y)
    assert np.allclose(w2, w)


def test_wavelength_to_energy_kev():
    assert wavelength_to_energy_kev(0.501345) == pytest.approx(24.73, abs=0.05)


def test_absorber_layer_is_frozen_and_round_trips():
    layer = AbsorberLayer(thickness_cm=0.2, mu_cm=0.394)
    with pytest.raises(dataclasses.FrozenInstanceError):
        layer.mu_cm = 1.0  # type: ignore[misc]
    d = layer.to_dict()
    layer2 = AbsorberLayer.from_dict(d)
    assert layer2 == layer


def test_histogram_spec_absorber_layers_round_trip_with_layers():
    h = HistogramSpec(
        data_path="a.xye",
        instrument_path="a.instprm",
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        absorber_layers=(AbsorberLayer(thickness_cm=0.2, mu_cm=0.394),),
    )
    d = h.to_dict()
    h2 = HistogramSpec.from_dict(d)
    assert h2.absorber_layers == h.absorber_layers


def test_histogram_spec_absorber_layers_round_trip_without_layers():
    h = HistogramSpec(
        data_path="a.xye",
        instrument_path="a.instprm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    assert h.absorber_layers == ()
    d = h.to_dict()
    assert d["absorber_layers"] == []
    h2 = HistogramSpec.from_dict(d)
    assert h2.absorber_layers == ()


def test_frame_spec_absorber_layers_round_trip_with_layers():
    frame = FrameSpec(
        data_path="frame0.xye",
        axis_value=1.0,
        absorber_layers=(AbsorberLayer(thickness_cm=0.2, mu_cm=0.394),),
    )
    d = frame.to_dict()
    frame2 = FrameSpec.from_dict(d)
    assert frame2.absorber_layers == frame.absorber_layers


def test_frame_spec_absorber_layers_round_trip_without_layers():
    frame = FrameSpec(data_path="frame0.xye")
    assert frame.absorber_layers == ()
    d = frame.to_dict()
    assert d["absorber_layers"] == []
    frame2 = FrameSpec.from_dict(d)
    assert frame2.absorber_layers == ()


def test_mu_from_composition_electrolyte_sanity_check():
    periodictable = pytest.importorskip("periodictable")
    del periodictable  # 存在確認のみ (importorskip が未導入なら skip する)

    elements_mol = {
        "C": 45.99,
        "H": 65.24,
        "O": 40.12,
        "Na": 1.0,
        "P": 1.1,
        "F": 6.6,
        "K": 0.1,
    }
    mu = mu_from_composition(elements_mol, volume_cm3=1090.0, energy_kev=24.73)
    assert mu == pytest.approx(0.394, abs=0.03)
