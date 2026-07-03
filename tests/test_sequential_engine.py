"""TASK-0019 SequentialEngine (オンライン逐次精密化 + 局所木探索) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/sequential/engine.py`` (**未実装**) の
``SequentialConfig`` / ``SequentialResult`` / ``SequentialEngine.__init__ / run()``。
engine.py 未作成のため collection 時に import が失敗し、本ファイルの全 18 テストがエラー(=失敗)になる想定。

方針 (docs/implements/m2-sequential/TASK-0019/sequential-engine-testcases.md 全 18 件に 1:1 対応):
- backend は原則 ``SimulatedBackend`` (GSAS-II 非依存)。合成シーケンスは格子/相構成を軸に沿って
  変化させたフレーム列を numpy で構築する。グリッドは小さく (``15–60°`` step 0.02、性能 smoke は粗く)。
- テストダブルは ``tests/test_tree_search.py`` の ``FakeBackend`` / ``RecordingSpyBackend`` の流儀を踏襲する。
  warm start 継承 (SE-N02/B03) は refine 入力 phases を記録するスパイ、失敗注入 (SE-E02) は
  フレーム固有 chi2=inf backend、evidence 非改善 (SE-B07) は refs 固定 rwp/chi2 の FakeBackend で制御する。
- 決定論 (SE-B02) は ``==`` ビット同一、物理量近似は ``pytest.approx``、非有限漏洩は ``math.isfinite``。
- 例外 (SE-E03) は ``pytest.raises(NotImplementedError)``、永続化 (SE-B05) は ``tmp_path``。

書式の範: ``tests/test_tree_search.py`` / ``tests/test_changepoint.py`` / ``tests/test_lifecycle.py``。
"""

from __future__ import annotations

import math
from typing import Mapping

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import ExternalChannel, LatticeParams, PhaseInstance
from tsumugin.sequential.series import FrameSeries
from tsumugin.store.persistent import PersistentLedger, PersistentSnapshotStore

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定。
from tsumugin.sequential.engine import (
    SequentialConfig,
    SequentialEngine,
    SequentialResult,
)

# ---------------------------------------------------------------------------
# 共通テストデータ・前提 (モジュールレベルで一度だけ構築し不変共有する)
# ---------------------------------------------------------------------------

