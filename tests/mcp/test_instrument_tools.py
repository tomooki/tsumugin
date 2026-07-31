"""② 装置パラメータファイルのツール (FR-502) の決定論テスト。

**このツール群が存在する理由**は §4.5 到達可能性そのもの: ``auto_rietveld`` /
``sequential_rietveld`` の ``instrument_path`` は、これまで Z-Code ``.zDiffractometer`` を
持つ利用者以外「どの ② ツールの出力から来るのか」を言えなかった。本テストはその往復
(データ → メタ情報 → instprm → 精密化ツールの引数) が実際に閉じることを縛る。
"""

from __future__ import annotations

import json

import pytest

from tsumugin.mcp.instrument_tools import (
    INSTRUMENT_TOOLS,
    create_instrument_params,
    inspect_instrument_params,
    list_instrument_presets,
    read_pattern_metadata,
)
from tsumugin.mcp.tools import MCP_TOOLS

_SAMPLE_XRDML = """<?xml version="1.0" encoding="UTF-8"?>
<xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/1.5" status="Completed">
  <xrdMeasurement measurementType="Scan" sampleMode="Reflection">
    <usedWavelength intended="K-Alpha 1">
      <kAlpha1 unit="Angstrom">1.540598</kAlpha1>
      <kAlpha2 unit="Angstrom">1.544426</kAlpha2>
      <ratioKAlpha2KAlpha1>0.5</ratioKAlpha2KAlpha1>
    </usedWavelength>
    <scan scanAxis="Gonio" status="Completed">
      <dataPoints>
        <positions axis="2Theta" unit="deg">
          <startPosition>10.000</startPosition>
          <endPosition>10.060</endPosition>
        </positions>
        <intensities unit="counts">292 275 279 274</intensities>
      </dataPoints>
    </scan>
  </xrdMeasurement>
</xrdMeasurements>
"""


def _xrdml(tmp_path):
    p = tmp_path / "frame.xrdml"
    p.write_text(_SAMPLE_XRDML, encoding="utf-8")
    return p


# =====================================================================
# 登録 / 契約
# =====================================================================


def test_tools_are_registered_in_mcp_tools():
    for name in INSTRUMENT_TOOLS:
        assert name in MCP_TOOLS, name
        assert MCP_TOOLS[name] is INSTRUMENT_TOOLS[name]


def test_tool_set_is_exactly_the_declared_five():
    assert set(INSTRUMENT_TOOLS) == {
        "list_instrument_presets",
        "read_pattern_metadata",
        "create_instrument_params",
        "inspect_instrument_params",
        "calibrate_instrument",
    }


def test_all_results_are_json_serializable(tmp_path):
    out = tmp_path / "x.instprm"
    results = [
        read_pattern_metadata(str(_xrdml(tmp_path))),
        create_instrument_params(str(out), radiation="xray_lab", wavelength=1.5405),
        inspect_instrument_params(str(out), radiation="xray_lab"),
    ]
    for r in results:
        json.dumps(r)


# =====================================================================
# read_pattern_metadata
# =====================================================================


def test_read_pattern_metadata_from_xrdml(tmp_path):
    r = read_pattern_metadata(str(_xrdml(tmp_path)))
    assert r["wavelength"] == pytest.approx(1.540598)
    assert r["kalpha2_stripped"] is True
    assert r["geometry"] == "bragg_brentano"
    assert r["radiation"] == "xray_lab"


def test_read_pattern_metadata_missing_file_degrades(tmp_path):
    r = read_pattern_metadata(str(tmp_path / "nope.xrdml"))
    assert "error" in r and r["error_type"] == "FileNotFoundError"


def test_read_pattern_metadata_unknown_format_degrades(tmp_path):
    p = tmp_path / "d.bogus"
    p.write_text("x\n", encoding="utf-8")
    r = read_pattern_metadata(str(p))
    assert "error" in r and r["error_type"] == "ValueError"


# =====================================================================
# create_instrument_params
# =====================================================================


def test_create_from_wavelength_alone(tmp_path):
    out = tmp_path / "x.instprm"
    r = create_instrument_params(str(out), radiation="xray_synchrotron", wavelength=0.79958)
    assert r["path"] == str(out)
    assert r["type"] == "PXC"
    assert r["radiation"] == "xray_synchrotron"
    assert r["wavelength"] == pytest.approx(0.79958)
    assert out.exists()


def test_create_from_data_path_fills_everything(tmp_path):
    """**一発経路**: XRDML を渡すだけで波長・幾何・Kα2 の扱いが決まる。"""
    out = tmp_path / "x.instprm"
    r = create_instrument_params(str(out), from_data_path=str(_xrdml(tmp_path)))
    assert r["radiation"] == "xray_lab"
    assert r["geometry"] == "bragg_brentano"
    assert r["wavelength"] == pytest.approx(1.540598)
    # Kα2 除去済みの宣言があるので二重線にしない (M9 CaTeO3 の最大の系統残差を避ける)
    assert r["kalpha2_stripped"] is True
    text = out.read_text(encoding="utf-8")
    assert "Lam:" in text and "Lam1:" not in text


