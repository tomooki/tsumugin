"""TASK-0033 operando/segmentation — IC 区間自動分割 (FR-316 / 設計 D5/D6) の失敗テスト (TDD Red)。

対象実装 (**未実装**): ``src/tsumugin/operando/segmentation.py`` の
``SegmentationConfig`` / ``SegmentationResult`` / ``segment_series``。

契約は ``docs/design/m3-operando/interfaces.py`` L287-321 に確定。テストケース定義
(operando-segmentation-testcases.md) の 17 件 (正常系 9 / 異常系 2 / 境界値 6) に 1:1 対応する。

合成データ方針 (決定論 / GSAS-II 非依存):
- **2 区間系列 (``_two_regime_series``)**: 前半・後半をそれぞれ格子 a を初期値 5.0 から連続変化させる
  ランプ (固溶体) とし、区間境界 T で a を初期値へ**不連続にリセット**する (機構切替)。単相 warm-start
  逐次 refine の区間コストでは、境界を跨ぐと直近フレームの格子から遠い基底へジャンプできず (ピーク非重畳
  で勾配 0)、以降のフレームが誤収束 (chi2 大 / bic 大) する。境界で区間を切り直すと初期値から再開して
  適合するため Σbic が減り、k=2 が k=1 に勝つ (真の切替位置に境界 1 本)。
- **一様系列 (``_uniform_series``)**: 全フレーム同一格子。どの区間も完全適合 → 分割は Σbic を減らさず
  ペナルティだけ増えるため k=1 が最良 (過分割抑止)。
- 失敗注入は ``FailAllBackend`` / ``FrameFailBackend``、呼び出し記録は ``CountingSpyBackend`` /
  ``FreeParamsSpyBackend`` で行う。いずれも ``RefinementBackend`` Protocol (name + refine) のみ満たす。

対象モジュール未実装のため collection 時に import が失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

import dataclasses
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance
from tsumugin.operando.cell_phases import CELL_PHASE_PRESETS
from tsumugin.sequential.series import FrameSeries
from tsumugin.store.ledger import Ledger

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定 (Red)。
from tsumugin.operando.segmentation import (  # noqa: E402
    SegmentationConfig,
    SegmentationResult,
    segment_series,
)

# ---------------------------------------------------------------------------
# 共通テストデータ・ヘルパ (モジュールレベルで一度だけ構築し不変共有する)
# ---------------------------------------------------------------------------

# 【観測グリッド】: smoke 用に粗く軽量な 0.1 刻み (15-40°)。a≈5.0 で (100)(110)(111)(200) の 4 反射を含む。🟡
GRID = np.arange(15.0, 40.0, 0.1)

# 【ピーク幅】: 0.1 刻みで十分サンプリングでき、境界ジャンプ (>2 FWHM) で確実に非重畳になる 0.3。🟡
FWHM = 0.3

# 【活物質の初期相】: 立方格子 a=b=c=5.0 の単相 (区間 warm-start 逐次 refine の初期起点)。🔵
PHASE_A0 = PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0), scale=1.0)
INITIAL = (PHASE_A0,)


def _backend() -> SimulatedBackend:
    """乱数なし決定論バックエンド (ビット同一)。🔵"""
    return SimulatedBackend(peak_fwhm=FWHM)


def _phase(a: float, ref: str = "A", scale: float = 1.0) -> PhaseInstance:
    """立方格子 (a=b=c) の相インスタンスを組む (a を変えると全反射のピーク位置が動く)。🔵"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _two_regime_series(
    true_boundary: int, n_frames: int, *, a_lo: float = 5.0, a_hi: float = 5.20
) -> FrameSeries:
    """境界 ``true_boundary`` で機構が切り替わる 2 区間合成系列を組む (前半・後半とも a を a_lo→a_hi ランプ)。

    区間 [0, T-1] と [T, n-1] のそれぞれで単相格子 a を a_lo から a_hi へ連続変化させ、境界 T で a を
    a_lo へ不連続リセットする。単相 warm-start 逐次 refine の区間コストは、境界を跨ぐ区間では直近格子
    (≈a_hi) から真値 (≈a_lo) へジャンプできず誤収束するため Σbic が増える。境界で切ると初期値から再開して
    適合するため k=2 が最良になる。🔵 note.md §5 / requirements N1
    """
    backend = _backend()
    rows = []
    for i in range(n_frames):
        if i < true_boundary:
            span = max(true_boundary - 1, 1)
            a = a_lo + (a_hi - a_lo) * i / span
        else:
            span = max(n_frames - true_boundary - 1, 1)
            a = a_lo + (a_hi - a_lo) * (i - true_boundary) / span
        # 【フレーム識別性の回復】: 前半・後半は同一 a ランプ (a_lo→a_hi) のため素の content が
        # 区間間でビット同一になり、content 一致で判定する ``_match_frame`` が frame 6..11 を 0..5 へ
        # 畳んでしまう (N6 の set(range(n)) 被覆・N-partial の fail_frames={7} が到達不能になる)。
        # scale に global frame index 由来の極小オフセット (1e-6·i) を与えて全 12 フレームの content を
        # 一意にする。scale は区間 refine で解放される (＝完全にフィットされ chi2 に寄与しない) ため、
        # 分割コスト・境界判定・決定論はビット等価に保たれ、被覆/局所失敗の識別のみが回復する。
        rows.append(backend.simulate([_phase(a, scale=1.0 + 1e-6 * i)], GRID))
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


