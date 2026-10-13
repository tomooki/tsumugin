"""fit-then-judge P1-1B タスク 12: テンプレートの e2e を実 GSAS で (合成 `S-dev`)。

hold-out と別の構造 (wurtzite ZnO + 岩塩 NaCl) から GSAS で計算したパターンに計数雑音を足して使う。
pass 1 → コンパイル → pass 2 が完走し、**コンパイル結果を `run_auto_rietveld(recipe=…)` に渡すだけで
ビット同一に再生できる** (REQ-FTJ-1B-401 の不変条件) ことを確かめる。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gsas

_ZNO = """data_ZnO
_cell_length_a 3.2500
_cell_length_b 3.2500
_cell_length_c 5.2070
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
_symmetry_space_group_name_H-M 'P 63 m c'
_symmetry_Int_Tables_number 186
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Zn1 Zn 0.33333333 0.66666667 0.00000 1.0 0.008
O1  O  0.33333333 0.66666667 {oz:.5f} 1.0 0.010
"""

_NACL = """data_NaCl
_cell_length_a 5.6400
_cell_length_b 5.6400
_cell_length_c 5.6400
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'F m -3 m'
_symmetry_Int_Tables_number 225
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Na1 Na 0.0 0.0 0.0 1.0 0.012
Cl1 Cl 0.5 0.5 0.5 1.0 0.012
"""


def _synthetic(tmp_path):
    """ZnO (主) + NaCl (副) の CW X 線パターン (真値 O z=0.382・計数雑音つき)。"""
    import numpy as np
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld.model import Radiation
    from tsumugin.instprm import build_instprm_text

    instprm = tmp_path / "cuka1.instprm"
    instprm.write_text(
        build_instprm_text(radiation=Radiation.XRAY_LAB, wavelength=1.5405980), encoding="utf-8"
    )
    zno_truth = tmp_path / "zno_truth.cif"
    zno_truth.write_text(_ZNO.format(oz=0.382), encoding="utf-8")
    nacl = tmp_path / "nacl.cif"
    nacl.write_text(_NACL, encoding="utf-8")
    zno_start = tmp_path / "zno_start.cif"
    zno_start.write_text(_ZNO.format(oz=0.372), encoding="utf-8")

    sim = G2sc.G2Project(newgpx=str(tmp_path / "sim.gpx"))
    sim.add_phase(str(zno_truth), phasename="ZnO", fmthint="CIF")
    sim.add_phase(str(nacl), phasename="NaCl", fmthint="CIF")
    hist = sim.add_simulated_powder_histogram(
        "sim", str(instprm), 20.0, 120.0, Tstep=0.02, phases=sim.phases()
    )
    nacl_ph = sim.phase("NaCl")
    nacl_ph.setHAPvalues({"Scale": [0.3, False]}, targethistlist=[hist])
    sim.do_refinements([{}])
    x = np.asarray(hist.getdata("x"), dtype=float)
    ycalc = np.asarray(hist.getdata("ycalc"), dtype=float)
    y = 2.0e4 * ycalc / ycalc.max() + 100.0 + 30.0 * np.exp(-(x - 20.0) / 30.0)
    y = np.random.default_rng(0).poisson(y).astype(float)
    xye = tmp_path / "mix.xye"
    np.savetxt(xye, np.column_stack([x, y, np.sqrt(np.maximum(y, 1.0))]), fmt="%.6f")
    return xye, instprm, zno_start, nacl


def test_the_template_compiles_runs_and_replays_bit_identically(tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.search import run_recipe_search
    from tsumugin.store import Ledger

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, zno, nacl = _synthetic(tmp_path)
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO, data_format="XYE",
    )
    phases = [PhaseSpec(str(zno), "ZnO"), PhaseSpec(str(nacl), "NaCl")]
    ledger = Ledger()
    summary = run_recipe_search([hist], phases, names=["template"], ledger=ledger)
    outcome = summary.outcomes[0]
    assert outcome.error == "", outcome.error
    cand, result = outcome.candidate, outcome.result
    d = cand.derivation
    assert d["decisions"]["target_phase"] == "ZnO"
    assert d["evidence"]["background"]["status"] == "pass"
    assert [s.label.split(" ")[1] for s in cand.stages][-1] == "final"
    nacl_spec = next(p for p in cand.phases if p.phase_name == "NaCl")
    assert set(nacl_spec.frozen_coord_labels) == {"Na1", "Cl1"}
    # 構造は真値へ戻る (対象相の座標を精密化した)
    assert abs(result.atom_coords["ZnO"]["O1"][2] - 0.382) < 0.004
    # pass 1 の成果物も残っている (役割名 template_pass1)
    kinds = [e.kind for e in ledger.entries]
    assert "template_pass1" in kinds and kinds.count("template_pass1_trial") >= 2

    # 【再生】: コンパイル結果を recipe= に渡すだけで同じ fit になる (動的な器が無い)
    replay = run_auto_rietveld(
        list(cand.histograms), list(cand.phases), recipe=cand.stages,
        stability=cand.stability, blas_threads=cand.blas_threads, save_gpx=False,
    )
    assert replay.final_rwp == result.final_rwp
    assert replay.refined_cells == result.refined_cells
    assert [(s.label, s.rwp, s.n_params, s.reverted) for s in replay.stage_results] == [
        (s.label, s.rwp, s.n_params, s.reverted) for s in result.stage_results
    ]
