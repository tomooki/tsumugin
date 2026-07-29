"""WS-1 診断ゲート — 収束判定 / no-op 検出 / 弱い変数の観測・報告・凍結 / 高相関記録。

要件: `docs/spec/stable-auto-rietveld/requirements.md` REQ-SAR-101〜104。
情報源は `autorietveld.diagnostics` に集約済み (REQ-SAR-105) なので、ここで固定するのは
**engine 側の判断ロジック**: 未収束をどう扱うか・何を no-op と呼ぶか・どの変数を凍結するか。

判断部分はすべて GSAS 非依存の純関数/純写像として切り出してあるため、本ファイルは
`-m "not gsas"` で回る (実 GSAS への配線は `test_stability_gates_gsas.py`)。
"""

from __future__ import annotations

import math

import pytest

from tsumugin.autorietveld.diagnostics import (
    RefinementDiagnostics,
    WeakVariable,
    split_weak_variables,
)
from tsumugin.autorietveld.engine import (
    _freeze_variables,
    _is_noop_stage,
    _needs_rescue,
    _prune_candidates,
    _run_convergence_cycles,
    _run_rescue_freezes,
)
from tsumugin.autorietveld.model import FinalPolish, StabilityOptions


# ---------------------------------------------------------------------------
# 非回帰契約 — 既定はすべて無効
# ---------------------------------------------------------------------------


def test_defaults_are_all_off_so_existing_runs_are_bit_identical():
    # 【目的】: `run_auto_rietveld()` を引数なしで呼んだときに現行と同一挙動であることの根拠。
    #   1 つでも既定 True になると T1-T4/CaTeO3/NaCuHCF の gated テストが動き出す。
    opts = StabilityOptions()

    assert opts.require_convergence is False
    assert opts.detect_noop_stages is False
    assert opts.record_weak_vars is False
    assert opts.report_undetermined is False
    assert opts.polish_frozen_undetermined is False
    assert opts.prune_weak_vars_each_stage is False
    assert opts.rescue_freeze_on_failure is False
    assert opts.record_correlations is False
    assert opts.needs_diagnostics is False, "既定では共分散を 1 度も読まない"
    assert opts.needs_final_diagnostics is False, "既定では最終診断も読まない"
    # WS-2: 箱拘束と restraint 有効化も既定 OFF (REQ-SAR-201/203)。
    assert opts.bound_cell is None
    assert opts.bound_displacement is None
    assert opts.bound_size_strain is False
    assert opts.enable_restraints is False
    assert opts.has_box_bounds is False, "既定では Controls (parmMin/parmMax) を 1 度も触らない"


@pytest.mark.parametrize(
    "field",
    [
        "require_convergence",
        "record_correlations",
        "record_weak_vars",
        "prune_weak_vars_each_stage",
        "rescue_freeze_on_failure",
    ],
)
def test_any_per_stage_gate_turns_on_covariance_reading(field):
    # 【目的】: **段ごとに**診断を要する項目を 1 つでも立てたら read_diagnostics が呼ばれること。
    #   ここが漏れると「有効にしたのに何も起きない」という最悪の静かな失敗になる。
    assert StabilityOptions(**{field: True}).needs_diagnostics is True


def test_noop_detection_alone_does_not_read_covariance():
    # 【目的】: no-op 検出 (REQ-SAR-102) は rwp/gof/n_params だけで判定でき、共分散を要さない。
    assert StabilityOptions(detect_noop_stages=True).needs_diagnostics is False


def test_final_reporting_does_not_add_per_stage_covariance_reads():
    # 【目的】: 「決まらなかったパラメータの報告」は**最終収束後に 1 度**読めば足りる。
    #   毎段の読み出しに混ぜると、報告を足しただけで段ごとのコストと失敗点が増える。
    opts = StabilityOptions(report_undetermined=True)
    assert opts.needs_diagnostics is False
    assert opts.needs_final_diagnostics is True


