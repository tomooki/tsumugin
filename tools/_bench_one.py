"""ベンチマーク 1 件を実行して JSON を 1 行 stdout に出す (`bench_recipes.py` の子プロセス)。

⚠ **spec は `tests/autorietveld/test_engine_t*.py` と 1 対 1 で一致させること。** 実測事故:
T3 の ``temperature=295/10`` を落としたら `temp_diff` が立たず `hydrostatic_strain` (Dij) 段が
消えて Rwp 6.66% → 12.56% になり、「回帰した」と誤読しかけた。**ハーネスがテストと違う条件を
測っていると、以降の全判断が狂う。**

**別プロセスで動かす前提**: GSAS-II はグローバル状態を多く持つため、1 件 1 プロセスにして
並列化と隔離を同時に得る。親は stdout の最終 JSON 行だけを読む。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))

_DATA = _REPO / "docs" / "benchmark" / "testdata"


def _specs(dataset: str):
    """(histograms, phases, background_coeffs, max_cyc) を組む。"""
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation

    if dataset == "T1":
        d = _DATA / "m7/labdata"
        return ([HistogramSpec(data_path=str(d / "FAP.XRA"), instrument_path=str(d / "INST_XRY.PRM"),
                               radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                               data_format="GSAS")],
                [PhaseSpec(structure_path=str(d / "FAP.EXP"), phase_name="fap", format_hint="EXP")],
                6, 12)
    if dataset == "T2":
        d = _DATA / "m7/cwneutron"
        return ([HistogramSpec(data_path=str(d / "garnet.raw"), instrument_path=str(d / "inst_d1a.prm"),
                               radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS")],
                [PhaseSpec(structure_path=str(d / "garnet_YFeAlO.cif"), phase_name="garnet",
                           format_hint="CIF",
                           mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")))],
                6, 12)
    if dataset == "T3":
        d = _DATA / "m7/cwcombined"
        return ([HistogramSpec(data_path=str(d / "PBSO4.XRA"), instrument_path=str(d / "INST_XRY.PRM"),
                               radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                               data_format="GSAS", temperature=295.0),
                 HistogramSpec(data_path=str(d / "PBSO4.CWN"), instrument_path=str(d / "inst_d1a.prm"),
                               radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS", temperature=10.0)],
                [PhaseSpec(structure_path=str(_DATA / "PbSO4-Wyckoff.cif"), phase_name="PbSO4",
                           format_hint="CIF")],
                6, 12)
    if dataset == "T4":
        d = _DATA / "m7/tofcw"
        return ([HistogramSpec(data_path=str(d / "11BM_NAC.fxye"), instrument_path=str(d / "11bm_gsas.prm"),
                               radiation=Radiation.XRAY_SYNCHROTRON, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="FXYE", two_theta_limits=(3.0, 40.0)),
                 HistogramSpec(data_path=str(d / "PG3_22048.gsa"), instrument_path=str(d / "POWGEN_1066.instprm"),
                               radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS", bank=1, two_theta_limits=(2000.0, 15000.0)),
                 HistogramSpec(data_path=str(d / "PG3_22049.gsa"), instrument_path=str(d / "POWGEN_2665.instprm"),
                               radiation=Radiation.NEUTRON_TOF, geometry=Geometry.DEBYE_SCHERRER,
                               data_format="GSAS", bank=1, two_theta_limits=(2000.0, 30000.0))],
                [PhaseSpec(structure_path=str(d / "NAC.cif"), phase_name="NAC"),
                 PhaseSpec(structure_path=str(d / "CaF2.cif"), phase_name="CaF2")],
                6, 12)
    if dataset == "CaTeO3":
        from tsumugin.insitu.engine import _xrdml_to_xye

        d = _DATA / "m9/cateo3"
        tmp = Path(tempfile.mkdtemp(prefix="bench-cateo3-"))
        xye = tmp / "frame.xye"
        _xrdml_to_xye(str(d / "NB-LM01MO_030.XRDML"), str(xye))
        return ([HistogramSpec(data_path=str(xye), instrument_path=str(d / "cateo3_CuKa.instprm"),
                               radiation=Radiation.XRAY_LAB, geometry=Geometry.BRAGG_BRENTANO,
                               data_format="XYE", two_theta_limits=(12.0, 70.0))],
                [PhaseSpec(structure_path=str(d / "alpha_CaTeO3_H2O.cif"), phase_name="alpha")],
                24, 20)
    raise SystemExit(f"unknown dataset: {dataset}")


def main() -> int:
    dataset, recipe_name = sys.argv[1], sys.argv[2]
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.recipe import build_recipe, build_serious_recipe

    hists, phases, bg, max_cyc = _specs(dataset)
    if recipe_name == "serious":
        recipe = build_serious_recipe(hists, phases, background_coeffs=bg)
    else:
        recipe = build_recipe(hists, phases, background_coeffs=bg)

    result = run_auto_rietveld(hists, phases, recipe=recipe, max_cyc=max_cyc)
    payload = {
        "dataset": dataset,
        "recipe": recipe_name,
        "rwp": float(result.final_rwp) if result.final_rwp == result.final_rwp else None,
        "gof": float(result.final_gof) if result.final_gof == result.final_gof else None,
        "n_stages": len(result.stage_results),
        "n_reverted": sum(1 for s in result.stage_results if s.reverted),
        "detail": f"validity={'pass' if result.validity.passed else 'fail'}",
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
