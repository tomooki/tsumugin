"""JSON ↔ discrimination 入力の marshaling ヘルパ (Issue #130 L3) のテスト。

numpy-only・GSAS 非依存。往復同型 (to_dict→from_dict でビット等価)・不正入力の ValueError・
FrameSeries のファイルスタック/生配列両経路を検証する。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.mcp._discriminate_spec import (
    fixed_phase_from_dict,
    fixed_phase_to_dict,
    frame_series_from_spec,
    lattice_from_dict,
    lattice_to_dict,
    phase_instance_from_dict,
    phase_instance_to_dict,
)
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.operando.cell_phases import FixedPhaseSpec


# --- LatticeParams ---


def test_lattice_roundtrip():
    lat = LatticeParams(8.48, 5.40, 6.96, alpha=90.0, beta=90.0, gamma=90.0)
    d = lattice_to_dict(lat)
    assert d == {"a": 8.48, "b": 5.40, "c": 6.96, "alpha": 90.0, "beta": 90.0, "gamma": 90.0}
    back = lattice_from_dict(d)
    assert (back.a, back.b, back.c, back.alpha, back.beta, back.gamma) == (
        8.48, 5.40, 6.96, 90.0, 90.0, 90.0,
    )


def test_lattice_from_dict_defaults_angles_to_90():
    lat = lattice_from_dict({"a": 5.0, "b": 5.0, "c": 5.0})
    assert lat.alpha == 90.0 and lat.beta == 90.0 and lat.gamma == 90.0


def test_lattice_from_dict_missing_length_raises():
    with pytest.raises(ValueError):
        lattice_from_dict({"a": 5.0, "b": 5.0})  # c 欠落


def test_lattice_to_dict_drops_sigma():
    # σ は当該 refine 由来の出力であって入力 spec には載せない (往復で消える)
    lat = LatticeParams(5, 5, 5, sigma={"a": 0.01}, sigma_source="covariance")
    d = lattice_to_dict(lat)
    assert "sigma" not in d and "sigma_source" not in d


# --- PhaseInstance ---


def test_phase_instance_roundtrip_with_structure_ref():
    p = PhaseInstance(
        phase_ref="pbso4",
        lattice=LatticeParams(8.48, 5.40, 6.96),
        scale=1.5,
        wt_frac=0.6,
        occupancies={"Pb": 0.97},
        structure_ref="/data/PbSO4.cif",
    )
    d = phase_instance_to_dict(p)
    back = phase_instance_from_dict(d)
    assert back.phase_ref == "pbso4"
    assert back.scale == 1.5
    assert back.wt_frac == 0.6
    assert dict(back.occupancies) == {"Pb": 0.97}
    assert back.structure_ref == "/data/PbSO4.cif"
    assert back.lattice.a == 8.48


def test_phase_instance_minimal_defaults():
    p = phase_instance_from_dict(
        {"phase_ref": "a", "lattice": {"a": 5.0, "b": 5.0, "c": 5.0}}
    )
    assert p.scale == 1.0
    assert p.wt_frac is None
    assert p.structure_ref is None
    assert dict(p.occupancies) == {}


def test_phase_instance_missing_required_raises():
    with pytest.raises(ValueError):
        phase_instance_from_dict({"lattice": {"a": 5.0, "b": 5.0, "c": 5.0}})  # phase_ref 欠落
    with pytest.raises(ValueError):
        phase_instance_from_dict({"phase_ref": "a"})  # lattice 欠落


# --- FixedPhaseSpec ---


def test_fixed_phase_roundtrip():
    fp = FixedPhaseSpec(
        phase=PhaseInstance(phase_ref="Al", lattice=LatticeParams(4.05, 4.05, 4.05)),
        label="Al",
    )
    d = fixed_phase_to_dict(fp)
    back = fixed_phase_from_dict(d)
    assert back.label == "Al"
    assert back.phase.phase_ref == "Al"
    assert back.phase.lattice.a == 4.05


# --- FrameSeries ---


def test_frame_series_from_raw_arrays():
    spec = {
        "two_theta": [10.0, 10.1, 10.2],
        "intensities": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]],
    }
    series = frame_series_from_spec(spec, loader=None)
    assert series.two_theta.tolist() == [10.0, 10.1, 10.2]
    assert series.intensities.shape == (2, 3)
    assert series.intensities[1].tolist() == [4.0, 5.0, 6.0]


def test_frame_series_from_files_stacks_rows():
    # loader(path) -> (two_theta, intensity) を注入し、行スタックされることを確認
    grid = np.array([10.0, 10.1, 10.2])

    def fake_loader(path: str):
        idx = int(path.split("_")[-1])
        return grid, grid * 0 + idx

    spec = {"data_paths": ["f_0", "f_1", "f_2"]}
    series = frame_series_from_spec(spec, loader=fake_loader)
    assert series.intensities.shape == (3, 3)
    assert series.two_theta.tolist() == [10.0, 10.1, 10.2]
    assert series.intensities[2].tolist() == [2.0, 2.0, 2.0]


def test_frame_series_empty_spec_raises():
    with pytest.raises(ValueError):
        frame_series_from_spec({}, loader=None)


def test_frame_series_mismatched_grid_raises():
    grid_a = np.array([10.0, 10.1, 10.2])
    grid_b = np.array([10.0, 10.1])  # 長さ違い

    def bad_loader(path: str):
        return (grid_a if path == "a" else grid_b), np.zeros(3 if path == "a" else 2)

    with pytest.raises(ValueError):
        frame_series_from_spec({"data_paths": ["a", "b"]}, loader=bad_loader)


def test_frame_series_files_without_loader_raises():
    # data_paths を渡したのに loader 未注入は明示エラー (到達可能性: ② は load_pattern を渡す)
    with pytest.raises(ValueError):
        frame_series_from_spec({"data_paths": ["a"]}, loader=None)
