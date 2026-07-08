"""diagnose_residual (残差解析の既定 diagnose, REQ-002) の決定論テスト。"""

from __future__ import annotations

import numpy as np

from tsumugin.autorietveld.model import (
    AutoRietveldResult,
    Geometry,
    HistogramSpec,
    Radiation,
    StageResult,
    ValidityReport,
)
from tsumugin.refine_loop.action import AnalysisInput
from tsumugin.refine_loop.diagnose_residual import diagnose_residual


def _inp(*rads: Radiation) -> AnalysisInput:
    if not rads:
        rads = (Radiation.XRAY_SYNCHROTRON,)
    hists = tuple(
        HistogramSpec(f"d{i}.xye", "i.instprm", radiation=r,
                      geometry=Geometry.DEBYE_SCHERRER, data_format="XYE")
        for i, r in enumerate(rads)
    )
    return AnalysisInput(hists, (), background_coeffs=12)


def _result(**kw) -> AutoRietveldResult:
    return AutoRietveldResult(
        stage_results=(StageResult("final", rwp=12.0, gof=1.3, n_params=8, converged=True),),
        final_rwp=12.0, final_gof=1.3, refined_cells={"P1": (5.0,) * 3 + (90.0,) * 3},
        validity=ValidityReport(passed=True), **kw,
    )


def test_introspection_signals_propagate():
    res = _result(
        peak_width_ratio=(1.3,), asymmetry_metric=(0.2,),
        intensity_bias_metric=(0.1,), bg_extrema=(12,),
    )
    feats = diagnose_residual(res, _inp())
    assert len(feats) == 1
    f = feats[0]
    assert f.fwhm_ratio == 1.3
    assert f.asymmetry_residual == 0.2
    assert f.intensity_bias == 0.1
    assert f.bg_extrema_count == 12
    assert f.n_background_coeffs == 12


def test_tof_flag_from_radiation():
    feats = diagnose_residual(_result(asymmetry_metric=(0.0, 0.3)),
                              _inp(Radiation.XRAY_SYNCHROTRON, Radiation.NEUTRON_TOF))
    assert feats[0].radiation_is_tof is False
    assert feats[1].radiation_is_tof is True
    assert feats[1].asymmetry_residual == 0.3


def test_negative_absorption_sets_uncertain():
    feats = diagnose_residual(_result(hist_absorption=(-0.06,)), _inp())
    assert feats[0].absorption_uncertain is True


def test_diverged_uiso_detected():
    res = _result(atom_uiso={"P1": {"Cu": 0.01, "Ow": 0.05, "C1": -0.3, "O2A": 5e6}})
    feats = diagnose_residual(res, _inp())
    assert feats[0].diverged_uiso_labels == ("C1", "O2A")  # 昇順・物理範囲外のみ


def test_missing_introspection_degrades_no_error():
    # 内省フィールド皆無 (旧 result) でも例外なく縮退 (EDGE-001)。
    feats = diagnose_residual(_result(), _inp())
    assert len(feats) == 1
    assert feats[0].fwhm_ratio == 1.0  # 既定
    assert feats[0].asymmetry_residual == 0.0
    assert feats[0].diverged_uiso_labels == ()


def test_all_noise_residual_no_signal():
    # 残差が全ノイズ (|resid| < 3σ) → 残差由来シグナルを立てない (EDGE-102)。
    rng = np.arange(50.0)
    res = _result(
        residual_two_theta=tuple(rng),
        residual_intensity=tuple(np.full(50, 0.5)),
        residual_sigma=tuple(np.full(50, 1.0)),  # 0.5 < 3*1.0 → 全ノイズ
    )
    f = diagnose_residual(res, _inp())[0]
    assert f.low_freq_bg_residual == 0.0
    assert f.unindexed_peak_frac == 0.0


def test_significant_residual_sets_signals():
    # 有意な正ピーク残差 → 未指数割合が立つ。
    resid = np.zeros(50)
    resid[20:25] = 50.0  # 大きな正ピーク
    res = _result(
        residual_two_theta=tuple(np.arange(50.0)),
        residual_intensity=tuple(resid),
        residual_sigma=tuple(np.ones(50)),
    )
    f = diagnose_residual(res, _inp())[0]
    assert f.unindexed_peak_frac > 0.0


def test_deterministic():
    res = _result(peak_width_ratio=(1.2,), atom_uiso={"P1": {"C1": -0.3, "Cu": 0.01}})
    a = diagnose_residual(res, _inp())
    b = diagnose_residual(res, _inp())
    assert [x.fwhm_ratio for x in a] == [x.fwhm_ratio for x in b]
    assert a[0].diverged_uiso_labels == b[0].diverged_uiso_labels


def test_empty_histograms():
    assert diagnose_residual(_result(), AnalysisInput((), ())) == []
