"""TASK-0022 公開 API 統合 + E2E (M2 総仕上げ) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/__init__.py`` への M2 公開シンボル re-export
(``SequentialEngine`` / ``SequentialConfig`` / ``SequentialResult`` / ``FrameSeries`` /
``FrameRecord`` / ``Trajectory`` / ``ExternalChannel`` / ``PhaseLifecycle`` /
``PersistentLedger`` / ``PersistentSnapshotStore`` / ``FinalSelectionEngine`` / ``Decision`` /
``ReviewQueue`` / ``ReviewItem`` / ``detect_escalations`` / ``detect_changepoint`` /
``estimate_transition`` / ``fit_thermal_baseline`` / ``LifecycleTracker`` / ``ThermalBaseline`` /
``TransitionEstimate`` / ``ChangepointConfig`` / ``ChangepointSignal`` / ``LifecycleConfig`` /
``phase_to_dict`` / ``phase_from_dict``) と、公開 API 経由の一気通貫 E2E 結線検証。

Red の失敗機構: 本モジュール冒頭の ``from tsumugin import SequentialEngine, ...`` は M2 分が
トップレベル未 re-export (現状 M0 + M1 分のみ) のため collection 時に ImportError となり、
本ファイルの全テストが失敗する (テストケース定義書 §4 テスト実装方針)。``tests/test_m1_e2e.py``
と同一の Red 方針。

方針:
- E2E は実バックエンドを使う (SimulatedBackend=マーカー無し / GSASIIBackend=@gsas)。
- 観測グリッドは 15-60° / step 0.02 (test_sequential_engine.py と同較正)。step 0.02 は
  clustering の bin 較正上変更禁止 (note §6)。
- TC-108-01 の一気通貫は module スコープ fixture ``warming_run`` で 1 回だけ実行し
  正常系 TC-022-03〜10 で読み取り専用共有する (実行時間の抑制。M1 ``ab_result`` の範)。
- @gsas 1 件 (TC-022-11) は GSAS-II 未導入環境で conftest.py が自動 skip。
- 決定論 (TC-022-15) は ``==`` ビット同一、物理量は ``pytest.approx``、非有限漏洩は ``math.isfinite``。

書式の範: ``tests/test_m1_e2e.py`` / ``tests/test_sequential_engine.py`` /
``tests/test_persistent_store.py`` / ``tests/test_selection.py`` / ``tests/test_thermal.py``。
テストケース定義 (19 件, TC-022-01〜19, @gsas 1 件含む) に 1:1 対応する。
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import tsumugin
import tsumugin.model
import tsumugin.selection
import tsumugin.sequential
import tsumugin.store
from tsumugin.errors import LedgerIntegrityError

# 【Red の失敗点】: M2 シンボルはトップレベル未 re-export のため、この import が collection 時に
#   ImportError となり本ファイルの全テストが失敗する想定。M0/M1 分 (PhaseInstance 等) は既に
#   re-export 済みだが、M2 分を含む結合 import 文全体が失敗する。🔵
from tsumugin import (
    ChangepointConfig,
    ChangepointSignal,
    Decision,
    ExternalChannel,
    FinalSelectionEngine,
    FrameRecord,
    FrameSeries,
    HypothesisTreeSearch,
    LatticeParams,
    LifecycleConfig,
    LifecycleTracker,
    PersistentLedger,
    PersistentSnapshotStore,
    PhaseInstance,
    PhaseLifecycle,
    ReviewItem,
    ReviewQueue,
    SequentialConfig,
    SequentialEngine,
    SequentialResult,
    SimulatedBackend,
    ThermalBaseline,
    Trajectory,
    TransitionEstimate,
    detect_changepoint,
    detect_escalations,
    estimate_transition,
    fit_thermal_baseline,
    phase_from_dict,
    phase_to_dict,
)

# ---------------------------------------------------------------------------
# 共通テストデータ・前提 (tests/test_sequential_engine.py の慣習を踏襲)
# ---------------------------------------------------------------------------

# 【観測グリッド】: 全候補ピークが収まる 15-60° / step 0.02。tree.py と同較正でマッチングを安定化。🔵
GRID = np.arange(15.0, 60.0, 0.02)
# 【高速グリッド】: 100 フレーム性能 smoke 用の粗い小グリッド (changepoint 非発火・実行時間抑制)。🟡
GRID_FAST = np.arange(15.0, 40.0, 0.05)
# 【GSAS-II グリッド】: @gsas smoke 用 (tests/test_gsasii_backend.py と同一)。🔵
GRID_GSAS = np.arange(20.0, 80.0, 0.05)


def _phase(a: float, ref: str, scale: float = 1.0) -> PhaseInstance:
    """立方格子の相インスタンスを作る (格子定数 a を変えるとピーク位置が変わる)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _refs(phases) -> set[str]:
    """相集合 (phase_ref の集合) を返す。"""
    return {p.phase_ref for p in phases}


