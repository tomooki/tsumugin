"""backend の ``RefinementResult.warnings`` を ``refine`` の消費側が落とさないこと。

GSAS の structure_ref 経路は特殊位置吸着の記録 (とりわけ「多重度を保証できず吸着しなかった」
skipped) を ``RefinementResult.warnings`` にしか残さない (backend に ledger が無い)。これを
判別 (`operando.discrimination`) 以外の消費側 — 段階精密化・単一パターン pipeline・木探索・
マルチスタート・逐次 — が捨てていたため、それらの経路では skipped が無言だった。

各消費側は backend の警告を **出現順・重複なし** で結果の ``backend_warnings`` に持ち、② の MCP
出力はそれを ``warnings`` に載せる。消費側自身の ``warnings`` (発散・平坦パターン等) とは
別の欄に置く — 混ぜると、判別のように子の結果を束ねる側で「自分の警告」と「backend の警告」を
区別して重複除去できなくなる。
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult, merge_warnings
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.multistart import MultistartConfig
from tsumugin.multistart.engine import MultistartEngine
from tsumugin.pipeline import analyze_single_pattern
from tsumugin.refinement.staged import StagedRefinementEngine
from tsumugin.search.tree import HypothesisTreeSearch, SearchConfig
from tsumugin.sequential.engine import SequentialConfig, SequentialEngine
from tsumugin.sequential.series import FrameSeries
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

GRID = np.arange(15.0, 45.0, 0.05)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _skip_note(ref: str) -> str:
    return f"特殊位置へ吸着しませんでした ({ref}.cif): 多重度を保証できません"


class WarningBackend:
    """SimulatedBackend の結果に、相ごとの固定警告 (GSAS の skipped を模す) を足す。

    同じ相を精密化するたびに同じ文を返す (実 GSAS も同じ CIF なら毎回同じ文を出す)。
    """

    name = "warning-fake"

    def __init__(self) -> None:
        self._inner = SimulatedBackend(peak_fwhm=0.2)
        self.n_calls = 0

    def simulate(self, phases, two_theta):  # 探索/逐次がピーク照合に使う
        return self._inner.simulate(phases, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        self.n_calls += 1
        result = self._inner.refine(model, max_cycles=max_cycles)
        notes = tuple(_skip_note(p.phase_ref) for p in model.phases)
        return RefinementResult(
            phases=result.phases,
            chi2=result.chi2,
            rwp=result.rwp,
            n_obs=result.n_obs,
            n_params=result.n_params,
            converged=result.converged,
            n_cycles=result.n_cycles,
            free_params=result.free_params,
            globals=result.globals,
            warnings=result.warnings + notes,
            noise_scale=result.noise_scale,
            curvature=result.curvature,
        )


class CycleTaggedBackend(WarningBackend):
    """相ごとの文に加え ``max_cycles`` も書く — 同じ相でも経路 (段階 20 / 逐次 direct 10 /
    探索ノード 5) ごとに違う文になるので、どの経路の警告が届いたかを見分けられる。"""

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        result = super().refine(model, max_cycles=max_cycles)
        return RefinementResult(
            phases=result.phases,
            chi2=result.chi2,
            rwp=result.rwp,
            n_obs=result.n_obs,
            n_params=result.n_params,
            converged=result.converged,
            n_cycles=result.n_cycles,
            free_params=result.free_params,
            warnings=result.warnings + (f"cycles-{max_cycles}",),
        )


def _observed(*phases: PhaseInstance) -> np.ndarray:
    return SimulatedBackend(peak_fwhm=0.2).simulate(list(phases), GRID)


def test_staged_report_keeps_backend_warnings_once_in_order():
    backend = WarningBackend()
    ledger = Ledger()
    engine = StagedRefinementEngine(backend, SnapshotStore(ledger), ledger)

    report = engine.run(
        (_phase(4.05, "A"), _phase(5.60, "B", 0.5)),
        GRID,
        _observed(_phase(4.0, "A"), _phase(5.64, "B", 0.5)),
    )

    assert backend.n_calls > 2  # 同じ文が何度も返ってきた上で
    assert report.backend_warnings == (_skip_note("A"), _skip_note("B"))


def test_analyze_single_pattern_collects_across_candidates():
    result = analyze_single_pattern(
        GRID,
        _observed(_phase(4.0, "A")),
        [[_phase(4.05, "A")], [_phase(5.60, "B")], [_phase(4.05, "A"), _phase(5.60, "B")]],
        backend=WarningBackend(),
    )

    assert result.backend_warnings == (_skip_note("A"), _skip_note("B"))


def test_tree_search_collects_node_and_final_refine_warnings():
    search = HypothesisTreeSearch(WarningBackend(), config=SearchConfig(max_phases=2))
    result = search.search(
        GRID, _observed(_phase(4.0, "A")), [_phase(4.05, "A"), _phase(5.60, "B")]
    )

    assert result.backend_warnings == (_skip_note("A"), _skip_note("B"))
    # ② (list_hypotheses / identify_phase_mixtures) は to_summary を返す — そこへ出ること
    summary = result.to_summary()
    assert summary["warnings"] == [_skip_note("A"), _skip_note("B")]
    json.dumps(summary, allow_nan=False)


def test_tree_search_collects_final_full_refine_warnings():
    # 最終フル精密化 (段階 = max_cycles 20) だけが出す文も届く
    search = HypothesisTreeSearch(CycleTaggedBackend())
    result = search.search(GRID, _observed(_phase(4.0, "A")), [_phase(4.05, "A")])

    assert result.final_reports  # 最終フル精密化が実際に走った
    assert "cycles-20" in result.backend_warnings
    assert "cycles-5" in result.backend_warnings  # 探索ノード


def test_multistart_keeps_backend_warnings_apart_from_its_own():
    engine = MultistartEngine(WarningBackend(), config=MultistartConfig(n_starts=4))
    result = engine.run((_phase(4.05, "A"),), GRID, _observed(_phase(4.0, "A")))

    assert result.backend_warnings == (_skip_note("A"),)
    assert result.warnings == ()  # 自身の警告 (全滅) は別の欄


def _series(n_frames: int, *, b_from: int | None = None) -> FrameSeries:
    rows = []
    for i in range(n_frames):
        phases = [_phase(4.0 + 0.002 * i, "A")]
        if b_from is not None and i >= b_from:
            phases.append(_phase(5.64, "B", 0.6))
        rows.append(_observed(*phases))
    return FrameSeries(
        two_theta=GRID,
        intensities=np.asarray(rows),
        axis_values=tuple(float(i) for i in range(n_frames)),
    )


def test_sequential_collects_staged_direct_and_search_warnings():
    # 候補 B は changepoint 時の局所探索でしか精密化されない (B が途中で現れて持続する)
    engine = SequentialEngine(WarningBackend(), candidates=(_phase(5.60, "B"),))
    result = engine.run(_series(6, b_from=2), (_phase(4.05, "A"),))

    assert result.search_results  # 局所探索が実際に走った
    assert result.backend_warnings == (_skip_note("A"), _skip_note("B"))


def test_sequential_collects_each_route_by_cycle_tag():
    # frame0 段階 (20)・後続 direct (10)・局所探索ノード (5) のどれも届く
    engine = SequentialEngine(CycleTaggedBackend(), candidates=(_phase(5.60, "B"),))
    result = engine.run(_series(6, b_from=2), (_phase(4.05, "A"),))

    assert result.search_results
    for tag in ("cycles-20", "cycles-10", "cycles-5"):
        assert tag in result.backend_warnings


def test_sequential_first_frame_staged_alone_is_collected():
    # changepoint が起きない系列 — 段階の文 (20) を出すのは frame0 だけ
    engine = SequentialEngine(CycleTaggedBackend())
    result = engine.run(_series(3), (_phase(4.05, "A"),))

    assert not result.search_results
    assert "cycles-20" in result.backend_warnings


def test_sequential_direct_frames_alone_are_collected():
    # frame0 staged を切っても direct 精密化の警告が届く
    engine = SequentialEngine(
        WarningBackend(), config=SequentialConfig(first_frame_staged=False)
    )
    result = engine.run(_series(3), (_phase(4.05, "A"),))

    assert result.backend_warnings == (_skip_note("A"),)


def test_merge_folds_same_kind_of_per_fit_message_and_counts_the_rest():
    """値だけ違う同種の文 (精密化ごとの μt・ノイズ推定) は最初の 1 文 + 件数に畳む。"""
    merged = merge_warnings(
        ["s=0.1 (n_iterations=3)", "s=0.2 (n_iterations=4)"], ["s=0.3 (n_iterations=4)"]
    )
    assert merged == ("s=0.1 (n_iterations=3) [同種の文 ほか 2 件]",)


def test_merge_does_not_count_identical_text():
    # GSAS は同じ CIF なら毎回同じ文を返す — 回数は数えない (別の精密化結果ではない)
    assert merge_warnings([_skip_note("A")] * 5, [_skip_note("A")]) == (_skip_note("A"),)


def test_merge_keeps_counts_through_nested_results():
    # 段階の結果 (畳み済み) を逐次がさらに束ねても件数が保たれる
    inner = merge_warnings(["rwp=1.5%", "rwp=2.5%"])
    assert merge_warnings(inner, ["rwp=3.5%"]) == merge_warnings(["rwp=1.5%", "rwp=2.5%", "rwp=3.5%"])
    assert merge_warnings(inner, ["rwp=3.5%"]) == ("rwp=1.5% [同種の文 ほか 2 件]",)


def test_merge_keeps_phases_with_digit_names_apart():
    # 相名・パスの数字は値ではない — 別の相の記録を同種として畳まない
    a1 = "相 A1: 特殊位置への吸着を見送った (入力 A1.cif) — 対称操作が無い"
    a2 = "相 A2: 特殊位置への吸着を見送った (入力 A2.cif) — 対称操作が無い"
    assert merge_warnings([a1, a2]) == (a1, a2)


def test_simulated_per_fit_messages_do_not_flood_a_sequential_result():
    """estimate_noise の由来文は精密化ごとに値が違う — 20 フレームでも 1 行に畳まれる。"""
    rng = np.random.default_rng(0)
    rows = [
        _observed(_phase(4.0 + 0.002 * i, "A")) + rng.normal(0.0, 0.01, GRID.size)
        for i in range(20)
    ]
    backend = SimulatedBackend(peak_fwhm=0.2, estimate_noise=True)
    result = SequentialEngine(backend).run(
        FrameSeries(two_theta=GRID, intensities=np.asarray(rows)), (_phase(4.05, "A"),)
    )

    (line,) = result.backend_warnings
    assert line.startswith("ノイズスケール EM 推定") and "[同種の文 ほか" in line


def test_default_simulated_backend_adds_nothing():
    """既定の SimulatedBackend は警告を出さない — 既存の結果に行が増えないこと。"""
    result = analyze_single_pattern(
        GRID, _observed(_phase(4.0, "A")), [[_phase(4.05, "A")]]
    )
    assert result.backend_warnings == ()


class CycleNoteBackend:
    """``max_cycles`` を警告文に書く固定フェイク — どの精密化経路の警告かを見分ける。

    判別では逐次 direct が ``seq_max_cycles``、端点マルチスタートが ``ms_max_cycles`` で呼ぶ。
    """

    name = "cycle-note-fake"

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        return RefinementResult(
            phases=model.phases,
            chi2=10.0 * len(model.phases),
            rwp=5.0,
            n_obs=int(np.asarray(model.intensity).size),
            n_params=0,
            converged=True,
            n_cycles=1,
            free_params=model.free_params,
            warnings=(f"cycles-{max_cycles}",),
        )


def test_discrimination_carries_multistart_backend_warnings_once():
    from tsumugin.operando.discrimination import DiscriminationConfig, discriminate_interval

    config = DiscriminationConfig(
        seq_max_cycles=10, multistart=MultistartConfig(n_starts=2, ms_max_cycles=15)
    )
    series = FrameSeries(two_theta=GRID, intensities=np.ones((4, GRID.size)))
    result = discriminate_interval(
        CycleNoteBackend(), series, (0, 3), (_phase(4.0, "A"),), config=config
    )

    assert result.multistart_single.backend_warnings == ("cycles-15",)
    # 逐次 2 仮説・マルチスタート 4 回ぶんの同じ文は 1 回ずつ
    assert result.warnings.count("cycles-10") == 1
    assert result.warnings.count("cycles-15") == 1


class PhaseCountNoteBackend(CycleNoteBackend):
    """相数と ``max_cycles`` を文に書く — 判別のどの仮説・どの段の警告かを見分ける。"""

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        result = super().refine(model, max_cycles=max_cycles)
        return RefinementResult(
            phases=result.phases, chi2=result.chi2, rwp=result.rwp, n_obs=result.n_obs,
            n_params=result.n_params, converged=True, n_cycles=1,
            free_params=result.free_params,
            warnings=(f"phases-{len(model.phases)} cycles-{max_cycles}",),
        )


def test_discrimination_backend_warnings_follow_execution_order():
    # 仮説 A 逐次 → A 端点マルチスタート → 仮説 B 逐次 → B 端点マルチスタート
    from tsumugin.operando.discrimination import DiscriminationConfig, discriminate_interval

    config = DiscriminationConfig(
        seq_max_cycles=10, multistart=MultistartConfig(n_starts=2, ms_max_cycles=15)
    )
    series = FrameSeries(two_theta=GRID, intensities=np.ones((4, GRID.size)))
    result = discriminate_interval(
        PhaseCountNoteBackend(), series, (0, 3), (_phase(4.0, "A"),), config=config
    )

    tail = [w for w in result.warnings if w.startswith("phases-")]
    assert tail == ["phases-1 cycles-10", "phases-1 cycles-15",
                    "phases-2 cycles-10", "phases-2 cycles-15"]


def _mcp_session(backend):
    from tsumugin.mcp.tools import AnalysisSession
    from tsumugin.model import Project
    from tsumugin.selection import FinalSelectionEngine

    ledger = Ledger()
    return AnalysisSession(
        project=Project(id="proj-0"),
        backend=backend,
        selection=FinalSelectionEngine(mode="agent", ledger=ledger),
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
    )


def test_mcp_submit_single_reports_backend_warnings():
    from tsumugin.mcp.tools import submit_analysis

    response = submit_analysis(
        _mcp_session(WarningBackend()),
        GRID,
        _observed(_phase(4.0, "A")),
        [[_phase(4.05, "A")], [_phase(5.60, "B")]],
    )

    assert response["warnings"] == [_skip_note("A"), _skip_note("B")]
    json.dumps(response, allow_nan=False)


def test_mcp_submit_joint_reports_search_backend_warnings():
    from tsumugin.joint.model import JointHistogram
    from tsumugin.mcp.tools import submit_analysis

    intensity = _observed(_phase(4.0, "A"))
    response = submit_analysis(
        _mcp_session(WarningBackend()),
        GRID,
        intensity,
        [[_phase(4.05, "A")]],
        histograms=(JointHistogram(two_theta=GRID, intensity=intensity, probe="xray"),),
    )

    assert _skip_note("A") in response["warnings"]
    assert len(response["warnings"]) == len(set(response["warnings"]))


def _zno_cif(tmp_path, **kwargs):
    """`tests/autorietveld/test_special_position_snap._zno_cif` (4 桁の 1/3 の ZnO) を借りる。"""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent / "autorietveld" / "test_special_position_snap.py"
    spec = importlib.util.spec_from_file_location("_special_position_snap_fixtures", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._zno_cif(tmp_path, **kwargs)


@pytest.mark.gsas
def test_real_gsas_skipped_snap_reaches_sequential_result(tmp_path):
    """★実 GSAS: 吸着できなかった (対称操作も H-M も無い) CIF の記録が逐次の結果に 1 回届く。

    PR #253 までは判別以外の消費側がこの文を捨てていた (逐次では無言)。
    """
    from tsumugin.backends.gsasii import GSASIIBackend

    cif = _zno_cif(tmp_path, with_symops=False)
    text = cif.read_text(encoding="utf-8")
    cif.write_text(text.replace("_symmetry_space_group_name_H-M 'P 63 m c'\n", ""), encoding="utf-8")
    phase = PhaseInstance(
        phase_ref="zno", lattice=LatticeParams(3.2495, 3.2495, 5.2069, gamma=120.0),
        structure_ref=str(cif),
    )
    backend = GSASIIBackend()
    tt = np.arange(20.0, 80.0, 0.05)
    y = np.asarray(backend.simulate((phase,), tt), dtype=float)
    series = FrameSeries(two_theta=tt, intensities=np.vstack([y, y]))

    engine = SequentialEngine(backend, config=SequentialConfig(first_frame_staged=False))
    result = engine.run(series, (phase,))

    skipped = [w for w in result.backend_warnings if "zno" in w and "H-M" in w]
    assert len(skipped) == 1, result.backend_warnings


def test_mcp_submit_joint_does_not_fold_its_own_warnings(monkeypatch):
    """同種の文を畳むのは backend の警告だけ — 検証の警告は値違いでも別の行に残す。"""
    from tsumugin.joint.model import JointHistogram
    from tsumugin.joint.verification import JointVerificationResult
    from tsumugin.mcp import tools as t

    own = ("joint 検証: rwp=12.3 が残った", "joint 検証: rwp=15.1 が残った")
    monkeypatch.setattr(
        t, "verify_survivors",
        lambda *a, **k: JointVerificationResult(
            verified=(), joint_results={}, recommendations={}, warnings=own
        ),
    )
    intensity = _observed(_phase(4.0, "A"))
    response = t.submit_analysis(
        _mcp_session(SimulatedBackend(peak_fwhm=0.2)),
        GRID,
        intensity,
        [[_phase(4.05, "A")]],
        histograms=(JointHistogram(two_theta=GRID, intensity=intensity, probe="xray"),),
    )

    assert response["warnings"][:2] == list(own)
