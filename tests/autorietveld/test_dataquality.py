"""Issue #78: autorietveld.dataquality (背景減算検出/2θ上限提案/背景項走査) の numpy コアテスト。"""

from __future__ import annotations

import dataclasses

import numpy as np
import pytest

from tsumugin.autorietveld.dataquality import (
    BackgroundScanReport,
    BackgroundSubtractedReport,
    detect_background_subtracted,
    scan_background_coeffs,
    suggest_two_theta_limit,
)


def _gaussian_peaks(x: np.ndarray, centers, height=100.0, width=0.15) -> np.ndarray:
    y = np.zeros_like(x)
    for c in centers:
        y = y + height * np.exp(-0.5 * ((x - c) / width) ** 2)
    return y


def _parasitic_pattern() -> tuple[np.ndarray, np.ndarray]:
    """試料の信号終端 (18°) の外側に、強い寄生ピーク (26°) が 1 本だけ立つ合成パターン。

    operando セルのハードウェア由来の寄生反射を模擬する (実在する強度なので、除外しなければ
    S/N 判定は正しくこれを信号として拾ってしまう)。
    """
    rng = np.random.default_rng(7)
    x = np.linspace(5.0, 30.0, 5000)
    sample = np.where(
        x < 18.0,
        _gaussian_peaks(x, centers=[7.0, 10.0, 13.0, 16.0], height=200.0, width=0.02),
        0.0,
    )
    parasitic = _gaussian_peaks(x, centers=[26.0], height=200.0, width=0.02)
    y = 5.0 + rng.normal(0.0, 1.0, size=x.size) + sample + parasitic
    return x, y


def _subtracted_pattern() -> tuple[np.ndarray, np.ndarray]:
    """背景減算済みを模擬: ベースラインはほぼ 0 (Poisson ノイズのみ) で構造なし。"""
    rng = np.random.default_rng(0)
    x = np.linspace(10.0, 50.0, 4000)
    peaks = _gaussian_peaks(x, centers=[15.0, 22.0, 30.0, 38.0], height=120.0, width=0.1)
    baseline = 2.0 + rng.normal(0.0, 0.3, size=x.size)
    return x, np.clip(baseline + peaks, 0.1, None)


def _raw_pattern() -> tuple[np.ndarray, np.ndarray]:
    """生データを模擬: 実質的なベースラインがあり低角側で高く高角側で下がる (実背景)。"""
    rng = np.random.default_rng(1)
    x = np.linspace(10.0, 50.0, 4000)
    peaks = _gaussian_peaks(x, centers=[15.0, 22.0, 30.0, 38.0], height=100.0, width=0.1)
    sloping_background = 60.0 - 0.8 * (x - x.min()) + rng.normal(0.0, 3.0, size=x.size)
    return x, np.clip(sloping_background + peaks, 1.0, None)


# --- detect_background_subtracted -----------------------------------------


def test_detect_background_subtracted_true_for_bkg_subtracted_synthetic():
    x, y = _subtracted_pattern()
    esd = np.sqrt(np.maximum(y, 1.0))

    report = detect_background_subtracted(x, y, esd)

    assert isinstance(report, BackgroundSubtractedReport)
    assert report.is_subtracted is True
    assert report.confidence >= 0.5
    assert len(report.reasons) > 0
    assert report.recommendation


def test_detect_background_subtracted_false_for_raw_like_synthetic():
    x, y = _raw_pattern()

    report = detect_background_subtracted(x, y)

    assert report.is_subtracted is False
    assert report.confidence < 0.5


def test_detect_background_subtracted_esd_does_not_inflate_confidence_for_raw():
    """esd=√y は生データでも成立する慣習なので confidence を一切押し上げてはならない。

    生データ合成は h3 (平坦性) のみ発火し 0.32 (=0.8/2.5) となる (この合成の線形背景は
    変動比 0.229 で閾値 0.4 を下回るため)。旧実装では h4 が加わり 0.32→0.51 で判定が
    `is_subtracted=True` に反転していた。ここでは esd を与えても confidence が h1/h2/h3
    のみの値から動かないこと (= h4 が投票に寄与しないこと) を検証する。
    """
    x, y = _raw_pattern()
    esd = np.sqrt(np.maximum(y, 1.0))

    with_esd = detect_background_subtracted(x, y, esd)
    without_esd = detect_background_subtracted(x, y)

    assert with_esd.is_subtracted is False
    assert with_esd.confidence == pytest.approx(without_esd.confidence)
    # esd 起因の誤解を招く根拠が「非減算」レポートに載らないこと
    assert not any("esd" in r for r in with_esd.reasons)


