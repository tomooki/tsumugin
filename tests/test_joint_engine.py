"""TASK-0039 joint/engine の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/joint/engine.py``: ``refine_joint(backend, model, *, weighting,
  max_cycles=20, ledger=None) -> RefinementResult`` と
  ``refine_joint_detailed(...) -> JointRefinementResult``
- ``src/tsumugin/joint/__init__.py``: 上記 2 シンボルの re-export (__all__ 昇順)

契約は ``docs/design/m4-joint-mcp/interfaces.py`` の joint/engine 節に依拠。
完了条件 6 項目 (TC-402-02〜05 / EDGE-001 / REQ-005) に 1:1 対応する。

SimulatedBackend 経路は各ヒストを ``backend.refine`` (ヒスト独立 free) で精密化し
χ² を合算する。合成データは既存 ``test_simulated_backend.py`` の真値回収パターンを踏襲し、
乱数種固定 (SimulatedBackend は乱数を使わない) で決定論を担保する。
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from tsumugin.backends.base import RefinementResult, param_name
from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.joint import (
    HistogramWeighting,
    JointHistogram,
    JointRefinementModel,
    JointRefinementResult,
    refine_joint,
    refine_joint_detailed,
)
from tsumugin.model import LatticeParams, PhaseInstance
from tsumugin.store.ledger import Ledger


# ---------------------------------------------------------------------------
# ヘルパ (test_simulated_backend.py の真値回収パターンを踏襲)
# ---------------------------------------------------------------------------


def _phase(a: float = 5.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(15.0, 80.0, 0.02)


def _two_histogram_model(
    *,
    truth_a: float = 5.03,
    start_a: float = 5.0,
    scales: tuple[float, float] = (2.0, 3.0),
) -> tuple[JointRefinementModel, SimulatedBackend]:
    """2 ヒスト joint モデルを構築する。

    共有構造 (lattice.a) は真値 ``truth_a``・初期値 ``start_a`` からずらして解放し、
    各ヒストは独立 scale を持つ。両ヒストは同じ共有相の真値から生成し、χ² 合算で
    共有 lattice.a が回収されることを検証できるようにする。
    """
    backend = SimulatedBackend(peak_fwhm=0.2)
    tt = _grid()
    # 真の共有相 (lattice.a = truth_a)。各ヒストの観測は相の scale を変えて生成。
    truth0 = _phase(a=truth_a, scale=scales[0])
    truth1 = _phase(a=truth_a, scale=scales[1])
    y0 = backend.simulate((truth0,), tt)
    y1 = backend.simulate((truth1,), tt)

    hists = (
        JointHistogram(two_theta=tt, intensity=y0, probe="xray"),
        JointHistogram(two_theta=tt, intensity=y1, probe="neutron_cw"),
    )
    # 共有相は lattice.a を start_a にずらし、scale も初期化。
    shared_phase = _phase(a=start_a, scale=1.0)
    model = JointRefinementModel(
        phases=(shared_phase,),
        histograms=hists,
        shared_free_params=frozenset({param_name(0, "lattice.a")}),
        per_histogram_free_params={
            0: frozenset({param_name(0, "scale")}),
            1: frozenset({param_name(0, "scale")}),
        },
    )
    return model, backend


# ---------------------------------------------------------------------------
# (1) SimulatedBackend で 2 ヒスト χ² 合算 joint が収束し共有構造の真値回収 [TC-402-02]
# ---------------------------------------------------------------------------


def test_refine_joint_recovers_shared_structure_from_two_histograms():
    # 【目的】: 2 ヒスト χ² 合算 joint が収束し共有 lattice.a の真値を回収する (TC-402-02) 🔵
    model, backend = _two_histogram_model(truth_a=5.03, start_a=5.0)
    result = refine_joint(backend, model)

    assert isinstance(result, RefinementResult)  # 【確認】: 集約は RefinementResult 🔵
    assert result.converged  # 【確認】: 収束 🔵
    # 【確認】: 共有 lattice.a が真値 5.03 を回収 🔵
    assert result.phases[0].lattice.a == pytest.approx(5.03, abs=0.01)
    assert math.isfinite(result.chi2)


def test_refine_joint_chi2_is_weighted_sum_of_histograms():
    # 【目的】: 集約 chi2 = Σ (weight_k · chi2_k) (χ² 合算, D2) 🔵
    model, backend = _two_histogram_model()
    weighting = HistogramWeighting()  # statistical → 全ヒスト 1.0
    result = refine_joint(backend, model, weighting=weighting)
    detailed = refine_joint_detailed(backend, model, weighting=weighting)

    per_chi2 = sum(m.chi2 for m in detailed.per_histogram)
    assert result.chi2 == pytest.approx(per_chi2)


# ---------------------------------------------------------------------------
# (2) 集約が hist別 Rwp/scale と共有構造±σ を単一 RefinementResult へ [TC-402-03]
# ---------------------------------------------------------------------------


def test_aggregate_globals_carry_per_histogram_rwp_and_scale():
    # 【目的】: aggregate.globals に "hist{k}.rwp"/"hist{k}.scale" を格納 (REQ-006/TC-402-03) 🔵
    model, backend = _two_histogram_model()
    result = refine_joint(backend, model)

    for k in range(2):
        assert f"hist{k}.rwp" in result.globals  # 【確認】: ヒスト別 Rwp 🔵
        assert f"hist{k}.scale" in result.globals  # 【確認】: ヒスト別 scale 🔵
        assert math.isfinite(result.globals[f"hist{k}.rwp"])
        assert result.globals[f"hist{k}.scale"] > 0.0


def test_aggregate_recovers_per_histogram_scales():
    # 【目的】: ヒスト独立 scale が各ヒストの真値へ回収される (共有構造は χ² 和で更新) 🔵
    # 共有 lattice.a は真値一致で開始し、ヒスト独立 scale の回収を分離して検証する。
    model, backend = _two_histogram_model(truth_a=5.0, start_a=5.0, scales=(2.0, 3.0))
    result = refine_joint(backend, model)
    # 各ヒストは truth scale (2.0, 3.0) を独立回収する
    assert result.globals["hist0.scale"] == pytest.approx(2.0, rel=0.05)
    assert result.globals["hist1.scale"] == pytest.approx(3.0, rel=0.05)


# ---------------------------------------------------------------------------
# (3) refine_joint_detailed が aggregate + PerHistogramMetrics(入力順) を返す [REQ-402]
# ---------------------------------------------------------------------------


def test_refine_joint_detailed_returns_aggregate_and_per_histogram_in_order():
    # 【目的】: detailed が aggregate + PerHistogramMetrics(入力順) を返す (REQ-402) 🔵
    model, backend = _two_histogram_model()
    detailed = refine_joint_detailed(backend, model)

    assert isinstance(detailed, JointRefinementResult)
    assert isinstance(detailed.aggregate, RefinementResult)
    # 【確認】: per_histogram は入力順 (index 昇順) 🔵
    assert [m.hist_index for m in detailed.per_histogram] == [0, 1]
    assert [m.probe for m in detailed.per_histogram] == ["xray", "neutron_cw"]
    # 【確認】: aggregate は refine_joint と一致 (詳細ラッパ) 🔵
    plain = refine_joint(backend, model)
    assert detailed.aggregate.chi2 == pytest.approx(plain.chi2)
    assert detailed.aggregate.phases[0].lattice.a == pytest.approx(plain.phases[0].lattice.a)


def test_detailed_sigma_source_reflects_weighting():
    # 【目的】: PerHistogramMetrics.sigma_source が weighting.sigma_source に一致 (REQ-009) 🔵
    model, backend = _two_histogram_model()
    weighting = HistogramWeighting(mode="empirical", empirical_weights={1: 0.5})
    detailed = refine_joint_detailed(backend, model, weighting=weighting)

    assert detailed.per_histogram[0].sigma_source == "covariance"  # 未指定 → 統計 σ
    assert detailed.per_histogram[1].sigma_source == "hist_weight"  # 指定あり
    # 【確認】: σ 由来が warnings に明示される 🔵
    assert any("hist1" in w for w in detailed.warnings)


# ---------------------------------------------------------------------------
# (4) 1 ヒスト失敗 → chi2=inf 変換・非クラッシュ・warnings に index [TC-402-04/EDGE-001]
# ---------------------------------------------------------------------------


class _FailingSecondHistBackend:
    """2 番目のヒスト (index で判別できない) の refine で例外を送出するバックエンド。

    joint は各ヒストを個別 refine するため、呼び出し回数で 2 回目を失敗させる。
    """

    name = "failing"

    def __init__(self) -> None:
        self._delegate = SimulatedBackend(peak_fwhm=0.2)
        self._calls = 0

    def refine(self, model, *, max_cycles: int = 20) -> RefinementResult:
        self._calls += 1
        # 2 回目以降の呼び出し (= 2 番目のヒスト) で例外を送出
        if self._calls == 2:
            raise RuntimeError("synthetic refine failure")
        return self._delegate.refine(model, max_cycles=max_cycles)


def test_single_histogram_failure_propagates_inf_without_crash():
    # 【目的】: 1 ヒスト失敗を chi2=inf へ変換し joint 全体はクラッシュしない (EDGE-001/REQ-007) 🔵
    model, _ = _two_histogram_model()
    backend = _FailingSecondHistBackend()

    # 例外を投げず結果を返す
    result = refine_joint(backend, model, max_cycles=1)
    assert result.chi2 == float("inf")  # 【確認】: 集約 chi2=inf へ伝播 🔵
    # 【確認】: warnings に失敗ヒスト index (1) を明示 🔵
    assert any("hist1" in w or "index 1" in w or "1" in w for w in result.warnings)


def test_failure_marks_failing_histogram_chi2_inf_in_detailed():
    # 【目的】: detailed で失敗ヒストの chi2=inf、成功ヒストは有限 (EDGE-001) 🔵
    model, _ = _two_histogram_model()
    backend = _FailingSecondHistBackend()
    detailed = refine_joint_detailed(backend, model, max_cycles=1)

    assert detailed.per_histogram[0].chi2 != float("inf")  # 成功ヒスト
    assert detailed.per_histogram[1].chi2 == float("inf")  # 失敗ヒスト
    assert any("hist1" in w for w in detailed.warnings)


def test_backend_returning_inf_chi2_is_treated_as_failure():
    # 【目的】: 例外でなく chi2=inf を返すバックエンドも失敗として伝播する 🔵
    class _InfBackend:
        name = "inf"

        def __init__(self) -> None:
            self._delegate = SimulatedBackend(peak_fwhm=0.2)
            self._calls = 0

        def refine(self, model, *, max_cycles: int = 20) -> RefinementResult:
            self._calls += 1
            base = self._delegate.refine(model, max_cycles=max_cycles)
            if self._calls == 2:
                return RefinementResult(
                    phases=base.phases,
                    chi2=float("inf"),
                    rwp=float("inf"),
                    n_obs=base.n_obs,
                    n_params=base.n_params,
                    converged=False,
                    n_cycles=base.n_cycles,
                )
            return base

    model, _ = _two_histogram_model()
    result = refine_joint(_InfBackend(), model, max_cycles=1)
    assert result.chi2 == float("inf")


# ---------------------------------------------------------------------------
# (5) 2 回実行でビット同一 [TC-402-05/NFR-102]
# ---------------------------------------------------------------------------


def test_refine_joint_is_bit_identical_across_runs():
    # 【目的】: joint 一式が 2 回実行でビット同一 (NFR-102) 🔵
    model, backend = _two_histogram_model()
    r1 = refine_joint(backend, model)
    r2 = refine_joint(backend, model)

    assert r1.chi2 == r2.chi2  # 【確認】: chi2 ビット同一 🔵
    assert r1.rwp == r2.rwp  # 【確認】: rwp ビット同一 🔵
    assert r1.phases[0].lattice.a == r2.phases[0].lattice.a  # 共有構造ビット同一
    assert dict(r1.globals) == dict(r2.globals)  # globals ビット同一


def test_refine_joint_detailed_is_bit_identical_across_runs():
    # 【目的】: detailed も 2 回実行でビット同一 (NFR-102) 🔵
    model, backend = _two_histogram_model()
    d1 = refine_joint_detailed(backend, model)
    d2 = refine_joint_detailed(backend, model)

    assert d1.aggregate.chi2 == d2.aggregate.chi2
    for m1, m2 in zip(d1.per_histogram, d2.per_histogram):
        assert m1.chi2 == m2.chi2
        assert m1.rwp == m2.rwp
        assert m1.scale == m2.scale


# ---------------------------------------------------------------------------
# ledger 記録 (要所を追記記録)
# ---------------------------------------------------------------------------


def test_refine_joint_appends_to_ledger_when_provided():
    # 【目的】: ledger 非 None なら要所を追記記録しチェーン整合を保つ 🔵
    model, backend = _two_histogram_model()
    ledger = Ledger()
    refine_joint(backend, model, ledger=ledger)
    assert len(ledger.entries) > 0  # 【確認】: 追記された 🔵
    assert ledger.verify()  # 【確認】: ハッシュチェーン整合 🔵


# ---------------------------------------------------------------------------
# (6) @gsas smoke: GSASIIBackend 接続点が起動 [REQ-005]
# ---------------------------------------------------------------------------


@pytest.mark.gsas
def test_refine_joint_gsasii_smoke():
    # 【目的】: GSASIIBackend 接続点が起動し RefinementResult を返す (REQ-005) 🔵
    from tsumugin.backends.gsasii import GSASIIBackend

    backend = GSASIIBackend()
    tt = np.arange(20.0, 80.0, 0.05)
    truth = _phase(a=4.0, scale=1.0)
    y = backend.simulate((truth,), tt)
    hists = (
        JointHistogram(two_theta=tt, intensity=y, probe="xray"),
        JointHistogram(two_theta=tt, intensity=y, probe="xray"),
    )
    model = JointRefinementModel(
        phases=(_phase(a=4.0, scale=1.0),),
        histograms=hists,
        shared_free_params=frozenset(),
        per_histogram_free_params={0: frozenset(), 1: frozenset()},
    )
    result = refine_joint(backend, model, max_cycles=1)
    assert isinstance(result, RefinementResult)
    assert result.n_obs > 0


# ---------------------------------------------------------------------------
# F11: 0 ヒストグラムは沈黙成功でなく chi2=inf (非成功) へ落とす
# ---------------------------------------------------------------------------


def test_refine_joint_empty_histograms_returns_non_finite_failure():
    # 【F11】: histograms 空 (n_hist=0) は chi2=0/converged=True の成功ではなく chi2=inf の
    #   非成功結果を返し、warning を添えること (ガードレールに失敗として処理させる)。
    backend = SimulatedBackend(peak_fwhm=0.2)
    model = JointRefinementModel(
        phases=(_phase(),),
        histograms=(),
    )
    result = refine_joint(backend, model)
    assert not math.isfinite(result.chi2)
    assert result.converged is False
    assert result.warnings  # 空 histograms の warning が付く


# ---------------------------------------------------------------------------
# F12: empirical 重み下でも 2 仮説の BIC 比較順位が weighting に対し決定論・一貫
# ---------------------------------------------------------------------------


def test_empirical_weighting_bic_order_is_deterministic_and_consistent():
    # 【F12】: empirical (w≠1) weighting で 2 仮説を比較しても、集約 chi2 の大小関係が
    #   weighting に対し決定論・一貫であること (同一 weighting 下で順序保存)。
    weighting = HistogramWeighting(mode="empirical", empirical_weights={0: 2.0, 1: 0.5})

    # 良い仮説 (真値近い start_a) と悪い仮説 (真値から大きく外す) を同一 weighting で評価。
    good_model, backend = _two_histogram_model(truth_a=5.03, start_a=5.02)
    bad_model, _ = _two_histogram_model(truth_a=5.03, start_a=5.30)

    good1 = refine_joint(backend, good_model, weighting=weighting)
    good2 = refine_joint(backend, good_model, weighting=weighting)
    bad = refine_joint(backend, bad_model, weighting=weighting)

    # 決定論: 同入力・同 weighting でビット同一 chi2。
    assert good1.chi2 == good2.chi2
    # 一貫性: 良い仮説の集約 chi2 は悪い仮説より小さい (weighting 下でも順序保存)。
    assert good1.chi2 <= bad.chi2
