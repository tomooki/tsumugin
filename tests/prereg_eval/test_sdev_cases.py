"""合成 `S-dev` の事例の定義が P0 §6 を満たす (型・欠陥・不一致の割合) ことと、事例の組み立て。

構造はテスト内の小さな CIF (COD の項目と同じラベル) で代用する — COD の CIF は追跡しない。
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from tsumugin.prereg_eval.synth import DEFECTS, check_set_mismatch_fraction

_DIR = Path(__file__).resolve().parents[2] / "docs" / "benchmark" / "fit-then-judge-synthetic"


def _load(name):
    sys.path.insert(0, str(_DIR))
    try:
        spec = importlib.util.spec_from_file_location(f"_sdev_{name}", _DIR / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = mod  # dataclass は定義したモジュールを sys.modules から引く
        spec.loader.exec_module(mod)
        return mod
    finally:
        sys.path.remove(str(_DIR))


cases = _load("cases")

_HEAD = """data_x
_cell_length_a {a}
_cell_length_b {b}
_cell_length_c {c}
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma {g}
_symmetry_space_group_name_H-M '{sg}'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
_atom_site_U_iso_or_equiv
"""
_CIFS = {
    "ZnO": (dict(a=3.25, b=3.25, c=5.2, g=120, sg="P 63 m c"),
            ["Zn1 Zn 0.3333 0.6667 0 1 0.01", "O1 O 0.3333 0.6667 0.38 1 0.01"]),
    "Mg2SiO4": (dict(a=4.75, b=10.2, c=5.98, g=90, sg="P b n m"),
                ["Mg1 Mg 0 0 0 1 0.01", "Mg2 Mg 0.99 0.28 0.25 1 0.01", "Si1 Si 0.43 0.09 0.25 1 0.01",
                 "O1 O 0.77 0.09 0.25 1 0.01", "O2 O 0.22 0.45 0.25 1 0.01", "O3 O 0.28 0.16 0.03 1 0.01"]),
    "FeS2": (dict(a=5.42, b=5.42, c=5.42, g=90, sg="P a -3"),
             ["Fe1 Fe 0 0 0 1 0.01", "S1 S 0.384 0.384 0.384 1 0.01"]),
    "MgAl2O4": (dict(a=8.08, b=8.08, c=8.08, g=90, sg="F d -3 m"),
                ["Mg1 Mg 0 0 0 1 0.01", "Al1 Al 0.625 0.625 0.625 1 0.01", "O1 O 0.385 0.385 0.385 1 0.01"]),
    "TiO2": (dict(a=4.59, b=4.59, c=2.96, g=90, sg="P 42/m n m"),
             ["Ti Ti 0 0 0 1 0.01", "O O 0.305 0.305 0 1 0.01"]),
}


@pytest.fixture
def cifs(tmp_path):
    out = {}
    for name, (cell, rows) in _CIFS.items():
        p = tmp_path / f"{name}.cif"
        p.write_text(_HEAD.format(**cell) + "\n".join(rows) + "\n", encoding="utf-8")
        out[name] = p
    return out


def test_every_registered_defect_is_used():
    used = {k for c in cases.CASES for k, _ in c.defects}
    assert used == set(DEFECTS)


def test_required_structure_types_are_present():
    compounds = {pd.compound for c in cases.CASES for pd in c.phases}
    assert "ZnO" in compounds  # 極性 (P6₃mc)
    assert {"FeS2", "MgAl2O4"} & compounds  # 結合した特殊位置 (x,x,x)
    assert any(pd.mixed_fe for c in cases.CASES for pd in c.phases)  # 混合占有
    multi = [c for c in cases.CASES if len(c.phases) >= 2]
    assert multi and all(0.01 <= min(pd.wt for pd in c.phases) <= 0.10 for c in multi)  # 副相 1–10 wt%


def test_case_ids_and_seeds_are_unique():
    assert len({c.case_id for c in cases.CASES}) == len(cases.CASES)
    assert len({c.seed for c in cases.CASES}) == len(cases.CASES)


def test_kalpha2_mismatch_only_on_an_instrument_with_kalpha2():
    for c in cases.CASES:
        if "kalpha2_ratio" in c.mismatches:
            assert c.instrument == "lab_bb", c.case_id


def test_every_case_builds_a_valid_manifest_before_any_pattern(cifs, tmp_path):
    gen = _load("generate")
    built = [gen.build_case(c, cifs, tmp_path / "out") for c in cases.CASES]
    manifests = [b["manifest"] for b in built]
    assert check_set_mismatch_fraction(manifests) is None  # 半数以上に不一致
    for b in built:
        m = b["manifest"]
        assert m.expected and m.pattern_sha256 == ""  # 期待する結果は書いてあり、パターンはまだ
        for spec in b["start_phases"]:
            assert Path(spec["structure_path"]).exists()


def test_defects_change_the_start_not_the_truth(cifs, tmp_path):
    gen = _load("generate")
    by = {c.case_id: c for c in cases.CASES}
    b = gen.build_case(by["sdev08_fo_missing_atom"], cifs, tmp_path / "o")
    truth = Path(b["truth_paths"]["Mg2SiO4"]).read_text()
    start = Path(b["start_phases"][0]["structure_path"]).read_text()
    assert "O1 " in truth and "O1 " not in start
    mixed = gen.build_case(by["sdev07_fo_mixed"], cifs, tmp_path / "m")
    assert mixed["start_phases"][0]["mixed_occupancy_groups"] == [["Mg1", "Fe1"], ["Mg2", "Fe2"]]
    missing = gen.build_case(by["sdev11_mix_missing_phase"], cifs, tmp_path / "p")
    assert [p["phase_name"] for p in missing["start_phases"]] == ["ZnO"]  # 欠落相はモデルに入れない
    zero = gen.build_case(by["sdev03_zno_zero"], cifs, tmp_path / "z")
    assert zero["zero_deg"] in (0.01, 0.03)
    frozen = gen.build_case(by["sdev12_mix_minor_frozen"], cifs, tmp_path / "f")
    assert [p["refine_cell"] for p in frozen["start_phases"]] == [True, False]


def test_manifest_records_true_and_starting_values(cifs, tmp_path):
    gen = _load("generate")
    by = {c.case_id: c for c in cases.CASES}
    m = gen.build_case(by["sdev05_fo_displaced"], cifs, tmp_path / "d")["manifest"]
    d = m.defects[0]
    assert d.truth.startswith("O3 O (0.28000") and d.start.startswith("O3 O (") and d.truth != d.start
    m = gen.build_case(by["sdev12_mix_minor_frozen"], cifs, tmp_path / "f")["manifest"]
    assert "frozen" in m.defects[0].start and m.defects[0].truth.startswith("a=5.42000")
