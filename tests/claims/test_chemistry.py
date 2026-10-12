"""fit-then-judge P1-1A タスク 6: 結晶化学検査器 (REQ-FTJ-1A-403/404)。

陽性/陰性対照: 正しい構造で pass、欠陥を注入した構造 (潰れた格子・ずれた座標・電荷の合わない
占有率) で fail、組めないときは unevaluated。参照構造は岩塩 NaCl と ルチル TiO2 (どちらも
hold-out と無関係な教科書構造)。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from tsumugin.claims.chemistry import CHEMISTRY_CHECKS, crystal_chemistry
from tsumugin.claims.model import Check

pytest.importorskip("pymatgen")


def _write_cif(tmp_path, name, sg, a, c, species, coords):
    from pymatgen.core import Lattice, Structure
    from pymatgen.io.cif import CifWriter

    lattice = Lattice.tetragonal(a, c) if c else Lattice.cubic(a)
    s = Structure.from_spacegroup(sg, lattice, species, coords)
    path = tmp_path / f"{name}.cif"
    CifWriter(s, symprec=0.01).write_file(str(path))
    return str(path)


def _result_from_cif(path, phase, *, cell=None, shift=None, occ=None):
    """CIF の値をそのまま「精密化後」とした結果 (指定した値だけ差し替える)。"""
    from tsumugin.autorietveld.cif_normalize import read_structure_cif

    s = read_structure_cif(path)
    coords = {at.label: (at.x, at.y, at.z) for at in s.atoms}
    for label, xyz in (shift or {}).items():
        coords[label] = xyz
    occupancy = {at.label: at.occ for at in s.atoms}
    occupancy.update(occ or {})
    return SimpleNamespace(
        refined_cells={phase: cell or (s.a, s.b, s.c, s.alpha, s.beta, s.gamma)},
        atom_coords={phase: coords},
        atom_occupancy={phase: occupancy},
    ), s


@pytest.fixture
def nacl(tmp_path):
    return _write_cif(tmp_path, "nacl", "Fm-3m", 5.64, None, ["Na", "Cl"],
                      [[0, 0, 0], [0.5, 0.5, 0.5]])


@pytest.fixture
def rutile(tmp_path):
    return _write_cif(tmp_path, "rutile", "P4_2/mnm", 4.594, 2.959, ["Ti", "O"],
                      [[0, 0, 0], [0.3053, 0.3053, 0]])


@pytest.mark.parametrize("fixture", ["nacl", "rutile"])
def test_correct_structures_pass_every_check(fixture, request):
    path = request.getfixturevalue(fixture)
    result, _ = _result_from_cif(path, "P")
    got = crystal_chemistry("P", path, result)
    assert {name: got[name][0] for name in (*CHEMISTRY_CHECKS, "crystal_chemistry")} == {
        name: Check.PASS for name in (*CHEMISTRY_CHECKS, "crystal_chemistry")
    }, {k: dict(v[1].detail) for k, v in got.items()}


def test_a_collapsed_cell_fails_short_contact_and_gii(nacl):
    result, _ = _result_from_cif(nacl, "P", cell=(3.6, 3.6, 3.6, 90.0, 90.0, 90.0))
    got = crystal_chemistry("P", nacl, result)
    assert got["short_contact"][0] is Check.FAIL
    assert got["bvs_gii"][0] is Check.FAIL
    assert got["crystal_chemistry"][0] is Check.FAIL


def test_a_misplaced_oxygen_fails_bond_valence(rutile):
    """ルチルの O を x=0.20 へずらす — Rwp では見えうるが結合原子価は大きく崩れる。"""
    result, s = _result_from_cif(rutile, "P")
    o_label = next(at.label for at in s.atoms if at.type_symbol.startswith("O"))
    result.atom_coords["P"][o_label] = (0.20, 0.20, 0.0)
    got = crystal_chemistry("P", rutile, result)
    assert got["bvs_gii"][0] is Check.FAIL


def test_refined_occupancy_that_breaks_charge_balance_fails(nacl):
    result, s = _result_from_cif(nacl, "P")
    na = next(at.label for at in s.atoms if at.type_symbol.startswith("Na"))
    result.atom_occupancy["P"][na] = 0.6
    got = crystal_chemistry("P", nacl, result)
    assert got["charge_neutrality"][0] is Check.FAIL


def test_a_missing_atom_in_the_result_is_unevaluated_not_pass(nacl):
    result, s = _result_from_cif(nacl, "P")
    del result.atom_coords["P"][s.atoms[0].label]
    got = crystal_chemistry("P", nacl, result)
    assert all(got[name][0] is Check.UNEVALUATED for name in CHEMISTRY_CHECKS)
    assert got["crystal_chemistry"][0] is Check.UNEVALUATED
    # 理由はどの原子が無いかを名指す (③ が「なぜ検査できなかったか」を報告できる)
    assert "LookupError" in got["short_contact"][1].detail["reason"]
    assert s.atoms[0].label in got["short_contact"][1].detail["reason"]


def test_an_unreadable_structure_is_unevaluated(tmp_path):
    got = crystal_chemistry("P", str(tmp_path / "missing.cif"), SimpleNamespace(
        refined_cells={}, atom_coords={}, atom_occupancy={}))
    assert got["crystal_chemistry"][0] is Check.UNEVALUATED
    assert "structure_unavailable" in got["short_contact"][1].detail["reason"]


def test_without_pymatgen_every_check_is_unevaluated(nacl, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "pymatgen" or name.startswith("pymatgen."):
            raise ImportError("no pymatgen")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result, _ = _result_from_cif(nacl, "P")
    got = crystal_chemistry("P", nacl, result)
    assert all(got[name][0] is Check.UNEVALUATED for name in (*CHEMISTRY_CHECKS,
                                                               "crystal_chemistry"))


def test_mixed_occupancy_sites_are_evaluated_not_crashed(tmp_path):
    """混合占有サイト (garnet の Fe/Al 型) でも結合原子価和を計算する — pymatgen の
    ``calculate_bv_sum_unordered`` は近接原子の型の違いで AttributeError になり、実データ (T2 garnet)
    で bvs_gii が常に unevaluated だった。"""
    path = _write_cif(tmp_path, "mixed", "P4_2/mnm", 4.65, 3.03,
                      [{"Ti": 0.5, "Sn": 0.5}, "O"], [[0, 0, 0], [0.3053, 0.3053, 0]])
    result, _ = _result_from_cif(path, "P")
    got = crystal_chemistry("P", path, result)
    outcome, witness = got["bvs_gii"]
    assert "AttributeError" not in str(witness.detail.get("reason", ""))
    assert outcome in (Check.PASS, Check.FAIL), dict(witness.detail)


def test_bond_valence_sum_matches_pymatgen_on_ordered_sites(rutile):
    """自前の和は順序サイトでは pymatgen の ``calculate_bv_sum`` と一致する (式の取り違えの検出)。"""
    from pymatgen.analysis.bond_valence import calculate_bv_sum
    from pymatgen.io.cif import CifParser

    from tsumugin.claims.chemistry import _bv_sum

    s = CifParser(rutile).parse_structures(primitive=False)[0]
    for site in s:
        nn = s.get_neighbors(site, 3.5)
        assert _bv_sum(site, nn) == pytest.approx(calculate_bv_sum(site, nn), rel=1e-9)


def test_a_mixed_site_sum_is_the_occupancy_weighted_mean_of_its_species(tmp_path):
    """Ti0.5Sn0.5 サイトの結合原子価和 = 0.5 × (Ti だけ) + 0.5 × (Sn だけ)。"""
    from pymatgen.io.cif import CifParser

    from tsumugin.claims.chemistry import _bv_sum

    path = _write_cif(tmp_path, "mixed", "P4_2/mnm", 4.65, 3.03,
                      [{"Ti": 0.5, "Sn": 0.5}, "O"], [[0, 0, 0], [0.3053, 0.3053, 0]])
    s = CifParser(path).parse_structures(primitive=False)[0]
    i = next(k for k, site in enumerate(s) if not site.is_ordered)
    mixed = _bv_sum(s[i], s.get_neighbors(s[i], 3.5))
    pure = []
    for el in ("Ti", "Sn"):
        t = s.copy()
        t.replace(i, el)
        pure.append(_bv_sum(t[i], t.get_neighbors(t[i], 3.5)))
    assert mixed == pytest.approx(0.5 * pure[0] + 0.5 * pure[1], rel=1e-9)
