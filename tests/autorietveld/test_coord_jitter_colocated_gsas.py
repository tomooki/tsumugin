"""共位置の原子 (混合占有) への座標の初期摂動が実 GSAS で共位置を壊さないこと (合成 Fe(S,Se)2, Pa-3)。

engine は共位置を座標**シフト**の等値 (`_equiv_positions`) で保つだけで、値を揃え直さない。収束確認
(Phase B, `run_auto_rietveld(initial_coord_jitter=...)`) が原子ごとに別の乱数を掛けると、出発点で開いた
共位置のずれが最終座標に残り、開始点ごとに違う値 = 偽の割れ (`initial_value_dependent`) になる
(fit-then-judge P1.5 の S-dev: 混合占有の Fe2/Mg2 が T-AB でだけ x が 0.08 Å 割れた)。

S/Se の混合サイトは 3 回軸上 (x,x,x) で自由度は x の 1 つ。公開ベンチや hold-out を使わず、GSAS で
計算したパターン + Poisson ノイズで試す。
"""

from __future__ import annotations

import pytest

_CIF = """data_FeSSe
_cell_length_a 5.4500
_cell_length_b 5.4500
_cell_length_c 5.4500
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P a -3'
_symmetry_Int_Tables_number 205
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Fe1 Fe 0.00000 0.00000 0.00000 1.0 0.004
S1  S  {sx:.5f} {sx:.5f} {sx:.5f} 0.7 0.006
Se1 Se {sx:.5f} {sx:.5f} {sx:.5f} 0.3 0.006
"""

_TRUE_SX = 0.3848


def _synthetic(tmp_path):
    import numpy as np
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld.model import Radiation
    from tsumugin.instprm import build_instprm_text

    instprm = tmp_path / "cuka1.instprm"
    instprm.write_text(
        build_instprm_text(radiation=Radiation.XRAY_LAB, wavelength=1.5405980), encoding="utf-8"
    )
    truth = tmp_path / "truth.cif"
    truth.write_text(_CIF.format(sx=_TRUE_SX), encoding="utf-8")
    start = tmp_path / "start.cif"
    start.write_text(_CIF.format(sx=0.3800), encoding="utf-8")

    sim = G2sc.G2Project(newgpx=str(tmp_path / "sim.gpx"))
    sim.add_phase(str(truth), phasename="FeSSe", fmthint="CIF")
    hist = sim.add_simulated_powder_histogram(
        "sim", str(instprm), 20.0, 120.0, Tstep=0.02, phases=sim.phases()
    )
    sim.do_refinements([{}])
    x = np.asarray(hist.getdata("x"), dtype=float)
    ycalc = np.asarray(hist.getdata("ycalc"), dtype=float)
    mean = 2.0e4 * ycalc / ycalc.max() + 100.0
    y = np.random.default_rng(20261016).poisson(mean).astype(float)
    xye = tmp_path / "sim.xye"
    np.savetxt(xye, np.column_stack([x, y, np.sqrt(np.maximum(y, 1.0))]), fmt="%.6f")
    return xye, instprm, start


@pytest.mark.gsas
def test_jittered_starts_keep_a_mixed_site_colocated(tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.store.ledger import Ledger

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _synthetic(tmp_path)
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    spec = PhaseSpec(str(start), "FeSSe", mixed_occupancy_groups=(("S1", "Se1"),))

    def run(jitter_seed=None):
        jitter = None if jitter_seed is None else {"FeSSe": 0.05}
        return run_auto_rietveld(
            [hist], [spec], ledger=Ledger(), initial_coord_jitter=jitter, jitter_seed=jitter_seed or 0,
        )

    base = run()
    bs, bse = base.atom_coords["FeSSe"]["S1"], base.atom_coords["FeSSe"]["Se1"]
    assert tuple(bs) == tuple(bse), "摂動なしで共位置が開いた"

    for seed in (1, 2, 3):
        jittered = run(seed)
        assert jittered.coord_jitter_axes_moved == 1, "共位置の組の自由度 1 つだけを数える"
        s, se = jittered.atom_coords["FeSSe"]["S1"], jittered.atom_coords["FeSSe"]["Se1"]
        assert max(abs(a - b) for a, b in zip(s, se)) < 1e-9, (
            f"種 {seed}: 精密化後に S1 {s} と Se1 {se} の共位置が開いた — 出発点で別々に振った"
        )
        assert abs(s[0] - bs[0]) < 1e-4, f"種 {seed}: 摂動なしの x={bs[0]} へ戻らない ({s[0]})"