# 【観測グリッド】: 全候補のピークが収まる 15–60° / step 0.02。tree.py と同較正でマッチングを安定化 🔵/🟡
GRID = np.arange(15.0, 60.0, 0.02)
# 【高速グリッド】: 100 フレーム性能 smoke 用の粗い小グリッド (changepoint 非発火・実行時間抑制) 🟡
GRID_FAST = np.arange(15.0, 40.0, 0.05)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンスを作る (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _refs(phases) -> set[str]:
    """相集合 (phase_ref の集合) を返す。"""
    return {p.phase_ref for p in phases}


def _true_a(a0: float, delta: float, i: int) -> float:
    """フレーム i の真の格子定数 a (線形膨張)。"""
    return a0 + delta * i


def _expansion_intensities(
    *, a0: float, delta: float, n_frames: int, grid: np.ndarray, scale: float = 1.0
) -> np.ndarray:
    """格子 a が線形膨張する単一相 A の (n_frames, n_points) 強度行列を作る。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    if n_frames == 0:
        return np.empty((0, grid.size), dtype=float)
    rows = [
        backend.simulate([_phase(_true_a(a0, delta, i), "A", scale=scale)], grid)
        for i in range(n_frames)
    ]
    return np.asarray(rows, dtype=float)


def _expansion_series(
    *, a0: float = 5.0, delta: float = 0.01, n_frames: int = 20,
    grid: np.ndarray = GRID, scale: float = 1.0,
) -> FrameSeries:
    """線形膨張シーケンス (相構成不変・changepoint なし想定) を組む。"""
    intensities = _expansion_intensities(
        a0=a0, delta=delta, n_frames=n_frames, grid=grid, scale=scale
    )
    return FrameSeries(two_theta=grid, intensities=intensities)


def _phase_b_intensities(
    *, n_frames: int, b_onset: int, a: float = 5.0, b: float = 6.0, grid: np.ndarray = GRID
) -> np.ndarray:
    """frame < b_onset は相 A のみ、frame >= b_onset は A+B の強度行列を作る。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    rows = []
    for i in range(n_frames):
        phases = [_phase(a, "A")]
        if i >= b_onset:
            phases.append(_phase(b, "B"))
        rows.append(backend.simulate(phases, grid))
    return np.asarray(rows, dtype=float)


def _phase_b_series(
    *, n_frames: int = 16, b_onset: int = 10, grid: np.ndarray = GRID
) -> FrameSeries:
    """相 B が中間フレームで出現するシーケンス (changepoint → 局所探索 → 採択の検証用)。"""
    intensities = _phase_b_intensities(n_frames=n_frames, b_onset=b_onset, grid=grid)
    return FrameSeries(two_theta=grid, intensities=intensities)


# ---------------------------------------------------------------------------
# テストダブル (warm start 観測・失敗注入・rwp/chi2 制御)
# ---------------------------------------------------------------------------


class PhaseRecordingSpyBackend:
    """SimulatedBackend へ委譲しつつ refine の入力 phases (格子 a / scale) と max_cycles を記録する。

    後続フレームの direct refine は ``max_cycles == seq_max_cycles`` で識別でき (frame0 staged は
    既定 20、局所探索は explore_max_cycles=5)、warm start 継承 (SE-N02) と inherit="lattice_only"
    (SE-B03) の入力契約を観測する。
    """

    name = "phasespy"

    def __init__(self) -> None:
        self._sim = SimulatedBackend(peak_fwhm=0.2)
        # (input_a, input_scale, max_cycles) をフレーム順に記録する
        self.refine_calls: list[tuple[float, float, int]] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        p0 = model.phases[0]
        self.refine_calls.append((p0.lattice.a, p0.scale, max_cycles))
        return self._sim.refine(model, max_cycles=max_cycles)

    def direct_calls(self, seq_max_cycles: int) -> list[tuple[float, float]]:
        """direct refine (後続フレーム) の (input_a, input_scale) をフレーム順で返す。"""
        return [(a, s) for (a, s, mc) in self.refine_calls if mc == seq_max_cycles]


class FrameFailBackend:
    """特定フレームの強度に対してのみ chi2=inf/converged=False を返す精密化失敗注入 backend (EDGE-002)。

    ``model.intensity`` が指定の失敗フレーム強度に一致したとき非収束結果を返し、他は SimulatedBackend
    へ委譲する。frame0 staged や局所探索の refine は対象外強度なので正常に通る。
    """

    name = "framefail"

    def __init__(self, fail_intensity: np.ndarray) -> None:
        self._sim = SimulatedBackend(peak_fwhm=0.2)
        self._fail = np.asarray(fail_intensity, dtype=float)

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        intensity = np.asarray(model.intensity, dtype=float)
        if intensity.shape == self._fail.shape and np.array_equal(intensity, self._fail):
            return RefinementResult(
                phases=model.phases,
                chi2=float("inf"),
                rwp=float("inf"),
                n_obs=int(intensity.size),
                n_params=len(model.free_params),
                converged=False,
                n_cycles=0,
                free_params=frozenset(model.free_params),
            )
        return self._sim.refine(model, max_cycles=max_cycles)


class FakeBackend:
    """相組合せ (phase_ref の frozenset) をキーに固定 (rwp, chi2) を返す決定論スタブ。

    evidence 非改善 (SE-B07) を厳密制御する: 現行相 {A} を最良 (低 rwp/chi2)、新構成 {A,B} を劣位に
    設定し、局所探索の最良仮説が現行と同集合になる (=採択されず reject) 状況を作る。simulate/peak_positions
    は内蔵 SimulatedBackend へ委譲し、観測ピーク経路 (新規未マッチ→changepoint) を成立させる。
    """

    name = "fake"

    def __init__(
        self,
        *,
        rwp_by_refs: dict[frozenset[str], float] | None = None,
        chi2_by_refs: dict[frozenset[str], float] | None = None,
        default_rwp: float = 50.0,
        default_chi2: float = 10.0,
    ) -> None:
        self._sim = SimulatedBackend(peak_fwhm=0.2)
        self._rwp = dict(rwp_by_refs or {})
        self._chi2 = dict(chi2_by_refs or {})
        self._default_rwp = float(default_rwp)
        self._default_chi2 = float(default_chi2)
        self.refine_calls: list[frozenset[str]] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        refs = frozenset(p.phase_ref for p in model.phases)
        self.refine_calls.append(refs)
        rwp = self._rwp.get(refs, self._default_rwp)
        chi2 = self._chi2.get(refs, self._default_chi2)
        n_obs = int(np.asarray(model.intensity).size)
        return RefinementResult(
            phases=model.phases,
            chi2=chi2,
            rwp=rwp,
            n_obs=n_obs,
            n_params=len(model.free_params),
            converged=math.isfinite(chi2),
            n_cycles=1,
            free_params=frozenset(model.free_params),
        )


# ---------------------------------------------------------------------------
# 1. 正常系テストケース (SE-N01〜SE-N07)
# ---------------------------------------------------------------------------


def test_linear_expansion_tracks_true_lattice():
    # 【テスト目的】: 線形膨張 20 フレームで精密化格子が真値 ±0.01 Å を追跡することを確認 (SE-N01/TC-101-01)
    # 【テスト内容】: SimulatedBackend の膨張シーケンスに対する SequentialEngine.run() の逐次追従
    # 【期待される動作】: 各 record.phases[0].lattice.a == approx(真値_i, abs=0.01)、行数=20、失敗なし
    # 🔵 信頼性レベル: 完了条件① / TC-101-01 / REQ-001 に直接依拠

    # 【テストデータ準備】: a0=5.0 から 0.01*i で線形膨張させた (20, n_points) 強度行列
    # 【初期条件設定】: 単一相 A・相構成不変 (changepoint なし)・候補プール空
    backend = SimulatedBackend(peak_fwhm=0.2)
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=20)

    # 【実際の処理実行】: frame0 staged 確立 → 後続 warm start direct refine のフルパス
    result = SequentialEngine(backend).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 各フレームの主相格子が真値近傍を追跡し非有限が漏れない
    records = result.trajectory.records
    assert len(records) == 20  # 【確認内容】: 行数=フレーム数 🔵
    for i, rec in enumerate(records):
        # 【期待値確認】: フレーム i の格子 a が真値 ±0.01 (warm start 逐次追従) 🔵
        assert rec.phases[0].lattice.a == pytest.approx(_true_a(5.0, 0.01, i), abs=0.01)
        assert rec.refine_failed is False  # 【確認内容】: 全フレーム精密化成功 🔵
        assert rec.rwp is None or math.isfinite(rec.rwp)  # 【確認内容】: 非有限 rwp を漏らさない 🔵


