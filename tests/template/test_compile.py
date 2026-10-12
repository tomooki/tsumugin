"""fit-then-judge P1-1B タスク 5: 静的コンパイル (REQ-FTJ-1B-401〜404)。"""

from __future__ import annotations

import json

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.recipe import CORRELATION_GROUPS, released_group_members
from tsumugin.template.compile import (
    NO_NEW_DOF,
    TEMPLATE_VERSION,
    TemplateDecisions,
    compile_template,
    pass1_stages,
)


def _hist(geometry=Geometry.BRAGG_BRENTANO) -> HistogramSpec:
    return HistogramSpec(
        data_path="d.xye", instrument_path="i.instprm",
        radiation=Radiation.XRAY_LAB, geometry=geometry,
    )


A = PhaseSpec("a.cif", "A")
B = PhaseSpec("b.cif", "B")
LABELS = {"A": ("Ca1", "O1"), "B": ("Si1", "O2")}


def _decisions(**kw) -> TemplateDecisions:
    base = dict(target_phase="A", phase_labels=LABELS)
    base.update(kw)
    return TemplateDecisions(**base)


def _labels(compiled) -> list[str]:
    return [s.label.split(" ", 1)[1] for s in compiled.stages]


def _flags(compiled, name: str) -> dict:
    return next(s.flags for s in compiled.stages if s.label.split(" ", 1)[1] == name)


# --- 段の表 -----------------------------------------------------------------


def test_single_phase_bragg_brentano_uncalibrated_stage_list():
    c = compile_template([_hist()], [A], _decisions())
    assert _labels(c) == [
        "scale+background", "lattice+offset", "width-1", "width-2", "asym",
        "coords", "B", "pref", "struct-retry", "final",
    ]
    assert _flags(c, "lattice+offset") == {"cell": True, "displacement": {0: ["Shift"]}}
    assert _flags(c, "width-2") == {"profile_lorentzian": ["X", "Y"]}  # Zero を束ねない
    assert _flags(c, "pref") == {"preferred_orientation": 1, "preferred_orientation_phases": ["A"]}


def test_debye_scherrer_releases_zero_and_skips_preferred_orientation():
    c = compile_template([_hist(Geometry.DEBYE_SCHERRER)], [A], _decisions())
    assert _flags(c, "lattice+offset") == {"cell": True, "zero_offset": True}
    assert "pref" not in _labels(c)


def test_calibrated_instrument_reads_widths_as_sample_broadening():
    c = compile_template([_hist()], [A], _decisions(calibrated=True))
    assert _flags(c, "width-1") == {"size_strain": "isotropic"}
    assert "width-2" not in _labels(c) and "asym" not in _labels(c)


def test_frozen_cells_are_left_out_of_stage_one_and_retried():
    c = compile_template([_hist()], [A, B], _decisions(frozen_cell_phases=("B",)))
    assert _flags(c, "lattice+offset")["cell_phases"] == ["A"]
    assert _labels(c).index("lattice-retry") == _labels(c).index("asym") + 1
    assert _flags(c, "lattice-retry") == {"cell": True}


def test_no_lattice_retry_without_frozen_cells():
    c = compile_template([_hist()], [A, B], _decisions())
    assert "lattice-retry" not in _labels(c)
    assert "cell_phases" not in _flags(c, "lattice+offset")


def test_multiphase_releases_phase_fractions_with_the_scale():
    c = compile_template([_hist()], [A, B], _decisions())
    assert _flags(c, "scale+background")["phase_fraction_sum"] is True
    single = compile_template([_hist()], [A], _decisions())
    assert "phase_fraction_sum" not in _flags(single, "scale+background")


def test_occupancy_stage_only_when_the_target_has_occupancy_groups():
    plain = compile_template([_hist()], [A], _decisions())
    assert "occupancy" not in _labels(plain)
    mixed = PhaseSpec("a.cif", "A", mixed_occupancy_groups=(("Fe1", "Al1"),))
    c = compile_template([_hist()], [mixed, B], _decisions())
    assert _flags(c, "occupancy") == {"occupancy": True, "occupancy_phases": ["A"]}


