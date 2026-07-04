"""TASK-0035 公開 API 統合 + E2E (M3 operando 総仕上げ) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/__init__.py`` への M3 公開シンボル re-export
(``MultistartEngine`` / ``MultistartConfig`` / ``MultistartResult`` / ``BasinInfo`` /
``PerturbationSpec`` / ``cluster_basins`` / ``generate_starts`` / ``AbsorptionConfig`` /
``transmission_factor`` / ``read_echem_csv`` / ``EchemData`` / ``EchemLoader`` /
``BiologicMprLoader`` / ``CELL_PHASE_PRESETS`` / ``FixedPhaseSpec`` / ``fixed_free_suffixes`` /
``DiscriminationConfig`` / ``DiscriminationResult`` / ``discriminate_interval`` /
``SegmentationConfig`` / ``SegmentationResult`` / ``segment_series`` / ``combined_csv`` /
``transition_point`` / ``TransitionPoint`` / ``BranchComparison`` / ``split_branches`` /
``branch_differences`` / ``CellConfig`` / ``CellLayer`` / ``BeamConfig`` / ``MuCalculator`` /
``XraylibMuCalculator``) と、公開 API 経由の operando 一気通貫 E2E 結線検証。

Red の失敗機構: 本モジュール冒頭の ``from tsumugin import MultistartEngine, ...`` は M3 分が
トップレベル未 re-export (現状 M0 + M1 + M2 分のみ) のため collection 時に ImportError となり、
本ファイルの全テストが失敗する (テストケース定義書 §共通前提 / note §0)。``tests/test_m2_e2e.py``
と同一の Red 方針。

方針:
- E2E は SimulatedBackend で決定論・乱数不使用 (@gsas は TC-035-11 の 1 件のみ・conftest.py が自動 skip)。
- 観測グリッドは 15-60° / step 0.05 (tests/test_discrimination.py と同較正・固定相 Al まで捉える <30 秒 smoke)。
- TC-035-04〜09 の一気通貫は module スコープ fixture ``operando_run`` で 1 回だけ実行し正常系で読み取り
  専用共有する (実行時間の抑制。M2 ``warming_run`` の範)。共有 Ledger を segment/discriminate へ注入する。
- 決定論 (TC-035-15) は ``==`` ビット同一、物理量は ``pytest.approx``。
テストケース定義 (18 件, TC-035-01〜18, @gsas 1 件含む) に 1:1 対応する。
"""

from __future__ import annotations

import csv
import dataclasses
import inspect
import math
import time
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

import tsumugin
import tsumugin.absorption
import tsumugin.model
import tsumugin.multistart
import tsumugin.operando

# 【Red の失敗点】: M3 シンボルはトップレベル未 re-export のため、この import が collection 時に
#   ImportError となり本ファイルの全テストが失敗する想定。M0/M1/M2 分 (PhaseInstance 等) は既に
#   re-export 済みだが、M3 分を含む結合 import 文全体が失敗する。🔵
from tsumugin import (
    CELL_PHASE_PRESETS,
    AbsorptionConfig,
    BasinInfo,
    BeamConfig,
    BiologicMprLoader,
    BranchComparison,
    CellConfig,
    CellLayer,
    DiscriminationConfig,
    DiscriminationResult,
    EchemData,
    EchemLoader,
    FixedPhaseSpec,
    FrameSeries,
    LatticeParams,
    Ledger,
    MuCalculator,
    MultistartConfig,
    MultistartEngine,
    MultistartResult,
    PerturbationSpec,
    PhaseInstance,
    ReviewQueue,
    SegmentationConfig,
    SegmentationResult,
    SequentialEngine,
    SimulatedBackend,
    TransitionPoint,
    XraylibMuCalculator,
    branch_differences,
    cluster_basins,
    combined_csv,
    discriminate_interval,
    fixed_free_suffixes,
    generate_starts,
    read_echem_csv,
    segment_series,
    split_branches,
    transition_point,
    transmission_factor,
)

# ---------------------------------------------------------------------------
# 共通テストデータ・前提 (tests/test_discrimination.py の慣習を踏襲)
# ---------------------------------------------------------------------------

# 【観測グリッド】: 判別/分割テストと同較正の 15-60° / step 0.05。固定相 Al (211)≈55.5° まで捉える。🔵
GRID = np.arange(15.0, 60.0, 0.05)
# 【@gsas グリッド】: マルチスタート smoke 用 (tests/test_m2_e2e.py L95 と同一)。🔵
GRID_GSAS = np.arange(20.0, 80.0, 0.05)
# 【活物質の初期相】: 立方格子 a=b=c=5.0 の単相 (仮説 A の単相起点 / 分割 refine の初期相)。🔵
INITIAL: tuple[PhaseInstance, ...] = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
# 【セル固定相】: Al 集電体プリセット (FixedPhaseSpec)。系列へ scale=0.7 で重畳する。🔵
AL = CELL_PHASE_PRESETS["Al"]
# 【高速 config】: verdict はマルチスタート本数非依存のため n_starts=2 で実行時間を抑える。🟡
CONFIG_FAST = DiscriminationConfig(multistart=MultistartConfig(n_starts=2))
# 【verdict 値域】: 判別結果の 3 値 (contract)。🔵
VERDICTS = {"solid_solution", "two_phase", "undecided"}
# 【echem CSV 列写像 / 容量→x 換算】: frame 同期キー + 容量 Q の線形換算 x = 0.1·Q。🔵
ECHEM_COLUMN_MAP = {"frame": "frame", "voltage": "voltage", "capacity": "capacity"}
CAPACITY_TO_X = (0.1, 0.0)

