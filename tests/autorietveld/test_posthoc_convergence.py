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


def test_posthoc_refinement_is_kept_beside_the_source_and_indexed(tmp_path, monkeypatch):
    """事後検査の精密化も成果物として残す (規定 2026-08-20「全解析で保存する」)。元の gpx の隣に上書きせず書く。"""
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import posthoc_shift_esd, run_auto_rietveld
    from tsumugin.gpxstore import read_manifest

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    xye, instprm, start = _zno(tmp_path)
    hist = HistogramSpec(data_path=str(xye), instrument_path=str(instprm), radiation=Radiation.XRAY_LAB,
                         geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
    result = run_auto_rietveld([hist], [PhaseSpec(str(start), "ZnO")])
    src = Path(result.gpx_path)

    posthoc_shift_esd(result.gpx_path, cycles=1)
    posthoc_shift_esd(result.gpx_path, cycles=1)

    kept = sorted(src.parent.glob(f"{src.stem}.posthoc*.gpx"))
    assert len(kept) == 2, kept  # 2 回目は連番 (上書きしない)
    rows = [r for r in read_manifest(str(src.parent)) if r.get("role") == "posthoc"]
    assert len(rows) == 2 and all(r["source_gpx"] == str(src) for r in rows)  # extra は行に平らに入る
    assert all(r["phases"] == ["ZnO"] and r["rwp"] is not None for r in rows)  # どの fit の写しかを 1 行で
