"""P0 §5: 反証プローブを実 GSAS の保存 gpx に当てる (合成 `S-dev` だけ — hold-out に触れない)。"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytestmark = pytest.mark.gsas


def _zno_cif(tmp_path):
    src = Path(__file__).resolve().parents[1] / "autorietveld" / "test_engine_polar_origin.py"
    spec = importlib.util.spec_from_file_location("_zno_cif_probe", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    p = tmp_path / "zno.cif"
    p.write_text(mod._ZNO_CIF.format(oz=0.382), encoding="utf-8")
    return p


def _fit(tmp_path, monkeypatch, zero_deg):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    zno = _zno_cif(tmp_path)
    sim = simulate_pattern([SimPhase(str(zno), "ZnO", 1.0)], instrument="sync_ds", out_dir=str(tmp_path / "sim"),
                           stem="z", max_counts=1e5, seed=5, zero_deg=zero_deg)
    hist = HistogramSpec(data_path=sim.xye_path, instrument_path=sim.instprm_path,
                         radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    # 既定のレシピは DS で zero_offset を解放するので、ゼロ点を固定する既定を作るために格子と幅だけの段にする
    from tsumugin.autorietveld.model import RefinementStage

    recipe = (RefinementStage("S0", {"scale": True, "background": {"coeffs": 6}}),
              RefinementStage("S1", {"cell": True}), RefinementStage("S2", {"profile": ["U", "V", "W"]}))
    return run_auto_rietveld([hist], [PhaseSpec(str(zno), "ZnO")], recipe=recipe)


def test_a_real_zero_offset_refutes_the_fixed_zero_default(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _fit(tmp_path, monkeypatch, zero_deg=0.05)
    before = hashlib.sha256(Path(res.gpx_path).read_bytes()).hexdigest()
    out = run_probe(res.gpx_path, "zero_fixed")
    assert out.outcome == "refuted" and out.k == 1 and out.statistic > 10
    # Hamilton の R 比 Δχ²/GOF²_big (P0 §5.1: GOF² は大きい模型の値)
    assert out.statistic == pytest.approx((out.chi2_small - out.chi2_big) / out.gof2, rel=1e-12)
    assert out.chi2_big < out.chi2_small
    assert out.power is not None and 0.0 < out.power <= 1.0
    assert hashlib.sha256(Path(res.gpx_path).read_bytes()).hexdigest() == before  # 写しで行う


def test_no_zero_offset_does_not_refute(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _fit(tmp_path, monkeypatch, zero_deg=0.0)
    out = run_probe(res.gpx_path, "zero_fixed")
    assert out.outcome in ("not_refuted", "not_refuted_low_power")
    assert np.isfinite(out.lam)


_PYRITE = """data_pyrite
_cell_length_a {a}
_cell_length_b {a}
_cell_length_c {a}
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
S1 S {x} {x} {x} 1 0.005
"""


def _mix_fit(tmp_path, monkeypatch, *, start_a, start_x, refine_cell, freeze_coords, start_s_uiso=0.005,
             freeze_uiso=False):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import RefinementStage
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    zno = _zno_cif(tmp_path)
    truth = tmp_path / "fes2_truth.cif"
    truth.write_text(_PYRITE.format(a=5.4166, x=0.3848), encoding="utf-8")
    start = tmp_path / "fes2_start.cif"
    start.write_text(_PYRITE.format(a=start_a, x=start_x).replace("1 0.005", f"1 {start_s_uiso:.3f}"),
                     encoding="utf-8")
    sim = simulate_pattern([SimPhase(str(zno), "ZnO", 0.8), SimPhase(str(truth), "FeS2", 0.2)],
                           instrument="sync_ds", out_dir=str(tmp_path / "sim"), stem="m", max_counts=1e5, seed=9)
    hist = HistogramSpec(data_path=sim.xye_path, instrument_path=sim.instprm_path,
                         radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    minor = PhaseSpec(str(start), "FeS2", refine_cell=refine_cell,
                      frozen_coord_labels=("Fe1", "S1") if freeze_coords else (),
                      frozen_uiso_labels=("Fe1", "S1") if freeze_uiso else ())
    recipe = (RefinementStage("S0", {"scale": True, "background": {"coeffs": 6}, "phase_fraction_sum": True}),
              RefinementStage("S1", {"cell": True}), RefinementStage("S2", {"profile": ["U", "V", "W"]}),
              RefinementStage("S3", {"coords": True}), RefinementStage("S4", {"uiso": True}))
    return run_auto_rietveld([hist], [PhaseSpec(str(zno), "ZnO"), minor], recipe=recipe)


def test_a_wrong_frozen_minor_cell_is_refuted(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _mix_fit(tmp_path, monkeypatch, start_a=5.4166 * 1.004, start_x=0.3848, refine_cell=False,
                   freeze_coords=False)
    out = run_probe(res.gpx_path, "minor_cell_frozen", phase="FeS2")
    assert out.outcome == "refuted", out
    assert out.k == 1  # 立方晶は独立な格子定数が 1 つ (A0)


def test_a_right_frozen_minor_cell_is_not_refuted(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _mix_fit(tmp_path, monkeypatch, start_a=5.4166, start_x=0.3848, refine_cell=False, freeze_coords=False)
    out = run_probe(res.gpx_path, "minor_cell_frozen", phase="FeS2")
    assert out.outcome in ("not_refuted", "not_refuted_low_power"), out
    assert out.lam is not None and out.lam > 0


def test_wrong_frozen_minor_coordinates_are_refuted(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _mix_fit(tmp_path, monkeypatch, start_a=5.4166, start_x=0.3748, refine_cell=True, freeze_coords=True)
    out = run_probe(res.gpx_path, "minor_coords_frozen", phase="FeS2")
    assert out.outcome == "refuted", out
    assert out.k == 1  # S の (x,x,x) は自由度 1


def test_a_wrong_frozen_minor_uiso_is_refuted(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    # 真値の S の Uiso 0.005 を 0.040 のまま凍結した
    res = _mix_fit(tmp_path, monkeypatch, start_a=5.4166, start_x=0.3848, refine_cell=True, freeze_coords=False,
                   start_s_uiso=0.040, freeze_uiso=True)
    out = run_probe(res.gpx_path, "minor_uiso_frozen", phase="FeS2")
    assert out.outcome == "refuted", out
    assert out.k >= 1


def _zno_grouped_fit(tmp_path, monkeypatch, *, o_uiso):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import RefinementStage
    from tsumugin.prereg_eval.synth_gsas import SimPhase, simulate_pattern

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    base = _zno_cif(tmp_path).read_text(encoding="utf-8")
    truth = tmp_path / "zno_truth.cif"
    truth.write_text(base.replace("0.010\n", f"{o_uiso:.3f}\n"), encoding="utf-8")
    sim = simulate_pattern([SimPhase(str(truth), "ZnO", 1.0)], instrument="sync_ds", out_dir=str(tmp_path / "sim"),
                           stem="u", max_counts=1e5, seed=13)
    hist = HistogramSpec(data_path=sim.xye_path, instrument_path=sim.instprm_path,
                         radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    recipe = (RefinementStage("S0", {"scale": True, "background": {"coeffs": 6}}),
              RefinementStage("S1", {"cell": True}), RefinementStage("S2", {"profile": ["U", "V", "W"]}),
              RefinementStage("S3", {"coords": True}), RefinementStage("S4", {"uiso": True}))
    phase = PhaseSpec(str(_zno_cif(tmp_path)), "ZnO", uiso_equiv_groups=(("Zn1", "O1"),))
    return run_auto_rietveld([hist], [phase], recipe=recipe)


def test_wrong_uiso_grouping_is_refuted(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _zno_grouped_fit(tmp_path, monkeypatch, o_uiso=0.030)  # Zn 0.008・O 0.030 を 1 つにまとめた
    out = run_probe(res.gpx_path, "uiso_grouping", phase="ZnO")
    assert out.outcome == "refuted", out
    assert out.k >= 1  # まとめを外して増えた変数 (元の fit で Uiso の段が棄却されていれば 2)


def test_right_uiso_grouping_is_not_refuted(tmp_path, monkeypatch):
    from tsumugin.prereg_eval.probe_run import run_probe

    res = _zno_grouped_fit(tmp_path, monkeypatch, o_uiso=0.008)  # 真値も等しい
    out = run_probe(res.gpx_path, "uiso_grouping", phase="ZnO")
    assert out.outcome in ("not_refuted", "not_refuted_low_power"), out
