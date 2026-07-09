"""_extract_profile (GSAS Instrument Parameters → {key:(value,refined)}) の決定論テスト。

GSAS 非依存モック (.data['Instrument Parameters'][0]) で検証。numpy-only。
"""

from __future__ import annotations

from tsumugin.autorietveld.engine import _extract_profile


class _MockHist:
    def __init__(self, inst: dict | None):
        # GSAS 格納形: data['Instrument Parameters'] = (paramdict, {})
        if inst is None:
            self.data = {}
        else:
            self.data = {"Instrument Parameters": (inst, {})}


def test_extract_value_and_refine_flag():
    # TC-001-01: [default, value, refine] から (value, refined) を抽出
    h = _MockHist({
        "U": [2.0, 3.1, True],
        "V": [-2.0, -2.0, False],
        "W": [5.0, 4.8, True],
    })
    out = _extract_profile([h])
    assert out == ({"U": (3.1, True), "V": (-2.0, False), "W": (4.8, True)},)


def test_extract_distinguishes_refined_and_fixed():
    # TC-001-02: 解放/未解放を区別
    h = _MockHist({"X": [0.0, 1.5, True], "Y": [0.0, 0.0, False]})
    out = _extract_profile([h])
    assert out[0]["X"] == (1.5, True)
    assert out[0]["Y"] == (0.0, False)


def test_extract_only_profile_keys():
    # プロファイル関連キーのみ抽出 (Type/Bank/Azimuth 等は無視)
    h = _MockHist({
        "Type": ["PXC"], "Bank": [1.0, 1.0, False],
        "SH/L": [0.002, 0.003, True], "Zero": [0.0, 0.01, True],
        "Polariz.": [0.0, 0.95, False],
    })
    out = _extract_profile([h])
    assert set(out[0]) == {"SH/L", "Zero"}


def test_extract_tof_keys():
    h = _MockHist({
        "difC": [0.0, 7476.0, False], "sig-1": [0.0, 12.0, True],
        "alpha": [0.0, 0.5, False], "beta-0": [0.0, 0.02, True],
    })
    out = _extract_profile([h])
    assert out[0] == {
        "difC": (7476.0, False), "sig-1": (12.0, True),
        "alpha": (0.5, False), "beta-0": (0.02, True),
    }


def test_missing_instrument_parameters_degrades_to_empty():
    # TC-001-E01: Instrument Parameters 欠落 → 空 dict、例外なし
    h = _MockHist(None)
    out = _extract_profile([h])
    assert out == ({},)


def test_two_element_entry_defaults_unrefined():
    # [default, value] のみ (refine flag 欠落) → refined=False
    h = _MockHist({"U": [2.0, 2.5]})
    out = _extract_profile([h])
    assert out[0]["U"] == (2.5, False)


def test_hist_profile_projection_is_value_only():
    # hist_profile への射影 (key->value) が float 値になる
    h = _MockHist({"U": [2.0, 3.1, True], "V": [-2.0, -2.0, False]})
    full = _extract_profile([h])
    projected = {k: v for k, (v, _) in full[0].items()}
    assert projected == {"U": 3.1, "V": -2.0}


def test_multiple_hists_order_preserved():
    h1 = _MockHist({"U": [2.0, 2.0, False]})
    h2 = _MockHist({"sig-1": [0.0, 9.0, True]})
    out = _extract_profile([h1, h2])
    assert out == ({"U": (2.0, False)}, {"sig-1": (9.0, True)})
