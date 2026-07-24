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

import importlib.util
import math
import time
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, RefinementResult
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.evidence.base import EvidenceResult
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance
from tsumugin.multistart import MultistartConfig
from tsumugin.multistart.engine import MultistartResult
from tsumugin.nested.arbitration import ArbitrationConfig
from tsumugin.nested.sampler import NestedBackend, NestedConfig, NestedOutcome
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


class FrameFailFakeBackend:
    """仮説 A を frame offset ``fail_a``、仮説 B を frame offset ``fail_b`` で発散させる決定論スタブ。

    逐次 direct refine (max_cycles != ms_max_cycles) を仮説種別 (単相=A / 2 相=B) ごとにカウントし、
    指定 offset 番目のフレームのみ chi2=inf/rwp=inf を返す。端点 (offset 0 と末尾) は成功させ、A/B が
    「異なる 1 フレーム」で発散する → 有限フレーム件数は同じ (n-1) だが**集合が食い違う**縮退を作る。
    件数一致だけを見るガードはこれを見逃すため、有限フレーム集合一致を要求する強化ガードの検証に用いる。
    マルチスタート呼び出し (max_cycles==ms) は常に有限 (端点 basin を作らせ B 初期化を成立させる)。
    """

    name = "framefail"

    def __init__(
        self,
        *,
        fail_a: int,
        fail_b: int,
        chi2_single: float = 10.0,
        chi2_two: float = 100.0,
        rwp: float = 1.0,
        ms_max_cycles: int = 15,
    ) -> None:
        self.fail_a = int(fail_a)
        self.fail_b = int(fail_b)
        self.chi2_single = float(chi2_single)
        self.chi2_two = float(chi2_two)
        self.rwp = float(rwp)
        self.ms_max_cycles = int(ms_max_cycles)
        self._seq_a = 0  # 単相逐次 refine の通し番号 (= 区間フレーム offset)
        self._seq_b = 0  # 2 相逐次 refine の通し番号 (= 区間フレーム offset)

    def simulate(self, phases, two_theta):
        return np.zeros_like(np.asarray(two_theta, dtype=float))

    def peak_positions(self, phase, two_theta):
        return []

    def refine(self, model: RefinementModel, *, max_cycles: int = 20) -> RefinementResult:
        n_phases = len(model.phases)
        n_obs = int(np.asarray(model.intensity).size)
        chi2 = self.chi2_single if n_phases <= 1 else self.chi2_two
        rwp = self.rwp
        # 【逐次のみ offset 判定】: マルチスタート (max_cycles==ms) は常に有限にして端点 basin を確保
        if max_cycles != self.ms_max_cycles:
            if n_phases <= 1:
                if self._seq_a == self.fail_a:
                    chi2, rwp = float("inf"), float("inf")
                self._seq_a += 1
            else:
                if self._seq_b == self.fail_b:
                    chi2, rwp = float("inf"), float("inf")
                self._seq_b += 1
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


class FakeNestedBackend:
    """discriminate_interval(nested_backend=...) 注入用フェイク (Issue #65)。

    ``EvidenceProblem.label`` ("single"/"two_phase") ごとに固定 value を返すことで、
    nested 裁定の結果を決定論的に制御する。実 dynesty/ultranest を一切 import しない。
    ``run_with_fallback(problem, *, ledger=None) -> NestedOutcome`` のみ実装 (duck typing)。
    """

    def __init__(self, values_by_label: dict[str, float], *, truncated: bool = False) -> None:
        self._values = values_by_label
        self._truncated = truncated
        self.calls: list[str] = []

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        self.calls.append(problem.label)
        value = self._values[problem.label]
        backend_name = "laplace" if self._truncated else "nested"
        result = EvidenceResult(backend=backend_name, value=value)
        if ledger is not None:
            ledger.append(
                "nested_fallback" if self._truncated else "nested_run",
                {"label": problem.label, "value": value},
            )
        return NestedOutcome(result=result, logz=-value, truncated=self._truncated)