def test_polish_requires_the_report_it_freezes():
    # 【目的】: 研磨の凍結対象は「報告された決まらなかったパラメータ」そのもの。報告が無効なら
    #   凍結対象が定義されないので、黙って何もしないのではなく大声で落ちる。
    with pytest.raises(ValueError, match="report_undetermined"):
        StabilityOptions(polish_frozen_undetermined=True)
    assert StabilityOptions(
        polish_frozen_undetermined=True, report_undetermined=True
    ).needs_final_diagnostics is True


# ---------------------------------------------------------------------------
# WS-2 拘束・境界 (REQ-SAR-201/202/203)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"bound_cell": 0.05},
        {"bound_displacement": 5000.0},
        {"bound_size_strain": True},
    ],
)
def test_any_box_option_turns_on_bound_registration(kwargs):
    # 【目的】: 箱拘束を 1 つでも立てたら Controls への登録と境界検出が走ること。
    #   漏れると「拘束したつもりで拘束されていない」静かな失敗になる。
    assert StabilityOptions(**kwargs).has_box_bounds is True


def test_box_bounds_do_not_require_the_covariance_reader():
    # 【目的】: 箱拘束の情報源は Controls['parmFrozen'] であって共分散ではない (別経路)。
    #   片方を有効にしただけでもう片方の読み出しが始まると非回帰契約が崩れる。
    assert StabilityOptions(bound_cell=0.05).needs_diagnostics is False


def test_enabling_restraints_without_reporting_is_rejected_loudly():
    # 【目的】: REQ-SAR-203。restraint を χ² に入れると母数が実質増えるので、**何が決まらな
    #   かったかを見ないまま**回すことは認めない。黙って片肺で走らせるくらいなら大声で落ちる
    #   (② では error dict へ縮退する)。
    #   ⚠ 旧版は毎段プルーニング (prune_weak_vars) を必須にしていたが、その根拠 (GSAS 自身の
    #   自動パラメータ削除を失う) は D4-b の実測で誤りと判明したため、必須要件は「見ること」だけ。
    with pytest.raises(ValueError, match="report_undetermined"):
        StabilityOptions(enable_restraints=True)
    # 報告との併用は通る。
    assert StabilityOptions(enable_restraints=True, report_undetermined=True).enable_restraints


def test_restraints_do_not_force_the_irreversible_freeze():
    # 【目的】: 上の必須要件が**毎段凍結ではない**ことを固定する。拘束下で毎段凍結すると
    #   母数が不可逆に痩せる (実測: n_params が S2 で 7→3)。要求するのは観測だけである。
    opts = StabilityOptions(enable_restraints=True, report_undetermined=True)
    assert opts.prune_weak_vars_each_stage is False


def test_spec_round_trips_through_json():
    # 【目的】: ② 到達可能性 — ③ は JSON しか送れない。to_dict/from_dict が同値であること。
    opts = StabilityOptions(
        bound_cell=0.03,
        bound_displacement=2500.0,
        bound_size_strain=True,
        max_size=5.0e3,
        enable_restraints=True,
        record_weak_vars=True,
        report_undetermined=True,
        polish_frozen_undetermined=True,
        rescue_freeze_on_failure=True,
        rescue_max_freeze=2,
        rescue_max_rounds=3,
        esd_ratio_exempt_tokens=("dAx",),
    )
    assert StabilityOptions.from_dict(opts.to_dict()) == opts


def test_the_renamed_freeze_key_is_rejected_not_silently_ignored():
    # 【目的】: 旧 ``prune_weak_vars`` は**意味が変わった** (毎段永続凍結 → 観測/報告/救済に分割)。
    #   旧名の JSON をそのまま受けると「凍結しているつもりで凍結していない」逆の静かな失敗に
    #   なるため、未知キーとして大声で落ちること。
    with pytest.raises(ValueError, match="prune_weak_vars"):
        StabilityOptions.from_dict({"prune_weak_vars": True})


