"""TASK-0032 operando/discrimination — 固溶体 vs 二相判別 (FR-313 / 設計 D4) の失敗テスト (TDD Red)。

対象実装 (**未実装**): ``src/tsumugin/operando/discrimination.py`` の
``DiscriminationConfig`` / ``DiscriminationResult`` / ``discriminate_interval``。

契約は ``docs/design/m3-operando/interfaces.py`` L252-284 に確定。テストケース定義
(operando-discrimination-testcases.md) の 17 件 (正常系 8 / 異常系 4 / 境界値 5) に 1:1 対応する。

テスト方針:
- 実データ検証 (TC-N01/N02/N04/N06/N07/N08/BV03/BV05) は ``SimulatedBackend`` の乱数なし合成系列
  (固溶体 = 単相格子の連続変化 / 二相 = 端成分 2 相の分率漸移) を用いフルパイプラインを回す。
- 呼び出し観測 (TC-N03/N05/E04) は ``RecordingSpyBackend`` (SimulatedBackend へ委譲しつつ
  free_params / max_cycles / 相数を記録)。
- 判別分岐制御 (TC-E01/E02/E03/BV01/BV02) は ``ControlledFakeBackend`` (相数=仮説種別で chi2/rwp を
  固定返しし、僅差 / 両仮説高 R / マルチスタート全滅を決定論注入)。
- いずれも ``RefinementBackend`` Protocol (name + refine) のみ満たし GSAS-II 非依存 (gsas マーカー不要)。

対象モジュール未実装のため collection 時に import が失敗し、本ファイルの全テストがエラー(=失敗)になる想定 (Red)。
"""

from __future__ import annotations

import math
import time
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance
from tsumugin.multistart import MultistartConfig
from tsumugin.multistart.engine import MultistartResult
from tsumugin.operando.cell_phases import CELL_PHASE_PRESETS
from tsumugin.selection.review_queue import ReviewQueue
from tsumugin.sequential.series import FrameSeries
from tsumugin.store.ledger import Ledger

# 未実装のため、この import が collection 時に失敗し全テストがエラー(=失敗)になる想定 (Red)。
from tsumugin.operando.discrimination import (  # noqa: E402
    DiscriminationConfig,
    DiscriminationResult,
    discriminate_interval,
)

# ---------------------------------------------------------------------------
# 共通テストデータ・ヘルパ (モジュールレベルで一度だけ構築し不変共有する)
# ---------------------------------------------------------------------------

# 【観測グリッド】: <30 秒 smoke を意識した小グリッド (先例 0.02 刻みより粗い 0.05 刻み)。
#   固定相 Al ((211)≈55.5°) まで捉えるため上端 60° まで取る。🟡 note.md §5
GRID = np.arange(15.0, 60.0, 0.05)

# 【活物質の初期相】: 立方格子 a=b=c=5.0 の単相 (仮説 A の単相起点)。🔵 requirements §2.2
PHASE_A0 = PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0), scale=1.0)

# 【高速 config】: verdict 判定はマルチスタート本数に依存しないため n_starts=2 で実行時間を抑える。🟡
CONFIG_FAST = DiscriminationConfig(multistart=MultistartConfig(n_starts=2))


def _phase(a: float, ref: str = "A", scale: float = 1.0, wt: float | None = None) -> PhaseInstance:
    """立方格子 (a=b=c) の相インスタンスを組む (a を変えると全反射のピーク位置が動く)。"""
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale, wt_frac=wt)


def _solid_solution_series(n_frames: int = 8, a0: float = 5.0, a1: float = 5.10) -> FrameSeries:
    """単相の格子 a=b=c をフレームで線形変化させた合成系列 (格子連続変化 = 固溶体)。🔵 note.md §5"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    rows = [
        backend.simulate([_phase(a0 + (a1 - a0) * i / (n_frames - 1), "A")], GRID)
        for i in range(n_frames)
    ]
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


def _two_phase_series(n_frames: int = 8, a_alpha: float = 5.0, a_beta: float = 5.06) -> FrameSeries:
    """端成分 2 相 (格子固定・別位置ピーク) の scale を α:1→0 / β:0→1 で漸移 (二相反応)。🔵 note.md §5

    端点は純端成分 (frame0=α のみ / frame-1=β のみ) にし、仮説 A の warm-start 逐次が両端の格子を
    発見できるようにする (端成分分離幅は SimulatedBackend の LM 追従域内へ = a_beta≈5.06)。
    """
    backend = SimulatedBackend(peak_fwhm=0.2)
    rows = []
    for i in range(n_frames):
        t = i / (n_frames - 1)
        phases = []
        if 1.0 - t > 0.0:
            phases.append(_phase(a_alpha, "alpha", scale=1.0 - t))
        if t > 0.0:
            phases.append(_phase(a_beta, "beta", scale=t))
        rows.append(backend.simulate(phases, GRID))
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


def _solid_solution_with_al_series(n_frames: int = 8, a0: float = 5.0, a1: float = 5.10) -> FrameSeries:
    """固溶体の活物質ピークに Al 固定相ピークを重畳した合成系列 (TC-N06 用)。🔵"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    al = CELL_PHASE_PRESETS["Al"].phase.with_updates(scale=0.7)
    rows = [
        backend.simulate([_phase(a0 + (a1 - a0) * i / (n_frames - 1), "A"), al], GRID)
        for i in range(n_frames)
    ]
    return FrameSeries(two_theta=GRID, intensities=np.asarray(rows, dtype=float))