def _uniform_series(n_frames: int, *, a: float = 5.0) -> FrameSeries:
    """全フレーム同一格子の一様系列 (機構切替なし → k=1 が最良・過分割抑止の検証)。🔵 note.md §5"""
    backend = _backend()
    rows = [backend.simulate([_phase(a)], GRID) for _ in range(n_frames)]
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


def _sawtooth_series(n_regimes: int, frames_per_regime: int, *, a_hi: float = 5.15) -> FrameSeries:
    """各区間が a を 5.0→a_hi ランプする鋸歯系列 (区間境界ごとに a を 5.0 へリセット)。多境界データ。🟡"""
    backend = _backend()
    rows = []
    for _ in range(n_regimes):
        for j in range(frames_per_regime):
            a = 5.0 + (a_hi - 5.0) * j / max(frames_per_regime - 1, 1)
            rows.append(backend.simulate([_phase(a)], GRID))
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


# ---------------------------------------------------------------------------
# テストダブル (失敗注入 / 呼び出し記録)
# ---------------------------------------------------------------------------


def _match_frame(series: FrameSeries, intensity: np.ndarray) -> int | None:
    """refine 入力強度が series のどのフレーム行かを厳密一致で判定する (warm-start は強度を変えない)。"""
    arr = np.asarray(intensity, dtype=float)
    for i in range(series.n_frames):
        row = np.asarray(series.intensities[i], dtype=float)
        if row.shape == arr.shape and np.array_equal(row, arr):
            return i
    return None


class FailAllBackend:
    """全フレームで収束失敗 (chi2=inf) を返す病的バックエンド (E1 / 全滅縮退)。"""

    name = "fail-all"

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        return RefinementResult(
            phases=model.phases,
            chi2=float("inf"),
            rwp=float("inf"),
            n_obs=int(np.asarray(model.intensity).size),
            n_params=len(model.free_params),
            converged=False,
            n_cycles=1,
            free_params=frozenset(model.free_params),
        )


class FrameFailBackend:
    """指定フレームのみ chi2=inf を返し、他は SimulatedBackend へ委譲する (E2 / 局所失敗)。"""

    name = "frame-fail"

    def __init__(self, series: FrameSeries, fail_frames: set[int]) -> None:
        self._sim = _backend()
        self._series = series
        self._fail = set(fail_frames)

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        idx = _match_frame(self._series, model.intensity)
        if idx in self._fail:
            return RefinementResult(
                phases=model.phases,
                chi2=float("inf"),
                rwp=float("inf"),
                n_obs=int(np.asarray(model.intensity).size),
                n_params=len(model.free_params),
                converged=False,
                n_cycles=1,
                free_params=frozenset(model.free_params),
            )
        return self._sim.refine(model, max_cycles=max_cycles)


class CountingSpyBackend:
    """SimulatedBackend へ委譲しつつ refine 呼び出し数とフレーム index を記録する (N6 メモ化検証)。"""

    name = "counting-spy"

    def __init__(self, series: FrameSeries) -> None:
        self._sim = _backend()
        self._series = series
        self.frames: list[int | None] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        self.frames.append(_match_frame(self._series, model.intensity))
        return self._sim.refine(model, max_cycles=max_cycles)


