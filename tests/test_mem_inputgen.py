"""mem/inputgen.py の失敗テスト (TASK-0054 / REQ-021/022/023 / NFR-102)。

対象実装 (未実装):
- ``src/tsumugin/mem/inputgen.py``:
  ``StructureFactor`` / ``MEMInput`` (frozen dataclass) と
  ``extract_structure_factors(joint_result, *, hist_index=0) -> tuple[StructureFactor, ...]`` /
  ``build_mem_input(joint_result, probe, *, hist_index=0, grid_shape=(64,64,64)) -> MEMInput``
- ``src/tsumugin/mem/__init__.py``: 上記 4 シンボルの re-export (__all__ 昇順)

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の mem/inputgen 節に依拠。
完了条件 (TC-506-03/04/05 / REQ-021/022/023 / NFR-102/REQ-402) に 1:1 対応する。

方針:
- プライマリ探索 (``HypothesisTreeSearch`` 1 ヒスト) → ``verify_survivors`` で実際の
  ``JointRefinementResult`` を生成し、現実の構造 (精密化済み phases/lattice) で検証する。
- 決定論は SimulatedBackend が乱数不使用のため ``==`` ビット同一で検証する。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.joint import JointHistogram, verify_survivors
from tsumugin.joint.model import JointRefinementResult
from tsumugin.mem.inputgen import (
    MEMInput,
    StructureFactor,
    build_mem_input,
    extract_structure_factors,
)
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.search.tree import HypothesisTreeSearch, SearchConfig, SearchResult

GRID = np.arange(15.0, 60.0, 0.02)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


PHASE_A = _phase(5.0, "A")
PHASE_B = _phase(6.0, "B")
PHASE_C = _phase(4.5, "C")


def _primary_search() -> tuple[SearchResult, SimulatedBackend]:
    backend = SimulatedBackend(peak_fwhm=0.2)
    intensity = backend.simulate((PHASE_A,), GRID)
    search = HypothesisTreeSearch(backend, config=SearchConfig())
    candidates = [
        PhaseCandidate(phase=PHASE_A),
        PhaseCandidate(phase=PHASE_B),
        PhaseCandidate(phase=PHASE_C),
    ]
    result = search.search(GRID, intensity, candidates)
    return result, backend


def _joint_histograms(backend: SimulatedBackend) -> tuple[JointHistogram, ...]:
    y_xray = backend.simulate((PHASE_A,), GRID)
    y_neutron = backend.simulate((PHASE_A,), GRID)
    return (
        JointHistogram(two_theta=GRID, intensity=y_xray, probe="xray"),
        JointHistogram(two_theta=GRID, intensity=y_neutron, probe="neutron_cw"),
    )


def _a_joint_result() -> JointRefinementResult:
    """実際の verify_survivors から生存仮説 1 件の JointRefinementResult を取り出す。"""
    result, backend = _primary_search()
    histograms = _joint_histograms(backend)
    verification = verify_survivors(backend, result, histograms)
    assert verification.joint_results, "生存仮説が空だとテストが無意味"
    # ID 昇順先頭を採用 (決定論)。
    sid = sorted(verification.joint_results)[0]
    return verification.joint_results[sid]


# ---------------------------------------------------------------------------
# (A) StructureFactor / MEMInput が frozen dataclass である
# ---------------------------------------------------------------------------


def test_structure_factor_fields_and_frozen():
    sf = StructureFactor(hkl=(1, 0, 0), f_obs=12.5, phase=0.0, d_spacing=5.0)
    assert sf.hkl == (1, 0, 0)
    assert sf.f_obs == 12.5
    assert sf.phase == 0.0
    assert sf.d_spacing == 5.0
    with pytest.raises(FrozenInstanceError):
        sf.f_obs = 1.0  # type: ignore[misc]


def test_mem_input_fields_and_frozen():
    sf = StructureFactor(hkl=(1, 0, 0), f_obs=12.5, phase=0.0, d_spacing=5.0)
    mi = MEMInput(
        structure_factors=(sf,),
        density_kind="electron",
        lattice=(5.0, 5.0, 5.0, 90.0, 90.0, 90.0),
        space_group="P1",
        grid_shape=(64, 64, 64),
    )
    assert mi.structure_factors == (sf,)
    assert mi.density_kind == "electron"
    assert mi.lattice == (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)
    assert mi.grid_shape == (64, 64, 64)
    assert mi.lambda_start == 1.0  # 既定値
    with pytest.raises(FrozenInstanceError):
        mi.space_group = "P2"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (B) extract_structure_factors: JointRefinementResult から StructureFactor 群 [TC-506-03]
# ---------------------------------------------------------------------------


def test_extract_returns_structure_factors():
    """joint 結果から StructureFactor 群を返す (非空・型)。"""
    joint = _a_joint_result()
    sfs = extract_structure_factors(joint)
    assert isinstance(sfs, tuple)
    assert len(sfs) >= 1
    for sf in sfs:
        assert isinstance(sf, StructureFactor)
        assert isinstance(sf.hkl, tuple) and len(sf.hkl) == 3
        assert np.isfinite(sf.f_obs)
        assert np.isfinite(sf.phase)
        assert sf.d_spacing > 0.0


def test_extract_reflections_sorted_ascending():
    """反射は (h,k,l) 昇順で返る (REQ-023/NFR-102)。"""
    joint = _a_joint_result()
    sfs = extract_structure_factors(joint)
    hkls = [sf.hkl for sf in sfs]
    assert hkls == sorted(hkls)


def test_extract_bit_identical_on_repeat():
    """同一仮説から 2 回抽出でビット同一 (REQ-402/NFR-102)。"""
    joint = _a_joint_result()
    assert extract_structure_factors(joint) == extract_structure_factors(joint)


def test_extract_hist_index_selects_histogram():
    """hist_index 指定で該当ヒストの指標を用いる (決定論・非空)。"""
    joint = _a_joint_result()
    sfs0 = extract_structure_factors(joint, hist_index=0)
    sfs1 = extract_structure_factors(joint, hist_index=1)
    assert len(sfs0) >= 1 and len(sfs1) >= 1
    # 各 hist_index 内で再現的。
    assert extract_structure_factors(joint, hist_index=1) == sfs1


# ---------------------------------------------------------------------------
# (C) build_mem_input: probe→密度種別分岐 [TC-506-04/REQ-022]
# ---------------------------------------------------------------------------


def test_build_xray_selects_electron_density():
    joint = _a_joint_result()
    mi = build_mem_input(joint, "xray")
    assert mi.density_kind == "electron"


def test_build_neutron_cw_selects_nuclear_density():
    joint = _a_joint_result()
    mi = build_mem_input(joint, "neutron_cw")
    assert mi.density_kind == "nuclear"


def test_build_neutron_tof_selects_nuclear_density():
    joint = _a_joint_result()
    mi = build_mem_input(joint, "neutron_tof")
    assert mi.density_kind == "nuclear"


# ---------------------------------------------------------------------------
# (D) build_mem_input: 決定論・(h,k,l) 昇順継承・grid_shape [TC-506-05/REQ-023]
# ---------------------------------------------------------------------------


def test_build_carries_ascending_reflections():
    """MEMInput の structure_factors は (h,k,l) 昇順 (extract を継ぐ)。"""
    joint = _a_joint_result()
    mi = build_mem_input(joint, "xray")
    hkls = [sf.hkl for sf in mi.structure_factors]
    assert hkls == sorted(hkls)
    # extract_structure_factors の結果をそのまま継ぐ。
    assert mi.structure_factors == extract_structure_factors(joint)


def test_build_bit_identical_on_repeat():
    """同一入力でビット同一 MEMInput (REQ-023/NFR-102)。"""
    joint = _a_joint_result()
    assert build_mem_input(joint, "xray") == build_mem_input(joint, "xray")


def test_build_default_grid_shape():
    joint = _a_joint_result()
    mi = build_mem_input(joint, "xray")
    assert mi.grid_shape == (64, 64, 64)


def test_build_grid_shape_override():
    joint = _a_joint_result()
    mi = build_mem_input(joint, "xray", grid_shape=(48, 48, 48))
    assert mi.grid_shape == (48, 48, 48)


def test_build_lattice_from_aggregate_phase():
    """lattice は集約 phases[0] の精密化済み格子を反映する (a,b,c,α,β,γ)。"""
    joint = _a_joint_result()
    mi = build_mem_input(joint, "xray")
    lat = joint.aggregate.phases[0].lattice
    assert mi.lattice == (lat.a, lat.b, lat.c, lat.alpha, lat.beta, lat.gamma)


# ---------------------------------------------------------------------------
# (E) core-only import [TC-514-04/REQ-403]
# ---------------------------------------------------------------------------


def test_core_only_import():
    import tsumugin.mem.inputgen as inputgen

    assert inputgen.StructureFactor is StructureFactor
    assert inputgen.MEMInput is MEMInput