# 【昇格契約】: 本タスクでトップレベルへ昇格する M3 公開面全体 (要件定義 §2.1 / note §0.1)。🔵
_M3_PROMOTED_SYMBOLS = {
    # multistart
    "MultistartEngine",
    "MultistartConfig",
    "MultistartResult",
    "BasinInfo",
    "PerturbationSpec",
    "cluster_basins",
    "generate_starts",
    # absorption
    "AbsorptionConfig",
    "transmission_factor",
    # operando
    "read_echem_csv",
    "EchemData",
    "EchemLoader",
    "BiologicMprLoader",
    "CELL_PHASE_PRESETS",
    "FixedPhaseSpec",
    "fixed_free_suffixes",
    "DiscriminationConfig",
    "DiscriminationResult",
    "discriminate_interval",
    "SegmentationConfig",
    "SegmentationResult",
    "segment_series",
    "combined_csv",
    "transition_point",
    "TransitionPoint",
    "BranchComparison",
    "split_branches",
    "branch_differences",
    # model.cell
    "CellConfig",
    "CellLayer",
    "BeamConfig",
    "MuCalculator",
    "XraylibMuCalculator",
}

# 【後方互換契約】: 既存 M0/M1/M2 公開シンボル (削除・改名禁止 / REQ-404)。現行 __all__ (52 件)。🔵
_M0M1M2_PUBLIC_SYMBOLS = {
    "AICBackend",
    "AnalysisResult",
    "BICBackend",
    "ChangepointConfig",
    "ChangepointSignal",
    "Decision",
    "ExternalChannel",
    "FinalSelectionEngine",
    "FrameRecord",
    "FrameSeries",
    "Hypothesis",
    "HypothesisTreeSearch",
    "LatticeParams",
    "Ledger",
    "LifecycleConfig",
    "LifecycleTracker",
    "Peak",
    "PersistentLedger",
    "PersistentSnapshotStore",
    "PhaseCandidate",
    "PhaseInstance",
    "PhaseLifecycle",
    "Project",
    "RankedHypothesis",
    "RefinementBackend",
    "RefinementMetrics",
    "RefinementModel",
    "RefinementReport",
    "RefinementResult",
    "ReviewItem",
    "ReviewQueue",
    "SearchConfig",
    "SearchResult",
    "SequentialConfig",
    "SequentialEngine",
    "SequentialResult",
    "SimulatedBackend",
    "SnapshotStore",
    "StagedRefinementEngine",
    "ThermalBaseline",
    "Trajectory",
    "TransitionEstimate",
    "UnmatchedPeakReport",
    "analyze_single_pattern",
    "detect_changepoint",
    "detect_escalations",
    "estimate_transition",
    "export_gpx",
    "fit_thermal_baseline",
    "phase_from_dict",
    "phase_to_dict",
    "rank",
}


def _phase(a: float, ref: str = "A", scale: float = 1.0) -> PhaseInstance:
    """立方格子 (a=b=c) の相インスタンスを組む (a を変えると全反射のピーク位置が動く)。"""
    return PhaseInstance(ref, LatticeParams(a, a, a), scale=scale)


def _two_phase_series(
    n_frames: int = 8, a_alpha: float = 5.0, a_beta: float = 5.06, *, with_fixed: bool = True
) -> FrameSeries:
    """端成分 2 相の scale を α:1→0 / β:0→1 で漸移させ Al 固定相を重畳した二相反応系列。🔵 note §5

    端点を純端成分 (frame0=α のみ / frame-1=β のみ) にし、仮説 A の warm-start 逐次が両端格子を
    追従できるようにする (a_beta≈5.06 は SimulatedBackend の LM 追従域内)。``with_fixed`` 時は
    Al 集電体ピーク (scale=0.7) を全フレームへ重畳する (固定相込み解析の対象)。
    """
    backend = SimulatedBackend(peak_fwhm=0.2)
    al = AL.phase.with_updates(scale=0.7)
    rows = []
    for i in range(n_frames):
        t = i / (n_frames - 1)
        phases = []
        if 1.0 - t > 0.0:
            phases.append(_phase(a_alpha, "alpha", scale=1.0 - t))
        if t > 0.0:
            phases.append(_phase(a_beta, "beta", scale=t))
        if with_fixed:
            phases.append(al)
        rows.append(backend.simulate(phases, GRID))
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


