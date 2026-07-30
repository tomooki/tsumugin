"""M6 TASK-0109 GSAS 粉末データローダーの失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/io.py`` (未実装)。
`load_gsas_powder(path)` / `parse_gsas_powder(text)`: GSAS CONST/STD 形式の粉末データを
``(two_theta, intensity)`` へ読む。インライン文字列で決定論的に検証 (実データ非依存)。
"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.reference.io import load_gsas_powder, parse_gsas_powder

# BANK: 20 点, CONST, start=1000 cd (10.0°), step=2.5 cd (0.025°), STD (強度のみ)
_SAMPLE_GSAS = """PbSO4 sample title  Cu Ka
BANK 1  20  2 CONST 1000 2.5 0 0 STD
   100   110   120   130   140   150   160   170   180   190
   200   210   220   230   240   250   260   270   280   290
"""


def test_parse_gsas_powder_shapes_and_axis():
    from tsumugin.reference.io import parse_gsas_powder

    tt, inten = parse_gsas_powder(_SAMPLE_GSAS)
    assert tt.shape == (20,)
    assert inten.shape == (20,)
    # CONST: start 10.0°, step 0.025°
    assert tt[0] == pytest.approx(10.0)
    assert tt[1] == pytest.approx(10.025)
    assert tt[-1] == pytest.approx(10.0 + 19 * 0.025)


def test_parse_gsas_powder_intensities():
    from tsumugin.reference.io import parse_gsas_powder

    _, inten = parse_gsas_powder(_SAMPLE_GSAS)
    assert inten[0] == pytest.approx(100.0)
    assert inten[10] == pytest.approx(200.0)
    assert inten[-1] == pytest.approx(290.0)


def test_parse_gsas_powder_ignores_trailing_padding():
    from tsumugin.reference.io import parse_gsas_powder

    # 末尾にパディングの 0 が並んでも npts 分だけ読む
    text = (
        "title\n"
        "BANK 1  3  1 CONST 2000 5.0 0 0 STD\n"
        "   10   20   30    0    0    0    0    0    0    0\n"
    )
    tt, inten = parse_gsas_powder(text)
    assert tt.shape == (3,)
    assert tt[0] == pytest.approx(20.0)  # 2000 cd
    assert inten.tolist() == [10.0, 20.0, 30.0]


def test_parse_gsas_powder_missing_bank_raises():
    from tsumugin.reference.io import parse_gsas_powder

    with pytest.raises(ValueError):
        parse_gsas_powder("no bank record here\njust text\n")


def test_parse_gsas_powder_truncated_data_raises():
    from tsumugin.reference.io import parse_gsas_powder

    # npts=50 だが値が足りない
    text = "title\nBANK 1  50  5 CONST 1000 2.5 0 0 STD\n   1   2   3\n"
    with pytest.raises(ValueError):
        parse_gsas_powder(text)


def test_parse_gsas_powder_non_const_mode_raises():
    from tsumugin.reference.io import parse_gsas_powder

    text = "title\nBANK 1  10  1 RALF 1000 2.5 0 0 STD\n   1   2   3\n"
    with pytest.raises(ValueError, match="CONST"):
        parse_gsas_powder(text)


def test_parse_gsas_powder_non_std_format_raises():
    from tsumugin.reference.io import parse_gsas_powder

    text = "title\nBANK 1  2  1 CONST 1000 2.5 0 0 ESD\n   1   2\n"
    with pytest.raises(ValueError, match="STD"):
        parse_gsas_powder(text)


def test_parse_gsas_powder_malformed_bank_raises():
    from tsumugin.reference.io import parse_gsas_powder

    text = "title\nBANK 1 notanint\n   1   2\n"
    with pytest.raises(ValueError):
        parse_gsas_powder(text)


def test_load_gsas_powder_reads_file(tmp_path):

    path = tmp_path / "sample.xra"
    path.write_text(_SAMPLE_GSAS, encoding="utf-8")
    tt, inten = load_gsas_powder(path)
    assert isinstance(tt, np.ndarray)
    assert tt.shape == (20,)
    assert inten[0] == pytest.approx(100.0)


# --- 2 列 XY 形式 (Jana/汎用) ----------------------------------------------

_SAMPLE_XY = """# radtype 1 dattype 2 pwdmethod 1
# lambda 1.54059 lpfactor 2
10.005000 13736.0
10.020000 13619.0
10.035000 13800.0
"""


def test_parse_xy_skips_comments_and_reads_columns():
    from tsumugin.reference.io import parse_xy

    tt, inten = parse_xy(_SAMPLE_XY)
    assert tt.shape == (3,)
    assert tt[0] == pytest.approx(10.005)
    assert tt[-1] == pytest.approx(10.035)
    assert inten[1] == pytest.approx(13619.0)


def test_parse_xy_handles_three_columns_with_esd():
    from tsumugin.reference.io import parse_xy

    text = "20.0 100.0 10.0\n20.02 121.0 11.0\n"
    tt, inten = parse_xy(text)
    assert tt.tolist() == [20.0, 20.02]
    assert inten.tolist() == [100.0, 121.0]  # 3 列目 (esd) は無視


def test_parse_xy_empty_raises():
    from tsumugin.reference.io import parse_xy

    with pytest.raises(ValueError):
        parse_xy("# only a comment\n\n")


def test_load_xy_reads_file(tmp_path):
    from tsumugin.reference.io import load_xy

    path = tmp_path / "pattern.xy"
    path.write_text(_SAMPLE_XY, encoding="utf-8")
    tt, inten = load_xy(path)
    assert tt.shape == (3,)
    assert inten[0] == pytest.approx(13736.0)


def test_parse_fxye_converts_centidegrees_to_degrees():
    from tsumugin.reference.io import parse_fxye

    # FXYE: X はセンチ度 (2θ×100), 3 列 X Y ESD。先頭タイトル行 + # コメント + 数値行
    text = (
        "NAC /nov12/11bmb_1804\n"
        "# Run no. = 1804\n"
        "   500.0   239.933   16.08\n"
        "   500.1   244.123   16.18\n"
        "   500.2   224.020   15.60\n"
    )
    tt, inten = parse_fxye(text)
    assert tt.tolist() == pytest.approx([5.0, 5.001, 5.002])
    assert inten.tolist() == pytest.approx([239.933, 244.123, 224.020])  # ESD 無視


def test_parse_fxye_empty_raises():
    from tsumugin.reference.io import parse_fxye

    with pytest.raises(ValueError):
        parse_fxye("title only\n# comment\n\n")


def test_load_fxye_reads_file(tmp_path):
    from tsumugin.reference.io import load_fxye

    path = tmp_path / "p.fxye"
    path.write_text("TITLE\n# c\n1000.0 50.0 7.0\n1001.0 55.0 7.4\n", encoding="utf-8")
    tt, inten = load_fxye(path)
    assert tt.tolist() == pytest.approx([10.0, 10.01])
    assert inten[1] == pytest.approx(55.0)


# ============================ Panalytical XRDML (M9) ============================

# 【最小 XRDML】: 2Theta 軸 start=10, end=10.06 (4 点 → step 0.02), Omega 軸も混在させ
#   2Theta を正しく選ぶことを検証する。intensities は 4 値。
_SAMPLE_XRDML = """<?xml version="1.0" encoding="UTF-8"?>
<xrdMeasurements xmlns="http://www.xrdml.com/XRDMeasurement/1.5" status="Completed">
  <xrdMeasurement measurementType="Scan" sampleMode="Reflection">
    <usedWavelength intended="K-Alpha 1">
      <kAlpha1 unit="Angstrom">1.540598</kAlpha1>
    </usedWavelength>
    <scan appendNumber="0" mode="Pre-set time" scanAxis="Gonio" status="Completed">
      <dataPoints>
        <positions axis="2Theta" unit="deg">
          <startPosition>10.000</startPosition>
          <endPosition>10.060</endPosition>
        </positions>
        <positions axis="Omega" unit="deg">
          <startPosition>5.000</startPosition>
          <endPosition>5.030</endPosition>
        </positions>
        <commonCountingTime unit="seconds">198.0</commonCountingTime>
        <intensities unit="counts">292 275 279 274</intensities>
      </dataPoints>
    </scan>
  </xrdMeasurement>
