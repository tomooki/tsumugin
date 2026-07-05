"""TASK-0704/0705: engine.run_auto_rietveld を T1 fluoroapatite 実データで検証。

GSAS-II 必須 (@pytest.mark.gsas)。データ未取得時は自動 skip。
目標: チュートリアル Rwp 10.38% / GOF 3.44 と同等 (合格基準 Rwp ≤ 12%, GOF ≤ 4.5)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld

_DATA = Path("docs/benchmark/testdata/m7/labdata")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "FAP.XRA").exists() and (_DATA / "FAP.EXP").exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T1 データ未取得")
def test_t1_labdata_reaches_tutorial_quality():
    hist = HistogramSpec(
        data_path=str(_DATA / "FAP.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(_DATA / "FAP.EXP"), phase_name="fap", format_hint="EXP"
    )
    result = run_auto_rietveld([hist], [phase])

    # 合格基準 (チュートリアル 10.38% / 3.44 と同等)
    assert result.final_rwp <= 12.0, f"Rwp={result.final_rwp}"
    assert result.final_gof <= 4.5, f"GOF={result.final_gof}"
    # 段階が単調に (概ね) 改善している
    assert result.stage_results[0].rwp > result.final_rwp
    # 物理的妥当性: 格子 fluoroapatite (a~9.37, c~6.89)
    a, b, c, al, be, ga = result.refined_cells["fap"]
    assert 9.30 < a < 9.45 and 6.80 < c < 6.95
    assert result.validity.passed, [c for c in result.validity.checks if not c[1]]
