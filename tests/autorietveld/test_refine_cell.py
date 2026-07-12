"""PhaseSpec.refine_cell (副相セル凍結, Issue #47) のテスト。

roundtrip と、engine の "cell" 段で refine_cell=False の相が Cell 解放されないことを
GSAS 非依存モックで検証する。
"""

from __future__ import annotations

import tsumugin.autorietveld.engine as eng
from tsumugin.autorietveld.model import PhaseSpec, RefinementStage, Radiation


def test_roundtrip_refine_cell():
    spec = PhaseSpec("s.cif", "P", refine_cell=False)
    assert PhaseSpec.from_dict(spec.to_dict()).refine_cell is False


def test_default_true():
    assert PhaseSpec("s.cif", "P").refine_cell is True


class _RecPhase:
    """set_refinements / set_HAP_refinements を記録するだけの相モック。"""

    def __init__(self, name):
        self.name = name
        self.calls: list[dict] = []

    def set_refinements(self, d):
        self.calls.append(d)

    def set_HAP_refinements(self, *a, **k):
        pass

    def cell_refined(self) -> bool:
        return any(c.get("Cell") is True for c in self.calls)


def test_cell_stage_skips_frozen_phase():
    # 主相 (refine_cell=True) と副相 (False) を混在させ、cell 段で主相のみ Cell 解放される。
    phases = [_RecPhase("main"), _RecPhase("minor")]
    phase_infos = [{"refine_cell": True}, {"refine_cell": False}]
    for info in phase_infos:  # _update_atom_flags が触るキーを埋める
        info.update({"labels": [], "coord_atoms": [], "mixed": set(),
                     "free_occ": set(), "equiv_occ": set(), "uiso_labels": []})
    atom_flag_maps = [{}, {}]
    stage = RefinementStage("cell", {"cell": True})
    eng._apply_stage(
        gpx=None, hists=[], phases=phases, phase_infos=phase_infos,
        atom_flag_maps=atom_flag_maps, radiations=[Radiation.XRAY_SYNCHROTRON],
        stage=stage,
    )
    assert phases[0].cell_refined() is True
    assert phases[1].cell_refined() is False


def test_cell_stage_default_refines_all():
    phases = [_RecPhase("a"), _RecPhase("b")]
    phase_infos = [{}, {}]  # refine_cell 欠落 → 既定 True (後方互換)
    for info in phase_infos:
        info.update({"labels": [], "coord_atoms": [], "mixed": set(),
                     "free_occ": set(), "equiv_occ": set(), "uiso_labels": []})
    stage = RefinementStage("cell", {"cell": True})
    eng._apply_stage(
        gpx=None, hists=[], phases=phases, phase_infos=phase_infos,
        atom_flag_maps=[{}, {}], radiations=[Radiation.XRAY_SYNCHROTRON], stage=stage,
    )
    assert phases[0].cell_refined() and phases[1].cell_refined()
