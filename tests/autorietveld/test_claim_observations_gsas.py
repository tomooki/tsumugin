"""fit-then-judge P1-1A タスク 2: engine が足した観測フィールドが実 GSAS で埋まること。

`final_covariance` (最終 varyList・従属・強い相関) / `claim_variables` (値 → GSAS 変数) /
`reflection_two_theta` (計算反射の位置)。観測のみでフィットは変えない (既定経路のビット同一は
`test_golden_default_routes.py` が縛る)。データは T2 garnet (hold-out ではない)。
"""

from __future__ import annotations

from pathlib import Path

import pytest

_T2 = Path("docs/benchmark/testdata/m7/cwneutron")

pytestmark = [
    pytest.mark.gsas,
    pytest.mark.skipif(
        not all((_T2 / f).exists() for f in ("garnet.raw", "garnet_YFeAlO.cif", "inst_d1a.prm")),
        reason="M7 T2 データ未取得",
    ),
]


@pytest.fixture(scope="module")
def garnet_result(tmp_path_factory):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld

    tmp = tmp_path_factory.mktemp("claims_obs")
    hist = HistogramSpec(
        data_path=str(_T2 / "garnet.raw"), instrument_path=str(_T2 / "inst_d1a.prm"),
        radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER, data_format="GSAS",
    )
    phase = PhaseSpec(
        str(_T2 / "garnet_YFeAlO.cif"), "garnet",
        mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
    )
    return run_auto_rietveld([hist], [phase], gpx_dir=str(tmp / "gpx"))


def test_final_covariance_lists_what_the_final_fit_refined(garnet_result):
    cov = garnet_result.final_covariance
    assert cov is not None
    assert any(name.endswith("::A0") for name in cov.vary_list), "格子を精密化したはず"
    assert any("::dAx:" in name or "::AUiso:" in name for name in cov.vary_list)


def test_claim_variables_name_variables_that_gsas_actually_uses(garnet_result):
    """値のキーが指す GSAS 変数名が、最終 varyList の名前と同じ形であること (取り違えの検出)。"""
    keys = garnet_result.claim_variables
    vary = set(garnet_result.final_covariance.vary_list)
    dependent = set(garnet_result.final_covariance.dependent)
    assert keys is not None
    assert set(keys["cell:garnet.a"]) & vary
    refined_uiso = [k for k in keys if k.startswith("uiso:") and set(keys[k]) & (vary | dependent)]
    assert refined_uiso, "Uiso 段を受理したのに、どの Uiso のキーも varyList に当たらない"


def test_reflection_positions_are_inside_the_measured_range(garnet_result):
    pos = garnet_result.reflection_two_theta
    assert pos, "反射位置が取れていない"
    assert list(pos) == sorted(pos)
    lo, hi = min(garnet_result.residual_two_theta), max(garnet_result.residual_two_theta)
    assert lo - 1.0 <= pos[0] and pos[-1] <= hi + 1.0