def test_warm_start_inherits_previous_frame_phases():
    # 【テスト目的】: フレーム i の direct refine 入力 phases が i−1 の出力 phases に一致 (SE-N02/TC-101-02)
    # 【テスト内容】: refine 入力を記録する spy で warm start 継承経路 (inherit="phases" 既定) を観測
    # 【期待される動作】: 各 direct 呼び (max_cycles==seq_max_cycles) の入力 a == records[i-1] の出力 a
    # 🔵 信頼性レベル: 完了条件① / TC-101-02 に直接依拠 (spy は test_tree_search.py 踏襲)

    # 【テストデータ準備】: SE-N01 と同じ線形膨張。seq_max_cycles=7 で staged(20)/探索(5) と識別可能化
    spy = PhaseRecordingSpyBackend()
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=8)
    config = SequentialConfig(seq_max_cycles=7)

    # 【実際の処理実行】: staged(frame0) → direct refine(frame1..7) の継承境界を通す
    result = SequentialEngine(spy, config=config).run(series, [_phase(5.0, "A")])

    # 【結果検証】: direct 呼びはフレーム順に n-1 件で、各入力 = 前フレーム出力の格子 (ビット一致)
    records = result.trajectory.records
    direct = spy.direct_calls(seq_max_cycles=7)
    assert len(direct) == len(records) - 1  # 【確認内容】: 後続フレームごとに 1 回の direct refine 🔵
    for i in range(1, len(records)):
        input_a, _input_scale = direct[i - 1]
        # 【期待値確認】: frame i の入力格子 == frame i-1 の出力格子 (warm start 継承の契約) 🔵
        assert input_a == records[i - 1].phases[0].lattice.a


def test_phase_b_emergence_triggers_changepoint():
    # 【テスト目的】: 相 B 出現フレームで changepoint が判定されることを確認 (SE-N03/TC-102-01)
    # 【テスト内容】: frame0-9=A のみ / frame10+=A+B のシーケンスで frame10 が新規未マッチで発火
    # 【期待される動作】: records[10].changepoint == True、"new_peaks" が理由に含まれ search_results に 10
    # 🔵 信頼性レベル: 完了条件② / TC-102-01 / REQ-003/101 に依拠

    # 【テストデータ準備】: 中間フレーム 10 から相 B のピークが出現する 16 フレーム列
    # 【初期条件設定】: 候補プールに B を供給し局所探索が B を発見できるようにする
    series = _phase_b_series(n_frames=16, b_onset=10)
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: 相 B 出現フレームで changepoint が立ち、新規未マッチが理由に含まれる
    rec10 = result.trajectory.records[10]
    assert rec10.changepoint is True  # 【確認内容】: warm-up (window=5) 経過後に発火 🔵
    assert "new_peaks" in rec10.changepoint_reasons  # 【確認内容】: 新規未マッチピークが発火理由 🔵
    assert 10 in result.search_results  # 【確認内容】: 発火フレームで局所探索が起動し記録される 🔵


def test_local_search_adopts_phase_b_and_continues():
    # 【テスト目的】: changepoint の局所探索が B 込み仮説を採択し以後 B 込みで継続する (SE-N04/TC-102-03)
    # 【テスト内容】: evidence 改善する A+B 構成を採択し、以降フレームの相集合に B が恒常的に含まれる
    # 【期待される動作】: 後半フレームの相集合に "B"、ledger に "adopt" 記録、採択は一度きり
    # 🔵 信頼性レベル: 完了条件② / TC-102-03 / D3 に依拠

    # 【テストデータ準備】: SE-N03 と同じ B 出現シーケンス。evidence 既定 BIC で A+B が改善する
    series = _phase_b_series(n_frames=16, b_onset=10)
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: 採択後フレームで B が相集合に恒常的に含まれ、採択は理由付き ledger 記録が残る
    assert "B" in _refs(result.trajectory.records[15].phases)  # 【確認内容】: 以後 B 込みで継続 🔵
    assert "B" in _refs(result.trajectory.records[12].phases)  # 【確認内容】: 採択直後から B が継続 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "adopt" in kinds  # 【確認内容】: 採択が kind="adopt" 相当で記録される 🔵
    assert len(result.search_results) == 1  # 【確認内容】: 再探索は起きず採択は一度きり (warm start 継続) 🔵