# 【フェイク用小グリッド】: ControlledFakeBackend は intensity.size (=n_obs) しか参照しないため小さくてよい。
_FAKE_GRID = np.linspace(10.0, 40.0, 64)


def _fake_series(n_frames: int = 8) -> FrameSeries:
    """ControlledFakeBackend 用のダミー系列 (強度内容は無関係、n_obs 用の形状だけ持つ)。"""
    return FrameSeries(
        two_theta=_FAKE_GRID, intensities=np.ones((n_frames, _FAKE_GRID.size), dtype=float)
    )


# ---------------------------------------------------------------------------
# テストダブル (呼び出し記録スパイ / 判別分岐を制御する決定論フェイク)
# ---------------------------------------------------------------------------


class RecordingSpyBackend:
    """SimulatedBackend へ委譲しつつ refine の (free_params / max_cycles / 相数 / 相名) を記録する。

    マルチスタート呼び出しは ``max_cycles == ms_max_cycles`` (既定 15) で、逐次 direct refine は
    ``max_cycles == seq_max_cycles`` (既定 10) で識別できる。仮説 A は単相 (n_phases==1)、
    仮説 B は端成分 2 相 (n_phases==2) で識別できる (固定相なしの場合)。
    先例: tests/test_sequential_engine.py の PhaseRecordingSpyBackend。
    """

    name = "spy"

    def __init__(self, *, peak_fwhm: float = 0.2) -> None:
        self._sim = SimulatedBackend(peak_fwhm=peak_fwhm)
        self.calls: list[dict] = []

    def simulate(self, phases, two_theta):
        return self._sim.simulate(phases, two_theta)

    def peak_positions(self, phase, two_theta):
        return self._sim.peak_positions(phase, two_theta)

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        self.calls.append(
            {
                "free_params": frozenset(model.free_params),
                "max_cycles": max_cycles,
                "n_phases": len(model.phases),
                "phase_refs": tuple(p.phase_ref for p in model.phases),
            }
        )
        return self._sim.refine(model, max_cycles=max_cycles)


class ControlledFakeBackend:
    """相数 (単相=仮説A / 2相=仮説B) をキーに chi2/rwp を固定返しする決定論スタブ。

    - close モード: A/B とも同一 chi2 → Σbic_A−Σbic_B が 0 (|ΔBIC|<close_threshold) → 僅差 (TC-E01)。
    - high_r モード: 全 refine に rwp=50.0 (>high_r_threshold) を返す (両仮説高 R / TC-E02)。
      chi2 は A 優位に振る (通常なら decisive) が、高 R でエスカレーションが優先されることを検証する。
    - diverge_multistart モード: マルチスタート呼び出し (max_cycles==ms_max_cycles) にのみ chi2=inf を
      返し逐次は正常値 (全滅の縮退 / TC-E03)。
    - fail_single モード: 単相 (仮説 A / n_phases<=1) の全 refine に chi2=inf/rwp=inf を返し、2 相 (仮説 B)
      は正常値。片仮説の backend 全失敗で有限フレーム数が食い違う縮退を注入する (TC-E05 / 比較可能性ガード)。
    - threshold モード: chi2_single/chi2_two を陽に与え ΔBIC=chi2_single−chi2_two を厳密制御 (TC-BV01)。

    n_obs=model.intensity.size / n_params=0 (BIC ペナルティを 0 に固定し ΔBIC=chi2 差へ帰着) を返し、
    BIC 算出を決定論化する。RefinementBackend Protocol (name + refine) のみ満たす。
    """

    name = "controlled"

    def __init__(
        self,
        *,
        mode: str,
        chi2_single: float = 100.0,
        chi2_two: float = 100.0,
        rwp: float = 1.0,
        ms_max_cycles: int = 15,
    ) -> None:
        self.mode = mode
        self.chi2_single = float(chi2_single)
        self.chi2_two = float(chi2_two)
        self.rwp = float(rwp)
        self.ms_max_cycles = int(ms_max_cycles)
        self.calls: list[dict] = []

    def simulate(self, phases, two_theta):
        # 【防御実装】: 判別は refine のみ使う契約だが、万一 simulate されても落ちないよう零を返す。
        return np.zeros_like(np.asarray(two_theta, dtype=float))

    def peak_positions(self, phase, two_theta):
        return []

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        n_phases = len(model.phases)
        n_obs = int(np.asarray(model.intensity).size)
        is_multistart = max_cycles == self.ms_max_cycles
        self.calls.append({"n_phases": n_phases, "max_cycles": max_cycles})

        # 【仮説種別で chi2 を分岐】: 単相 (<=1) = 仮説A / 2 相以上 = 仮説B。
        chi2 = self.chi2_single if n_phases <= 1 else self.chi2_two
        rwp = self.rwp
        if self.mode == "high_r":
            rwp = 50.0  # 両仮説高 R (>30.0) を強制
        if self.mode == "diverge_multistart" and is_multistart:
            chi2 = float("inf")  # マルチスタート start をすべて発散させる
            rwp = float("inf")
        if self.mode == "fail_single" and n_phases <= 1:
            chi2 = float("inf")  # 仮説 A (単相) の逐次・マルチスタートを全失敗させる
            rwp = float("inf")

        return RefinementResult(
            phases=model.phases,
            chi2=chi2,
            rwp=rwp,
            n_obs=n_obs,
            n_params=0,
            converged=math.isfinite(chi2),
            n_cycles=1,
            free_params=frozenset(model.free_params),
        )


