"""`autorietveld.diagnostics` — 精密化の自己診断 (REQ-SAR-105 の土台)。

収束判定 (REQ-SAR-101) / esd プルーニング (103) / 相関検出 (104) は**どれも同じ情報源**
(`gpx.data["Covariance"]["data"]`) を要するため、読み出しを 1 箇所に集約する。純関数部分は
GSAS 非依存でここに固定する (GSAS 依存は `read_diagnostics` の 1 関数のみ)。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.autorietveld.diagnostics import (
    RefinementDiagnostics,
    correlated_pairs,
    diagnostics_from_cov_data,
    weak_variables,
)


# ---------------------------------------------------------------------------
# weak_variables — esd > |値| の検出 (REQ-SAR-103)
# ---------------------------------------------------------------------------


def test_flags_variables_whose_esd_exceeds_their_value():
    # 【目的】: esd > |値| は「決まらなかった」= 物理的に無意味。凍結候補として拾う。
    names = ["0::A", "0::B", "0::C"]
    values = [1.0, 0.10, -2.0]
    sig = [0.05, 0.50, 0.30]  # B のみ esd > |値|

    weak = weak_variables(names, values, sig)

    assert [w.name for w in weak] == ["0::B"]
    assert weak[0].value == pytest.approx(0.10)
    assert weak[0].esd == pytest.approx(0.50)
    assert weak[0].ratio == pytest.approx(5.0)


def test_weak_variables_are_ordered_worst_first():
    names, values, sig = ["a", "b"], [1.0, 1.0], [2.0, 9.0]
    assert [w.name for w in weak_variables(names, values, sig)] == ["b", "a"]


def test_zero_valued_variable_with_finite_esd_is_weak():
    # 値 0 は ratio が発散するので特別扱い: esd>0 なら weak (0 除算で落ちない)。
    weak = weak_variables(["z"], [0.0], [0.01])
    assert [w.name for w in weak] == ["z"]
    assert math.isinf(weak[0].ratio)


def test_missing_or_nonfinite_esd_is_not_flagged():
    # 【目的】: esd が取れないのは「決まらなかった」証拠ではない (共分散が無いだけ)。
    #   ここで拾うと esd を持たない精密化で全変数を凍結してしまう。
    assert weak_variables(["a", "b"], [1.0, 1.0], [None, float("nan")]) == ()


def test_length_mismatch_degrades_to_empty_rather_than_raising():
    # 診断が例外で精密化を落とさない (fail open)。
    assert weak_variables(["a", "b"], [1.0], [0.1, 0.2]) == ()


# ---------------------------------------------------------------------------
# correlated_pairs — |r| > 閾値 の検出 (REQ-SAR-104)
# ---------------------------------------------------------------------------


def _cov_from_corr(sig, corr):
    """相関行列 + esd から共分散行列を作る (テスト用の逆写像)。"""
    s = np.asarray(sig, dtype=float)
    return np.asarray(corr, dtype=float) * np.outer(s, s)


def test_detects_a_strongly_correlated_pair():
    # 【目的】: U,V,W や cell×Shift のような強相関を**測って**見つける。
    names = ["0::U", "0::V", "0::W"]
    sig = [0.1, 0.2, 0.3]
    corr = [[1.0, 0.95, 0.1], [0.95, 1.0, 0.2], [0.1, 0.2, 1.0]]

    pairs = correlated_pairs(names, _cov_from_corr(sig, corr), sig, threshold=0.9)

    assert [(p.a, p.b) for p in pairs] == [("0::U", "0::V")]
    assert pairs[0].r == pytest.approx(0.95)


def test_negative_correlation_is_detected_by_absolute_value():
    names = ["a", "b"]
    sig = [1.0, 1.0]
    pairs = correlated_pairs(names, _cov_from_corr(sig, [[1.0, -0.97], [-0.97, 1.0]]), sig, 0.9)
    assert [(p.a, p.b) for p in pairs] == [("a", "b")]
    assert pairs[0].r == pytest.approx(-0.97)


def test_pairs_are_ordered_by_absolute_correlation_descending():
    names = ["a", "b", "c"]
    sig = [1.0, 1.0, 1.0]
    corr = [[1.0, 0.92, -0.99], [0.92, 1.0, 0.95], [-0.99, 0.95, 1.0]]
    pairs = correlated_pairs(names, _cov_from_corr(sig, corr), sig, 0.9)
    assert [abs(p.r) for p in pairs] == sorted([abs(p.r) for p in pairs], reverse=True)
    assert (pairs[0].a, pairs[0].b) == ("a", "c")


def test_diagonal_is_never_reported():
    names, sig = ["a"], [1.0]
    assert correlated_pairs(names, _cov_from_corr(sig, [[1.0]]), sig, 0.5) == ()


def test_zero_esd_pair_is_skipped_without_dividing_by_zero():
    names, sig = ["a", "b"], [0.0, 1.0]
    assert correlated_pairs(names, np.array([[0.0, 0.0], [0.0, 1.0]]), sig, 0.5) == ()


def test_empty_or_malformed_covariance_degrades_to_empty():
    assert correlated_pairs([], np.zeros((0, 0)), [], 0.9) == ()
    assert correlated_pairs(["a", "b"], np.zeros((3, 3)), [1.0, 1.0], 0.9) == ()


# ---------------------------------------------------------------------------
# diagnostics_from_cov_data — covData dict → 診断 (GSAS 非依存の写像)
# ---------------------------------------------------------------------------


def _cov_data(**over):
    sig = [0.05, 0.50]
    base = {
        "varyList": ["0::A", "0::B"],
        "variables": [1.0, 0.1],
        "sig": sig,
        "covMatrix": _cov_from_corr(sig, [[1.0, 0.99], [0.99, 1.0]]),
        "Rvals": {
            "converged": True,
            "Max shft/sig": 0.42,
            "SVD0": 0,
            "DelChi2": 1e-5,
            "Nobs": 4200,
            "Nvars": 2,
            "RestraintSum": 0.0,
            "msg": "",
        },
    }
    base.update(over)
    return base


def test_maps_the_gsas_rvals_fields():
    d = diagnostics_from_cov_data(_cov_data())
    assert isinstance(d, RefinementDiagnostics)
    assert d.converged is True
    assert d.max_shift_esd == pytest.approx(0.42)
    assert d.svd_singularities == 0
    assert d.n_obs == 4200
    assert d.n_vars == 2
    assert d.restraint_sum == pytest.approx(0.0)


def test_derives_weak_variables_and_correlated_pairs():
    d = diagnostics_from_cov_data(_cov_data(), corr_threshold=0.9)
    assert [w.name for w in d.weak_vars] == ["0::B"]
    assert [(p.a, p.b) for p in d.correlated_pairs] == [("0::A", "0::B")]


def test_missing_covariance_yields_an_empty_but_valid_diagnostics():
    # 【目的】: 精密化が失敗して covData が空でも**診断自体は返る** (呼び出し側で分岐しない)。
    d = diagnostics_from_cov_data({})
    assert d.converged is None
    assert d.max_shift_esd is None
    assert d.weak_vars == ()
    assert d.correlated_pairs == ()
    assert d.n_obs == 0


def test_non_finite_values_are_normalised_to_none():
    # finite_or_none 規約 (② JSON 境界へそのまま載せられること)。
    d = diagnostics_from_cov_data(_cov_data(Rvals={"Max shft/sig": float("inf"), "Nobs": 10}))
    assert d.max_shift_esd is None
    assert d.n_obs == 10


def test_svd_singularities_are_surfaced():
    # SVD0 > 0 は「特異な変数があった」= 悪条件の直接証拠。
    d = diagnostics_from_cov_data(_cov_data(Rvals={"SVD0": 3}))
    assert d.svd_singularities == 3


def test_is_converged_requires_both_the_flag_and_the_shift_criterion():
    """収束判定 (REQ-SAR-101): GSAS の converged だけを信じない。

    実測ログには `Maximum shift/esd = 258.822` を出しながら段が「改善した」として通過する例が
    ある。**shift/esd が大きいまま次の段へ進むと、後段が壊れた出発点から始まる。**
    """
    ok = diagnostics_from_cov_data(_cov_data(Rvals={"converged": True, "Max shft/sig": 0.3}))
    assert ok.is_converged(max_shift_esd=1.0) is True

    shaky = diagnostics_from_cov_data(_cov_data(Rvals={"converged": True, "Max shft/sig": 258.8}))
    assert shaky.is_converged(max_shift_esd=1.0) is False

    flagged = diagnostics_from_cov_data(_cov_data(Rvals={"converged": False, "Max shft/sig": 0.1}))
    assert flagged.is_converged(max_shift_esd=1.0) is False


def test_unknown_convergence_is_not_asserted_as_converged():
    # 情報が無いことを「収束した」と答えない (② 不変条件: 空入力を正常と答えない)。
    assert diagnostics_from_cov_data({}).is_converged(max_shift_esd=1.0) is None


def test_to_dict_is_json_ready():
    # ② MCP 境界へそのまま載せられること (numpy 型/非有限を出さない)。
    import json

    d = diagnostics_from_cov_data(_cov_data())
    payload = d.to_dict()
    json.dumps(payload)  # 例外が出ないこと
    assert payload["converged"] is True
    assert payload["weak_vars"][0]["name"] == "0::B"
    assert payload["correlated_pairs"][0]["r"] == pytest.approx(0.99)
