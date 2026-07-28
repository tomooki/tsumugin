"""WS-4 (REQ-SAR-401/402/403): `autorietveld.autorange` の numpy コアテスト。

合成データ (背景 + Bragg ピーク + Poisson ノイズ) で検証する。乱数は seed 固定
(NFR-102 決定論)。GSAS-II には一切依存しない (`-m "not gsas"` で回る)。
"""

from __future__ import annotations

import dataclasses
import inspect

import numpy as np
import pytest

from tsumugin.autorietveld import autorange
from tsumugin.autorietveld.autorange import (
    BackgroundTermsSuggestion,
    ExcludedRegionCandidate,
    ExclusionProposal,
    TwoThetaRangeSuggestion,
    propose_excluded_regions,
    suggest_background_terms,
    suggest_two_theta_range,
)
from tsumugin.autorietveld.dataquality import suggest_two_theta_limit


# --- 合成パターン生成 -------------------------------------------------------


def _gauss(x: np.ndarray, center: float, height: float, fwhm: float) -> np.ndarray:
    sigma = fwhm / 2.354820045
    return height * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def _peaks(x: np.ndarray, spec, fwhm: float = 0.12) -> np.ndarray:
    y = np.zeros_like(x)
    for center, height in spec:
        y = y + _gauss(x, center, height, fwhm)
    return y


def _t4_like_pattern(seed: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """T4 の病理を模した合成パターン。

    - 低角 (3-6°): ビームストップ/空気散乱の急峻な裾 (背景モデルでは説明できない巨大強度)
    - 12-40°: Bragg ピーク群
    - 42-80°: 信号が途絶えた**ノイズ支配域** (最小二乗を支配し平坦化を招く域)
    """
    rng = np.random.default_rng(seed)
    x = np.linspace(3.0, 80.0, 7701)  # 0.01° step
    beamstop = 4000.0 * np.exp(-(x - 3.0) / 0.7)
    clean = 20.0 + beamstop + _peaks(
        x,
        [(12.0, 900.0), (17.0, 600.0), (21.0, 1200.0), (26.0, 400.0), (31.0, 700.0), (40.0, 250.0)],
    )
    return x, rng.poisson(clean).astype(float)


def _full_range_pattern(seed: int = 5) -> tuple[np.ndarray, np.ndarray]:
    """信号が端から端まで続くパターン (切り詰めてはいけない)。"""
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 60.0, 5001)
    clean = 30.0 + _peaks(x, [(c, 800.0) for c in np.arange(10.5, 60.0, 3.0)])
    return x, rng.poisson(clean).astype(float)


def _noise_only_pattern(seed: int = 11) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 60.0, 5001)
    return x, rng.poisson(np.full_like(x, 30.0)).astype(float)


def _narrow_signal_pattern(seed: int = 13) -> tuple[np.ndarray, np.ndarray]:
    """信号が中央のごく一部にしかない病的パターン (切り詰めガードの検査用)。"""
    rng = np.random.default_rng(seed)
    x = np.linspace(5.0, 85.0, 8001)
    clean = 30.0 + _peaks(x, [(44.0, 900.0), (46.0, 700.0)])
    return x, rng.poisson(clean).astype(float)


# =========================================================================
# 4-2 データレンジ自動決定 (REQ-SAR-402)
# =========================================================================


def test_range_trims_low_angle_beamstop_and_high_angle_noise():
    x, y = _t4_like_pattern()

    s = suggest_two_theta_range(x, y)

    assert isinstance(s, TwoThetaRangeSuggestion)
    # 低角: ビームストップ裾 (3-6°) を落とし、平坦背景域は残す
    assert 4.5 <= s.lower <= 11.0
    # 高角: 最後の Bragg ピーク (40°) の直後で切れる (80° まで引きずらない)
    assert 40.0 <= s.upper <= 46.0
    assert s.data_lower == pytest.approx(3.0)
    assert s.data_upper == pytest.approx(80.0)
    assert 0.0 < s.fraction_kept < 1.0
    assert s.n_points_kept > 0
    assert s.lower_reason and s.upper_reason


def test_range_as_limits_matches_fields_and_is_plain_python():
    x, y = _t4_like_pattern()

    s = suggest_two_theta_range(x, y)

    assert s.as_limits() == (s.lower, s.upper)
    # ② MCP 境界へそのまま載せられる素の型であること
    d = dataclasses.asdict(s)
    assert all(isinstance(v, (float, int, str, bool)) for v in d.values())


def test_range_is_deterministic():
    x, y = _t4_like_pattern()

    assert suggest_two_theta_range(x, y) == suggest_two_theta_range(x, y)


