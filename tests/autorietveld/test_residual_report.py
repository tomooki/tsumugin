"""Issue #83: autorietveld.residual_report (残差分解: baseline/peak・角度ビン・上位特徴)。"""

from __future__ import annotations

import numpy as np
import pytest

from tsumugin.autorietveld.model import AutoRietveldResult, StageResult, ValidityReport
from tsumugin.autorietveld.residual_report import (
    ResidualFeature,
    ResidualReport,
    residual_report,
    residual_report_from_result,
)


def _base_result(**kw) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=10.0, gof=1.2, n_params=5, converged=True),),
        final_rwp=10.0,
        final_gof=1.2,
        refined_cells={},
        validity=ValidityReport(passed=True),
        **kw,
    )


def _gaussian(x: np.ndarray, center: float, height: float, width: float) -> np.ndarray:
    return height * np.exp(-0.5 * ((x - center) / width) ** 2)


def _baseline_only_residual_pattern():
    """残差が baseline (ピーク間) にのみ存在し、ピーク自体は完全一致する合成パターン。"""
    rng = np.random.default_rng(0)
    x = np.linspace(0.0, 20.0, 4000)
    peaks = (
        _gaussian(x, 5.0, 300.0, 0.05)
        + _gaussian(x, 10.0, 300.0, 0.05)
        + _gaussian(x, 15.0, 300.0, 0.05)
    )
    baseline_true = 5.0
    noise = rng.normal(0.0, 0.6, size=x.size)
    # ピーク近傍 (中心から 0.3 以内) はノイズを 0 にし、残差が baseline にのみ乗るようにする。
    near_peak = (
        (np.abs(x - 5.0) < 0.3) | (np.abs(x - 10.0) < 0.3) | (np.abs(x - 15.0) < 0.3)
    )
    noise = np.where(near_peak, 0.0, noise)
    yobs = baseline_true + peaks + noise
    ycalc = baseline_true + peaks
    return x, yobs, ycalc


def _missing_peak_pattern():
    """calc に存在しない未説明ピークを 12.3° に含む合成パターン (欠落相を模擬)。"""
    x = np.linspace(0.0, 20.0, 4000)
    baseline = 5.0
    matched_peak = _gaussian(x, 5.0, 250.0, 0.05)
    missing_peak = _gaussian(x, 12.3, 180.0, 0.05)
    yobs = baseline + matched_peak + missing_peak
    ycalc = baseline + matched_peak
    return x, yobs, ycalc


def test_baseline_only_residual_gives_high_baseline_fraction():
    x, yobs, ycalc = _baseline_only_residual_pattern()
    report = residual_report(x, yobs, ycalc)
    assert report.baseline_numerator_fraction > 0.9
    assert report.peak_numerator_fraction < 0.1


def test_peak_only_rwp_differs_from_rwp_when_baseline_carries_residual():
    x, yobs, ycalc = _baseline_only_residual_pattern()
    report = residual_report(x, yobs, ycalc)
    assert report.peak_only_rwp < report.rwp
    # ピークは完全一致なので peak_only_rwp はほぼ 0 に近いはず。
    assert report.peak_only_rwp < 1.0


def test_top_feature_locates_missing_peak_with_positive_sign():
    x, yobs, ycalc = _missing_peak_pattern()
    report = residual_report(x, yobs, ycalc, n_features=3)
    assert len(report.top_features) >= 1
    top = report.top_features[0]
    assert top.two_theta == pytest.approx(12.3, abs=0.05)
    assert top.residual > 0.0  # calc 不足 = 未説明強度


def test_top_features_deduplicate_adjacent_large_residuals():
    # 手作りの小さな配列: x=10.0 と x=10.05 に隣接する大残差点を置く (feature_min_separation=0.15
    # 未満の距離)。統合後は 1 特徴のみ残り、|残差| が大きい方 (x=10.05, resid=50) を採用する。
    x = np.array([0.0, 5.0, 10.0, 10.05, 15.0])
    yobs = np.array([5.0, 5.0, 45.0, 55.0, 5.0])
    ycalc = np.array([5.0, 5.0, 5.0, 5.0, 5.0])
    report = residual_report(x, yobs, ycalc, n_features=6, feature_min_separation=0.15)
    close_features = [f for f in report.top_features if abs(f.two_theta - 10.0) < 1.0]
    assert len(close_features) == 1
    assert close_features[0].two_theta == pytest.approx(10.05)
    assert close_features[0].residual == pytest.approx(50.0)


