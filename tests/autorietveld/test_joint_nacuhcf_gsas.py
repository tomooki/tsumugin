"""NaCuHCF·nD2O SXRD+ND 同時精密化のエンドツーエンド確認 (T7-8, gated)。

interop 変換 → CIF 正規化 → 2 ヒストグラム (放射光 X 線 + iMATERIA TOF 中性子) の joint 精密化が
GSAS-II で通り、両ヒストグラムに対し有限 Rwp を返すことを確認する。実データは RIETPY/example 配下
(リポジトリ外) にあるため、存在しなければ skip する。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.gsas

_DATA = Path(r"C:/Users/tomoo/Documents/programming/RIETPY/example/NaCuHCF")


def _require_data() -> None:
    if not (_DATA / "NaCuHCF.int").exists():
        pytest.skip("NaCuHCF 実データ (RIETPY/example) が無いため skip")


def test_prepare_histograms_pair_from_real_data(tmp_path):
    _require_data()
    from tsumugin.autorietveld.model import Radiation
    from tsumugin.interop import prepare_histograms

    xray, nd = prepare_histograms(
        xray_int=_DATA / "NaCuHCF.int",
        xray_diffractometer=_DATA / "SR_CeO2_SPV 2.zDiffractoMeter",
        nd_igor=_DATA / "ND/MAT059372.SE.bin02Double_0_int_c.histogramIgor",
        nd_diffractometer=_DATA / "ND/imateria_D_SE_type0m_30SC_251104_700kW.zDiffractometer",
        out_dir=tmp_path,
    )
    assert xray.radiation is Radiation.XRAY_SYNCHROTRON
    assert nd.radiation is Radiation.NEUTRON_TOF
    assert Path(xray.data_path).exists()
    assert Path(nd.data_path).exists()


def test_joint_refinement_runs_and_returns_finite_rwp(tmp_path):
    _require_data()
    import math

    from tsumugin.autorietveld.cif_normalize import normalize_cif_for_gsas
    from tsumugin.autorietveld.engine import run_auto_rietveld
    from tsumugin.autorietveld.model import PhaseSpec, RefinementStage
    from tsumugin.interop import prepare_histograms

    xray, nd = prepare_histograms(
        xray_int=_DATA / "NaCuHCF.int",
        xray_diffractometer=_DATA / "SR_CeO2_SPV 2.zDiffractoMeter",
        nd_igor=_DATA / "ND/MAT059372.SE.bin02Double_0_int_c.histogramIgor",
        nd_diffractometer=_DATA / "ND/imateria_D_SE_type0m_30SC_251104_700kW.zDiffractometer",
        out_dir=tmp_path,
    )
    clean = normalize_cif_for_gsas(
        _DATA / "saved_model5_physicalB/NaCuHCF_refined.cif",
        tmp_path / "m5.cif",
        phase_name="NaCuHCF",
    )
    phase = PhaseSpec(
        str(clean), "NaCuHCF", mixed_occupancy_groups=(("Na1", "O3"), ("Na2", "O1"))
    )
    # 短縮レシピ (背景 + セル) で joint が通ることを確認する (収束品質は解析スクリプトの担当)。
    recipe = [
        RefinementStage("bg", {"background": {"coeffs": 12}}),
        RefinementStage("cell", {"cell": True}),
    ]
    res = run_auto_rietveld([xray, nd], [phase], recipe=recipe, max_cyc=2)
    assert res.n_obs > 0
    assert math.isfinite(res.final_rwp)
    assert res.final_rwp > 0.0
