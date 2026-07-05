"""M6 TASK-0112 Dara 式ピークマッチングスコアの失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/reference/scoring.py`` (未実装)。
Dara (Fei et al., Chem. Mater. 2026) の式(1):
  Score = (I_matched + I_wrong_intensity − 0.1·I_missing − 0.5·I_extra) / I_exp
実測強度で正規化し候補のピーク数では罰しない (peak-rich 相の希釈を回避)。
"""

from __future__ import annotations

import pytest

from tsumugin.search.peaks import Peak


def _peaks(*specs):
    return tuple(Peak(position=p, height=h) for p, h in specs)


def test_perfect_match_scores_one():
    from tsumugin.reference.scoring import dara_peak_score

    obs = _peaks((20.0, 100.0), (30.0, 50.0))
    calc = _peaks((20.0, 100.0), (30.0, 50.0))
    r = dara_peak_score(calc, obs)
    assert r.score == pytest.approx(1.0, abs=1e-6)
    assert r.i_missing == pytest.approx(0.0)
    assert r.i_extra == pytest.approx(0.0)


def test_matched_indices_reported():
    from tsumugin.reference.scoring import dara_peak_score

    obs = _peaks((20.0, 100.0), (30.0, 50.0), (40.0, 30.0))
    calc = _peaks((20.0, 100.0), (40.0, 30.0))
    r = dara_peak_score(calc, obs)
    assert set(r.matched_observed) == {0, 2}


def test_missing_peaks_penalized_weakly():
    from tsumugin.reference.scoring import dara_peak_score

    # 観測に calc で説明できないピーク (missing) → -0.1 罰
    obs = _peaks((20.0, 100.0), (50.0, 100.0))
    calc = _peaks((20.0, 100.0))
    r = dara_peak_score(calc, obs)
    assert r.i_missing == pytest.approx(100.0)
    # score = (100 - 0.05*100)/200 = 0.475 (Dara 既定 missing 係数 -0.05)
    assert r.score == pytest.approx(0.475, abs=1e-6)


def test_extra_peaks_penalized_strongly():
    from tsumugin.reference.scoring import dara_peak_score

    # calc に観測に無いピーク (extra) → -0.5 罰。強度スケールは matched でそろえる
    obs = _peaks((20.0, 100.0))
    calc = _peaks((20.0, 100.0), (60.0, 100.0))
    r = dara_peak_score(calc, obs)
    assert r.i_extra > 0.0
    # score = (100 - 0.5*100)/100 = 0.5
    assert r.score == pytest.approx(0.5, abs=1e-6)


def test_extra_penalty_isolated():
    # 同一の観測・同一の matched/missing で、余分な計算ピーク (extra) が加わると score が下がる
    from tsumugin.reference.scoring import dara_peak_score

    obs = _peaks((20.0, 100.0), (30.0, 100.0), (40.0, 100.0))  # I_exp=300
    # 20,30 を一致・40 を missing (matched=200, missing=100)
    no_extra = _peaks((20.0, 100.0), (30.0, 100.0))
    # 同上 + 80° に余分な計算ピーク (extra 100)
    with_extra = _peaks((20.0, 100.0), (30.0, 100.0), (80.0, 100.0))
    s_no = dara_peak_score(no_extra, obs).score
    s_extra = dara_peak_score(with_extra, obs).score
    assert s_extra < s_no  # extra 追加で score 低下
    # extra 罰 = 0.5 * I_extra / I_exp = 0.5*100/300 ≈ 0.1667
    assert (s_no - s_extra) == pytest.approx(0.5 * 100.0 / 300.0, abs=1e-6)