class FreeParamsSpyBackend:
    """SimulatedBackend へ委譲しつつ refine の free_params / phase_refs を記録する (N9 固定相検証)。"""

    name = "free-params-spy"

    def __init__(self) -> None:
        self._sim = _backend()
        self.calls: list[dict] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        self.calls.append(
            {
                "free_params": frozenset(model.free_params),
                "phase_refs": tuple(p.phase_ref for p in model.phases),
            }
        )
        return self._sim.refine(model, max_cycles=max_cycles)


# ===========================================================================
# 1. 正常系テストケース
# ===========================================================================


def test_two_regime_series_adopts_k2_boundary_within_tolerance():
    # 【テスト目的】: 2 区間合成データで k=2 が採択され境界が真値 ±2 に入ることを確認する
    # 【テスト内容】: segment_series を貪欲挿入 + 粗→細スキャンで実行し boundaries を検証
    # 【期待される動作】: n_segments==2、境界 1 本が真値近傍に配置、k=2 の合計コストが k=1 未満
    # 🔵 信頼性レベル: acceptance-criteria.md TC-206-01 / architecture.md D5 に依拠

    # 【テストデータ準備】: 境界 T=6 で機構が切り替わる 12 フレーム合成系列 (乱数なし)
    T = 6
    series = _two_regime_series(true_boundary=T, n_frames=12)

    # 【実際の処理実行】: k=1→2 の貪欲挿入 + ±G 細密スキャン
    result = segment_series(_backend(), series, INITIAL)

    # 【結果検証】: 採択 k・境界本数・境界位置・k 別合計コストの単調性
    assert result.n_segments == 2  # 【検証項目】: k=2 採択 🔵
    assert len(result.boundaries) == 1  # 【検証項目】: 境界は 1 本 🔵
    assert abs(result.boundaries[0] - T) <= 2  # 【検証項目】: 境界 ±2 フレーム 🔵
    assert result.evidence_by_k[2] < result.evidence_by_k[1]  # 【検証項目】: k=2 が合計コスト最小 🔵


def test_uniform_series_selects_k1_no_oversegmentation():
    # 【テスト目的】: 機構切替のない一様系列で k=1 が最良となり境界を追加しないことを確認する
    # 【テスト内容】: 全フレーム同一格子の系列に segment_series を適用
    # 【期待される動作】: n_segments==1、boundaries==()、k=1 が k=2 以下の合計コスト
    # 🔵 信頼性レベル: acceptance-criteria.md TC-206-02 / requirements EDGE-004 に依拠

    # 【テストデータ準備】: 全フレーム a=5.0 の一様系列 (過分割抑止の代表入力)
    series = _uniform_series(n_frames=12)

    # 【実際の処理実行】: 境界追加の改善が閾値未満 → k=1 採択
    result = segment_series(_backend(), series, INITIAL)

    # 【結果検証】: 過分割抑止 (境界空・k=1 が最良)
    assert result.n_segments == 1  # 【検証項目】: k=1 採択 🔵
    assert result.boundaries == ()  # 【検証項目】: 境界を追加しない 🔵
    if 2 in result.evidence_by_k:
        assert result.evidence_by_k[2] >= result.evidence_by_k[1]  # k=2 は改善しない 🔵


def test_greedy_insertion_stops_below_improvement_threshold():
    # 【テスト目的】: k を増やしても改善が閾値未満になった時点で打ち切り max_segments まで走らないことを確認
    # 【テスト内容】: 真の区間数が 2 の系列に既定 config (improvement_threshold=10.0, max_segments=6) を適用
    # 【期待される動作】: n_segments < max_segments、探索した k が max_segments へ到達しない
    # 🔵 信頼性レベル: acceptance-criteria.md TC-206-03 / requirements REQ-013 に依拠

    # 【テストデータ準備】: 真の切替が 1 本 (k=2) の 12 フレーム系列
    series = _two_regime_series(true_boundary=6, n_frames=12)
    config = SegmentationConfig(max_segments=6, improvement_threshold=10.0)

    # 【実際の処理実行】: 改善が閾値未満で貪欲挿入を打ち切る
    result = segment_series(_backend(), series, INITIAL, config=config)

    # 【結果検証】: 打ち切り (探索が max_segments へ到達しない)
    assert result.n_segments == 2  # 【検証項目】: 真の区間数 2 を採択 🔵
    assert result.n_segments < config.max_segments  # 【検証項目】: 安全上限まで走らない 🔵
    assert max(result.evidence_by_k) <= result.n_segments + 1  # 探索 k が採択 k+1 で止まる 🔵