# ===========================================================================
# 1. 正常系テストケース
# ===========================================================================


def test_solid_solution_series_yields_solid_solution_verdict():
    # 【テスト目的】: 格子連続変化の合成系列で仮説 A が優位となり "solid_solution" 判別になることを確認
    # 【テスト内容】: SimulatedBackend 合成の固溶体系列に discriminate_interval を適用するフルパイプライン
    # 【期待される動作】: verdict=="solid_solution"、delta_evidence <= -close_threshold、escalations==()
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-01 / 設計 D4 / REQ-010 に直接依拠

    # 【テストデータ準備】: 単相の格子を 5.00→5.10 へ線形変化させた 8 フレーム合成系列 (乱数なし)
    series = _solid_solution_series(n_frames=8)
    backend = SimulatedBackend(peak_fwhm=0.2)

    # 【実際の処理実行】: 仮説A 逐次 refine → 仮説B 端成分固定 refine → 端点マルチスタート → ΔBIC 判定
    result = discriminate_interval(backend, series, (0, 7), (PHASE_A0,), config=CONFIG_FAST)

    # 【結果検証】: 固溶体判別・ΔBIC 符号規約・非エスカレーション
    assert result.verdict == "solid_solution"  # 【確認内容】: 仮説 A 優位の verdict 🔵
    assert result.delta_evidence <= -CONFIG_FAST.close_threshold  # ΔBIC=Σbic_A−Σbic_B ≤ −閾値 🔵
    assert result.escalations == ()  # 【確認内容】: 明瞭な判別ではエスカレーションなし 🔵


def test_two_phase_series_yields_two_phase_verdict():
    # 【テスト目的】: 端成分分率変化の合成系列で仮説 B が優位となり "two_phase" 判別になることを確認
    # 【テスト内容】: SimulatedBackend 合成の二相系列 (α:1→0 / β:0→1) に discriminate_interval を適用
    # 【期待される動作】: verdict=="two_phase"、delta_evidence >= close_threshold、B は端成分 2 相
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-02 / 設計 D4 / REQ-010 に直接依拠

    # 【テストデータ準備】: 端成分 α(a=5.0) / β(a=5.06) の scale を漸移させた 8 フレーム合成系列
    series = _two_phase_series(n_frames=8)
    backend = SimulatedBackend(peak_fwhm=0.2)

    # 【実際の処理実行】: 仮説A(単相)は中間フレームで不適合、仮説B(端成分固定 2 相)が適合
    result = discriminate_interval(backend, series, (0, 7), (PHASE_A0,), config=CONFIG_FAST)

    # 【結果検証】: 二相判別・ΔBIC 符号規約・端成分 2 相構成
    assert result.verdict == "two_phase"  # 【確認内容】: 仮説 B 優位の verdict 🔵
    assert result.delta_evidence >= CONFIG_FAST.close_threshold  # ΔBIC ≥ +閾値 (B 優位) 🔵
    assert len(result.hypothesis_two_phase.phases) >= 2  # 【確認内容】: 仮説 B は端成分 2 相以上 🔵


