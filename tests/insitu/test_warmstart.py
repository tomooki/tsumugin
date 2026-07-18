"""相分率ウォームスタートの共有機構 `insitu._warmstart` のテスト (Issue #96)。

Issue #82 で `insitu.engine._call_runner` にのみ実装された「runner が受け付ける場合だけ
`initial_fractions` をキーワードで渡す」機構を共有ヘルパへ切り出したもの。逐次 (M9) /
アンカー双方向 (M10) / 修復 (repair) の 3 経路が同一の判定を使うことを担保する。

**`Runner` の 3 引数プロトコルは不変** — 3 引数スタブに `initial_fractions` を渡して
TypeError を起こさないことが本モジュールの存在意義。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu._warmstart import call_runner, runner_accepts_initial_fractions
from tsumugin.insitu.model import FrameSpec

ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
FRAME = FrameSpec(data_path="f0.xye", axis_value=0.0)


def _result():
    return AutoRietveldResult(
        stage_results=(), final_rwp=9.0, final_gof=1.0,
        refined_cells={"alpha": (5.0, 5.0, 5.0, 90.0, 90.0, 90.0)},
        validity=ValidityReport(passed=True), phase_fractions={"alpha": 1.0},
    )


# ---------------------------------------------------------------------------
# runner_accepts_initial_fractions
# ---------------------------------------------------------------------------


def test_accepts_explicit_initial_fractions_parameter():
    def runner(frame, phases, initial_cells, initial_fractions=None):
        return _result()

    assert runner_accepts_initial_fractions(runner) is True


def test_accepts_var_keyword_runner():
    """``**kwargs`` を持つ runner は受け付けるとみなす (転送ラッパを壊さない)。"""

    def runner(frame, phases, initial_cells, **kwargs):
        return _result()

    assert runner_accepts_initial_fractions(runner) is True


def test_three_arg_runner_is_not_accepted():
    def runner(frame, phases, initial_cells):
        return _result()

    assert runner_accepts_initial_fractions(runner) is False


def test_uninspectable_callable_is_not_accepted():
    """シグネチャを取れない callable (組み込み等) は False へ縮退する (例外を出さない)。"""
    assert runner_accepts_initial_fractions(print) is False


# ---------------------------------------------------------------------------
# call_runner
# ---------------------------------------------------------------------------


def test_call_runner_passes_fractions_to_capable_runner():
    seen: list[object] = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        seen.append(initial_fractions)
        return _result()

    call_runner(runner, FRAME, (ALPHA,), None, {"alpha": 0.6, "beta": 0.4})
    assert seen == [{"alpha": 0.6, "beta": 0.4}]


def test_call_runner_omits_fractions_for_three_arg_runner():
    """3 引数 runner には決して渡さない (TypeError を起こさない = 後方互換の要)。"""
    calls: list[int] = []

    def runner(frame, phases, initial_cells):
        calls.append(3)
        return _result()

    call_runner(runner, FRAME, (ALPHA,), None, {"alpha": 0.5, "beta": 0.5})
    assert calls == [3]


def test_call_runner_omits_fractions_when_none():
    """``initial_fractions=None`` なら対応 runner にもキーワードを渡さない (従来の 3 引数呼び)。

    既定値の番人 (``"UNSET"``) が残ることで「渡していない」ことを ``None`` と弁別する。
    """
    seen: list[object] = []

    def runner(frame, phases, initial_cells, initial_fractions="UNSET"):
        seen.append(initial_fractions)
        return _result()

    call_runner(runner, FRAME, (ALPHA,), None, None)
    assert seen == ["UNSET"]
