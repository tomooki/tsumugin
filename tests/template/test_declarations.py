"""fit-then-judge P1-1B タスク 4: 入力宣言と範囲 (REQ-FTJ-1B-201〜203)。"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.errors import TsumuginError
from tsumugin.store import Ledger
from tsumugin.template.declarations import (
    TemplateDeclarations,
    TemplateScopeError,
    check_template_scope,
    record_declarations,
)


def _hist(radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO) -> HistogramSpec:
    return HistogramSpec(
        data_path="d.xye", instrument_path="i.instprm", radiation=radiation, geometry=geometry
    )


_PHASES = [PhaseSpec("a.cif", "A"), PhaseSpec("b.cif", "B")]


def test_no_declaration_means_undeclared():
    d = TemplateDeclarations.from_dict(None)
    assert d == TemplateDeclarations()
    assert d.declared_ids() == ()


def test_declarations_round_trip_through_json():
    import json

    d = TemplateDeclarations.from_dict(
        {"instrument_calibrated": True, "internal_standard": "B", "target_phase": "A",
         "zero_calibrated": False}
    )
    assert TemplateDeclarations.from_dict(json.loads(json.dumps(d.to_dict()))) == d
    assert d.declared_ids() == (
        "instrument_calibrated", "internal_standard", "target_phase", "zero_calibrated"
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"target_phas": "A"},  # 綴り違いを黙って捨てない
        {"instrument_calibrated": "true"},  # 文字列の真偽
        {"internal_standard": 3},
        ["target_phase"],
    ],
)
def test_malformed_declarations_are_refused(bad):
    with pytest.raises(ValueError):
        TemplateDeclarations.from_dict(bad)


def test_declared_phase_names_must_exist():
    with pytest.raises(ValueError, match="C"):
        TemplateDeclarations(target_phase="C").check_phases(_PHASES)
    with pytest.raises(ValueError, match="Z"):
        TemplateDeclarations(internal_standard="Z").check_phases(_PHASES)
    TemplateDeclarations(target_phase="A", internal_standard="B").check_phases(_PHASES)


@pytest.mark.parametrize(
    ("hists", "backend"),
    [
        ([_hist(Radiation.NEUTRON_CW)], "gsasii"),
        ([_hist(Radiation.NEUTRON_TOF)], "gsasii"),
        ([_hist(), _hist()], "gsasii"),  # joint
        ([], "gsasii"),
        ([_hist()], "topas"),
    ],
)
def test_out_of_scope_inputs_fail_loudly(hists, backend):
    with pytest.raises(TemplateScopeError) as e:
        check_template_scope(hists, _PHASES, backend=backend)
    assert isinstance(e.value, TsumuginError) and isinstance(e.value, ValueError)


@pytest.mark.parametrize("rad", [Radiation.XRAY_LAB, Radiation.XRAY_SYNCHROTRON])
@pytest.mark.parametrize("geom", [Geometry.BRAGG_BRENTANO, Geometry.DEBYE_SCHERRER])
def test_single_cw_xray_histograms_are_in_scope(rad, geom):
    check_template_scope([_hist(rad, geom)], _PHASES, backend="gsasii")


def test_declarations_are_recorded_as_unverified_caller_input():
    ledger = Ledger()
    record_declarations(ledger, TemplateDeclarations(target_phase="A"))
    entry = ledger.entries[-1]
    assert entry.kind == "template_declaration"
    assert entry.payload["actor"] == "caller_unverified"
    assert entry.payload["declarations"] == {"target_phase": "A"}


def test_every_field_is_reachable_from_json():
    """フィールドを足したのに from_dict が読まない (= ③ から届かない) を防ぐ。"""
    from dataclasses import fields

    samples = {bool: True, str: "A"}
    for f in fields(TemplateDeclarations):
        typ = bool if "bool" in str(f.type) else str
        d = TemplateDeclarations.from_dict({f.name: samples[typ]})
        assert getattr(d, f.name) == samples[typ], f.name


def test_the_internal_standard_cannot_be_the_target():
    with pytest.raises(ValueError, match="内部標準"):
        TemplateDeclarations(target_phase="A", internal_standard="A").check_phases(_PHASES)