def test_tree_search_runs_only_on_changepoint_frames():
    # 【テスト目的】: 局所木探索が changepoint 発火フレームでのみ起動することを確認 (SE-N05/TC-102-02)
    # 【テスト内容】: search_results のキー数 == changepoint フレーム数、非発火フレームでは非起動
    # 【期待される動作】: len(search_results) == sum(record.changepoint)、全キーが changepoint フレーム
    # 🔵 信頼性レベル: 完了条件③ / TC-102-02 / EDGE-104 に直接依拠

    # 【テストデータ準備】: SE-N03 の B 出現シーケンス (発火は frame10 の 1 回のみが期待値)
    series = _phase_b_series(n_frames=16, b_onset=10)
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: 局所起動の計算量制御 (P5) — 探索回数が changepoint 数に厳密一致し無駄打ちが無い
    records = result.trajectory.records
    changepoint_frames = {i for i, r in enumerate(records) if r.changepoint}
    assert len(result.search_results) == len(changepoint_frames)  # 探索回数==発火フレーム数 🔵
    assert set(result.search_results) == changepoint_frames  # 全キーが発火フレームに一致 🔵
    for i, rec in enumerate(records):
        if not rec.changepoint:
            assert i not in result.search_results  # 【確認内容】: 非発火フレームでは非起動 🔵


def test_trajectory_assembly_is_complete():
    # 【テスト目的】: Trajectory 組立の完全性 (行数/軸値/lifecycles/frame_range) を確認 (SE-N06)
    # 【テスト内容】: 行数=フレーム数、axis_value/temperature が channels 由来、確定相 lifecycle と採択区間
    # 【期待される動作】: len(records)==n、axis_value/temperature 反映、lifecycles に確定相、frame_range 保持
    # 🔵🟡 信頼性レベル: 完了条件②⑥ / FR-306 / dataflow データ整合性 (lifecycle 反映詳細は 🟡)

    # 【テストデータ準備】: B 出現シーケンス + 軸値 (index) + 温度チャネル (300+i) を紐付ける
    n_frames = 16
    intensities = _phase_b_intensities(n_frames=n_frames, b_onset=10)
    axis_values = tuple(float(i) for i in range(n_frames))
    channel = ExternalChannel(
        kind="temperature", sync_map={i: 300.0 + i for i in range(n_frames)}
    )
    series = FrameSeries(
        two_theta=GRID, intensities=intensities, axis_values=axis_values,
        axis_kind="time", channels=(channel,),
    )
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: FR-306 の出力契約 — 行数一致・軸値/温度反映・lifecycle 確定・採択区間保持
    records = result.trajectory.records
    assert len(records) == n_frames  # 【確認内容】: 行数=フレーム数 (データ整合性) 🔵
    assert records[8].axis_value == 8.0  # 【確認内容】: axis_value が series.axis_values 由来 🟡
    assert records[8].temperature == pytest.approx(308.0)  # 【確認内容】: 温度が channel 由来 🟡
    lifecycles = result.trajectory.lifecycles
    assert "A" in lifecycles  # 【確認内容】: 全フレーム存在の A が lifecycle 確定 🔵
    assert lifecycles["B"].birth_frame is not None  # 【確認内容】: 出現・確定した B の birth 確定 🟡
    assert any(
        h.frame_range is not None and "B" in _refs(h.phases)
        for h in result.hypotheses.values()
    )  # 【確認内容】: 採択仮説が frame_range 付きで系譜に登録される 🟡


def test_sequential_result_structure_and_ledger_records():
    # 【テスト目的】: SequentialResult 構造と ledger の adopt/reject 記録を確認 (SE-N07)
    # 【テスト内容】: first_frame_report 非 None、search_results が frame_index キー、hypotheses/warnings 契約
    # 【期待される動作】: first_frame_report 非 None、int キー Mapping、adopt 記録、warnings は tuple
    # 🔵🟡 信頼性レベル: 完了条件② / D3 / interfaces.py L224-234 に依拠 (ledger kind 名は 🟡)

    # 【テストデータ準備】: B 出現シーケンス (staged 確立 + 採択を含むフルパス)
    series = _phase_b_series(n_frames=16, b_onset=10)
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: interfaces.py L224-234 の出力契約を網羅する
    assert result.first_frame_report is not None  # 【確認内容】: first_frame_staged=True で非 None 🟡
    assert isinstance(result.search_results, Mapping)  # 【確認内容】: search_results は Mapping 🔵
    records = result.trajectory.records
    changepoint_frames = {i for i, r in enumerate(records) if r.changepoint}
    for key in result.search_results:
        assert isinstance(key, int)  # 【確認内容】: キーは frame_index (int) 🔵
        assert key in changepoint_frames  # 【確認内容】: 全キーが changepoint フレーム 🔵
    kinds = [e.kind for e in result.ledger.entries]
    assert "adopt" in kinds  # 【確認内容】: 採択が理由付き ledger 記録される 🟡
    assert result.hypotheses  # 【確認内容】: 採択構成の系譜 hypotheses は非空 🔵
    assert isinstance(result.warnings, tuple)  # 【確認内容】: warnings は tuple (既定 空) 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (SE-E01〜SE-E04)
