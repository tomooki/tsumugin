"""fit-then-judge P1a タスク 7: 精密化後の構造の書き出し (`run_auto_rietveld(export_cif_dir=)`)。

1A の結晶化学検査 (短すぎる結合・GII・電荷中性) は精密化**後**の構造を要る。既存ファイルは
上書きしない (P2 非破壊) — 同名があれば連番を付ける。書き出しの失敗でフィットを落とさない。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tsumugin.autorietveld.engine import _unique_path


def test_unique_path_uses_the_plain_name_when_free(tmp_path):
    assert _unique_path(tmp_path, "garnet", ".cif") == tmp_path / "garnet.cif"


def test_unique_path_never_overwrites(tmp_path):
    (tmp_path / "garnet.cif").write_text("x")
    (tmp_path / "garnet-1.cif").write_text("x")
    assert _unique_path(tmp_path, "garnet", ".cif") == tmp_path / "garnet-2.cif"


def test_unique_path_sanitizes_the_phase_name(tmp_path):
    """相名は CIF/MP 由来で / や空白を含みうる — 別ディレクトリへ書かない。"""
    p = _unique_path(tmp_path, "a/b c", ".cif")
    assert p.parent == tmp_path and "/" not in p.name and " " not in p.name


_T2 = Path("docs/benchmark/testdata/m7/cwneutron")


def _cell_a(cif_text: str) -> float:
    m = re.search(r"_cell_length_a\s+([0-9.]+)", cif_text)
    assert m, "CIF に _cell_length_a が無い"
    return float(m.group(1))


@pytest.mark.gsas
@pytest.mark.skipif(
    not all((_T2 / f).exists() for f in ("garnet.raw", "garnet_YFeAlO.cif", "inst_d1a.prm")),
    reason="M7 T2 データ未取得",
)
def test_refined_structure_is_exported_on_garnet(tmp_path, monkeypatch):
    from tsumugin.autorietveld import Geometry, HistogramSpec, PhaseSpec, Radiation
    from tsumugin.autorietveld.engine import run_auto_rietveld

    monkeypatch.setenv("TSUMUGIN_GPX_DIR", str(tmp_path / "gpx"))
    hist = HistogramSpec(
        data_path=str(_T2 / "garnet.raw"), instrument_path=str(_T2 / "inst_d1a.prm"),
        radiation=Radiation.NEUTRON_CW, geometry=Geometry.DEBYE_SCHERRER, data_format="GSAS",
    )
    phase = PhaseSpec(
        str(_T2 / "garnet_YFeAlO.cif"), "garnet",
        mixed_occupancy_groups=(("Fe1", "Al1"), ("Al2", "Fe2")),
    )
    out_dir = tmp_path / "cif"
    result = run_auto_rietveld([hist], [phase], export_cif_dir=str(out_dir))

    path = Path(result.exported_cifs["garnet"])
    assert path.parent == out_dir and path.exists()
    # 書き出したのは**精密化後**の構造 (出発 CIF の写しではない)
    a_refined = result.refined_cells["garnet"][0]
    assert abs(_cell_a(path.read_text(encoding="utf-8")) - a_refined) < 1e-3
    start_a = _cell_a((_T2 / "garnet_YFeAlO.cif").read_text(encoding="utf-8"))
    assert a_refined != start_a, "格子が動いていない (この比較が空振りする)"