def test_partitions_saved_as_hypotheses_and_browsable_by_k():
    # 【テスト目的】: 評価した各 k の分割が Hypothesis として保存され evidence_by_k で閲覧できることを確認
    # 【テスト内容】: 2 区間系列で partitions / evidence_by_k の内容と id 命名・frame_range を検証
    # 【期待される動作】: partitions>=2、id は "seg-k" 前置、frame_range=全区間、evidence_by_k は float
    # 🔵 信頼性レベル: acceptance-criteria.md TC-206-04 / architecture.md D6 / design-interview D-Q6 に依拠

    # 【テストデータ準備】: k=1,2 が評価される 2 区間系列 (代替分割の閲覧検証)
    series = _two_regime_series(true_boundary=6, n_frames=12)

    # 【実際の処理実行】: 各 k の分割を Hypothesis 化して保持
    result = segment_series(_backend(), series, INITIAL)

    # 【結果検証】: 分割仮説の保存・命名規約・全区間 frame_range・evidence 網羅性
    assert len(result.partitions) >= 2  # 【検証項目】: 少なくとも k=1, k=2 を保存 🔵
    for part in result.partitions:
        assert isinstance(part, Hypothesis)  # 【検証項目】: 各分割は Hypothesis 🔵
        assert part.id.startswith("seg-k")  # 【検証項目】: id は "seg-k{K}-" 前置 🔵
        assert part.frame_range == (0, series.n_frames - 1)  # 【検証項目】: frame_range=全区間 🔵
    assert all(isinstance(v, float) for v in result.evidence_by_k.values())  # 合計コストは float 🔵
    # 【検証項目】: 採択 n_segments に対応する Hypothesis が partitions に存在 🔵
    assert any(p.id.startswith(f"seg-k{result.n_segments}-") for p in result.partitions)


def test_fine_scan_improves_boundary_over_coarse():
    # 【テスト目的】: 採択境界を ±coarse_step で細密スキャンし粗グリッド格子点より真値へ近づくことを確認
    # 【テスト内容】: 真値 T=8 (粗グリッド 5 の倍数から 2 以上離す) の系列で細密化後の境界誤差を検証
    # 【期待される動作】: boundaries[0] が真値の ±1 に入る (粗グリッド格子だけでは到達不能な精度)
    # 🟡 信頼性レベル: acceptance-criteria.md TC-206-05 前半 / architecture.md D5 に依拠

    # 【テストデータ準備】: T=8 は粗グリッド {5,10} のどの点からも 2 以上離れる (細密化が必須)
    T = 8
    series = _two_regime_series(true_boundary=T, n_frames=12)
    config = SegmentationConfig(coarse_step=5)
    # 【前提確認】: 粗グリッド (5 の倍数) には T の ±1 に入る候補が存在しない (細密化なしでは到達不能)
    nearest_coarse = round(T / config.coarse_step) * config.coarse_step
    assert abs(nearest_coarse - T) >= 2

    # 【実際の処理実行】: 粗スキャン採択境界を ±G 細密再配置
    result = segment_series(_backend(), series, INITIAL, config=config)

    # 【結果検証】: 細密化が粗グリッド格子より真値に近い境界を得ている
    assert result.n_segments == 2  # 【検証項目】: k=2 採択 🔵
    assert abs(result.boundaries[0] - T) <= 1  # 【検証項目】: 細密化で ±1 (粗のみでは不可能) 🟡