def test_multistart_is_mandatory_at_interval_endpoints():
    # 【テスト目的】: 判別 1 回で両仮説の区間端点フレームにマルチスタートが必須適用されることを確認
    # 【テスト内容】: RecordingSpyBackend で refine 呼び出しを観測し max_cycles==15 の本数を数える
    # 【期待される動作】: マルチスタート分 = n_starts × 端点2 × 仮説2 本、両 MultistartResult.n_starts==n
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-03 / REQ-004 / FR-233 / D4「区間端点でマルチスタート必須」に依拠

    # 【テストデータ準備】: 固溶体系列 + n_starts=4 (呼び出し本数を数えやすい小 N)
    n_starts = 4
    config = DiscriminationConfig(multistart=MultistartConfig(n_starts=n_starts))
    spy = RecordingSpyBackend()
    series = _solid_solution_series(n_frames=8)

    # 【実際の処理実行】: 判別フルパイプライン (端点 start/end × 両仮説でマルチスタート適用)
    result = discriminate_interval(spy, series, (0, 7), (PHASE_A0,), config=config)

    # 【結果検証】: マルチスタート呼び出し本数 (max_cycles==ms_max_cycles=15) と n_starts 伝播
    ms_calls = [c for c in spy.calls if c["max_cycles"] == 15]
    assert len(ms_calls) == n_starts * 2 * 2  # 端点 2 × 仮説 2 × n_starts=4 → 16 本 🔵
    assert result.multistart_single.n_starts == n_starts  # 仮説 A 端点マルチスタート本数 🔵
    assert result.multistart_two_phase.n_starts == n_starts  # 仮説 B 端点マルチスタート本数 🔵


def test_both_hypotheses_carry_metrics_multistart():
    # 【テスト目的】: 両仮説の metrics.multistart に {"n","n_basins","n_diverged"} が付与されることを確認
    # 【テスト内容】: 既定 n_starts=8 で判別し hypothesis_single/two_phase.metrics.multistart を検証
    # 【期待される動作】: 非 None・キー 3 つ・MultistartResult (basins 数 / n_diverged) と整合
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-03 後半 / interfaces.py L266 / REQ-006 に依拠

    # 【テストデータ準備】: 固溶体系列 + 既定 config (n_starts=8)
    series = _solid_solution_series(n_frames=8)
    result = discriminate_interval(SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,))

    # 【結果検証】: 仮説 A / B の metrics.multistart 付与と MultistartResult との整合
    for hyp, ms in (
        (result.hypothesis_single, result.multistart_single),
        (result.hypothesis_two_phase, result.multistart_two_phase),
    ):
        assert hyp.metrics is not None  # 【確認内容】: metrics が付与される 🔵
        record = hyp.metrics.multistart
        assert record is not None  # 【確認内容】: multistart 記録が非 None (単一 basin でも付与) 🔵
        assert set(record) >= {"n", "n_basins", "n_diverged"}  # キー 3 つの存在 🔵
        assert record["n"] == 8  # 【確認内容】: n_starts と一致 🔵
        assert record["n_basins"] == len(ms.basins)  # basin 数の整合 🔵
        assert record["n_diverged"] == ms.n_diverged  # 発散数の整合 🔵


def test_two_phase_hypothesis_keeps_lattice_fixed():
    # 【テスト目的】: 仮説 B の逐次 refine とマルチスタートで格子パラメータが解放されないことを確認 (D4)
    # 【テスト内容】: RecordingSpyBackend で 2 相 (仮説B) 呼び出しの free_params に lattice が無いことを観測
    # 【期待される動作】: n_phases==2 の全 refine 呼び出しで free_params に "lattice" を含まない
    # 🟡 信頼性レベル: 設計 D4 (L73-74) / dataflow (L66)「格子固定、scale/wt のみ解放」に依拠

    # 【テストデータ準備】: 固溶体系列 (仮説 B も必ず構築される) + n_starts=2
    spy = RecordingSpyBackend()
    series = _solid_solution_series(n_frames=8)

    # 【実際の処理実行】: 仮説 A/B 双方の refine を観測
    discriminate_interval(spy, series, (0, 7), (PHASE_A0,), config=CONFIG_FAST)

    # 【結果検証】: 仮説 B (2 相) 呼び出しの free_params が格子を解放しないこと
    b_calls = [c for c in spy.calls if c["n_phases"] == 2]
    assert b_calls  # 【確認内容】: 仮説 B の refine 呼び出しが存在する 🔵
    for call in b_calls:
        assert all("lattice" not in name for name in call["free_params"])  # 格子は固定 🟡