def test_unknown_box_key_is_rejected_not_ignored():
    # 【目的】: 綴り間違いで「拘束したつもり」にならないこと (既存の未知キー規律を WS-2 でも維持)。
    with pytest.raises(ValueError, match="bound_cel"):
        StabilityOptions.from_dict({"bound_cel": 0.05})


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
    # 【目的】: dAx/dAy/dAz は座標そのものではなく**そのサイクルでのシフト量**であり、GSAS は
    #   精密化のたびに 0 へ初期化する (`GSASIIstrIO`:1732 → `ApplyXYZshifts`:2940 で座標へ
    #   足し込む)。したがって分母は収束するほど 0 に近づき、比は**よく決まっている座標ほど
    #   大きくなる** = 向きが逆の構造的偽陽性。**最終判定だけにしても消えない**
    #   (むしろ収束点で最大になる) ので、タイミングを変えた後も除外は維持する。
    weak = (_weak("0::dAx:3"), _weak("0::dAz:7"), _weak("0::AUiso:4"))
    exempt = StabilityOptions().esd_ratio_exempt_tokens

    assert [w.name for w in _prune_candidates(weak, set(), exempt)] == ["0::AUiso:4"]


def test_exemption_can_be_disabled_explicitly():
    weak = (_weak("0::dAx:3"),)
    assert [w.name for w in _prune_candidates(weak, set(), ())] == ["0::dAx:3"]


def test_exempt_variables_are_returned_not_discarded():
    # 【目的】: 除外は「判定できない」であって「決まっている」ではない。黙って捨てると報告が
    #   **何を見なかったか**を隠す (② が「弱い変数は無かった」と読む最悪の形)。
    weak = (_weak("0::dAx:3"), _weak("0::AUiso:4"))
    judged, exempt = split_weak_variables(weak, ("dAx",))

    assert [w.name for w in judged] == ["0::AUiso:4"]
    assert [w.name for w in exempt] == ["0::dAx:3"]


def test_split_preserves_the_worst_first_ordering():
    # 【目的】: 先頭が「最弱」であることに救済 (最弱から凍結) が依存している。
    weak = (_weak("a", 9.0), _weak("b", 4.0), _weak("c", 2.0))
    judged, _exempt = split_weak_variables(weak, ())
    assert [w.name for w in judged] == ["a", "b", "c"]
    assert [w.name for w in _prune_candidates(weak, set(), ())] == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# REQ-SAR-103 救済プルーニング (行き詰まったときだけ落とす)
# ---------------------------------------------------------------------------


def _diag_weak(
    *, shift: "float | None" = 0.1, svd: int = 0, names: "tuple[str, ...]" = ("v1", "v2", "v3")
) -> RefinementDiagnostics:
    return RefinementDiagnostics(
        converged=True,
        max_shift_esd=shift,
        svd_singularities=svd,
        weak_vars=tuple(_weak(n, 9.0 - i) for i, n in enumerate(names)),
    )


def test_a_healthy_stage_is_never_rescued():
    # 【★ 今回の設計変更の核】: 順調な段では**凍結しない**。途中段階の大きな esd は
    #   「決定不能」ではなく「まだ決まっていない」だけで、ここで凍らせると後段で決まるように
    #   なったパラメータを二度と解放できない (不可逆なラチェット)。
    assert _needs_rescue(_diag_weak(), max_shift_esd=1.0) is False


def test_unconverged_stage_is_rescued():
    assert _needs_rescue(_diag_weak(shift=42.0), max_shift_esd=1.0) is True


def test_singular_matrix_is_rescued_even_when_gsas_says_converged():
    # 【目的】: SVD0>0 は悪条件の**直接**証拠。収束フラグの上に載っていても信用しない。
    assert _needs_rescue(_diag_weak(svd=2), max_shift_esd=1.0) is True


def test_missing_convergence_information_does_not_trigger_a_rescue():
    # 【目的】: 情報が無いことを異常と断じない (fail open)。共分散を持たない精密化で毎段
    #   母数を削り始めると、静かに全部凍る。
    assert _needs_rescue(RefinementDiagnostics(), max_shift_esd=1.0) is False


