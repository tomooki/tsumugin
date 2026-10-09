"""TASK-0806: HistogramSpec/PhaseSpec の to_dict/from_dict (MCP JSON 露出用)。

Enum は値文字列に、tuple は list に写像し、json.dumps(allow_nan=False) 安全な素の型のみを返す。
from_dict は往復同型 (round-trip) を保証する (architecture.md §6)。
"""

from __future__ import annotations

import json

import pytest

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


# ---------------------------------------------------------------------------
# JSON 経路の null / 型取り違え (③ は LLM — null は「未指定」、型違いは大声で落とす)
# ---------------------------------------------------------------------------
#
# 旧実装は `bool(d.get("refine_cell", True))` で、③ が「未指定」のつもりで送った null を
# `bool(None) == False` = **格子凍結**に読み替えていた (GSAS は Cell 段を飛ばし、TOPAS は格子
# prm を固定する — どちらも例外を出さず、相の格子が初期値のまま出版される)。文字列 "false" は
# 逆に `bool("false") == True`。ラベル列は `or ()` + `tuple(...)` だったので、裸の文字列
# "O7" が ("O", "7") に分解され、engine はラベルを fail-open で照合するため**何も凍結しない**。

_PHASE_BASE = {"structure_path": "a.cif", "phase_name": "A"}
_HIST_BASE = {
    "data_path": "d.xye",
    "instrument_path": "i.instprm",
    "radiation": "xray_lab",
    "geometry": "bragg_brentano",
}


def _phase(**kw):
    return PhaseSpec.from_dict({**_PHASE_BASE, **kw})


def _hist(**kw):
    return HistogramSpec.from_dict({**_HIST_BASE, **kw})


def test_refine_cell_null_means_unspecified_not_frozen():
    assert _phase(refine_cell=None).refine_cell is True


def test_refine_cell_missing_key_defaults_to_refined():
    assert PhaseSpec.from_dict(_PHASE_BASE).refine_cell is True


@pytest.mark.parametrize("value", [True, False])
def test_refine_cell_accepts_real_booleans(value):
    assert _phase(refine_cell=value).refine_cell is value


@pytest.mark.parametrize("value", ["false", "true", "False", 0, 1, 0.0, [], {}])
def test_refine_cell_rejects_non_booleans(value):
    with pytest.raises(ValueError, match="refine_cell は真偽値"):
        _phase(refine_cell=value)


_LABEL_FIELDS = (
    "free_occupancy_labels",
    "free_uiso_labels",
    "frozen_coord_labels",
    "frozen_uiso_labels",
)
_GROUP_FIELDS = (
    "mixed_occupancy_groups",
    "occupancy_equiv_groups",
    "position_equiv_groups",
    "occupancy_sum_groups",
)


@pytest.mark.parametrize("key", _LABEL_FIELDS)
def test_label_list_rejects_a_bare_string(key):
    # "O7" を受けると ("O", "7") になり、存在しないラベルとして黙って無視される。
    with pytest.raises(ValueError, match=f"{key} は原子ラベル"):
        _phase(**{key: "O7"})


@pytest.mark.parametrize("key", _LABEL_FIELDS)
def test_label_list_rejects_non_string_elements(key):
    with pytest.raises(ValueError, match=f"{key} の要素"):
        _phase(**{key: ["O7", 7]})


@pytest.mark.parametrize("key", _LABEL_FIELDS)
@pytest.mark.parametrize("value", [False, 0, {"O7": True}])
def test_label_list_rejects_non_list_values(key, value):
    with pytest.raises(ValueError, match=f"{key} は原子ラベル"):
        _phase(**{key: value})


@pytest.mark.parametrize("key", _GROUP_FIELDS)
def test_group_list_rejects_a_flat_label_list(key):
    # 平坦な ["Fe1", "Al1"] は (("F","e","1"), ("A","l","1")) になり、拘束が 1 本も張られない。
    with pytest.raises(ValueError, match=f"{key} の要素"):
        _phase(**{key: ["Fe1", "Al1"]})


@pytest.mark.parametrize("key", _GROUP_FIELDS)
def test_group_list_rejects_a_bare_string(key):
    with pytest.raises(ValueError, match=f"{key} は原子ラベルの組"):
        _phase(**{key: "Fe1"})


@pytest.mark.parametrize("key", _GROUP_FIELDS)
def test_group_list_accepts_lists_and_tuples(key):
    assert getattr(_phase(**{key: [["Fe1", "Al1"], ("O1", "D1")]}), key) == (
        ("Fe1", "Al1"),
        ("O1", "D1"),
    )


@pytest.mark.parametrize(
    "key, default",
    [
        ("format_hint", "CIF"),
        ("mixed_occupancy_groups", ()),
        ("free_occupancy_labels", ()),
        ("occupancy_equiv_groups", ()),
        ("free_uiso_labels", None),  # None = 未指定 (全原子解放) — [] (凍結) と別物 (#189)
        ("position_equiv_groups", ()),
        ("occupancy_sum_groups", ()),
        ("frozen_coord_labels", ()),
        ("frozen_uiso_labels", ()),
        ("refine_cell", True),
        ("temperature", None),
    ],
)
def test_phase_spec_null_is_the_field_default(key, default):
    assert getattr(_phase(**{key: None}), key) == default
    assert getattr(PhaseSpec("a.cif", "A"), key) == default  # 表が dataclass 既定とずれない


