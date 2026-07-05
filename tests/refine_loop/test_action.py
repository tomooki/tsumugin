"""TASK-0801: refine_loop.action — AnalysisAction 群 (safe/unsafe 型分け + 純変換 apply)。

GSAS 非依存の純データ層。SafeAction (規則が実行可) と ModelAction (③ 専用) を基底で型分けし、
各 Action の apply(inp) -> inp が spec を純粋に変換することを検証する (architecture.md §3.1)。
"""

from __future__ import annotations

import dataclasses

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation, RefinementStage
from tsumugin.refine_loop.action import (
    AddPhase,
    AdjustBackground,
    AnalysisAction,
    AnalysisInput,
    ModelAction,
    ReleaseParams,
    RemovePhase,
    ReviseStructure,
    SafeAction,
    SetLimits,
    SetMixedOccupancy,
    Stop,
)

_HX = HistogramSpec(
    data_path="d.xra",
    instrument_path="i.prm",
    radiation=Radiation.XRAY_LAB,
    geometry=Geometry.BRAGG_BRENTANO,
)
_HN = HistogramSpec(
    data_path="n.gsa",
    instrument_path="j.prm",
    radiation=Radiation.NEUTRON_CW,
    geometry=Geometry.DEBYE_SCHERRER,
)
_PA = PhaseSpec(structure_path="a.cif", phase_name="nac")
_PB = PhaseSpec(structure_path="b.cif", phase_name="caf2")


def _inp(**kw) -> AnalysisInput:
    base = dict(histograms=(_HX, _HN), phases=(_PA, _PB), background_coeffs=6, extra_stages=())
    base.update(kw)
    return AnalysisInput(**base)


# ---- 型分け (safe/unsafe) ----

def test_safe_actions_are_safeaction_subclass():
    for a in (AdjustBackground(9), ReleaseParams("size", {"size_strain": True}), Stop("done")):
        assert isinstance(a, SafeAction)
        assert isinstance(a, AnalysisAction)
        assert not isinstance(a, ModelAction)
        assert a.is_safe


def test_model_actions_are_modelaction_subclass():
    edits = {"structure_path": "b_edited.cif"}
    for a in (
        SetLimits(0, 2.5, 32.0),
        AddPhase(spec=PhaseSpec(structure_path="c.cif", phase_name="extra")),
        RemovePhase("caf2"),
        ReviseStructure("nac", edits),
        SetMixedOccupancy("nac", (("Fe1", "Al1"),)),
    ):
        assert isinstance(a, ModelAction)
        assert isinstance(a, AnalysisAction)
        assert not isinstance(a, SafeAction)
        assert not a.is_safe


def test_actions_are_frozen():
    a = AdjustBackground(9)
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.n_coeffs = 12  # type: ignore[misc]


# ---- SafeAction.apply ----

def test_adjust_background_sets_coeff_count():
    out = AdjustBackground(9).apply(_inp())
    assert out.background_coeffs == 9
    # 他フィールドは不変 (純変換)
    assert out.histograms == _inp().histograms and out.phases == _inp().phases


def test_release_params_appends_stage():
    out = ReleaseParams("size_strain", {"size_strain": True}).apply(_inp())
    assert len(out.extra_stages) == 1
    st = out.extra_stages[0]
    assert isinstance(st, RefinementStage)
    assert st.flags == {"size_strain": True}
    # 追加は累積する
    out2 = ReleaseParams("coords", {"coords": True}).apply(out)
    assert [s.flags for s in out2.extra_stages] == [{"size_strain": True}, {"coords": True}]


def test_stop_apply_is_identity():
    inp = _inp()
    assert Stop("target reached").apply(inp) == inp


# ---- ModelAction.apply ----

def test_set_limits_replaces_histogram_limits():
    out = SetLimits(0, 2.5, 32.0).apply(_inp())
    assert out.histograms[0].two_theta_limits == (2.5, 32.0)
    assert out.histograms[1].two_theta_limits is None  # 他ヒストグラムは不変


def test_set_limits_out_of_range_hist_id_raises():
    with pytest.raises(IndexError):
        SetLimits(9, 2.5, 32.0).apply(_inp())


def test_add_phase_with_spec_appends():
    extra = PhaseSpec(structure_path="c.cif", phase_name="extra")
    out = AddPhase(spec=extra).apply(_inp())
    assert out.phases[-1] == extra
    assert len(out.phases) == 3


def test_add_phase_hint_only_cannot_apply():
    # element_hint のみは相同定を経て spec 化しないと適用不能 (③ 専用)
    with pytest.raises(ValueError):
        AddPhase(element_hint=("Ca", "F")).apply(_inp())


def test_remove_phase_drops_named_phase():
    out = RemovePhase("caf2").apply(_inp())
    assert [p.phase_name for p in out.phases] == ["nac"]


def test_remove_phase_unknown_name_raises():
    with pytest.raises(KeyError):
        RemovePhase("nope").apply(_inp())


def test_revise_structure_updates_phase_fields():
    out = ReviseStructure("nac", {"structure_path": "nac_edited.cif"}).apply(_inp())
    nac = next(p for p in out.phases if p.phase_name == "nac")
    assert nac.structure_path == "nac_edited.cif"
    # 他相は不変
    assert next(p for p in out.phases if p.phase_name == "caf2").structure_path == "b.cif"


def test_revise_structure_unknown_field_raises():
    with pytest.raises(ValueError):
        ReviseStructure("nac", {"bogus_field": 1}).apply(_inp())


def test_set_mixed_occupancy_sets_groups():
    groups = (("Fe1", "Al1"), ("Al2", "Fe2"))
    out = SetMixedOccupancy("nac", groups).apply(_inp())
    nac = next(p for p in out.phases if p.phase_name == "nac")
    assert nac.mixed_occupancy_groups == groups


# ---- AnalysisInput ----

def test_analysis_input_is_frozen():
    inp = _inp()
    with pytest.raises(dataclasses.FrozenInstanceError):
        inp.background_coeffs = 12  # type: ignore[misc]
