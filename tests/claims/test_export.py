"""fit-then-judge P1-1A タスク 9: 出版状態の列を持つ CSV (REQ-FTJ-1A-503)。

出版不可の値を素の数値だけで書かない — 全行が状態の列を持つ。上書きしない。② から呼べる。
"""

from __future__ import annotations

import csv
import json

import pytest

from tsumugin.claims.export import CSV_COLUMNS, write_claims_csv
from tsumugin.claims.model import Check, Claim, Determinacy, Witness


def _claims() -> dict[str, dict]:
    ok = Claim(
        key="cell:P.a", param_class="cell", value=5.0, esd=0.001, unit="angstrom", phase="P",
        axis="a", provenance=frozenset({"refined"}),
        checks={"phase_set_completeness": Check.PASS, "provenance_known": Check.PASS},
    )
    held = Claim(
        key="coord:P.O1.x", param_class="coord", value=0.1, esd=0.002, unit="fractional",
        phase="P", label="O1", axis="x", provenance=frozenset({"refined"}),
        determinacy=Determinacy.INITIAL_VALUE_DEPENDENT, gate=frozenset({"jr-2", "jr-1"}),
        checks={"crystal_chemistry": Check.FAIL},
        witnesses=(Witness("multistart_disagreement", {"z": 9.0}),),
    )
    return {c.key: c.to_dict() for c in (ok, held)}


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_every_row_carries_its_publication_state(tmp_path):
    path = write_claims_csv(_claims(), tmp_path / "claims.csv")
    rows = _rows(path)
    assert [r["key"] for r in rows] == ["cell:P.a", "coord:P.O1.x"]
    assert list(rows[0]) == list(CSV_COLUMNS)
    held = rows[1]
    assert held["publishable"] == "false"
    assert held["determinacy"] == "initial_value_dependent"
    assert held["gate"] == "jr-1;jr-2"
    assert "crystal_chemistry=fail" in held["checks"]
    assert rows[0]["publishable"] == "true"


def test_the_state_columns_cannot_be_dropped():
    """状態を落とす変換の禁止 (principles §4.4): 列の宣言から状態の列を消したら落ちる。"""
    for col in ("publishable", "determinacy", "provenance", "scope", "checks", "gate"):
        assert col in CSV_COLUMNS


def test_none_is_an_empty_cell_not_zero(tmp_path):
    d = _claims()
    d["cell:P.a"] = {**d["cell:P.a"], "esd": None}
    rows = _rows(write_claims_csv(d, tmp_path / "c.csv"))
    assert rows[0]["esd"] == ""


def test_existing_files_are_not_overwritten(tmp_path):
    target = tmp_path / "claims.csv"
    target.write_text("keep", encoding="utf-8")
    with pytest.raises(FileExistsError):
        write_claims_csv(_claims(), target)
    assert target.read_text(encoding="utf-8") == "keep"


def test_flattened_values_are_refused(tmp_path):
    """状態の無い素の数値 (例 ``{"cell:P.a": 5.0}``) を CSV にしない。"""
    with pytest.raises((TypeError, ValueError, KeyError)):
        write_claims_csv({"cell:P.a": 5.0}, tmp_path / "c.csv")  # type: ignore[dict-item]


def test_the_layer_two_tool_writes_from_the_auto_rietveld_output(tmp_path):
    from tsumugin.mcp.rietveld_tools import export_claims_csv

    out = export_claims_csv(_claims(), str(tmp_path / "claims.csv"))
    assert out == {"path": str(tmp_path / "claims.csv"), "n_rows": 2, "n_publishable": 1}
    json.dumps(out)


@pytest.mark.parametrize(
    ("claims", "path"),
    [
        (None, "ABS"),  # auto_rietveld が claims を作れなかった (null)
        ({}, "ABS"),  # 空 — 「何も無い CSV」を黙って書かない
        ("CLAIMS", "relative.csv"),  # 相対パスはサーバの作業ディレクトリに化ける
        ({"cell:P.a": 5.0}, "ABS"),
    ],
)
def test_the_layer_two_tool_returns_an_error_dict_not_an_exception(tmp_path, claims, path):
    from tsumugin.mcp.rietveld_tools import export_claims_csv

    claims = _claims() if claims == "CLAIMS" else claims
    path = str(tmp_path / "c.csv") if path == "ABS" else path
    out = export_claims_csv(claims, path)  # type: ignore[arg-type]
    assert set(out) == {"error", "error_type"}


def test_the_layer_two_tool_refuses_to_overwrite(tmp_path):
    from tsumugin.mcp.rietveld_tools import export_claims_csv

    target = tmp_path / "c.csv"
    target.write_text("keep", encoding="utf-8")
    out = export_claims_csv(_claims(), str(target))
    assert out["error_type"] == "FileExistsError"
    assert target.read_text(encoding="utf-8") == "keep"