class RaisingNestedBackend:
    """run_with_fallback がフォールバックすら不能な完全失敗を模すフェイク (Issue #65 / 要件3d)。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        self.calls.append(problem.label)
        raise RuntimeError("total nested failure (simulated)")


class MixedRouteNestedBackend:
    """label ごとに nested 成功/Laplace 縮退 (truncated) を個別制御できるフェイク。

    PR #75 レビュー指摘の三重ガード①「同一経路」検証用: 片側 nested 成功・片側 Laplace 縮退という
    evidence のスケールが食い違う (-logZ vs Σbic) 非対称ケースを決定論的に注入する。
    ``warnings_by_label`` を与えると ``NestedOutcome.warnings`` にそのタプルを載せ、
    ``ArbitrationResult.warnings`` 経由の伝播 (要件4) も検証できる。
    """

    def __init__(
        self,
        values_by_label: dict[str, float],
        truncated_by_label: dict[str, bool],
        *,
        warnings_by_label: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._values = values_by_label
        self._truncated = truncated_by_label
        self._warnings = warnings_by_label or {}
        self.calls: list[str] = []

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        self.calls.append(problem.label)
        value = self._values[problem.label]
        truncated = self._truncated[problem.label]
        backend_name = "laplace" if truncated else "nested"
        result = EvidenceResult(backend=backend_name, value=value)
        warnings = self._warnings.get(problem.label, ())
        if ledger is not None:
            ledger.append(
                "nested_fallback" if truncated else "nested_run",
                {"label": problem.label, "value": value},
            )
        return NestedOutcome(result=result, logz=-value, truncated=truncated, warnings=warnings)


class SpyNestedBackend:
    """discriminate_interval が nested を呼んだかどうかだけを記録するフェイク (Issue #65 / 要件2)。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        self.calls.append(problem.label)
        result = EvidenceResult(backend="nested", value=0.0)
        return NestedOutcome(result=result, logz=0.0, truncated=False)


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


def test_two_phase_endmembers_preserve_active_phase_ref_for_hkl_lookup():
    # 【テスト目的】: 仮説 B の端成分が初期活物質相の phase_ref を保持することを確認 (改名しない)。
    # 【テスト内容】: 固溶体系列を判別し、hypothesis_two_phase の活物質端成分 (固定相なし) の phase_ref 集合を検証。
    # 【期待される動作】: 端成分 phase_ref はすべて初期相の "A" (端成分は同一結晶構造の 2 格子)。
    # 【背景】: phase_ref を "A#alpha"/"A#beta" 等へ改名すると backend の hkl_table 完全一致引きを外し、
    #   hkl_table 登録時に仮説 B が既定 hkl へ落ちて Σbic_B が偏り verdict を歪める (回帰防止の構造テスト)。
    # 🔵 信頼性レベル: SimulatedBackend.hkl_table の完全一致引き / 二相反応端成分の同一構造前提に依拠。

    # 【テストデータ準備】: 固溶体系列 (固定相なし → hypothesis_two_phase.phases は活物質端成分のみ)
    series = _solid_solution_series(n_frames=8)
    result = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,), config=CONFIG_FAST
    )

    # 【結果検証】: 端成分 phase_ref が初期相 "A" のまま (改名されていない = hkl 引きの完全一致キーを保つ)
    b_refs = {phase.phase_ref for phase in result.hypothesis_two_phase.phases}
    assert b_refs == {"A"}  # 【確認内容】: 2 端成分とも初期 phase_ref を継承・改名なし 🔵


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


def test_disjoint_finite_frames_with_equal_count_are_incomparable():
    # 【テスト目的】: 両仮説が「異なる 1 フレーム」で発散し有限フレーム件数は同じでも、集合が食い違えば
    #   Σbic 比較を信頼せず undecided + incomparable_evidence へ縮退することを確認 (集合一致ガード)。
    # 【テスト内容】: FrameFailFakeBackend で仮説 A を frame1・仮説 B を frame2 で発散させる (区間 0..3)。
    #   有限集合は A={0,2,3} / B={0,1,3} で件数は 3 で一致するが集合は不一致。件数のみ見るガードは
    #   誤って verdict を確定 (chi2_single≪chi2_two のため solid_solution) してしまう。
    # 【期待される動作】: verdict=="undecided"、escalations に incomparable_evidence、warnings に A の frame1・
    #   B の frame2 除外が両方含まれる (集合が実際に食い違ったことの裏付け)。
    # 🔵 信頼性レベル: 比較可能性ガードの十分条件化 (件数一致は必要条件に過ぎない) / CLAUDE.md 不変条件に依拠。

    # 【テストデータ準備】: A=frame1 / B=frame2 で発散 (端点 0,3 は成功) する framefail フェイク + Queue
    backend = FrameFailFakeBackend(fail_a=1, fail_b=2, chi2_single=10.0, chi2_two=100.0)
    queue = ReviewQueue()

    # 【実際の処理実行】: 件数一致でも集合不一致なら Σbic 比較不能として undecided へ縮退
    result = discriminate_interval(backend, _fake_series(), (0, 3), (PHASE_A0,), queue=queue)

    # 【結果検証】: 集合不一致の検出・誤確定の回避・除外フレームの裏付け
    assert result.verdict == "undecided"  # 【確認内容】: 集合不一致で verdict を確定しない 🔵
    assert any("incomparable_evidence" in msg for msg in result.escalations)  # 縮退理由の明示 🔵
    assert any(item.reason == "incomparable_evidence" for item in queue.unresolved)  # Queue 通知 🔵
    assert any("hypothesis_a" in w and "frame 1" in w for w in result.warnings)  # A は frame1 除外 🔵
    assert any("hypothesis_b" in w and "frame 2" in w for w in result.warnings)  # B は frame2 除外 🔵


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


