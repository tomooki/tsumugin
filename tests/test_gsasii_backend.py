from __future__ import annotations

import numpy as np
import pytest

from tsumugin.backends.base import RefinementModel, param_name
from tsumugin.backends.gsasii import GSASIIBackend, _strip_sigma, gsasii_available
from tsumugin.errors import GSASUnavailableError
from tsumugin.model import LatticeParams, PhaseInstance


def _phase(a: float = 4.0, scale: float = 1.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=scale)


def _grid() -> np.ndarray:
    return np.arange(20.0, 80.0, 0.05)


def test_gsasii_available_returns_bool_without_raising():
    result = gsasii_available()
    assert isinstance(result, bool)


def test_backend_raises_when_unavailable():
    if gsasii_available():
        pytest.skip("GSAS-II is installed; unavailable path not exercised")
    with pytest.raises(GSASUnavailableError):
        GSASIIBackend()


@pytest.mark.gsas
def test_simulate_produces_nontrivial_pattern():
    backend = GSASIIBackend()
    tt = _grid()
    y = backend.simulate((_phase(a=4.0, scale=1.0),), tt)
    assert y.shape == tt.shape
    assert np.all(np.isfinite(y))
    # diffraction peaks rise well above the flat background
    assert y.max() > 5 * max(np.median(y), 1e-9)


@pytest.mark.gsas
def test_refine_noop_returns_metrics():
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=1.0)
    y = backend.simulate((truth,), tt)
    result = backend.refine(
        RefinementModel(phases=(truth,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    assert result.n_params == 0
    assert result.rwp >= 0.0
    assert result.n_obs == tt.size


@pytest.mark.gsas
def test_refine_scale_improves_fit():
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=2.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.0, scale=0.5)
    noop = backend.refine(
        RefinementModel(phases=(start,), free_params=frozenset(), two_theta=tt, intensity=y)
    )
    fitted = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "scale")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert fitted.rwp < noop.rwp
    assert fitted.n_params >= 1
    assert fitted.phases[0].scale != start.scale  # scale actually moved


@pytest.mark.gsas
def test_refine_lattice_recovers_cell():
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=1.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.01, scale=1.0)  # slightly off
    fitted = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "lattice.a")}),
            two_theta=tt,
            intensity=y,
        )
    )
    assert fitted.phases[0].lattice.a == pytest.approx(4.0, abs=0.005)


@pytest.mark.gsas
def test_refine_lattice_populates_covariance_sigma():
    # 【テスト目的】: 格子 a を解放すると G2Phase.get_cell_and_esd() 由来の共分散 σ が
    #   LatticeParams.sigma["a"] に populate され、sigma_source="covariance" になることを
    #   確認 (Issue #66 / FR-306 / NFR-107)。
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=1.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.01, scale=1.0)
    fitted = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "lattice.a")}),
            two_theta=tt,
            intensity=y,
        )
    )
    lattice = fitted.phases[0].lattice
    assert lattice.sigma_source == "covariance"  # 【確認内容】: 共分散由来を明示 🔵
    assert "a" in lattice.sigma  # 【確認内容】: 解放した a の esd が populate される 🔵
    assert lattice.sigma["a"] > 0.0
    assert lattice.sigma["a"] < 1.0  # 【確認内容】: 妥当なオーダー (Å 未満) 🟡


@pytest.mark.gsas
def test_refine_without_lattice_free_leaves_gsas_sigma_empty():
    # 【テスト目的】: 格子未解放 (scale のみ) では sigma が空・sigma_source="" のまま
    #   縮退することを確認 (fail-loud しない / 非回帰)。
    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=2.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.0, scale=0.5)
    fitted = backend.refine(
        RefinementModel(
            phases=(start,),
            free_params=frozenset({param_name(0, "scale")}),
            two_theta=tt,
            intensity=y,
        )
    )
    lattice = fitted.phases[0].lattice
    assert lattice.sigma == {}  # 【確認内容】: 格子非解放は空 dict 🔵
    assert lattice.sigma_source == ""  # 【確認内容】: 由来も未設定 🔵


