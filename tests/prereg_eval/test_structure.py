"""P0 §1.3: 規格化偏差 u・事例の指標 D (RMS)・n_out (u > 3)。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.prereg_eval.structure import (
    FitValue,
    RefValue,
    deviations,
    metrics,
)

CUBIC_10 = np.eye(3) * 10.0  # a = 10 Å の立方格子 (分率 0.001 = 0.01 Å)


def _coord(key, frac, sigma=(0.0, 0.0, 0.0)):
    return RefValue("coord", key, tuple(frac), tuple(sigma))


def _fit_coord(key, frac, sigma=(0.0, 0.0, 0.0), refined=True):
    return FitValue("coord", key, tuple(frac), tuple(sigma), refined)


def test_coordinate_deviation_is_a_cartesian_distance_with_a_floor():
    ref = [_coord("O1", (0.1, 0.2, 0.3), (0.0005, 0.0005, 0.0005))]
    # x だけ 0.003 (= 0.03 Å) ずれる。σ_c = √(0.005² + 0.004²) Å (x 方向だけ効く) ≈ 0.0064 → 床 0.02/3 ≈ 0.00667 が勝つ
    fit = [_fit_coord("O1", (0.103, 0.2, 0.3), (0.0004, 0.0004, 0.0004))]
    d = deviations(ref, fit, lattice=CUBIC_10)
    assert d.values["O1"] == pytest.approx(0.03 / (0.02 / 3), rel=1e-9)


def test_esd_beats_the_floor_when_larger():
    ref = [_coord("O1", (0.1, 0.2, 0.3), (0.003, 0.0, 0.0))]
    fit = [_fit_coord("O1", (0.109, 0.2, 0.3), (0.004, 0.0, 0.0))]
    d = deviations(ref, fit, lattice=CUBIC_10)
    # |Δr| = 0.09 Å, σ_c = 0.05 Å
    assert d.values["O1"] == pytest.approx(0.09 / 0.05, rel=1e-9)


def test_unrefined_values_count_with_zero_fit_esd():
    ref = [RefValue("occupancy", "Fe1", 0.60, 0.01)]
    refined = deviations(ref, [FitValue("occupancy", "Fe1", 0.50, 0.03, True)], lattice=CUBIC_10)
    frozen = deviations(ref, [FitValue("occupancy", "Fe1", 0.50, 0.03, False)], lattice=CUBIC_10)
    # 凍結した値は σ_fit = 0 (凍結に無料の得点を与えない)
    assert frozen.values["Fe1"] == pytest.approx(0.10 / max(0.01, 0.02 / 3), rel=1e-9)
    assert refined.values["Fe1"] == pytest.approx(0.10 / math.hypot(0.01, 0.03), rel=1e-9)


def test_cell_uses_a_relative_floor():
    ref = [RefValue("cell", "a", 10.0, 0.0)]
    d = deviations(ref, [FitValue("cell", "a", 10.0005, 0.0, True)], lattice=CUBIC_10)
    # 床は相対 1e-4 → σ_c の下限 = 10 × 1e-4 / 3
    assert d.values["a"] == pytest.approx(0.0005 / (10.0 * 1e-4 / 3), rel=1e-9)


def test_reference_without_esd_is_unevaluated():
    ref = [RefValue("occupancy", "Fe1", 0.6, None), _coord("O1", (0.1, 0.1, 0.1), (0.001, None, 0.001))]
    fit = [FitValue("occupancy", "Fe1", 0.6, 0.01, True), _fit_coord("O1", (0.1, 0.1, 0.1))]
    d = deviations(ref, fit, lattice=CUBIC_10)
    assert d.values == {}
    assert set(d.unevaluated) == {"Fe1", "O1"}


def test_missing_fit_value_is_unevaluated_not_a_pass():
    ref = [RefValue("occupancy", "Fe1", 0.6, 0.01)]
    d = deviations(ref, [], lattice=CUBIC_10)
    assert d.values == {} and d.unevaluated == ("Fe1",)


def test_common_denominator_uses_the_larger_fit_esd_of_both_arms():
    ref = [RefValue("occupancy", "Fe1", 0.60, 0.01)]
    tight = [FitValue("occupancy", "Fe1", 0.50, 0.01, True)]
    loose = [FitValue("occupancy", "Fe1", 0.50, 0.10, True)]
    alone = deviations(ref, tight, lattice=CUBIC_10).values["Fe1"]
    shared = deviations(ref, tight, lattice=CUBIC_10, other=loose).values["Fe1"]
    # 悪い (esd の大きい) 相手が居ると分母が共通になり、こちらの偏差も同じ物差しで測られる
    assert shared == pytest.approx(0.10 / math.hypot(0.01, 0.10), rel=1e-9)
    assert shared < alone


def test_metrics_rms_and_outliers():
    m = metrics({"a": 1.0, "b": 3.0, "c": 4.0}, unevaluated=("d",))
    assert m.d == pytest.approx(math.sqrt((1 + 9 + 16) / 3))
    assert m.n_out == 1  # u > 3 は厳密に大きい側だけ (3.0 は外れでない)
    assert m.n_evaluated == 3 and m.n_unevaluated == 1


def test_metrics_of_nothing_is_unevaluated():
    m = metrics({}, unevaluated=("x",))
    assert m.d is None and m.n_out is None and m.n_unevaluated == 1


def test_non_orthogonal_lattice_is_used_for_distances():
    # 六方 a = 10 Å: 分率 (0.01, 0.01, 0) は 10 × 0.01 Å の長さ (120° の a, b)
    a = 10.0
    hexagonal = np.array([[a, 0, 0], [-a / 2, a * math.sqrt(3) / 2, 0], [0, 0, 7.0]])
    ref = [_coord("P1", (0.0, 0.0, 0.0), (0.0001, 0.0001, 0.0001))]
    fit = [_fit_coord("P1", (0.01, 0.01, 0.0))]
    d = deviations(ref, fit, lattice=hexagonal)
    assert d.values["P1"] == pytest.approx(0.1 / (0.02 / 3), rel=1e-6)


def test_common_denominator_applies_per_axis_for_coordinates():
    ref = [_coord("O1", (0.1, 0.2, 0.3), (0.001, 0.001, 0.001))]
    tight = [_fit_coord("O1", (0.11, 0.2, 0.3), (0.001, 0.001, 0.001))]
    loose = [_fit_coord("O1", (0.11, 0.2, 0.3), (0.01, 0.001, 0.001))]
    shared = deviations(ref, tight, lattice=CUBIC_10, other=loose).values["O1"]
    # x 方向の σ は大きい方 (0.01 → 0.1 Å) に揃う
    assert shared == pytest.approx(0.1 / (10 * math.hypot(0.001, 0.01)), rel=1e-9)
