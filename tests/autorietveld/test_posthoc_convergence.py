"""P0 §1.2: 全アームの最終 gpx に同じ事後の収束検査 (追加サイクルでの max |shift|/esd) を掛ける。

合成 `S-dev` (wurtzite ZnO) だけを使う — (準) hold-out に触れない。
"""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

pytestmark = pytest.mark.gsas


def _zno(tmp_path):
    src = Path(__file__).resolve().parent / "test_engine_polar_origin.py"
    spec = importlib.util.spec_from_file_location("_zno_synthetic_posthoc", src)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod._synthetic_zno(tmp_path)


def test_posthoc_check_reports_a_small_shift_on_a_converged_fit_and_leaves_the_file(tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import posthoc_shift_esd, run_auto_rietveld

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _zno(tmp_path)
    hist = HistogramSpec(data_path=str(xye), instrument_path=str(instprm), radiation=Radiation.XRAY_LAB,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    result = run_auto_rietveld([hist], [PhaseSpec(str(start), "ZnO")])
    before = hashlib.sha256(Path(result.gpx_path).read_bytes()).hexdigest()

    shift = posthoc_shift_esd(result.gpx_path, cycles=1)

    assert shift is not None and 0.0 <= shift < 1.0
    assert hashlib.sha256(Path(result.gpx_path).read_bytes()).hexdigest() == before  # 写しで行う
