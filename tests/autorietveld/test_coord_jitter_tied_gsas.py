"""結束した座標への摂動が実 GSAS で結束を壊さないこと (合成 pyrite FeS2, Pa-3)。

収束確認 (Phase B, `run_auto_rietveld(initial_coord_jitter=...)`) は結束軸を動かす。GSAS は結束を
**シフト**の等値 (``dAy = (cy/cx)·dAx``, `GSASIIstrIO.py:1760-1765`) として張るだけで、精密化の
前にも途中にも従属座標を代表へ揃え直さない (2026-10-13 実測: 代表軸 x だけを振った開始点は
S が (0.3819, 0.3863, 0.3863) 等で止まり、x と y=z の差は摂動のずれのまま残った)。
代表軸だけを書き換えると対称性を破った出発点になり、開始点ごとに違う座標 = 偽の割れ
(`claims` の ``initial_value_dependent``) を作る。

pyrite の S は 3 回軸上 (x,x,x; site ``3(111)``) にあり、自由度は x の 1 つだけ。公開ベンチや
hold-out を使わず、GSAS で計算したパターン + Poisson ノイズで試す。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.agreement import COORD, is_agreement, parameter_agreements

_FES2_CIF = """data_FeS2
_cell_length_a 5.4170
_cell_length_b 5.4170
_cell_length_c 5.4170
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
S1  S  {sx:.5f} {sx:.5f} {sx:.5f} 1.0 0.006
"""

_TRUE_SX = 0.3848


def _synthetic_pyrite(tmp_path):
    """真値 (S x=0.3848) の FeS2 パターン (Poisson ノイズ付き) と、x=0.3800 の出発 CIF。"""
    import numpy as np
    from GSASII import GSASIIscriptable as G2sc

    from tsumugin.autorietveld.model import Radiation
    from tsumugin.instprm import build_instprm_text

    instprm = tmp_path / "cuka1.instprm"
    instprm.write_text(
        build_instprm_text(radiation=Radiation.XRAY_LAB, wavelength=1.5405980), encoding="utf-8"
    )
    truth = tmp_path / "fes2_truth.cif"
    truth.write_text(_FES2_CIF.format(sx=_TRUE_SX), encoding="utf-8")
    start = tmp_path / "fes2_start.cif"
    start.write_text(_FES2_CIF.format(sx=0.3800), encoding="utf-8")

    sim = G2sc.G2Project(newgpx=str(tmp_path / "sim.gpx"))
    sim.add_phase(str(truth), phasename="FeS2", fmthint="CIF")
    hist = sim.add_simulated_powder_histogram(
        "sim", str(instprm), 20.0, 120.0, Tstep=0.02, phases=sim.phases()
    )
    sim.do_refinements([{}])
    x = np.asarray(hist.getdata("x"), dtype=float)
    ycalc = np.asarray(hist.getdata("ycalc"), dtype=float)
    mean = 2.0e4 * ycalc / ycalc.max() + 100.0  # 計数統計の尺度 + 平坦な背景
    y = np.random.default_rng(20261013).poisson(mean).astype(float)
    xye = tmp_path / "fes2_sim.xye"
    np.savetxt(xye, np.column_stack([x, y, np.sqrt(np.maximum(y, 1.0))]), fmt="%.6f")
    return xye, instprm, start


@pytest.mark.gsas
def test_jittered_starts_on_a_threefold_axis_return_to_the_unjittered_solution(
    tmp_path, monkeypatch
):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.store.ledger import Ledger

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _synthetic_pyrite(tmp_path)
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )

    def run(jitter_seed=None):
        jitter = None if jitter_seed is None else {"FeS2": 0.05}
        return run_auto_rietveld(
            [hist], [PhaseSpec(str(start), "FeS2")], ledger=Ledger(),
            initial_coord_jitter=jitter, jitter_seed=jitter_seed or 0,
        )

    base = run()
    bx, by, bz = base.atom_coords["FeS2"]["S1"]
    assert bx == by == bz and abs(bx - _TRUE_SX) < 0.002, f"摂動なしの解が真値に来ない: {bx}"

    # 種 2・3 は修正前に x と y=z が 0.004-0.008 (0.02-0.04 Å) 割れた開始点
    for seed in (2, 3):
        jittered = run(seed)
        assert jittered.coord_jitter_axes_moved == 1, "S の自由度 1 つだけを振る (Fe は全固定)"
        x, y, z = jittered.atom_coords["FeS2"]["S1"]
        assert abs(x - y) < 1e-9 and abs(y - z) < 1e-9, (
            f"種 {seed}: 精密化後の S が 3 回軸から外れた ({x}, {y}, {z}) — 結束が壊れた出発点"
        )
        # 雑音や esd の見積もりに依らない判定: 修正後は摂動なしの x から 5e-7 以内に戻る
        #   (2026-10-13 実測, 種 1-8)。修正前は種 2 で 2.9e-3・種 3 で 5.1e-3 ずれた
        #   (種 2 は esd/床の内側なので一致判定だけでは捕まらない)
        assert abs(x - bx) < 1e-5, f"種 {seed}: 摂動なしの S x={bx} へ戻らない ({x})"
        coords = parameter_agreements(base, jittered)[COORD]
        assert coords, "座標の突き合わせが空 (比較していないのに一致と言わない)"
        split = [(p.key, p.verdict, p.delta) for p in coords if not is_agreement(p.verdict)]
        assert not split, f"種 {seed}: 摂動なしの解と割れた座標 (偽の割れ): {split}"


@pytest.mark.gsas
def test_the_initial_value_probe_moves_a_tied_site_and_it_comes_back(tmp_path, monkeypatch):
    """初期値プローブ (±0.05 Å) も結束した組を組ごと振り、S は 3 回軸上のまま戻る → 3 軸とも証人が付く。

    以前のプローブは結束座標を振らなかった (代表だけ振ると結束が壊れるため) ので、高対称構造の
    結束座標には `locally_stable` が付かなかった。
    """
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.probe import ProbeConfig, run_initial_value_probe
    from tsumugin.claims.build import base_claims, with_probe
    from tsumugin.claims.model import Determinacy

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _synthetic_pyrite(tmp_path)
    hist = HistogramSpec(
        data_path=str(xye), instrument_path=str(instprm),
        radiation=Radiation.XRAY_LAB, geometry=Geometry.DEBYE_SCHERRER, data_format="XYE",
    )
    base = run_auto_rietveld([hist], [PhaseSpec(str(start), "FeS2")])
    bx = base.atom_coords["FeS2"]["S1"][0]

    outcome = run_initial_value_probe(
        base.gpx_path, ProbeConfig(cell_frac=0.0, coord_jitter_ang=0.05)
    )
    assert outcome.complete, outcome.errors
    keys = ("FeS2.S1.x", "FeS2.S1.y", "FeS2.S1.z")
    for probe in outcome.probes:
        assert probe.coord_jitter_moved == keys, "Fe は全固定・S は組の 3 軸を振る"
        assert probe.coord_jitter_shift == pytest.approx(
            {k: 0.05 / 5.417 for k in keys}, rel=1e-3
        ), "立方晶 (x,x,x) は 3 軸とも amp Å ちょうど"
        x, y, z = probe.atom_coords["FeS2"]["S1"]
        assert abs(x - y) < 1e-9 and abs(y - z) < 1e-9, "プローブ後も 3 回軸上"
        assert abs(x - bx) < 1e-5, f"S x が戻らない: {x} vs {bx}"

    claims = with_probe(base_claims(base), base, outcome)
    for k in keys:
        assert claims[f"coord:{k}"].determinacy is Determinacy.LOCALLY_STABLE, k