# ===========================================================================
# 4. nested 裁定 (Issue #65 / FR-313 / FR-122) — bic 一次 + 僅差競合のみ nested 再裁定
# ===========================================================================
#
# ControlledFakeBackend(mode="close") + _fake_series() は既存 TC-E01 と同一構成: chi2_single==
# chi2_two==100.0 かつ両仮説の評価 DOF が釣り合う (4==4) ため ΔBIC=0 (僅差)。この close_competitor
# 構成に discriminate_interval(nested_backend=...) を注入して nested 裁定配線を検証する。


def _close_competitor_config(nested_arbitration: ArbitrationConfig | None) -> DiscriminationConfig:
    """TC-E01 と同一の close_threshold=10.0 既定で nested_arbitration だけを差し替える。"""
    return DiscriminationConfig(nested_arbitration=nested_arbitration)


def test_nested_arbitration_invoked_on_close_competitor_adds_provenance():
    # 【テスト目的】: 僅差競合 + nested_arbitration 設定ありで裁定が実行され、判別結果に由来
    #   (adjudicated_by/nested_delta_evidence/nested_arbitration) が付くことを確認 (Red (a))。
    # 【テスト内容】: close 構成 + FakeNestedBackend(単相優位に振った決定論値) を注入して判別
    # 【期待される動作】: 例外なし、nested が両ラベルで呼ばれる、adjudicated_by=="nested"、
    #   nested_delta_evidence が負 (単相優位)、暫定 verdict=="solid_solution" へ更新、
    #   close_competitor の ReviewQueue 通知は維持される (要件4)
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    queue = ReviewQueue()
    nested = FakeNestedBackend({"single": 50.0, "two_phase": 200.0})
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, queue=queue, nested_backend=nested,
    )

    # 【結果検証】: nested 裁定が実際に実行され (両ラベル呼び出し)、由来と暫定 verdict が反映される
    assert sorted(nested.calls) == ["single", "two_phase"]  # 両仮説とも nested 対象 🔵
    assert result.adjudicated_by == "nested"  # 【確認内容】: 裁定由来が判別結果に付く (要件3) 🔵
    # 【Issue #76】: nested 経路 (-logZ スケール) は ×2 の BIC 等価スケールで記録される
    assert result.nested_delta_evidence == pytest.approx(2.0 * (50.0 - 200.0))  # single 優位で負 🔵
    assert result.nested_arbitration is not None
    assert result.nested_arbitration.nested_ids == ("discrimination-single", "discrimination-two-phase")
    assert result.verdict == "solid_solution"  # 【確認内容】: 暫定裁定で undecided から更新 (FR-403) 🔵
    # 【要件4】: 既存エスカレーション動作は維持 (close_competitor は取り下げない・要確認フラグ)
    assert any(item.reason == "close_competitor" for item in queue.unresolved)
    assert any("nested_arbitration" in msg for msg in result.escalations)
    # 【レビュー指摘 (d): 解消時の文言】: verdict が確定した場合のみ「〜としました」を含む 🔵
    assert any("としました" in msg for msg in result.escalations)


def test_nested_arbitration_not_invoked_when_not_close_competitor():
    # 【テスト目的】: 非僅差 (明瞭な判別) では nested が絶対に呼ばれないことを確認 (Red (b) / 要件2)。
    # 【テスト内容】: 固溶体系列の decisive 判別に nested_arbitration を設定し SpyNestedBackend を注入
    # 【期待される動作】: nested.calls が空、adjudicated_by=="bic"、nested_arbitration is None
    series = _solid_solution_series(n_frames=8)
    spy = SpyNestedBackend()
    config = DiscriminationConfig(
        multistart=MultistartConfig(n_starts=2), nested_arbitration=ArbitrationConfig()
    )

    result = discriminate_interval(
        SimulatedBackend(peak_fwhm=0.2), series, (0, 7), (PHASE_A0,),
        config=config, nested_backend=spy,
    )

    # 【結果検証】: 明瞭な判別 (非僅差) では nested がコスト抑制のため一切呼ばれない
    assert result.verdict == "solid_solution"  # 【前提確認】: 明瞭判別 (close_competitor でない) 🔵
    assert spy.calls == []  # 【確認内容】: nested は非僅差で絶対に呼ばれない 🔵
    assert result.adjudicated_by == "bic"  # 【確認内容】: 由来は bic のまま 🔵
    assert result.nested_arbitration is None
    assert result.nested_delta_evidence is None


