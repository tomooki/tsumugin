"""TASK-0703: check_validity — 物理的妥当性ゲート (GSAS 非依存)。"""

from __future__ import annotations

from tsumugin.autorietveld.validity import check_validity


def _good_kwargs():
    return dict(
        refined_cells={"fap": (9.3719, 9.3719, 6.8859, 90.0, 90.0, 120.0)},
        reference_cells={"fap": (9.3717, 9.3717, 6.8859, 90.0, 90.0, 120.0)},
        uiso={"fap": [0.006, 0.005, 0.004]},
        occupancies={"fap": [1.0, 1.0]},
        phase_fractions=None,
        converged=True,
    )


def test_all_good_passes():
    rep = check_validity(**_good_kwargs())
    assert rep.passed
    assert all(ok for _, ok, _ in rep.checks)


def test_lattice_out_of_tolerance_fails():
    kw = _good_kwargs()
    kw["refined_cells"] = {"fap": (9.60, 9.60, 6.8859, 90.0, 90.0, 120.0)}  # +2.4% off
    rep = check_validity(**kw)
    assert not rep.passed
    assert any(name.startswith("lattice") and not ok for name, ok, _ in rep.checks)


def test_negative_uiso_fails():
    kw = _good_kwargs()
    kw["uiso"] = {"fap": [0.006, -0.001, 0.004]}  # 明確に負 (< -uiso_neg_tol)
    rep = check_validity(**kw)
    assert not rep.passed
    assert any("uiso" in name and not ok for name, ok, _ in rep.checks)


def test_fixed_zero_and_tiny_negative_uiso_pass():
    # L9 回帰: 未精密化で 0 の Uiso / 数値ノイズの微小負 (>= -uiso_neg_tol) は許容
    kw = _good_kwargs()
    kw["uiso"] = {"fap": [0.0, -5e-5, 0.006]}
    rep = check_validity(**kw)
    assert rep.passed, [c for c in rep.checks if not c[1]]


def test_uiso_above_max_fails():
    kw = _good_kwargs()
    kw["uiso"] = {"fap": [0.006, 0.25]}  # > 0.1
    rep = check_validity(**kw)
    assert not rep.passed


def test_occupancy_out_of_range_fails():
    kw = _good_kwargs()
    kw["occupancies"] = {"fap": [1.2, 0.9]}
    rep = check_validity(**kw)
    assert not rep.passed
    assert any("occupancy" in name and not ok for name, ok, _ in rep.checks)


def test_phase_fraction_sum_constraint():
    kw = _good_kwargs()
    kw["refined_cells"] = {
        "nac": (10.25, 10.25, 10.25, 90, 90, 90),
        "caf2": (5.46, 5.46, 5.46, 90, 90, 90),
    }
    kw["reference_cells"] = {
        "nac": (10.25, 10.25, 10.25, 90, 90, 90),
        "caf2": (5.46, 5.46, 5.46, 90, 90, 90),
    }
    kw["uiso"] = {"nac": [0.01], "caf2": [0.01]}
    kw["occupancies"] = {"nac": [1.0], "caf2": [1.0]}
    kw["phase_fractions"] = [0.9, 0.11]  # 和 1.01 → 許容内
    rep = check_validity(**kw)
    assert rep.passed
    kw["phase_fractions"] = [0.9, 0.5]  # 和 1.4 → 逸脱
    rep2 = check_validity(**kw)
    assert not rep2.passed
    assert any("fraction" in name and not ok for name, ok, _ in rep2.checks)


def test_phase_fraction_with_nan_fails_not_skipped():
    # 部分抽出 (相分率の一部が NaN) は和検査を skip せず fail させる (再レビュー指摘)
    kw = _good_kwargs()
    kw["phase_fractions"] = [0.6, float("nan")]  # 2 相分の長さは保つが 1 相が NaN
    rep = check_validity(**kw)
    assert not rep.passed
    assert any("fraction" in name and not ok for name, ok, _ in rep.checks)


def test_non_converged_produces_warning_but_not_hard_fail():
    kw = _good_kwargs()
    kw["converged"] = False
    rep = check_validity(**kw)
    assert rep.warnings
    assert any("converg" in w.lower() for w in rep.warnings)