@pytest.mark.gsas
def test_pipeline_ranks_hypotheses_on_gsasii_backend():
    """M0 受け入れ機能 (多仮説ランキング) が実バックエンドで動くことの契約。"""
    from tsumugin.pipeline import analyze_single_pattern

    backend = GSASIIBackend()
    tt = _grid()
    truth = (_phase(a=4.0, scale=2.0),)
    y = backend.simulate(truth, tt)

    good = (_phase(a=4.01, scale=1.0),)   # 正しい構造、初期値ずれ
    bad = (_phase(a=5.3, scale=1.0),)     # 誤った格子
    result = analyze_single_pattern(tt, y, [good, bad], backend=backend)

    assert len(result.ranked) == 2
    top = result.ranked[0]
    assert top.hypothesis.phases[0].lattice.a == pytest.approx(4.0, abs=0.02)
    assert top.probability > result.ranked[1].probability
    assert result.ledger.verify()


# ---------------------------------------------------------------------------
# レビュー ラウンド2 指摘 3: _cell_sigma の esd 失敗時に検証済み cell を破棄しないこと
# ---------------------------------------------------------------------------


def test_cell_sigma_esd_failure_keeps_validated_cell():
    # 【テスト目的】: get_cell_and_esd() の cell 検証には成功するが esd 抽出側で例外が
    #   出た場合に、検証済み cell まで巻き添えに捨てないことを確認する
    #   (旧実装は単一 try で包んでいたため cell も (None, {}, "") へ縮退し、呼び出し側が
    #   get_cell() を再呼び出しする無駄が生じていた)。
    # 【実装方針】: _cell_sigma は self を一切参照しないため、GSAS-II 未導入環境でも
    #   GSASIIBackend インスタンス化なしに unbound で直接呼び出せる (numpy-only テスト)。
    # 🔵 信頼性: レビュー指摘 (esd 失敗時 cell 破棄) の再現防止

    class _BadEsd:
        def get(self, key):  # noqa: ARG002 - duck-typed esd 引数
            raise RuntimeError("esd extraction failure")

    class _FakePhase:
        def get_cell_and_esd(self):
            raw_cell = {
                "length_a": 4.01,
                "length_b": 4.02,
                "length_c": 4.03,
                "angle_alpha": 90.0,
                "angle_beta": 90.0,
                "angle_gamma": 90.0,
            }
            return raw_cell, _BadEsd()

    cell, sigma, source = GSASIIBackend._cell_sigma(None, _FakePhase())

    assert cell is not None  # 【確認内容】: 検証済み cell は破棄されない 🔵
    assert cell["length_a"] == pytest.approx(4.01)
    assert cell["length_c"] == pytest.approx(4.03)
    assert sigma == {}  # 【確認内容】: esd 抽出失敗なので σ は空 🔵
    assert source == ""


def test_cell_sigma_outer_failure_returns_none_cell():
    # 【テスト目的】: get_cell_and_esd() 自体 (cell 検証) が失敗する場合は、従来どおり
    #   cell=None (呼び出し側 get_cell() フォールバック) へ縮退することを確認する (非回帰)。
    # 🔵 信頼性: 分割後も外側 try の縮退挙動が保たれることの確認

    class _FakePhaseBroken:
        def get_cell_and_esd(self):
            raise RuntimeError("cell extraction failure")

    cell, sigma, source = GSASIIBackend._cell_sigma(None, _FakePhaseBroken())

    assert cell is None  # 【確認内容】: cell 取得不能は None (フォールバック標識) 🔵
    assert sigma == {}
    assert source == ""


# ---------------------------------------------------------------------------
# レビュー ラウンド2 指摘 4: GSAS 例外経路の σ 素通り防止 (_strip_sigma)
# ---------------------------------------------------------------------------


def test_strip_sigma_clears_only_phases_with_populated_sigma():
    # 【テスト目的】: sigma/sigma_source が非空の相のみ {}/"" に置換され、既に空の相は
    #   変更されないことを確認する (numpy-only, GSAS 不要)。
    # 🔵 信頼性: レビュー指摘「do_refinements 失敗分岐で古い σ が chi2=inf 仮説に素通りする」対応

    stale = LatticeParams(5.0, 5.0, 5.0, sigma={"a": 0.1}, sigma_source="covariance")
    p_with_sigma = PhaseInstance(phase_ref="A", lattice=stale)
    p_without_sigma = PhaseInstance(phase_ref="B", lattice=LatticeParams(4.0, 4.0, 4.0))

    out = _strip_sigma((p_with_sigma, p_without_sigma))

    assert out[0].lattice.sigma == {}  # 【確認内容】: 非空だった相は剥離される 🔵
    assert out[0].lattice.sigma_source == ""
    assert out[0].phase_ref == "A"  # 【確認内容】: sigma 以外のフィールドは保持 🔵
    assert out[1].lattice.sigma == {}  # 【確認内容】: 元々空の相も空のまま (非回帰) 🔵
    assert out[1].lattice.sigma_source == ""