def _rescue(diag, *, results=(), max_freeze=1, max_rounds=2, already=frozenset(), reject=()):
    """`_run_rescue_freezes` を GSAS 無しで回す薄いハーネス。"""
    frozen: list[str] = []
    seq = list(results)

    def freeze(names):
        got = [n for n in names if n not in reject]
        frozen.extend(got)
        return got

    def cycle():
        return seq.pop(0) if seq else (diag, "payload")

    out = _run_rescue_freezes(
        diag,
        freeze,
        cycle,
        max_shift_esd=1.0,
        exempt=(),
        already_frozen=set(already),
        max_freeze=max_freeze,
        max_rounds=max_rounds,
    )
    return out, frozen


def test_rescue_freezes_only_the_weakest_variable_by_default():
    # 【目的】: まとめて刈ると「どれが効いたのか」が分からなくなる。既定は 1 個ずつ。
    (_diag, _payload, rounds, names), frozen = _rescue(
        _diag_weak(shift=42.0), results=[(_diag_weak(), "p1")]
    )
    assert rounds == 1
    assert names == ("v1",) and frozen == ["v1"]


def test_rescue_stops_as_soon_as_the_stage_converges():
    (_d, payload, rounds, names), _frozen = _rescue(
        _diag_weak(shift=42.0), results=[(_diag_weak(), "p1")], max_rounds=5
    )
    assert (rounds, payload) == (1, "p1")
    assert len(names) == 1, "収束したらそれ以上母数を削らない"


def test_rescue_gives_up_when_it_runs_out_of_budget():
    stuck = _diag_weak(shift=42.0)
    (_d, _p, rounds, names), _frozen = _rescue(stuck, max_rounds=2)
    assert rounds == 2 and len(names) == 2


def test_rescue_does_nothing_with_a_zero_budget():
    (_d, payload, rounds, names), frozen = _rescue(_diag_weak(shift=42.0), max_rounds=0)
    assert (rounds, payload, names, frozen) == (0, None, (), [])


def test_rescue_never_refreezes_an_already_frozen_variable():
    (_d, _p, _rounds, names), _frozen = _rescue(
        _diag_weak(shift=42.0), already={"v1"}, max_rounds=1
    )
    assert names == ("v2",)


def test_rescue_stops_when_nothing_can_be_frozen():
    # 【目的】: GSAS が全部拒否したら回しても同じ結果になる = 無限ループを作らない。
    (_d, _p, rounds, names), _frozen = _rescue(
        _diag_weak(shift=42.0), reject=("v1", "v2", "v3"), max_rounds=5
    )
    assert (rounds, names) == (0, ())


def test_rescue_stops_when_there_are_no_weak_variables_left():
    stuck = RefinementDiagnostics(converged=False, max_shift_esd=42.0, weak_vars=())
    (_d, _p, rounds, names), _frozen = _rescue(stuck, max_rounds=5)
    assert (rounds, names) == (0, ()), "落とせる変数が無いなら revert に任せる"


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


# ---------------------------------------------------------------------------
# REQ-SAR-103 最終研磨の記録 (出版値がどう作られたかを隠さない)
# ---------------------------------------------------------------------------


def test_polish_record_is_json_ready_and_shows_the_cost():
    # 【目的】: 研磨は**出版値を「一部を凍結した fit」のものに変える**。黙って値だけ変えると
    #   拘束なしの run と同じ列で比較できなくなるので、何を凍結して Rwp がどう動いたかを残す。
    polish = FinalPolish(
        applied=True, frozen=("0::AUiso:4",), rwp_before=9.80, rwp_after=9.86
    )
    assert polish.to_dict() == {
        "applied": True,
        "frozen": ["0::AUiso:4"],
        "rwp_before": 9.80,
        "rwp_after": 9.86,
        "reverted": False,
        "reason": "",
    }


def test_polish_that_was_thrown_away_says_so_with_a_reason():
    # 【目的】: 「研磨したが破棄した」を無言にしない (適用したのかしなかったのかが結果から
    #   分からないと、published Rwp がどちらのものか決められない)。
    polish = FinalPolish(
        applied=False, frozen=("x",), rwp_before=9.8, rwp_after=float("inf"),
        reverted=True, reason="研磨後の格子/プロファイルが非物理",
    )
    d = polish.to_dict()
    assert d["applied"] is False and d["reverted"] is True
    assert d["rwp_after"] is None, "非有限は None (JSON 化できない値を ② へ流さない)"
    assert d["reason"]


