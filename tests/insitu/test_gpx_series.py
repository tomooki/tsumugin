"""★規定「全解析で gpx を保存する」の**系列**側 (M9 逐次 / M10 アンカー双方向)。

系列解析は本規定の中心である — フレームが 754 枚あっても、残ったのが最終 Rwp の数字だけでは

- 段が無言 no-op だったフレームを後から特定できない
- 相分率 ~0 で棄却されたトライアルが「残差を説明できない相」なのか
  「セルがずれて説明**できなかった**相」なのか切れない
- MEM (`mem_density`) を後から任意のフレームに掛けられない

GSAS 非依存の決定論テスト: スタブ runner が ambient 文脈 (`gpxstore`) を読んで
「どの役割で呼ばれたか」を記録し、返した ``gpx_path`` が結果と ledger に載ることを見る。
実ファイルが本当に出来ることは gated テスト (`test_engine_gsas.py` 系) が確かめる。
"""

from __future__ import annotations

from pathlib import Path

from tsumugin.autorietveld.model import AutoRietveldResult, PhaseSpec, ValidityReport
from tsumugin.gpxstore import active_context
from tsumugin.insitu.engine import run_sequential_rietveld
from tsumugin.insitu.model import FrameSpec, PhaseIdConfig, SequentialConfig
from tsumugin.store.ledger import Ledger


def _result(rwp, cells, fracs, *, valid=True, gof=1.0, gpx_path=""):
    return AutoRietveldResult(
        stage_results=(),
        final_rwp=rwp,
        final_gof=gof,
        refined_cells=cells,
        validity=ValidityReport(passed=valid),
        phase_fractions=fracs,
        gpx_path=gpx_path,
    )


def _frames(n, base="f"):
    return [
        FrameSpec(data_path=f"{base}{i}.xrdml", axis_value=300.0 + 20.0 * i) for i in range(n)
    ]


_ALPHA = PhaseSpec(structure_path="alpha.cif", phase_name="alpha")
_CELL = {"alpha": (14.8, 6.8, 8.0, 90, 90, 90)}


def test_series_shares_one_run_dir_and_labels_each_frame(tmp_path):
    """系列は run ディレクトリを 1 つ共有し、各フレームが ``frame`` 役割 + 番号で呼ばれる。

    フレームごとに run ディレクトリが分かれると 754 個のディレクトリが出来て探せない。
    """
    seen: list[tuple[str, int | None, str]] = []

    def runner(frame, phases, initial_cells):
        ctx = active_context()
        seen.append((ctx.role, ctx.index, ctx.run_dir))
        return _result(9.0, _CELL, {"alpha": 1.0}, gpx_path=f"{ctx.run_dir}/f{ctx.index:04d}.gpx")

    res = run_sequential_rietveld(_frames(3), [_ALPHA], runner=runner, gpx_dir=str(tmp_path))

    assert [(r, i) for r, i, _ in seen] == [("frame", 0), ("frame", 1), ("frame", 2)]
    run_dirs = {d for _, _, d in seen}
    assert len(run_dirs) == 1, f"フレームごとに run ディレクトリが分かれている: {run_dirs}"
    assert Path(next(iter(run_dirs))).parent == tmp_path
    assert res.gpx_dir == next(iter(run_dirs))


def test_frame_results_carry_the_saved_gpx_path(tmp_path):
    """★保存したパスが `FrameRietveldResult.gpx_path` に載る (② → ③ へ届く唯一の経路)。"""

    def runner(frame, phases, initial_cells):
        ctx = active_context()
        return _result(9.0, _CELL, {"alpha": 1.0}, gpx_path=f"/out/f{ctx.index:04d}.gpx")

    res = run_sequential_rietveld(_frames(2), [_ALPHA], runner=runner, gpx_dir=str(tmp_path))

    assert [f.gpx_path for f in res.frames] == ["/out/f0000.gpx", "/out/f0001.gpx"]


def test_rejected_trials_are_saved_and_traceable(tmp_path):
    """★棄却されたトライアルも 1 成果物として残り、ledger からそのパスを引ける。

    「なぜ棄却されたか」は Rwp と相分率だけでは切れない (セルがずれて説明できなかったのか、
    そもそも残差を説明しないのか)。棄却された fit そのものが残っていて初めて追える。
    """
    beta = PhaseSpec(structure_path="beta.cif", phase_name="beta")
    roles: list[tuple[str, str]] = []

    def runner(frame, phases, initial_cells):
        ctx = active_context()
        roles.append((ctx.role, ctx.label))
        if len(phases) == 2:  # トライアル (新相追加) — 相分率 ~0 で棄却される
            return _result(
                8.9, {**_CELL, "beta": (5.0, 5.0, 5.0, 90, 90, 90)},
                {"alpha": 1.0, "beta": 1e-12},
                gpx_path=f"/out/trial_{ctx.label}.gpx",
            )
        # フレームが進むほど Rwp が上がる = 未同定相の成長 (相同定トリガ rwp_jump が発火する)
        return _result(30.0 + 10.0 * ctx.index, _CELL, {"alpha": 1.0}, gpx_path="/out/base.gpx")

    def finder(frame, elements, exclude, workdir, known_refs):
        return [(beta, {"dara_score": 1.0, "formula": "B2O3", "source": "test"})]

    ledger = Ledger()
    pid = PhaseIdConfig(elements=("Ca", "O"), snr_trigger=0.0, trigger_rwp_ratio=1.0)
    res = run_sequential_rietveld(
        _frames(2), [_ALPHA], runner=runner, phase_finder=finder, ledger=ledger,
        config=SequentialConfig(phase_id=pid), gpx_dir=str(tmp_path),
    )

    assert ("trial", "beta") in roles, roles
    assert res.appearances == ()  # 棄却されている (相分率 ~0)
    trials = [e.payload for e in ledger.entries if e.kind == "m9_phaseid_trial"]
    assert trials, "トライアルが ledger に残っていない"
    assert all(t["gpx_path"] == "/out/trial_beta.gpx" for t in trials), trials


def test_save_gpx_false_disables_the_series(tmp_path):
    """``save_gpx=False`` なら系列でも文脈が無効になり、1 成果物も作らない。"""
    seen: list[bool] = []

    def runner(frame, phases, initial_cells):
        ctx = active_context()
        seen.append(ctx.enabled)
        return _result(9.0, _CELL, {"alpha": 1.0})

    res = run_sequential_rietveld(
        _frames(2), [_ALPHA], runner=runner, save_gpx=False, gpx_dir=str(tmp_path)
    )

    assert seen == [False, False]
    assert res.gpx_dir == ""
    assert not list(tmp_path.iterdir())


def test_plain_three_arg_runner_still_works(tmp_path):
    """文脈を読まない素の 3 引数 runner は素通りする (Runner プロトコル非破壊)。"""

    def runner(frame, phases, initial_cells):
        return _result(9.0, _CELL, {"alpha": 1.0})

    res = run_sequential_rietveld(_frames(2), [_ALPHA], runner=runner, gpx_dir=str(tmp_path))

    assert len(res.frames) == 2
    assert [f.gpx_path for f in res.frames] == ["", ""]
