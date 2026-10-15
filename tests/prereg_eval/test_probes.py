"""P0 §5: 反証プローブの登録 (効果量) と、報告の 1 行 (検出力・判定) の計算。"""

from __future__ import annotations

import math

import numpy as np
import pytest

pytest.importorskip("scipy")

from tsumugin.prereg_eval.probes import (  # noqa: E402
    PROBES,
    classify,
    delta_cell,
    delta_coords,
    delta_uiso,
    delta_zero,
    noncentrality,
    power,
)


def test_registered_probes_and_their_floors():
    assert set(PROBES) == {"zero_fixed", "minor_cell_frozen", "minor_coords_frozen", "minor_uiso_frozen",
                           "uiso_grouping"}
    for spec in PROBES.values():
        assert spec.test == "hamilton" and spec.phase_role in ("main", "minor") and spec.rationale
    assert PROBES["minor_cell_frozen"].phase_role == "minor" and PROBES["zero_fixed"].phase_role == "main"


def test_effect_sizes_follow_p0_5_2_and_the_agreement_floors():
    assert delta_zero() == pytest.approx([0.01])  # 2θ の度
    assert delta_cell([5.0, 7.0]) == pytest.approx([0.025, 0.035])  # 各独立な格子定数の 0.5%
    # 座標: 自由軸ごとに原子が 0.02 Å 動く分率 (軸の長さで割る)
    assert delta_coords([("x", 10.0), ("z", 4.0)]) == pytest.approx([0.002, 0.005])
    assert delta_uiso(3) == pytest.approx([0.002] * 3)  # Uiso の一致の床 (Å²)


def test_noncentrality_takes_the_smallest_sign_combination():
    cov = np.array([[1.0, 0.9], [0.9, 1.0]])
    # 正の相関 → 同符号のずれは見分けにくい (λ が小さい)。P0: 符号の組み合わせのうち λ が最小のものを報告
    same = float(np.array([1.0, 1.0]) @ np.linalg.solve(cov, np.array([1.0, 1.0])))
    lam = noncentrality([1.0, 1.0], cov)
    assert lam == pytest.approx(same) and lam < float(np.array([1.0, -1.0]) @ np.linalg.solve(cov, [1.0, -1.0]))


def test_power_of_the_hamilton_test():
    # k = 1, α = 0.05: λ = 7.85 で検出力 0.8 (P0 §5.1 の数値)
    assert power(7.85, k=1, alpha=0.05) == pytest.approx(0.80, abs=0.005)
    assert power(0.0, k=1, alpha=0.05) == pytest.approx(0.05, abs=1e-6)


@pytest.mark.parametrize(
    ("statistic", "lam", "expected"),
    [(20.0, 1.0, "refuted"), (1.0, 20.0, "not_refuted"), (1.0, 1.0, "not_refuted_low_power")],
)
def test_outcomes(statistic, lam, expected):
    assert classify(statistic=statistic, lam=lam, k=1, alpha=0.05) == expected


def test_failed_probe_is_unevaluated_with_its_reason():
    assert classify(statistic=None, lam=None, k=1, alpha=0.05, failure="diverged") == "unevaluated(diverged)"
    assert classify(statistic=math.nan, lam=5.0, k=1, alpha=0.05) == "unevaluated(non-finite statistic)"
