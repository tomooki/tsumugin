"""P0 §3.2.1-2: `H-pub` の候補一覧の規則 (合成の入力だけ — RRUFF/COD の実データを使わない)。"""

from __future__ import annotations

import pytest

from tsumugin.prereg_eval.hpub import (
    STATUS_CONFIRMED,
    is_room_conditions,
    normalize_mineral,
    parse_raw_header,
    profile_shape_ok,
    publication_key,
    rruff_fractions,
    salted_hash,
)


def _raw(names="Zincite, ZnO", status=STATUS_CONFIRMED[0], start=5.0, stop=85.0, step=0.01, extra=""):
    head = [f"##NAMES={names}", "##RRUFFID=R050419", "##IDEAL CHEMISTRY=Zn^2+^O", f"##STATUS={status}",
            "##FILETYPE=RAW Powder Diffraction Profile", "##CELL PARAMETERS=a: 3.25 b: 3.25 c: 5.2", extra]
    xs = []
    x = start
    while x <= stop + 1e-9:
        xs.append(f"{x:.4f}, 123")
        x += step
    return "\n".join([h for h in head if h] + xs + ["##END="])


def test_header_reads_only_the_allowed_fields():
    h = parse_raw_header(_raw())
    assert h.names == "Zincite, ZnO" and h.rruff_id == "R050419" and h.ideal_chemistry == "Zn^2+^O"
    assert h.status == STATUS_CONFIRMED[0]
    assert not hasattr(h, "cell") and "CELL" not in repr(h)  # 粉末から精密化したセルは読まない
    assert h.x_start == pytest.approx(5.0) and h.x_end == pytest.approx(85.0) and h.step == pytest.approx(0.01)
    assert "123" not in repr(h)  # 強度を持たない


@pytest.mark.parametrize(
    ("kw", "ok"),
    [({}, True), ({"start": 3.0}, False), ({"stop": 70.0}, False), ({"step": 0.02}, False), ({"step": 0.0115}, True)],
)
def test_profile_shape(kw, ok):
    assert profile_shape_ok(parse_raw_header(_raw(**kw))) is ok


def test_status_must_match_exactly():
    assert len(STATUS_CONFIRMED) == 6
    h = parse_raw_header(_raw(status="The identification of this mineral is not yet confirmed"))
    assert h.status not in STATUS_CONFIRMED


def test_mineral_names_are_normalized():
    assert normalize_mineral("Römerite") == normalize_mineral("romerite")
    assert normalize_mineral("Ferro-Actinolite") == "ferroactinolite"
    assert normalize_mineral("O'Danielite") == "odanielite"


@pytest.mark.parametrize(
    ("ideal", "expected"),
    [
        ("Zn^2+^O", {"Zn": 0.5, "O": 0.5}),
        ("Ca_5_(PO_4_)_3_F", {"Ca": 5 / 21, "P": 3 / 21, "O": 12 / 21, "F": 1 / 21}),
        ("Cu^2+^SO_4_·5H_2_O", {"Cu": 1 / 11, "S": 1 / 11, "O": 9 / 11}),  # H は除く、水の O は数える
    ],
)
def test_rruff_chemistry(ideal, expected):
    assert rruff_fractions(ideal) == pytest.approx(expected)


@pytest.mark.parametrize("ideal", ["(Mg,Fe)_2_SiO_4_", "Ca_x_Zn", "□Al_2_O_3_", "REE(PO_4_)", "CuSO_4_·nH_2_O"])
def test_uninterpretable_chemistry_is_rejected(ideal):
    assert rruff_fractions(ideal) is None


def test_room_conditions():
    assert is_room_conditions({}, {}, "Crystal structure of zincite")  # 記録が無ければ常温常圧とみなす
    assert not is_room_conditions({"celltemp": "100"}, {}, "")
    assert not is_room_conditions({"cellpressure": "2000"}, {}, "")
    assert not is_room_conditions({}, {"_diffrn_ambient_temperature": "120(2)"}, "")
    assert not is_room_conditions({}, {"_cell_measurement_pressure": "5000"}, "")
    assert not is_room_conditions({}, {}, "Zincite at 5 GPa")
    assert not is_room_conditions({}, {}, "A High-Temperature study")
    assert is_room_conditions({"celltemp": "293"}, {"_diffrn_ambient_temperature": "295(1)"}, "")


def test_publication_key_prefers_doi_then_title_then_citation():
    assert publication_key({"doi": "10.1/ABC", "title": "x"}) == "doi:10.1/abc"
    assert publication_key({"title": "Zincite: a re-study!"}) == "title:zincitearestudy"
    assert publication_key({"journal": "Am Min", "year": "1990", "volume": "75", "firstpage": "12"}) == \
        "cite:Am Min|1990|75|12"
    assert publication_key({}) is None  # 決まらなければ参照にしない
    assert publication_key({"journal": "Am Min", "year": "1990"}) is None  # 組が欠けても決まらない


def test_salted_hash_hides_the_id():
    a = salted_hash("s3cret", "R050419")
    assert len(a) == 64 and "R050419" not in a
    assert a != salted_hash("other", "R050419") and a == salted_hash("s3cret", "R050419")