# ---------------------------------------------------------------------------


def test_empty_series_returns_empty_trajectory_without_error():
    # 【テスト目的】: 空フレーム列で空 Trajectory を返し例外化しない (SE-E01/TC-101-05/EDGE-001)
    # 【テスト内容】: n_frames=0 の強度行列を渡し、全コレクションが空値へ安全側縮退する
    # 【期待される動作】: records==()、lifecycles=={}、first_frame_report is None、search_results=={}
    # 🔵 信頼性レベル: 完了条件④ / TC-101-05 / EDGE-001 に直接依拠

    # 【テストデータ準備】: 測定フィルタ後に全フレーム除外された等の空入力 (n_frames=0)
    series = _expansion_series(n_frames=0)

    # 【実際の処理実行】: 空入力でも例外を投げず実体を返す (下流 CSV 出力を破綻させない)
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2)).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 全コレクションが空値へ縮退し例外が送出されない
    assert result.trajectory.records == ()  # 【確認内容】: 空フレーム列 🔵
    assert dict(result.trajectory.lifecycles) == {}  # 【確認内容】: 空 lifecycles 🔵
    assert result.first_frame_report is None  # 【確認内容】: staged 確立入力すら無いため None 🔵
    assert dict(result.search_results) == {}  # 【確認内容】: 局所探索なし 🔵


def test_failed_frame_continues_with_warning_and_last_success_warm_start():
    # 【テスト目的】: 失敗フレーム (chi2=inf) を継続し警告 + 直近成功 warm start (SE-E02/TC-101-07/EDGE-002)
    # 【テスト内容】: frame7 の refine に chi2=inf を注入し、非有限漏洩なしで完走・継続することを確認
    # 【期待される動作】: records[7] は refine_failed/rwp=None/chi2=None、warnings 追加、frame8 は正常継続
    # 🟡 信頼性レベル: 完了条件④ / TC-101-07 / EDGE-002 (warm start 詳細は 🟡)

    # 【テストデータ準備】: 線形膨張 12 フレーム。frame7 の強度に一致する refine のみ失敗させる
    n_frames = 12
    intensities = _expansion_intensities(a0=5.0, delta=0.01, n_frames=n_frames, grid=GRID)
    series = FrameSeries(two_theta=GRID, intensities=intensities)
    backend = FrameFailBackend(fail_intensity=intensities[7])

    # 【実際の処理実行】: 単一フレーム失敗で全系列を止めず直近成功から継続する (M1 教訓)
    result = SequentialEngine(backend).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 失敗フレームは行を保持しつつ None 値化し、非有限を FrameRecord/CSV に漏らさない
    records = result.trajectory.records
    assert len(records) == n_frames  # 【確認内容】: 失敗フレームも 1 行 (行数=フレーム数) 🟡
    assert records[7].refine_failed is True  # 【確認内容】: 失敗フラグ 🟡
    assert records[7].rwp is None  # 【確認内容】: 非有限 rwp を None で伝播 🟡
    assert records[7].chi2 is None  # 【確認内容】: 非有限 chi2 を None で伝播 🟡
    assert len(result.warnings) >= 1  # 【確認内容】: 失敗フレームの警告が積まれる 🟡
    assert records[8].refine_failed is False  # 【確認内容】: 継続後フレームは正常精密化 🟡
    # 【期待値確認】: 直近成功 (frame6) から継続し frame8 の格子が真値近傍を保つ 🟡
    assert records[8].phases[0].lattice.a == pytest.approx(_true_a(5.0, 0.01, 8), abs=0.05)
    for rec in records:
        # 【非有限漏洩検証】: 全 record の rwp/chi2 は None か有限のみ (inf/nan を漏らさない) 🔵
        assert rec.rwp is None or math.isfinite(rec.rwp)
        assert rec.chi2 is None or math.isfinite(rec.chi2)


