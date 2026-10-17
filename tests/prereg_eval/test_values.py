"""P0 §1.6: 出版状態 (claims) → 1A の値の集合 V の状態。"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from tsumugin.claims.model import Claim, Determinacy, Witness
from tsumugin.prereg_eval.structure import FitValue, RefValue
from tsumugin.prereg_eval.values import main_phase, outlier_map, value_states


def _c(key, cls, *, phase="P", prov="refined", gate=(), det=Determinacy.ESD_ONLY):
    witnesses = (Witness("multistart", {}),) if det == Determinacy.DETERMINED else ()
    return Claim(key=key, param_class=cls, value=1.0, esd=0.1, unit="", phase=phase,
                 determinacy=det, provenance=frozenset({prov}), gate=frozenset(gate), witnesses=witnesses)


def test_v_takes_structure_values_and_drops_symmetry_fixed_and_nuisance():
    claims = {c.key: c for c in [
        _c("cell:P.a", "cell"),
        _c("cell:P.b", "cell", prov="symmetry"),  # a と等しいと対称で決まる軸 (独立でない)
        _c("coord:P.O1.z", "coord"),
        _c("coord:P.O1.x", "coord", prov="symmetry"),
        _c("coord:P.O2.x", "coord", prov="input"),  # 自由座標だが解放しなかった — V に入る
        _c("occupancy:P.O1", "occupancy"),
        _c("occupancy:P.Zn1", "occupancy", prov="input"),  # 精密化しなかった占有率 — 入らない
        _c("uiso:P.O1", "uiso"),
        _c("weight_fraction:P.wt", "weight_fraction"),
        _c("profile:hist0.U", "profile", phase=None),
        _c("microstructure:P.0.size", "microstructure"),
    ]}
    keys = {v.key for v in value_states(claims, main="P", outliers={})}
    assert keys == {"cell:P.a", "coord:P.O1.z", "coord:P.O2.x", "occupancy:P.O1", "uiso:P.O1", "weight_fraction:P.wt"}


def test_state_carries_publishability_gate_main_phase_and_outlier():
    claims = {
        "coord:P.O1.z": _c("coord:P.O1.z", "coord", gate=("phase_set_completeness",)),
        "coord:Q.C1.x": _c("coord:Q.C1.x", "coord", phase="Q", det=Determinacy.DETERMINED),
        "uiso:P.O1": _c("uiso:P.O1", "uiso"),
    }
    vs = {v.key: v for v in value_states(claims, main="P", outliers={"coord:P.O1": True, "coord:Q.C1": False})}
    o1 = vs["coord:P.O1.z"]
    assert not o1.publishable and o1.blocked_by == ("phase_set_completeness",) and o1.main_phase and o1.outlier
    c1 = vs["coord:Q.C1.x"]
    assert not c1.main_phase and c1.outlier is False and c1.determinacy == "determined"
    assert vs["uiso:P.O1"].outlier is None  # Uiso は比較集合に入らない (P0 §1.3)


def test_outlier_map_uses_the_arms_own_esd():
    ref = (RefValue("occupancy", "occ:P.O1", 0.60, 0.001),)
    tight = (FitValue("occupancy", "occ:P.O1", 0.65, 0.001, True),)
    loose = (FitValue("occupancy", "occ:P.O1", 0.65, 0.05, True),)
    lattice = np.eye(3) * 10
    assert outlier_map(ref, tight, lattice=lattice) == {"occ:P.O1": True}
    assert outlier_map(ref, loose, lattice=lattice) == {"occ:P.O1": False}


def test_main_phase_is_the_largest_integrated_intensity_summed_over_histograms():
    r = SimpleNamespace(phase_integrated_intensity={"P": (10.0, None), "Q": (6.0, 6.0)})
    assert main_phase(r) == "Q"
    assert main_phase(SimpleNamespace(phase_integrated_intensity=None)) is None