def test_detect_background_subtracted_esd_reason_is_context_only_when_subtracted():
    """減算済み判定時のみ、esd≈√y は判定に不使用である旨を明記した補助情報として付記される。"""
    x, y = _subtracted_pattern()
    esd = np.sqrt(np.maximum(y, 1.0))

    report = detect_background_subtracted(x, y, esd)

    # h1+h2+h3 が全て発火 → confidence は esd 抜きで 1.0
    assert report.confidence == pytest.approx(1.0)
    esd_reasons = [r for r in report.reasons if "esd" in r]
    assert len(esd_reasons) == 1
    assert "判定には不使用" in esd_reasons[0]


def test_detect_background_subtracted_raw_with_esd_is_not_false_positive():
    """回帰: 生データ + esd=√y が「減算済み」と誤判定されないこと。

    h4 を重み 1.0 で投票に含めていた旧実装では、この生データ合成が h3(0.8)+h4(1.0)=1.8/3.5
    = 0.514 ≥ 0.5 となり `is_subtracted=True` に誤反転していた (実測)。h4 を投票から外した
    ことで 0.32 < 0.5 となり正しく False を返す。
    """
    x, y = _raw_pattern()
    esd = np.sqrt(np.maximum(y, 1.0))

    report = detect_background_subtracted(x, y, esd)

    assert report.is_subtracted is False
    assert report.confidence < 0.5


def test_detect_background_subtracted_confidence_identical_with_and_without_esd():
    """esd の有無で confidence が変わらない (投票に寄与しないことの直接確認)。"""
    x, y = _subtracted_pattern()
    esd = np.sqrt(np.maximum(y, 1.0))

    with_esd = detect_background_subtracted(x, y, esd)
    without_esd = detect_background_subtracted(x, y)

    assert with_esd.confidence == pytest.approx(without_esd.confidence)
    assert with_esd.is_subtracted is without_esd.is_subtracted


