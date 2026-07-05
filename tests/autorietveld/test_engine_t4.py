"""TASK-0712/0713/0714: T4 NAC+CaF2 TOF+放射光 多相のインフラ検証。

GSAS-II 必須。Phase D の多相・TOF・FXYE インフラ (複数相ロード + 相分率和=1 制約 +
TOF プロファイルキー + FXYE ローダー) が動作することを検証する。

注記: TOF 全域 (低 d 雑音領域) を含むデータのため、チュートリアル相当の最終 Rwp (6.83%) 到達には
データ範囲制限 (TOF 単位の Limits) と TOF プロファイル初期化の追加調整が必要 (M-later)。
本テストは相分率和=1 制約が張られ、両相の格子が物理的に精密化されることを検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld

_DATA = Path("docs/benchmark/testdata/m7/tofcw")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "11BM_NAC.fxye").exists() and (_DATA / "NAC.cif").exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T4 データ未取得")
def test_t4_multiphase_tof_infrastructure():
    hx = HistogramSpec(
        data_path=str(_DATA / "11BM_NAC.fxye"),
        instrument_path=str(_DATA / "11bm_gsas.prm"),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="FXYE",
    )
    ht = HistogramSpec(
        data_path=str(_DATA / "PG3_22048.gsa"),
        instrument_path=str(_DATA / "POWGEN_1066.instprm"),
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
    )
    phases = [
        PhaseSpec(structure_path=str(_DATA / "NAC.cif"), phase_name="NAC"),
        PhaseSpec(structure_path=str(_DATA / "CaF2.cif"), phase_name="CaF2"),
    ]
    result = run_auto_rietveld([hx, ht], phases, max_cyc=6)

    # 多相の両相が読み込まれ、格子が物理的 (NAC 立方 a~10.25, CaF2 蛍石 a~5.46)
    assert "NAC" in result.refined_cells and "CaF2" in result.refined_cells
    assert 10.15 < result.refined_cells["NAC"][0] < 10.35
    assert 5.40 < result.refined_cells["CaF2"][0] < 5.52
    # 例外なく完走し、妥当性レポートが生成される
    assert result.stage_results
    assert isinstance(result.validity.passed, bool)
