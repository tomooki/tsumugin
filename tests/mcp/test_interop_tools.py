"""② convert_pattern / write_instrument_params (interop 変換) の MCP 露出テスト (Issue #108)。

interop (XND) は当初意図的 ② 非露出だったが、③ が生の外部形式を受けたとき変換手順の案内が無く
手作業を強いていたため 2026-07-17 に ② 露出へ方針転換。numpy-only なので GSAS 非依存で決定論テスト。
"""

from __future__ import annotations

import json

from tsumugin.mcp.interop_tools import (
    INTEROP_TOOLS,
    convert_pattern,
    write_instrument_params,
)

_SAMPLE_INT = "GENERAL\n5\n0.800000 8838.0\n0.806000 8841.0\n0.812000 8981.0\n0.818000 9108.0\n0.824000 9013.0\n"

_SAMPLE_XRAY_DIFF = """[File format version] 1
[Beam type] X-Ray
[Measurement method] Synchrotron Radiation

[Diffracto meter parameter]
\t[Wave length]
\t\t[Value] 0.5
\t[End]
\t[Z]
\t\t[Value] 0.005896
\t[End]
[End]
"""


def test_registry():
    assert set(INTEROP_TOOLS) == {"convert_pattern", "write_instrument_params"}


def test_convert_pattern_rietan_int_by_extension(tmp_path):
    src = tmp_path / "d.int"
    src.write_text(_SAMPLE_INT, encoding="utf-8")
    out = convert_pattern(str(src), str(tmp_path / "out.xye"))
    assert "error" not in out
    assert out["format"] == "rietan_int"
    assert out["n_points"] == 5
    assert (tmp_path / "out.xye").exists()
    json.dumps(out, allow_nan=False)


def test_convert_pattern_explicit_format(tmp_path):
    src = tmp_path / "pattern.dat"  # 拡張子で推定できない → input_format 明示
    src.write_text(_SAMPLE_INT, encoding="utf-8")
    out = convert_pattern(str(src), str(tmp_path / "o.xye"), input_format="rietan_int")
    assert out["format"] == "rietan_int"
    assert out["n_points"] == 5


def test_convert_pattern_unknown_format_returns_error_dict(tmp_path):
    src = tmp_path / "mystery.dat"
    src.write_text("whatever", encoding="utf-8")
    out = convert_pattern(str(src), str(tmp_path / "o.xye"))
    assert out["error_type"] == "ValueError"
    assert "input_format" in out["error"]


def test_convert_pattern_missing_file_returns_error_dict(tmp_path):
    out = convert_pattern(str(tmp_path / "nope.int"), str(tmp_path / "o.xye"))
    assert "error" in out
    assert out["error_type"] in ("FileNotFoundError", "OSError")


def test_write_instrument_params_xray(tmp_path):
    src = tmp_path / "sr.zDiffractometer"
    src.write_text(_SAMPLE_XRAY_DIFF, encoding="utf-8")
    out = write_instrument_params(str(src), str(tmp_path / "sr.instprm"))
    assert "error" not in out
    assert out["is_tof"] is False
    text = (tmp_path / "sr.instprm").read_text(encoding="utf-8")
    assert "PXC" in text  # X 線 instprm


def test_write_instrument_params_wavelength_override(tmp_path):
    src = tmp_path / "sr.zDiffractometer"
    src.write_text(_SAMPLE_XRAY_DIFF, encoding="utf-8")
    out = write_instrument_params(
        str(src), str(tmp_path / "sr.instprm"), wavelength=0.79958
    )
    assert "error" not in out
    text = (tmp_path / "sr.instprm").read_text(encoding="utf-8")
    assert "0.79958" in text


def test_write_instrument_params_missing_file_returns_error_dict(tmp_path):
    out = write_instrument_params(
        str(tmp_path / "nope.zDiffractometer"), str(tmp_path / "o.instprm")
    )
    assert "error" in out
    assert out["error_type"] in ("FileNotFoundError", "OSError")


def test_interop_tools_registered_in_mcp_tools():
    from tsumugin.mcp.tools import MCP_TOOLS

    assert "convert_pattern" in MCP_TOOLS
    assert "write_instrument_params" in MCP_TOOLS
