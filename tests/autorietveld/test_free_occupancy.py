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


class _FakePhase:
    def __init__(self, pid, labels):
        self.id = pid
        # AtomPtrs=[cx,ct,cs,cia]; ct=1 → label は row[ct-1]=row[0]。
        self.data = {
            "Atoms": [[lab] for lab in labels],
            "General": {"AtomPtrs": [1, 1, 2, 3]},
        }


class _FakeGpx:
    def __init__(self):
        self.eqn = []
        self.equiv = []
        self.bounds = {"parmMin": {}, "parmMax": {}}

    def add_EqnConstr(self, total, vars_, weights):
        self.eqn.append((total, tuple(vars_)))

    def add_EquivConstr(self, vars_):
        self.equiv.append(tuple(vars_))

    def set_Controls(self, control, value, variable=None):
        self.bounds[control][variable] = value


def test_setup_constraints_bounds_and_sum_constraints():
    from tsumugin.autorietveld.engine import _setup_constraints

    ph = _FakePhase(0, ["Cu", "Na1", "O3", "Ow"])  # Afrac idx: Na1=1,O3=2,Ow=3
    spec = PhaseSpec(
        "m.cif", "NaCuHCF",
        mixed_occupancy_groups=(("Na1", "O3"),),
        free_occupancy_labels=("Ow",),
    )
    gpx = _FakeGpx()
    _setup_constraints(gpx, [ph], [], [spec])
    # 共有サイトに 占有率和=1 + Uiso 等価。
    assert (1.0, ("0::Afrac:1", "0::Afrac:2")) in gpx.eqn
    assert ("0::AUiso:1", "0::AUiso:2") in gpx.equiv
    # 混合占有 (Na1,O3) と単独解放 (Ow) の Afrac に [0,1] 拘束。
    for v in ("0::Afrac:1", "0::Afrac:2", "0::Afrac:3"):
        assert gpx.bounds["parmMin"][v] == 0.0
        assert gpx.bounds["parmMax"][v] == 1.0
    # 非占有原子 (Cu, Afrac:0) には拘束を張らない。
    assert "0::Afrac:0" not in gpx.bounds["parmMin"]


def test_setup_constraints_occupancy_equiv_groups():
    from tsumugin.autorietveld.engine import _setup_constraints

    ph = _FakePhase(0, ["Ow", "DOw1", "DOw2"])  # Afrac idx: Ow=0, DOw1=1, DOw2=2
    spec = PhaseSpec(
        "m.cif", "NaCuHCF",
        free_occupancy_labels=("Ow",),
        occupancy_equiv_groups=(("Ow", "DOw1", "DOw2"),),
    )
    gpx = _FakeGpx()
    _setup_constraints(gpx, [ph], [], [spec])
    # D 占有率を親 O に等値 (add_EquivConstr で 1 変数化)。
    assert ("0::Afrac:0", "0::Afrac:1", "0::Afrac:2") in gpx.equiv


def test_tof_profile_stage_refines_only_tof_histograms():
    from tsumugin.autorietveld.engine import _apply_stage, _tof_profile_keys
    from tsumugin.autorietveld.model import RefinementStage

    class _FakeHist:
        def __init__(self):
            self.refined = []

        def set_refinements(self, d):
            self.refined.append(d)

    xray_h, tof_h = _FakeHist(), _FakeHist()
    rads = [Radiation.XRAY_SYNCHROTRON, Radiation.NEUTRON_TOF]
    stage = RefinementStage("tofprof", {"tof_profile": True})
    _apply_stage(None, [xray_h, tof_h], [], [], [], rads, stage)
    # TOF ヒストグラムのみ profile 較正キーを解放。
    assert tof_h.refined == [{"Instrument Parameters": _tof_profile_keys()}]
    assert xray_h.refined == []
    assert _tof_profile_keys() == ["sig-1", "sig-2"]


def test_equiv_groups_from_sites_groups_by_parent():
    from tsumugin.autorietveld.deuterium import DeuteriumSite, equiv_groups_from_sites

    sites = (
        DeuteriumSite("DO11", "O1", (0.0, 0.0, 0.0), 0.25),
        DeuteriumSite("DO12", "O1", (0.1, 0.0, 0.0), 0.25),
        DeuteriumSite("DOw1", "Ow", (0.2, 0.0, 0.0), 0.17),
        DeuteriumSite("DOw2", "Ow", (0.3, 0.0, 0.0), 0.17),
    )
    groups = equiv_groups_from_sites(sites)
    assert groups == (("O1", "DO11", "DO12"), ("Ow", "DOw1", "DOw2"))


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