def test_fixed_phase_preserved_and_does_not_disturb_verdict():
    # 【テスト目的】: fixed_phases を渡すと固定相が両仮説に常駐し、格子ビット不変・判別を乱さないことを確認
    # 【テスト内容】: Al 固定相ピークを重畳した固溶体系列に fixed_phases=(Al,) を渡して判別
    # 【期待される動作】: verdict=="solid_solution"、固定相 Al の格子が精密化後もビット不変
    # 🔵 信頼性レベル: FR-312 / REQ-009 / fixed_free_suffixes docstring (呼び側=TASK-0032) に依拠

    # 【テストデータ準備】: 活物質 (固溶体) + Al 固定相を重畳した合成系列 + fixed_phases
    series = _solid_solution_with_al_series(n_frames=8)
    al_spec = CELL_PHASE_PRESETS["Al"]

    # 【実際の処理実行】: 固定相込みの判別 (固定相は scale のみ解放・構造固定)
    result = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,),
        config=CONFIG_FAST, fixed_phases=(al_spec,),
    )

    # 【結果検証】: 固定相が判別を乱さない + 固定相格子のビット不変
    assert result.verdict == "solid_solution"  # 【確認内容】: 固定相込みでも固溶体判別 🔵
    al_phases = [p for p in result.hypothesis_single.phases if p.phase_ref == "Al"]
    assert al_phases  # 【確認内容】: 固定相が仮説 A に常駐する 🔵
    assert al_phases[0].lattice == al_spec.phase.lattice  # 固定相格子はビット不変 🔵


def test_ledger_records_and_verifies():
    # 【テスト目的】: ledger 提供時に判別の各操作が追記され、実行後も verify() が True であることを確認
    # 【テスト内容】: Ledger を渡した固溶体判別後にエントリ非空・kind 前置・ハッシュチェーン整合を確認
    # 【期待される動作】: entries 非空、判別系 "discrimination." を含む、全 kind が既知前置、verify()==True
    # 🔵 信頼性レベル: タスク本文「全操作 ledger 記録」/ NFR-105 / P2 に依拠 (kind 文字列は 🟡)

    # 【テストデータ準備】: Ledger を渡した固溶体判別
    ledger = Ledger()
    series = _solid_solution_series(n_frames=8)
    discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,),
        config=CONFIG_FAST, ledger=ledger,
    )

    # 【結果検証】: 追記専用・kind 前置・ハッシュチェーン整合
    assert len(ledger.entries) > 0  # 【確認内容】: 判別操作が記録される 🔵
    assert any(e.kind.startswith("discrimination.") for e in ledger.entries)  # 判別系 kind 🔵
    assert all(
        e.kind.startswith(("discrimination.", "multistart.")) for e in ledger.entries
    )  # 【確認内容】: kind は判別系 / マルチスタート系のみ 🟡
    assert ledger.verify() is True  # 【確認内容】: 記録後もチェーン整合 🔵


def test_discrimination_is_deterministic_bitwise_identical():
    # 【テスト目的】: 同一入力で 2 回実行すると DiscriminationResult が完全ビット同一になることを確認
    # 【テスト内容】: 固溶体系列を独立に 2 回判別し結果の == 一致を確認 (ledger/queue なし)
    # 【期待される動作】: result_a == result_b (verdict / delta / hypothesis_* / multistart_* すべて一致)
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-06 / NFR-102 / REQ-402 に直接依拠

    # 【テストデータ準備】: 同一の固溶体系列を新規 backend で 2 回判別
    series = _solid_solution_series(n_frames=8)
    result_a = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,), config=CONFIG_FAST
    )
    result_b = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,), config=CONFIG_FAST
    )

    # 【結果検証】: 乱数不使用・安定順・決定論 id 採番によるビット同一
    assert result_a == result_b  # 【確認内容】: 2 回実行でビット同一 🔵


# ===========================================================================
# 2. 異常系テストケース
# ===========================================================================


def test_close_competitor_yields_undecided_and_queue_notice_without_blocking():
    # 【テスト目的】: 僅差 (|ΔBIC|<閾値) で "undecided" + ReviewQueue 通知になり例外を投げないことを確認
    # 【テスト内容】: ControlledFakeBackend(close) で Σbic_A==Σbic_B を注入し queue 連携を検証
    # 【期待される動作】: 例外なし、verdict=="undecided"、|delta|<閾値、queue に close_competitor、escalations 非空
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-04 / REQ-101 / dataflow L72-76 に直接依拠

    # 【テストデータ準備】: 相数によらず同一 chi2 を返す close フェイク + ReviewQueue
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    queue = ReviewQueue()

    # 【実際の処理実行】: 僅差でもブロックせず結果を返す (例外化しない)
    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,), queue=queue
    )

    # 【結果検証】: undecided 判定・Queue 連携・非例外・エスカレーション
    assert result.verdict == "undecided"  # 【確認内容】: 僅差は自動確定しない 🔵
    assert abs(result.delta_evidence) < 10.0  # 【確認内容】: |ΔBIC| < close_threshold 🔵
    assert any(item.reason == "close_competitor" for item in queue.unresolved)  # Queue 通知 🔵
    assert result.escalations != ()  # 【確認内容】: 僅差を示すエスカレーション文字列 🔵


