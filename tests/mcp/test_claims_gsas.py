"""fit-then-judge P1-1A: 実 GSAS を ② の JSON 経路で回し、出版状態が実データで機能すること。

データは T2 garnet (CW 中性子・単相・Fe/Al 混合占有。hold-out ではない)。この実データで
2 件の欠陥が見つかった (どちらも合成データのテストでは出なかった):

- 相集合の完全性の証人が、強い反射 (50.77°) の**裾**を欠落相と取り違えて fail していた
  (単純な窓の和は坂と山を区別しない → 平均 0 の山形の窓に変えた)
- 結合原子価和が混合占有サイトで AttributeError になり、常に unevaluated だった
  (pymatgen の ``calculate_bv_sum_unordered`` → 占有率で重み付けた自前の和に変えた)
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
def garnet(tmp_path_factory):
    from tsumugin.mcp.rietveld_tools import auto_rietveld

    return auto_rietveld(
        [{"data_path": str(_T2 / "garnet.raw"), "instrument_path": str(_T2 / "inst_d1a.prm"),
          "radiation": "neutron_cw", "geometry": "debye_scherrer", "data_format": "GSAS"}],
        [{"structure_path": str(_T2 / "garnet_YFeAlO.cif"), "phase_name": "garnet",
          "mixed_occupancy_groups": [["Fe1", "Al1"], ["Al2", "Fe2"]]}],
        gpx_dir=str(tmp_path_factory.mktemp("claims_e2e")),
    )


def test_a_good_single_phase_fit_publishes_its_refined_structure(garnet):
    assert "error" not in garnet, garnet.get("error")
    pub = garnet["publishable_values"]
    assert "cell:garnet.a" in pub
    assert any(k.startswith("coord:") and garnet["claims"][k]["provenance"] == ["refined"]
               for k in pub), "精密化した座標が 1 つも出版されない"
    blocking = [r["id"] for r in garnet["judgment_requests"] if r["blocking"]]
    assert blocking == [], blocking


def test_the_phase_set_witness_is_not_fooled_by_peak_tails(garnet):
    check = garnet["claims"]["cell:garnet.a"]["checks"]["phase_set_completeness"]
    assert check == "pass"


def test_crystal_chemistry_is_evaluated_on_mixed_occupancy(garnet):
    assert garnet["claims"]["coord:garnet.O1.x"]["checks"]["crystal_chemistry"] == "pass"


def test_unreleased_values_are_not_published(garnet):
    """解放しなかったプロファイル項は入力値 — 出版しない。"""
    held = [k for k, c in garnet["claims"].items() if "input" in c["provenance"]]
    assert held and not set(held) & set(garnet["publishable_values"])


def test_the_sidecar_matches_the_saved_gpx(garnet):
    from tsumugin.claims.sidecar import read_claims_sidecar

    side = read_claims_sidecar(garnet["gpx_path"])
    assert side is not None, garnet["claims_sidecar_reason"]
    assert side["claims"] == garnet["claims"]
