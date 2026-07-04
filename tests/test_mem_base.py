"""mem/base.py の型基盤テスト (TASK-0053 / REQ-018/027〜031)。

MEMBackend Protocol (交換可能境界) と MEMResult 群 (frozen dataclass) の契約を検証する。
コア numpy のみに依存し、MEMInput は前方参照 (TASK-0054 定義予定) のため import しない。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.mem.base import (
    BondPathDensity,
    DensityCrossSection,
    MEMBackend,
    MEMDensityMap,
    MEMResult,
)


def _density_map() -> MEMDensityMap:
    return MEMDensityMap(
        path="/tmp/rho.grd",
        density_kind="electron",
        grid_shape=(64, 64, 64),
        min_density=-0.1,
        max_density=12.3,
    )


def test_core_only_import():
    """core-only import: numpy のみで import tsumugin.mem.base が成功する (REQ-401/403)。"""
    import tsumugin.mem.base as base

    assert base.MEMResult is MEMResult


def test_density_map_is_frozen_and_path_referenced():
    """MEMDensityMap は生成でき frozen。密度は path 参照でメモリに配列を持たない (REQ-027)。"""
    dm = _density_map()
    assert dm.path == "/tmp/rho.grd"
    assert dm.density_kind == "electron"
    assert dm.grid_shape == (64, 64, 64)
    with pytest.raises(FrozenInstanceError):
        dm.min_density = 0.0  # type: ignore[misc]

    # 【path 参照】: 実密度グリッド配列フィールドを持たず、統計 (min/max) のみ 🔵 REQ-027
    field_names = {f for f in vars(dm)}
    assert field_names == {
        "path",
        "density_kind",
        "grid_shape",
        "min_density",
        "max_density",
    }
    assert not hasattr(dm, "grid")
    assert not hasattr(dm, "density")
    assert not hasattr(dm, "values")


def test_cross_section_is_frozen():
    """DensityCrossSection は np.ndarray を保持し frozen (REQ-028)。"""
    cs = DensityCrossSection(
        label="Na1-Na2",
        dimension=1,
        coordinates=np.array([0.0, 0.5, 1.0]),
        values=np.array([1.0, 0.3, 0.9]),
    )
    assert cs.dimension == 1
    assert cs.coordinates.shape == (3,)
    with pytest.raises(FrozenInstanceError):
        cs.label = "x"  # type: ignore[misc]


def test_bond_path_density_is_frozen():
    """BondPathDensity は始点/終点/最小密度/経路長を持ち frozen (REQ-029)。"""
    bp = BondPathDensity(
        start_site="Na1",
        end_site="Na2",
        min_density=0.12,
        path_length=3.45,
    )
    assert bp.start_site == "Na1"
    assert bp.end_site == "Na2"
    assert bp.min_density == 0.12
    assert bp.path_length == 3.45
    with pytest.raises(FrozenInstanceError):
        bp.min_density = 0.0  # type: ignore[misc]


def test_mem_result_defaults():
    """MEMResult は既定値 (cross_sections=() 等) を持ち frozen (REQ-018)。"""
    r = MEMResult(density_map=_density_map())
    assert r.cross_sections == ()
    assert r.bond_paths == ()
    assert r.r_factor is None
    assert r.converged is True
    assert r.warnings == ()
    with pytest.raises(FrozenInstanceError):
        r.converged = False  # type: ignore[misc]


def test_mem_result_carries_warnings():
    """warnings に適用ガード警告を積める (REQ-030)。"""
    r = MEMResult(
        density_map=_density_map(),
        warnings=("multiphase: 信頼性低下の可能性",),
    )
    assert r.warnings == ("multiphase: 信頼性低下の可能性",)


def test_mem_result_has_no_exclusion_field():
    """Dara 教訓: 仮説除外/rejected フィールドを持たない (REQ-031)。警告のみで除外しない。"""
    r = MEMResult(density_map=_density_map())
    for forbidden in ("excluded", "rejected", "exclude", "reject", "is_rejected", "accepted"):
        assert not hasattr(r, forbidden), f"MEMResult は {forbidden} を持ってはならない (Dara 教訓)"


def test_mem_backend_is_runtime_checkable():
    """MEMBackend は runtime_checkable Protocol。name + run を持つ実装は isinstance True。"""

    class DummyBackend:
        name = "dummy"

        def run(self, mem_input):  # noqa: ANN001, ANN201 - ダミー実装
            return MEMResult(density_map=_density_map())

    assert isinstance(DummyBackend(), MEMBackend)


def test_mem_backend_rejects_incomplete_impl():
    """run を欠くオブジェクトは MEMBackend として isinstance False。"""

    class NoRun:
        name = "x"

    class NotABackend:
        pass

    assert not isinstance(NoRun(), MEMBackend)
    assert not isinstance(NotABackend(), MEMBackend)
