"""相分率ウォームスタート (SequentialConfig.warm_start_fractions) のテスト (Issue #82 再スコープ)。

run_sequential_rietveld の warm_start は格子のみを引き継ぎ相分率は毎フレーム既定 HAP Scale から
再出発するため、転移ドーム域で分率精密化が既定値に張り付くフレームが生じる (実測、issue #82 参照)。
GSAS/MP 非依存の fake runner (tests/insitu/test_engine.py と同じパターン) で検証する。
"""

from __future__ import annotations

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.insitu.engine import run_sequential_rietveld
from tsumugin.insitu.model import FrameSpec, PhaseIdConfig, SequentialConfig


def _result(rwp, cells, fracs, *, valid=True, gof=1.0):
    return AutoRietveldResult(
        stage_results=(), final_rwp=rwp, final_gof=gof, refined_cells=cells,
        validity=ValidityReport(passed=valid), phase_fractions=fracs,
    )


def _frames(n, start=300.0, step=20.0):
    return [FrameSpec(data_path=f"f{i}.xrdml", axis_value=start + i * step) for i in range(n)]


def test_warm_start_fractions_default_false_runner_never_receives_fractions():
    """既定 (warm_start_fractions=False) では runner が initial_fractions を一切受け取らない (非回帰)。

    fake runner を initial_fractions を受け付ける 4 引数シグネチャにしても、既定設定では None しか
    渡らないこと (=呼ばれ方が 3 引数のまま、または渡っても None) を確認する。
    """
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    beta = PhaseSpec(structure_path="beta.cif", phase_name="beta")
    seen_fractions = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        seen_fractions.append(initial_fractions)
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                             "beta": (5.0, 5.0, 5.0, 90, 90, 90)},
                       {"alpha": 0.5, "beta": 0.5})

    run_sequential_rietveld(
        _frames(3), [alpha, beta], runner=runner,
        config=SequentialConfig(warm_start=True, warm_start_fractions=False),
    )
    assert seen_fractions == [None, None, None]