def test_range_keeps_full_span_when_signal_spans_everything():
    x, y = _full_range_pattern()

    s = suggest_two_theta_range(x, y)

    assert s.lower == pytest.approx(float(x[0]))
    assert s.upper >= 58.0
    assert s.fraction_kept > 0.95


def test_range_does_not_trim_when_no_signal_found():
    """全域ノイズ: 信号終端が定義できない。**全域維持**へ縮退する (破壊的に切らない)。"""
    x, y = _noise_only_pattern()

    s = suggest_two_theta_range(x, y)

    assert s.as_limits() == (float(x[0]), float(x[-1]))
    assert "信号" in s.upper_reason


def test_range_trim_guard_limits_how_much_is_discarded():
    x, y = _narrow_signal_pattern()

    s = suggest_two_theta_range(x, y, min_fraction_kept=0.8)

    # 「探索が暴走してデータを捨てる」を防ぐ下限 (中心を保ったまま広げて満たす)
    assert s.fraction_kept >= 0.79
    assert "ガード" in s.upper_reason or "ガード" in s.lower_reason


def test_range_uses_esd_as_counting_statistics_noise_when_given():
    x, y = _t4_like_pattern()
    esd = np.sqrt(np.maximum(y, 1.0))

    s = suggest_two_theta_range(x, y, esd)

    assert s.noise_model == "esd"
    assert 40.0 <= s.upper <= 46.0


def test_range_with_inflated_esd_finds_no_signal_and_keeps_everything():
    """esd を極端に大きくすると全点が「計数統計ノイズの範囲内」になる → 切らない。"""
    x, y = _t4_like_pattern()
    esd = np.full_like(y, 1.0e6)

    s = suggest_two_theta_range(x, y, esd)

    assert s.as_limits() == (float(x[0]), float(x[-1]))


def test_range_excluded_regions_keep_parasitic_peak_out_of_the_decision():
    """寄生ピークは「実在する強度」なので、除外しなければ上限がそこまで押し出される。"""
    x, y = _t4_like_pattern()
    y = y + _peaks(x, [(62.0, 500.0)])

    without = suggest_two_theta_range(x, y)
    with_excl = suggest_two_theta_range(x, y, excluded_regions=[(61.0, 63.0)])

    assert without.upper >= 61.0
    assert with_excl.upper <= 46.0


def test_range_upper_is_consistent_with_dataquality_single_limit():
    """既存 `dataquality.suggest_two_theta_limit` との整合 (実装 drift 検出)。

    契約は違う (あちらは上限 1 値・esd 非対応・ガードなし・**持続性を要求しない**) ため値は
    一致しない。不変なのは以下 2 点で、どちらかが崩れたら実装が drift している:

    1. **どちらも最後の実ピーク (40°) より外側**を返す (信号を切り落としていない)
    2. 本モジュールは持続性要求のぶん**常に同等かより保守的** (= 上限が低い)。
       あちらは窓内 S/N 単独判定なので、窓数が増えると多重比較で純ノイズを信号と誤り
       上限が伸びる (実測: 本合成データで 48.44° 対 40.54°)
    """
    rng = np.random.default_rng(17)
    x = np.linspace(5.0, 50.0, 4501)
    clean = 20.0 + _peaks(x, [(12.0, 900.0), (21.0, 1200.0), (31.0, 700.0), (40.0, 250.0)])
    y = rng.poisson(clean).astype(float)

    s = suggest_two_theta_range(x, y)
    legacy = suggest_two_theta_limit(x, y)

    assert s.upper >= 40.0
    assert legacy >= 40.0
    assert s.upper <= legacy + 1.0  # 窓 1 つ分の格子ずれは許容


def test_range_handles_noiseless_data_without_zero_division():
    """ノイズ 0 の合成データ (MAD=0) でも信号終端を見失わないこと。"""
    x = np.linspace(5.0, 60.0, 5501)
    y = 20.0 + _peaks(x, [(12.0, 900.0), (21.0, 1200.0), (30.0, 700.0)])

    s = suggest_two_theta_range(x, y)

    assert 30.0 <= s.upper <= 36.0
    assert s.lower == pytest.approx(float(x[0]))


def test_range_empty_input_degrades_without_raising():
    s = suggest_two_theta_range([], [])

    assert s.as_limits() == (0.0, 0.0)
    assert s.n_points_kept == 0


def test_range_rejects_length_mismatch():
    with pytest.raises(ValueError):
        suggest_two_theta_range([1.0, 2.0, 3.0], [1.0, 2.0])


def test_range_does_not_mutate_input():
    x, y = _t4_like_pattern()
    x0, y0 = x.copy(), y.copy()

    suggest_two_theta_range(x, y)

    assert np.array_equal(x, x0)
    assert np.array_equal(y, y0)


