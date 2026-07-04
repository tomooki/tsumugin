"""TASK-0052 nested/calibration の契約テスト (較正評価ユーティリティ)。

検証:
- CalibrationSample / ReliabilityBin / CalibrationReport 生成・frozen (REQ-016/017/106)
- reliability_diagram: 既知サンプルの手計算ビン (下端昇順・空ビン count=0 保持)、
  n_bins 指定、p=1.0 が最終ビン、mean_predicted / observed_frequency (REQ-016/017/EDGE-012)
- expected_calibration_error: 完全較正で ECE≈0・既知不整合で手計算一致・空サンプル 0.0 (REQ-016/017)
- calibrate_by_backend: bic+nested 混在を 2 系列に分離・backend 名昇順・
  各系列 report の backend/n_samples/probability_semantics・nested 別系列 (REQ-016/106/EDGE-012)
- 決定論 (2 回ビット同一・ビン順/backend 順固定) (NFR-102/REQ-402)
- コア (numpy) のみで import できる (REQ-401/403)
"""

from __future__ import annotations

import dataclasses

import pytest


def test_import_core_only():
    import tsumugin.nested.calibration as calibration  # noqa: F401


# ------------------------------------------------------------------
# dataclass 生成・frozen
# ------------------------------------------------------------------


def test_calibration_sample_defaults_and_frozen():
    from tsumugin.nested.calibration import CalibrationSample

    s = CalibrationSample(predicted_probability=0.8, correct=True)
    assert s.predicted_probability == pytest.approx(0.8)
    assert s.correct is True
    assert s.backend == "bic"

    s2 = CalibrationSample(predicted_probability=0.3, correct=False, backend="nested")
    assert s2.backend == "nested"

    with pytest.raises(dataclasses.FrozenInstanceError):
        s.predicted_probability = 0.1  # type: ignore[misc]


def test_reliability_bin_frozen():
    from tsumugin.nested.calibration import ReliabilityBin

    b = ReliabilityBin(
        lower=0.0, upper=0.1, mean_predicted=0.05, observed_frequency=0.0, count=0
    )
    assert b.lower == pytest.approx(0.0)
    assert b.upper == pytest.approx(0.1)
    assert b.count == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.count = 3  # type: ignore[misc]


def test_calibration_report_defaults_and_frozen():
    from tsumugin.nested.calibration import CalibrationReport

    r = CalibrationReport(backend="bic", bins=(), ece=0.0, n_samples=0)
    assert r.backend == "bic"
    assert r.bins == ()
    assert r.probability_semantics == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.ece = 1.0  # type: ignore[misc]


# ------------------------------------------------------------------
# reliability_diagram
# ------------------------------------------------------------------


def test_reliability_diagram_bins_sorted_and_empty_preserved():
    from tsumugin.nested.calibration import CalibrationSample, reliability_diagram

    # n_bins=5 -> 幅 0.2 のビン 5 本 (下端 0.0/0.2/0.4/0.6/0.8)
    # ビン0 [0.0,0.2): p=0.1(F) → obs=0, mean=0.1
    # ビン3 [0.6,0.8): p=0.7(T), p=0.7(F) → obs=0.5, mean=0.7
    # 他は空 (count=0)
    samples = [
        CalibrationSample(0.1, False),
        CalibrationSample(0.7, True),
        CalibrationSample(0.7, False),
    ]
    bins = reliability_diagram(samples, n_bins=5)
    assert len(bins) == 5
    lowers = [b.lower for b in bins]
    assert lowers == sorted(lowers)
    assert lowers == pytest.approx([0.0, 0.2, 0.4, 0.6, 0.8])
    uppers = [b.upper for b in bins]
    assert uppers == pytest.approx([0.2, 0.4, 0.6, 0.8, 1.0])

    # ビン0
    assert bins[0].count == 1
    assert bins[0].mean_predicted == pytest.approx(0.1)
    assert bins[0].observed_frequency == pytest.approx(0.0)
    # ビン1/2 空
    assert bins[1].count == 0
    assert bins[2].count == 0
    # ビン3
    assert bins[3].count == 2
    assert bins[3].mean_predicted == pytest.approx(0.7)
    assert bins[3].observed_frequency == pytest.approx(0.5)
    # ビン4 空
    assert bins[4].count == 0