def test_native_orchestration_raises_not_implemented():
    # 【テスト目的】: orchestration="native" が NotImplementedError を送出する (SE-E03/REQ-105)
    # 【テスト内容】: native 協調精密化は M-later スコープ。誤動作でなく明示的に未実装を通知
    # 【期待される動作】: run() が NotImplementedError を送出する (副作用を起こさず早期に)
    # 🔵 信頼性レベル: 完了条件⑦ / REQ-105 / FR-302 に直接依拠

    # 【テストデータ準備】: 任意の有効な単一フレーム series と native 設定
    series = _expansion_series(n_frames=1)
    engine = SequentialEngine(
        SimulatedBackend(peak_fwhm=0.2), config=SequentialConfig(orchestration="native")
    )

    # 【結果検証】: 未実装モードは明示的な例外で通知される
    with pytest.raises(NotImplementedError):
        engine.run(series, [_phase(5.0, "A")])  # 【確認内容】: native は NotImplementedError 🔵


def test_all_frames_changepoint_completes_run():
    # 【テスト目的】: 全フレーム changepoint でも例外なく完走する (SE-E04/TC-102-05/EDGE-103)
    # 【テスト内容】: 候補プール空 + 常時未マッチ (A+B データを A のみで説明) で毎フレーム発火させる
    # 【期待される動作】: 例外なく完走、行数=フレーム数、探索回数==発火数、決定論維持
    # 🟡 信頼性レベル: 完了条件⑧ / TC-102-05 / EDGE-103 (全発火合成の作り込みは 🟡)

    # 【テストデータ準備】: frame0 から A+B データだが候補プール空のため B を採択できず未マッチが継続
    n_frames = 12
    intensities = _phase_b_intensities(n_frames=n_frames, b_onset=0)
    series = FrameSeries(two_theta=GRID, intensities=intensities)

    # 【実際の処理実行】: 高頻度探索でもメモリ/状態を破綻させず Trajectory を返すことを確認
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: 完走が主眼 (物理的正しさは問わない)。探索回数と発火フレームの整合が保たれる
    records = result.trajectory.records
    assert len(records) == n_frames  # 【確認内容】: 探索連発でも行数=フレーム数 🟡
    changepoint_frames = {i for i, r in enumerate(records) if r.changepoint}
    assert len(result.search_results) == len(changepoint_frames)  # 探索回数==発火数 (連発でも整合) 🟡
    assert len(changepoint_frames) >= 1  # 【確認内容】: warm-up 後に高頻度発火し重い経路を実行 🟡
    assert isinstance(result, SequentialResult)  # 【確認内容】: 例外なく実体を返す 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース (SE-B01〜SE-B07)
# ---------------------------------------------------------------------------


def test_single_frame_yields_length_one_trajectory():
    # 【テスト目的】: 単一フレームで長さ 1 の Trajectory を返す (SE-B01/TC-101-06/EDGE-101)
    # 【テスト内容】: n_frames=1 で frame0 staged 確立のみが走り changepoint/warm start が非発火
    # 【期待される動作】: len(records)==1、first_frame_report 非 None、search_results=={}
    # 🔵 信頼性レベル: 完了条件④ / TC-101-06 / EDGE-101 に直接依拠

    # 【テストデータ準備】: 後続フレーム無しの最小非空境界 (n_frames=1)
    series = _expansion_series(n_frames=1)

    # 【実際の処理実行】: staged 確立のみで長さ 1 の Trajectory へ写像する
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2)).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 空 (n=0) と 2 フレーム以上の中間として一貫した振る舞い
    assert len(result.trajectory.records) == 1  # 【確認内容】: 長さ 1 の Trajectory 🔵
    assert result.first_frame_report is not None  # 【確認内容】: staged 確立結果が存在 🔵
    assert dict(result.search_results) == {}  # 【確認内容】: warm-up で changepoint 非発火 🔵


def test_deterministic_bit_identical_across_runs():
    # 【テスト目的】: 同一入力 2 回実行で全出力がビット同一 (SE-B02/TC-101-04/REQ-402)
    # 【テスト内容】: changepoint・局所探索・採択を含む複雑経路で決定論が崩れないことを確認
    # 【期待される動作】: records/hypotheses キー/search_results キー/ledger kind 列がビット同一
    # 🔵 信頼性レベル: 完了条件⑤ / TC-101-04 / REQ-402 に直接依拠

    def once() -> SequentialResult:
        series = _phase_b_series(n_frames=16, b_onset=10)
        engine = SequentialEngine(
            SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]
        )
        return engine.run(series, [_phase(5.0, "A")])

    # 【テストデータ準備】: 新規エンジン同士で 2 回独立実行し pytest.approx を使わず == で比較
    r1, r2 = once(), once()

    # 【結果検証】: 乱数なし・安定ソート・dict 反復順非依存が全経路で守られる (ビット同一)
    assert r1.trajectory.records == r2.trajectory.records  # 【確認内容】: FrameRecord tuple がビット同一 🔵
    assert list(r1.hypotheses.keys()) == list(r2.hypotheses.keys())  # ID 採番が入力順非依存 🔵
    assert list(r1.search_results.keys()) == list(r2.search_results.keys())  # キー列一致 🔵
    assert [e.kind for e in r1.ledger.entries] == [
        e.kind for e in r2.ledger.entries
    ]  # 【確認内容】: ledger の kind 列が同順 (hash 連鎖の決定論) 🔵