def test_both_high_r_escalates_without_verdict():
    # 【テスト目的】: 両仮説とも高 R のとき未知相フラグ + エスカレーションで判別を確定しないことを確認
    # 【テスト内容】: ControlledFakeBackend(high_r) で全 refine に rwp=50 を返し (chi2 は A 優位) 判別
    # 【期待される動作】: 例外なし、verdict=="undecided"、escalations 非空、queue に all_high_r/unknown_phase
    # 🔵 信頼性レベル: 受け入れ基準 TC-204-05 / EDGE-005 / dataflow L115 に直接依拠

    # 【テストデータ準備】: rwp=50 (>30) を全返しし、chi2 は本来 A 優位に振った high_r フェイク + Queue
    backend = ControlledFakeBackend(mode="high_r", chi2_single=10.0, chi2_two=1000.0)
    queue = ReviewQueue()

    # 【実際の処理実行】: 不適合仮説同士の比較で verdict を出さずエスカレーションへ縮退
    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,), queue=queue
    )

    # 【結果検証】: 判別を確定しない (undecided) + エスカレーション + Queue 通知
    assert result.verdict == "undecided"  # 【確認内容】: 優位側を宣言しない (判別なし) 🔵
    assert result.escalations != ()  # 【確認内容】: 高 R/未知相を示すエスカレーション 🔵
    assert any(
        item.reason in ("all_high_r", "unknown_phase") for item in queue.items
    )  # 【確認内容】: 高 R の Queue 通知 🔵


def test_all_multistart_diverged_degrades_with_warning():
    # 【テスト目的】: 端点マルチスタート全 start 発散でも判別がクラッシュせず警告付き継続することを確認
    # 【テスト内容】: ControlledFakeBackend(diverge_multistart) で max_cycles==15 のみ chi2=inf を注入
    # 【期待される動作】: 例外なし、multistart_single.basins==()、warnings 非空、逐次 Σbic から verdict 決定
    # 🟡 信頼性レベル: REQ-102 / EDGE-002 / dataflow L114 に依拠 (warnings 伝播粒度は妥当推測)

    # 【テストデータ準備】: 逐次は decisive A (chi2 10 vs 1000)・マルチスタートのみ発散する diverge フェイク
    backend = ControlledFakeBackend(
        mode="diverge_multistart", chi2_single=10.0, chi2_two=1000.0, rwp=1.0
    )

    # 【実際の処理実行】: 全滅を例外化せず縮退値を返す (元仮説維持で判別継続)
    result = discriminate_interval(backend, _fake_series(), (0, 3), (PHASE_A0,))

    # 【結果検証】: 全滅の非例外化・空 basins・警告伝播・判別本体の継続
    assert result.multistart_single.basins == ()  # 【確認内容】: 端点マルチスタート全滅で空 basins 🟡
    assert result.multistart_single.warnings != ()  # 全滅を示す警告 (MultistartEngine 由来) 🟡
    assert result.warnings != ()  # 【確認内容】: 判別結果へ警告が伝播/包含される 🟡
    assert result.verdict == "solid_solution"  # 逐次 Σbic 比較から通常どおり決まる (元仮説維持) 🟡


def test_partial_backend_failure_does_not_confirm_a_verdict():
    # 【テスト目的】: 片仮説 (A) の backend 全失敗で Σbic 比較が不能になっても誤確定せず undecided + エスカレーション
    #   へ縮退することを確認 (比較可能性ガード)。
    # 【テスト内容】: ControlledFakeBackend(fail_single) で単相 (仮説 A) の全 refine に chi2=inf を注入し、
    #   2 相 (仮説 B) は有限値。A の Σbic は非有限フレーム除外で 0 (最小) に、B は正 → 素朴な ΔBIC は
    #   A 優位に見えるが、有限フレーム数が食い違う (A=0, B=n) ため判別を確定してはならない。
    # 【期待される動作】: 例外なし、verdict=="undecided"、escalations に incomparable_evidence、
    #   queue に incomparable_evidence 通知、delta<0 (素朴 Σbic では A が優位に見えるトラップ)。
    # 🔵 信頼性レベル: CLAUDE.md「backend 失敗=chi2=inf をガードレールで処理」/ segmentation の全滅=inf 対称に依拠。

    # 【テストデータ準備】: 仮説 A を全失敗・仮説 B は有限 chi2 を返す fail_single フェイク + ReviewQueue
    backend = ControlledFakeBackend(mode="fail_single", chi2_single=10.0, chi2_two=100.0)
    queue = ReviewQueue()

    # 【実際の処理実行】: 片仮説の全失敗を例外化せず、Σbic 比較不能として undecided へ縮退
    result = discriminate_interval(backend, _fake_series(), (0, 3), (PHASE_A0,), queue=queue)

    # 【結果検証】: 誤確定の回避・エスカレーション・Queue 通知・トラップの明示
    assert result.verdict == "undecided"  # 【確認内容】: 比較不能で verdict を確定しない 🔵
    assert any("incomparable_evidence" in msg for msg in result.escalations)  # 縮退理由の明示 🔵
    assert any(item.reason == "incomparable_evidence" for item in queue.unresolved)  # Queue 通知 🔵
    assert result.delta_evidence < 0  # 【確認内容】: 素朴 Σbic では A 優位に見える (ガードが無ければ誤確定) 🔵