def test_create_from_data_path_uses_doublet_when_not_stripped(tmp_path):
    p = tmp_path / "d.xrdml"
    p.write_text(_SAMPLE_XRDML.replace('intended="K-Alpha 1"', 'intended="K-Alpha"'), "utf-8")
    out = tmp_path / "x.instprm"
    create_instrument_params(str(out), from_data_path=str(p))
    text = out.read_text(encoding="utf-8")
    assert "Lam1:" in text and "Lam2:" in text


def test_create_explicit_args_win_over_data_path(tmp_path):
    out = tmp_path / "x.instprm"
    r = create_instrument_params(
        str(out), from_data_path=str(_xrdml(tmp_path)), wavelength=0.79958,
        radiation="xray_synchrotron",
    )
    assert r["wavelength"] == pytest.approx(0.79958)
    assert r["radiation"] == "xray_synchrotron"


def test_create_tof(tmp_path):
    out = tmp_path / "n.instprm"
    r = create_instrument_params(
        str(out), radiation="neutron_tof", tof={"difC": 10060.51, "Zero": -2.65, "two_theta": 90.0}
    )
    assert r["type"] == "PNT"
    assert r["wavelength"] is None


def test_create_reports_inspection_findings(tmp_path):
    """作った直後に検査結果を返す — ③ が「作れたが変」に気付けるようにする。"""
    out = tmp_path / "x.instprm"
    r = create_instrument_params(
        str(out), radiation="xray_lab", wavelength=1.5405, geometry="bragg_brentano"
    )
    codes = {f["code"] for f in r["findings"]}
    assert "kalpha1_only_bragg_brentano" in codes
    assert r["ok"] is True  # info は ok を落とさない


def test_create_without_wavelength_degrades(tmp_path):
    r = create_instrument_params(str(tmp_path / "x.instprm"), radiation="xray_lab")
    assert "error" in r and r["error_type"] == "ValueError"
    assert "波長" in r["error"]


def test_create_unknown_radiation_degrades(tmp_path):
    r = create_instrument_params(str(tmp_path / "x.instprm"), radiation="xr", wavelength=1.0)
    assert "error" in r and r["error_type"] == "ValueError"


def test_create_requires_radiation_or_preset_or_data(tmp_path):
    r = create_instrument_params(str(tmp_path / "x.instprm"), wavelength=1.5405)
    assert "error" in r
    assert "radiation" in r["error"]


def test_create_missing_data_path_degrades(tmp_path):
    r = create_instrument_params(
        str(tmp_path / "x.instprm"), from_data_path=str(tmp_path / "nope.xrdml")
    )
    assert "error" in r and r["error_type"] == "FileNotFoundError"


# =====================================================================
# inspect_instrument_params
# =====================================================================


def test_inspect_reports_findings(tmp_path):
    out = tmp_path / "n.instprm"
    create_instrument_params(str(out), radiation="neutron_cw", wavelength=1.909)
    r = inspect_instrument_params(str(out), radiation="xray_lab")
    assert r["ok"] is False
    assert "radiation_type_mismatch" in {f["code"] for f in r["findings"]}


def test_inspect_missing_file_is_a_finding_not_an_error(tmp_path):
    """存在しないパスでも ``error`` dict ではなく**検査結果**を返す (指摘の方が情報量が多い)。"""
    r = inspect_instrument_params(str(tmp_path / "nope.instprm"))
    assert "error" not in r
    assert r["ok"] is False
    assert "file_not_found" in {f["code"] for f in r["findings"]}


def test_inspect_does_not_call_garbage_valid(tmp_path):
    """② の最悪の失敗形は「garbage を正常と答える」こと。"""
    p = tmp_path / "x.instprm"
    p.write_text("これは装置ファイルではありません\n", encoding="utf-8")
    assert inspect_instrument_params(str(p))["ok"] is False


# =====================================================================
# §4.5 到達可能性: 出力が精密化ツールの入力になること
# =====================================================================


def test_created_path_feeds_auto_rietveld_histogram_spec(tmp_path):
    """``create_instrument_params`` の ``path`` が ``HistogramSpec`` の instrument_path になる。"""
    from tsumugin.autorietveld.model import Geometry, HistogramSpec, Radiation

    out = tmp_path / "x.instprm"
    r = create_instrument_params(str(out), from_data_path=str(_xrdml(tmp_path)))
    spec = HistogramSpec(
        data_path=str(_xrdml(tmp_path)),
        instrument_path=r["path"],
        radiation=Radiation(r["radiation"]),
        geometry=Geometry(r["geometry"]),
        data_format="XRDML",
    )
    # to_dict/from_dict は ② が auto_rietveld へ渡す JSON そのもの
    assert HistogramSpec.from_dict(spec.to_dict()).instrument_path == str(out)