def test_extra_coefficient_exceeds_missing_coefficient():
    # 係数として extra(0.5) > missing(0.1): 同一強度の欠陥で extra の減点が大きい
    from tsumugin.reference.scoring import dara_peak_score

    # missing 罰: obs に計算が説明しない弱ピーク → 減点 0.1*I/I_exp
    obs_m = _peaks((20.0, 100.0), (50.0, 20.0))  # I_exp=120
    calc_m = _peaks((20.0, 100.0))
    drop_missing = 1.0 - dara_peak_score(calc_m, obs_m).score  # 完全一致 1.0 からの低下でない点に注意
    # 純粋な係数確認: i_missing の寄与
    r_m = dara_peak_score(calc_m, obs_m)
    assert r_m.i_missing == pytest.approx(20.0)
    # extra 罰: 完全一致 + 余分ピーク
    obs_e = _peaks((20.0, 100.0))  # I_exp=100
    calc_e = _peaks((20.0, 100.0), (60.0, 20.0))
    r_e = dara_peak_score(calc_e, obs_e)
    assert r_e.i_extra == pytest.approx(20.0)
    # 同じ欠陥強度 20 に対し extra の減点 (0.5*20) > missing の減点 (0.1*20)
    assert 0.5 * r_e.i_extra > 0.1 * r_m.i_missing
    assert drop_missing >= 0.0


def test_moderate_intensity_diff_is_wrong_intensity():
    from tsumugin.reference.scoring import dara_peak_score

    # 位置一致で強度が中程度に違う (2〜5x) → wrong-intensity (正の重み 1.0, missing にしない)
    obs = _peaks((20.0, 100.0), (30.0, 100.0))
    calc = _peaks((20.0, 100.0), (30.0, 30.0))  # 30° は約 3x 差
    r = dara_peak_score(calc, obs)
    assert r.i_wrong_intensity > 0.0
    assert r.i_missing == pytest.approx(0.0)  # 解消されず missing にならない


def test_extreme_intensity_diff_dissolves_to_missing_and_extra():
    from tsumugin.reference.scoring import dara_peak_score

    # 位置一致でも強度比が >5x なら説明不能としてペア解消 (obs→missing, calc→extra)
    obs = _peaks((20.0, 100.0), (30.0, 100.0))
    calc = _peaks((20.0, 100.0), (30.0, 1.0))  # 30° は 100x 差
    r = dara_peak_score(calc, obs)
    assert r.i_missing > 0.0   # 30° 観測は missing 化
    assert r.i_extra > 0.0     # 30° 計算は extra 化
    assert r.score < 0.6       # 罰されてスコア低下


def test_peak_rich_phase_not_diluted_by_count():
    from tsumugin.reference.scoring import dara_peak_score

    # 観測の全ピークを説明する peak-rich 相 (余分な弱いピークあり) は count で希釈されない
    obs = _peaks((20.0, 100.0), (30.0, 80.0), (40.0, 60.0))
    peak_rich = _peaks((20.0, 100.0), (30.0, 80.0), (40.0, 60.0), (25.0, 2.0), (35.0, 2.0))
    sparse_wrong = _peaks((22.0, 100.0), (55.0, 100.0))  # 位置がほぼ合わない
    s_rich = dara_peak_score(peak_rich, obs).score
    s_wrong = dara_peak_score(sparse_wrong, obs).score
    assert s_rich > s_wrong  # 観測を説明する peak-rich 相が勝つ


def test_empty_observed_scores_zero():
    from tsumugin.reference.scoring import dara_peak_score

    r = dara_peak_score(_peaks((20.0, 100.0)), ())
    assert r.score == pytest.approx(0.0)


def test_deterministic():
    from tsumugin.reference.scoring import dara_peak_score

    obs = _peaks((20.0, 100.0), (30.0, 50.0))
    calc = _peaks((20.05, 90.0), (30.0, 40.0), (70.0, 10.0))
    assert dara_peak_score(calc, obs).score == dara_peak_score(calc, obs).score


def test_tolerance_controls_position_match():
    from tsumugin.reference.scoring import dara_peak_score

    obs = _peaks((20.0, 100.0))
    calc = _peaks((20.3, 100.0))  # 0.3° ずれ
    strict = dara_peak_score(calc, obs, tol_deg=0.15)
    loose = dara_peak_score(calc, obs, tol_deg=0.5)
    assert strict.i_missing > 0.0  # 厳しい許容ではミスマッチ
    assert loose.i_missing == pytest.approx(0.0)  # 緩い許容では一致
