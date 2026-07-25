"""``tsumugin.workbench.project`` の TDD テスト (spec ロード/相対パス絶対化/検証/プレビュー間引き)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation
from tsumugin.workbench.project import WorkbenchProject, load_project_spec, preview_pattern


def _write_xy(path: Path, n: int = 10, *, start: float = 10.0, step: float = 0.01) -> None:
    lines = [f"{start + i * step:.4f} {100.0 + 5.0 * (i % 7):.2f}" for i in range(n)]
    path.write_text("\n".join(lines), encoding="utf-8")


def _minimal_spec_dict(data_rel: str = "hist.xy") -> dict:
    return {
        "name": "unit-test project",
        "background_coeffs": 8,
        "max_cyc": 5,
        "histograms": [
            {
                "data_path": data_rel,
                "instrument_path": "hist.instprm",
                "radiation": "xray_lab",
                "geometry": "bragg_brentano",
                "data_format": "XY",
                "two_theta_limits": [10.0, 10.5],
            }
        ],
        "phases": [
            {
                "structure_path": "phase.cif",
                "phase_name": "phaseA",
                "format_hint": "CIF",
                "display": {"space_group": "P1"},
            }
        ],
    }


@pytest.fixture()
def project_dir(tmp_path: Path) -> Path:
    _write_xy(tmp_path / "hist.xy", n=20)
    (tmp_path / "hist.instprm").write_text("# instprm placeholder\n", encoding="utf-8")
    (tmp_path / "phase.cif").write_text("data_dummy\n_cell_length_a 5.0\n", encoding="utf-8")
    return tmp_path


def _write_spec(project_dir: Path, spec: dict) -> Path:
    spec_path = project_dir / "project.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return spec_path


# ---------------------------------------------------------------------------
# ロード + 相対パス絶対化
# ---------------------------------------------------------------------------


def test_load_project_spec_absolutizes_relative_paths(project_dir: Path):
    spec_path = _write_spec(project_dir, _minimal_spec_dict())

    project = load_project_spec(spec_path)

    assert isinstance(project, WorkbenchProject)
    assert project.name == "unit-test project"
    assert project.background_coeffs == 8
    assert project.max_cyc == 5

    hist = project.histograms[0]
    assert Path(hist.data_path).is_absolute()
    assert Path(hist.data_path) == (project_dir / "hist.xy").resolve()
    assert Path(hist.instrument_path) == (project_dir / "hist.instprm").resolve()

    phase = project.phases[0]
    assert Path(phase.structure_path) == (project_dir / "phase.cif").resolve()
    assert phase.phase_name == "phaseA"
    assert project.phase_display["phaseA"]["space_group"] == "P1"

    # gpx 出力パスは spec ディレクトリ基準の workbench_out/ 配下
    assert Path(project.gpx_path).parent.name == "workbench_out"
    assert Path(project.gpx_path).parent.parent == project_dir.resolve()


def test_load_project_spec_accepts_absolute_paths_unchanged(project_dir: Path):
    spec = _minimal_spec_dict(data_rel=str((project_dir / "hist.xy").resolve()))
    spec_path = _write_spec(project_dir, spec)

    project = load_project_spec(spec_path)

    assert Path(project.histograms[0].data_path) == (project_dir / "hist.xy").resolve()


# ---------------------------------------------------------------------------
# 不正 spec → ValueError
# ---------------------------------------------------------------------------


def test_load_project_spec_missing_histograms_key_raises_value_error(project_dir: Path):
    spec = _minimal_spec_dict()
    del spec["histograms"]
    spec_path = _write_spec(project_dir, spec)

    with pytest.raises(ValueError):
        load_project_spec(spec_path)


def test_load_project_spec_empty_phases_raises_value_error(project_dir: Path):
    spec = _minimal_spec_dict()
    spec["phases"] = []
    spec_path = _write_spec(project_dir, spec)

    with pytest.raises(ValueError):
        load_project_spec(spec_path)


def test_load_project_spec_unknown_radiation_raises_value_error(project_dir: Path):
    spec = _minimal_spec_dict()
    spec["histograms"][0]["radiation"] = "not-a-radiation"
    spec_path = _write_spec(project_dir, spec)

    with pytest.raises(ValueError):
        load_project_spec(spec_path)


def test_load_project_spec_malformed_json_raises_value_error(project_dir: Path):
    spec_path = project_dir / "bad.json"
    spec_path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ValueError):
        load_project_spec(spec_path)


def test_load_project_spec_missing_file_raises_value_error(project_dir: Path):
    with pytest.raises(ValueError):
        load_project_spec(project_dir / "does-not-exist.json")


def test_load_project_spec_non_object_json_raises_value_error(project_dir: Path):
    spec_path = project_dir / "list.json"
    spec_path.write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError):
        load_project_spec(spec_path)


# ---------------------------------------------------------------------------
# XRDML 自己変換 (M9 make_gsas_runner の先例踏襲)
# ---------------------------------------------------------------------------

_XRDML = """<?xml version="1.0"?>
<xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/1.0">
  <xrdMeasurement>
    <scan>
      <dataPoints>
        <positions axis="2Theta" unit="deg">
          <startPosition>10.0</startPosition>
          <endPosition>10.4</endPosition>
        </positions>
        <intensities unit="counts">10 20 30 40 50</intensities>
      </dataPoints>
    </scan>
  </xrdMeasurement>
