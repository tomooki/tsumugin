"""TASK-0712/0713/0714: T4 NAC+CaF2 TOF+放射光 多相の収束検証。

GSAS-II 必須。多相・TOF・FXYE + データリミット + 適応段階解放で収束することを検証する。
チュートリアル最終 Rw 6.83% (75 変数)。自動解析は段階解放と器械プロファイルの初期化差
(11BM 背景項数・NAC mustrain 初期値など手動調整) により **~13%** まで収束する。

**T4 で確立した収束の鍵** (docs/tasks/m7-real-data-validation/AGENT_PLAYBOOK.md §4):
- データリミット必須: ノイズ領域 (11BM 高角・TOF 低d) を除くと平坦化 (nvar 凍結) が解消。
- 多相は相分率 (和=1) を格子と分離して先に解放する。
- size/微小歪みは最後に解放 (座標より先に張ると座標段階が悪化して revert)。
- size/微小歪みは低分解能 CW 中性子を除き X線/放射光・TOF に張る (TOF は高分解能)。
- TOF 装置プロファイルは精密化しない (キャリブレーション依存)。
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
def test_t4_multiphase_tof_converges():
    hx = HistogramSpec(
        data_path=str(_DATA / "11BM_NAC.fxye"),
        instrument_path=str(_DATA / "11bm_gsas.prm"),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="FXYE",
        two_theta_limits=(2.5, 32.0),  # 高角ノイズ除外 (チュートリアル)
        temperature=298.0,
    )
    ht1 = HistogramSpec(
        data_path=str(_DATA / "PG3_22048.gsa"),
        instrument_path=str(_DATA / "POWGEN_1066.instprm"),
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
        two_theta_limits=(11750.0, 103794.0),  # 低d端ノイズ除外 (TOF 単位)
        temperature=298.0,
    )
    ht2 = HistogramSpec(
        data_path=str(_DATA / "PG3_22049.gsa"),
        instrument_path=str(_DATA / "POWGEN_2665.instprm"),
        radiation=Radiation.NEUTRON_TOF,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
    )
    phases = [
        PhaseSpec(structure_path=str(_DATA / "NAC.cif"), phase_name="NAC"),
        PhaseSpec(structure_path=str(_DATA / "CaF2.cif"), phase_name="CaF2"),
    ]
    result = run_auto_rietveld([hx, ht1, ht2], phases, max_cyc=10)

    # データリミットで平坦化が解消し単調収束すること (48% 平坦 → ~13%)
    assert result.final_rwp <= 15.0, f"Rwp={result.final_rwp}"
    assert result.final_rwp < result.stage_results[0].rwp - 20.0  # S0 51% から大きく改善
    # 両相の格子が物理的 (NAC 立方 a~10.25, CaF2 蛍石 a~5.46)
    assert 10.20 < result.refined_cells["NAC"][0] < 10.30
    assert 5.42 < result.refined_cells["CaF2"][0] < 5.50