def test_invalid_frame_range_raises_value_error():
    # 【テスト目的】: 不正な frame_range (start>end / 範囲外 / 負値) が ValueError になることを確認
    # 【テスト内容】: 3 パターンの不正区間で判別を呼び、いずれも ValueError・refine 未開始を確認
    # 【期待される動作】: pytest.raises(ValueError)、判別処理は開始されない (refine 呼び出し 0 件)
    # 🟡 信頼性レベル: sequential/series.py の明示 ValueError 慣習 / requirements §2.2 に依拠

    # 【テストデータ準備】: n_frames=8 の固溶体系列 + 呼び出し観測スパイ
    spy = RecordingSpyBackend()
    series = _solid_solution_series(n_frames=8)

    # 【実際の処理実行 & 結果検証】: start>end / end 範囲外 / 負値 index の 3 パターン
    for frame_range in [(5, 2), (0, 99), (-1, 3)]:
        with pytest.raises(ValueError):
            discriminate_interval(spy, series, frame_range, (PHASE_A0,), config=CONFIG_FAST)
    assert spy.calls == []  # 【確認内容】: フェイルファストで refine を開始しない 🟡


# ===========================================================================
# 3. 境界値テストケース
# ===========================================================================


def test_delta_bic_exactly_threshold_is_decided_closed_boundary():
    # 【テスト目的】: |ΔBIC| == close_threshold ちょうどは確定側 (>= の閉境界) になることを確認
    # 【テスト内容】: 単一フレーム区間 + ControlledFakeBackend(threshold) で ΔBIC を 10.0/9.99/10.01 に注入
    # 【期待される動作】: 10.0 → two_phase・queue 空、9.99 → undecided・queue 通知、10.01 → two_phase・queue 空
    # 🟡 信頼性レベル: タスク本文「ΔBIC ≥ 閾値で verdict、未満は undecided」の字義に依拠 (閉境界は推測)

    # 【テストデータ準備】: 単一フレーム区間 (N=1) で ΔBIC=chi2_single−chi2_two を厳密制御する threshold フェイク
    series = _fake_series()

    def _run(chi2_single: float):
        queue = ReviewQueue()
        backend = ControlledFakeBackend(mode="threshold", chi2_single=chi2_single, chi2_two=100.0)
        result = discriminate_interval(backend, series, (2, 2), (PHASE_A0,), queue=queue)
        return result, queue

    # 【実際の処理実行 & 結果検証】: 閾値の直上/ちょうど/直下で verdict と Queue 通知が切り替わる
    exact, exact_q = _run(110.0)  # ΔBIC = +10.0 ちょうど
    assert exact.verdict == "two_phase"  # 【確認内容】: 閾値ちょうどは確定側 (>= 閉境界) 🟡
    assert exact_q.unresolved == ()  # 【確認内容】: 確定側では僅差通知なし 🟡

    below, below_q = _run(109.99)  # ΔBIC = +9.99 (閾値直下)
    assert below.verdict == "undecided"  # 【確認内容】: 閾値未満は僅差 undecided 🟡
    assert any(i.reason == "close_competitor" for i in below_q.unresolved)  # 僅差通知あり 🟡

    above, above_q = _run(110.01)  # ΔBIC = +10.01 (閾値直上)
    assert above.verdict == "two_phase"  # 【確認内容】: 閾値超は確定側 🟡
    assert above_q.unresolved == ()  # 【確認内容】: 確定側では僅差通知なし 🟡


def test_none_queue_and_ledger_do_not_change_verdict():
    # 【テスト目的】: queue=None / ledger=None でも例外なく動作し判別結果が提供時と一致することを確認
    # 【テスト内容】: 僅差構成で None 版と提供版を実行し verdict/delta/escalations の一致を確認
    # 【期待される動作】: 例外なし、verdict=="undecided"、通知/記録の有無だけが異なり判別結果は同一
    # 🔵 信頼性レベル: interfaces.py L282-283 (ledger/queue 既定 None) に直接依拠

    # 【テストデータ準備】: 同一の僅差フェイク構成を None 版と提供版で実行
    series = _fake_series()
    result_none = discriminate_interval(
        ControlledFakeBackend(mode="close"), series, (0, 3), (PHASE_A0,),
        queue=None, ledger=None,
    )
    result_provided = discriminate_interval(
        ControlledFakeBackend(mode="close"), series, (0, 3), (PHASE_A0,),
        queue=ReviewQueue(), ledger=Ledger(),
    )

    # 【結果検証】: None ガード動作・判別結果の一致 (通知/記録の有無に非依存)
    assert result_none.verdict == "undecided"  # 【確認内容】: None でも僅差判別が成立 🔵
    assert result_none.verdict == result_provided.verdict  # verdict が一致 🔵
    assert result_none.delta_evidence == result_provided.delta_evidence  # ΔBIC が一致 🔵
    assert result_none.escalations == result_provided.escalations  # escalations が一致 🔵


