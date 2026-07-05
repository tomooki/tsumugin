"""M6 TASK-0109 GSAS 粉末データローダーの失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/io.py`` (未実装)。
`load_gsas_powder(path)` / `parse_gsas_powder(text)`: GSAS CONST/STD 形式の粉末データを
``(two_theta, intensity)`` へ読む。インライン文字列で決定論的に検証 (実データ非依存)。
"""

from __future__ import annotations

import numpy as np
import pytest

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
    from tsumugin.reference.io import load_gsas_powder

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