def test_interval_cost_memoized_reduces_backend_calls():
    # 【テスト目的】: 区間コストのメモ化で backend.refine の再評価が抑制されることを確認
    # 【テスト内容】: 呼び出し記録 Spy で総 refine 回数と全フレーム被覆・決定論性を検証
    # 【期待される動作】: 全フレームが評価され、総 refine 回数がメモ化予算内・2 回実行で同数
    # 🟡 信頼性レベル: acceptance-criteria.md TC-206-05 後半 / design-interview D-Q5 (メモ化) に依拠

    # 【テストデータ準備】: 2 区間系列 + 呼び出し記録 Spy を 2 回実行
    series = _two_regime_series(true_boundary=6, n_frames=12)
    spy1 = CountingSpyBackend(series)
    spy2 = CountingSpyBackend(series)
    segment_series(spy1, series, INITIAL)
    segment_series(spy2, series, INITIAL)

    # 【結果検証】: 全フレーム被覆・メモ化予算・決定論的な呼び出し数
    n = series.n_frames
    assert set(f for f in spy1.frames if f is not None) == set(range(n))  # 全フレーム評価 🟡
    # 【検証項目】: メモ化により再評価が抑制され、素朴な全候補×フレーム再計算の上限を大きく下回る 🟡
    assert 0 < len(spy1.frames) <= 4 * n * n
    assert len(spy1.frames) == len(spy2.frames)  # 【検証項目】: 決定論 (2 回実行で同数) 🔵


def test_segmentation_deterministic_bit_identical():
    # 【テスト目的】: 同一入力で 2 回実行すると分割結果 (ledger 以外) がビット同一になることを確認
    # 【テスト内容】: 2 区間系列を独立に 2 回分割し boundaries/n_segments/evidence_by_k/partitions の一致を確認
    # 【期待される動作】: 乱数/IO/集合反復順に依存せず全フィールドが一致
    # 🔵 信頼性レベル: acceptance-criteria.md TC-206-07 / CLAUDE.md NFR-102 に依拠

    # 【テストデータ準備】: 同一の 2 区間系列で新規 backend を用い 2 回分割
    series = _two_regime_series(true_boundary=6, n_frames=12)
    r1 = segment_series(_backend(), series, INITIAL)
    r2 = segment_series(_backend(), series, INITIAL)

    # 【結果検証】: ledger インスタンス以外の全フィールドがビット同一 (決定論)
    assert r1.boundaries == r2.boundaries  # 【検証項目】: 境界が一致 🔵
    assert r1.n_segments == r2.n_segments  # 【検証項目】: 区間数が一致 🔵
    assert r1.evidence_by_k == r2.evidence_by_k  # 【検証項目】: k 別合計コストが一致 🔵
    assert r1.partitions == r2.partitions  # 【検証項目】: 分割仮説が一致 (Hypothesis の ==) 🔵


def test_ledger_records_boundaries_and_verify_true():
    # 【テスト目的】: 分割操作が ledger に追記され実行後も verify() が True であることを確認
    # 【テスト内容】: Ledger を渡した分割後にエントリ非空・kind 前置・ハッシュチェーン整合を確認
    # 【期待される動作】: 渡した ledger が返り、entries 非空、全 kind が "segmentation." 前置、verify()==True
    # 🔵 信頼性レベル: CLAUDE.md P2/NFR-105 / interfaces.py L309 に依拠

    # 【テストデータ準備】: Ledger を渡した 2 区間系列の分割
    ledger = Ledger()
    series = _two_regime_series(true_boundary=6, n_frames=12)
    result = segment_series(_backend(), series, INITIAL, ledger=ledger)

    # 【結果検証】: 追記専用・kind 前置・ハッシュチェーン整合
    assert result.ledger is ledger  # 【検証項目】: 渡した ledger を返す 🔵
    assert len(ledger.entries) > 0  # 【検証項目】: 分割操作が記録される 🔵
    assert any(e.kind.startswith("segmentation.") for e in ledger.entries)  # 分割系 kind 🔵
    assert all(e.kind.startswith("segmentation.") for e in ledger.entries)  # kind は分割系のみ 🟡
    assert ledger.verify() is True  # 【検証項目】: 記録後もチェーン整合 🔵