def test_nested_arbitration_none_config_matches_prior_behavior():
    # 【テスト目的】: nested_arbitration=None (既定) では新フィールドが中立既定のまま現行挙動と
    #   完全一致することを確認 (Red (c) / 後方互換)。
    # 【テスト内容】: 旧来どおりの呼び出し (新 kwarg 省略) と、明示的に nested_arbitration=None を
    #   渡した呼び出しを比較し、bic 系フィールドが TC-E01 の期待と一致することを確認
    backend_kwargs = dict(mode="close", chi2_single=100.0, chi2_two=100.0)
    series = _fake_series()

    result_legacy = discriminate_interval(
        ControlledFakeBackend(**backend_kwargs), series, (0, 3), (PHASE_A0,),
    )
    result_explicit_none = discriminate_interval(
        ControlledFakeBackend(**backend_kwargs), series, (0, 3), (PHASE_A0,),
        config=DiscriminationConfig(nested_arbitration=None),
    )

    for result in (result_legacy, result_explicit_none):
        assert result.verdict == "undecided"  # 【確認内容】: TC-E01 と同一の bic 一次結果 🔵
        assert abs(result.delta_evidence) < 10.0
        assert result.adjudicated_by == "bic"  # 【確認内容】: nested 未配線時の中立既定 🔵
        assert result.nested_delta_evidence is None
        assert result.nested_arbitration is None
    # 【後方互換】: nested_arbitration 省略と明示 None は完全に同一の結果になる
    assert result_legacy == result_explicit_none


def test_nested_arbitration_total_failure_falls_back_to_review_queue_escalation():
    # 【テスト目的】: nested 裁定が (フォールバックすら不能な) 例外で完全失敗しても discriminate_interval
    #   が例外を投げず、bic 一次の close_competitor エスカレーションへ縮退することを確認 (Red (d))。
    # 【テスト内容】: run_with_fallback が常に RuntimeError を送出する RaisingNestedBackend を注入
    # 【期待される動作】: 例外なし、verdict=="undecided" (bic 一次のまま)、adjudicated_by=="bic"、
    #   nested_arbitration is None、queue に close_competitor 通知は維持、warnings に失敗理由が残る
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    queue = ReviewQueue()
    raising = RaisingNestedBackend()
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, queue=queue, nested_backend=raising,
    )

    # 【結果検証】: 完全失敗でも例外化せず bic 一次のエスカレーションへ縮退する (要件3/4)
    assert result.verdict == "undecided"  # 【確認内容】: bic 一次のまま (nested が救えなかった) 🔵
    assert result.adjudicated_by == "bic"  # 【確認内容】: nested 裁定は不成立 🔵
    assert result.nested_arbitration is None
    assert result.nested_delta_evidence is None
    assert any(item.reason == "close_competitor" for item in queue.unresolved)  # 通知は維持 🔵
    assert any("nested_arbitration" in w for w in result.warnings)  # 失敗理由が警告に残る 🔵


def test_nested_arbitration_records_ledger_and_verifies():
    # 【テスト目的】: nested 裁定発動時に判別・裁定双方の操作が ledger に記録され、記録後も
    #   verify()==True であることを確認 (Red (e) / NFR-105)。
    # 【テスト内容】: close 構成 + FakeNestedBackend + Ledger を渡して判別を実行
    # 【期待される動作】: entries 非空、"discrimination.nested_arbitration" と "arbitration"
    #   (nested.arbitration.arbitrate 自身の記録) の両方を含み、verify()==True
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    nested = FakeNestedBackend({"single": 50.0, "two_phase": 200.0})
    ledger = Ledger()
    config = _close_competitor_config(ArbitrationConfig())

    discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, ledger=ledger, nested_backend=nested,
    )

    # 【結果検証】: nested 裁定の実行・結果・由来が理由付きで記録され、チェーン整合を保つ
    kinds = [e.kind for e in ledger.entries]
    assert "discrimination.nested_arbitration" in kinds  # discrimination 自身の由来記録 🔵
    assert "arbitration" in kinds  # nested.arbitration.arbitrate 自身の理由付き記録 (再利用) 🔵
    assert ledger.verify() is True  # 【確認内容】: 追記後もハッシュチェーン整合 🔵


# ---------------------------------------------------------------------------
# PR #75 レビュー確定指摘: verdict 上書きの三重ガード / 契約修復 / メッセージング正直化 (Issue #65)
# ---------------------------------------------------------------------------


def test_nested_arbitration_mixed_route_does_not_override_verdict():
    # 【テスト目的】: 片側 nested 成功・片側 Laplace 縮退 (経路混在) では、素朴な ΔBIC(nested) が
    #   閾値を超えていても verdict を上書きせず、経路非対称の警告を残すことを確認
    #   (レビュー指摘: 三重ガード①「同一経路」。evidence のスケール [-logZ vs Σbic] が食い違うため)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    queue = ReviewQueue()
    nested = MixedRouteNestedBackend(
        values_by_label={"single": 50.0, "two_phase": 200.0},
        truncated_by_label={"single": False, "two_phase": True},
    )
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, queue=queue, nested_backend=nested,
    )

    # 【結果検証】: 両ラベルとも呼ばれるが経路混在のため verdict は undecided のまま
    assert sorted(nested.calls) == ["single", "two_phase"]
    assert result.verdict == "undecided"  # 【確認内容】: 経路混在では verdict を上書きしない 🔵
    assert any(
        "経路が非対称のため裁定値を比較できません" in msg for msg in result.escalations
    )  # 経路混在の警告 🔵
    assert any(item.reason == "close_competitor" for item in queue.unresolved)  # 通知は維持 🔵


