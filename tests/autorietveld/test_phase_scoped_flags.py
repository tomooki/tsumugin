"""fit-then-judge P1-1B タスク 2: 相を絞る段フラグ ``cell_phases`` / ``preferred_orientation_phases``。

テンプレートは pass 1 で格子を凍結した相を段 R でもう一度試す (`refine_cell=False` は「決して解放しない」
なので使えない)。選択配向は対象相にだけ張る。どちらも静的な段フラグで表し、`recipe=` だけで再生できる。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.engine import _apply_stage
from tsumugin.autorietveld.model import PhaseSpec, Radiation, RefinementStage
from tsumugin.autorietveld.recipe import check_phase_scoped_flags
from tsumugin.errors import InvalidPhaseSpecError
from tsumugin.mcp._recipe_spec import stage_from_dict


def _info(refine_cell: bool = True) -> dict:
    return {
        "refine_cell": refine_cell,
        "labels": [], "coord_atoms": [], "mixed": set(),
        "free_occ": set(), "equiv_occ": set(), "uiso_labels": [],
    }


class _Phase:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[dict] = []
        self.hap: list[dict] = []

    def set_refinements(self, d):
        self.calls.append(d)

    def set_HAP_refinements(self, d, histograms=None):
        self.hap.append(d)

    def HAPvalue(self, *a, **k):
        return None

    def cell_refined(self) -> bool:
        return any(c.get("Cell") is True for c in self.calls)

    def po_refined(self) -> bool:
        return any(d.get("Pref.Ori.") is True for d in self.hap)


def _apply(phases, flags, infos=None):
    _apply_stage(
        gpx=None, hists=[object()], phases=phases,
        phase_infos=infos or [_info() for _ in phases], atom_flag_maps=[{} for _ in phases],
        radiations=[Radiation.XRAY_LAB], stage=RefinementStage("s", flags),
    )


def test_cell_phases_releases_only_the_named_phases():
    a, b = _Phase("A"), _Phase("B")
    _apply([a, b], {"cell": True, "cell_phases": ["B"]})
    assert not a.cell_refined() and b.cell_refined()


def test_without_cell_phases_every_phase_is_released_as_before():
    a, b = _Phase("A"), _Phase("B")
    _apply([a, b], {"cell": True})
    assert a.cell_refined() and b.cell_refined()


def test_cell_phases_never_overrides_a_manual_freeze():
    """手動 > 自動 > 既定の順序を壊さない (`refine_cell=False` は「決して解放しない」)。"""
    a = _Phase("A")
    _apply([a], {"cell": True, "cell_phases": ["A"]}, infos=[_info(refine_cell=False)])
    assert not a.cell_refined()


def test_preferred_orientation_phases_limits_the_march_dollase_release():
    a, b = _Phase("A"), _Phase("B")
    _apply([a, b], {"preferred_orientation": 1, "preferred_orientation_phases": ["A"]})
    assert a.po_refined() and not b.po_refined()


def _spec(name: str) -> PhaseSpec:
    return PhaseSpec(structure_path=f"{name}.cif", phase_name=name)


@pytest.mark.parametrize(
    "flags",
    [
        {"cell": True, "cell_phases": ["C"]},  # 相に無い名前
        {"cell_phases": ["A"]},  # cell を解放しない段 = 何もしない
        {"cell": False, "cell_phases": ["A"]},
        {"cell": True, "cell_phases": []},  # 空 = 全相が凍る (意図の逆を黙って)
        {"cell": True, "cell_phases": "A"},  # 文字列は文字の列に化ける
        {"preferred_orientation": 1, "preferred_orientation_phases": ["Z"]},
        {"preferred_orientation_phases": ["A"]},
    ],
)
def test_misuse_is_refused_before_refinement(flags):
    with pytest.raises(InvalidPhaseSpecError):
        check_phase_scoped_flags([RefinementStage("s", flags)], [_spec("A"), _spec("B")])


def test_valid_scoped_flags_pass():
    check_phase_scoped_flags(
        [RefinementStage("s", {"cell": True, "cell_phases": ["A", "B"]})], [_spec("A"), _spec("B")]
    )


def test_the_engine_entry_checks_the_flags_before_gsas():
    """GSAS が無くても同じエラーで止まる (入力の誤りは backend の有無と無関係)。"""
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import Geometry, HistogramSpec

    h = HistogramSpec(
        data_path="d.xye", instrument_path="i.instprm",
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
    )
    with pytest.raises(InvalidPhaseSpecError, match="cell_phases"):
        run_auto_rietveld(
            [h], [_spec("A")],
            recipe=[RefinementStage("S0", {"cell": True, "cell_phases": ["nope"]})],
            save_gpx=False,
        )


@pytest.mark.parametrize("name", ["cell_phases", "preferred_orientation_phases"])
def test_layer_two_accepts_the_flags_as_name_lists(name):
    stage_from_dict({"label": "s", "flags": {"cell": True, name: ["A"]}})
    for bad in ([], "A", [1], True):
        with pytest.raises(ValueError):
            stage_from_dict({"label": "s", "flags": {"cell": True, name: bad}})