# =========================================================================
# 4-1 背景項数の提案 (REQ-SAR-401)
# =========================================================================


def _flat_background_pattern(seed: int = 21) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 70.0, 6001)
    clean = 200.0 - 0.5 * (x - 10.0) + _peaks(x, [(c, 1500.0) for c in (14.0, 23.0, 35.0, 52.0)])
    return x, rng.poisson(clean).astype(float)


def _wavy_background_pattern(seed: int = 23) -> tuple[np.ndarray, np.ndarray]:
    """非晶質ハロー + 蛍光の立ち上がりでうねる背景 (少ない項数では追えない)。"""
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 70.0, 6001)
    background = (
        150.0
        + 900.0 * np.exp(-((x - 22.0) ** 2) / (2.0 * 4.0**2))
        + 500.0 * np.exp(-((x - 45.0) ** 2) / (2.0 * 3.0**2))
        + 400.0 * np.exp(-((x - 60.0) ** 2) / (2.0 * 2.0**2))
        + 120.0 * np.sin(x / 1.7)
    )
    clean = background + _peaks(x, [(c, 1500.0) for c in (14.0, 23.0, 35.0, 52.0)])
    return x, rng.poisson(clean).astype(float)


def test_background_terms_flat_background_needs_few_terms():
    x, y = _flat_background_pattern()

    s = suggest_background_terms(x, y)

    assert isinstance(s, BackgroundTermsSuggestion)
    assert s.recommended <= 12
    assert s.candidates[0] == 6
    assert s.recommended in s.candidates


def test_background_terms_wavy_background_needs_more_terms_than_flat():
    x_flat, y_flat = _flat_background_pattern()
    x_wavy, y_wavy = _wavy_background_pattern()

    flat = suggest_background_terms(x_flat, y_flat)
    wavy = suggest_background_terms(x_wavy, y_wavy)

    assert wavy.recommended > flat.recommended
    assert wavy.n_inflections >= flat.n_inflections
    # うねりの多い背景ほど「エスカレーションの候補列」が伸びる (6→12→24 …)
    assert wavy.candidates[-1] >= 18


def test_background_terms_candidates_are_ascending_unique_and_contain_recommended():
    for pattern in (_flat_background_pattern(), _wavy_background_pattern()):
        s = suggest_background_terms(*pattern)
        assert list(s.candidates) == sorted(set(s.candidates))
        assert all(c >= 1 for c in s.candidates)
        assert s.recommended in s.candidates
        assert len(s.candidates) >= 2  # エスカレーションできる列であること


def test_background_terms_is_deterministic():
    x, y = _wavy_background_pattern()

    assert suggest_background_terms(x, y) == suggest_background_terms(x, y)


def test_background_terms_respects_custom_ladder():
    x, y = _wavy_background_pattern()

    s = suggest_background_terms(x, y, ladder=(4, 8, 16))

    assert set(s.candidates) <= {4, 8, 16}
    assert s.candidates[0] == 4


def test_background_terms_misfits_decrease_with_more_terms():
    x, y = _wavy_background_pattern()

    s = suggest_background_terms(x, y)
    values = [m for _, m in s.misfits]

    assert len(values) >= 3
    assert values[-1] <= values[0]


def test_background_terms_noiseless_input_uses_improvement_fallback():
    """ノイズ 0 では「残差がノイズ水準に落ちる」判定が使えない → 改善飽和で決める。"""
    x = np.linspace(10.0, 70.0, 3001)
    y = 100.0 + 50.0 * np.sin(x / 9.0) + _peaks(x, [(20.0, 900.0), (40.0, 900.0)])

    s = suggest_background_terms(x, y)

    assert s.recommended in s.candidates
    assert "飽和" in s.reason or "ノイズ" in s.reason


def test_background_terms_empty_input_degrades_without_raising():
    s = suggest_background_terms([], [])

    assert s.recommended == s.candidates[0]
    assert s.misfits == ()


# =========================================================================
# 4-3 除外領域の提案 (REQ-SAR-403) — 提案のみ・自動適用禁止
# =========================================================================


def _spike_pattern(seed: int = 31) -> tuple[np.ndarray, np.ndarray]:
    """試料ピーク (FWHM 0.20°) の中に、鋭い孤立スパイク (FWHM 0.05°) が 1 本混ざる。"""
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 60.0, 5001)
    sample = [(15.0, 900.0), (24.0, 700.0), (38.0, 800.0), (50.0, 600.0)]
    clean = 40.0 + _peaks(x, sample, fwhm=0.20)
    clean = clean + _gauss(x, 33.0, 700.0, 0.05)
    return x, rng.poisson(clean).astype(float)


