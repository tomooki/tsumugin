"""`tsumugin.instprm` (装置パラメータファイルの生成・解析・検査) の決定論テスト。

FR-502「装置パラメータ — .instprm 第一級管理、標準試料からの生成ウィザード」の ① 層。
本モジュールは stdlib-only なので **GSAS-II 非導入の CI ティア (`-m "not gsas"`) で完全に回る**
(プリセット読み出しだけは GSAS-II 同梱 `defaultIparms` に依存するため gated)。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.errors import GSASUnavailableError
from tsumugin.instprm import (
    InstprmFinding,
    InstprmReport,
    build_instprm_text,
    inspect_instprm,
    instprm_from_profile,
    list_instrument_presets,
    parse_instprm,
    preset_instprm_text,
    write_instprm,
)

# =====================================================================
# parse_instprm
# =====================================================================


def test_parse_instprm_one_key_per_line():
    text = "#GSAS-II instrument parameter file\nType:PXC\nLam:1.540500\nSH/L:0.002\n"
    d = parse_instprm(text)
    assert d == {"Type": "PXC", "Lam": "1.540500", "SH/L": "0.002"}


def test_parse_instprm_semicolon_delimited_block():
    """GSAS-II 同梱 `defaultIparms` の書式 (1 行に `;` 区切りで複数 key:value)。"""
    text = (
        "#GSAS-II instrument parameter file for lab CuKa data\n"
        "Type:PXC;Bank:1\n"
        "Lam1:1.5405;Lam2:1.5443;Zero:0.0;Polariz.:0.7;Azimuth:0.0;I(L2)/I(L1):0.5\n"
        "U:2.0;V:-2.0;W:5.0;X:0.0;Y:0.0;Z:0.0;SH/L:0.002\n"
    )
    d = parse_instprm(text)
    assert d["Type"] == "PXC"
    assert d["Lam1"] == "1.5405"
    assert d["Lam2"] == "1.5443"
    # キー自身が '/' を含む 2 例 (最初の ':' でのみ分割すること)
    assert d["I(L2)/I(L1)"] == "0.5"
    assert d["SH/L"] == "0.002"


def test_parse_instprm_ignores_comments_and_blank_lines():
    assert parse_instprm("# c\n\n  \nType:PNC\n") == {"Type": "PNC"}


def test_parse_instprm_strips_whitespace():
    assert parse_instprm("  Type : PXC  \n")["Type"] == "PXC"


# =====================================================================
# build_instprm_text — 放射源ごとの Type と必須キー
# =====================================================================


def test_build_pxc_monochromatic_from_wavelength_alone():
    """**初心者の最小入力**: 波長だけで GSAS が読める instprm になること。"""
    d = parse_instprm(build_instprm_text(radiation="xray_synchrotron", wavelength=0.79958))
    assert d["Type"] == "PXC"
    assert float(d["Lam"]) == pytest.approx(0.79958)
    assert float(d["Polariz."]) == pytest.approx(0.95)  # 放射光は高偏光
    assert "Lam1" not in d and "Lam2" not in d
    for key in ("Bank", "Zero", "Azimuth", "U", "V", "W", "X", "Y", "Z", "SH/L"):
        assert key in d, key


def test_build_pxc_lab_defaults_to_low_polarization():
    d = parse_instprm(build_instprm_text(radiation="xray_lab", wavelength=1.5405))
    assert float(d["Polariz."]) == pytest.approx(0.7)


def test_build_pxc_kalpha_doublet():
    d = parse_instprm(
        build_instprm_text(
            radiation="xray_lab", wavelength=1.5405, wavelength_ka2=1.5443, ka2_ratio=0.5
        )
    )
    assert float(d["Lam1"]) == pytest.approx(1.5405)
    assert float(d["Lam2"]) == pytest.approx(1.5443)
    assert float(d["I(L2)/I(L1)"]) == pytest.approx(0.5)
    assert "Lam" not in d  # 二重線では Lam1/Lam2 を使い Lam は書かない


def test_build_pnc_cw_neutron():
    """CW 中性子 (PNC)。既存の 2 writer が対応していなかった放射源。"""
    d = parse_instprm(build_instprm_text(radiation="neutron_cw", wavelength=1.909))
    assert d["Type"] == "PNC"
    assert float(d["Lam"]) == pytest.approx(1.909)
    assert float(d["Polariz."]) == pytest.approx(0.0)  # 中性子に X 線偏光は無い
    # CW 中性子は X 線より桁違いに広いピーク → 既定 U,V,W は X 線既定を使い回さないこと
    assert float(d["U"]) > 10.0


def test_build_pnt_tof_neutron():
    d = parse_instprm(
        build_instprm_text(
            radiation="neutron_tof",
            tof={"difC": 10060.510395, "difA": -1.125499, "Zero": -2.653194, "two_theta": 90.0},
        )
    )
    assert d["Type"] == "PNT"
    assert float(d["difC"]) == pytest.approx(10060.510395)
    assert float(d["difA"]) == pytest.approx(-1.125499)
    assert float(d["Zero"]) == pytest.approx(-2.653194)
    assert float(d["difB"]) == pytest.approx(0.0)
    # fltPath は difC = 2·252.816·L·sinθ の逆算
    expected_l = 10060.510395 / (2.0 * 252.816 * math.sin(math.radians(45.0)))
    assert float(d["fltPath"]) == pytest.approx(expected_l, rel=1e-4)
    for key in ("alpha", "beta-0", "beta-1", "beta-q", "sig-0", "sig-1", "sig-2", "sig-q"):
        assert key in d, key


def test_build_pnt_accepts_explicit_flt_path():
    d = parse_instprm(
        build_instprm_text(
            radiation="neutron_tof",
            tof={"difC": 3500.0, "fltPath": 10.0, "two_theta": 90.0},
        )
    )
    assert float(d["fltPath"]) == pytest.approx(10.0)


def test_build_profile_override():
    d = parse_instprm(
        build_instprm_text(
            radiation="xray_synchrotron",
            wavelength=0.7,
            profile={"U": 1.163, "V": -0.126, "W": 0.063, "X": 0.5},
        )
    )
    assert float(d["U"]) == pytest.approx(1.163)
    assert float(d["X"]) == pytest.approx(0.5)
    assert float(d["Y"]) == pytest.approx(0.0)  # 未指定は既定のまま


# --- 入力エラーは早期に、直せる言葉で ---


def test_build_xray_without_wavelength_raises():
    with pytest.raises(ValueError, match="波長"):
        build_instprm_text(radiation="xray_lab")


def test_build_neutron_cw_without_wavelength_raises():
    with pytest.raises(ValueError, match="波長"):
        build_instprm_text(radiation="neutron_cw")


def test_build_tof_without_difc_raises():
    with pytest.raises(ValueError, match="difC"):
        build_instprm_text(radiation="neutron_tof", tof={"two_theta": 90.0})


def test_build_unknown_radiation_raises():
    with pytest.raises(ValueError, match="radiation"):
        build_instprm_text(radiation="gamma_ray", wavelength=1.0)


def test_build_accepts_radiation_enum():
    """① は enum を、② は JSON 文字列を渡す — どちらも受ける (leaf モジュールの両対応)。"""
    from tsumugin.autorietveld.model import Radiation

    a = build_instprm_text(radiation=Radiation.XRAY_LAB, wavelength=1.5405)
    b = build_instprm_text(radiation="xray_lab", wavelength=1.5405)
    assert a == b


def test_build_is_deterministic():
    """NFR-102: 同じ入力はビット同一。"""
    kw = {"radiation": "xray_lab", "wavelength": 1.5405, "wavelength_ka2": 1.5443}
    assert build_instprm_text(**kw) == build_instprm_text(**kw)


# =====================================================================
# write_instprm
# =====================================================================


def test_write_instprm_roundtrip(tmp_path):
    out = write_instprm(tmp_path / "x.instprm", radiation="xray_lab", wavelength=1.5405)
    assert out.exists()
    d = parse_instprm(out.read_text(encoding="utf-8"))
    assert d["Type"] == "PXC"
    assert float(d["Lam"]) == pytest.approx(1.5405)


def test_write_instprm_creates_parent_dirs(tmp_path):
    out = write_instprm(
        tmp_path / "deep" / "nested" / "x.instprm", radiation="xray_lab", wavelength=1.5405
    )
    assert out.exists()


# =====================================================================
# instprm_from_profile — 標準試料較正の結果を書き戻す (これまで欠けていた閉路)
# =====================================================================


def test_instprm_from_profile_writes_refined_values():
    """`extract_instrument_profile*` / `calibrate_instrument_from_standard` の出力 → instprm。"""
    from tsumugin.autorietveld.model import InstrumentProfile

    prof = InstrumentProfile(
        values={"U": 0.0, "V": 1.81, "W": 0.96, "X": 0.41, "Y": 0.0, "Zero": 0.0059},
        source_rwp=9.06,
        wavelength=0.79958,
    )
    d = parse_instprm(instprm_from_profile(prof, radiation="xray_synchrotron"))
    assert float(d["V"]) == pytest.approx(1.81)
    assert float(d["W"]) == pytest.approx(0.96)
    assert float(d["X"]) == pytest.approx(0.41)
    assert float(d["Zero"]) == pytest.approx(0.0059)
    assert float(d["Lam"]) == pytest.approx(0.79958)  # profile.wavelength を採る


def test_instprm_from_profile_accepts_calibration_result():
    from tsumugin.autorietveld.model import CalibrationResult

    cal = CalibrationResult(
        wavelength=0.800113,
        wavelength_init=0.79958,
        zero=-0.0031,
        profile={"U": 0.0, "V": 1.8, "W": 0.9, "X": 0.4, "Y": 0.0},
        reference_cell=(5.41165, 5.41165, 5.41165, 90.0, 90.0, 90.0),
        source_rwp=9.06,
    )
    d = parse_instprm(instprm_from_profile(cal, radiation="xray_synchrotron"))
    assert float(d["Lam"]) == pytest.approx(0.800113)  # 較正後の実効波長
    assert float(d["Zero"]) == pytest.approx(-0.0031)
    assert float(d["V"]) == pytest.approx(1.8)


def test_instprm_from_profile_explicit_wavelength_wins():
    from tsumugin.autorietveld.model import InstrumentProfile

    prof = InstrumentProfile(values={"U": 1.0}, wavelength=0.7)
    d = parse_instprm(
        instprm_from_profile(prof, radiation="xray_synchrotron", wavelength=0.79958)
    )
    assert float(d["Lam"]) == pytest.approx(0.79958)


def test_instprm_from_profile_without_wavelength_raises():
    from tsumugin.autorietveld.model import InstrumentProfile

    with pytest.raises(ValueError, match="波長"):
        instprm_from_profile(
            InstrumentProfile(values={"U": 1.0}), radiation="xray_synchrotron"
        )


# =====================================================================
# inspect_instprm — 「持っているファイルが正しいか」を精密化前に言う
# =====================================================================


def _write(tmp_path, name: str, text: str):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def _codes(report: InstprmReport) -> set[str]:
    return {f.code for f in report.findings}


def test_inspect_clean_file_has_no_error(tmp_path):
    p = _write(
        tmp_path,
        "x.instprm",
        build_instprm_text(radiation="xray_synchrotron", wavelength=0.79958),
    )
    rep = inspect_instprm(p, radiation="xray_synchrotron", geometry="debye_scherrer")
    assert isinstance(rep, InstprmReport)
    assert rep.ok is True
    assert not [f for f in rep.findings if f.severity == "error"]


def test_inspect_detects_radiation_type_mismatch(tmp_path):
    """宣言 `radiation` と instprm の `Type:` の食い違い (取り違えは実際に起きる)。"""
    p = _write(tmp_path, "n.instprm", build_instprm_text(radiation="neutron_cw", wavelength=1.909))
    rep = inspect_instprm(p, radiation="xray_lab")
    assert "radiation_type_mismatch" in _codes(rep)
    assert rep.ok is False
    # 何と食い違ったのかがメッセージから読めること (③ は文字列しか読めない)
    msg = next(f.message for f in rep.findings if f.code == "radiation_type_mismatch")
    assert "PNC" in msg and "PXC" in msg


def test_inspect_flags_kalpha1_only_with_bragg_brentano(tmp_path):
    """CaTeO3 無言失敗クラス: Kα1 単色 instprm を反射光学系に使う組み合わせ。

    `engine._apply_sample_geometry` が Sample `Type` を宣言側へ矯正するので精密化自体は
    走るが、Kα2 除去済みでないデータに単色 instprm を当てると最大の系統残差になる。
    **精密化前に**その組み合わせであることを告げる。
    """
    p = _write(tmp_path, "x.instprm", build_instprm_text(radiation="xray_lab", wavelength=1.5405))
    rep = inspect_instprm(p, radiation="xray_lab", geometry="bragg_brentano")
    assert "kalpha1_only_bragg_brentano" in _codes(rep)


def test_inspect_asks_about_kalpha2_when_doublet(tmp_path):
    """Kα2 の有無はデータ側を見ないと決まらない → 断定せず question として返す。"""
    p = _write(
        tmp_path,
        "x.instprm",
        build_instprm_text(radiation="xray_lab", wavelength=1.5405, wavelength_ka2=1.5443),
    )
    rep = inspect_instprm(p, radiation="xray_lab", geometry="bragg_brentano")
    codes = _codes(rep)
    assert "kalpha2_consistency_question" in codes
    assert "kalpha1_only_bragg_brentano" not in codes
    q = next(f for f in rep.findings if f.code == "kalpha2_consistency_question")
    assert q.severity == "question"


def test_inspect_detects_missing_wavelength(tmp_path):
    p = _write(tmp_path, "x.instprm", "#GSAS-II\nType:PXC\nBank:1.0\nU:2.0\nV:-2.0\nW:5.0\n")
    rep = inspect_instprm(p)
    assert "missing_wavelength" in _codes(rep)
    assert rep.ok is False


def test_inspect_detects_missing_tof_keys(tmp_path):
    p = _write(tmp_path, "n.instprm", "#GSAS-II\nType:PNT\nfltPath:10.0\n2-theta:90.0\n")
    rep = inspect_instprm(p)
    codes = _codes(rep)
    assert "missing_tof_keys" in codes
    msg = next(f.message for f in rep.findings if f.code == "missing_tof_keys")
    assert "difC" in msg


def test_inspect_detects_zero_peak_width(tmp_path):
    """U=V=W=X=Y=0 は幅ゼロ = 非物理。GSAS はデルタ関数状のピークを立てて破綻する。"""
    p = _write(
        tmp_path,
        "x.instprm",
        build_instprm_text(
            radiation="xray_lab",
            wavelength=1.5405,
            profile={"U": 0.0, "V": 0.0, "W": 0.0, "X": 0.0, "Y": 0.0},
        ),
    )
    rep = inspect_instprm(p)
    assert "zero_peak_width" in _codes(rep)


def test_inspect_missing_file_reports_error_not_exception(tmp_path):
    rep = inspect_instprm(tmp_path / "nope.instprm")
    assert "file_not_found" in _codes(rep)
    assert rep.ok is False


def test_inspect_unparseable_file_reports_error(tmp_path):
    p = _write(tmp_path, "x.instprm", "これは装置ファイルではありません\n")
    rep = inspect_instprm(p)
    assert "no_type_key" in _codes(rep)
    assert rep.ok is False


def test_inspect_findings_carry_actionable_hint(tmp_path):
    """③ は LLM なので「次に何をするか」まで書いてある必要がある。"""
    rep = inspect_instprm(tmp_path / "nope.instprm")
    for f in rep.findings:
        assert isinstance(f, InstprmFinding)
        assert f.hint, f.code


def test_inspect_report_to_dict_is_json_safe(tmp_path):
    import json

    p = _write(tmp_path, "x.instprm", build_instprm_text(radiation="xray_lab", wavelength=1.5405))
    rep = inspect_instprm(p, radiation="xray_lab", geometry="bragg_brentano")
    json.dumps(rep.to_dict())  # ② 境界を越えられること


# =====================================================================
# プリセット (GSAS-II 同梱 defaultIparms の遅延 import)
# =====================================================================


@pytest.mark.gsas
def test_list_instrument_presets_from_gsasii():
    presets = list_instrument_presets()
    labels = [p.label for p in presets]
    assert "CuKa lab data" in labels
    for p in presets:
        assert p.radiation in ("xray_lab", "xray_synchrotron", "neutron_cw", "neutron_tof")
        assert p.geometry in ("bragg_brentano", "debye_scherrer")


@pytest.mark.gsas
def test_cuka_lab_preset_is_bragg_brentano():
    """GSAS-II はラベル中の 'lab data' で Bragg-Brentano を決める (defaultIparms.py の規則)。"""
    presets = {p.label: p for p in list_instrument_presets()}
    assert presets["CuKa lab data"].geometry == "bragg_brentano"
    others = [p for label, p in presets.items() if "lab data" not in label]
    assert others and all(p.geometry == "debye_scherrer" for p in others)


@pytest.mark.gsas
def test_preset_instprm_text_is_parseable():
    d = parse_instprm(preset_instprm_text("CuKa lab data"))
    assert d["Type"] == "PXC"
    assert float(d["Lam1"]) == pytest.approx(1.5405)


@pytest.mark.gsas
def test_preset_unknown_label_raises():
    with pytest.raises(KeyError, match="未登録"):
        preset_instprm_text("no such preset")


def test_preset_without_gsasii_raises_dedicated_error(monkeypatch):
    """GSAS-II 非導入環境では専用例外で導入手順を案内する (available + 専用例外パターン)。"""
    import builtins

    real_import = builtins.__import__

    def _blocked(name, *args, **kwargs):
        if name.startswith("GSASII"):
            raise ImportError("no GSASII")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _blocked)
    with pytest.raises(GSASUnavailableError):
        list_instrument_presets()


# =====================================================================
# 既存 3 writer の委譲リファクタ非回帰
# ---------------------------------------------------------------------
# `resolution.pxc_instprm_text` / `interop.instrument.write_gsas_instprm` /
# `backends.gsasii._write_instprm` は同じ instprm を 3 通りに書いていた。共通実装へ寄せる際、
# **X 線 CW は 1 バイトも変えない** (最も使われている経路)。TOF と backends は書式を正規化する
# (キー順・桁) が **値は同一** — 正規化しないと共通実装が「既存の書き癖」を 3 つ抱え続ける。
# =====================================================================

_GOLDEN_PXC_RESOLUTION = """\
#GSAS-II instrument parameter file; created by tsumugin.autorietveld.resolution
Type:PXC
Bank:1.0
Lam:0.799580
Zero:0.005900
Polariz.:0.9500
Azimuth:0.0
U:2.0
V:-2.0
W:5.0
X:0.0
Y:0.0
Z:0.0
SH/L:0.002
"""

_GOLDEN_PXC_INTEROP = _GOLDEN_PXC_RESOLUTION.replace(
    "created by tsumugin.autorietveld.resolution", "created by tsumugin.interop"
).replace("Zero:0.005900", "Zero:0.005896")


def test_pxc_instprm_text_is_byte_identical_after_delegation():
    from tsumugin.autorietveld.resolution import pxc_instprm_text

    assert pxc_instprm_text(0.79958, zero=0.0059, polarization=0.95) == _GOLDEN_PXC_RESOLUTION


def test_interop_xray_writer_is_byte_identical_after_delegation(tmp_path):
    from tsumugin.interop.instrument import write_gsas_instprm
    from tsumugin.interop.zrietveld import ZDiffractometer

    zd = ZDiffractometer(
        beam_type="X-Ray", method="Synchrotron Radiation", wavelength=0.5, zero=0.005896
    )
    out = write_gsas_instprm(zd, tmp_path / "x.instprm", wavelength=0.79958)
    assert out.read_text(encoding="utf-8") == _GOLDEN_PXC_INTEROP


def test_interop_tof_writer_keeps_every_value(tmp_path):
    """TOF は書式 (キー順) を正規化するが**値は 1 つも変えない**。"""
    from tsumugin.interop.instrument import write_gsas_instprm
    from tsumugin.interop.zrietveld import ZDiffractometer

    zd = ZDiffractometer(
        beam_type="Neutron",
        method="Time Of Flight",
        conversion_params=(-2.653194, 10060.510395, -1.125499),
        bank_two_theta=90.0,
        profile={"SigmaSquare0": 0.001, "SigmaSquare1": 265.946, "SigmaSquare2": 7.9156},
    )
    out = write_gsas_instprm(zd, tmp_path / "n.instprm")
    d = parse_instprm(out.read_text(encoding="utf-8"))
    expected = {
        "Type": "PNT", "fltPath": 28.1385, "alpha": 0.5, "sig-1": 265.946, "2-theta": 90.0,
        "sig-q": 0.0, "sig-0": 0.001, "sig-2": 7.9156, "Zero": -2.653194, "difB": 0.0,
        "Azimuth": 0.0, "Y": 0.0, "X": 0.0, "beta-q": 0.0, "beta-0": 0.02,
        "difC": 10060.510395, "beta-1": 0.0, "difA": -1.125499,
    }
    assert d["Type"] == expected.pop("Type")
    for key, value in expected.items():
        assert float(d[key]) == pytest.approx(value), key


def test_gsasii_backend_writer_keeps_every_value(tmp_path):
    from tsumugin.backends.gsasii import _write_instprm

    out = tmp_path / "g.instprm"
    _write_instprm(out, 1.5405)
    d = parse_instprm(out.read_text(encoding="utf-8"))
    assert d["Type"] == "PXC"
    for key, value in {
        "Bank": 1.0, "Lam": 1.5405, "Polariz.": 0.7, "Azimuth": 0.0, "Zero": 0.0,
        "U": 2.0, "V": -2.0, "W": 5.0, "X": 0.0, "Y": 0.0, "Z": 0.0, "SH/L": 0.002,
    }.items():
        assert float(d[key]) == pytest.approx(value), key


def test_gsasii_backend_writer_does_not_truncate_wavelength(tmp_path):
    """⚠ 6 桁固定にすると波長が ppm 単位で丸まる。丸めで値が変わる場合は完全精度を保つこと。"""
    from tsumugin.backends.gsasii import _write_instprm

    lam = 0.7995812345678
    out = tmp_path / "g.instprm"
    _write_instprm(out, lam)
    assert float(parse_instprm(out.read_text(encoding="utf-8"))["Lam"]) == lam