def test_strip_sigma_returns_same_tuple_when_all_already_empty():
    # 【テスト目的】: 全相の sigma/sigma_source が既に空なら、同一タプルをそのまま返す
    #   (無駄な複製を避ける最適化)。
    # 🔵 信頼性: strip_lattice_sigma docstring の契約に依拠

    p1 = PhaseInstance(phase_ref="A", lattice=LatticeParams(5.0, 5.0, 5.0))
    p2 = PhaseInstance(phase_ref="B", lattice=LatticeParams(4.0, 4.0, 4.0))
    phases = (p1, p2)

    out = _strip_sigma(phases)

    assert out is phases  # 【確認内容】: 同一オブジェクト (複製されない) 🔵


@pytest.mark.gsas
def test_refine_failure_strips_stale_sigma_from_returned_phases(monkeypatch):
    # 【テスト目的】: GSAS-II 側の最小二乗が失敗 (do_refinements が例外) した場合、入力相に
    #   残る古い σ が chi2=inf の結果へ素通りしないことを、実際の refine() 例外分岐配線を
    #   通して end-to-end 確認する (単体は numpy-only テストで既に検証済み)。
    # 【実装方針】: _build_project を monkeypatch し、do_refinements が必ず例外を送出する
    #   偽 gpx を注入することで、実データ/実精密化なしに except 分岐を確実に踏む。
    # 🔵 信頼性: レビュー指摘「do_refinements 失敗分岐で古い σ が chi2=inf 仮説に素通りする」対応

    backend = GSASIIBackend()
    stale = LatticeParams(4.0, 4.0, 4.0, sigma={"a": 0.05}, sigma_source="covariance")
    phases = (PhaseInstance(phase_ref="P", lattice=stale, scale=1.0),)

    class _FailingGpx:
        def __init__(self) -> None:
            self.data = {"Controls": {"data": {}}}

        def do_refinements(self, *_args, **_kwargs):
            raise RuntimeError("synthetic do_refinements failure")

    def _fake_build_project(self, gpx_path, work_dir, phases_arg, two_theta, intensity, weights):
        return _FailingGpx(), None, []

    monkeypatch.setattr(GSASIIBackend, "_build_project", _fake_build_project)

    tt = _grid()
    y = np.ones_like(tt)
    result = backend.refine(
        RefinementModel(
            phases=phases,
            free_params=frozenset({param_name(0, "lattice.a")}),
            two_theta=tt,
            intensity=y,
        )
    )

    assert result.chi2 == float("inf")  # 【確認内容】: 失敗は chi2=inf へ変換 🔵
    assert result.phases[0].lattice.sigma == {}  # 【確認内容】: 古い σ が素通りしない 🔵
    assert result.phases[0].lattice.sigma_source == ""


@pytest.mark.gsas
def test_staged_engine_runs_on_gsasii_backend():
    """M0 パイプラインの中核 (段階解放+ガード) が実バックエンドでも回ることの契約。"""
    from tsumugin.refinement.staged import StagedRefinementEngine
    from tsumugin.store.ledger import Ledger
    from tsumugin.store.snapshot import SnapshotStore

    backend = GSASIIBackend()
    tt = _grid()
    truth = _phase(a=4.0, scale=2.0)
    y = backend.simulate((truth,), tt)

    start = _phase(a=4.01, scale=1.0)
    ledger = Ledger()
    engine = StagedRefinementEngine(backend, SnapshotStore(ledger), ledger)
    report = engine.run((start,), tt, y)

    assert report.escalated is False
    assert report.metrics.rwp < 20.0
    assert report.final_phases[0].lattice.a == pytest.approx(4.0, abs=0.01)
    assert ledger.verify()
