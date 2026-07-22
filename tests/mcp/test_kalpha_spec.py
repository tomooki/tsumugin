"""`mcp._kalpha_spec`: JSON Kα2 spec ↔ KAlpha2 変換の共有ヘルパ (Issue #118)。

`identify_phases`/`identify_phase_mixtures` の ``kalpha2`` 引数 (JSON dict) を ①
``reference.kalpha.KAlpha2`` (frozen dataclass) へ変換する唯一の実装であることを、構造的な検証と
往復性で固定する (``tests/mcp/test_recipe_spec.py`` と同じ様式)。
"""

from __future__ import annotations

import pytest

from tsumugin.mcp._kalpha_spec import kalpha2_from_spec
from tsumugin.reference.kalpha import KAlpha2


def test_none_spec_returns_none():
    assert kalpha2_from_spec(None) is None


def test_empty_dict_returns_defaults():
    assert kalpha2_from_spec({}) == KAlpha2()


def test_full_spec_sets_both_fields():
    cfg = kalpha2_from_spec({"intensity_ratio": 0.3, "wavelength_ratio": 1.01})
    assert cfg == KAlpha2(intensity_ratio=0.3, wavelength_ratio=1.01)


def test_partial_spec_keeps_other_default():
    cfg = kalpha2_from_spec({"intensity_ratio": 0.25})
    assert cfg == KAlpha2(intensity_ratio=0.25, wavelength_ratio=KAlpha2().wavelength_ratio)


@pytest.mark.parametrize(
    "bad",
    [
        pytest.param("not-a-dict", id="非 dict"),
        pytest.param(5, id="int"),
        pytest.param(["intensity_ratio", 0.5], id="list"),
        pytest.param({"intensity_ratio": 0.5, "unknown_key": 1}, id="不明なキー"),
        pytest.param({"intensity_ratio": "0.5"}, id="値が非数値 (str)"),
        pytest.param({"intensity_ratio": True}, id="値が bool (int サブクラス誤入力)"),
        pytest.param({"wavelength_ratio": None}, id="値が None"),
    ],
)
def test_rejects_malformed_input(bad):
    """不正なキー/型は黙って無視せず ValueError にする (「呼べるが黙って間違う」の再導入防止)。"""
    with pytest.raises(ValueError):
        kalpha2_from_spec(bad)


def test_unknown_key_error_lists_allowed_keys():
    with pytest.raises(ValueError) as ei:
        kalpha2_from_spec({"intensty_ratio": 0.5})  # タイポ
    msg = str(ei.value)
    assert "intensty_ratio" in msg
    assert "intensity_ratio" in msg  # 許容一覧に本来のキーが出る (③ が自力で直せる)


def test_allowed_keys_cover_kalpha2_dataclass_fields():
    """★許容キーが `KAlpha2` の実フィールドを網羅すること (drift 検出)。

    非トートロジー: 表を読まず `dataclasses.fields` で**実 dataclass** から名前を取る。
    将来 `KAlpha2` にフィールドが増えたのに本表が古いままだと、③ がその新フィールドを
    指定した瞬間「不明なキー」で弾かれる — **露出したのに使えない**状態になるため、
    ここで強制的に気づかせる。
    """
    import dataclasses

    from tsumugin.mcp._kalpha_spec import _ALLOWED_KALPHA2_KEYS
    from tsumugin.reference.kalpha import KAlpha2

    real = {f.name for f in dataclasses.fields(KAlpha2)}
    assert real, "KAlpha2 のフィールド抽出が 0 件 — 検査が空回りしている"
    missing = real - _ALLOWED_KALPHA2_KEYS
    assert not missing, (
        f"KAlpha2 のフィールド {sorted(missing)} が ② の許容キーに無い。"
        "③ が指定しても『不明なキー』で弾かれる — _kalpha_spec.py の表を更新すること"
    )