def _sample_only_pattern(seed: int = 33) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = np.linspace(10.0, 60.0, 5001)
    sample = [(15.0, 900.0), (24.0, 700.0), (38.0, 800.0), (50.0, 600.0)]
    clean = 40.0 + _peaks(x, sample, fwhm=0.20)
    return x, rng.poisson(clean).astype(float)


def test_exclusion_proposes_sharp_isolated_spike():
    x, y = _spike_pattern()

    proposal = propose_excluded_regions(x, y)

    assert isinstance(proposal, ExclusionProposal)
    centers = [c.center for c in proposal.candidates]
    assert any(abs(c - 33.0) < 0.2 for c in centers)
    # 試料ピーク (通常幅) は提案しない — 未知相のピークを消さないため
    for center in centers:
        assert not any(abs(center - p) < 0.3 for p in (15.0, 24.0, 38.0, 50.0))


def test_exclusion_candidate_fields_describe_why():
    x, y = _spike_pattern()

    candidate = propose_excluded_regions(x, y).candidates[0]

    assert isinstance(candidate, ExcludedRegionCandidate)
    assert candidate.lower < candidate.center < candidate.upper
    assert candidate.sharpness >= 2.0
    assert candidate.snr > 0.0
    assert candidate.reason


def test_exclusion_skips_peaks_explained_by_a_phase():
    x, y = _spike_pattern()

    proposal = propose_excluded_regions(x, y, explained_two_theta=[33.0])

    assert proposal.candidates == ()
    assert proposal.n_peaks_examined > 0


def test_exclusion_returns_nothing_for_a_clean_sample_pattern():
    x, y = _sample_only_pattern()

    assert propose_excluded_regions(x, y).candidates == ()


def test_exclusion_is_always_a_proposal_never_applied():
    """P-SAR-3: 除外は解析の解釈を変えるので**提案に留める**。"""
    x, y = _spike_pattern()

    proposal = propose_excluded_regions(x, y)

    assert proposal.requires_human_approval is True
    assert "承認" in proposal.note
    # 適用側 API を生やしていないこと (生やすと「提案 ≠ 適用」が壊れる)
    assert not any(name.startswith("apply") for name in dir(proposal))


def test_autorange_module_never_applies_to_a_histogram_spec():
    """恒久ガード: 本モジュールはヒストグラム仕様を知らない (= 自動適用の配線を持てない)。

    変異実証: `from .model import HistogramSpec` を足すと fail する。
    """
    source = inspect.getsource(autorange)

    assert "HistogramSpec" not in source
    assert "from .model import" not in source
    assert "autorietveld.model" not in source


def test_exclusion_warns_when_phase_positions_were_not_supplied():
    x, y = _spike_pattern()

    proposal = propose_excluded_regions(x, y)

    assert "反射位置" in proposal.note


def test_exclusion_is_deterministic_and_non_mutating():
    x, y = _spike_pattern()
    y0 = y.copy()

    first = propose_excluded_regions(x, y)
    second = propose_excluded_regions(x, y)

    assert first == second
    assert np.array_equal(y, y0)


def test_exclusion_empty_input_degrades_without_raising():
    proposal = propose_excluded_regions([], [])

    assert proposal.candidates == ()
    assert proposal.n_peaks_examined == 0


def test_exclusion_max_candidates_caps_the_list():
    rng = np.random.default_rng(41)
    x = np.linspace(10.0, 60.0, 5001)
    clean = 40.0 + _peaks(x, [(c, 800.0) for c in (15.0, 24.0, 38.0, 50.0)], fwhm=0.20)
    # スパイクは 3 本 (試料ピーク 4 本より少数)。代表幅を中央値に取る設計上、アーチファクトが
    # 多数派になると判定が反転する (モジュール docstring に明記した限界)。
    for center in (18.0, 30.0, 43.0):
        clean = clean + _gauss(x, center, 700.0, 0.05)
    y = rng.poisson(clean).astype(float)

    proposal = propose_excluded_regions(x, y, max_candidates=2)

    assert len(proposal.candidates) == 2
    # snr 降順で上位が残る
    assert proposal.candidates[0].snr >= proposal.candidates[1].snr


# =========================================================================
# 4-4 Le Bail 基準線 (REQ-SAR-404) — 本 worktree では設計のみ
# =========================================================================


def test_lebail_baseline_design_is_documented_not_implemented():
    """REQ-SAR-404 は GSAS が要るため実装しない。**設計が残っている**ことだけを保証する。"""
    assert autorange.__doc__ is not None
    assert "Le Bail" in autorange.__doc__
    assert "REQ-SAR-404" in autorange.__doc__
    # GSAS 非依存であること (numpy-only コアの不変条件)
    source = inspect.getsource(autorange)
    assert "import GSASII" not in source
    assert "from GSASII" not in source
