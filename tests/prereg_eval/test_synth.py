"""P0 §6: 合成ケース (S-dev / S-eval) の生成器の numpy の核 — 除外・雑音・欠陥の登録・manifest。"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.prereg_eval.synth import (
    DEFECTS,
    MISMATCHES,
    CaseManifest,
    DefectSpec,
    PhaseSource,
    add_counting_noise,
    check_set_mismatch_fraction,
    composition_fractions,
    excluded_reason,
    sample_defect,
)


# --- 除外 (P0 §6.1) --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "formula",
    ["Ca5 (P O4)3 F", "Ca5P3O12F", "Ca Te O3", "Ca Te O3 (H2 O)", "Pb S O4", "Na2 Ca3 Al2 F14", "Ca F2",
     "Si O2", "Ca C O3", "Al2 O3"],
)
def test_holdout_and_gate_compounds_are_refused(formula):
    assert excluded_reason(formula) is not None


@pytest.mark.parametrize("formula", ["Zn O", "Fe S2", "Mg2 Si O4", "Ti O2", "Na Cl", "Ca F3", "Al O"])
def test_other_compounds_are_allowed(formula):
    assert excluded_reason(formula) is None


def test_composition_ignores_hydrogen_and_scales():
    assert composition_fractions("Ca Te O3 (H2 O)") == pytest.approx({"Ca": 1 / 6, "Te": 1 / 6, "O": 4 / 6})
    assert composition_fractions("Ca2 Te2 O6") == composition_fractions("CaTeO3")


def test_unparseable_formula_is_refused_not_allowed():
    # 解釈できない式は「除外に当たらない」とせず拒否する (黙って hold-out の化合物を通さない)
    assert excluded_reason("(Mg,Fe)2 Si O4") is not None


# --- 雑音 (P0 §6.2) --------------------------------------------------------------------------


def test_counting_noise_is_poisson_scaled_and_reproducible():
    ycalc = np.array([0.0, 1.0, 5.0, 10.0])
    a = add_counting_noise(ycalc, max_counts=1e4, background=50.0, seed=7)
    b = add_counting_noise(ycalc, max_counts=1e4, background=50.0, seed=7)
    assert np.array_equal(a.y, b.y) and np.array_equal(a.esd, np.sqrt(np.maximum(a.y, 1.0)))
    assert a.expected.max() == pytest.approx(1e4 + 50.0)
    assert np.all(a.y >= 0) and np.all(a.y == np.round(a.y))


def test_esd_has_a_floor_of_one_count():
    y = add_counting_noise(np.array([0.0, 0.0, 1.0]), max_counts=1e4, background=0.0, seed=0)
    assert y.y[0] == 0.0 and y.esd[0] == 1.0


@pytest.mark.parametrize("bad", [5e3, 1e6])
def test_only_registered_count_levels(bad):
    with pytest.raises(ValueError):
        add_counting_noise(np.ones(3), max_counts=bad, background=10.0, seed=0)


# --- 欠陥と不一致の登録 (P0 §6.3) ------------------------------------------------------------


def test_all_ten_registered_defects_have_expectations():
    assert sorted(DEFECTS) == list(range(1, 11))
    for spec in DEFECTS.values():
        assert spec.expected  # 期待する検出器の結果は登録の時点で決まっている
    assert DEFECTS[4].low == 0.2 and DEFECTS[4].high == 0.4  # Å
    assert DEFECTS[5].low == 0.02 and DEFECTS[5].high == 0.10  # wt 分率
    assert DEFECTS[6].low == 0.01 and DEFECTS[6].high == 0.03  # 軸ごと
    assert DEFECTS[7].choices == (1.0, 3.0)  # × Δ_zero
    assert DEFECTS[10].choices == (0.8,)  # March–Dollase r


def test_sample_defect_stays_in_range_and_is_seeded():
    rng1, rng2 = np.random.default_rng(3), np.random.default_rng(3)
    for k, spec in DEFECTS.items():
        a = sample_defect(k, rng1)
        assert a == sample_defect(k, rng2)
        if spec.choices:
            assert a in spec.choices
        elif spec.low is not None:
            assert spec.low <= a <= spec.high


def test_mismatches_are_registered():
    assert set(MISMATCHES) == {"asymmetry", "kalpha2_ratio", "impurity_peak", "amorphous_hump"}


def test_at_least_half_of_a_set_carries_a_mismatch():
    def m(mis):
        return CaseManifest(case_id="c", case_set="S-dev", phases=(), instrument="lab_bb", max_counts=1e4,
                            seed=0, defects=(), mismatches=mis, expected=("none",))
    assert check_set_mismatch_fraction([m(("asymmetry",)), m(())]) is None
    assert check_set_mismatch_fraction([m(("asymmetry",)), m(()), m(())]) is not None


# --- manifest (P0 §6.4) ----------------------------------------------------------------------


def _phase():
    return PhaseSource(db="COD", entry_id="9008877", revision="123", sha256="ab" * 32, license="CC0",
                       phase_name="ZnO", formula="Zn O", wt_fraction=1.0)


def test_manifest_requires_expectations_before_the_pattern_exists():
    with pytest.raises(ValueError, match="expected"):
        CaseManifest(case_id="c", case_set="S-dev", phases=(_phase(),), instrument="lab_bb",
                     max_counts=1e4, seed=0, defects=(), mismatches=(), expected=())


def test_manifest_refuses_excluded_compounds_and_bad_fractions():
    bad = PhaseSource(db="COD", entry_id="1", revision="1", sha256="cd" * 32, license="CC0",
                      phase_name="F", formula="Ca F2", wt_fraction=1.0)
    with pytest.raises(ValueError, match="excluded"):
        CaseManifest(case_id="c", case_set="S-dev", phases=(bad,), instrument="lab_bb", max_counts=1e4,
                     seed=0, defects=(), mismatches=(), expected=("none",))
    two = (_phase(), _phase())
    with pytest.raises(ValueError, match="wt"):
        CaseManifest(case_id="c", case_set="S-dev", phases=two, instrument="lab_bb", max_counts=1e4,
                     seed=0, defects=(), mismatches=(), expected=("none",))


def test_manifest_round_trips_and_records_the_pattern_hash():
    m = CaseManifest(case_id="c", case_set="S-dev", phases=(_phase(),), instrument="sync_ds", max_counts=1e5,
                     seed=11, defects=(DefectSpec(4, "ZnO.O1", 0.3, "truth", "start"),),
                     mismatches=("asymmetry",), expected=("chemistry fail or recovered",))
    done = m.with_pattern(np.array([[1.0, 2.0, 1.4]]))
    assert done.pattern_sha256 and m.pattern_sha256 == ""
    assert CaseManifest.from_dict(done.to_dict()) == done