def test_fixed_phases_scale_only_free_in_interval_refine():
    # 【テスト目的】: fixed_phases を渡すと区間逐次 refine に固定相が連結され scale のみ解放されることを確認
    # 【テスト内容】: FreeParamsSpy で固定相 (Be) を含む refine の free_params を観測
    # 【期待される動作】: 固定相 index の free_params は scale のみ・lattice を含まない
    # 🔵 信頼性レベル: FR-312 / note.md §3.6 / cell_phases.py fixed_free_suffixes に依拠

    # 【テストデータ準備】: 2 区間系列 + Be 固定相 + free_params 記録 Spy
    series = _two_regime_series(true_boundary=6, n_frames=12)
    be = CELL_PHASE_PRESETS["Be"]
    spy = FreeParamsSpyBackend()

    # 【実際の処理実行】: 固定相込みの分割 (固定相は構造固定・scale のみ解放)
    result = segment_series(spy, series, INITIAL, fixed_phases=(be,))

    # 【結果検証】: 固定相が区間 refine に常駐し格子を解放しないこと
    assert result.n_segments >= 1  # 【検証項目】: 固定相込みでも分割が完走 🔵
    be_calls = [c for c in spy.calls if "Be" in c["phase_refs"]]
    assert be_calls  # 【検証項目】: 固定相 Be が区間 refine に常駐する 🔵
    for c in be_calls:
        be_idx = c["phase_refs"].index("Be")
        assert f"phase{be_idx}.scale" in c["free_params"]  # 固定相 scale は解放 🔵
        assert not any(
            name.startswith(f"phase{be_idx}.lattice") for name in c["free_params"]
        )  # 【検証項目】: 固定相の格子は解放しない (scale のみ) 🔵


# ===========================================================================
# 2. 異常系テストケース
# ===========================================================================


def test_all_frames_nonfinite_degrades_to_k1_with_warning():
    # 【テスト目的】: 全フレーム非有限 (backend 全滅) で例外を投げず分割なし + 警告へ縮退することを確認
    # 【テスト内容】: 常に chi2=inf を返す FailAllBackend で分割を実行
    # 【期待される動作】: 例外なし、n_segments==1、boundaries==()、warnings 非空 (inf を採択値に据えない)
    # 🟡 信頼性レベル: CLAUDE.md 不変条件 (非有限漏洩防止) / note.md §6-7 に依拠

    # 【テストデータ準備】: 全フレーム収束失敗を注入する FailAllBackend + 2 区間系列
    series = _two_regime_series(true_boundary=6, n_frames=12)

    # 【実際の処理実行】: 全滅を例外化せず縮退結果を返す
    result = segment_series(FailAllBackend(), series, INITIAL)

    # 【結果検証】: 非有限の縮退 (分割なし + 警告)
    assert result.n_segments == 1  # 【検証項目】: 分割不能で k=1 へ縮退 🟡
    assert result.boundaries == ()  # 【検証項目】: 境界を採択しない 🟡
    assert result.warnings != ()  # 【検証項目】: 非有限縮退の理由を warning に残す 🟡


def test_partial_frame_failure_excluded_from_interval_bic():
    # 【テスト目的】: 一部フレームの失敗 (chi2=inf) を Σbic に混ぜず分割を完走することを確認
    # 【テスト内容】: 特定フレームのみ inf を返す FrameFailBackend で分割を実行
    # 【期待される動作】: 例外なし、分割完走、warnings に除外を記録 (非有限を下流に漏らさない)
    # 🟡 信頼性レベル: note.md §3.1/§6-7 / discrimination.py 先例 (n_finite 管理) に依拠

    # 【テストデータ準備】: 中間フレーム 1 本のみ収束失敗を注入 + 2 区間系列
    series = _two_regime_series(true_boundary=6, n_frames=12)
    backend = FrameFailBackend(series, fail_frames={7})

    # 【実際の処理実行】: 局所失敗を有限成分のみで処理し分割継続
    result = segment_series(backend, series, INITIAL)

    # 【結果検証】: 完走 + 非有限除外の記録
    assert result.n_segments >= 1  # 【検証項目】: 局所失敗でも分割が完走 🟡
    assert result.warnings != ()  # 【検証項目】: 非有限フレーム除外を warning に記録 🟡


# ===========================================================================
# 3. 境界値テストケース
# ===========================================================================


