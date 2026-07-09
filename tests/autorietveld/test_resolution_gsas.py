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
    extract_instrument_profile_from_standard,
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


def _total_fwhm_min(vals, tt_lo=5.0, tt_hi=110.0, n=64):
    """GSAS getFWHM CW 準拠の総 FWHM をレンジで評価し最小値を返す (負なら転写不能)。"""
    import numpy as np

    U, V, W, X, Y = (vals.get(k, 0.0) for k in ("U", "V", "W", "X", "Y"))
    tt = np.linspace(tt_lo, tt_hi, n)
    th = np.radians(tt / 2)
    t, c = np.tan(th), np.cos(th)
    sig = np.sqrt(np.maximum(0.001, U * t * t + V * t + W))
    g = X / c + Y * t
    a = 2.35482 * sig
    poly = (a**5 + 2.69269 * a**4 * g + 2.42843 * a**3 * g**2
            + 4.47163 * a**2 * g**3 + 0.07842 * a * g**4 + g**5)
    return float(np.min(poly))


@pytest.mark.skipif(not _present(), reason="Issue #38 CeO2 データ未取得")
def test_extract_ceo2_constrained_is_transferable():
    # 非負拘束 (既定) で抽出 → X,Y≥0・全域 FWHM 正 (転写可能)・Rwp<12% (~9%)。
    ip = extract_instrument_profile(_standard(), _ceo2(), refine_sh_l=False)
    assert ip.source_rwp < 12.0, f"Rwp={ip.source_rwp}"
    for k in ("U", "V", "W", "X", "Y"):
        assert k in ip.values
    # 非負拘束が効いている
    assert ip.values["X"] >= -1e-6 and ip.values["Y"] >= -1e-6, ip.values
    # Lorentzian は X (1/cosθ) が担う (有意)
    assert ip.values["X"] > 0.1, ip.values
    # 総 FWHM がレンジ全域で正 → 別試料へ転写可能
    assert _total_fwhm_min(ip.values) > 0.0, "総 FWHM が負 (転写不能)"


@pytest.mark.skipif(not _present(), reason="Issue #38 CeO2 データ未取得")
def test_extract_ceo2_unconstrained_can_be_nonphysical():
    # 無拘束 (constrain_nonneg=False) は相関非物理解 (Y<0・FWHM 負) になりうる (対比)。
    ip = extract_instrument_profile(_standard(), _ceo2(), refine_sh_l=False, constrain_nonneg=False)
    assert ip.source_rwp < 12.0
    # 無拘束では総 FWHM がレンジで負に触れる (転写不能) — 拘束の必要性を示す
    assert _total_fwhm_min(ip.values) < 0.0, f"無拘束でも正: {ip.values}"


@pytest.mark.skipif(not _present(), reason="Issue #38 CeO2 データ未取得")
def test_reproduce_from_standard_pipeline(tmp_path):
    # 生データ 1 ファイルから一括再現 (ceo2.xye を load_xy が 2 列として読む)。~8.9% を再現。
    ip = extract_instrument_profile_from_standard(
        str(_DATA / "ceo2.xye"), wavelength=0.79958, standard="CeO2",
        work_dir=str(tmp_path), two_theta_limits=(8.0, 82.0), zero=0.0059, refine_sh_l=False,
    )
    assert ip.source_rwp < 12.0, f"Rwp={ip.source_rwp}"
    assert ip.wavelength == 0.79958
    assert {"U", "V", "W", "X", "Y"}.issubset(set(ip.values))


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
