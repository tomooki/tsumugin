"""TASK-0038 joint/model + joint/weights の失敗テスト (TDD Red)。

対象実装 (未実装):
- ``src/tsumugin/joint/model.py``: ``JointHistogram`` / ``JointRefinementModel`` /
  ``PerHistogramMetrics`` / ``JointRefinementResult`` (全 frozen dataclass)
- ``src/tsumugin/joint/weights.py``: ``HistogramWeighting`` (mode / empirical_weights /
  ``resolve`` / ``sigma_source``)
- ``src/tsumugin/joint/__init__.py``: 上記 5 シンボルの re-export (__all__ 昇順)

契約は ``docs/design/m4-joint-mcp/interfaces.py`` の joint/model・joint/weights 節に依拠。
np.ndarray を持つ frozen dataclass の等価比較は曖昧になるため、本テストはフィールド個別
または ``np.array_equal`` で検証する (既存 ``RefinementModel`` の流儀に合わせ eq=True のまま)。
frozen 検証は ``FrozenInstanceError``、近似は ``pytest.approx``。

TASK-0038.md 完了条件・TC-402/TC-403 系に 1:1 対応する。未実装のため import が
collection 時に失敗し、全テストがエラー(=失敗)になる想定 (Red フェーズ)。
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from tsumugin.joint import (
    HistogramWeighting,
    JointHistogram,
    JointRefinementModel,
    JointRefinementResult,
    PerHistogramMetrics,
)
from tsumugin.backends.base import RefinementResult
from tsumugin.model import LatticeParams, PhaseInstance


# ---------------------------------------------------------------------------
# ヘルパ
# ---------------------------------------------------------------------------


def _phase(ref: str = "p0") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a=5.0, b=5.0, c=5.0))


def _hist(probe: str = "xray") -> JointHistogram:
    return JointHistogram(
        two_theta=np.array([10.0, 20.0, 30.0]),
        intensity=np.array([100.0, 200.0, 150.0]),
        probe=probe,
    )


def _agg() -> RefinementResult:
    return RefinementResult(
        phases=(_phase(),),
        chi2=1.5,
        rwp=0.08,
        n_obs=3,
        n_params=1,
        converged=True,
        n_cycles=5,
    )


# ---------------------------------------------------------------------------
# 1. JointHistogram — 生成 / 既定値 / frozen
# ---------------------------------------------------------------------------


def test_joint_histogram_construction_holds_arrays_and_defaults():
    # 【目的】: JointHistogram が生成でき、配列と既定値を保持する (TC-402-01) 🔵
    tt = np.array([10.0, 20.0, 30.0])
    it = np.array([100.0, 200.0, 150.0])
    hist = JointHistogram(two_theta=tt, intensity=it)

    assert np.array_equal(hist.two_theta, tt)  # 【確認】: 2θ 軸を保持 🔵
    assert np.array_equal(hist.intensity, it)  # 【確認】: 強度を保持 🔵
    assert hist.probe == "xray"  # 【確認】: probe 既定は xray 🔵
    assert hist.weights is None  # 【確認】: weights 既定は None 🔵
    assert hist.hist_weight == pytest.approx(1.0)  # 【確認】: hist_weight 既定 1.0 🔵
    assert hist.bank_id is None  # 【確認】: bank_id 既定は None 🔵


def test_joint_histogram_explicit_fields():
    # 【目的】: 全フィールド明示指定が保持される 🔵
    w = np.array([1.0, 1.0, 1.0])
    hist = JointHistogram(
        two_theta=np.array([1.0]),
        intensity=np.array([2.0]),
        probe="neutron_tof",
        weights=w,
        hist_weight=0.5,
        bank_id=2,
    )
    assert hist.probe == "neutron_tof"
    assert np.array_equal(hist.weights, w)
    assert hist.hist_weight == pytest.approx(0.5)
    assert hist.bank_id == 2


def test_joint_histogram_is_frozen():
    # 【目的】: frozen dataclass で属性再代入不可 🔵
    hist = _hist()
    with pytest.raises(FrozenInstanceError):
        hist.hist_weight = 2.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 2. JointRefinementModel — 構造共有 / ヒスト独立の分離保持 (TC-402-01)
# ---------------------------------------------------------------------------


def test_joint_model_separates_shared_and_per_histogram_free_params():
    # 【目的】: shared_free_params とヒスト独立 per_histogram_free_params を分離保持 (TC-402-01) 🔵
    phases = (_phase("a"), _phase("b"))
    hists = (_hist("xray"), _hist("neutron_cw"))
    shared = frozenset({"phase0.lattice.a"})
    per = {0: frozenset({"phase0.scale"}), 1: frozenset({"phase1.scale", "bg"})}

    model = JointRefinementModel(
        phases=phases,
        histograms=hists,
        shared_free_params=shared,
        per_histogram_free_params=per,
    )

    assert model.shared_free_params == shared  # 【確認】: 共有 free をそのまま保持 🔵
    assert model.per_histogram_free_params[0] == frozenset({"phase0.scale"})  # 🔵
    assert model.per_histogram_free_params[1] == frozenset({"phase1.scale", "bg"})  # 🔵
    # 【確認】: 共有と独立が混ざらない (分離保持) 🔵
    assert "phase0.scale" not in model.shared_free_params
    assert "phase0.lattice.a" not in model.per_histogram_free_params[0]


def test_joint_model_defaults_empty_free_params():
    # 【目的】: 既定で共有 free は空集合・ヒスト独立は空 Mapping 🔵
    model = JointRefinementModel(phases=(_phase(),), histograms=(_hist(),))
    assert model.shared_free_params == frozenset()
    assert dict(model.per_histogram_free_params) == {}


def test_joint_model_preserves_histogram_input_order():
    # 【目的】: histograms が入力順で保存される (REQ-402/TC-402-01) 🔵
    h0, h1, h2 = _hist("xray"), _hist("neutron_cw"), _hist("neutron_tof")
    model = JointRefinementModel(phases=(_phase(),), histograms=(h0, h1, h2))
    assert model.histograms == (h0, h1, h2)  # 【確認】: 順序保存 🔵
    assert [h.probe for h in model.histograms] == ["xray", "neutron_cw", "neutron_tof"]


def test_joint_model_is_frozen():
    # 【目的】: frozen dataclass 🔵
    model = JointRefinementModel(phases=(_phase(),), histograms=(_hist(),))
    with pytest.raises(FrozenInstanceError):
        model.phases = ()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 3. PerHistogramMetrics — 生成 / frozen / sigma_source 明示 (TC-403-03)
# ---------------------------------------------------------------------------


def test_per_histogram_metrics_construction():
    # 【目的】: PerHistogramMetrics が生成でき σ 由来を明示保持 (TC-403-03/NFR-107) 🔵
    m = PerHistogramMetrics(
        hist_index=1,
        probe="neutron_cw",
        rwp=0.07,
        chi2=1.2,
        scale=0.9,
        sigma_source="hist_weight",
    )
    assert m.hist_index == 1
    assert m.probe == "neutron_cw"
    assert m.rwp == pytest.approx(0.07)
    assert m.chi2 == pytest.approx(1.2)
    assert m.scale == pytest.approx(0.9)
    assert m.sigma_source == "hist_weight"


def test_per_histogram_metrics_accepts_inf_chi2():
    # 【目的】: 失敗ヒストは chi2=inf を保持できる (EDGE-001) 🔵
    m = PerHistogramMetrics(
        hist_index=0,
        probe="xray",
        rwp=float("inf"),
        chi2=float("inf"),
        scale=1.0,
        sigma_source="covariance",
    )
    assert m.chi2 == float("inf")


def test_per_histogram_metrics_is_frozen():
    m = PerHistogramMetrics(
        hist_index=0, probe="xray", rwp=0.1, chi2=1.0, scale=1.0, sigma_source="covariance"
    )
    with pytest.raises(FrozenInstanceError):
        m.rwp = 0.2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 4. JointRefinementResult — aggregate は RefinementResult / 順序 / frozen (TC-402-01)
# ---------------------------------------------------------------------------


def test_joint_result_aggregate_is_refinement_result():
    # 【目的】: aggregate が RefinementResult で rank/evidence 経路と互換 (REQ-006/D1) 🔵
    agg = _agg()
    result = JointRefinementResult(aggregate=agg, per_histogram=())
    assert isinstance(result.aggregate, RefinementResult)
    assert result.aggregate is agg
    assert result.warnings == ()  # 【確認】: warnings 既定は空 tuple 🔵


def test_joint_result_preserves_per_histogram_input_order():
    # 【目的】: per_histogram が入力順で保存される (REQ-402) 🔵
    m0 = PerHistogramMetrics(
        hist_index=0, probe="xray", rwp=0.1, chi2=1.0, scale=1.0, sigma_source="covariance"
    )
    m1 = PerHistogramMetrics(
        hist_index=1, probe="neutron_cw", rwp=0.2, chi2=2.0, scale=0.8,
        sigma_source="hist_weight",
    )
    result = JointRefinementResult(
        aggregate=_agg(), per_histogram=(m0, m1), warnings=("hist1: empirical",)
    )
    assert result.per_histogram == (m0, m1)  # 【確認】: 順序保存 🔵
    assert [m.hist_index for m in result.per_histogram] == [0, 1]
    assert result.warnings == ("hist1: empirical",)


def test_joint_result_is_frozen():
    result = JointRefinementResult(aggregate=_agg(), per_histogram=())
    with pytest.raises(FrozenInstanceError):
        result.warnings = ("x",)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 5. HistogramWeighting.resolve — statistical (TC-403-01)
# ---------------------------------------------------------------------------


def test_histogram_weighting_default_is_statistical():
    # 【目的】: 既定 mode は statistical / empirical_weights 空 (TC-403-01) 🔵
    w = HistogramWeighting()
    assert w.mode == "statistical"
    assert dict(w.empirical_weights) == {}


def test_resolve_statistical_returns_all_ones():
    # 【目的】: statistical は全ヒスト 1.0 を返す (TC-403-01/REQ-008) 🔵
    model = JointRefinementModel(
        phases=(_phase(),), histograms=(_hist("xray"), _hist("neutron_cw"), _hist("neutron_tof"))
    )
    weights = HistogramWeighting().resolve(model)
    assert weights == (1.0, 1.0, 1.0)  # 【確認】: 全 1.0 🔵


def test_histogram_weighting_is_frozen():
    w = HistogramWeighting()
    with pytest.raises(FrozenInstanceError):
        w.mode = "empirical"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 6. HistogramWeighting.resolve — empirical 上書き (TC-403-02)
# ---------------------------------------------------------------------------


def test_resolve_empirical_overrides_specified_indices():
    # 【目的】: empirical は指定 index を上書きし寄与を変える (TC-403-02/REQ-301) 🔵
    model = JointRefinementModel(
        phases=(_phase(),), histograms=(_hist("xray"), _hist("neutron_cw"), _hist("neutron_tof"))
    )
    w = HistogramWeighting(mode="empirical", empirical_weights={0: 2.0, 2: 0.5})
    weights = w.resolve(model)
    assert weights == (2.0, 1.0, 0.5)  # 【確認】: 指定は上書き・未指定は 1.0 🔵


def test_resolve_empirical_unspecified_defaults_to_one():
    # 【目的】: empirical で未指定 index は 1.0 (TC-403-02) 🔵
    model = JointRefinementModel(
        phases=(_phase(),), histograms=(_hist("xray"), _hist("neutron_cw"))
    )
    w = HistogramWeighting(mode="empirical", empirical_weights={})
    assert w.resolve(model) == (1.0, 1.0)


def test_resolve_is_deterministic_input_order():
    # 【目的】: resolve は決定論順 (入力ヒスト順) でビット同一 (REQ-402) 🔵
    model = JointRefinementModel(
        phases=(_phase(),),
        histograms=(_hist("xray"), _hist("neutron_cw"), _hist("neutron_tof"), _hist("xray")),
    )
    # dict 反復順に依存しないことを、逆順キー挿入で確認する
    w = HistogramWeighting(mode="empirical", empirical_weights={3: 0.3, 1: 0.7, 0: 0.9})
    first = w.resolve(model)
    second = w.resolve(model)
    assert first == second  # 【確認】: 再実行でビット同一 🔵
    assert first == (0.9, 0.7, 1.0, 0.3)  # 【確認】: 入力順 (index 昇順) タプル 🔵


# ---------------------------------------------------------------------------
# 7. HistogramWeighting.sigma_source (TC-403-03)
# ---------------------------------------------------------------------------


def test_sigma_source_statistical_is_covariance():
    # 【目的】: statistical は covariance を返す (TC-403-03/NFR-107) 🔵
    w = HistogramWeighting()
    assert w.sigma_source(0) == "covariance"
    assert w.sigma_source(5) == "covariance"


def test_sigma_source_empirical_specified_is_hist_weight():
    # 【目的】: empirical で当該 index に重み指定ありなら hist_weight (TC-403-03) 🔵
    w = HistogramWeighting(mode="empirical", empirical_weights={0: 2.0, 2: 0.5})
    assert w.sigma_source(0) == "hist_weight"
    assert w.sigma_source(2) == "hist_weight"


def test_sigma_source_empirical_unspecified_is_covariance():
    # 【目的】: empirical でも重み未指定 index は covariance (統計 σ のまま) 🔵
    w = HistogramWeighting(mode="empirical", empirical_weights={0: 2.0})
    assert w.sigma_source(1) == "covariance"