def _expansion_series(
    *, a0: float = 5.0, delta: float = 0.01, n_frames: int, grid: np.ndarray = GRID
) -> FrameSeries:
    """相構成不変・格子のみ線形膨張する単一相 A のシーケンス (changepoint なし想定)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    rows = [backend.simulate([_phase(a0 + delta * i, "A")], grid) for i in range(n_frames)]
    intensities = np.asarray(rows, dtype=float)
    return FrameSeries(two_theta=grid, intensities=intensities)


def _warming_transition_series(
    *,
    n_frames: int = 16,
    b_onset: int = 10,
    a0: float = 5.0,
    delta: float = 0.01,
    b: float = 6.0,
    grid: np.ndarray = GRID,
    t0: float = 300.0,
    dt: float = 5.0,
) -> FrameSeries:
    """昇温 + 相転移合成シーケンス。前半は熱膨張する主相 A のみ、後半で新相 B が出現する。

    格子 a を線形膨張 (delta=0.01 は SE-B06 で非発火較正済み) させつつ、``b_onset`` 以降で新相 B を
    重畳し新規未マッチピークで changepoint を発火させる。温度チャネル (t0 + dt*i) を同期し
    ``estimate_transition`` の温度軸へ伝播させる。
    """
    backend = SimulatedBackend(peak_fwhm=0.2)
    rows = []
    for i in range(n_frames):
        a_i = a0 + delta * i
        phases = [_phase(a_i, "A")]
        if i >= b_onset:
            phases.append(_phase(b, "B"))
        rows.append(backend.simulate(phases, grid))
    intensities = np.asarray(rows, dtype=float)
    temps = tuple(t0 + dt * i for i in range(n_frames))
    channel = ExternalChannel(kind="temperature", sync_map={i: temps[i] for i in range(n_frames)})
    return FrameSeries(
        two_theta=grid,
        intensities=intensities,
        axis_values=temps,
        axis_kind="temperature",
        channels=(channel,),
    )


# 【後方互換契約】: 既存 M0/M1 公開シンボル (削除・改名禁止 / REQ-404)。現行 __all__ 26 件。🔵
_M0M1_PUBLIC_SYMBOLS = {
    "AICBackend",
    "AnalysisResult",
    "BICBackend",
    "Hypothesis",
    "HypothesisTreeSearch",
    "LatticeParams",
    "Ledger",
    "Peak",
    "PhaseCandidate",
    "PhaseInstance",
    "Project",
    "RankedHypothesis",
    "RefinementBackend",
    "RefinementMetrics",
    "RefinementModel",
    "RefinementReport",
    "RefinementResult",
    "SearchConfig",
    "SearchResult",
    "SimulatedBackend",
    "SnapshotStore",
    "StagedRefinementEngine",
    "UnmatchedPeakReport",
    "analyze_single_pattern",
    "export_gpx",
    "rank",
}

# 【昇格契約】: 本タスクでトップレベルへ昇格する M2 シンボル (要件定義 §2.1 / note §3 昇格候補)。🔵
_M2_PROMOTED_SYMBOLS = {
    # sequential
    "SequentialEngine",
    "SequentialConfig",
    "SequentialResult",
    "FrameSeries",
    "FrameRecord",
    "Trajectory",
    "ChangepointConfig",
    "ChangepointSignal",
    "LifecycleConfig",
    "LifecycleTracker",
    "ThermalBaseline",
    "TransitionEstimate",
    "detect_changepoint",
    "estimate_transition",
    "fit_thermal_baseline",
    # selection
    "FinalSelectionEngine",
    "Decision",
    "ReviewQueue",
    "ReviewItem",
    "detect_escalations",
    # store
    "PersistentLedger",
    "PersistentSnapshotStore",
    "phase_to_dict",
    "phase_from_dict",
    # model
    "ExternalChannel",
    "PhaseLifecycle",
}


@pytest.fixture(scope="module")
def warming_run(tmp_path_factory) -> SimpleNamespace:
    """昇温 + 相転移一気通貫パイプラインを 1 回だけ実行し正常系で読み取り専用共有する (TC-108-01)。

    【テスト前準備】: 公開 API (from tsumugin import ...) 経由でフルパイプライン (frame0 staged →
    warm start direct → changepoint → 局所探索 → 採択 → lifecycle → Trajectory) を実行し、frozen な
    SequentialResult と注入した永続ファイルパスを正常系 8 ケース (TC-022-03〜10) で共有する。🔵
    """
    tmp_dir = tmp_path_factory.mktemp("m2_warming")
    ledger_path = tmp_dir / "ledger.jsonl"
    snap_path = tmp_dir / "snapshots.jsonl"
    n_frames = 16
    b_onset = 10
    series = _warming_transition_series(n_frames=n_frames, b_onset=b_onset)
    ledger = PersistentLedger(ledger_path)
    snapshots = PersistentSnapshotStore(snap_path, ledger=ledger)
    engine = SequentialEngine(
        SimulatedBackend(peak_fwhm=0.2),
        candidates=[_phase(6.0, "B")],
        ledger=ledger,
        snapshots=snapshots,
    )
    result = engine.run(series, [_phase(5.0, "A")])
    return SimpleNamespace(
        result=result,
        series=series,
        n_frames=n_frames,
        b_onset=b_onset,
        ledger_path=ledger_path,
        snap_path=snap_path,
        tmp_dir=tmp_dir,
    )


# ---------------------------------------------------------------------------
# 1. 正常系テストケース (TC-022-01〜11)
# ---------------------------------------------------------------------------


def test_m2_public_symbols_are_reexported():
    # 【テスト目的】: M2 公開シンボルが from tsumugin import ... で解決し期待の型を持つ (TC-022-01)
    # 【テスト内容】: モジュール冒頭 import 済みの各シンボルが class / dataclass / 関数 のいずれか検証
    # 【期待される動作】: トップレベル tsumugin 名前空間から M2 中核シンボルへ到達できる (完了条件①)
    # 🔵 信頼性レベル: 要件定義 §2.1 / 完了条件① / test_m1_public_symbols_are_reexported の範に依拠

    # 【結果検証】: エンジン/ストア/キュー系はクラス
    assert inspect.isclass(SequentialEngine)  # 【確認内容】: 逐次エンジンはクラス 🔵
    assert inspect.isclass(FinalSelectionEngine)  # 【確認内容】: 最終選択エンジンはクラス 🔵
    assert inspect.isclass(LifecycleTracker)  # 【確認内容】: lifecycle 追跡はクラス 🔵
    assert inspect.isclass(PersistentLedger)  # 【確認内容】: 永続台帳はクラス 🔵
    assert inspect.isclass(PersistentSnapshotStore)  # 【確認内容】: 永続スナップショットはクラス 🔵
    assert inspect.isclass(ReviewQueue)  # 【確認内容】: Review Queue はクラス 🔵

    # 【結果検証】: 値オブジェクト系は dataclass
    for dc in (
        SequentialConfig,
        SequentialResult,
        FrameSeries,
        FrameRecord,
        Trajectory,
        ExternalChannel,
        PhaseLifecycle,
        Decision,
        ThermalBaseline,
        TransitionEstimate,
        ReviewItem,
        ChangepointConfig,
        ChangepointSignal,
        LifecycleConfig,
    ):
        assert dataclasses.is_dataclass(dc)  # 【確認内容】: 値オブジェクトは dataclass 🔵

    # 【結果検証】: 純関数系は callable でありクラスでない
    for fn in (
        detect_changepoint,
        estimate_transition,
        fit_thermal_baseline,
        detect_escalations,
        phase_to_dict,
        phase_from_dict,
    ):
        assert callable(fn) and not inspect.isclass(fn)  # 【確認内容】: 関数として呼び出し可能 🔵

    # 【期待値確認】: トップレベルはサブパッケージ実体の re-export (コピーや別実装でない) 🔵
    assert SequentialEngine is tsumugin.sequential.SequentialEngine  # 【確認内容】: 同一実体 🔵
    assert FinalSelectionEngine is tsumugin.selection.FinalSelectionEngine  # 【確認内容】: 同一実体 🔵
    assert PersistentLedger is tsumugin.store.PersistentLedger  # 【確認内容】: 同一実体 🔵
    assert ExternalChannel is tsumugin.model.ExternalChannel  # 【確認内容】: 同一実体 🔵
    assert estimate_transition is tsumugin.sequential.estimate_transition  # 【確認内容】: 同一実体 🔵


def test_m2_symbols_in_dunder_all_and_sorted():
    # 【テスト目的】: 昇格 M2 シンボルが tsumugin.__all__ に含まれ昇順ソート + 後方互換維持 (TC-022-02)
    # 【テスト内容】: __all__ の包含関係・ソート順・M0/M1 分の後方互換 (削除なし)・実属性整合を検証
    # 【期待される動作】: __all__ が M0 + M1 + M2 を統合しアルファベット昇順のまま (完了条件① / REQ-404)
    # 🔵 信頼性レベル: 要件定義 §2.1 / REQ-404 / 既存 __init__.py の __all__ 慣習に直接依拠

    exported = set(tsumugin.__all__)

    # 【結果検証】: 昇格 M2 シンボルが公開面 (__all__) に配線されていること
    assert _M2_PROMOTED_SYMBOLS <= exported  # 【確認内容】: M2 シンボルが __all__ に包含 🔵
    # 【後方互換】: 既存 M0/M1 シンボルが 1 つも削除・改名されていないこと (REQ-404)
    assert _M0M1_PUBLIC_SYMBOLS <= exported  # 【確認内容】: M0/M1 公開面の非破壊 (後方互換維持) 🔵
    # 【規約遵守】: __all__ がアルファベット昇順ソートを維持していること
    assert list(tsumugin.__all__) == sorted(tsumugin.__all__)  # 【確認内容】: 昇順ソート維持 🔵
    # 【実体整合】: __all__ の全名称が実際に属性として解決できること
    for name in tsumugin.__all__:
        assert hasattr(tsumugin, name)  # 【確認内容】: __all__ と実属性の乖離が無い 🔵


def test_e2e_warming_sequence_completes_all_frames(warming_run: SimpleNamespace):
    # 【テスト目的】: 昇温逐次精密化が全フレーム完走し trajectory 長 == n_frames (TC-022-03 / TC-108-01a)
    # 【テスト内容】: 昇温 + 相転移合成 FrameSeries への run() が例外なく SequentialResult を返すか検証
    # 【期待される動作】: frame0 staged → warm start direct → Trajectory 組立の単一パスが完走 (完了条件②)
    # 🔵 信頼性レベル: 完了条件② / 受け入れ基準 TC-108-01 / tests/test_sequential_engine.py に依拠

    result = warming_run.result

    # 【結果検証】: 逐次精密化がフレーム列全長で破綻せず非有限を漏らさない
    assert isinstance(result, SequentialResult)  # 【確認内容】: run() は SequentialResult を返す 🔵
    assert len(result.trajectory.records) == warming_run.n_frames  # 【確認内容】: 行数=フレーム数 🔵
    for rec in result.trajectory.records:
        assert rec.rwp is None or math.isfinite(rec.rwp)  # 【確認内容】: 非有限 rwp を漏らさない 🔵


def test_e2e_changepoint_fires_near_transition(warming_run: SimpleNamespace):
    # 【テスト目的】: changepoint が転移近傍で発火し search_results に該当フレームが載る (TC-022-04)
    # 【テスト内容】: 相転移フレーム近傍で FrameRecord.changepoint が立ち局所探索が起動するか検証
    # 【期待される動作】: 複合指標の robust z が転移フレームで発火し局所木探索を起動 (完了条件② / D3)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-003/101 / tests/test_changepoint.py に依拠

    result = warming_run.result
    b_onset = warming_run.b_onset
    records = result.trajectory.records
    changepoint_frames = {i for i, r in enumerate(records) if r.changepoint}

    # 【結果検証】: 発火あり + 局所探索起動 + 発火フレームでのみ探索 + 転移近傍で発火
    assert changepoint_frames  # 【確認内容】: 少なくとも 1 フレームで changepoint 発火 🔵
    assert result.search_results  # 【確認内容】: 発火フレームで局所探索が起動し記録される 🔵
    assert set(result.search_results) == changepoint_frames  # 【確認内容】: 探索は発火フレームのみ 🔵
    for i in changepoint_frames:
        assert records[i].changepoint_reasons  # 【確認内容】: 発火理由が非空で説明可能 🔵
    assert any(
        b_onset - 1 <= f <= b_onset + 2 for f in changepoint_frames
    )  # 【確認内容】: 転移フレーム近傍で発火 🔵


def test_e2e_new_phase_adopted_into_hypotheses(warming_run: SimpleNamespace):
    # 【テスト目的】: 局所探索で新相 B が採択され hypotheses 系譜へ反映される (TC-022-05 / TC-108-01c)
    # 【テスト内容】: 採択後の相集合が転移前と異なり系譜に B 込み構成が frame_range 付きで登録されるか
    # 【期待される動作】: 転移前 {A} → 転移後 {A,B} の 2 種類以上の相集合が系譜に現れる (完了条件② / D3)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-101 / architecture.md D3 に直接依拠

    result = warming_run.result
    lineage_refsets = [frozenset(_refs(h.phases)) for h in result.hypotheses.values()]

    # 【結果検証】: 系譜が非空で B を含む構成があり、相集合が 2 種類以上 (転移の反映)
    assert result.hypotheses  # 【確認内容】: 採択構成の系譜が非空 🔵
    assert any("B" in rs for rs in lineage_refsets)  # 【確認内容】: 新相 B が系譜に反映 🔵
    assert len(set(lineage_refsets)) >= 2  # 【確認内容】: 転移前後で相集合が変化 (2 種類以上) 🔵
    assert any(
        h.frame_range is not None and "B" in _refs(h.phases) for h in result.hypotheses.values()
    )  # 【確認内容】: 採択仮説が frame_range 付きで系譜に登録される 🔵


def test_e2e_lifecycle_birth_death_recorded(warming_run: SimpleNamespace):
    # 【テスト目的】: lifecycle に新相 B の birth が記録される (TC-022-06 / TC-108-01d)
    # 【テスト内容】: trajectory.lifecycles に相ごとの PhaseLifecycle が入り B の birth_frame が妥当か
    # 【期待される動作】: ヒステリシス (N=3) で確定した birth が lifecycle に反映 (完了条件② / REQ-004/201)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-004/201 / tests/test_lifecycle.py に直接依拠

    result = warming_run.result
    lifecycles = result.trajectory.lifecycles

    # 【結果検証】: 確定相 A/B が lifecycle に入り B の birth が転移フレーム以降で妥当
    assert "A" in lifecycles  # 【確認内容】: 全フレーム存在の A が lifecycle 確定 🔵
    assert "B" in lifecycles  # 【確認内容】: 出現・確定した B が lifecycle に登録 🔵
    b_life = lifecycles["B"]
    assert b_life.birth_frame is not None  # 【確認内容】: 出現・確定した B の birth 確定 🔵
    assert b_life.birth_frame >= warming_run.b_onset  # 【確認内容】: birth は転移フレーム以降 🔵
    assert 0.0 <= b_life.confidence <= 1.0  # 【確認内容】: confidence が [0,1] に収まる 🔵


def test_e2e_transition_temperature_estimated(warming_run: SimpleNamespace):
    # 【テスト目的】: 温度軸と相分率から estimate_transition が転移温度を推定する (TC-022-07 / TC-108-01e)
    # 【テスト内容】: trajectory の温度列と相 B の分率列から estimate_transition が非 None を返すか検証
    # 【期待される動作】: 相分率シグモイド遷移の補間から onset/midpoint±σ を算出 (完了条件② / REQ-008)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-008 / tests/test_thermal.py に直接依拠

    result = warming_run.result
    records = result.trajectory.records
    # 【テストデータ準備】: 温度チャネル由来の温度列と相 B の存在分率 (0→1 単調) を trajectory から抽出
    temperatures = [rec.temperature for rec in records]
    fractions = [1.0 if "B" in _refs(rec.phases) else 0.0 for rec in records]

    # 【実際の処理実行】: 相分率シグモイドから転移温度を推定する
    estimate = estimate_transition(temperatures, fractions, phase_ref="B")

    # 【結果検証】: 明瞭な相出現データでは転移温度が推定可能で方向が appearing
    assert estimate is not None  # 【確認内容】: 転移が推定される (曖昧データの None でない) 🔵
    assert estimate.phase_ref == "B"  # 【確認内容】: 対象相識別子が透過保持される 🔵
    assert estimate.onset is not None and math.isfinite(estimate.onset)  # 【確認内容】: onset 有限 🔵
    assert estimate.midpoint is not None and math.isfinite(estimate.midpoint)  # midpoint 有限 🔵
    assert estimate.onset <= estimate.midpoint  # 【確認内容】: 出現方向で onset <= midpoint 🔵
    assert estimate.direction == "appearing"  # 【確認内容】: 分率増加につき出現方向 🔵


def test_e2e_agent_final_selection_decides(warming_run: SimpleNamespace):
    # 【テスト目的】: 転移フレームの探索結果に agent 裁定を適用し Decision を返す (TC-022-08 / TC-108-01f)
    # 【テスト内容】: 局所探索 SearchResult に FinalSelectionEngine(mode="agent").decide を適用し裁定検証
    # 【期待される動作】: agent モードで自動 accept または暫定裁定 + Review Queue 通知 (完了条件② / REQ-013)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-013/014/102 / tests/test_selection.py に直接依拠

    result = warming_run.result
    frame_index, search_result = next(iter(result.search_results.items()))
    # 【入力読取】: 裁定前の先頭仮説 ID/状態を控え非破壊性 (D5) を後で確認する
    top_id_before = search_result.ranked[0].hypothesis.id
    status_before = search_result.ranked[0].hypothesis.status

    # 【実際の処理実行】: 共有結果を汚さないよう独立の ledger/queue を注入して agent 裁定する
    ledger = tsumugin.store.Ledger()
    queue = ReviewQueue(ledger=ledger)
    engine = FinalSelectionEngine(mode="agent", ledger=ledger, queue=queue)
    decision = engine.decide(search_result, frame_index=frame_index)

    # 【結果検証】: Decision 構造 + agent モード + 定量根拠 + 有効裁定 (accept か暫定) を確認
    assert isinstance(decision, Decision)  # 【確認内容】: 裁定は Decision を返す 🔵
    assert decision.mode == "agent"  # 【確認内容】: agent モードの裁定 🔵
    assert isinstance(decision.rationale, str) and decision.rationale  # 定量根拠を含む非空文字列 🔵
    assert (
        decision.accepted is not None or decision.provisional_id is not None
    )  # 【確認内容】: 自動 accept か暫定裁定のいずれか (best 存在時) 🔵
    if decision.accepted is not None:
        assert decision.accepted.accepted_by == "agent"  # 【確認内容】: 自動 accept は agent 由来 🔵
    # 【非破壊検証 (D5)】: decide は入力 SearchResult を変更しない
    assert search_result.ranked[0].hypothesis.id == top_id_before  # 【確認内容】: 先頭 ID 不変 🔵
    assert search_result.ranked[0].hypothesis.status == status_before  # 【確認内容】: 状態不変 🔵


def test_e2e_persistent_ledger_verify_and_reopen(warming_run: SimpleNamespace):
    # 【テスト目的】: 永続 ledger の verify() True + 再オープン検証 (TC-022-09 / TC-108-01g)
    # 【テスト内容】: 実行後 result.ledger.verify() True + 注入 ledger を新インスタンスで再オープン検証
    # 【期待される動作】: 全操作が追記専用ハッシュチェーンに記録されプロセス跨ぎで改竄検知 (完了条件②)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-010 / NFR-105/201 / tests/test_persistent_store.py

    result = warming_run.result

    # 【結果検証】: 実行時 verify() True + entries 非空 (空 ledger の自明 True でない)
    assert isinstance(result.ledger, PersistentLedger)  # 【確認内容】: 注入した永続版がそのまま返る 🔵
    assert result.ledger.verify() is True  # 【確認内容】: ハッシュ連鎖が無傷 (改竄なし) 🔵
    assert len(result.ledger.entries) > 0  # 【確認内容】: 空 ledger の自明 True でない 🔵

    # 【追加検証】: 同一 JSONL を再オープンしても検証成功しエントリ数が一致 (プロセス跨ぎ)
    reopened = PersistentLedger(warming_run.ledger_path)
    assert reopened.verify() is True  # 【確認内容】: 再オープンでもチェーンが健全 🔵
    assert len(reopened.entries) == len(result.ledger.entries)  # 【確認内容】: エントリ数一致 🔵


def test_e2e_trajectory_to_csv_written(warming_run: SimpleNamespace):
    # 【テスト目的】: Trajectory.to_csv がヘッダ + n_frames 行の CSV を書き出す (TC-022-10 / TC-108-01h)
    # 【テスト内容】: to_csv(path) が書き出しパスを返しファイルが実在しヘッダ 1 行 + データ n_frames 行か
    # 【期待される動作】: stdlib csv でトラジェクトリを機械可読な CSV へ書き出す (完了条件② / REQ-005)
    # 🔵 信頼性レベル: 完了条件② / TC-108-01 / REQ-005 / tests/test_trajectory.py に直接依拠

    result = warming_run.result
    csv_path = warming_run.tmp_dir / "traj.csv"

    # 【実際の処理実行】: トラジェクトリを CSV へ書き出す
    written = result.trajectory.to_csv(str(csv_path))

    # 【結果検証】: 戻り値パス一致 + ファイル実在 + 行数 = ヘッダ + フレーム行
    assert written == str(csv_path)  # 【確認内容】: 戻り値が書き出しパスと一致 🔵
    assert Path(written).exists()  # 【確認内容】: 永続 CSV がファイルとして実在 🔵
    lines = Path(written).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 + warming_run.n_frames  # 【確認内容】: ヘッダ 1 行 + n_frames 行 🔵


@pytest.mark.gsas
def test_e2e_gsasii_three_frame_sequential_smoke():
    # 【テスト目的】: GSASIIBackend で 3 フレーム逐次精密化 smoke が完走する (TC-022-11 / TC-108-02)
    # 【テスト内容】: 実 GSAS-II 精密化を用いた短い逐次解析が破綻せず SequentialResult を返すか検証
    # 【期待される動作】: バックエンド交換 (P7) しても逐次パイプラインが同契約で完走 (完了条件③)
    # 🔵 信頼性レベル: 完了条件③ / TC-108-02 / tests/test_gsasii_backend.py の @gsas パターンに依拠

    from tsumugin.backends.gsasii import GSASIIBackend

    # 【テストデータ準備】: GSAS-II が確実に計算できる立方相の 3 フレーム (同一相の smoke)
    backend = GSASIIBackend()
    phase = _phase(4.0, "P")
    rows = [backend.simulate([phase], GRID_GSAS) for _ in range(3)]
    intensities = np.asarray(rows, dtype=float)
    series = FrameSeries(two_theta=GRID_GSAS, intensities=intensities)

    # 【実際の処理実行】: 実バックエンドで短い逐次解析を通す
    result = SequentialEngine(backend).run(series, [phase])

    # 【結果検証】: 例外なく完走し 3 行のトラジェクトリと健全な ledger を返す
    assert isinstance(result, SequentialResult)  # 【確認内容】: 実バックエンドでも実体を返す 🔵
    assert len(result.trajectory.records) == 3  # 【確認内容】: 3 フレーム完走 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 統合経路でも ledger 連鎖が無傷 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (TC-022-12〜14)
# ---------------------------------------------------------------------------


def test_e2e_empty_series_degrades_gracefully():
    # 【テスト目的】: 空フレーム列で例外なく空トラジェクトリへ縮退する (TC-022-12 / EDGE-001)
    # 【テスト内容】: (0, n_points) の空フレーム列で run しても例外を投げず空値を返すか検証
    # 【期待される動作】: 上流が空データを渡してもパイプラインがクラッシュしない (M0/M1 縮退規約)
    # 🔵 信頼性レベル: 要件定義 §4.3 / EDGE-001 / tests/test_sequential_engine.py に直接依拠

    # 【テストデータ準備】: 測定フィルタ後に全フレーム除外された等の空入力 (n_frames=0)
    series = FrameSeries(GRID, np.empty((0, GRID.size)))

    # 【実際の処理実行】: 空入力でも例外化せず実体を返す (下流 CSV 出力を破綻させない)
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2)).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 全コレクションが空値へ縮退し ledger が健全な状態を保つ
    assert result.trajectory.records == ()  # 【確認内容】: 空フレーム列 (例外を出さない契約) 🔵
    assert dict(result.trajectory.lifecycles) == {}  # 【確認内容】: 空 lifecycles 🔵
    assert dict(result.search_results) == {}  # 【確認内容】: 局所探索なし 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 空でも ledger 実体が健全 🔵


def test_e2e_corrupted_persistent_ledger_raises_on_reopen(tmp_path):
    # 【テスト目的】: 永続 ledger 破損を再オープンで検出し LedgerIntegrityError (TC-022-13 / EDGE-003)
    # 【テスト内容】: 逐次解析で追記した JSONL の 1 行を改竄し再オープンで明示エラー + ファイル無変更
    # 【期待される動作】: 改竄・破損を黙って修復せず監査証跡の信頼性を保全 (P2 / NFR-105)
    # 🔵 信頼性レベル: 要件定義 §4.3 / EDGE-003 / REQ-401 / tests/test_persistent_store.py に直接依拠

    # 【テストデータ準備】: 永続 ledger を注入した短い逐次解析でエントリを追記する
    path = tmp_path / "ledger.jsonl"
    pl = PersistentLedger(path)
    series = _warming_transition_series(n_frames=6, b_onset=3)
    SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")], ledger=pl).run(
        series, [_phase(5.0, "A")]
    )
    assert len(pl.entries) > 0  # 【前提確認】: 追記エントリが存在する (自明破損でない)

    # 【改竄操作】: 追記済み JSONL の末尾行 payload を書き換えハッシュチェーンを断つ
    lines = path.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[-1])
    row["payload"] = {"tampered": 999}
    lines[-1] = json.dumps(row)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = path.read_bytes()

    # 【結果検証】: 再オープンで LedgerIntegrityError を送出し、ファイルは修復・上書きされない
    with pytest.raises(LedgerIntegrityError):  # 【確認内容】: 破損を沈黙せず明示エラー 🔵
        PersistentLedger(path)
    assert path.read_bytes() == before  # 【確認内容】: 修復・上書きしない (無修復 / P2) 🔵


def test_e2e_agent_no_candidates_escalates_only():
    # 【テスト目的】: 裁定対象ゼロで accept せずエスカレーションのみ返す (TC-022-14 / EDGE-004)
    # 【テスト内容】: 候補ゼロ探索の空 SearchResult に agent 裁定を適用し誤 accept しないか検証
    # 【期待される動作】: 裁定材料が無い状態で誤って accept せず Decision 構造で表現 (EDGE-004)
    # 🔵 信頼性レベル: 要件定義 §4.3 / EDGE-004 / tests/test_selection.py に直接依拠

    # 【テストデータ準備】: 候補ゼロで探索した空 SearchResult (ranked が空 = 裁定対象なし)
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate([_phase(5.0, "A")], GRID)
    search_result = HypothesisTreeSearch(backend).search(GRID, y, [])

    # 【実際の処理実行】: 材料ゼロで agent 裁定を試みる (誤 accept 防止)
    engine = FinalSelectionEngine(mode="agent", queue=ReviewQueue())
    decision = engine.decide(search_result)

    # 【結果検証】: accept せず Decision を返し、accepted レジストリが増えない
    assert isinstance(decision, Decision)  # 【確認内容】: 例外でなく Decision 構造で表現 🔵
    assert decision.mode == "agent"  # 【確認内容】: agent モードの縮退裁定 🔵
    assert decision.accepted is None  # 【確認内容】: 裁定対象ゼロで accept しない 🔵
    assert decision.provisional_id is None  # 【確認内容】: 暫定裁定も立たない (best 不在) 🔵
    assert dict(engine.accepted) == {}  # 【確認内容】: accepted レジストリに新規追加なし 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース (TC-022-15〜19)
# ---------------------------------------------------------------------------


def test_e2e_deterministic_trajectory_and_csv_bitwise_identical(tmp_path):
    # 【テスト目的】: 同一入力 2 回実行で trajectory / CSV バイト列がビット同一 (TC-022-15 / REQ-402)
    # 【テスト内容】: changepoint・局所探索・採択を含む複雑経路で毎回独立実行し == で完全一致を検証
    # 【期待される動作】: 乱数不使用・中央値/MAD・canonical JSON ソート・ID 決定論採番で完全再現
    # 🔵 信頼性レベル: 受け入れ基準 REQ-402 / NFR-102/202 / tests/test_sequential_engine.py に依拠

    def once(tag: str) -> tuple[SequentialResult, bytes]:
        # 【初期条件設定】: backend/engine とも毎回独立に生成し状態共有を排除する
        series = _warming_transition_series(n_frames=16, b_onset=10)
        engine = SequentialEngine(SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")])
        result = engine.run(series, [_phase(5.0, "A")])
        csv_path = tmp_path / f"traj_{tag}.csv"
        result.trajectory.to_csv(str(csv_path))
        return result, csv_path.read_bytes()

    r1, csv1 = once("1")
    r2, csv2 = once("2")

    # 【結果検証】: CSV バイト列・FrameRecord 列・系譜 ID 列・ledger kind 列がビット同一
    assert csv1 == csv2  # 【確認内容】: CSV がビット同一 (決定論) 🔵
    assert r1.trajectory.records == r2.trajectory.records  # 【確認内容】: FrameRecord 列が同一 🔵
    assert list(r1.hypotheses.keys()) == list(r2.hypotheses.keys())  # 【確認内容】: ID 採番が同一 🔵
    assert [e.kind for e in r1.ledger.entries] == [
        e.kind for e in r2.ledger.entries
    ]  # 【確認内容】: ledger の kind 列が同順 (hash 連鎖の決定論) 🔵


def test_e2e_single_frame_sequence():
    # 【テスト目的】: 単一フレームで長さ 1 のトラジェクトリを返す (TC-022-16 / EDGE-101)
    # 【テスト内容】: n_frames=1 で frame0 staged 確立のみが走り changepoint 非発火となるか検証
    # 【期待される動作】: 最小フレーム数でも run が長さ 1 のトラジェクトリを破綻なく返す (EDGE-101)
    # 🔵 信頼性レベル: 受け入れ基準 EDGE-101 / tests/test_sequential_engine.py に直接依拠

    # 【テストデータ準備】: 後続フレーム無しの最小非空境界 (単一フレーム・主相 A のみ)
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=1)

    # 【実際の処理実行】: staged 確立のみで長さ 1 のトラジェクトリへ写像する
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2)).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 空 (TC-022-12) と複数フレーム (TC-022-03) の中間で連続的に動作
    assert len(result.trajectory.records) == 1  # 【確認内容】: 長さ 1 のトラジェクトリ 🔵
    assert result.trajectory.records[0].changepoint is False  # 【確認内容】: 履歴不足で非発火 🔵
    assert dict(result.search_results) == {}  # 【確認内容】: 局所探索なし 🔵
    assert result.ledger.verify() is True  # 【確認内容】: 最小構成でも ledger 健全 🔵


def test_e2e_no_changepoint_skips_local_search():
    # 【テスト目的】: changepoint ゼロで局所木探索が一度も呼ばれない (TC-022-17 / EDGE-104)
    # 【テスト内容】: 相構成不変・格子のみ膨張するシーケンスで発火せず search_results 空となるか検証
    # 【期待される動作】: 発火が無い区間で局所木探索を一度も呼ばず探索コストを回避 (FR-304 / NFR-103)
    # 🔵 信頼性レベル: 受け入れ基準 EDGE-104 / REQ-101 / tests/test_sequential_engine.py に直接依拠

    # 【テストデータ準備】: 相構成不変で格子のみ線形膨張する 15 フレーム (新相なし)
    series = _expansion_series(a0=5.0, delta=0.01, n_frames=15)

    # 【実際の処理実行】: 熱膨張 (連続変化) を changepoint と誤検出しないこと
    result = SequentialEngine(
        SimulatedBackend(peak_fwhm=0.2), candidates=[_phase(6.0, "B")]
    ).run(series, [_phase(5.0, "A")])

    # 【結果検証】: 発火あり (TC-022-04) と対をなし、非発火時のコスト回避を保証
    assert all(not r.changepoint for r in result.trajectory.records)  # 【確認内容】: 全フレーム非発火 🔵
    assert dict(result.search_results) == {}  # 【確認内容】: 局所探索が一度も起動しない 🔵
    assert len(result.trajectory.records) == 15  # 【確認内容】: 行数=フレーム数 🔵


def test_readme_m2_example_executes(tmp_path):
    # 【テスト目的】: README「使い方 (M2)」節の最小使用例と同等コードが動作する (TC-022-18)
    # 【テスト内容】: 公開 import → 昇温合成 → SequentialEngine(...).run → to_csv の写経実行と完走検証
    # 【期待される動作】: 使用例が例外なく実行され SequentialResult と書き出し CSV が得られる (完了条件⑤)
    # 🟡 信頼性レベル: 完了条件⑤ / 要件定義 §2.4 からの妥当な推測 (README 文面は Green で確定)

    # --- ここから README 使用例と同等のコード (公開 API のみ使用) ---
    # 【テストデータ準備】: 昇温で格子が膨張しつつ途中で相転移する合成フレーム列を組む
    backend = SimulatedBackend(peak_fwhm=0.2)
    two_theta = np.arange(15.0, 60.0, 0.02)
    n_frames = 12
    b_onset = 8
    rows = []
    temps = []
    for i in range(n_frames):
        a_i = 5.0 + 0.01 * i
        phases = [PhaseInstance("A", LatticeParams(a_i, a_i, a_i))]
        if i >= b_onset:
            phases.append(PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0)))
        rows.append(backend.simulate(phases, two_theta))
        temps.append(300.0 + 5.0 * i)
    series = FrameSeries(
        two_theta,
        np.asarray(rows, dtype=float),
        axis_values=tuple(temps),
        axis_kind="temperature",
        channels=(ExternalChannel("temperature", {i: t for i, t in enumerate(temps)}),),
    )
    engine = SequentialEngine(
        backend, candidates=[PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0))]
    )
    result = engine.run(series, [PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0))])
    written = result.trajectory.to_csv(str(tmp_path / "traj.csv"))
    # --- ここまで README 使用例と同等のコード ---

    # 【結果検証】: 使用例の出力が公開 API の実シグネチャ・契約に追従していること
    assert isinstance(result, SequentialResult)  # 【確認内容】: run は SequentialResult を返す 🟡
    assert len(result.trajectory.records) == n_frames  # 【確認内容】: 全フレーム完走 🟡
    assert Path(written).exists()  # 【確認内容】: 使用例の最終出力 CSV が実在 🟡


def test_e2e_hundred_frames_within_time_budget():
    # 【テスト目的】: 合成 100 フレーム (changepoint なし) が 60 秒以内に完了する (TC-022-19 / TC-108-03)
    # 【テスト内容】: 滑らかな線形膨張 100 フレーム (局所探索コスト非混入) の direct refine 経路の性能
    # 【期待される動作】: 非探索区間は warm start + direct refine で軽量に処理される (NFR-001 / NFR-103)
    # 🟡 信頼性レベル: 受け入れ基準 TC-108-03 / NFR-001 / tests/test_sequential_engine.py (SE-B08) に依拠

    import time

    # 【テストデータ準備】: 粗い小グリッドの滑らかな膨張 100 フレーム (発火を抑制し探索コスト混入を防ぐ)
    series = _expansion_series(a0=5.0, delta=0.005, n_frames=100, grid=GRID_FAST)

    # 【実際の処理実行】: direct refine (~7 パラメータ × <=10 cycles) が線形にスケールする
    start = time.perf_counter()
    result = SequentialEngine(SimulatedBackend(peak_fwhm=0.2)).run(series, [_phase(5.0, "A")])
    elapsed = time.perf_counter() - start

    # 【結果検証】: 実用規模の最小担保 — 時間予算内で全フレームを処理し局所探索を混入させない
    assert len(result.trajectory.records) == 100  # 【確認内容】: 100 フレーム完走 🟡
    assert dict(result.search_results) == {}  # 【確認内容】: changepoint 非発火で探索ゼロ 🟡
    assert elapsed < 60.0  # 【確認内容】: 60 秒以内 (NFR-001 性能境界) 🟡
