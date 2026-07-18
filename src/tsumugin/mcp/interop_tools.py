"""薄い MCP ツール — 外部ソフト形式 → GSAS-II 変換 (interop, Issue #108)。

`tsumugin.interop` (XND) は当初「変換済みパスを auto_rietveld に渡せば足りる」として意図的に
② 非露出だったが、③ が生の RIETAN `.int` / Z-Code Igor TOF / `.zDiffractometer` を受けたとき変換
手順の案内が無く手作業を強いていた。2026-07-17 のユーザー判断で ② 露出に方針転換。

- ``convert_pattern``: RIETAN-FP `.int` / Z-Code Igor TOF `.histogramIgor` → GSAS 向け `.xye` /
  TOF FXYE。変換後パスは ``auto_rietveld``/``sequential_rietveld`` の ``histograms``/``frames`` の
  ``data_path`` へそのまま渡せる (§4.5 往復)。
- ``write_instrument_params``: Z-Code `.zDiffractometer` → GSAS `.instprm` (X 線 PXC / TOF PNT)。
  出力 instprm パスは ``instrument`` spec の ``path`` へ渡せる (sequential_rietveld/anchored_sequential/
  repair_frames と往復)。

**SDK 非依存**: 素の型 dict のみ。numpy-only (GSAS 非依存)。ファイル不在・不正形式は error dict。

信頼性: 🔵 Issue #108 / architecture.md §4.5 カバレッジ規則④。
"""

from __future__ import annotations

from pathlib import Path

__all__ = ["INTEROP_TOOLS", "convert_pattern", "write_instrument_params"]

#: 拡張子 → 形式キー (input_format 省略時の推定)。
_EXT_FORMAT = {".int": "rietan_int", ".histogramigor": "igor_tof"}


def convert_pattern(
    input_path: str,
    out_path: str,
    *,
    input_format: str | None = None,
    title: str = "",
    reason: str = "",
) -> dict:
    """外部形式の粉末パターンを GSAS 向け形式へ変換する (計器・前処理)。

    :param input_path: 入力ファイル (RIETAN `.int` / Z-Code Igor TOF `.histogramIgor`)
    :param out_path: 出力パス (`.xye` / TOF FXYE)
    :param input_format: ``"rietan_int"`` / ``"igor_tof"``。省略時は拡張子から推定
        (`.int`→rietan_int / `.histogramIgor`→igor_tof)
    :param title: igor_tof 変換時の FXYE タイトル (任意)
    :returns: ``{path, format, n_points}``。変換後パスは auto_rietveld/sequential_rietveld の
        ``data_path`` へ渡せる。不正形式・ファイル不在は ``{"error", "error_type"}``
    """
    from ..interop.rietan import convert_rietan_int, parse_rietan_int
    from ..interop.zrietveld import convert_igor_tof, parse_igor_tof

    fmt = input_format or _EXT_FORMAT.get(Path(input_path).suffix.lower())
    if fmt not in ("rietan_int", "igor_tof"):
        return {
            "error": (
                f"input_format を判別できません (input_format={input_format!r}, "
                f"拡張子={Path(input_path).suffix!r})。'rietan_int' か 'igor_tof' を明示してください"
            ),
            "error_type": "ValueError",
        }
    try:
        if fmt == "rietan_int":
            out = convert_rietan_int(input_path, out_path)
            n = len(parse_rietan_int(Path(input_path).read_text(encoding="utf-8"))[0])
        else:
            out = convert_igor_tof(input_path, out_path, title=title)
            n = len(parse_igor_tof(Path(input_path).read_text(encoding="utf-8"))[0])
    except (OSError, ValueError, KeyError, IndexError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    return {"path": str(out), "format": fmt, "n_points": n, "reason": reason}


def write_instrument_params(
    zdiffractometer_path: str,
    out_path: str,
    *,
    wavelength: float | None = None,
    polarization: float | None = None,
    reason: str = "",
) -> dict:
    """Z-Code `.zDiffractometer` から GSAS `.instprm` を書き出す (計器・前処理)。

    :param zdiffractometer_path: Z-Code 回折計設定ファイル
    :param out_path: 出力 `.instprm` パス
    :param wavelength: X 線波長 [Å] の上書き (別較正ファイルの波長を無視したいとき。TOF では無視)
    :param polarization: X 線偏光係数の上書き (既定は放射光 0.95 / それ以外 0.7)
    :returns: ``{path, is_tof}``。出力 instprm パスは ``instrument`` spec の ``path`` へ渡せる
        (sequential_rietveld/anchored_sequential/repair_frames と往復)。放射源判別不能・必須
        パラメータ欠落・ファイル不在は ``{"error", "error_type"}``
    """
    from ..interop.instrument import write_gsas_instprm
    from ..interop.zrietveld import parse_zdiffractometer

    try:
        text = Path(zdiffractometer_path).read_text(encoding="utf-8")
        zd = parse_zdiffractometer(text)
        out = write_gsas_instprm(
            zd, out_path, wavelength=wavelength, polarization=polarization
        )
    except (OSError, ValueError, KeyError) as exc:
        return {"error": str(exc), "error_type": type(exc).__name__}
    return {"path": str(out), "is_tof": bool(zd.is_tof), "reason": reason}


#: MCP_TOOLS へマージする interop 変換ツール (Issue #108)。
INTEROP_TOOLS: dict[str, object] = {
    "convert_pattern": convert_pattern,
    "write_instrument_params": write_instrument_params,
}
