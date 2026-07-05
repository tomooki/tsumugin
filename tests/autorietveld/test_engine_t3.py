"""TASK-0709/0710/0711: engine を T3 PbSO4 X線+CW中性子 joint 実データで検証。

GSAS-II 必須。目標: チュートリアル 合計 wR 6.71% と同等 (合格基準 合計 Rwp ≤ 8%)。
複数ヒストグラム (共有構造) + 温度差 Dij + size/strain X線限定を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld

_DATA = Path("docs/benchmark/testdata/m7/cwcombined")
_CIF = Path("docs/benchmark/testdata/PbSO4-Wyckoff.cif")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "PBSO4.XRA").exists() and (_DATA / "PBSO4.CWN").exists() and _CIF.exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T3 データ未取得")
def test_t3_joint_xray_neutron_reaches_tutorial_quality():
    xray = HistogramSpec(
        data_path=str(_DATA / "PBSO4.XRA"),
        instrument_path=str(_DATA / "INST_XRY.PRM"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="GSAS",
        temperature=295.0,
    )
    neutron = HistogramSpec(
        data_path=str(_DATA / "PBSO4.CWN"),
        instrument_path=str(_DATA / "inst_d1a.prm"),
        radiation=Radiation.NEUTRON_CW,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
        temperature=10.0,
    )
    phase = PhaseSpec(structure_path=str(_CIF), phase_name="PbSO4", format_hint="CIF")
    result = run_auto_rietveld([xray, neutron], [phase])

    # 合格基準 (チュートリアル合計 wR 6.71%)
    assert result.final_rwp <= 8.0, f"Rwp={result.final_rwp}"
    # PbSO4 (Pnma) 格子 a~8.48, b~5.40, c~6.96
    a, b, c, al, be, ga = result.refined_cells["PbSO4"]
    assert 8.44 < a < 8.52 and 5.36 < b < 5.44 and 6.92 < c < 7.00
    assert result.validity.passed, [c for c in result.validity.checks if not c[1]]