def test_free_uiso_labels_empty_list_still_means_frozen():
    # null → 既定 (None) にしたことで [] (明示的に凍結) まで潰れていないこと (#189)。
    assert _phase(free_uiso_labels=[]).free_uiso_labels == ()


@pytest.mark.parametrize("key", ["structure_path", "phase_name"])
def test_phase_spec_required_string_rejects_null(key):
    # str(None) == "None" — 相名 "None" / パス "None" で黙って進めない。
    with pytest.raises(ValueError, match=f"{key} に null"):
        _phase(**{key: None})


@pytest.mark.parametrize("key", ["structure_path", "phase_name"])
def test_phase_spec_required_string_missing_is_still_a_key_error(key):
    # insitu の `_parse_known_phases` は KeyError を「必須キーがありません」へ言い換える契約。
    d = dict(_PHASE_BASE)
    del d[key]
    with pytest.raises(KeyError):
        PhaseSpec.from_dict(d)


@pytest.mark.parametrize("value", [1, ["CIF"], True])
def test_format_hint_rejects_non_strings(value):
    with pytest.raises(ValueError, match="format_hint は文字列"):
        _phase(format_hint=value)


@pytest.mark.parametrize("value", ["300", True, [300.0]])
def test_phase_temperature_rejects_non_numbers(value):
    with pytest.raises(ValueError, match="temperature は数値"):
        _phase(temperature=value)


def test_phase_temperature_accepts_int_and_float():
    assert _phase(temperature=300).temperature == 300.0
    assert _phase(temperature=10.5).temperature == 10.5


@pytest.mark.parametrize(
    "key, default",
    [
        ("data_format", "GSAS"),
        ("bank", None),
        ("two_theta_limits", None),
        ("excluded_regions", ()),
        ("temperature", None),
        ("weight", 1.0),
        ("absorption", 0.0),
        ("instrument_profile", None),
        ("profile_bounds", None),
        ("absorber_layers", ()),
    ],
)
def test_histogram_spec_null_is_the_field_default(key, default):
    assert getattr(_hist(**{key: None}), key) == default
    base = HistogramSpec("d.xye", "i.instprm", Radiation.XRAY_LAB, Geometry.BRAGG_BRENTANO)
    assert getattr(base, key) == default  # 表が dataclass 既定とずれない


@pytest.mark.parametrize("key", ["data_path", "instrument_path"])
def test_histogram_spec_required_string_rejects_null(key):
    with pytest.raises(ValueError, match=f"{key} に null"):
        _hist(**{key: None})


@pytest.mark.parametrize("value", [1, ["GSAS"], True])
def test_data_format_rejects_non_strings(value):
    with pytest.raises(ValueError, match="data_format は文字列"):
        _hist(data_format=value)


@pytest.mark.parametrize("key", ["weight", "absorption", "temperature"])
@pytest.mark.parametrize("value", ["2", True, [2.0]])
def test_histogram_numbers_reject_non_numbers(key, value):
    # True は float() で 1.0 になる — 「重み 1」「吸収 1」を黙って作らない。
    with pytest.raises(ValueError, match=f"{key} は数値"):
        _hist(**{key: value})


@pytest.mark.parametrize("value", ["2", True, 2.5])
def test_bank_rejects_non_integers(value):
    with pytest.raises(ValueError, match="bank は整数"):
        _hist(bank=value)


def test_bank_accepts_an_integral_float():
    # JSON クライアントは int/float を区別しないことがある (`_config_spec` と同じ扱い)。
    bank = _hist(bank=2.0).bank
    assert bank == 2 and isinstance(bank, int)


def test_full_phase_spec_survives_a_json_round_trip():
    p = PhaseSpec(
        structure_path="g.cif",
        phase_name="garnet",
        format_hint="EXP",
        mixed_occupancy_groups=(("Fe1", "Al1"),),
        free_occupancy_labels=("Ow",),
        occupancy_equiv_groups=(("O1", "DO11", "DO12"),),
        free_uiso_labels=(),
        position_equiv_groups=(("H1", "D1"),),
        occupancy_sum_groups=(("O1", "H1", "D1"),),
        frozen_coord_labels=("D1",),
        refine_cell=False,
        temperature=10.0,
        frozen_uiso_labels=("H1",),
    )
    assert PhaseSpec.from_dict(json.loads(json.dumps(p.to_dict()))) == p


def test_full_histogram_spec_survives_a_json_round_trip():
    h = HistogramSpec(
        data_path="d.fxye",
        instrument_path="i.prm",
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="FXYE",
        bank=2,
        two_theta_limits=(2.5, 32.0),
        excluded_regions=((10.0, 11.0),),
        temperature=298.0,
        weight=2.0,
        absorption=0.3,
        profile_bounds={"U": (0.0, None)},
    )
    assert HistogramSpec.from_dict(json.loads(json.dumps(h.to_dict()))) == h