def test_warm_start_fractions_true_second_frame_receives_first_frame_fractions():
    """warm_start_fractions=True: 2 フレーム目の runner 呼び出しが 1 フレーム目の phase_fractions を受け取る。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    beta = PhaseSpec(structure_path="beta.cif", phase_name="beta")
    seen_fractions = []
    call = {"n": 0}

    def runner(frame, phases, initial_cells, initial_fractions=None):
        seen_fractions.append(initial_fractions)
        i = call["n"]
        call["n"] += 1
        frac_beta = 0.4 + 0.05 * i
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                             "beta": (5.0, 5.0, 5.0, 90, 90, 90)},
                       {"alpha": 1 - frac_beta, "beta": frac_beta})

    run_sequential_rietveld(
        _frames(3), [alpha, beta], runner=runner,
        config=SequentialConfig(warm_start=True, warm_start_fractions=True),
    )
    assert seen_fractions[0] is None  # フレーム0: 前フレームがなくウォームスタートなし
    assert seen_fractions[1] == {"alpha": 0.6, "beta": 0.4}  # フレーム0 の分率を引き継ぐ
    assert seen_fractions[2] == {"alpha": 0.55, "beta": 0.45}  # フレーム1 の分率を引き継ぐ


def test_warm_start_fractions_requires_warm_start_true():
    """warm_start=False なら warm_start_fractions=True でも分率は引き継がれない (格子と同じゲート)。"""
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    beta = PhaseSpec(structure_path="beta.cif", phase_name="beta")
    seen_fractions = []

    def runner(frame, phases, initial_cells, initial_fractions=None):
        seen_fractions.append(initial_fractions)
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                             "beta": (5.0, 5.0, 5.0, 90, 90, 90)},
                       {"alpha": 0.5, "beta": 0.5})

    run_sequential_rietveld(
        _frames(3), [alpha, beta], runner=runner,
        config=SequentialConfig(warm_start=False, warm_start_fractions=True),
    )
    assert seen_fractions == [None, None, None]


def test_runner_without_fractions_parameter_is_never_passed_fractions():
    """runner が initial_fractions を受け付けないシグネチャ (3 引数) なら常に 3 引数で呼ばれる (非破壊)。

    Runner プロトコル (frame, phases, initial_cells) は破壊しない。inspect でシグネチャを検査し、
    initial_fractions を受け付けない runner には決して渡さない (TypeError を起こさない)。
    """
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    beta = PhaseSpec(structure_path="beta.cif", phase_name="beta")
    call_arities = []

    def runner(frame, phases, initial_cells):  # 3 引数のみ (initial_fractions を受け付けない)
        call_arities.append(3)
        return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                             "beta": (5.0, 5.0, 5.0, 90, 90, 90)},
                       {"alpha": 0.5, "beta": 0.5})

    # 例外なく完走すること自体が非破壊の確認
    run_sequential_rietveld(
        _frames(3), [alpha, beta], runner=runner,
        config=SequentialConfig(warm_start=True, warm_start_fractions=True),
    )
    assert call_arities == [3, 3, 3]


def test_phase_set_change_resets_fractions_to_fresh():
    """核形成安全弁: 相集合が変化した直後のフレームは分率を引き継がない (fresh)。

    frame0: alpha 単相 (frac=1.0)。frame0 中に beta が新相追加され frame0 の最終相集合は
    {alpha, beta}。frame1 の相集合も {alpha, beta} (変化なし直後) だが、frame0 内で相集合が
    増えた直後の frame1 では分率を引き継がず None (fresh) にする。frame2 以降は {alpha, beta}
    のまま変化がないため frame1 の分率を frame2 が引き継ぐ。
    """
    alpha = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
    beta = PhaseSpec(structure_path="beta.cif", phase_name="new_beta")
    seen_fractions = []
    call = {"n": 0}

    def runner(frame, phases, initial_cells, initial_fractions=None):
        names = [p.phase_name for p in phases]
        seen_fractions.append((tuple(names), initial_fractions))
        if "new_beta" in names:
            return _result(9.0, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90),
                                 "new_beta": (5.0, 5.0, 5.0, 90, 90, 90)},
                           {"alpha": 0.6, "new_beta": 0.4})
        i = call["n"]
        call["n"] += 1
        rwp = 9.0 if i < 1 else 20.0  # frame1 で Rwp ジャンプ→新相探索トリガ
        return _result(rwp, {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}, {"alpha": 1.0})

    def finder(frame, elements, exclude, workdir, known_phases=()):
        return [(beta, {"source": "mp", "formula": "Beta"})]

    pid = PhaseIdConfig(elements=("A", "B"), frac_min=0.02, trigger_rwp_ratio=1.25)
    res = run_sequential_rietveld(
        _frames(4), [alpha], runner=runner, phase_finder=finder,
        config=SequentialConfig(
            warm_start=True, warm_start_fractions=True, phase_id=pid,
            backward_propagation=False,
        ),
    )
    assert len(res.appearances) == 1
    assert res.appearances[0].frame_index == 1  # frame1 で beta 追加 (Rwp ジャンプ)

    # frame1 の base 呼び出し (alpha 単相, 追加トライアル前) は前フレーム(alpha単相)の分率を引き継ぐ
    # frame1 の trial 呼び出し ({alpha,new_beta}) は新相探索用で initial_fractions を使わない
    # frame2 の呼び出しは {alpha,new_beta} だが、直前フレーム(frame1)で相集合が変化した直後なので
    # fresh (None) になる
    frame2_calls = [f for names, f in seen_fractions if names == ("alpha", "new_beta")]
    # 最初の {alpha,new_beta} 呼び出しは frame1 のトライアル (fresh, None)
    assert frame2_calls[0] is None
    # frame2 の呼び出し (2 番目の {alpha,new_beta} 呼び出し) も fresh (None) — 核形成安全弁
    assert frame2_calls[1] is None
    # frame3 は {alpha,new_beta} が 2 フレーム連続で安定 → frame2 の分率を引き継ぐ
    assert frame2_calls[2] == {"alpha": 0.6, "new_beta": 0.4}
