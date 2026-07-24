"""Issue #130 L6: discriminate ツールの実データ GSAS end-to-end カナリア (@pytest.mark.gsas)。

route X の全鎖 (JSON → GSASIIBackend + FrameSeries + PhaseInstance.structure_ref 実 CIF →
discriminate_interval) が実際に走り、構造化 verdict を返すことを実証する。特定 verdict は
アサートしない (合成系列依存で脆いため) — GSAS 判別パイプラインが実 CIF 構造で完走し、
error dict でなく valid な verdict を返すことを確認する。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gsas

_PBSO4_CIF = "docs/benchmark/testdata/PbSO4-Wyckoff.cif"


def _present() -> bool:
    return Path(_PBSO4_CIF).exists()


def _solid_solution_series(n_frames: int = 3):
    """PbSO4 単相の格子 a を微小連続変化させた合成系列 (固溶体的) を GSAS で作る。"""
    from tsumugin.backends.gsasii import GSASIIBackend
    from tsumugin.model import LatticeParams, PhaseInstance

    backend = GSASIIBackend()
    tt = np.arange(20.0, 55.0, 0.05)
    rows = []
    for i in range(n_frames):
        a = 8.48 + 0.02 * i  # a を連続シフト (固溶体シグネチャ)
        phase = PhaseInstance(
            phase_ref="pbso4",
            lattice=LatticeParams(a, 5.398, 6.958),
            scale=1.0,
            structure_ref=_PBSO4_CIF,
        )
        rows.append(backend.simulate((phase,), tt))
    return tt, np.vstack(rows)


@pytest.mark.skipif(not _present(), reason="PbSO4 CIF 未取得")
def test_discriminate_runs_end_to_end_on_real_cif():
    from tsumugin.mcp.discriminate_tools import discriminate

    tt, intensities = _solid_solution_series(n_frames=3)
    out = discriminate(
        series={"two_theta": tt.tolist(), "intensities": intensities.tolist()},
        initial_phases=[
            {
                "phase_ref": "pbso4",
                "lattice": {"a": 8.48, "b": 5.398, "c": 6.958},
                "structure_ref": _PBSO4_CIF,
            }
        ],
        frame_range=[0, 2],
        config={"multistart": {"n_starts": 2}, "seq_max_cycles": 4},
    )
    # error dict でなく構造化 verdict が返る (全鎖が実 CIF 構造で完走)
    assert "error" not in out, out
    assert out["verdict"] in ("solid_solution", "two_phase", "undecided")
    assert out["adjudicated_by"] in ("bic", "nested", "laplace")
    assert isinstance(out["delta_evidence"], float)
    assert out["hypothesis_single"]["n_starts"] == 2


@pytest.mark.skipif(not _present(), reason="PbSO4 CIF 未取得")
def test_discriminate_nested_opt_in_runs_on_real_cif():
    # 僅差時の nested 物理尤度裁定 (#76) オプトインが実 CIF 経路で例外なく走る
    from tsumugin.mcp.discriminate_tools import discriminate

    tt, intensities = _solid_solution_series(n_frames=3)
    out = discriminate(
        series={"two_theta": tt.tolist(), "intensities": intensities.tolist()},
        initial_phases=[
            {
                "phase_ref": "pbso4",
                "lattice": {"a": 8.48, "b": 5.398, "c": 6.958},
                "structure_ref": _PBSO4_CIF,
            }
        ],
        frame_range=[0, 2],
        config={
            "multistart": {"n_starts": 2},
            "seq_max_cycles": 4,
            "nested_arbitration": {},
        },
    )
    assert "error" not in out, out
    assert out["verdict"] in ("solid_solution", "two_phase", "undecided")