def test_nested_arbitration_non_finite_delta_does_not_override_verdict():
    # 【テスト目的】: nested/Laplace 裁定後の ΔBIC(nested) が非有限 (inf) のとき verdict を
    #   上書きしないことを確認 (レビュー指摘: 三重ガード②「有限性」)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    queue = ReviewQueue()
    nested = FakeNestedBackend({"single": float("inf"), "two_phase": 200.0})
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, queue=queue, nested_backend=nested,
    )

    # 【結果検証】: 非有限 delta では verdict を確定しない (bic 一次の undecided のまま)
    assert result.verdict == "undecided"  # 【確認内容】: 非有限 ΔBIC では verdict を上書きしない 🔵
    assert result.nested_delta_evidence is not None
    assert not math.isfinite(result.nested_delta_evidence)  # 由来自体は記録される (監査用) 🔵
    # 【文言検証 (レビュー指摘)】: 非有限は通常の僅差継続と区別し「evidence 計算の異常」と明示する。
    #   「僅差は解消されませんでした」(閾値未満の正常ケース文言) を出さない 🔵
    non_finite_msgs = [m for m in result.escalations if "非有限" in m]
    assert non_finite_msgs
    assert all("異常" in m for m in non_finite_msgs)
    assert all("僅差は解消されませんでした" not in m for m in result.escalations)


def test_nested_arbitration_unresolved_message_omits_settled_wording():
    # 【テスト目的】: nested 裁定後も僅差が解消されない (|ΔBIC(nested)| < close_threshold のまま) 場合、
    #   verdict を確定させたと誤解させる「〜としました」という文言を含まないことを確認
    #   (レビュー指摘: メッセージングの正直化)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    # 【Issue #76】: nested 経路は ×2 の BIC 等価スケールで閾値比較されるため、
    #   |2Δ|=8 < close_threshold=10 になる値を選ぶ (未解消メッセージの検証が目的)
    nested = FakeNestedBackend({"single": 100.0, "two_phase": 104.0})
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=nested,
    )

    # 【結果検証】: 未解消メッセージのみが積まれ、「としました」を含まない
    assert result.verdict == "undecided"
    nested_msgs = [m for m in result.escalations if "nested_arbitration" in m]
    assert nested_msgs  # 【確認内容】: nested 裁定のメッセージ自体は積まれる 🔵
    assert all("としました" not in m for m in nested_msgs)  # 未確定を確定と誤認させない 🔵
    assert any("再裁定でも僅差は解消されませんでした" in m for m in nested_msgs)


def test_nested_arbitration_propagates_arbitration_warnings():
    # 【テスト目的】: nested 裁定 (ArbitrationResult) 由来の警告 (truncated/縮退等) が
    #   DiscriminationResult.warnings へマージされることを確認 (レビュー指摘: warnings 退行の修復)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    nested = MixedRouteNestedBackend(
        values_by_label={"single": 50.0, "two_phase": 200.0},
        truncated_by_label={"single": True, "two_phase": True},  # 両方 Laplace 縮退 (同一経路)
        warnings_by_label={
            "single": ("nested sampling を打ち切り Laplace 代替へ縮退しました (single)。",),
            "two_phase": ("nested sampling を打ち切り Laplace 代替へ縮退しました (two_phase)。",),
        },
    )
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=nested,
    )

    # 【結果検証】: 両ラベルの縮退警告が判別結果の warnings に現れる (以前は空になっていた退行)
    assert any("Laplace 代替へ縮退しました (single)" in w for w in result.warnings)
    assert any("Laplace 代替へ縮退しました (two_phase)" in w for w in result.warnings)


def test_nested_arbitration_queue_detail_includes_bic_and_nested_messages():
    # 【テスト目的】: ReviewQueue の detail に close_competitor の元メッセージ (bic 一次) と
    #   nested 裁定結果の両方が含まれ、detail 単体で読めることを確認 (レビュー指摘: queue detail 更新)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    queue = ReviewQueue()
    nested = FakeNestedBackend({"single": 50.0, "two_phase": 200.0})
    config = _close_competitor_config(ArbitrationConfig())

    discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, queue=queue, nested_backend=nested,
    )

    items = [i for i in queue.unresolved if i.reason == "close_competitor"]
    assert items
    detail = items[0].detail
    assert "close_competitor" in detail  # 元メッセージ (bic 一次の僅差説明) 🔵
    assert "nested_arbitration" in detail  # nested 裁定結果も同一 detail から読める 🔵


