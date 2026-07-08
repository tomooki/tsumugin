"""free_occupancy_labels (単独占有率解放) の決定論テスト。

Ow のような共有でない部分占有サイトの占有率を、和=1 制約なしで解放する経路を検証する。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _update_atom_flags
from tsumugin.autorietveld.model import (
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
)
from tsumugin.autorietveld.recipe import build_recipe


def test_update_atom_flags_frees_mixed_and_free_occ():
    info = {
        "labels": ["Na1", "O3", "Ow", "Cu"],
        "coord_atoms": ["Na1", "O3", "Ow"],
        "mixed": {"Na1", "O3"},
        "free_occ": {"Ow"},
    }
    flags: dict[str, str] = {}
    _update_atom_flags(flags, info, {"occupancy": True})
    # 混合占有 (Na1/O3) と単独解放 (Ow) の双方に F、非対象 Cu には付かない。
    assert "F" in flags.get("Na1", "")
    assert "F" in flags.get("O3", "")
    assert "F" in flags.get("Ow", "")
    assert "F" not in flags.get("Cu", "")


def test_phasespec_roundtrip_free_occupancy():
    p = PhaseSpec(
        structure_path="m6.cif",
        phase_name="NaCuHCF",
        mixed_occupancy_groups=(("Na1", "O3"),),
        free_occupancy_labels=("Ow",),
    )
    p2 = PhaseSpec.from_dict(p.to_dict())
    assert p2.free_occupancy_labels == ("Ow",)
    assert p2.mixed_occupancy_groups == (("Na1", "O3"),)


def test_recipe_adds_occupancy_stage_for_free_occ_only():
    # mixed_occupancy_groups は空だが free_occupancy_labels があれば occupancy 段階が入る。
    hist = HistogramSpec(
        "d.xye", "i.instprm",
        radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
    )
    phase = PhaseSpec("m.cif", "NaCuHCF", free_occupancy_labels=("Ow",))
    stages = build_recipe([hist], [phase])
    assert any("occupancy" in s.flags for s in stages)