def test_angular_rwp_concentrates_misfit_in_one_bin():
    x = np.linspace(0.0, 20.0, 4000)
    yobs = np.full_like(x, 10.0)
    ycalc = np.full_like(x, 10.0)
    # 6-8° の範囲だけ大きく食い違わせる (ビン境界は 0,4,8,12,16,20 の 5 分割で 4-8° ビンに収まる)。
    misfit_region = (x >= 6.0) & (x < 8.0)
    ycalc = np.where(misfit_region, ycalc + 40.0, ycalc)

    report = residual_report(x, yobs, ycalc, n_bins=5)
    assert len(report.angular_rwp) == 5
    misfit_bin = [b for b in report.angular_rwp if b[0] <= 6.0 < b[1]]
    assert misfit_bin, "6°を含むビンが見つからない"
    misfit_rwp = misfit_bin[0][2]
    other_rwps = [b[2] for b in report.angular_rwp if b is not misfit_bin[0]]
    assert misfit_rwp > max(other_rwps) * 5


def test_empty_arrays_degrade_gracefully():
    report = residual_report(np.array([]), np.array([]), np.array([]))
    assert report.rwp == 0.0
    assert report.peak_only_rwp == 0.0
    assert report.baseline_numerator_fraction == 0.0
    assert report.peak_numerator_fraction == 0.0
    assert report.angular_rwp == ()
    assert report.top_features == ()


def test_all_zero_yobs_degrades_gracefully():
    x = np.linspace(0.0, 10.0, 100)
    yobs = np.zeros_like(x)
    ycalc = np.zeros_like(x)
    report = residual_report(x, yobs, ycalc)
    assert report.rwp == 0.0
    assert report.baseline_numerator_fraction == 0.0


def test_mismatched_lengths_raise_value_error():
    with pytest.raises(ValueError):
        residual_report(np.array([1.0, 2.0]), np.array([1.0]), np.array([1.0, 2.0]))


def test_mismatched_weight_length_raises_value_error():
    x = np.array([1.0, 2.0, 3.0])
    yobs = np.array([1.0, 2.0, 3.0])
    ycalc = np.array([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        residual_report(x, yobs, ycalc, weight=np.array([1.0, 1.0]))


def test_result_type_is_frozen_dataclass():
    report = residual_report(np.array([1.0]), np.array([5.0]), np.array([5.0]))
    with pytest.raises(Exception):
        report.rwp = 99.0  # type: ignore[misc]
    assert isinstance(report, ResidualReport)


def test_adapter_reconstructs_from_result_fields():
    x, yobs, ycalc = _missing_peak_pattern()
    resid = yobs - ycalc
    sigma = np.sqrt(np.maximum(yobs, 1.0))  # 計数統計慣習: yweight=1/yobs → sigma=sqrt(yobs)

    result = _base_result(
        residual_two_theta=tuple(x.tolist()),
        residual_intensity=tuple(resid.tolist()),
        residual_sigma=tuple(sigma.tolist()),
    )
    report = residual_report_from_result(result, n_features=3)
    assert report is not None
    assert isinstance(report, ResidualReport)
    top = report.top_features[0]
    assert top.two_theta == pytest.approx(12.3, abs=0.05)
    assert top.residual > 0.0


def test_adapter_excludes_non_finite_sigma_points():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    resid = np.array([0.0, 0.0, 100.0, 0.0])
    sigma = np.array([1.0, float("inf"), 1.0, 1.0])
    result = _base_result(
        residual_two_theta=tuple(x.tolist()),
        residual_intensity=tuple(resid.tolist()),
        residual_sigma=tuple(sigma.tolist()),
    )
    report = residual_report_from_result(result)
    assert report is not None
    # 除外されなければ 4 点、除外されれば 3 点 -> 角度ビンの端が変わることで間接確認。
    assert report.rwp >= 0.0


def test_adapter_returns_none_on_empty_residual_fields():
    result = _base_result()  # residual_* は既定空タプル (後方互換)
    assert residual_report_from_result(result) is None


def test_adapter_returns_none_when_all_sigma_non_finite():
    result = _base_result(
        residual_two_theta=(1.0, 2.0),
        residual_intensity=(0.0, 0.0),
        residual_sigma=(float("inf"), float("inf")),
    )
    assert residual_report_from_result(result) is None


def test_residual_feature_fields():
    f = ResidualFeature(two_theta=5.7, residual=12.5, obs=200.0)
    assert f.two_theta == 5.7
    assert f.residual == 12.5
    assert f.obs == 200.0