def test_reliability_diagram_default_n_bins_is_10():
    from tsumugin.nested.calibration import CalibrationSample, reliability_diagram

    bins = reliability_diagram([CalibrationSample(0.55, True)])
    assert len(bins) == 10
    # p=0.55 は floor(0.55*10)=5 → ビン5 [0.5,0.6)
    assert bins[5].count == 1
    assert bins[5].mean_predicted == pytest.approx(0.55)
    assert bins[5].observed_frequency == pytest.approx(1.0)


def test_reliability_diagram_p_one_in_last_bin():
    from tsumugin.nested.calibration import CalibrationSample, reliability_diagram

    bins = reliability_diagram([CalibrationSample(1.0, True)], n_bins=10)
    # p=1.0 は最終ビンに含める (floor(1.0*10)=10 を clamp)
    assert bins[-1].count == 1
    assert bins[-1].mean_predicted == pytest.approx(1.0)
    assert bins[-1].observed_frequency == pytest.approx(1.0)
    assert sum(b.count for b in bins) == 1


def test_reliability_diagram_empty_bins_have_defined_values():
    from tsumugin.nested.calibration import reliability_diagram

    bins = reliability_diagram([], n_bins=4)
    assert len(bins) == 4
    for b in bins:
        assert b.count == 0
        assert b.mean_predicted == pytest.approx(0.0)
        assert b.observed_frequency == pytest.approx(0.0)


def test_reliability_diagram_deterministic():
    from tsumugin.nested.calibration import CalibrationSample, reliability_diagram

    samples = [
        CalibrationSample(0.1, False),
        CalibrationSample(0.9, True),
        CalibrationSample(0.9, False),
    ]
    assert reliability_diagram(samples, n_bins=10) == reliability_diagram(
        samples, n_bins=10
    )


# ------------------------------------------------------------------
# expected_calibration_error
# ------------------------------------------------------------------


def test_ece_empty_is_zero():
    from tsumugin.nested.calibration import expected_calibration_error

    assert expected_calibration_error([]) == pytest.approx(0.0)


def test_ece_perfect_calibration_is_zero():
    from tsumugin.nested.calibration import CalibrationSample, expected_calibration_error

    # 各ビンで予測確率 = 観測正解率 になるよう構成
    # ビン [0.0,0.1): p=0.05, 10 サンプル中 0 正解 → obs=0.0 ≈ conf 0.05 ... 完全較正のため
    # ビン [0.9,1.0): p=0.95, 20 サンプル中 全正解 → obs=1.0
    # ここでは conf=obs となるサンプルを厳密に組む: p=0.5 で half true / half false。
    samples = [CalibrationSample(0.5, True), CalibrationSample(0.5, False)]
    # ビン5: mean=0.5, obs=0.5 → |0.5-0.5|=0 → ECE=0
    assert expected_calibration_error(samples, n_bins=10) == pytest.approx(0.0)


def test_ece_known_mismatch():
    from tsumugin.nested.calibration import CalibrationSample, expected_calibration_error

    # 全 4 サンプル。
    # ビンA: p=0.2, 2 サンプル, 全正解 → mean=0.2, obs=1.0 → |1.0-0.2|=0.8, weight=2/4
    # ビンB: p=0.8, 2 サンプル, 全不正解 → mean=0.8, obs=0.0 → |0.0-0.8|=0.8, weight=2/4
    # ECE = 0.5*0.8 + 0.5*0.8 = 0.8
    samples = [
        CalibrationSample(0.2, True),
        CalibrationSample(0.2, True),
        CalibrationSample(0.8, False),
        CalibrationSample(0.8, False),
    ]
    assert expected_calibration_error(samples, n_bins=10) == pytest.approx(0.8)


