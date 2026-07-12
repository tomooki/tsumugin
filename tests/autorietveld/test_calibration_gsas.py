"""calibrate_instrument_from_standard の実データ検証 (Issue #61, gated)。

NIST SRM 674b CeO2 (放射光, docs/benchmark/testdata/issue38) で格子固定較正を実行し、
公称波長固定でゼロ点・プロファイルが物理的に得られることを確認する。
GSAS-II 必須 (@pytest.mark.gsas)。データ未取得時は自動 skip。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tsumugin.autorietveld.resolution import (
    calibrate_instrument_from_standard,
    profile_fwhm_min,
)

_DATA = Path("docs/benchmark/testdata/issue38")
_LAM = 0.79958  # この標準データの公称波長

pytestmark = pytest.mark.gsas


def _present() -> bool:
    return (_DATA / "ceo2.xye").exists()


@pytest.mark.skipif(not _present(), reason="CeO2 標準データ未取得")
def test_calibrate_fixed_wavelength_physical():
    res = calibrate_instrument_from_standard(
        str(_DATA / "ceo2.xye"), wavelength_init=_LAM, standard="CeO2",
        two_theta_limits=(8.0, 82.0),
    )
    # 既定は波長固定 → 入力値のまま (ppm_shift=0)
    assert res.wavelength == _LAM
    assert res.ppm_shift == 0.0
    # 格子は認証値に固定
    assert res.reference_cell[0] == pytest.approx(5.41165)
    # ゼロ点は小さい (公称波長と認証格子が整合 → 位置補正は微小)
    assert abs(res.zero) < 0.1
    # 装置プロファイルは全域 FWHM 正 (転写可能)
    assert profile_fwhm_min({**res.profile}, 8.0, 82.0) > 0.0
    # 収束している (実測 ~9%)
    assert res.source_rwp < 20.0


@pytest.mark.skipif(not _present(), reason="CeO2 標準データ未取得")
def test_calibrate_refine_wavelength_cross_check():
    # refine_wavelength=True でも収束し、波長は公称近傍 (縮退のため厳密一致は期待しない)
    res = calibrate_instrument_from_standard(
        str(_DATA / "ceo2.xye"), wavelength_init=_LAM, standard="CeO2",
        two_theta_limits=(8.0, 82.0), refine_wavelength=True,
    )
    assert res.source_rwp < 20.0
    assert abs(res.ppm_shift) < 5000.0  # 縮退で振れ得るが桁は保つ
