"""Issue #48 の E2E 検証: normalize_cif_for_gsas の出力を GSAS-II が P21/n として読むこと。

numpy-only の単体テスト (test_cif_normalize.py) は symop ループの保持を確認するが、GSAS-II が
その CIF を**実際に受理し非標準セッティング P21/n を保つ**ことまでは示せない。本テストは実 GSAS-II で
add_phase し、空間群記号が 'P 21/n' になることを直接確認する (バグ修正の本証明)。

GSAS-II 必須 (@pytest.mark.gsas)。未導入環境では import skip + マーカーで自動 skip。
"""

from __future__ import annotations

import pytest

from tsumugin.autorietveld.cif_normalize import normalize_cif_for_gsas

pytestmark = pytest.mark.gsas

# P21/n (非標準セッティング, IT #14) — n-glide 対称操作ループ付き。
_P21N_SYMOPS = """data_p21n
_cell_length_a 5
_cell_length_b 6
_cell_length_c 7
_cell_angle_alpha 90
_cell_angle_beta 95
_cell_angle_gamma 90
_symmetry_space_group_name_H-M 'P 21/n'
_symmetry_Int_Tables_number 14

loop_
_space_group_symop_id
_space_group_symop_operation_xyz
1 'x, y, z'
2 '-x+1/2, y+1/2, -z+1/2'
3 '-x, -y, -z'
4 'x+1/2, -y+1/2, z+1/2'

loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
Fe1 Fe 0.1 0.2 0.3 1.0 0.01
Mn1 Mn 0.4 0.5 0.6 1.0 0.01
"""


def test_gsas_reads_p21n_setting(tmp_path):
    try:
        from GSASII import GSASIIscriptable as G2sc  # noqa: PLC0415
    except Exception as exc:  # pragma: no cover - 環境依存
        pytest.skip(f"GSAS-II を import できません: {exc}")

    src = tmp_path / "p21n_src.cif"
    src.write_text(_P21N_SYMOPS, encoding="utf-8")
    out = normalize_cif_for_gsas(src, tmp_path / "p21n_out.cif", phase_name="p21n")

    gpx = G2sc.G2Project(newgpx=str(tmp_path / "p21n.gpx"))
    ph = gpx.add_phase(str(out), phasename="p21n", fmthint="CIF")

    spgrp = ph.data["General"]["SGData"]["SpGrp"]
    assert spgrp.replace(" ", "") == "P21/n", f"GSAS が P21/n を保持していない: {spgrp!r}"