def test_nested_arbitration_ledger_sanitizes_non_finite_delta():
    # 【テスト目的】: nested_delta_evidence が非有限 (inf) のとき ledger payload では None 化される
    #   ことを確認 (レビュー指摘: canonical JSON への Infinity 混入防止)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    nested = FakeNestedBackend({"single": float("inf"), "two_phase": 200.0})
    ledger = Ledger()
    config = _close_competitor_config(ArbitrationConfig())

    discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, ledger=ledger, nested_backend=nested,
    )

    entry = next(e for e in ledger.entries if e.kind == "discrimination.nested_arbitration")
    assert entry.payload["nested_delta_evidence"] is None  # 非有限は None 化 🔵
    assert ledger.verify() is True  # 【確認内容】: 追記後もハッシュチェーン整合 🔵


def test_nested_arbitration_is_deterministic_bitwise_identical():
    # 【テスト目的】: 同一入力 (決定論フェイク nested backend) で 2 回実行すると DiscriminationResult
    #   が完全ビット同一になることを確認 (Red (f) / NFR-102)。
    # 【テスト内容】: close 構成 + FakeNestedBackend (乱数不使用) を独立に 2 回判別し結果の == 一致を確認
    # 【期待される動作】: result_a == result_b (nested_arbitration/adjudicated_by/verdict 含め全一致)
    config = _close_competitor_config(ArbitrationConfig())

    def _run() -> DiscriminationResult:
        backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
        nested = FakeNestedBackend({"single": 50.0, "two_phase": 200.0})
        return discriminate_interval(
            backend, _fake_series(), (0, 3), (PHASE_A0,),
            config=config, nested_backend=nested,
        )

    result_a = _run()
    result_b = _run()

    # 【結果検証】: LaplaceBackend/シミュレートのみ用いた決定論経路でビット同一 (NFR-102)
    assert result_a == result_b  # 【確認内容】: 2 回実行でビット同一 🔵


@pytest.mark.nested
def test_nested_arbitration_real_dynesty_smoke():
    # 【テスト目的】: 実 nested サンプラ (dynesty, optional extra) が導入済みの環境で、discrimination
    #   が構成する EvidenceProblem (定数尤度サロゲート) が実サンプラで最後まで実行できることを確認する
    #   smoke テスト (未導入環境は conftest.py の nested マーカーで自動 skip)。
    # 【テスト内容】: close 構成 + 実 NestedBackend (n_live/max_calls を小さく絞り高速化) で判別
    # 【期待される動作】: 例外なし、adjudicated_by in ("nested","laplace") (時間内に完走すれば nested)、
    #   nested_arbitration.nested_ids に両仮説の id が含まれる
    if importlib.util.find_spec("dynesty") is None:
        pytest.skip("dynesty 未導入")

    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    real_nested = NestedBackend(config=NestedConfig(n_live=25, max_calls=2000, seed=0))
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=real_nested,
    )

    # 【結果検証】: 実サンプラ配線が最後まで動作する (縮退しても laplace で許容)
    assert result.adjudicated_by in ("nested", "laplace")
    assert result.nested_arbitration is not None
    assert set(result.nested_arbitration.nested_ids) == {
        "discrimination-single", "discrimination-two-phase",
    }


# ===========================================================================
# 5. 物理尤度配線 (Issue #76 / T4) — v1 サロゲートからの置換・実効経路検出・BIC 等価スケール
# ===========================================================================


class CaptureNestedBackend:
    """run_with_fallback へ渡された EvidenceProblem 自体を捕捉するフェイク (Issue #76 T4)。"""

    def __init__(self, values_by_label: dict[str, float], *, truncated: bool = False) -> None:
        self._values = values_by_label
        self._truncated = truncated
        self.problems: dict[str, object] = {}

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        self.problems[problem.label] = problem
        value = self._values[problem.label]
        backend_name = "laplace" if self._truncated else "nested"
        result = EvidenceResult(backend=backend_name, value=value)
        return NestedOutcome(result=result, logz=-value, truncated=self._truncated)


class EchoBicNestedBackend:
    """value = BIC(problem.metrics) をそのまま返す (= Laplace の BIC フォールバック) フェイク。

    実効経路検出 (Issue #76 T4) の "bic_fallback" 判定は「value が BIC 値に厳密一致する」
    という LaplaceBackend の文書化契約を用いる。本フェイクはその状況を決定論的に再現する。
    ``offset_by_label`` で片側だけ BIC からずらし「実 Laplace」経路を模せる。
    """

    def __init__(self, offset_by_label: dict[str, float] | None = None) -> None:
        self._offsets = offset_by_label or {}
        self.calls: list[str] = []

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        from tsumugin.evidence.ic import BICBackend

        self.calls.append(problem.label)
        value = float(BICBackend().score(problem.metrics).value)
        value += self._offsets.get(problem.label, 0.0)
        result = EvidenceResult(backend="laplace", value=value)
        return NestedOutcome(result=result, logz=None, truncated=True)


