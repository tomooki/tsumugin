"""M6 TASK-0115 動的スコア閾値 (変曲点検出) の失敗テスト (Red)。

対象実装: ``src/tsumugin/reference/threshold.py`` (未実装)。
`inflection_threshold(scores)`: スコア分布のパーセンタイル曲線の2階微分が最大となる点 (変曲点) を
良/悪の境界とする動的閾値 (Dara find_optimal_score_threshold 準拠, numpy のみ)。固定 top-k と違い
良い相を件数に依らず残す (正解を落とさない)。
"""

from __future__ import annotations

import numpy as np
import pytest


def test_empty_returns_zero():
    from tsumugin.reference.threshold import inflection_threshold

    assert inflection_threshold([]) == pytest.approx(0.0)


def test_threshold_between_min_and_max():
    from tsumugin.reference.threshold import inflection_threshold

    scores = [0.9, 0.8, 0.5, 0.1, 0.05, -0.1, -0.2]
    thr = inflection_threshold(scores)
    assert min(scores) - 0.02 <= thr <= max(scores)


def test_separates_bimodal_distribution():
    from tsumugin.reference.threshold import inflection_threshold

    # 少数の高スコア (正解相) + 多数の低スコア (無関係相)
    high = [0.7, 0.65, 0.6]
    low = list(np.linspace(-0.15, 0.1, 25))
    thr = inflection_threshold(high + low)
    # 高スコア群は閾値以上、低スコア群の大半は閾値未満
    assert all(h >= thr for h in high)
    assert sum(x < thr for x in low) >= 0.7 * len(low)


def test_keeps_all_good_regardless_of_count():
    from tsumugin.reference.threshold import inflection_threshold

    # 正解相が 5 個あっても固定 top-k のように 1-2 個に切らない
    high = [0.6, 0.58, 0.56, 0.54, 0.52]
    low = list(np.linspace(-0.1, 0.05, 30))
    thr = inflection_threshold(high + low)
    assert sum(h >= thr for h in high) == len(high)  # 5 個全て残る


def test_deterministic():
    from tsumugin.reference.threshold import inflection_threshold

    scores = [0.5, 0.4, 0.1, -0.1, 0.3, 0.05]
    assert inflection_threshold(scores) == inflection_threshold(scores)


def test_single_score():
    from tsumugin.reference.threshold import inflection_threshold

    thr = inflection_threshold([0.5])
    assert thr <= 0.5
