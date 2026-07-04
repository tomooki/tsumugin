"""mem/dysnomia.py の失敗テスト (TASK-0055 / REQ-019/020/406 / EDGE-006 / NFR-106)。

対象実装:
- ``src/tsumugin/mem/dysnomia.py``:
  ``DysnomiaBackend`` (frozen dataclass, MEMBackend Protocol 実装) と
  ``run(mem_input: MEMInput) -> MEMResult``。
- ``src/tsumugin/mem/__init__.py``: ``DysnomiaBackend`` の re-export (__all__ 昇順)。

契約は ``docs/design/m5-nested-mem-oed/interfaces.py`` の mem/dysnomia 節に依拠。
完了条件 (TC-506-02 / TC-514-04 / REQ-019/020/406 / EDGE-006 / NFR-106) に対応する。

方針:
- Dysnomia バイナリ未導入環境が前提。``_resolve_binary`` が None を返すのを模して
  ``run()`` が ``MEMUnavailableError`` へ縮退することを検証する (実未導入でも同結果)。
- 決定論的入力生成は ``_render_input`` ヘルパを直接叩き、同一 MEMInput でビット同一を確認する。
- 実バイナリ smoke は ``@pytest.mark.mem`` で分離し、未導入環境では conftest が auto-skip する。
"""

from __future__ import annotations

import dataclasses
import shutil
from dataclasses import FrozenInstanceError, replace

import numpy as np
import pytest

from tsumugin.errors import MEMUnavailableError
from tsumugin.mem.base import MEMBackend, MEMResult
from tsumugin.mem.dysnomia import DysnomiaBackend
from tsumugin.mem.inputgen import MEMInput, StructureFactor


def _mem_input() -> MEMInput:
    """(h,k,l) 昇順の決定論的 MEMInput を組む (テスト固定入力)。"""
    factors = (
        StructureFactor(hkl=(0, 0, 1), f_obs=3.25, phase=0.0, d_spacing=5.0),
        StructureFactor(hkl=(0, 1, 0), f_obs=2.50, phase=3.14159, d_spacing=6.0),
        StructureFactor(hkl=(1, 0, 0), f_obs=1.75, phase=0.0, d_spacing=4.5),
    )
    return MEMInput(
        structure_factors=factors,
        density_kind="electron",
        lattice=(5.0, 6.0, 4.5, 90.0, 90.0, 90.0),
        space_group="P1",
        grid_shape=(32, 32, 32),
    )


# ---------------------------------------------------------------------------
# (A) frozen dataclass / 既定値 / name / MEMBackend Protocol
# ---------------------------------------------------------------------------


def test_backend_defaults_and_name():
    be = DysnomiaBackend()
    assert be.binary_path is None
    assert be.work_dir is None
    assert be.name == "dysnomia"


def test_backend_is_frozen_dataclass():
    assert dataclasses.is_dataclass(DysnomiaBackend)
    be = DysnomiaBackend()
    with pytest.raises(FrozenInstanceError):
        be.name = "x"  # type: ignore[misc]


def test_backend_satisfies_mem_backend_protocol():
    """runtime_checkable な MEMBackend Protocol を満たす。"""
    be = DysnomiaBackend()
    assert isinstance(be, MEMBackend)


# ---------------------------------------------------------------------------
# (B) core-only import [TC-514-04/REQ-403]
# ---------------------------------------------------------------------------


def test_core_only_import():
    """import tsumugin.mem.dysnomia はコア (numpy) のみで成功する (バイナリ非依存)。"""
    import tsumugin.mem.dysnomia as dysnomia

    assert dysnomia.DysnomiaBackend is DysnomiaBackend


# ---------------------------------------------------------------------------
# (C) バイナリ未検出時 run() が MEMUnavailableError [TC-506-02/REQ-020/EDGE-006]
# ---------------------------------------------------------------------------


def test_run_raises_when_binary_unavailable(monkeypatch):
    """_resolve_binary が None を返すと run() は MEMUnavailableError へ縮退する。"""
    be = DysnomiaBackend()
    monkeypatch.setattr(DysnomiaBackend, "_resolve_binary", lambda self: None)
    with pytest.raises(MEMUnavailableError):
        be.run(_mem_input())


def test_unavailable_message_mentions_install(monkeypatch):
    """案内メッセージに導入手順 (extra/バイナリ) の手がかりを含む。"""
    be = DysnomiaBackend()
    monkeypatch.setattr(DysnomiaBackend, "_resolve_binary", lambda self: None)
    with pytest.raises(MEMUnavailableError) as exc:
        be.run(_mem_input())
    assert "Dysnomia" in str(exc.value)


# ---------------------------------------------------------------------------
# (D) 決定論的入力生成 [REQ-406/NFR-106]
# ---------------------------------------------------------------------------


def test_render_input_is_deterministic():
    """同一 MEMInput から生成される入力文字列がビット同一 (決定論)。"""
    be = DysnomiaBackend()
    mi = _mem_input()
    assert be._render_input(mi) == be._render_input(mi)


def test_render_input_reflects_ascending_reflections():
    """生成入力に (h,k,l) 昇順の反射がその順で現れる (契約固定)。"""
    be = DysnomiaBackend()
    mi = _mem_input()
    text = be._render_input(mi)
    # 反射行の登場順が (h,k,l) 昇順 (入力の順序) と一致する。
    pos = [
        text.index("{0} {1} {2}".format(*sf.hkl))
        for sf in mi.structure_factors
    ]
    assert pos == sorted(pos)


def test_render_input_is_string():
    be = DysnomiaBackend()
    assert isinstance(be._render_input(_mem_input()), str)


# ---------------------------------------------------------------------------
# (E) 生データ改変なし [P2]
# ---------------------------------------------------------------------------


def test_run_does_not_mutate_input(monkeypatch):
    """run() (未導入経路) が MEMInput を改変しない (P2)。"""
    be = DysnomiaBackend()
    mi = _mem_input()
    snapshot = replace(mi)
    monkeypatch.setattr(DysnomiaBackend, "_resolve_binary", lambda self: None)
    with pytest.raises(MEMUnavailableError):
        be.run(mi)
    assert mi == snapshot


def test_render_input_does_not_mutate_input():
    """_render_input が MEMInput を改変しない (P2)。"""
    be = DysnomiaBackend()
    mi = _mem_input()
    snapshot = replace(mi)
    be._render_input(mi)
    assert mi == snapshot


# ---------------------------------------------------------------------------
# (F) @mem: 実 Dysnomia バイナリ smoke [TC-515-04/FR-602/NFR-106]
# ---------------------------------------------------------------------------


@pytest.mark.mem
def test_real_dysnomia_smoke(tmp_path):
    """実 Dysnomia バイナリで MEM を実行し MEMResult を得る (未導入時 auto-skip)。"""
    assert shutil.which("dysnomia") is not None, "conftest の auto-skip 前提が破れている"
    be = DysnomiaBackend(work_dir=str(tmp_path))
    result = be.run(_mem_input())
    assert isinstance(result, MEMResult)
    assert result.density_map.density_kind == "electron"
    assert np.isfinite(result.density_map.min_density)
    assert np.isfinite(result.density_map.max_density)