def test_physical_problem_is_default_for_nested_arbitration():
    # 【テスト目的】: nested 裁定発動時、既定で v1 サロゲート (定数尤度・map_point 無し・ダミー 1 次元
    #   事前分布) でなく物理 problem (map_point あり・frame 前置の実パラメータ事前分布) が渡ること。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    capture = CaptureNestedBackend({"single": 50.0, "two_phase": 200.0})
    config = _close_competitor_config(ArbitrationConfig())

    discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=capture,
    )

    problem = capture.problems["single"]
    # 【確認内容】: 物理 problem の指紋 — map_point が精密化状態から埋まり、priors が frame 前置 🔵
    assert problem.map_point is not None
    names = [p.param_name for p in problem.priors]
    assert all(n.startswith("frame") for n in names)
    assert len(names) >= 4  # 4 フレーム × 解放パラメータ (>=1) — ダミー 1 次元でない
    # 【確認内容】: 仮説 B 側も物理 problem 🔵
    problem_b = capture.problems["two_phase"]
    assert problem_b.map_point is not None


def test_physical_problem_escape_hatch_none_restores_v1_surrogate():
    # 【テスト目的】: DiscriminationConfig.physical_problem=None で v1 サロゲート (定数尤度・
    #   ダミー 1 次元事前分布・map_point 無し) へ明示退避できること (互換 escape hatch)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    capture = CaptureNestedBackend({"single": 50.0, "two_phase": 200.0})
    config = DiscriminationConfig(
        nested_arbitration=ArbitrationConfig(), physical_problem=None
    )

    discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=capture,
    )

    problem = capture.problems["single"]
    assert problem.map_point is None  # v1 サロゲートの指紋 🔵
    assert [p.param_name for p in problem.priors] == ["discrimination.single.quality"]


def test_nested_delta_is_bic_equivalent_scale():
    # 【テスト目的】: nested 経路の Δ は BIC 等価スケール (×2) で閾値比較・記録されること
    #   (ΔBIC ≈ 2Δ(-logZ))。raw Δ=-6 (閾値未満) でも 2Δ=-12 で solid_solution が確定する。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    nested = FakeNestedBackend({"single": 100.0, "two_phase": 106.0})
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=nested,
    )

    assert result.nested_delta_evidence == pytest.approx(2.0 * (100.0 - 106.0))
    assert result.verdict == "solid_solution"  # |2Δ|=12 >= 10 で確定 🔵


def test_bic_fallback_both_sides_stays_honest_undecided():
    # 【テスト目的】: 両仮説とも Laplace の BIC フォールバック (実曲率なし = v1 と同じ情報しか無い)
    #   のときは Δ=ΔΣbic (スケールしない) のままで、発動条件と同じ閾値未満 → undecided を維持する
    #   (「解消できないものを解消したと主張しない」正直さの保存)。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    nested = EchoBicNestedBackend()  # 両側 BIC 値そのもの
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=nested,
    )

    assert result.verdict == "undecided"  # bic_fallback は僅差を解消できない (v1 と同じ) 🔵
    assert result.nested_delta_evidence is not None
    assert abs(result.nested_delta_evidence) < 10.0  # スケールされていない (ΔΣbic のまま) 🔵


def test_route_detection_distinguishes_real_laplace_from_bic_fallback():
    # 【テスト目的】: 片側「実 Laplace (-logZ スケール)」・片側「BIC フォールバック (Σbic スケール)」は
    #   どちらも adjudicated_by=="laplace" になるため v1 の経路一致判定では見抜けない (潜在欠陥)。
    #   実効経路検出 (value == BIC 値の文書化契約) がこの混在を経路非対称として undecided に留めること。
    backend = ControlledFakeBackend(mode="close", chi2_single=100.0, chi2_two=100.0)
    # single は BIC フォールバック (echo)、two_phase は BIC から +200 ずれた「実 Laplace」値
    nested = EchoBicNestedBackend(offset_by_label={"two_phase": 200.0})
    config = _close_competitor_config(ArbitrationConfig())

    result = discriminate_interval(
        backend, _fake_series(), (0, 3), (PHASE_A0,),
        config=config, nested_backend=nested,
    )

    # raw Δ = -200 (閾値超) でも経路混在なので verdict を上書きしない
    assert result.verdict == "undecided"
    assert any("経路が非対称のため裁定値を比較できません" in m for m in result.escalations)


# ---------------------------------------------------------------------------
# Issue #76 受け入れ基準: bic 僅差だが実曲率 Laplace/nested は判別可能なケース
# ---------------------------------------------------------------------------


class _LaplaceOnlyNestedBackend:
    """score_problem を実 LaplaceBackend へ直行させる (dynesty を回さない) 決定論バックエンド。

    実 NestedBackend の「サンプラ未導入 → Laplace 縮退」経路と同一の実効経路
    ("laplace" = 実曲率 Laplace) を、dynesty の導入有無に依存せず決定論的に踏む。
    """

    def __init__(self) -> None:
        from tsumugin.nested.laplace import LaplaceBackend

        self.laplace = LaplaceBackend()

    def run_with_fallback(self, problem, *, ledger=None) -> NestedOutcome:
        res = self.laplace.score_problem(problem)
        return NestedOutcome(result=res, logz=None, truncated=True)