class _PolishProject:
    """`_run_final_polish` に必要な `G2Project` の口だけを持つスタブ。"""

    def __init__(self, path):
        self.path = path
        self.frozen: list[str] = []
        self.data = {"Controls": {"data": {}}}

    def save(self):
        self.path.write_text("gpx", encoding="utf-8")

    def set_Frozen(self, variable, mode="remove"):  # noqa: N802 — GSAS-II の命名
        self.frozen.append(variable)
        return True

    def phases(self):
        return []

    def histograms(self):
        return []


#: 研磨前に判定済みの「判定対象外」(座標シフト)。**早期 return がこれを潰さない**ことを測る。
_EXEMPT = (_weak("0::dAx:2"), _weak("0::dAy:5"))


def _polish(monkeypatch, tmp_path, *, refine, rwp=9.9, physical=True):
    """`_run_final_polish` を GSAS 無しで回す (段列ループ外の分岐を直接測る)。"""
    from tsumugin.autorietveld import engine as eng
    from tsumugin.autorietveld.model import StageResult
    from tsumugin.store import Ledger

    gpx_path = tmp_path / "auto.gpx"
    gpx_path.write_text("gpx", encoding="utf-8")
    gpx = _PolishProject(gpx_path)

    monkeypatch.setattr(eng, "_refine_once", refine)
    monkeypatch.setattr(eng, "_rvals", lambda _g: (rwp, 1.1, 34))
    monkeypatch.setattr(eng, "_data_rwp", lambda _g, r, split: (r, None, 0.0))
    monkeypatch.setattr(eng, "_converged", lambda _g: True)
    monkeypatch.setattr(eng, "_cells_physical", lambda _p: physical)
    monkeypatch.setattr(
        eng, "_profiles_physical", lambda *a, **k: eng.ValidityReport(passed=physical)
    )
    monkeypatch.setattr(eng, "read_diagnostics", lambda _g, **k: RefinementDiagnostics())

    class _G2sc:
        @staticmethod
        def G2Project(gpxfile):  # noqa: N802 — GSAS-II の命名
            return _PolishProject(tmp_path / "auto.gpx")

    stages = [StageResult(label="S9", rwp=9.8, gof=1.2, n_params=35, converged=True)]
    ledger = Ledger()
    out_gpx, polish, undet, exempt = eng._run_final_polish(
        gpx,
        _G2sc,
        gpx_path=gpx_path,
        snap_path=tmp_path / "polish.gpx",
        undetermined=(_weak("0::AUiso:4"),),
        exempt=_EXEMPT,
        already_frozen=set(),
        stab=StabilityOptions(report_undetermined=True, polish_frozen_undetermined=True),
        stage_results=stages,
        dlg=None,
        split_penalty=False,
        max_cyc=12,
        radiations=[],
        histograms=[],
        ledger=ledger,
    )
    return polish, stages, ledger, out_gpx, undet, exempt


def test_polish_applies_even_though_freezing_costs_a_little_rwp(monkeypatch, tmp_path):
    # 【目的】: 凍結は自由度を減らすので Rwp は普通わずかに悪化する。それを revert 条件に
    #   すると研磨は**決して適用されない**。コストは rwp_before → rwp_after で見せる。
    polish, stages, ledger, *_ = _polish(
        monkeypatch, tmp_path, refine=lambda *a, **k: None, rwp=9.86
    )

    assert polish.applied is True and polish.reverted is False
    assert (polish.rwp_before, polish.rwp_after) == (9.8, 9.86)
    assert stages[-1].label == "final polish", "出版値がどの段の産物か段列から判る"
    assert [e.kind for e in ledger.entries] == ["m7_final_polish"]


