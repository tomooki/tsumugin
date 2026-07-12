"""MCP mem-model-fix 3 ツール (mem_density / propose_structure_revisions / edit_cif) の TDD
テスト (M8-③ Phase C)。

propose_structure_revisions / edit_cif は純関数 (GSAS 非依存)。mem_density は Dysnomia 未解決の
縮退 (エラー dict) を GSAS 非依存で検証し、実 MEM は gated (別途)。
"""
from __future__ import annotations

import json

from tsumugin.mcp.mem_tools import (
    MEM_MODEL_TOOLS,
    edit_cif,
    mem_density,
    propose_structure_revisions,
)

_CIF = """data_t
_cell_length_a 6.95
_cell_length_b 7.29
_cell_length_c 12.84
_cell_angle_alpha 90.0
_cell_angle_beta 119.66
_cell_angle_gamma 90.0
_symmetry_space_group_name_H-M "P 1"
loop_
 _atom_site_label
 _atom_site_type_symbol
 _atom_site_fract_x
 _atom_site_fract_y
 _atom_site_fract_z
 _atom_site_occupancy
 _atom_site_U_iso_or_equiv
Cu1 Cu 0.0 0.5 0.5 1.0 0.018
"""


def test_registry_has_three_tools():
    assert set(MEM_MODEL_TOOLS) == {"mem_density", "propose_structure_revisions", "edit_cif"}


# ---- propose_structure_revisions (pure) ----


def test_propose_structure_revisions_returns_jsonable_proposals():
    peaks = [
        {"frac": [0.3, 0.4, 0.2], "magnitude": 3.5, "nearest_atom": "Cu1", "distance": 1.6},
        {"frac": [0.0, 0.5, 0.5], "magnitude": 5.0, "nearest_atom": "Cu1", "distance": 0.1},
    ]
    out = propose_structure_revisions(peaks, "nuclear", phase="NaCuHCF")
    # 近接ピーク (d=0.1) は除外され 1 件
    assert len(out["proposals"]) == 1
    p = out["proposals"][0]
    assert p["action"]["type"] == "ReviseStructure"
    assert p["safe"] is False
    assert p["evidence"]["suggested_op"] == "add"
    # JSON 直列化可能 (allow_nan=False)
    json.dumps(out, allow_nan=False)


def test_propose_structure_revisions_empty():
    out = propose_structure_revisions([], "electron", phase="P")
    assert out["proposals"] == []


# ---- edit_cif (pure) ----


def test_edit_cif_adds_atom(tmp_path):
    src = tmp_path / "s.cif"
    src.write_text(_CIF, encoding="utf-8")
    out = tmp_path / "o.cif"
    res = edit_cif(str(src), [
        {"op": "add", "label": "Ow", "element": "O", "frac": [0.25, 0.25, 0.25], "occ": 0.3}
    ], str(out))
    assert res["cif_path"] == str(out)
    assert res["n_edits"] == 1
    assert "Ow" in out.read_text(encoding="utf-8")
    json.dumps(res, allow_nan=False)


def test_edit_cif_error_returns_error_dict(tmp_path):
    src = tmp_path / "s.cif"
    src.write_text(_CIF, encoding="utf-8")
    # 存在しないラベルの remove → KeyError → エラー dict (例外を投げない)
    res = edit_cif(str(src), [{"op": "remove", "label": "ZZ"}], str(tmp_path / "o.cif"))
    assert "error" in res
    assert res["error_type"] == "KeyError"


def test_edit_cif_missing_input_returns_error_dict(tmp_path):
    """入力 CIF が存在しない場合もエラー dict へ縮退する (例外を投げない)。"""
    res = edit_cif(str(tmp_path / "nope.cif"),
                   [{"op": "set_occupancy", "label": "Cu1", "occ": 0.5}],
                   str(tmp_path / "o.cif"))
    assert "error" in res
    assert res["error_type"] in ("FileNotFoundError", "OSError")


# ---- mem_density (Dysnomia 未解決の縮退, GSAS 非依存) ----


def test_mem_density_unavailable_returns_error_dict(tmp_path):
    fake = tmp_path / "x.gpx"
    fake.write_text("stub")
    # binary_path を存在しないパスにすると resolve が None → MEMUnavailableError → エラー dict
    res = mem_density(str(fake), binary_path=str(tmp_path / "no_dysnomia.exe"))
    assert "error" in res
    assert res["error_type"] == "MEMUnavailableError"
    json.dumps(res, allow_nan=False)


def test_mem_density_registered_in_mcp_tools():
    from tsumugin.mcp.tools import MCP_TOOLS

    for name in ("mem_density", "propose_structure_revisions", "edit_cif"):
        assert name in MCP_TOOLS
