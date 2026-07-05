"""TASK-0706/0707/0708: engine を T2 CW 中性子 garnet (混合占有) 実データで検証。

GSAS-II 必須。目標: チュートリアル Rwp 5.18% と同等 (合格基準 Rwp ≤ 6.5%, 占有率制約充足)。
中性子ロード + 占有率和=1 制約 + Uiso 等価制約 + 一般位置座標を検証する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
from tsumugin.autorietveld.engine import run_auto_rietveld

_DATA = Path("docs/benchmark/testdata/m7/cwneutron")

pytestmark = pytest.mark.gsas


def _data_present() -> bool:
    return (_DATA / "garnet.raw").exists() and (_DATA / "garnet_YFeAlO.cif").exists()


@pytest.mark.skipif(not _data_present(), reason="M7 T2 データ未取得")
def test_t2_cwneutron_mixed_occupancy_reaches_tutorial_quality():
    hist = HistogramSpec(
        data_path=str(_DATA / "garnet.raw"),
        instrument_path=str(_DATA / "inst_d1a.prm"),
        radiation=Radiation.NEUTRON_CW,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="GSAS",
    )
    phase = PhaseSpec(
        structure_path=str(_DATA / "garnet_YFeAlO.cif"),
        phase_name="garnet",
        format_hint="CIF",
        mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
    )
    result = run_auto_rietveld([hist], [phase])

    # 合格基準 (チュートリアル 5.18%)
    assert result.final_rwp <= 6.5, f"Rwp={result.final_rwp}"
    # 格子 (立方 Ia-3d, a~12.18)
    a, b, c, al, be, ga = result.refined_cells["garnet"]
    assert 12.10 < a < 12.25
    # 物理妥当性 (占有率 ∈[0,1] かつ 制約: 各サイト和=1)
    assert result.validity.passed, [c for c in result.validity.checks if not c[1]]
