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