def test_single_frame_series_returns_k1_only():
    # 【テスト目的】: n_frames<2 (1 フレーム) で分割不能となり k=1 のみ返すことを確認
    # 【テスト内容】: 1 フレームの系列に segment_series を適用
    # 【期待される動作】: 例外なし、n_segments==1、boundaries==()、warnings に分割不能理由
    # 🟡 信頼性レベル: note.md §6-7 (縮退) に依拠

    # 【テストデータ準備】: 1 フレームの一様系列 (分割の最小縮退)
    series = _uniform_series(n_frames=1)

    # 【実際の処理実行】: 境界を挿入できない最小フレーム数
    result = segment_series(_backend(), series, INITIAL)

    # 【結果検証】: 最小フレーム数での安全動作
    assert result.n_segments == 1  # 【検証項目】: 分割不能で k=1 🟡
    assert result.boundaries == ()  # 【検証項目】: 境界なし 🟡
    assert result.warnings != ()  # 【検証項目】: 分割不能理由を warning に残す 🟡


def test_coarse_step_ge_nframes_yields_k1():
    # 【テスト目的】: coarse_step >= n_frames で挿入候補が空となり k=1 で確定することを確認
    # 【テスト内容】: n_frames=4 の系列 + coarse_step=5 で分割を実行
    # 【期待される動作】: 例外なし、n_segments==1、boundaries==() (候補ゼロで貪欲ループ即終了)
    # 🟡 信頼性レベル: note.md §6-7 (縮退) / interfaces.py L296 に依拠

    # 【テストデータ準備】: フレーム数 4 < 粗グリッド刻み 5 (有効候補が生成されない)
    series = _uniform_series(n_frames=4)
    config = SegmentationConfig(coarse_step=5)

    # 【実際の処理実行】: 挿入候補が空でも通常の k=1 採択経路へ縮退
    result = segment_series(_backend(), series, INITIAL, config=config)

    # 【結果検証】: グリッド設定境界での堅牢性
    assert result.n_segments == 1  # 【検証項目】: 候補ゼロで k=1 確定 🟡
    assert result.boundaries == ()  # 【検証項目】: 境界なし 🟡


def test_reaches_max_segments_upper_bound():
    # 【テスト目的】: 改善が続く病的系列でも max_segments を超えず強制停止することを確認
    # 【テスト内容】: 段差の多い鋸歯系列 + max_segments=3, improvement_threshold=0.0 で分割
    # 【期待される動作】: n_segments <= max_segments、探索 k も max_segments を超えない
    # 🟡 信頼性レベル: interfaces.py L297 (max_segments) / architecture.md D5 に依拠

    # 【テストデータ準備】: 4 区間の鋸歯系列 (真の区間数 > 上限) + 閾値 0 で打ち切りが効かない config
    series = _sawtooth_series(n_regimes=4, frames_per_regime=4)
    config = SegmentationConfig(max_segments=3, improvement_threshold=0.0)

    # 【実際の処理実行】: 改善が続いても安全上限で必ず停止
    result = segment_series(_backend(), series, INITIAL, config=config)

    # 【結果検証】: 安全上限の遵守 (無限ループしない)
    assert result.n_segments <= config.max_segments  # 【検証項目】: 上限で停止 🟡
    assert max(result.evidence_by_k) <= config.max_segments  # 探索 k も上限内 🟡


def test_ledger_none_generates_internal_and_result_invariant():
    # 【テスト目的】: ledger=None でも例外なく動作し内部生成 ledger を返し数値結果が不変であることを確認
    # 【テスト内容】: ledger=None と ledger=Ledger() の 2 実行で boundaries 等の一致を確認
    # 【期待される動作】: result.ledger は非 None・verify()==True、分割数値は ledger 明示時とビット同一
    # 🔵 信頼性レベル: interfaces.py L320 / note.md §3.9 に依拠

    # 【テストデータ準備】: 同一 2 区間系列を None 版と提供版で実行
    series = _two_regime_series(true_boundary=6, n_frames=12)
    r_none = segment_series(_backend(), series, INITIAL, ledger=None)
    r_prov = segment_series(_backend(), series, INITIAL, ledger=Ledger())

    # 【結果検証】: ledger 依存注入の省略安全性・数値結果の不変性
    assert r_none.ledger is not None  # 【検証項目】: None なら内部で新規 Ledger 生成 🔵
    assert r_none.ledger.verify() is True  # 【検証項目】: 内部生成 ledger もチェーン整合 🔵
    assert r_none.boundaries == r_prov.boundaries  # 【検証項目】: 境界が ledger 有無で不変 🔵
    assert r_none.n_segments == r_prov.n_segments  # 【検証項目】: 区間数が不変 🔵
    assert r_none.evidence_by_k == r_prov.evidence_by_k  # 【検証項目】: 合計コストが不変 🔵