def test_single_frame_interval_degenerate_is_deterministic():
    # 【テスト目的】: 単一フレーム区間 (start==end) で端点が縮退しても例外なく決定論的に判別できることを確認
    # 【テスト内容】: frame_range=(3,3) の固溶体系列を 2 回判別し非例外・ビット同一を確認
    # 【期待される動作】: 例外なし、verdict は 3 値のいずれか、2 回実行でビット同一
    # 🟡 信頼性レベル: frame_range 契約 (requirements §2.2) からの妥当推測 (単一区間の明記なし)

    # 【テストデータ準備】: 単一フレーム区間 (start==end=3) の固溶体系列
    series = _solid_solution_series(n_frames=8)
    result_a = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (3, 3), (PHASE_A0,), config=CONFIG_FAST
    )
    result_b = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (3, 3), (PHASE_A0,), config=CONFIG_FAST
    )

    # 【結果検証】: 端点縮退での非例外・verdict 域・決定論
    assert result_a.verdict in ("solid_solution", "two_phase", "undecided")  # verdict 域 🟡
    assert result_a == result_b  # 【確認内容】: 端点重複適用でもビット同一 (決定論) 🟡


def test_config_and_result_are_frozen_with_contract_defaults():
    # 【テスト目的】: DiscriminationConfig / DiscriminationResult が frozen で既定値が契約どおりであることを確認
    # 【テスト内容】: config の既定値検証 + config/result 各フィールド再代入で FrozenInstanceError を確認
    # 【期待される動作】: 既定値が interfaces.py L252-257 と一致、属性代入で FrozenInstanceError
    # 🔵 信頼性レベル: interfaces.py L252-271 / CLAUDE.md 規約 (frozen dataclass) に直接依拠

    # 【テストデータ準備】: 既定 config と最小構成の result を構築
    config = DiscriminationConfig()
    assert config.close_threshold == 10.0  # 【確認内容】: 僅差閾値の既定 🔵
    assert config.high_r_threshold == 30.0  # 【確認内容】: 高 R 閾値の既定 🔵
    assert config.seq_max_cycles == 10  # 【確認内容】: 区間内逐次 refine サイクルの既定 🔵
    assert config.multistart == MultistartConfig()  # 【確認内容】: マルチスタート設定の既定 🔵

    ms = MultistartResult(
        basins=(), n_starts=1, n_diverged=0, promoted=(), is_global_corroborated=False
    )
    hyp = Hypothesis(id="h", phases=())
    result = DiscriminationResult(
        verdict="undecided",
        delta_evidence=0.0,
        hypothesis_single=hyp,
        hypothesis_two_phase=hyp,
        multistart_single=ms,
        multistart_two_phase=ms,
        escalations=(),
    )

    # 【結果検証】: frozen=True (再代入拒否)
    with pytest.raises(FrozenInstanceError):
        config.close_threshold = 5.0  # 【確認内容】: DiscriminationConfig は不変 🔵
    with pytest.raises(FrozenInstanceError):
        result.verdict = "two_phase"  # 【確認内容】: DiscriminationResult は不変 🔵


def test_single_interval_discrimination_under_thirty_seconds():
    # 【テスト目的】: 判別 1 区間 (N=8) が 30 秒以内で完了する (端点のみマルチスタート設計の smoke)
    # 【テスト内容】: 小グリッド固溶体系列 + 既定 config (n_starts=8) の判別を perf_counter で計測
    # 【期待される動作】: 経過時間 < 30.0 秒、判別結果も正しい (verdict=="solid_solution")
    # 🟡 信頼性レベル: 受け入れ基準 TC-209-03 / NFR-001 に依拠 (グリッド粒度・計測方法は妥当推測)

    # 【テストデータ準備】: 小グリッド (0.05 刻み) の固溶体系列 + 既定 config (n_starts=8)
    series = _solid_solution_series(n_frames=8)
    backend = SimulatedBackend(peak_fwhm=0.2)

    # 【実際の処理実行】: 端点 2 フレーム × 2 仮説のみマルチスタート + direct 逐次 refine
    start = time.perf_counter()
    result = discriminate_interval(backend, series, (0, 7), (PHASE_A0,))
    elapsed = time.perf_counter() - start

    # 【結果検証】: 性能上限と判別の正しさ
    assert elapsed < 30.0  # 【確認内容】: 判別 1 区間が 30 秒以内 🟡
    assert result.verdict == "solid_solution"  # 【確認内容】: smoke でも判別が正しい 🔵
