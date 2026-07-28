"""WS-1 診断ゲート — 収束判定 / no-op 検出 / esd プルーニング / 高相関記録。

要件: `docs/spec/stable-auto-rietveld/requirements.md` REQ-SAR-101〜104。
情報源は `autorietveld.diagnostics` に集約済み (REQ-SAR-105) なので、ここで固定するのは
**engine 側の判断ロジック**: 未収束をどう扱うか・何を no-op と呼ぶか・どの変数を凍結するか。

判断部分はすべて GSAS 非依存の純関数/純写像として切り出してあるため、本ファイルは
`-m "not gsas"` で回る (実 GSAS への配線は `test_stability_gates_gsas.py`)。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.diagnostics import RefinementDiagnostics, WeakVariable
from tsumugin.autorietveld.engine import (
    _freeze_variables,
    _is_noop_stage,
    _prune_candidates,
    _run_convergence_cycles,
)
from tsumugin.autorietveld.model import StabilityOptions


# ---------------------------------------------------------------------------
# 非回帰契約 — 既定はすべて無効
# ---------------------------------------------------------------------------


def test_defaults_are_all_off_so_existing_runs_are_bit_identical():
    # 【目的】: `run_auto_rietveld()` を引数なしで呼んだときに現行と同一挙動であることの根拠。
    #   1 つでも既定 True になると T1-T4/CaTeO3/NaCuHCF の gated テストが動き出す。
    opts = StabilityOptions()

    assert opts.require_convergence is False
    assert opts.detect_noop_stages is False
    assert opts.prune_weak_vars is False
    assert opts.record_correlations is False
    assert opts.needs_diagnostics is False, "既定では共分散を 1 度も読まない"


@pytest.mark.parametrize(
    "field", ["require_convergence", "prune_weak_vars", "record_correlations"]
)
def test_any_diagnostic_gate_turns_on_covariance_reading(field):
    # 【目的】: 診断を要する項目を 1 つでも立てたら read_diagnostics が呼ばれること。
    #   ここが漏れると「有効にしたのに何も起きない」という最悪の静かな失敗になる。
    assert StabilityOptions(**{field: True}).needs_diagnostics is True


def test_noop_detection_alone_does_not_read_covariance():
    # 【目的】: no-op 検出 (REQ-SAR-102) は rwp/gof/n_params だけで判定でき、共分散を要さない。
    assert StabilityOptions(detect_noop_stages=True).needs_diagnostics is False


# ---------------------------------------------------------------------------
# REQ-SAR-101 収束判定 + 追加サイクル
# ---------------------------------------------------------------------------


def _diag(shift: "float | None", *, converged: bool = True) -> RefinementDiagnostics:
    return RefinementDiagnostics(converged=converged, max_shift_esd=shift)


def test_converged_stage_runs_no_extra_cycle():
    calls = {"n": 0}

    def cycle():
        calls["n"] += 1
        return _diag(0.05), "payload"

    diag, payload, used = _run_convergence_cycles(
        _diag(0.05), cycle, max_shift_esd=1.0, extra_cycles=3
    )

    assert used == 0 and calls["n"] == 0
    assert payload is None, "回していないのに付随値を返してはいけない (rwp を上書きしてしまう)"
    assert diag.is_converged() is True


def test_unconverged_stage_is_rerun_until_it_converges():
    # 【目的】: REQ-SAR-101 の主眼。max shft/sig が 1 を超える段は「改善した」だけでは受理せず、
    #   同じ段のまま追加サイクルを回す。
    results = [(_diag(12.0), "p1"), (_diag(0.3), "p2")]
    calls = {"n": 0}

    def cycle():
        calls["n"] += 1
        return results.pop(0)

    diag, payload, used = _run_convergence_cycles(
        _diag(258.8), cycle, max_shift_esd=1.0, extra_cycles=5
    )

    assert calls["n"] == 2, "収束した時点で止まる (無駄に回さない)"
    assert used == 2
    assert payload == "p2", "最後のサイクルの指標が呼び出し側へ返る"
    assert diag.is_converged() is True


def test_still_unconverged_after_the_budget_is_reported_as_such():
    # 【目的】: 追加サイクルを使い切っても収束しなければ「収束していない」と答える
    #   (engine 側はこれを見て revert する)。ここで True を返すと未収束の解が段列に残る。
    def cycle():
        return _diag(90.0), "p"

    diag, _payload, used = _run_convergence_cycles(
        _diag(120.0), cycle, max_shift_esd=1.0, extra_cycles=2
    )

    assert used == 2
    assert diag.is_converged() is False


def test_zero_budget_means_no_rerun():
    def cycle():  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("extra_cycles=0 で追加サイクルを回してはいけない")

    diag, payload, used = _run_convergence_cycles(
        _diag(50.0), cycle, max_shift_esd=1.0, extra_cycles=0
    )

    assert (used, payload) == (0, None)
    assert diag.is_converged() is False


def test_negative_budget_is_clamped_not_infinite():
    def cycle():  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("負の予算は 0 に丸める")

    _diagnostics, _payload, used = _run_convergence_cycles(
        _diag(50.0), cycle, max_shift_esd=1.0, extra_cycles=-3
    )
    assert used == 0


def test_unknown_convergence_does_not_loop():
    # 【目的】: 共分散が無い (= 判定材料なし) 精密化で「未収束」と断じない (fail open)。
    #   ここを False 扱いにすると、esd を持たない経路が毎段 extra_cycles を空回りする。
    def cycle():  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("判定材料が無いときは回さない")

    diag, _payload, used = _run_convergence_cycles(
        RefinementDiagnostics(), cycle, max_shift_esd=1.0, extra_cycles=3
    )

    assert used == 0
    assert diag.is_converged() is None


def test_threshold_is_honoured():
    # 閾値を緩めれば同じ診断が「収束」になる (設定可能であることの固定)。
    assert _diag(2.5).is_converged(max_shift_esd=1.0) is False
    assert _diag(2.5).is_converged(max_shift_esd=3.0) is True


# ---------------------------------------------------------------------------
# REQ-SAR-102 no-op 段の検出
# ---------------------------------------------------------------------------


def test_bit_identical_metrics_with_no_new_params_is_a_noop():
    # 【目的】: T4 実測 (S5 profile_U / S6 profile_V が rwp ビット同一) のクラス。
    assert _is_noop_stage(38.9858, 5.57, 27, 38.9858, 5.57, 27) is True


def test_new_parameters_mean_the_stage_did_something():
    assert _is_noop_stage(38.9858, 5.57, 27, 38.9858, 5.57, 30) is False


def test_a_single_ulp_of_movement_is_not_a_noop():
    # 【目的】: 判定は**ビット同一**であること。「ほぼ同じ」を no-op と呼ぶと、
    #   本当に微小改善した段まで無言失敗の疑いをかけてしまう。
    rwp = 38.9858
    assert _is_noop_stage(rwp, 5.57, 27, math.nextafter(rwp, math.inf), 5.57, 27) is False


def test_gof_change_alone_is_not_a_noop():
    assert _is_noop_stage(38.9858, 5.57, 27, 38.9858, 5.58, 27) is False


def test_non_finite_metrics_are_not_reported_as_noop():
    # 【目的】: inf は既に revert 経路が扱う別クラスの失敗。`inf == inf` を「ビット同一」と
    #   読むと初段の失敗が全部 no-op として報告され、本物の no-op が埋もれる。
    inf = float("inf")
    assert _is_noop_stage(inf, inf, 0, inf, inf, 0) is False
    assert _is_noop_stage(12.0, 1.2, 20, inf, inf, 0) is False


def test_parameter_count_decrease_still_counts_as_noop():
    # プルーニングで母数が減った状態で rwp が動かないのも「この段は効いていない」。
    assert _is_noop_stage(12.0, 1.2, 25, 12.0, 1.2, 22) is True


# ---------------------------------------------------------------------------
# REQ-SAR-103 esd プルーニング
# ---------------------------------------------------------------------------


def _weak(name: str, ratio: float = 3.0) -> WeakVariable:
    return WeakVariable(name=name, value=1.0, esd=ratio, ratio=ratio)


def test_weak_variables_are_selected_for_freezing():
    weak = (_weak("0::AUiso:4", 5.0), _weak(":0:Back;11", 2.0))
    assert [w.name for w in _prune_candidates(weak, set(), ())] == [
        "0::AUiso:4",
        ":0:Back;11",
    ]


def test_already_frozen_variables_are_not_reported_again():
    # 【目的】: 同じ凍結を毎段 ledger に積むと台帳が読めなくなる (かつ二重登録になる)。
    weak = (_weak("0::AUiso:4"), _weak(":0:Back;11"))
    got = _prune_candidates(weak, {"0::AUiso:4"}, ())
    assert [w.name for w in got] == [":0:Back;11"]


def test_coordinate_shift_variables_are_exempt_by_default():
    # 【目的】: dAx/dAy/dAz は**座標シフト**変数で、収束するほど値が 0 に近づき esd/|値| が
    #   必ず 1 を超える = 「決まらなかった」の偽陽性。既定で凍結すると収束した瞬間に
    #   全座標が凍り、構造精密化が止まる。
    weak = (_weak("0::dAx:3"), _weak("0::dAz:7"), _weak("0::AUiso:4"))
    exempt = StabilityOptions().prune_exempt_tokens

    assert [w.name for w in _prune_candidates(weak, set(), exempt)] == ["0::AUiso:4"]


def test_exemption_can_be_disabled_explicitly():
    weak = (_weak("0::dAx:3"),)
    assert [w.name for w in _prune_candidates(weak, set(), ())] == ["0::dAx:3"]


class _FakeProject:
    """`G2Project.set_Frozen` だけを持つスタブ (GSAS を呼ばずに凍結の配線を測る)。"""

    def __init__(self, *, reject: "set[str] | None" = None, raises: "set[str] | None" = None):
        self.frozen: list[str] = []
        self._reject = reject or set()
        self._raises = raises or set()

    def set_Frozen(self, variable, mode="remove"):  # noqa: N802 — GSAS-II の命名に合わせる
        assert mode == "add"
        if variable in self._raises:
            raise ValueError(f"invalid variable {variable}")
        if variable in self._reject:
            return False
        self.frozen.append(variable)
        return True


def test_freeze_variables_registers_each_name():
    gpx = _FakeProject()
    assert _freeze_variables(gpx, ["0::AUiso:4", ":0:Back;11"]) == [
        "0::AUiso:4",
        ":0:Back;11",
    ]
    assert gpx.frozen == ["0::AUiso:4", ":0:Back;11"]


def test_freeze_variables_skips_names_gsas_rejects():
    gpx = _FakeProject(reject={":0:Back;11"})
    assert _freeze_variables(gpx, ["0::AUiso:4", ":0:Back;11"]) == ["0::AUiso:4"]


def test_a_bad_variable_name_does_not_kill_the_refinement():
    # 【目的】: 診断由来の付加機能が精密化本体を落とさない (fail open)。1 つ解釈できない
    #   変数名があっても残りは凍結し、例外は外へ出さない。
    gpx = _FakeProject(raises={"::garbage"})
    assert _freeze_variables(gpx, ["::garbage", "0::AUiso:4"]) == ["0::AUiso:4"]


# ---------------------------------------------------------------------------
# REQ-SAR-104 高相関の記録 (検出のみ・自動凍結しない)
# ---------------------------------------------------------------------------


def test_correlation_pairs_are_json_ready_for_the_ledger():
    from tsumugin.autorietveld.diagnostics import CorrelatedPair

    pair = CorrelatedPair(a="0::A0", b=":0:Shift", r=-0.987)
    assert pair.to_dict() == {"a": "0::A0", "b": ":0:Shift", "r": -0.987}


def test_recorded_pairs_are_capped_to_keep_the_ledger_readable():
    # ペア数は O(n²)。既定の上限が「全部載せる」になっていないことを固定する。
    assert StabilityOptions().max_recorded_pairs > 0
    assert StabilityOptions().max_recorded_pairs <= 50