def test_ece_matches_diagram_definition():
    from tsumugin.nested.calibration import (
        CalibrationSample,
        expected_calibration_error,
        reliability_diagram,
    )

    samples = [
        CalibrationSample(0.15, True),
        CalibrationSample(0.15, False),
        CalibrationSample(0.85, True),
    ]
    bins = reliability_diagram(samples, n_bins=10)
    n = len(samples)
    manual = sum(
        (b.count / n) * abs(b.observed_frequency - b.mean_predicted) for b in bins
    )
    assert expected_calibration_error(samples, n_bins=10) == pytest.approx(manual)


# ------------------------------------------------------------------
# calibrate_by_backend
# ------------------------------------------------------------------


def test_calibrate_by_backend_splits_series_sorted():
    from tsumugin.nested.calibration import CalibrationSample, calibrate_by_backend

    samples = [
        CalibrationSample(0.7, True, backend="nested"),
        CalibrationSample(0.3, False, backend="bic"),
        CalibrationSample(0.6, True, backend="bic"),
        CalibrationSample(0.9, False, backend="nested"),
    ]
    reports = calibrate_by_backend(samples, n_bins=10)
    assert len(reports) == 2
    # backend 名昇順: bic < nested
    assert [r.backend for r in reports] == ["bic", "nested"]

    bic_report = reports[0]
    nested_report = reports[1]
    assert bic_report.n_samples == 2
    assert nested_report.n_samples == 2
    # 各系列にビンが構成されている
    assert len(bic_report.bins) == 10
    assert len(nested_report.bins) == 10


def test_calibrate_by_backend_probability_semantics():
    from tsumugin.nested.calibration import CalibrationSample, calibrate_by_backend

    samples = [
        CalibrationSample(0.6, True, backend="bic"),
        CalibrationSample(0.6, True, backend="nested"),
    ]
    reports = {r.backend: r for r in calibrate_by_backend(samples)}
    assert "BIC" in reports["bic"].probability_semantics
    assert reports["bic"].probability_semantics != ""
    assert "logZ" in reports["nested"].probability_semantics
    assert reports["nested"].probability_semantics != ""


def test_calibrate_by_backend_nested_separated_edge012():
    from tsumugin.nested.calibration import CalibrationSample, calibrate_by_backend

    # nested 系列が別 report として分離される (EDGE-012)
    samples = [
        CalibrationSample(0.2, True, backend="bic"),
        CalibrationSample(0.8, True, backend="nested"),
    ]
    reports = calibrate_by_backend(samples)
    backends = [r.backend for r in reports]
    assert "bic" in backends
    assert "nested" in backends
    # 混ざっていない: 各 report は自系列のサンプル数のみ
    for r in reports:
        assert r.n_samples == 1


def test_calibrate_by_backend_ece_per_series():
    from tsumugin.nested.calibration import (
        CalibrationSample,
        calibrate_by_backend,
        expected_calibration_error,
    )

    samples = [
        CalibrationSample(0.2, True, backend="bic"),
        CalibrationSample(0.2, True, backend="bic"),
        CalibrationSample(0.8, False, backend="nested"),
    ]
    reports = {r.backend: r for r in calibrate_by_backend(samples)}
    bic_only = [s for s in samples if s.backend == "bic"]
    assert reports["bic"].ece == pytest.approx(
        expected_calibration_error(bic_only)
    )


def test_calibrate_by_backend_empty():
    from tsumugin.nested.calibration import calibrate_by_backend

    assert calibrate_by_backend([]) == ()


def test_calibrate_by_backend_deterministic():
    from tsumugin.nested.calibration import CalibrationSample, calibrate_by_backend

    samples = [
        CalibrationSample(0.7, True, backend="nested"),
        CalibrationSample(0.3, False, backend="bic"),
        CalibrationSample(0.6, True, backend="bic"),
    ]
    assert calibrate_by_backend(samples) == calibrate_by_backend(samples)


# ------------------------------------------------------------------
# re-export
# ------------------------------------------------------------------


def test_reexport_from_nested_package():
    from tsumugin.nested import (  # noqa: F401
        CalibrationReport,
        CalibrationSample,
        ReliabilityBin,
        calibrate_by_backend,
        expected_calibration_error,
        reliability_diagram,
    )
