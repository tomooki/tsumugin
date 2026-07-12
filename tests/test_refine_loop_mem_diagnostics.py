"""refine_loop.mem_diagnostics (MEM 密度→構造改訂提案) の TDD テスト (M8-③ Phase B)。

MEMDensityResult の未モデル密度ピーク → ReviseStructure ActionProposal (具体 evidence 付き)。
決定論・提案のみ (safe=False)・GSAS 非依存 (モック MEMDensityResult)。
"""
from __future__ import annotations

from tsumugin.mem.gsas import DensityPeak, MEMDensityResult
from tsumugin.mem.base import MEMDensityMap
from tsumugin.refine_loop.action import ReviseStructure
from tsumugin.refine_loop.mem_diagnostics import propose_structure_revisions_from_mem


def _mem(peaks, kind="nuclear"):
    dm = MEMDensityMap(path="m.grd", density_kind=kind, grid_shape=(8, 8, 8),
                       min_density=min([p.magnitude for p in peaks], default=0.0),
                       max_density=max([p.magnitude for p in peaks], default=1.0))
    return MEMDensityResult(
        density_map=dm, pre_min=-1.0, pre_max=5.0, n_reflections=800,
        mem_r_factor=None, converged=True, density_kind=kind, peaks=tuple(peaks),
    )


def test_positive_unmodeled_peak_proposes_revise_structure():
    mem = _mem([DensityPeak(frac=(0.3, 0.4, 0.2), magnitude=3.5,
                            nearest_atom="Cu1", distance=1.6)])
    props = propose_structure_revisions_from_mem(mem, phase="NaCuHCF",
                                                 unmodeled_distance=0.8)
    assert len(props) == 1
    p = props[0]
    assert isinstance(p.action, ReviseStructure)
    assert p.action.phase == "NaCuHCF"
    assert p.safe is False                       # ModelAction
    assert p.evidence["signal"] == "mem_unmodeled_positive"
    assert p.evidence["frac"] == (0.3, 0.4, 0.2)
    assert p.evidence["suggested_op"] == "add"
    assert "suggested_edit" in p.evidence


def test_positive_peak_near_atom_is_not_proposed():
    """最近接原子まで近い正ピークは既にモデル済み → 提案しない。"""
    mem = _mem([DensityPeak(frac=(0.0, 0.5, 0.5), magnitude=5.0,
                            nearest_atom="Cu1", distance=0.1)])
    props = propose_structure_revisions_from_mem(mem, phase="P", unmodeled_distance=0.8)
    assert props == ()


def test_negative_nuclear_peak_near_atom_proposes_h_or_occupancy():
    mem = _mem([DensityPeak(frac=(0.1, 0.2, 0.3), magnitude=-0.8,
                            nearest_atom="O1", distance=0.5)], kind="nuclear")
    props = propose_structure_revisions_from_mem(mem, phase="P", unmodeled_distance=0.8)
    assert len(props) == 1
    assert props[0].evidence["signal"] == "mem_negative_nuclear"
    assert "H" in props[0].evidence["suggested_op"] or "occup" in props[0].evidence["suggested_op"]


def test_negative_electron_peak_not_proposed():
    """電子密度の負ピーク (重原子近傍の series-termination) は構造改訂候補にしない。"""
    mem = _mem([DensityPeak(frac=(0.1, 0.2, 0.3), magnitude=-2.0,
                            nearest_atom="Fe1", distance=0.4)], kind="electron")
    props = propose_structure_revisions_from_mem(mem, phase="P", unmodeled_distance=0.8)
    assert props == ()


def test_deterministic_priority_sort_and_cap():
    peaks = [
        DensityPeak(frac=(0.1, 0.0, 0.0), magnitude=1.0, nearest_atom="A", distance=2.0),
        DensityPeak(frac=(0.2, 0.0, 0.0), magnitude=4.0, nearest_atom="A", distance=2.0),
        DensityPeak(frac=(0.3, 0.0, 0.0), magnitude=2.5, nearest_atom="A", distance=2.0),
    ]
    props = propose_structure_revisions_from_mem(_mem(peaks), phase="P",
                                                 unmodeled_distance=0.8, max_proposals=2)
    assert len(props) == 2
    # priority = |magnitude| 降順: 4.0, 2.5
    assert [round(p.priority, 1) for p in props] == [4.0, 2.5]


def test_empty_peaks_returns_empty():
    assert propose_structure_revisions_from_mem(_mem([]), phase="P") == ()


def test_suggested_edit_is_atomedit_template():
    """suggested_edit は edit_cif に渡せる AtomEdit テンプレ (op=add, frac 埋め, element/occ は ③)。"""
    mem = _mem([DensityPeak(frac=(0.3, 0.4, 0.2), magnitude=3.5,
                            nearest_atom="Cu1", distance=1.6)])
    props = propose_structure_revisions_from_mem(mem, phase="P", unmodeled_distance=0.8)
    edit = props[0].evidence["suggested_edit"]
    assert edit["op"] == "add"
    assert edit["frac"] == (0.3, 0.4, 0.2)
    assert edit["element"] is None      # ③ が密度大きさ×probe で判定
    assert edit["occ"] is None
