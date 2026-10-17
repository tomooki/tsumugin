"""P0 §6.2: 合成パターンの生成を実 GSAS で確かめる (合成 `S-dev` だけ — hold-out に触れない)。"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gsas

# 単位胞の質量が ZnO (Z=2, 約 163) の約 3 倍 (FeS2 Z=4, 約 480) — Scale を重量分率そのものにする誤りを検出できる
_PYRITE = """data_pyrite
_cell_length_a 5.4166
_cell_length_b 5.4166
_cell_length_c 5.4166
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P a -3'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Fe1 Fe 0 0 0 1 0.004
S1 S 0.3848 0.3848 0.3848 1 0.005
"""


def _zno_cif(tmp_path):
    src = Path(__file__).resolve().parents[1] / "autorietveld" / "test_engine_polar_origin.py"
    spec = importlib.util.spec_from_file_location("_zno_cif_synth", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = tmp_path / "zno.cif"
    p.write_text(mod._ZNO_CIF.format(oz=0.382), encoding="utf-8")
    return p


def test_weight_fractions_come_back_out_of_a_refinement(tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    zno = _zno_cif(tmp_path)
    rut = tmp_path / "pyrite.cif"
    rut.write_text(_PYRITE, encoding="utf-8")
    sim = simulate_pattern(
        [SimPhase(str(zno), "ZnO", 0.7), SimPhase(str(rut), "FeS2", 0.3)],
        instrument="sync_ds", out_dir=str(tmp_path / "sim"), stem="mix", max_counts=1e5, seed=1,
    )
    data = np.loadtxt(sim.xye_path)
    assert data.shape[1] == 3 and data[:, 1].max() > 0.9e5
    hist = HistogramSpec(data_path=sim.xye_path, instrument_path=sim.instprm_path,
                         radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER,
                         data_format="XYE")
    res = run_auto_rietveld([hist], [PhaseSpec(str(zno), "ZnO"), PhaseSpec(str(rut), "FeS2")])
    assert res.phase_weight_fractions["ZnO"] == pytest.approx(0.7, abs=0.02)
    assert res.final_rwp < 15.0


@pytest.mark.parametrize("mismatch", ["asymmetry", "kalpha2_ratio", "impurity_peak", "amorphous_hump"])
def test_each_mismatch_changes_the_truth_not_the_refinement_file(tmp_path, mismatch):
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    zno = _zno_cif(tmp_path)
    clean = simulate_pattern([SimPhase(str(zno), "ZnO", 1.0)], instrument="lab_bb", out_dir=str(tmp_path / "a"),
                             stem="c", max_counts=1e4, seed=3)
    bent = simulate_pattern([SimPhase(str(zno), "ZnO", 1.0)], instrument="lab_bb", out_dir=str(tmp_path / "b"),
                            stem="c", max_counts=1e4, seed=3, mismatches=(mismatch,))
    assert Path(clean.instprm_path).read_text() == Path(bent.instprm_path).read_text()
    assert not np.allclose(clean.ycalc, bent.ycalc)


def test_zero_offset_moves_the_peaks_by_that_much(tmp_path):
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    zno = _zno_cif(tmp_path)
    a = simulate_pattern([SimPhase(str(zno), "ZnO", 1.0)], instrument="lab_bb", out_dir=str(tmp_path / "a"),
                         stem="z", max_counts=1e4, seed=3)
    b = simulate_pattern([SimPhase(str(zno), "ZnO", 1.0)], instrument="lab_bb", out_dir=str(tmp_path / "b"),
                         stem="z", max_counts=1e4, seed=3, zero_deg=0.2)
    shift = float(b.x[np.argmax(b.ycalc)] - a.x[np.argmax(a.ycalc)])
    assert shift == pytest.approx(0.2, abs=0.03)