def _two_phase_close_tie_setup() -> tuple[SimulatedBackend, FrameSeries, PhaseInstance]:
    """bic 僅差になる真の二相系列 (broad peak で単相が肩代わり可能) を構成する。

    真実 = 二相 (a=5.00 / a=5.04, fwhm=0.6 で重なる) の相分率が 0.3→0.7 と変化する 3 フレーム。
    単相 (格子解放) 仮説 A が各フレームの平均ピーク位置をほぼ完全に肩代わりできるため
    ΔΣbic < 1 (bic では判別不能) だが、実曲率 Laplace は実 DOF 差 (A: 4/フレーム vs
    B: 2/フレーム) を curvature/事前分布体積で罰し ΔBIC_nested ≈ +23 で two_phase (真実) を
    確定できる (探索記録: scratchpad/explore_t5b.py, 2026-07-22)。
    """
    backend = SimulatedBackend(peak_fwhm=0.6)
    tt = np.arange(15.0, 80.0, 0.05)
    frames = []
    for i in range(3):
        x = 0.3 + 0.4 * i / 2.0
        y = backend.simulate(
            (
                PhaseInstance(phase_ref="P", lattice=LatticeParams(5.0, 5.0, 5.0), scale=1.0 - x),
                PhaseInstance(phase_ref="P", lattice=LatticeParams(5.04, 5.04, 5.04), scale=x),
            ),
            tt,
        )
        frames.append(y)
    series = FrameSeries(two_theta=tt, intensities=np.array(frames))
    start = PhaseInstance(phase_ref="P", lattice=LatticeParams(5.02, 5.02, 5.02), scale=1.0)
    return backend, series, start


def test_acceptance_bic_tie_resolved_by_real_curvature_laplace():
    # 【テスト目的 (Issue #76 受け入れ基準 1)】: bic 一次では僅差 (|ΔΣbic|<閾値) の真の二相データを、
    #   実曲率 Laplace (物理尤度 + JᵀJ + restraint 由来事前分布) が two_phase (真実) に確定させる。
    #   v1 サロゲートでは構造的に不可能だった「僅差の解消」の実証。
    backend, series, start = _two_phase_close_tie_setup()
    config = DiscriminationConfig(
        multistart=MultistartConfig(n_starts=2), nested_arbitration=ArbitrationConfig()
    )

    result = discriminate_interval(
        backend, series, (0, 2), (start,),
        config=config, nested_backend=_LaplaceOnlyNestedBackend(),
    )

    # bic 一次は僅差だった (発動条件の確認 — これが無いと「元々判別できていた」ことになる)
    assert abs(result.delta_evidence) < 10.0
    # 実曲率 Laplace が真実 (two_phase) へ確定させた
    assert result.verdict == "two_phase"
    assert result.adjudicated_by == "laplace"
    assert result.nested_delta_evidence is not None
    assert result.nested_delta_evidence >= 10.0  # BIC 等価スケールで閾値以上 🔵
    # 暫定裁定でも close_competitor の人間確認要求は維持される (FR-403)
    assert any("としました" in m for m in result.escalations)


def test_acceptance_case_is_deterministic():
    # 【テスト目的 (Issue #76 受け入れ基準 2)】: Laplace 経路 (サンプラ不使用) はビット同一の決定論。
    def _run() -> DiscriminationResult:
        backend, series, start = _two_phase_close_tie_setup()
        config = DiscriminationConfig(
            multistart=MultistartConfig(n_starts=2), nested_arbitration=ArbitrationConfig()
        )
        return discriminate_interval(
            backend, series, (0, 2), (start,),
            config=config, nested_backend=_LaplaceOnlyNestedBackend(),
        )

    assert _run() == _run()


@pytest.mark.nested
def test_acceptance_real_dynesty_agrees_in_sign():
    # 【テスト目的 (Issue #76 受け入れ基準 1/2)】: 実 dynesty (物理尤度・seed 固定・logz_err 併記) でも
    #   同符号 (two_phase 優位, Δ>0) で裁定できる。予算 (maxcall) は NFR-103 打ち切り安全弁。
    if importlib.util.find_spec("dynesty") is None:
        pytest.skip("dynesty 未導入")

    backend, series, start = _two_phase_close_tie_setup()
    config = DiscriminationConfig(
        multistart=MultistartConfig(n_starts=2), nested_arbitration=ArbitrationConfig()
    )
    real_nested = NestedBackend(config=NestedConfig(n_live=25, max_calls=3000, seed=0))

    result = discriminate_interval(
        backend, series, (0, 2), (start,),
        config=config, nested_backend=real_nested,
    )

    # 完走すれば nested、時間上限等で縮退すれば laplace — いずれも実曲率経路で Δ>0 (two_phase 優位)
    assert result.adjudicated_by in ("nested", "laplace")
    assert result.nested_delta_evidence is not None
    assert result.nested_delta_evidence > 0.0