</xrdMeasurements>
"""


def test_parse_xrdml_axis_and_shape():
    from tsumugin.reference.io import parse_xrdml

    tt, inten = parse_xrdml(_SAMPLE_XRDML)
    assert tt.shape == (4,)
    assert inten.shape == (4,)
    # 2Theta 軸を選ぶ (Omega の 5.0 ではない)。4 点なので step = 0.06/3 = 0.02
    assert tt[0] == pytest.approx(10.000)
    assert tt[1] == pytest.approx(10.020)
    assert tt[-1] == pytest.approx(10.060)


def test_parse_xrdml_intensities():
    from tsumugin.reference.io import parse_xrdml

    _, inten = parse_xrdml(_SAMPLE_XRDML)
    assert inten.tolist() == pytest.approx([292.0, 275.0, 279.0, 274.0])


def test_parse_xrdml_missing_intensities_raises():
    from tsumugin.reference.io import parse_xrdml

    text = _SAMPLE_XRDML.replace(
        "<intensities unit=\"counts\">292 275 279 274</intensities>", ""
    )
    with pytest.raises(ValueError):
        parse_xrdml(text)


def test_parse_xrdml_missing_2theta_positions_raises():
    from tsumugin.reference.io import parse_xrdml

    text = _SAMPLE_XRDML.replace('axis="2Theta"', 'axis="Omega2"')
    with pytest.raises(ValueError):
        parse_xrdml(text)


def test_load_xrdml_reads_file(tmp_path):
    from tsumugin.reference.io import load_xrdml

    path = tmp_path / "p.xrdml"
    path.write_text(_SAMPLE_XRDML, encoding="utf-8")
    tt, inten = load_xrdml(path)
    assert tt.shape == (4,)
    assert inten[0] == pytest.approx(292.0)

# ---------------------------------------------------------------------------
# GSAS STD の固定桁パック形式 (M12 で発覚した既存バグ)
# ---------------------------------------------------------------------------


def test_gsas_std_is_parsed_by_fixed_columns_not_whitespace():
    """GSAS STD は **(I2, I6) の 8 桁パック**を 1 行 10 点並べる形式である。

    先頭 I2 は「合算した検出器数」で強度ではない。空白分割すると検出器数と強度が交互に
    並んだ配列になり、**半分の点が 1 になる**。M7 の GSAS 経路は GSAS-II が .raw を直接
    読むためこのバグに当たっていなかった (M12 の TOPAS 経路で発覚)。
    """
    text = (
        "TITLE\n"
        "BANK 1 6 3 CONST 2400 5 0 0\n"
        " 1   162 1   178 1   155 2   166 1   180 1   181\n"
    )
    two_theta, intensity = parse_gsas_powder(text)
    assert intensity.tolist() == [162.0, 178.0, 155.0, 166.0, 180.0, 181.0]
    assert two_theta[0] == pytest.approx(24.0)
    assert two_theta[1] == pytest.approx(24.05)


def test_gsas_std_without_detector_counts_still_parses():
    """検出器数欄が空白 (実質 I8 の強度のみ) の書き方も同じ規則で読める (PBSO4.XRA)。"""
    text = "TITLE\nBANK 1 4 1 CONST 1000 2.5 0 0 STD\n     179     147     165     172\n"
    _, intensity = parse_gsas_powder(text)
    assert intensity.tolist() == [179.0, 147.0, 165.0, 172.0]


def test_real_garnet_raw_has_no_alternating_ones():
    """回帰: 実データ garnet.raw が 1.0 と実測値の交互にならないこと。"""
    from pathlib import Path

    path = Path("docs/benchmark/testdata/m7/cwneutron/garnet.raw")
    if not path.exists():
        pytest.skip("garnet 実データが無い")

    _, intensity = load_gsas_powder(path)
    assert len(intensity) == 2679
    # 誤読時は約半数が 1.0 になっていた
    assert (intensity == 1.0).sum() < len(intensity) * 0.1
    # 中性子計数の実測レンジ (誤読時は桁が混ざり 119510 という非現実的な値になっていた)
    assert 1e3 < intensity.max() < 1e4
