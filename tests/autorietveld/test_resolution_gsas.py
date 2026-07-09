"""extract_instrument_profile + 装置プロファイル固定の実データ検証 (Issue #38, gated)。

NIST SRM 674b CeO2 (放射光 λ=0.79958) で装置分解能を抽出し、固定モードで seed 値が保持されることを確認。
GSAS-II 必須 (@pytest.mark.gsas)。データ未取得時は自動 skip。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld import (
    Geometry,
    HistogramSpec,
    PhaseSpec,
    Radiation,
    extract_instrument_profile,
    run_auto_rietveld,
)
from tsumugin.autorietveld.resolution import build_resolution_recipe

_DATA = Path("docs/benchmark/testdata/issue38")

pytestmark = pytest.mark.gsas


def _present() -> bool:
    return (_DATA / "ceo2.xye").exists() and (_DATA / "ceo2.cif").exists()


def _standard():
    return HistogramSpec(
        data_path=str(_DATA / "ceo2.xye"),
        instrument_path=str(_DATA / "xray.instprm"),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=(8.0, 82.0),
    )


def _ceo2():
    return PhaseSpec(structure_path=str(_DATA / "ceo2.cif"), phase_name="CeO2", format_hint="CIF")


@pytest.mark.skipif(not _present(), reason="Issue #38 CeO2 データ未取得")
def test_extract_ceo2_resolution_reaches_low_rwp():
    ip = extract_instrument_profile(_standard(), _ceo2(), refine_sh_l=False)
    # シャープ放射光ピークで Rwp < 12% (直接精密化で ~8.9% 確認)
    assert ip.source_rwp < 12.0, f"Rwp={ip.source_rwp}"
    # 装置プロファイル一式が抽出される
    for k in ("U", "V", "W", "X", "Y"):
        assert k in ip.values
    # Lorentzian が有意 (シャープピークは L 支配)
    assert abs(ip.values["Y"]) > 0.5


@pytest.mark.skipif(not _present(), reason="Issue #38 CeO2 データ未取得")
def test_fixed_instrument_profile_is_preserved():
    # 抽出した分解能を instrument_profile に渡すと、profile 解放レシピでも値が動かない (固定)
    ip = extract_instrument_profile(_standard(), _ceo2(), refine_sh_l=False)
    fixed = HistogramSpec(
        data_path=str(_DATA / "ceo2.xye"),
        instrument_path=str(_DATA / "xray.instprm"),
        radiation=Radiation.XRAY_SYNCHROTRON,
        geometry=Geometry.DEBYE_SCHERRER,
        data_format="XYE",
        two_theta_limits=(8.0, 82.0),
        instrument_profile=ip,
    )
    r = run_auto_rietveld([fixed], [_ceo2()], recipe=build_resolution_recipe(refine_sh_l=False))
    for k in ("U", "V", "W", "X", "Y"):
        assert abs(r.hist_profile[0][k] - ip.values[k]) < 1e-6, f"{k} moved"
