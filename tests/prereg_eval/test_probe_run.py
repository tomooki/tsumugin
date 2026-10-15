"""反証プローブの GSAS を回さない部分 (Uiso のまとめの外し方)。"""

from __future__ import annotations

from types import SimpleNamespace

from tsumugin.prereg_eval.probe_run import _ungroup_uiso

# GSAS の Atoms の行: AtomPtrs = (cx, ct, cs, cia)。ここでは cx=0 (x,y,z), ct=3, cs=4, cia=5 で、ranId は cia + 8 = 13
_PTRS = (0, 3, 4, 5)


def _row(x, y, z, rid):
    row = [x, y, z, "L", "T", None, None, None, None, None, None, None, None, rid]
    return row


def _var(phase, atom):
    return SimpleNamespace(phase=phase, atom=atom, name="AUiso")


def test_groups_of_different_sites_are_removed_but_shared_sites_are_kept():
    ph = SimpleNamespace(data={
        "ranId": 7,
        "General": {"AtomPtrs": _PTRS},
        "Atoms": [_row(0.0, 0.0, 0.0, 101), _row(0.0, 0.0, 0.0, 102), _row(0.3, 0.3, 0.3, 103)],
    })
    template_group = [[1.0, _var(7, 101)], [1.0, _var(7, 103)], None, None, "e"]  # 位置が違う = テンプレートの選択
    shared_site = [[1.0, _var(7, 101)], [1.0, _var(7, 102)], None, None, "e"]  # 同じ席 (混合占有) = 物理
    other_phase = [[1.0, _var(8, 101)], [1.0, _var(8, 103)], None, None, "e"]
    sum_constraint = [[1.0, _var(7, 101)], [1.0, _var(7, 103)], 1.0, None, "c"]
    gpx = SimpleNamespace(data={"Constraints": {"data": {"Phase": [template_group, shared_site, other_phase,
                                                                   sum_constraint]}}})
    assert _ungroup_uiso(gpx, ph) == 1
    assert gpx.data["Constraints"]["data"]["Phase"] == [shared_site, other_phase, sum_constraint]
