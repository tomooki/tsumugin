"""fit-then-judge P1c タスク 2: MEM 系ツールが入力 gpx の出版状態を添える (拒否はしない)。"""

from __future__ import annotations

import json

import pytest

from tsumugin.mcp.mem_tools import mem_density, mem_rietveld_iterate


@pytest.fixture
def fake_mem(monkeypatch):
    from tsumugin.mem.gsas import MEMDensityResult

    def run(gpx_path, *, phase_name, hist_name, config, out_grd):
        from tsumugin.mem.base import MEMDensityMap

        return MEMDensityResult(
            density_map=MEMDensityMap(path="x.grd", density_kind="electron", grid_shape=(2, 2, 2),
                                      min_density=-1.0, max_density=5.0),
            pre_min=-1.0, pre_max=4.0, n_reflections=10, mem_r_factor=None, converged=True,
            density_kind="electron",
        )

    monkeypatch.setattr("tsumugin.mem.gsas.run_dysnomia_mem", run)


def _gpx_with_state(tmp_path):
    from tsumugin.autorietveld.claim_variables import PhaseVariables, claim_variable_names
    from tsumugin.autorietveld.diagnostics import CovarianceRecord
    from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
    from tsumugin.claims.publication import publication_state

    result = AutoRietveldResult(
        stage_results=(StageResult("S0", 10.0, 1.2, 5, True),), final_rwp=10.0, final_gof=1.2,
        refined_cells={"P": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)}, validity=ValidityReport(passed=True),
        atom_coords={"P": {"O1": (0.25, 0.1, 0.3)}},
        atom_coord_esd={"P": {"O1": (0.001, 0.002, None)}},
        atom_coord_free_index={"P": {"O1": (1, 2, 3)}},
        final_covariance=CovarianceRecord(vary_list=("0::dAx:0",), dependent=(), correlations=()),
        claim_variables=claim_variable_names([PhaseVariables(name="P", pid=0, labels=("O1",))], []),
    )
    gpx = tmp_path / "fit.gpx"
    gpx.write_bytes(b"gpx")
    publication_state(result, None, gpx_path=str(gpx))
    return str(gpx)


def test_mem_on_a_gpx_without_a_sidecar_runs_and_says_the_state_is_unknown(tmp_path, fake_mem):
    gpx = tmp_path / "old.gpx"
    gpx.write_bytes(b"gpx")
    out = mem_density(str(gpx))
    assert "error" not in out
    assert out["input_publication"]["state"] == "unknown"
    json.dumps(out, allow_nan=False)


def test_mem_reports_held_structure_values_of_the_input(tmp_path, fake_mem):
    out = mem_density(_gpx_with_state(tmp_path))
    pub = out["input_publication"]
    assert pub["state"] == "known" and "coord:P.O1.x" in pub["structure_held"]
    assert pub["blocking_requests"]


def test_mpf_children_are_marked_unknown_and_the_input_state_is_reported(tmp_path, monkeypatch):
    from tsumugin.mem.mpf import MPFCycle, MPFResult

    def fake_run(gpx_path, *, phase_name, hist_name, config, snapshot_dir, ledger):
        ledger.append("mpf_probe", {"n": 1})
        return MPFResult(
            cycles=(MPFCycle(0, "mpf_iter0.gpx", 8.0, 5.0, -1.0, None, 0),),
            stop_reason="converged",
        )

    monkeypatch.setattr("tsumugin.mem.mpf.run_mem_rietveld_gpx", fake_run)
    out = mem_rietveld_iterate(_gpx_with_state(tmp_path))
    assert out["input_publication"]["state"] == "known"
    assert out["cycles"][0]["publication_state"] == "unknown"
    json.dumps(out, allow_nan=False)