</xrdMeasurements>
"""


def test_load_project_spec_missing_xrdml_data_file_raises_value_error_not_oserror(
    project_dir: Path,
):
    """OSError の 500 貫通防止 (セルフレビュー指摘 #1)。

    XRDML ヒストグラムの ``data_path`` がロード時に実在しないファイルを指すと、変換
    (``load_xrdml``) は ``FileNotFoundError`` (OSError のサブクラス) を送出する。修正前は
    ``load_project_spec`` の内側 try が OSError を捕捉しないため生の OSError が呼び出し側
    (`app.py` の ``post_project_open``) まで貫通し、既知の 4xx マッピングに乗らず 500 になって
    いた。修正後は「どのファイルが読めないか」を含む ValueError へ正規化される。
    """
    spec = _minimal_spec_dict(data_rel="missing.xrdml")
    spec["histograms"][0]["data_format"] = "XRDML"
    spec_path = _write_spec(project_dir, spec)

    with pytest.raises(ValueError, match="missing.xrdml") as exc_info:
        load_project_spec(spec_path)

    assert not isinstance(exc_info.value, OSError)


def test_load_project_spec_converts_xrdml_to_xye(project_dir: Path):
    (project_dir / "hist.xrdml").write_text(_XRDML, encoding="utf-8")
    spec = _minimal_spec_dict(data_rel="hist.xrdml")
    spec["histograms"][0]["data_format"] = "XRDML"
    spec["histograms"][0]["two_theta_limits"] = [9.0, 11.0]
    spec_path = _write_spec(project_dir, spec)

    project = load_project_spec(spec_path)

    hist = project.histograms[0]
    assert hist.data_format == "XYE"
    out_path = Path(hist.data_path)
    assert out_path.exists()
    assert out_path.parent.name == "workbench_out"
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 5


# ---------------------------------------------------------------------------
# preview_pattern (契約 fit.plot 形 / ≤2000 点間引き)
# ---------------------------------------------------------------------------


def test_preview_pattern_returns_contract_shape(project_dir: Path):
    hist = HistogramSpec(
        data_path=str(project_dir / "hist.xy"),
        instrument_path=str(project_dir / "hist.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )

    result = preview_pattern(hist)

    assert set(result) == {"x", "yobs", "ycalc", "ybkg", "residual", "ticks"}
    assert result["ycalc"] is None
    assert result["ybkg"] is None
    assert result["residual"] is None
    assert result["ticks"] == {}
    assert len(result["x"]) == len(result["yobs"]) == 20
    assert all(isinstance(v, float) for v in result["x"])


def test_preview_pattern_decimates_to_2000_points(tmp_path: Path):
    data_path = tmp_path / "big.xy"
    _write_xy(data_path, n=5000, step=0.001)
    hist = HistogramSpec(
        data_path=str(data_path),
        instrument_path=str(data_path),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
    )

    result = preview_pattern(hist)

    assert len(result["x"]) <= 2000
    assert len(result["x"]) == len(result["yobs"])
    # 単調 (等間隔間引きが並び順を保つ)
    assert result["x"] == sorted(result["x"])


def test_preview_pattern_respects_two_theta_limits(project_dir: Path):
    hist = HistogramSpec(
        data_path=str(project_dir / "hist.xy"),
        instrument_path=str(project_dir / "hist.instprm"),
        radiation=Radiation.XRAY_LAB,
        geometry=Geometry.BRAGG_BRENTANO,
        data_format="XY",
        two_theta_limits=(10.0, 10.05),
    )

    result = preview_pattern(hist)

    assert all(10.0 <= x <= 10.05 for x in result["x"])
    assert len(result["x"]) < 20