def test_inherit_lattice_only_resets_scale_and_carries_lattice():
    # 【テスト目的】: inherit="lattice_only" が格子のみ継承し scale をリセットする (SE-B03/TC-101-03)
    # 【テスト内容】: data scale=3.0 に対し direct refine 入力 scale が初期値 1.0 のままで格子は継承される
    # 【期待される動作】: 各 direct 入力 scale==1.0 (リセット)、入力 a==前フレーム出力 a (継承)、追従維持
    # 🟡 信頼性レベル: 完了条件⑥ / TC-101-03 (lattice_only セマンティクス詳細は 🟡)

    # 【テストデータ準備】: 真の scale=3.0 の膨張シーケンス。初期相 scale=1.0 で継承/リセットを区別
    spy = PhaseRecordingSpyBackend()
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=8, scale=3.0)
    config = SequentialConfig(inherit="lattice_only", seq_max_cycles=7)

    # 【実際の処理実行】: 継承粒度を格子のみに限定した warm start を通す
    result = SequentialEngine(spy, config=config).run(series, [_phase(5.0, "A", scale=1.0)])

    # 【結果検証】: 格子は前フレーム出力を継承・scale は初期値へリセットされる (継承粒度の切替反映)
    records = result.trajectory.records
    direct = spy.direct_calls(seq_max_cycles=7)
    assert len(direct) == len(records) - 1  # 【確認内容】: 後続フレームごとに direct refine 1 回 🟡
    for i in range(1, len(records)):
        input_a, input_scale = direct[i - 1]
        assert input_scale == 1.0  # 【確認内容】: scale は継承されず初期値 1.0 へリセット 🟡
        assert input_a == records[i - 1].phases[0].lattice.a  # 【確認内容】: 格子のみ継承 🟡
    # 【期待値確認】: lattice_only でも格子追従性は保たれ真値近傍を追跡する 🟡
    assert records[-1].phases[0].lattice.a == pytest.approx(_true_a(5.0, 0.01, 7), abs=0.02)


def test_smoke_hundred_frames_within_time_budget():
    # 【テスト目的】: 100 フレーム (changepoint なし) が 60 秒以内に完了する (SE-B04/TC-108-03/NFR-001)
    # 【テスト内容】: 滑らかな線形膨張 100 フレーム (局所探索コスト非混入) の direct refine 支配経路の性能
    # 【期待される動作】: run() が 60 秒以内、len(records)==100、changepoint 非発火
    # 🟡 信頼性レベル: 完了条件⑨ / TC-108-03 / NFR-001 (閾値・マーク方針は 🟡)

    import time

    # 【テストデータ準備】: 粗い小グリッドの滑らかな膨張 100 フレーム (発火を抑制して探索コスト混入を防ぐ)
    series = _expansion_series(a0=5.0, delta=0.005, n_frames=100, grid=GRID_FAST)

    # 【実際の処理実行】: direct refine (~7 パラメータ × ≤10 cycles) が線形にスケールする
    start = time.perf_counter()
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2)).run(series, [_phase(5.0, "A")])
    elapsed = time.perf_counter() - start

    # 【結果検証】: 実用規模の最小担保 — 時間予算内で全フレームを処理し局所探索を混入させない
    assert len(result.trajectory.records) == 100  # 【確認内容】: 100 フレーム完走 🟡
    assert dict(result.search_results) == {}  # 【確認内容】: changepoint 非発火で探索ゼロ 🟡
    assert elapsed < 60.0  # 【確認内容】: 60 秒以内 (NFR-001 性能境界) 🟡


def test_persistent_store_injection_runs_m2_path(tmp_path):
    # 【テスト目的】: PersistentLedger/Store 注入で M2 経路が無改変で動く (SE-B05/TC-106-06 相当)
    # 【テスト内容】: JSONL パスの永続版 ledger/snapshots を注入して逐次解析が同一意味論で完走する
    # 【期待される動作】: run() 完走、pl.verify()==True、JSONL 追記され再オープンで verify True
    # 🔵 信頼性レベル: 追加 / TC-106-06 相当 / REQ-012 に依拠 (note.md 注意事項)

    # 【テストデータ準備】: tmp_path の JSONL で Persistent 版を構築し engine へ注入 (in-memory と同契約)
    ledger_path = tmp_path / "ledger.jsonl"
    snap_path = tmp_path / "snapshots.jsonl"
    pl = PersistentLedger(ledger_path)
    ps = PersistentSnapshotStore(snap_path, ledger=pl)
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=6)

    # 【実際の処理実行】: 台帳/スナップショットを差し替えても M2 経路が同一意味論で動く
    result = SequentialEngine(
        SimulatedBackend(peak_fwhm=0.2), ledger=pl, snapshots=ps
    ).run(series, [_phase(5.0, "A")])

    # 【結果検証】: append のみで成長し、再オープンしても改竄検証が通る (監査一貫性)
    assert len(result.trajectory.records) == 6  # 【確認内容】: 注入版でも逐次解析が完走 🔵
    assert result.ledger is pl  # 【確認内容】: 注入した ledger 実体がそのまま返る 🔵
    assert pl.verify() is True  # 【確認内容】: 追記チェーンが無傷 🔵
    assert ledger_path.exists()  # 【確認内容】: JSONL ファイルへ追記される 🔵
    assert PersistentLedger(ledger_path).verify() is True  # 再オープンで verify True 🔵