def test_polish_is_thrown_away_when_the_refinement_breaks(monkeypatch, tmp_path):
    # 【目的】: 破綻 (GSAS の失敗) は revert する。ここが抜けると研磨が壊れた状態を**出版値に
    #   昇格させる** — 段の revert ガードと同じ規律を最後の 1 回にも適用する。
    def _boom(*_a, **_k):
        raise RuntimeError("Refine failed")

    polish, stages, ledger, _gpx, undet, exempt = _polish(
        monkeypatch, tmp_path, refine=_boom
    )

    assert polish.applied is False and polish.reverted is True
    assert "Refine failed" in polish.reason
    assert stages[-1].label == "S9", "破棄した研磨を段列に足さない"
    # ★ revert = 研磨前へ戻した = 研磨前の判定がそのまま最終判定。**exempt を空で潰さない**
    #   (潰すと結果の undetermined_exempt が ledger `m7_undetermined` と食い違う, MEDIUM-2)。
    assert undet == (_weak("0::AUiso:4"),)
    assert exempt == _EXEMPT, "revert で判定対象外が消えた (報告が何を見なかったかを隠す)"


def test_polish_is_thrown_away_when_the_result_is_unphysical(monkeypatch, tmp_path):
    # 【目的】: 格子崩壊/プロファイル非物理も破綻。Rwp が下がっていても採らない。
    polish, _stages, _ledger, *_ = _polish(
        monkeypatch, tmp_path, refine=lambda *a, **k: None, rwp=1.0, physical=False
    )

    assert polish.applied is False and polish.reverted is True
    assert "非物理" in polish.reason


def test_polish_with_nothing_to_freeze_states_the_reason(monkeypatch, tmp_path):
    # 【目的】: 「有効にしたのに何も起きなかった」を静かにしない。
    from tsumugin.autorietveld import engine as eng
    from tsumugin.autorietveld.model import StageResult
    from tsumugin.store import Ledger

    gpx_path = tmp_path / "auto.gpx"
    gpx_path.write_text("gpx", encoding="utf-8")

    def _boom(*_a, **_k):  # pragma: no cover - 呼ばれたら失敗
        raise AssertionError("凍結対象が無いのに精密化してはいけない")

    monkeypatch.setattr(eng, "_refine_once", _boom)
    stages = [StageResult(label="S9", rwp=9.8, gof=1.2, n_params=35, converged=True)]
    ledger = Ledger()
    _gpx, polish, undet, exempt = eng._run_final_polish(
        _PolishProject(gpx_path),
        None,
        gpx_path=gpx_path,
        snap_path=tmp_path / "polish.gpx",
        undetermined=(),
        exempt=_EXEMPT,
        already_frozen=set(),
        stab=StabilityOptions(report_undetermined=True, polish_frozen_undetermined=True),
        stage_results=stages,
        dlg=None,
        split_penalty=False,
        max_cyc=12,
        radiations=[],
        histograms=[],
        ledger=ledger,
    )

    assert polish.applied is False and polish.reverted is False
    assert polish.reason and polish.rwp_before == polish.rwp_after == 9.8
    assert [e.kind for e in ledger.entries] == ["m7_final_polish"]
    # ★ 研磨しなかった経路でも「判定対象外」を返す (MEDIUM-2)。空タプルを返すと呼び出し側の
    #   再代入で握り潰され、結果の undetermined_exempt が ledger と食い違う。
    assert undet == ()
    assert exempt == _EXEMPT, "研磨しなかっただけで判定対象外が消えた"


def test_a_default_result_reports_nothing_rather_than_claiming_all_is_well():
    # 【目的】: 診断を要求していない run の空リストを「弱い変数は無かった」と読ませない。
    #   ② 不変条件「空/不正入力を『正常』と答えない」の ① 側の対応物。
    from tsumugin.autorietveld.model import AutoRietveldResult, ValidityReport

    r = AutoRietveldResult(
        stage_results=(), final_rwp=9.8, final_gof=1.1, refined_cells={},
        validity=ValidityReport(passed=True),
    )
    assert r.undetermined_parameters == ()
    assert r.undetermined_exempt == ()
    assert r.frozen_parameters == ()
    assert r.final_polish is None, "研磨していない = None (False や空 dict ではない)"