def test_config_and_result_are_frozen():
    # 【テスト目的】: SegmentationConfig / SegmentationResult が frozen で既定値が契約どおりであることを確認
    # 【テスト内容】: config の既定値検証 + config/result 各インスタンスへの再代入で FrozenInstanceError を確認
    # 【期待される動作】: 既定値が interfaces.py L292-310 と一致、属性代入で FrozenInstanceError
    # 🔵 信頼性レベル: interfaces.py L292/L301 / CLAUDE.md コーディング規約 (frozen dataclass) に依拠

    # 【テストデータ準備】: 既定 config と最小構成の result を構築
    config = SegmentationConfig()
    assert config.penalty_beta == 5.0  # 【検証項目】: β の既定 🔵
    assert config.improvement_threshold == 10.0  # 【検証項目】: 改善打ち切り閾値の既定 🔵
    assert config.coarse_step == 5  # 【検証項目】: 粗グリッド刻みの既定 🔵
    assert config.max_segments == 6  # 【検証項目】: 安全上限の既定 🔵
    assert config.seq_max_cycles == 10  # 【検証項目】: 区間 refine サイクルの既定 🔵

    result = SegmentationResult(
        boundaries=(),
        n_segments=1,
        evidence_by_k={1: 0.0},
        partitions=(),
        ledger=Ledger(),
    )

    # 【結果検証】: frozen=True (再代入拒否)
    with pytest.raises(FrozenInstanceError):
        config.penalty_beta = 1.0  # 【検証項目】: SegmentationConfig は不変 🔵
    with pytest.raises(FrozenInstanceError):
        result.n_segments = 2  # 【検証項目】: SegmentationResult は不変 🔵
    assert result.warnings == ()  # 【検証項目】: warnings の既定は空タプル 🔵
    assert isinstance(dataclasses.fields(SegmentationResult), tuple)  # frozen dataclass である 🔵


def test_improvement_exactly_at_threshold_boundary():
    # 【テスト目的】: 改善量が閾値ちょうどのとき当該 k を採択する (打ち切りは厳密に閾値未満) ことを確認
    # 【テスト内容】: 実際の改善量 Δ を学習し improvement_threshold=Δ と Δ+ε で採否が切り替わることを検証
    # 【期待される動作】: 改善量==閾値 → k=2 採択、改善量<閾値 (閾値=Δ+ε) → k=1 打ち切り。2 回実行で同一
    # 🟡 信頼性レベル: requirements REQ-013 (改善が閾値未満で打ち切り) / note.md §6-3 (< 規約凍結) に依拠

    # 【テストデータ準備】: 2 区間系列で k=1→2 の実際の改善量 Δ を permissive 実行から学習する
    series = _two_regime_series(true_boundary=6, n_frames=12)
    learn = segment_series(
        _backend(), series, INITIAL, config=SegmentationConfig(improvement_threshold=0.0)
    )
    delta = learn.evidence_by_k[1] - learn.evidence_by_k[2]
    assert delta > 0  # 【前提確認】: k=2 が k=1 を改善する (Δ>0) 🟡

    # 【実際の処理実行】: 閾値をちょうど Δ / Δ より僅かに大きく設定して採否を比較
    at = segment_series(
        _backend(), series, INITIAL, config=SegmentationConfig(improvement_threshold=delta)
    )
    above = segment_series(
        _backend(), series, INITIAL, config=SegmentationConfig(improvement_threshold=delta + 1.0)
    )

    # 【結果検証】: 閾値ちょうどは採択・閾値超は打ち切り (境界の内外で採否が反転)
    assert at.n_segments == 2  # 【検証項目】: 改善量==閾値は当該 k を採択 (厳密 < で打ち切り) 🟡
    assert above.n_segments == 1  # 【検証項目】: 改善量<閾値は直前 k で打ち切り 🟡