def test_created_path_feeds_instrument_spec_of_sequential_rietveld(tmp_path):
    """``instrument`` spec (`sequential_rietveld`/`anchored_sequential`) の path へも往復する。"""
    from tsumugin.insitu.model import FrameSpec
    from tsumugin.mcp.insitu_tools import _instrument_path_resolver

    out = tmp_path / "x.instprm"
    r = create_instrument_params(str(out), radiation="xray_lab", wavelength=1.5405)
    frames = [FrameSpec(data_path="f0.xrdml"), FrameSpec(data_path="f1.xrdml")]
    assert _instrument_path_resolver({"path": r["path"]}, frames) == str(out)


@pytest.mark.gsas
def test_generated_instprm_is_accepted_by_gsasii(tmp_path):
    """生成した instprm を **GSAS-II が実際に受理する**こと (字面だけでは保証にならない)。"""
    from GSASII import GSASIIscriptable as G2sc

    out = tmp_path / "x.instprm"
    create_instrument_params(str(out), radiation="xray_lab", wavelength=1.5405)
    gpx = G2sc.G2Project(newgpx=str(tmp_path / "p.gpx"))
    hist = gpx.add_simulated_powder_histogram("t", str(out), 10.0, 60.0, Tstep=0.05)
    assert hist is not None


@pytest.mark.gsas
def test_generated_doublet_and_neutron_instprm_are_accepted_by_gsasii(tmp_path):
    from GSASII import GSASIIscriptable as G2sc

    doublet = tmp_path / "d.instprm"
    create_instrument_params(
        str(doublet), radiation="xray_lab", wavelength=1.5405, wavelength_ka2=1.5443
    )
    neutron = tmp_path / "n.instprm"
    create_instrument_params(str(neutron), radiation="neutron_cw", wavelength=1.909)
    for i, prm in enumerate((doublet, neutron)):
        gpx = G2sc.G2Project(newgpx=str(tmp_path / f"p{i}.gpx"))
        assert gpx.add_simulated_powder_histogram("t", str(prm), 10.0, 60.0, Tstep=0.05)


@pytest.mark.gsas
def test_presets_are_listed_with_reachable_labels(tmp_path):
    r = list_instrument_presets()
    labels = [p["label"] for p in r["presets"]]
    assert "CuKa lab data" in labels
    out = tmp_path / "x.instprm"
    created = create_instrument_params(str(out), preset="CuKa lab data")
    assert created["type"] == "PXC"
    assert created["geometry"] == "bragg_brentano"
    assert created["radiation"] == "xray_lab"


@pytest.mark.gsas
def test_create_with_unknown_preset_degrades(tmp_path):
    r = create_instrument_params(str(tmp_path / "x.instprm"), preset="no such preset")
    assert "error" in r and r["error_type"] == "KeyError"


# =====================================================================
# /code-review 指摘の回帰テスト
# =====================================================================


@pytest.mark.parametrize(
    "kwargs",
    [
        {"radiation": "neutron_tof", "tof": "notadict"},
        {"radiation": "neutron_tof", "tof": [["difC", 3500]]},
        {"radiation": "xray_lab", "wavelength": 1.5, "profile": [1, 2]},
    ],
)
def test_create_degrades_non_mapping_inputs(tmp_path, kwargs):
    """② は例外を送出しない。JSON 由来の非写像 (配列/文字列) でも error dict へ縮退する。"""
    r = create_instrument_params(str(tmp_path / "x.instprm"), **kwargs)
    assert "error" in r and r["error_type"] == "ValueError"


def test_read_pattern_metadata_degrades_non_string_format(tmp_path):
    p = tmp_path / "s.xrdml"
    p.write_text(_SAMPLE_XRDML, encoding="utf-8")
    r = read_pattern_metadata(str(p), 5)  # type: ignore[arg-type]
    assert "error" in r


def test_create_uses_the_ka2_ratio_declared_by_the_data(tmp_path):
    """`from_data_path` が読み取った Kα2/Kα1 比を使うこと (既定 0.5 で上書きしない)。

    `ratioKAlpha2KAlpha1` は装置固有の実測定数で、`read_pattern_metadata` がわざわざ
    取り出している。既定で潰すと黙って別の装置の値を焼き込むことになる。
    """
    src = tmp_path / "d.xrdml"
    src.write_text(
        _SAMPLE_XRDML.replace('intended="K-Alpha 1"', 'intended="K-Alpha"').replace(
            "<ratioKAlpha2KAlpha1>0.5</ratioKAlpha2KAlpha1>",
            "<ratioKAlpha2KAlpha1>0.497</ratioKAlpha2KAlpha1>",
        ),
        encoding="utf-8",
    )
    out = tmp_path / "x.instprm"
    create_instrument_params(str(out), from_data_path=str(src))
    text = out.read_text(encoding="utf-8")
    assert "I(L2)/I(L1):0.4970" in text, text


def test_explicit_ka2_ratio_still_wins_over_the_data(tmp_path):
    src = tmp_path / "d.xrdml"
    src.write_text(_SAMPLE_XRDML.replace('intended="K-Alpha 1"', 'intended="K-Alpha"'), "utf-8")
    out = tmp_path / "x.instprm"
    create_instrument_params(str(out), from_data_path=str(src), ka2_ratio=0.4)
    assert "I(L2)/I(L1):0.4000" in out.read_text(encoding="utf-8")