def test_detect_background_subtracted_is_frozen():
    report = BackgroundSubtractedReport(
        is_subtracted=True,
        confidence=0.8,
        baseline_level=1.0,
        peak_max=100.0,
        reasons=("dummy",),
        recommendation="dummy",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.is_subtracted = False  # type: ignore[misc]


def test_detect_background_subtracted_empty_arrays_do_not_raise():
    report = detect_background_subtracted(np.array([]), np.array([]))
    assert report.is_subtracted is False
    assert report.confidence == pytest.approx(0.0)


def test_detect_background_subtracted_short_arrays_do_not_raise():
    report = detect_background_subtracted(np.array([1.0, 2.0]), np.array([5.0, 6.0]))
    assert isinstance(report, BackgroundSubtractedReport)


def test_detect_background_subtracted_all_zero_y_does_not_raise():
    x = np.linspace(0.0, 10.0, 50)
    y = np.zeros_like(x)
    report = detect_background_subtracted(x, y)
    assert report.is_subtracted is False
    assert report.peak_max == pytest.approx(0.0)


# --- suggest_two_theta_limit ------------------------------------------------


def test_suggest_two_theta_limit_detects_signal_cutoff():
    rng = np.random.default_rng(2)
    x = np.linspace(5.0, 30.0, 5000)
    cutoff = 18.0
    peaks = np.where(
        x < cutoff,
        _gaussian_peaks(x, centers=[7.0, 10.0, 13.0, 16.0], height=200.0, width=0.02),
        0.0,
    )
    noise = rng.normal(0.0, 1.0, size=x.size)
    y = 5.0 + noise + peaks

    limit = suggest_two_theta_limit(x, y, snr_min=5.0, window=51)

    assert x.min() <= limit <= x.max()
    assert limit == pytest.approx(cutoff, abs=2.0)


def test_suggest_two_theta_limit_returns_max_when_signal_persists():
    rng = np.random.default_rng(3)
    x = np.linspace(5.0, 30.0, 5000)
    centers = np.linspace(6.0, 29.9, 12)
    peaks = _gaussian_peaks(x, centers=centers, height=200.0, width=0.02)
    noise = rng.normal(0.0, 1.0, size=x.size)
    y = 5.0 + noise + peaks

    limit = suggest_two_theta_limit(x, y, snr_min=5.0, window=51)

    assert limit == pytest.approx(x.max())


def test_suggest_two_theta_limit_parasitic_peak_pushes_limit_out_without_exclusion():
    """寄生ピーク (セル由来) は実強度なので、除外しなければ信号終端が押し出される。"""
    x, y = _parasitic_pattern()

    limit = suggest_two_theta_limit(x, y, snr_min=5.0, window=51)

    # 真の信号終端 (18°) ではなく寄生ピーク (26°) 側まで押し出される
    assert limit > 24.0


def test_suggest_two_theta_limit_excluded_regions_recovers_true_terminus():
    """寄生ピークの窓を excluded_regions で除外すると真の信号終端に戻る。"""
    x, y = _parasitic_pattern()

    limit = suggest_two_theta_limit(
        x, y, snr_min=5.0, window=51, excluded_regions=[(25.5, 26.5)]
    )

    assert limit == pytest.approx(18.0, abs=2.0)


def test_suggest_two_theta_limit_excluded_regions_none_keeps_current_behaviour():
    """excluded_regions=None は既定 (除外なし) の挙動と同一。"""
    x, y = _parasitic_pattern()

    limit_default = suggest_two_theta_limit(x, y, snr_min=5.0, window=51)
    limit_none = suggest_two_theta_limit(x, y, snr_min=5.0, window=51, excluded_regions=None)
    limit_empty = suggest_two_theta_limit(x, y, snr_min=5.0, window=51, excluded_regions=[])

    assert limit_none == pytest.approx(limit_default)
    assert limit_empty == pytest.approx(limit_default)


def test_suggest_two_theta_limit_all_points_excluded_does_not_raise():
    x, y = _parasitic_pattern()

    limit = suggest_two_theta_limit(x, y, excluded_regions=[(0.0, 100.0)])

    assert limit == pytest.approx(0.0)


def test_suggest_two_theta_limit_empty_arrays_do_not_raise():
    limit = suggest_two_theta_limit(np.array([]), np.array([]))
    assert limit == pytest.approx(0.0)


def test_suggest_two_theta_limit_short_arrays_do_not_raise():
    x = np.array([1.0, 2.0])
    y = np.array([5.0, 6.0])
    limit = suggest_two_theta_limit(x, y)
    assert limit == pytest.approx(x.max())


# --- scan_background_coeffs -------------------------------------------------


def test_scan_background_coeffs_picks_min_rwp():
    rwp_by_n = {6: 0.15, 12: 0.10, 18: 0.062, 24: 0.07}
    report = scan_background_coeffs(lambda n: rwp_by_n[n])

    assert isinstance(report, BackgroundScanReport)
    assert report.best == 18
    assert report.results == ((6, 0.15), (12, 0.10), (18, 0.062), (24, 0.07))


def test_scan_background_coeffs_tie_picks_smallest_count():
    rwp_by_n = {6: 0.15, 12: 0.10, 18: 0.08, 24: 0.08}
    report = scan_background_coeffs(lambda n: rwp_by_n[n])

    assert report.best == 18


def test_scan_background_coeffs_custom_candidates():
    rwp_by_n = {3: 0.2, 9: 0.05}
    report = scan_background_coeffs(lambda n: rwp_by_n[n], candidates=(3, 9))

    assert report.best == 9
    assert report.results == ((3, 0.2), (9, 0.05))


def test_background_scan_report_is_frozen():
    report = BackgroundScanReport(best=18, results=((18, 0.08),))
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.best = 6  # type: ignore[misc]
