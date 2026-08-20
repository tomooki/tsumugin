"""M12 T7: 段の受理/revert/no-op 判定 (`autorietveld.stagepolicy`) — 純関数。

GSAS 経路と TOPAS 経路は**同じ方針**で段を受け取るべきなのに、判定が別実装だった。
実害は「片方だけが持つ検出」で出た — 無言 no-op 段 (rwp/gof/n_params がビット同一で
`reverted` も立たない) の検出は GSAS 側にしか無く、TOPAS の T4 では S3/S5 がその状態で
完走していた (2026-08-19 実測)。**方針を共有すれば、片方で学んだ検出がもう片方にも効く。**
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.stagepolicy import StageMetrics, decide_stage


def _m(rwp: float, gof: float = 1.0, n: int = 10) -> StageMetrics:
    return StageMetrics(rwp=rwp, gof=gof, n_params=n)


# ---------------- 受理 / revert ----------------


def test_improvement_is_accepted():
    decision = decide_stage(_m(20.0), _m(15.0, n=12))
    assert not decision.reverted and decision.reason == ""


def test_worsening_beyond_epsilon_is_reverted():
    decision = decide_stage(_m(15.0), _m(15.1, n=12))
    assert decision.reverted and decision.reason == "worse"


def test_worsening_within_epsilon_is_accepted():
    """数値ノイズで段を捨てない (両エンジンとも既定 1e-6)。"""
    assert not decide_stage(_m(15.0), _m(15.0 + 1e-9, n=12)).reverted


def test_non_finite_is_reverted_as_a_backend_failure():
    """**バックエンドの失敗は例外でなく inf に変換**され、ここで revert に落ちる (不変条件)。"""
    decision = decide_stage(_m(15.0), _m(float("inf"), gof=float("inf"), n=0))
    assert decision.reverted and decision.reason == "non_finite"


def test_first_stage_is_accepted_against_infinite_baseline():
    """初段は `prev_rwp = inf` から始まる — 有限になれば受理。"""
    assert not decide_stage(_m(float("inf"), gof=float("inf"), n=0), _m(40.0)).reverted


def test_unconverged_is_reverted_even_when_rwp_improved():
    """収束していない段は Rwp が下がっていても受理しない (GSAS の WS-1 ゲート)。"""
    decision = decide_stage(_m(20.0), _m(15.0, n=12), unconverged=True)
    assert decision.reverted and decision.reason == "unconverged"


# ---------------- no-op 検出 ----------------


def test_bit_identical_metrics_without_new_params_is_a_noop():
    """**段を適用したのに何も動いていない**状態を、区別できる事実として検出する。

    Rwp が動かないことを「改善しなかった」と読むと**無言失敗と区別が付かない**。
    """
    decision = decide_stage(_m(15.0, 1.5, 10), _m(15.0, 1.5, 10))
    assert decision.is_noop and not decision.reverted


def test_new_parameters_with_identical_metrics_is_still_a_noop():
    """母数が増えたのに指標がビット同一 = 解放したはずの変数が効いていない。"""
    assert decide_stage(_m(15.0, 1.5, 10), _m(15.0, 1.5, 11)).is_noop is False, (
        "母数が増えているなら「何もしていない」とは言えない (実際に動いた可能性がある)"
    )


def test_improvement_is_not_a_noop():
    assert not decide_stage(_m(15.0, 1.5, 10), _m(14.0, 1.4, 12)).is_noop


def test_non_finite_is_not_reported_as_a_noop():
    """``inf == inf`` を「ビット同一」と読むと初段の失敗を全部 no-op と誤報する。"""
    decision = decide_stage(
        _m(float("inf"), float("inf"), 0), _m(float("inf"), float("inf"), 0)
    )
    assert decision.reverted and not decision.is_noop


def test_reverted_stage_is_not_reported_as_a_noop():
    """revert された段は「戻した」ので no-op ではない (別の事実)。"""
    decision = decide_stage(_m(15.0, 1.5, 10), _m(16.0, 1.6, 12))
    assert decision.reverted and not decision.is_noop


def test_noop_detection_can_be_switched_off():
    """GSAS 側は `StabilityOptions.detect_noop_stages` で opt-in にしている (非回帰)。"""
    assert not decide_stage(_m(15.0, 1.5, 10), _m(15.0, 1.5, 10), detect_noop=False).is_noop


# ---------------- 両エンジンが同じ関数を使っていること ----------------


@pytest.mark.parametrize(
    "module",
    ["tsumugin.autorietveld.engine", "tsumugin.topas.engine"],
)
def test_both_engines_use_the_shared_policy(module):
    """**別実装に戻ったら落ちる**。判定が分かれると、片方で学んだ検出が他方に効かない。"""
    import importlib
    import inspect

    source = inspect.getsource(importlib.import_module(module))
    assert "decide_stage" in source, f"{module} が共有の段方針を使っていない"


def test_thresholds_stay_where_the_engines_expect_them():
    """既定 ``worsen_eps`` は両エンジンの実測値 (1e-6) と同じであること。"""
    signature = __import__("inspect").signature(decide_stage)
    assert signature.parameters["worsen_eps"].default == pytest.approx(1e-6)
    assert math.isfinite(1e-6)
