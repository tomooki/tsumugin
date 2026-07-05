"""TASK-0806: HistogramSpec/PhaseSpec の to_dict/from_dict (MCP JSON 露出用)。

Enum は値文字列に、tuple は list に写像し、json.dumps(allow_nan=False) 安全な素の型のみを返す。
from_dict は往復同型 (round-trip) を保証する (architecture.md §6)。
"""

from __future__ import annotations

import json

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation


def test_histogram_spec_roundtrip():
    h = HistogramSpec(
        data_path="d.fxye",
        instrument_path="i.prm",
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="FXYE",
        bank=2,
        two_theta_limits=(2.5, 32.0),
        temperature=298.0,
    )
    d = h.to_dict()
    # Enum は値文字列
    assert d["radiation"] == "neutron_tof"
    assert d["geometry"] == "debye_scherrer"
    assert d["two_theta_limits"] == [2.5, 32.0]
    # JSON 安全
    json.dumps(d, allow_nan=False)
    # 往復同型
    assert HistogramSpec.from_dict(d) == h


def test_histogram_spec_roundtrip_with_none_optionals():
    h = HistogramSpec(
        data_path="d.xra",
        instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    d = h.to_dict()
    assert d["two_theta_limits"] is None and d["bank"] is None and d["temperature"] is None
    assert HistogramSpec.from_dict(d) == h


def test_phase_spec_roundtrip():
    p = PhaseSpec(
        structure_path="g.cif",
        phase_name="garnet",
        format_hint="CIF",
        mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
        temperature=10.0,
    )
    d = p.to_dict()
    assert d["mixed_occupancy_groups"] == [["Fe1", "Al1"], ["Al2", "Fe2"]]
    json.dumps(d, allow_nan=False)
    assert PhaseSpec.from_dict(d) == p


def test_phase_spec_roundtrip_defaults():
    p = PhaseSpec(structure_path="a.cif", phase_name="nac")
    d = p.to_dict()
    assert d["mixed_occupancy_groups"] == []
    assert PhaseSpec.from_dict(d) == p


def test_from_dict_ignores_unknown_extra_keys_gracefully():
    # 余分なキー (server 側の handle メタ等) があっても既知フィールドのみで復元
    h = HistogramSpec(
        data_path="d.xra",
        instrument_path="i.prm",
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
    )
    d = h.to_dict()
    d["_handle"] = "abc"
    assert HistogramSpec.from_dict(d) == h