def test_smooth_series_has_no_changepoint_and_empty_search():
    # 【テスト目的】: 滑らかシーケンスで木探索ゼロ・search_results 空を確認 (SE-B06/TC-102-04)
    # 【テスト内容】: 相構成不変・滑らかな線形膨張で発火閾値を一度も超えず探索が完全抑制される
    # 【期待される動作】: 全 record.changepoint==False、search_results=={}
    # 🔵 信頼性レベル: 完了条件③ 補完 / TC-102-04 に依拠

    # 【テストデータ準備】: SE-N01 相当の滑らかな膨張 (格子差分の robust z が閾値未満に留まる)
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=15)

    # 【実際の処理実行】: 線形膨張が誤発火しないこと (changepoint.py の差分ベース判定に依拠)
    result = SequentialEngine(
        SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]
    ).run(series, [_phase(5.0, "A")])

    # 【結果検証】: SE-N05 の対極 — 発火ゼロで探索が完全に抑制される
    assert all(not rec.changepoint for rec in result.trajectory.records)  # 全フレーム非発火 🔵
    assert dict(result.search_results) == {}  # 【確認内容】: 木探索ゼロ・search_results 空 🔵


def test_non_improving_evidence_keeps_current_and_records_reject():
    # 【テスト目的】: evidence 非改善時は現行構成を維持し reject 記録する (SE-B07/D3)
    # 【テスト内容】: changepoint は発火するが最良仮説が現行 {A} と同集合になり採択されない境界
    # 【期待される動作】: 相構成が {A} のまま、ledger に "reject"、search_results 記録あり・新採択なし
    # 🟡 信頼性レベル: 完了条件② / D3 (evidence 同値=非改善の境界解釈は 🟡)

    # 【テストデータ準備】: A+B データ (新規未マッチで発火) だが FakeBackend で {A} を最良に固定
    series = _phase_b_series(n_frames=13, b_onset=10)
    backend = FakeBackend(
        rwp_by_refs={
            frozenset({"A"}): 5.0,
            frozenset({"B"}): 60.0,
            frozenset({"A", "B"}): 55.0,
        },
        chi2_by_refs={
            frozenset({"A"}): 5.0,
            frozenset({"B"}): 60.0,
            frozenset({"A", "B"}): 55.0,
        },
    )

    # 【実際の処理実行】: 局所探索は起動するが最良仮説 {A} が現行と同集合で改善しない
    result = SequentialEngine(backend, candidates=[_phase(6.0, "B")]).run(
        series, [_phase(5.0, "A")]
    )

    # 【結果検証】: 「evidence 改善時のみ採択」の否定側 — 現行維持 + 棄却の理由付き記録
    records = result.trajectory.records
    assert all("B" not in _refs(rec.phases) for rec in records)  # 相構成は {A} のまま維持 🟡
    assert len(result.search_results) >= 1  # 【確認内容】: changepoint で探索は起動し記録される 🟡
    kinds = [e.kind for e in result.ledger.entries]
    assert "reject" in kinds  # 【確認内容】: 棄却も理由付き ledger 記録 (説明可能性) 🟡
    assert not any(
        h.frame_range is not None and "B" in _refs(h.phases)
        for h in result.hypotheses.values()
    )  # 【確認内容】: 新採択 (B 込み frame_range) が増えない 🟡


# ---------------------------------------------------------------------------
# PR #2 レビュー指摘対応 (履歴量子化の挙動を回帰テストで固定)
# ---------------------------------------------------------------------------


def test_quantize_history_suppresses_noise_floor_but_keeps_real_change():
    # 【テスト目的】: changepoint 履歴の 6 桁量子化 (小数第 6 位) の両側挙動を固定する
    #   (a) 1e-7 級のノイズフロアジッタは同一値に潰れる (偽発火の材料を消す)
    #   (b) 1e-4 級の真の緩慢な変化は量子化後も区別可能 (真の変化を潰さない)
    q = SequentialEngine._quantize_history
    # (a) ノイズフロア: 5.0 ± 1e-8 は全て同一値へ
    assert q(5.0 + 1e-8) == q(5.0) == q(5.0 - 1e-8) == 5.0
    # (b) 物理的に意味のある変化 (1e-4 Å 級) は保存される
    assert q(5.0001) != q(5.0)
    # 丸めは小数第 6 位固定 (round half to even) であることを固定
    assert q(1.2345678) == 1.234568