def test_background_terms_come_from_the_decision():
    c = compile_template([_hist()], [A], _decisions(background_coeffs=18))
    assert _flags(c, "scale+background")["background"] == {"coeffs": 18}
    assert c.background_coeffs == 18


def test_retry_and_final_stages_are_marked_as_adding_no_freedom():
    c = compile_template([_hist()], [A], _decisions())
    for name in ("struct-retry", "final"):
        st = next(s for s in c.stages if s.label.endswith(name))
        assert NO_NEW_DOF in st.note
    assert _flags(c, "final") == {}


def test_no_correlation_group_is_split():
    """相関群を割る段を出さない (コンパイルの内部で検証しているが、外からも確かめる)。"""
    for calibrated in (False, True):
        c = compile_template([_hist()], [A, B], _decisions(calibrated=calibrated))
        for st in c.stages:
            for group in CORRELATION_GROUPS:
                members = released_group_members(st.flags, group)
                assert members in (frozenset(), frozenset(CORRELATION_GROUPS[group])) or (
                    group in ("lorentzian_profile", "zero_offset")
                ), (st.label, group, members)


# --- PhaseSpec ---------------------------------------------------------------


def test_non_target_structures_are_frozen_and_the_target_is_origin_fixed():
    c = compile_template([_hist()], [A, B], _decisions(uiso_groups=(("O1", "Ca1"),)))
    a, b = c.phases
    assert a.fix_polar_origin and a.uiso_equiv_groups == (("O1", "Ca1"),)
    assert not b.fix_polar_origin
    assert b.frozen_coord_labels == ("Si1", "O2") and b.frozen_uiso_labels == ("Si1", "O2")


def test_the_callers_phase_specs_are_not_modified():
    before = (A, B)
    compile_template([_hist()], list(before), _decisions())
    assert before == (PhaseSpec("a.cif", "A"), PhaseSpec("b.cif", "B"))


def test_caller_uiso_groups_take_precedence_over_the_rule():
    own = PhaseSpec("a.cif", "A", uiso_equiv_groups=(("Ca1", "O1"),))
    c = compile_template([_hist()], [own], _decisions(uiso_groups=(("O1", "O9"),)))
    assert c.phases[0].uiso_equiv_groups == (("Ca1", "O1"),)


def test_unknown_names_and_missing_labels_are_refused():
    with pytest.raises(ValueError, match="対象相"):
        compile_template([_hist()], [A], _decisions(target_phase="Z"))
    with pytest.raises(ValueError, match="凍結"):
        compile_template([_hist()], [A], _decisions(frozen_cell_phases=("Z",)))
    with pytest.raises(ValueError, match="ラベル"):
        compile_template([_hist()], [A, B], _decisions(phase_labels={"A": ("Ca1",)}))


# --- 版・derivation・pass 1 ---------------------------------------------------


def test_the_result_carries_version_and_a_json_safe_derivation():
    c = compile_template([_hist()], [A, B], _decisions(), evidence={"background": {"n": 6}})
    assert c.template_version == TEMPLATE_VERSION
    d = json.loads(json.dumps(c.derivation))
    assert d["template_version"] == TEMPLATE_VERSION
    assert d["decisions"]["target_phase"] == "A"
    assert d["evidence"] == {"background": {"n": 6}}
    assert d["stages"] == [s.label for s in c.stages]


def test_compilation_is_deterministic():
    a = compile_template([_hist()], [A, B], _decisions(frozen_cell_phases=("B",)))
    b = compile_template([_hist()], [A, B], _decisions(frozen_cell_phases=("B",)))
    assert a == b


def test_pass1_runs_the_shared_head_of_the_template():
    head = pass1_stages([_hist()], [A, B], background_coeffs=6, calibrated=False)
    full = compile_template([_hist()], [A, B], _decisions())
    assert head == full.stages[: len(head)]
    assert [s.label.split(" ", 1)[1] for s in head][-1] == "asym"


def test_pass1_can_leave_phases_out_of_the_lattice_stage():
    head = pass1_stages(
        [_hist()], [A, B], background_coeffs=6, calibrated=False, cell_phases=["B"]
    )
    assert head[1].flags["cell_phases"] == ["B"]