def _solid_solution_series(n_frames: int = 8, a0: float = 5.0, a1: float = 5.10) -> FrameSeries:
    """単相の格子 a=b=c をフレームで線形変化させた合成系列 (格子連続変化 = 固溶体)。🔵 note §5"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    al = AL.phase.with_updates(scale=0.7)
    rows = [
        backend.simulate([_phase(a0 + (a1 - a0) * i / (n_frames - 1), "A"), al], GRID)
        for i in range(n_frames)
    ]
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


def _write_echem_csv(path: str, n_frames: int) -> str:
    """frame/voltage/capacity 列の小 CSV を書き出す (正常系・欠損なし)。🔵"""
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "voltage", "capacity"])
        for i in range(n_frames):
            writer.writerow([i, round(3.5 - 0.1 * i, 4), float(i)])
    return path


def _intervals_from_boundaries(boundaries: tuple[int, ...], n: int) -> tuple[tuple[int, int], ...]:
    """区間分割の boundaries から判別対象区間 [(0,b0),(b0,b1),...,(bk,n-1)] を構成する (両端 inclusive)。

    設計判断④の索引規約。境界なし (単一セグメント) は (0, n-1) 1 本へ縮退する。
    """
    edges = (0, *boundaries, n - 1)
    return tuple((edges[i], edges[i + 1]) for i in range(len(edges) - 1))


def _run_operando_pipeline(tmp_dir: Path, *, n_frames: int = 8) -> SimpleNamespace:
    """operando 一気通貫を公開 API のみで実行し結果束を返す (fixture / 決定論テスト共用)。

    echem CSV 同期 → セル固定相込み逐次解析 (segment) → IC 区間分割 → 区間ごと判別 (discriminate) →
    結合出力 CSV → 共有 Ledger verify、を 1 パスで結線する。全 refine 系は SimulatedBackend で決定論。
    """
    # 【作業ディレクトリ保証】: fixture 経路は tmp_path_factory.mktemp で既存だが、直接呼び出し経路
    #   (TC-035-15 の tmp_path/"run1" 等) は未作成の副ディレクトリを渡すため CSV 書き出し前に作成する。
    #   mktemp と同じ「ディレクトリ存在」前提へ揃える最小補正 (assertion 不変・両経路で no-op/作成)。🟡
    tmp_dir.mkdir(parents=True, exist_ok=True)
    backend = SimulatedBackend(peak_fwhm=0.2)
    series = _two_phase_series(n_frames=n_frames)

    # 【入口: echem CSV 同期】: frame 同期キー + 容量→組成 x 換算で EchemData を得る 🔵
    echem_path = tmp_dir / "echem.csv"
    _write_echem_csv(str(echem_path), n_frames)
    echem = read_echem_csv(
        str(echem_path), column_map=ECHEM_COLUMN_MAP, capacity_to_x=CAPACITY_TO_X
    )

    # 【共有 Ledger】: segment と discriminate を 1 本の追記専用ハッシュチェーンへ集約する 🔵
    ledger = Ledger()
    queue = ReviewQueue(ledger=ledger)

    # 【セル固定相込み逐次解析 + IC 区間分割】: 固定相 AL 常駐 (scale のみ解放) で境界を得る 🔵
    seg = segment_series(backend, series, INITIAL, fixed_phases=(AL,), ledger=ledger)

    # 【区間ごと FR-313 判別】: boundaries から区間を構成し端点マルチスタート込みで判別する 🔵
    intervals = _intervals_from_boundaries(seg.boundaries, n_frames)
    discs = [
        discriminate_interval(
            backend, series, iv, INITIAL,
            config=CONFIG_FAST, fixed_phases=(AL,), ledger=ledger, queue=queue,
        )
        for iv in intervals
    ]

    # 【結合出力用 Trajectory】: 固定相を初期相に含めた逐次 run の trajectory (設計判断②a) 🟡
    seq = SequentialEngine(backend).run(series, [INITIAL[0], AL.phase])
    trajectory = seq.trajectory

    # 【結合出力 CSV】: trajectory + echem (V/I/Q/x) を frame_index で外部結合し書き出す 🔵
    csv_path = tmp_dir / "combined.csv"
    written = combined_csv(trajectory, echem, str(csv_path))

    return SimpleNamespace(
        backend=backend,
        series=series,
        echem=echem,
        echem_path=echem_path,
        ledger=ledger,
        seg=seg,
        intervals=intervals,
        discs=discs,
        trajectory=trajectory,
        written=written,
        csv_bytes=Path(written).read_bytes(),
        n_frames=n_frames,
    )


@pytest.fixture(scope="module")
def operando_run(tmp_path_factory) -> SimpleNamespace:
    """operando 一気通貫を 1 回だけ実行し正常系 (TC-035-04〜09) で読み取り専用共有する。

    【テスト前準備】: 公開 API (from tsumugin import ...) のみで echem 同期 → 固定相込み分割 →
    区間判別 → 結合出力 CSV → 共有 Ledger を通し、frozen な結果束を正常系で共有する (M2 warming_run の範)。🔵
    """
    tmp_dir = tmp_path_factory.mktemp("operando_e2e")
    return _run_operando_pipeline(tmp_dir)


# ---------------------------------------------------------------------------
# 1. 正常系テストケース (TC-035-01〜11)
# ---------------------------------------------------------------------------


def test_m3_public_symbols_are_reexported():
    # 【テスト目的】: M3 公開シンボルが from tsumugin import ... で解決し期待の型を持つ (TC-035-01)
    # 【テスト内容】: モジュール冒頭 import 済みの各シンボルが class / dataclass / 関数 のいずれか検証
    # 【期待される動作】: トップレベル tsumugin 名前空間から M3 中核シンボルへ到達できる (完了条件①)
    # 🔵 信頼性レベル: 要件定義 §2.1 / 完了条件① / test_m2_public_symbols_are_reexported の範に依拠

    # 【結果検証】: エンジン系・ローダ系・Protocol はクラス
    for cls in (MultistartEngine, BiologicMprLoader, XraylibMuCalculator, EchemLoader, MuCalculator):
        assert inspect.isclass(cls)  # 【確認内容】: エンジン/ローダ/Protocol はクラス 🔵

    # 【結果検証】: 値オブジェクト系は dataclass
    for dc in (
        MultistartConfig,
        MultistartResult,
        BasinInfo,
        PerturbationSpec,
        AbsorptionConfig,
        CellConfig,
        CellLayer,
        BeamConfig,
        EchemData,
        FixedPhaseSpec,
        DiscriminationConfig,
        DiscriminationResult,
        SegmentationConfig,
        SegmentationResult,
        TransitionPoint,
        BranchComparison,
    ):
        assert dataclasses.is_dataclass(dc)  # 【確認内容】: 値オブジェクトは dataclass 🔵

    # 【結果検証】: 純関数系は callable でありクラスでない
    for fn in (
        read_echem_csv,
        discriminate_interval,
        segment_series,
        combined_csv,
        transition_point,
        transmission_factor,
        cluster_basins,
        generate_starts,
        fixed_free_suffixes,
        split_branches,
        branch_differences,
    ):
        assert callable(fn) and not inspect.isclass(fn)  # 【確認内容】: 関数として呼び出し可能 🔵

    # 【期待値確認】: プリセットは読み取り可能な Mapping 🔵
    assert isinstance(CELL_PHASE_PRESETS, Mapping)  # 【確認内容】: プリセットは Mapping 🔵


def test_m3_symbols_in_dunder_all_and_sorted():
    # 【テスト目的】: 昇格 M3 シンボルが tsumugin.__all__ に含まれ昇順ソート + 後方互換維持 (TC-035-02)
    # 【テスト内容】: __all__ の包含関係・ソート順・M0/M1/M2 分の後方互換 (削除なし)・実属性整合を検証
    # 【期待される動作】: __all__ が M0/M1/M2 + M3 を統合しアルファベット昇順のまま (完了条件① / REQ-404)
    # 🔵 信頼性レベル: 要件定義 §2.1 / REQ-404 / 既存 __init__.py の __all__ 慣習に直接依拠

    exported = set(tsumugin.__all__)

    # 【結果検証】: 昇格 M3 シンボルが公開面 (__all__) に配線されていること
    assert _M3_PROMOTED_SYMBOLS <= exported  # 【確認内容】: M3 シンボルが __all__ に包含 🔵
    # 【後方互換】: 既存 M0/M1/M2 シンボルが 1 つも削除・改名されていないこと (REQ-404)
    assert _M0M1M2_PUBLIC_SYMBOLS <= exported  # 【確認内容】: M0/M1/M2 公開面の非破壊 (後方互換維持) 🔵
    # 【規約遵守】: __all__ がアルファベット昇順ソートを維持していること
    assert list(tsumugin.__all__) == sorted(tsumugin.__all__)  # 【確認内容】: 昇順ソート維持 🔵


def test_m3_reexports_are_same_object():
    # 【テスト目的】: トップレベルのシンボルがサブパッケージ実体と同一オブジェクト (TC-035-03)
    # 【テスト内容】: re-export が別実装・コピーでなくサブパッケージ実体の別名付けであることを is で検証
    # 【期待される動作】: MultistartEngine 等がサブパッケージ属性と is 一致 (二重実装防止)
    # 🔵 信頼性レベル: 要件定義 §2.1 / test_m2_e2e.py L304-308 の範に依拠

    assert MultistartEngine is tsumugin.multistart.MultistartEngine  # 【確認内容】: 同一実体 🔵
    assert discriminate_interval is tsumugin.operando.discriminate_interval  # 【確認内容】: 同一実体 🔵
    assert segment_series is tsumugin.operando.segment_series  # 【確認内容】: 同一実体 🔵
    assert combined_csv is tsumugin.operando.combined_csv  # 【確認内容】: 同一実体 🔵
    assert CellConfig is tsumugin.model.CellConfig  # 【確認内容】: 同一実体 🔵
    assert AbsorptionConfig is tsumugin.absorption.AbsorptionConfig  # 【確認内容】: 同一実体 🔵


def test_e2e_operando_pipeline_completes(operando_run: SimpleNamespace):
    # 【テスト目的】: operando 一気通貫が例外なく完走し各層の結果を返す (TC-035-04 / TC-209-01)
    # 【テスト内容】: echem 同期 → 固定相込み segment → 区間 discriminate → combined_csv → ledger の完走検証
    # 【期待される動作】: fixture が SegmentationResult / DiscriminationResult 列 / CSV / 健全 Ledger を返す
    # 🔵 信頼性レベル: 完了条件② / TC-209-01 / docs/design/m3-operando/dataflow.md の operando 縦串に依拠

    # 【結果検証】: 一気通貫の各層が破綻せず期待の型を返す (公開 API 経由の縦串成立)
    assert isinstance(operando_run.seg, SegmentationResult)  # 【確認内容】: 分割結果を得る 🔵
    assert operando_run.discs  # 【確認内容】: 少なくとも 1 区間分の判別結果が得られる 🔵
    for disc in operando_run.discs:
        assert isinstance(disc, DiscriminationResult)  # 【確認内容】: 各区間は判別結果 🔵
    assert isinstance(operando_run.echem, EchemData)  # 【確認内容】: echem 同期結果を得る 🔵
    assert Path(operando_run.written).exists()  # 【確認内容】: 結合出力 CSV が実在 🔵


def test_e2e_echem_synced_to_frames(operando_run: SimpleNamespace):
    # 【テスト目的】: echem CSV が frame 同期の EchemData へ変換される (TC-035-05)
    # 【テスト内容】: read_echem_csv が frame_index 位置整列の voltage / 容量→x 換算 composition_x を返すか
    # 【期待される動作】: voltage 長 = n_frames / composition_x[i] == slope·Q_i + intercept (FR-311)
    # 🔵 信頼性レベル: TC-209-01 (echem CSV 同期) / echem.py 実 API (note §3.3) に依拠

    echem = operando_run.echem
    n = operando_run.n_frames
    slope, intercept = CAPACITY_TO_X

    # 【結果検証】: フレーム同期長 + 容量→組成 x の線形換算一致
    assert len(echem.voltage) == n  # 【確認内容】: voltage が frame_index 位置に整列 (長さ=n_frames) 🔵
    assert len(echem.composition_x) == n  # 【確認内容】: composition_x も全フレーム分算出 🔵
    for i in range(n):
        assert echem.composition_x[i] == pytest.approx(slope * float(i) + intercept)
        # 【確認内容】: 容量→組成 x = slope·Q + intercept の線形換算一致 🔵


def test_e2e_segmentation_with_fixed_phase(operando_run: SimpleNamespace):
    # 【テスト目的】: segment_series が固定相込みで昇順 boundaries を返す (TC-035-06)
    # 【テスト内容】: 固定相 AL 常駐の分割が昇順・端非含有・n_segments 整合・注入 Ledger 保持を満たすか
    # 【期待される動作】: boundaries は昇順 int / 全て 0<b<n / n_segments == len(boundaries)+1 (FR-316/312)
    # 🔵 信頼性レベル: TC-209-01 (固定相 + 区間分割) / segmentation.py 契約 (note §3.5) に依拠

    seg = operando_run.seg
    n = operando_run.n_frames

    # 【結果検証】: 境界の昇順・端非含有・セグメント数整合・注入 Ledger の同一性
    assert list(seg.boundaries) == sorted(seg.boundaries)  # 【確認内容】: boundaries は昇順 🔵
    assert all(0 < b < n for b in seg.boundaries)  # 【確認内容】: 端 0/n を含まない内部境界 🔵
    assert seg.n_segments == len(seg.boundaries) + 1  # 【確認内容】: n_segments = 境界数 + 1 🔵
    assert seg.ledger is operando_run.ledger  # 【確認内容】: 注入した共有 Ledger をそのまま保持 🔵


def test_e2e_discrimination_verdict_and_multistart(operando_run: SimpleNamespace):
    # 【テスト目的】: 区間ごとに verdict と端点マルチスタートが得られる (TC-035-07)
    # 【テスト内容】: 各区間 discriminate が 3 値 verdict と n_starts 一致の MultistartResult を返すか
    # 【期待される動作】: verdict ∈ 3 値 / multistart_single・two_phase が MultistartResult (FR-313/230)
    # 🔵 信頼性レベル: TC-209-01 (区間判別) / discrimination.py 契約 (note §3.6) に依拠

    for disc in operando_run.discs:
        # 【結果検証】: verdict の値域とマルチスタート結果の型・本数
        assert disc.verdict in VERDICTS  # 【確認内容】: verdict は 3 値のいずれか 🔵
        assert isinstance(disc.multistart_single, MultistartResult)  # 【確認内容】: A 端点マルチスタート 🔵
        assert isinstance(disc.multistart_two_phase, MultistartResult)  # 【確認内容】: B 端点マルチスタート 🔵
        assert disc.multistart_single.n_starts == CONFIG_FAST.multistart.n_starts
        # 【確認内容】: マルチスタート本数 == config.multistart.n_starts (端点必須適用) 🔵
        assert math.isfinite(disc.delta_evidence)  # 【確認内容】: ΔBIC が有限 (非有限を漏らさない) 🔵


def test_e2e_combined_csv_written_and_readback(operando_run: SimpleNamespace, tmp_path):
    # 【テスト目的】: combined_csv が echem 列入り CSV を書き出し読み戻せる (TC-035-08)
    # 【テスト内容】: trajectory + echem を frame_index 外部結合した CSV が DictReader で読め非有限漏洩なし
    # 【期待される動作】: ヘッダに wt_frac/格子 列 + voltage/composition_x 列 / セルに inf/nan 文字列なし (FR-314)
    # 🔵 信頼性レベル: TC-209-01 (結合出力 CSV) / output.py 契約 (note §3.7) に依拠

    written = operando_run.written
    assert Path(written).exists()  # 【確認内容】: 結合出力 CSV がファイルとして実在 🔵

    with open(written, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    # 【結果検証】: trajectory 相列 + echem 列の存在と読み戻し + 非有限漏洩なし
    assert any(name.endswith(".wt_frac") for name in fieldnames)  # 【確認内容】: 相分率(x) 列を含む 🔵
    assert "voltage" in fieldnames  # 【確認内容】: echem 電圧列を含む 🔵
    assert "composition_x" in fieldnames  # 【確認内容】: echem 組成 x 列を含む 🔵
    assert len(rows) == operando_run.n_frames  # 【確認内容】: frame_index 和集合で n_frames 行 🔵
    for row in rows:
        for cell in row.values():
            assert "inf" not in cell.lower() and "nan" not in cell.lower()
            # 【確認内容】: 非有限 (inf/nan) は空欄化され文字列漏洩しない 🔵


def test_e2e_shared_ledger_verifies(operando_run: SimpleNamespace):
    # 【テスト目的】: 共有 ledger の verify() が True かつ entries 非空 (TC-035-09)
    # 【テスト内容】: segment/discriminate へ注入した共有 Ledger が実行後も無傷 (改竄なし) か検証
    # 【期待される動作】: verify() is True かつ len(entries) > 0 (空 ledger の自明 True でない / NFR-105)
    # 🔵 信頼性レベル: TC-209-01 (ledger verify) / NFR-105 / P2 に依拠

    ledger = operando_run.ledger

    # 【結果検証】: ハッシュ連鎖が無傷 + 非空 (segment と discriminate が同一チェーンへ集約)
    assert ledger.verify() is True  # 【確認内容】: 追記専用ハッシュチェーンが無傷 🔵
    assert len(ledger.entries) > 0  # 【確認内容】: 空 ledger の自明 True でない 🔵


def test_readme_m3_example_executes(tmp_path):
    # 【テスト目的】: README「使い方 (M3)」節の最小使用例と同等コードが動作する (TC-035-10)
    # 【テスト内容】: 公開 import → 合成 → segment/discriminate → combined_csv → verify の写経実行と完走検証
    # 【期待される動作】: 使用例が例外なく実行され CSV 実在 + ledger.verify() is True (完了条件⑤)
    # 🟡 信頼性レベル: 完了条件⑤ / 要件定義 §2.3 からの妥当な推測 (README 文面は Green で確定)

    # --- ここから README 使用例と同等のコード (公開 API のみ使用) ---
    # 【テストデータ準備】: 二相反応 (端成分 α/β の scale 漸移) + Al 固定相を重畳した合成系列
    backend = SimulatedBackend(peak_fwhm=0.2)
    two_theta = np.arange(15.0, 60.0, 0.05)
    n_frames = 6
    al = CELL_PHASE_PRESETS["Al"].phase.with_updates(scale=0.7)
    rows = []
    for i in range(n_frames):
        t = i / (n_frames - 1)
        phases = []
        if 1.0 - t > 0.0:
            phases.append(PhaseInstance("alpha", LatticeParams(5.0, 5.0, 5.0), scale=1.0 - t))
        if t > 0.0:
            phases.append(PhaseInstance("beta", LatticeParams(5.06, 5.06, 5.06), scale=t))
        phases.append(al)
        rows.append(backend.simulate(phases, two_theta))
    series = FrameSeries(two_theta, np.asarray(rows, dtype=float))

    fixed = CELL_PHASE_PRESETS["Al"]
    initial = (PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0)),)
    ledger = Ledger()
    seg = segment_series(backend, series, initial, fixed_phases=(fixed,), ledger=ledger)
    disc = discriminate_interval(
        backend, series, (0, n_frames - 1), initial,
        config=DiscriminationConfig(multistart=MultistartConfig(n_starts=2)),
        fixed_phases=(fixed,), ledger=ledger,
    )
    echem_path = tmp_path / "echem.csv"
    _write_echem_csv(str(echem_path), n_frames)
    echem = read_echem_csv(str(echem_path), column_map=ECHEM_COLUMN_MAP, capacity_to_x=(0.1, 0.0))
    trajectory = SequentialEngine(backend).run(series, [initial[0], al]).trajectory
    written = combined_csv(trajectory, echem, str(tmp_path / "combined.csv"))
    # --- ここまで README 使用例と同等のコード ---

    # 【結果検証】: 使用例の出力が公開 API の実シグネチャ・契約に追従していること
    assert seg.n_segments >= 1  # 【確認内容】: 分割が最低 1 セグメントを返す 🟡
    assert disc.verdict in VERDICTS  # 【確認内容】: 判別 verdict が 3 値のいずれか 🟡
    assert Path(written).exists()  # 【確認内容】: 使用例の最終出力 CSV が実在 🟡
    assert ledger.verify() is True  # 【確認内容】: 使用例経路でも ledger 連鎖が無傷 🟡


@pytest.mark.gsas
def test_e2e_gsasii_multistart_n4_smoke():
    # 【テスト目的】: GSASIIBackend でマルチスタート N=4 smoke が完走する (TC-035-11 / TC-209-02)
    # 【テスト内容】: 実 GSAS-II 精密化を用いた N=4 マルチスタートが破綻せず MultistartResult を返すか検証
    # 【期待される動作】: バックエンド交換 (P7) してもマルチスタートが同契約で完走 (完了条件③)
    # 🔵 信頼性レベル: 完了条件③ / TC-209-02 / test_m2_e2e.py の @gsas パターンに依拠

    from tsumugin.backends.gsasii import GSASIIBackend

    # 【テストデータ準備】: GSAS-II が確実に計算できる立方相 1 相 + 合成強度
    backend = GSASIIBackend()
    phase = _phase(4.0, "P")
    intensity = backend.simulate([phase], GRID_GSAS)

    # 【実際の処理実行】: 実バックエンドで N=4 マルチスタートを回す
    result = MultistartEngine(backend, config=MultistartConfig(n_starts=4)).run(
        (phase,), GRID_GSAS, intensity
    )

    # 【結果検証】: 例外なく完走し basins 非空 + n_starts == 4
    assert isinstance(result, MultistartResult)  # 【確認内容】: 実バックエンドでも実体を返す 🔵
    assert len(result.basins) >= 1  # 【確認内容】: basin が非空 (全滅していない) 🔵
    assert result.n_starts == 4  # 【確認内容】: 指定 N=4 本を実行 🔵


# ---------------------------------------------------------------------------
# 2. 異常系テストケース (TC-035-12〜14)
# ---------------------------------------------------------------------------


def test_e2e_echem_missing_column_raises(tmp_path):
    # 【テスト目的】: echem CSV の必須列欠損は ValueError (TC-035-12)
    # 【テスト内容】: column_map が指す列 (voltage) が CSV に無いとき fail-loud に停止するか検証
    # 【期待される動作】: 沈黙した誤同期でなく即 ValueError (M1/M2 教訓)
    # 🔵 信頼性レベル: read_echem_csv 欠損列 ValueError (note §3.3) に依拠

    # 【テストデータ準備】: voltage 列を欠く CSV (frame, capacity のみ)
    path = tmp_path / "echem_missing.csv"
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["frame", "capacity"])
        for i in range(4):
            writer.writerow([i, float(i)])

    # 【結果検証】: voltage を要求する column_map で欠損列を検出し ValueError
    with pytest.raises(ValueError):  # 【確認内容】: 誤った EchemData を作らず即停止 🔵
        read_echem_csv(str(path), column_map=ECHEM_COLUMN_MAP)


def test_e2e_undecided_escalates_without_exception(tmp_path):
    # 【テスト目的】: 判別 undecided はエスカレーションのみで例外化しない (TC-035-13)
    # 【テスト内容】: 両仮説高 R を誘発 (high_r_threshold=0.0) し verdict=undecided + escalations 非空を検証
    # 【期待される動作】: 縮退でも例外を出さず undecided + queue 通知で一気通貫を止めない (EDGE-002/005)
    # 🔵 信頼性レベル: EDGE-002/005 / 要件定義 §4 / discrimination._decide_verdict に依拠

    series = _two_phase_series(n_frames=6)
    ledger = Ledger()
    queue = ReviewQueue(ledger=ledger)
    # 【高 R 強制】: high_r_threshold=0.0 なら両仮説 rwp>0 が必ず高 R 判定 → undecided へ決定論縮退 🔵
    config = DiscriminationConfig(multistart=MultistartConfig(n_starts=2), high_r_threshold=0.0)

    # 【実際の処理実行】: 縮退区間でも例外化しない
    disc = discriminate_interval(
        series=series, backend=SimulatedBackend(peak_fwhm=0.2),
        frame_range=(0, 5), initial_phases=INITIAL,
        config=config, fixed_phases=(AL,), ledger=ledger, queue=queue,
    )

    # 【結果検証】: 誤自動確定せず undecided + エスカレーション通知 (処理はブロックしない)
    assert disc.verdict == "undecided"  # 【確認内容】: 両仮説高 R で判別を確定しない 🔵
    assert disc.escalations  # 【確認内容】: エスカレーション文字列が非空 (queue へ通知) 🔵
    assert ledger.verify() is True  # 【確認内容】: 縮退経路でも ledger 連鎖が無傷 🔵


def test_e2e_single_segment_completes(tmp_path):
    # 【テスト目的】: 単一セグメント (boundaries 空) でも完走する (TC-035-14)
    # 【テスト内容】: 分割を抑止 (improvement_threshold 特大) し境界空 → 区間 (0,n-1) 1 本を判別し完走するか
    # 【期待される動作】: 区間ループが 0 反復にならず 1 区間分の disc + ledger.verify() True (区間縮退)
    # 🔵 信頼性レベル: 要件定義 §4 (区間数 1 の縮退) に依拠

    n_frames = 8
    series = _solid_solution_series(n_frames=n_frames)
    ledger = Ledger()
    # 【分割抑止】: improvement_threshold を特大にし貪欲挿入が採択されない → boundaries=() 決定論 🔵
    seg = segment_series(
        SimulatedBackend(peak_fwhm=0.2), series, INITIAL,
        config=SegmentationConfig(improvement_threshold=1e9), fixed_phases=(AL,), ledger=ledger,
    )
    assert seg.boundaries == ()  # 【前提確認】: 境界が空 (単一セグメント) に縮退している 🔵

    # 【実際の処理実行】: 空境界から区間 (0, n-1) 1 本を構成して判別する
    intervals = _intervals_from_boundaries(seg.boundaries, n_frames)
    discs = [
        discriminate_interval(
            SimulatedBackend(peak_fwhm=0.2), series, iv, INITIAL,
            config=CONFIG_FAST, fixed_phases=(AL,), ledger=ledger,
        )
        for iv in intervals
    ]

    # 【結果検証】: 区間ループが 1 反復で回り例外なく完走 + ledger 健全
    assert intervals == ((0, n_frames - 1),)  # 【確認内容】: 単一区間 (0, n-1) を構成 🔵
    assert len(discs) == 1  # 【確認内容】: 1 区間分の判別が得られる (0 反復でない) 🔵
    assert discs[0].verdict in VERDICTS  # 【確認内容】: verdict は 3 値のいずれか 🔵
    assert ledger.verify() is True  # 【確認内容】: 単一セグメントでも ledger 連鎖が無傷 🔵


# ---------------------------------------------------------------------------
# 3. 境界値テストケース (TC-035-15〜18)
# ---------------------------------------------------------------------------


def test_e2e_deterministic_bitwise_identical(tmp_path):
    # 【テスト目的】: 同一入力 2 回実行で verdict/boundaries/CSV がビット同一 (TC-035-15)
    # 【テスト内容】: 独立 Ledger で一気通貫を 2 回実行し verdict 列/境界/CSV バイト列が == 一致するか検証
    # 【期待される動作】: 乱数・時刻・集合反復順に依存せず完全再現 (マルチスタートも n_starts 決定論 / NFR-102)
    # 🔵 信頼性レベル: NFR-102 / REQ-402 / test_m2_e2e.py L603 に依拠

    run1 = _run_operando_pipeline(tmp_path / "run1", n_frames=8)
    run2 = _run_operando_pipeline(tmp_path / "run2", n_frames=8)

    # 【結果検証】: verdict 列・境界・CSV バイト列がビット同一
    assert [d.verdict for d in run1.discs] == [d.verdict for d in run2.discs]
    # 【確認内容】: 区間 verdict 列が完全一致 🔵
    assert run1.seg.boundaries == run2.seg.boundaries  # 【確認内容】: 分割境界が完全一致 🔵
    assert run1.csv_bytes == run2.csv_bytes  # 【確認内容】: 結合出力 CSV がビット同一 (決定論) 🔵


def test_dunder_all_names_all_resolvable():
    # 【テスト目的】: __all__ の全名称が実属性として解決できる (TC-035-16)
    # 【テスト内容】: tsumugin.__all__ の全要素が hasattr(tsumugin, name) を満たすか (dangling 名なし)
    # 【期待される動作】: 公開契約 (__all__) と実装 (実属性) の乖離ゼロ (追記時 typo/実体欠落の検出)
    # 🔵 信頼性レベル: 要件定義 §2.1 / test_m2_e2e.py L326-327 に依拠

    for name in tsumugin.__all__:
        assert hasattr(tsumugin, name)  # 【確認内容】: __all__ と実属性の乖離が無い 🔵


def test_e2e_discrimination_performance_within_budget():
    # 【テスト目的】: 判別 1 区間 (N=8) が 30 秒以内 (TC-035-17 / TC-209-03)
    # 【テスト内容】: 粗グリッド + 小フレーム + N=8 の 1 区間判別の direct refine 経路の性能を計測
    # 【期待される動作】: 区間端点マルチスタート込みでも実用規模の最小担保内 (NFR-001)
    # 🟡 信頼性レベル: TC-209-03 (性能閾値は妥当な推測) / N=8 はマルチスタート既定下限 (FR-231)

    series = _two_phase_series(n_frames=8)
    # 【N=8 config】: マルチスタート既定下限 (DiscriminationConfig の既定 multistart は n_starts=8) 🔵
    config = DiscriminationConfig(multistart=MultistartConfig(n_starts=8))

    # 【実際の処理実行】: 1 区間 (0, 7) の判別 1 回の経過時間を測る
    start = time.perf_counter()
    disc = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), INITIAL,
        config=config, fixed_phases=(AL,),
    )
    elapsed = time.perf_counter() - start

    # 【結果検証】: 完走 + 時間予算内 (CI 変動を見た閾値マージン)
    assert disc.verdict in VERDICTS  # 【確認内容】: 判別が完走し verdict を返す 🔵
    assert disc.multistart_single.n_starts == 8  # 【確認内容】: N=8 本のマルチスタートを実行 🔵
    assert elapsed < 30.0  # 【確認内容】: 30 秒以内 (NFR-001 性能境界) 🟡


def test_e2e_empty_series_degrades_gracefully():
    # 【テスト目的】: 空 FrameSeries など最小入力で縮退する (TC-035-18)
    # 【テスト内容】: n_frames=0 の空系列を segment_series へ渡しても例外化せず縮退結果を返すか検証
    # 【期待される動作】: 空・単一入力でも例外を投げず ledger.verify() True (segment_series の縮退規約)
    # 🟡 信頼性レベル: M0/M1/M2 縮退規約からの妥当な推測 (空入力挙動は実挙動で確定)

    # 【テストデータ準備】: 測定フィルタ後に全フレーム除外された等の空入力 (n_frames=0)
    series = FrameSeries(GRID, np.empty((0, GRID.size)))

    # 【実際の処理実行】: 空入力でも例外化せず縮退結果を返す
    seg = segment_series(SimulatedBackend(peak_fwhm=0.2), series, INITIAL, fixed_phases=(AL,))

    # 【結果検証】: 空/縮退結果 + ledger 健全 (最小入力でクラッシュしない)
    assert isinstance(seg, SegmentationResult)  # 【確認内容】: 例外でなく縮退結果を返す 🟡
    assert seg.boundaries == ()  # 【確認内容】: 分割不能で境界空へ縮退 🟡
    assert seg.ledger.verify() is True  # 【確認内容】: 空入力でも ledger 連鎖が無傷 🟡
