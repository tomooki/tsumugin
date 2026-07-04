"""TASK-0058 公開 API 統合 + M5 E2E (nested / MEM / OED 総仕上げ) の失敗テスト (TDD Red)。

対象実装: ``src/tsumugin/__init__.py`` への M5 公開シンボル re-export (nested/mem/oed の 40 シンボル)
と、公開 API 経由の nested 裁定 / MEM 解析 / OED 提案 / MCP の一気通貫 E2E。

Red の失敗機構: 本モジュール冒頭の ``from tsumugin import ...`` は M5 分がトップレベル未 re-export
のため collection 時に ImportError となり、本ファイルの全テストが失敗する
(``tests/test_m4_e2e.py`` と同一の Red 方針)。

方針:
- E2E は SimulatedBackend + モック MEMBackend で決定論・乱数不使用 (実サンプラ/実バイナリ不要)。
- nested は未導入前提で Laplace 縮退経路 (adjudicated_by ∈ {"nested","laplace"}) を許容する。
- コア import が numpy のみ (dynesty/pyboed なし) を find_spec 不在確認 + import 成功で担保する。
- 決定論は ``==`` ビット同一。
テストケース定義 (TC-514 系 / TC-515 系) に 1:1 対応する。
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

import tsumugin
import tsumugin.errors
import tsumugin.mem
import tsumugin.nested
import tsumugin.oed

# 【Red の失敗点】: M5 シンボルはトップレベル未 re-export のため、この import が collection 時に
#   ImportError となり本ファイルの全テストが失敗する想定。M0〜M4 分は既に re-export 済みだが、
#   M5 分を含む結合 import 文全体が失敗する。🔵
from tsumugin import (
    ArbitratedHypothesis,
    ArbitrationConfig,
    ArbitrationResult,
    BICBackend,
    BondPathDensity,
    CalibrationReport,
    CalibrationSample,
    DensityCrossSection,
    DysnomiaBackend,
    EvidenceProblem,
    HypothesisTreeSearch,
    Hypothesis,
    JointHistogram,
    LaplaceBackend,
    LatticeParams,
    Ledger,
    MEMApplicabilityReport,
    MEMBackend,
    MEMDensityMap,
    MEMInput,
    MEMResult,
    MEMRietveldConfig,
    MEMRietveldResult,
    NestedBackend,
    NestedConfig,
    NestedOutcome,
    NestedUnavailableError,
    OEDProposal,
    OEDUnavailableError,
    PhaseInstance,
    PriorSpec,
    ProblemAwareEvidenceBackend,
    Project,
    RefinementMetrics,
    ReliabilityBin,
    RestraintSpec,
    SimulatedBackend,
    SnapshotStore,
    StructureFactor,
    SynthesisContext,
    acquire,
    arbitrate,
    build_mem_input,
    build_prior_from_restraints,
    calibrate_by_backend,
    check_mem_applicability,
    expected_calibration_error,
    extract_structure_factors,
    propose_measurements,
    rank,
    reliability_diagram,
    run_mem_rietveld,
    run_mem_spot,
    verify_survivors,
)
from tsumugin.evidence.base import EvidenceResult
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.joint.engine import refine_joint_detailed
from tsumugin.joint.model import JointRefinementModel
from tsumugin.mcp.tools import AnalysisSession, run_mem, submit_analysis
from tsumugin.search.clustering import PhaseCandidate
from tsumugin.selection.engine import FinalSelectionEngine

# ---------------------------------------------------------------------------
# 共通テストデータ・前提
# ---------------------------------------------------------------------------

GRID = np.arange(15.0, 40.0, 0.05)

PHASE_A = PhaseInstance("A", LatticeParams(5.0, 5.0, 5.0))
PHASE_B = PhaseInstance("B", LatticeParams(6.0, 6.0, 6.0))

# 【M5 昇格契約】: 本タスクでトップレベルへ昇格する M5 公開面全体 (interfaces.py 公開 API 節)。🔵
_M5_PROMOTED_SYMBOLS = {
    # nested
    "ArbitrationConfig",
    "ArbitrationResult",
    "ArbitratedHypothesis",
    "CalibrationReport",
    "CalibrationSample",
    "EvidenceProblem",
    "LaplaceBackend",
    "NestedBackend",
    "NestedConfig",
    "NestedOutcome",
    "NestedUnavailableError",
    "PriorSpec",
    "ProblemAwareEvidenceBackend",
    "ReliabilityBin",
    "RestraintSpec",
    "arbitrate",
    "build_prior_from_restraints",
    "calibrate_by_backend",
    "expected_calibration_error",
    "reliability_diagram",
    # mem
    "BondPathDensity",
    "DensityCrossSection",
    "DysnomiaBackend",
    "MEMApplicabilityReport",
    "MEMBackend",
    "MEMDensityMap",
    "MEMInput",
    "MEMResult",
    "MEMRietveldConfig",
    "MEMRietveldResult",
    "StructureFactor",
    "build_mem_input",
    "check_mem_applicability",
    "extract_structure_factors",
    "run_mem_rietveld",
    "run_mem_spot",
    # oed
    "OEDProposal",
    "OEDUnavailableError",
    "acquire",
    "propose_measurements",
}


class _MockMEMBackend:
    """決定論的な MEMResult を返すモック MEMBackend (実バイナリ不要)。"""

    name = "mock-mem"

    def __init__(self, r_factors=None, min_densities=None):
        self._r = list(r_factors) if r_factors is not None else None
        self._min = list(min_densities) if min_densities is not None else None
        self.calls = 0

    def run(self, mem_input):
        i = self.calls
        self.calls += 1
        r = self._r[i] if self._r is not None and i < len(self._r) else 0.1
        min_d = self._min[i] if self._min is not None and i < len(self._min) else 0.0
        dm = MEMDensityMap(
            path=f"mock-{i}.grd",
            density_kind=mem_input.density_kind,
            grid_shape=mem_input.grid_shape,
            min_density=min_d,
            max_density=10.0,
        )
        return MEMResult(
            density_map=dm,
            cross_sections=(
                DensityCrossSection(
                    label="M1-M2",
                    dimension=1,
                    coordinates=np.array([0.0, 1.0]),
                    values=np.array([1.0, 2.0]),
                ),
            ),
            bond_paths=(
                BondPathDensity(
                    start_site="Na1", end_site="Na2", min_density=0.3, path_length=2.5
                ),
            ),
            r_factor=r,
        )


def _hyp(hid: str, *, chi2: float) -> Hypothesis:
    """metrics を持つ最小の Hypothesis (BIC = chi2 + k*ln(n_obs) を制御)。"""
    metrics = RefinementMetrics(rwp=5.0, gof=1.2, chi2=chi2, n_obs=1000, n_params=8)
    return Hypothesis(id=hid, phases=(), metrics=metrics)


def _problem(label: str = "") -> EvidenceProblem:
    """尤度 + 事前分布を持つ最小の EvidenceProblem。"""
    priors = (
        PriorSpec(param_name="phase0.lattice.a", kind="uniform", low=4.0, high=6.0),
        PriorSpec(param_name="phase0.occ.site", kind="uniform", low=0.0, high=1.0),
    )

    def log_likelihood(theta: np.ndarray) -> float:
        center = np.array([5.0, 0.5])
        return float(-0.5 * np.sum((np.asarray(theta) - center) ** 2))

    metrics = RefinementMetrics(rwp=5.0, gof=1.2, chi2=100.0, n_obs=1000, n_params=8)
    return EvidenceProblem(
        metrics=metrics, log_likelihood=log_likelihood, priors=priors, label=label
    )


def _joint_result_single():
    """単相 joint 検証済み結果 (build_mem_input / run_mem_rietveld 用)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    phases = (PHASE_A,)
    y = backend.simulate(phases, GRID)
    model = JointRefinementModel(
        phases=phases,
        histograms=(JointHistogram(two_theta=GRID, intensity=y, probe="xray"),),
        shared_free_params=frozenset({"phase0.scale"}),
    )
    return backend, phases, refine_joint_detailed(backend, model)


def _primary_search(ledger: Ledger | None = None):
    """プライマリ木探索 (生存仮説を含む SearchResult)。"""
    backend = SimulatedBackend(peak_fwhm=0.2)
    intensity = backend.simulate((PHASE_A,), GRID)
    search = HypothesisTreeSearch(backend, ledger=ledger)
    candidates = [PhaseCandidate(phase=PHASE_A), PhaseCandidate(phase=PHASE_B)]
    return search.search(GRID, intensity, candidates)


def _joint_histograms():
    backend = SimulatedBackend(peak_fwhm=0.2)
    y = backend.simulate((PHASE_A,), GRID)
    return (
        JointHistogram(two_theta=GRID, intensity=y, probe="xray"),
        JointHistogram(two_theta=GRID, intensity=y, probe="neutron_cw"),
    )


# ---------------------------------------------------------------------------
# 1. 公開 API 統合テスト (TC-514-05)
# ---------------------------------------------------------------------------


def test_m5_symbols_in_dunder_all_and_sorted():
    # 【テスト目的】: M5 40 シンボルが __all__ に在り昇順 + 後方互換維持 [TC-514-05/REQ-404]
    # 🔵 test_m4_symbols_in_dunder_all_and_sorted の手本に倣う
    exported = set(tsumugin.__all__)
    assert _M5_PROMOTED_SYMBOLS <= exported  # M5 シンボルが __all__ に包含
    assert list(tsumugin.__all__) == sorted(tsumugin.__all__)  # 完全昇順維持
    # M4 の代表シンボルが 1 つも削除されていない (後方互換)。
    for m4 in ("AnalysisSession", "create_mcp_server", "verify_survivors", "refine_joint"):
        assert m4 in exported
    # 8 ツール実処理関数はトップレベル __all__ に入れない (mcp 側公開)。
    for tool in ("submit_analysis", "run_mem"):
        assert tool not in exported


def test_m5_reexports_are_same_object():
    # 【テスト目的】: トップレベルのシンボルがサブパッケージ実体と同一 [REQ-404]
    assert arbitrate is tsumugin.nested.arbitrate
    assert calibrate_by_backend is tsumugin.nested.calibrate_by_backend
    assert LaplaceBackend is tsumugin.nested.LaplaceBackend
    assert build_mem_input is tsumugin.mem.build_mem_input
    assert run_mem_rietveld is tsumugin.mem.run_mem_rietveld
    assert MEMBackend is tsumugin.mem.MEMBackend
    assert propose_measurements is tsumugin.oed.propose_measurements
    assert acquire is tsumugin.oed.acquire
    assert OEDProposal is tsumugin.oed.OEDProposal
    assert NestedUnavailableError is tsumugin.errors.NestedUnavailableError
    assert OEDUnavailableError is tsumugin.errors.OEDUnavailableError


def test_m5_dunder_all_names_all_resolvable():
    # 【テスト目的】: __all__ の全名称が実属性として解決できる (dangling 名なし)
    for name in tsumugin.__all__:
        assert hasattr(tsumugin, name)


def test_m5_core_imports_numpy_only():
    # 【テスト目的】: コア import が numpy のみ (dynesty/pyboed なし) [TC-514-04/REQ-403]
    import sys  # noqa: PLC0415

    # 実サンプラ/OED バイナリが未導入なら、コア import で sys.modules に載らないこと。
    for optional in ("dynesty", "ultranest", "pyboed"):
        if importlib.util.find_spec(optional) is None:
            assert optional not in sys.modules
    # M5 コアシンボルは extra 無しで import 済み (冒頭 import)。
    assert callable(arbitrate)
    assert callable(propose_measurements)
    assert callable(build_mem_input)


# ---------------------------------------------------------------------------
# 2. nested 一気通貫 E2E (TC-515-01)
# ---------------------------------------------------------------------------


def test_m5_nested_pipeline_end_to_end():
    # 【テスト目的】: nested 一気通貫が完走する [TC-515-01]
    # 【内容】: bic 探索 → rank → 僅差競合抽出 → arbitrate (nested 再裁定・未導入は Laplace 縮退) →
    #   calibrate_by_backend → ledger verify
    ledger = Ledger()

    # 僅差競合を含む仮説群 (h1 best / h2 僅差 / h3 遠い)。
    hyps = (_hyp("h1", chi2=100.0), _hyp("h2", chi2=103.0), _hyp("h3", chi2=200.0))

    # bic 一次 rank で僅差競合を抽出する。
    ranked = rank(hyps, BICBackend())
    close_ids = {r.hypothesis.id for r in ranked if r.close_competitor}
    assert {"h1", "h2"} <= close_ids  # h1/h2 が僅差競合

    # arbitrate: 僅差競合のみ nested 再裁定 (未導入は Laplace 縮退)。
    problems = {h.id: _problem(h.id) for h in hyps}
    result = arbitrate(hyps, problems=problems, nested=NestedBackend(), ledger=ledger)
    assert isinstance(result, ArbitrationResult)
    assert result.nested_ids == ("h1", "h2")  # 僅差競合のみ・昇順
    by = {a.ranked.hypothesis.id: a.adjudicated_by for a in result.arbitrated}
    assert by["h1"] in ("nested", "laplace")
    assert by["h2"] in ("nested", "laplace")
    assert by["h3"] == "bic"  # 遠い仮説は bic 一次のまま

    # 確率較正: arbitrated 確率から CalibrationSample を組み backend 別に較正。
    samples = [
        CalibrationSample(
            predicted_probability=a.ranked.probability,
            correct=(a.ranked.hypothesis.id == "h1"),
            backend=("nested" if a.adjudicated_by in ("nested", "laplace") else "bic"),
        )
        for a in result.arbitrated
    ]
    reports = calibrate_by_backend(samples)
    assert all(isinstance(r, CalibrationReport) for r in reports)
    # ECE スカラは有限。
    for r in reports:
        assert expected_calibration_error(
            [s for s in samples if s.backend == r.backend]
        ) == pytest.approx(r.ece)

    # ledger 連鎖が無傷 (arbitration 記録を通しても)。
    assert ledger.verify() is True
    assert any(e.kind == "arbitration" for e in ledger.entries)
    # arbitrate は仮説を accepted 化しない (非破壊)。
    for h in hyps:
        assert h.status == "candidate"


def test_m5_nested_pipeline_deterministic():
    # 【テスト目的】: nested 一気通貫が 2 回でビット同一 (決定論)
    hyps = (_hyp("h1", chi2=100.0), _hyp("h2", chi2=103.0), _hyp("h3", chi2=200.0))
    problems = {h.id: _problem(h.id) for h in hyps}

    def _run():
        r = arbitrate(hyps, problems=problems, nested=NestedBackend())
        return [
            (a.ranked.hypothesis.id, a.ranked.evidence.value, a.adjudicated_by)
            for a in r.arbitrated
        ]

    assert _run() == _run()


# ---------------------------------------------------------------------------
# 3. MEM 一気通貫 E2E (TC-515-03)
# ---------------------------------------------------------------------------


def test_m5_mem_pipeline_end_to_end():
    # 【テスト目的】: MEM 一気通貫が完走する [TC-515-03]
    # 【内容】: joint 検証済み仮説 → build_mem_input → (モック MEMBackend) 密度/断面/最小密度 →
    #   check_mem_applicability 警告 → run_mem_rietveld 子スナップショット → ledger verify
    backend, phases, joint_result = _joint_result_single()

    # build_mem_input: 精密化済み joint 結果 → MEM 入力 (probe に応じた密度種別)。
    mem_input = build_mem_input(joint_result, "xray", grid_shape=(32, 32, 32))
    assert isinstance(mem_input, MEMInput)
    assert mem_input.density_kind == "electron"  # xray → 電子密度
    # 構造因子は (h,k,l) 昇順で決定論。
    factors = extract_structure_factors(joint_result)
    assert all(isinstance(sf, StructureFactor) for sf in factors)
    assert [sf.hkl for sf in factors] == sorted(sf.hkl for sf in factors)

    # モック MEMBackend で密度/断面/最小密度を得る。
    mem = _MockMEMBackend(r_factors=[0.3, 0.2, 0.1])
    single = mem.run(mem_input)
    assert isinstance(single, MEMResult)
    assert isinstance(single.density_map, MEMDensityMap)
    assert all(isinstance(cs, DensityCrossSection) for cs in single.cross_sections)
    assert all(isinstance(bp, BondPathDensity) for bp in single.bond_paths)

    # check_mem_applicability: 単相なので推奨 (警告なし・除外しない)。
    verification = verify_survivors(
        backend, _primary_search(), _joint_histograms(), evidence=BICBackend()
    )
    if verification.verified:
        target = verification.verified[0].id
        report = check_mem_applicability(verification, target)
        assert isinstance(report, MEMApplicabilityReport)
        # recommended に関わらず除外フィールドが無い (Dara 教訓)。
        import dataclasses  # noqa: PLC0415

        names = {f.name for f in dataclasses.fields(MEMApplicabilityReport)}
        assert not (names & {"excluded", "rejected"})

    # run_mem_rietveld: 有効化して各サイクルを子スナップショットとして追記。
    snaps = SnapshotStore()
    ledger = Ledger()
    result = run_mem_rietveld(
        backend,
        _MockMEMBackend(r_factors=[0.5, 0.4, 0.3, 0.2]),
        joint_result,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=2, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
        ledger=ledger,
    )
    assert isinstance(result, MEMRietveldResult)
    assert len(result.cycles) >= 1
    # 子スナップショット = サイクル数 (親不変・追記のみ, P2)。
    assert len(snaps.snapshots) == len(result.cycles)
    # 親 phases は不変。
    assert phases == (PHASE_A,)
    assert ledger.verify() is True


# ---------------------------------------------------------------------------
# 4. OED 一気通貫 E2E (TC-515-05)
# ---------------------------------------------------------------------------


def test_m5_oed_pipeline_end_to_end():
    # 【テスト目的】: OED 一気通貫が完走する [TC-515-05]
    # 【内容】: 僅差競合検出 → propose_measurements JSON (情報利得順) → ledger 追記のみ・非破壊
    #   (仮説 status 不変)
    ledger = Ledger()
    hyps = (_hyp("h1", chi2=100.0), _hyp("h2", chi2=103.0), _hyp("h3", chi2=200.0))
    ranked = rank(hyps, BICBackend())
    assert any(r.close_competitor for r in ranked)

    proposals = propose_measurements(ranked, ledger=ledger)
    assert len(proposals) >= 1
    assert all(isinstance(p, OEDProposal) for p in proposals)

    # JSON 化は情報利得順。
    rows = tsumugin.oed.proposals_to_json(proposals)
    gains = [row["estimated_information_gain"] for row in rows]
    non_none = [g for g in gains if g is not None]
    assert non_none == sorted(non_none, reverse=True)

    # 非破壊: 仮説 status 不変・ledger 追記のみ。
    for h in hyps:
        assert h.status == "candidate"
        assert h.accepted_by is None
    assert ledger.verify() is True
    assert any(e.kind == "oed_proposal" for e in ledger.entries)


def test_m5_oed_no_close_competitor_is_noop():
    # 【テスト目的】: 僅差競合が無ければ提案なし・ledger 不変 (EDGE-010)
    ledger = Ledger()
    hyps = (_hyp("h1", chi2=100.0), _hyp("h2", chi2=300.0), _hyp("h3", chi2=500.0))
    ranked = rank(hyps, BICBackend())
    proposals = propose_measurements(ranked, ledger=ledger)
    assert proposals == ()
    assert len(ledger.entries) == 0


# ---------------------------------------------------------------------------
# 5. MCP E2E (TC-515-06)
# ---------------------------------------------------------------------------


def test_m5_mcp_run_mem_end_to_end():
    # 【テスト目的】: MCP E2E [TC-515-06]
    # 【内容】: submit_analysis → 僅差競合 → run_mem (モック MEMBackend 実体化) → 密度マップ dict →
    #   ledger verify
    backend = SimulatedBackend(peak_fwhm=0.2)
    intensity = backend.simulate((PHASE_A,), GRID)
    ledger = Ledger()

    # joint 検証済み結果を session.verification に載せる (run_mem の入力元)。
    verification = verify_survivors(
        backend, _primary_search(), _joint_histograms(), evidence=BICBackend()
    )

    session = AnalysisSession(
        project=Project(id="proj-m5"),
        backend=backend,
        selection=FinalSelectionEngine(mode="agent", ledger=ledger),
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        evidence=BICBackend(),
        two_theta=GRID,
        intensity=intensity,
        verification=verification,
    )

    # submit_analysis (単一パターン投入・素の型 dict)。
    submit_res = submit_analysis(session, GRID, intensity, [[PHASE_A]], reason="m5-e2e")
    assert isinstance(submit_res, dict)

    # run_mem: モック MEMBackend を実体化して委譲 (密度マップ dict)。
    mem_res = run_mem(session, mem_backend=_MockMEMBackend(r_factors=[0.1]))
    assert isinstance(mem_res, dict)
    assert mem_res["status"] == "ok"
    assert "density_map" in mem_res
    assert isinstance(mem_res["density_map"], dict)
    assert "path" in mem_res["density_map"]

    # ledger 連鎖が無傷。
    assert session.ledger.verify() is True


# ---------------------------------------------------------------------------
# 6. 横断: 非破壊性 / 削除 API 不在 (TC-514-01/02/REQ-401)
# ---------------------------------------------------------------------------


def test_m5_no_destructive_api():
    # 【テスト目的】: nested 裁定・MEM 反復・OED 提案・較正を通しても ledger 無傷・削除/上書き API 不在
    ledger = Ledger()
    hyps = (_hyp("h1", chi2=100.0), _hyp("h2", chi2=103.0), _hyp("h3", chi2=200.0))
    problems = {h.id: _problem(h.id) for h in hyps}
    arbitrate(hyps, problems=problems, nested=NestedBackend(), ledger=ledger)
    propose_measurements(rank(hyps, BICBackend()), ledger=ledger)

    backend, phases, joint_result = _joint_result_single()
    snaps = SnapshotStore()
    run_mem_rietveld(
        backend,
        _MockMEMBackend(r_factors=[0.5, 0.4, 0.3]),
        joint_result,
        phases,
        "xray",
        config=MEMRietveldConfig(enabled=True, max_iter=2, r_tol=1e-9, density_tol=1e-9),
        snapshots=snaps,
        ledger=ledger,
    )
    assert ledger.verify() is True

    # 公開面走査: トップレベル __all__ に破壊的動詞が現れない。
    forbidden = ("delete", "remove", "drop", "overwrite", "truncate", "purge", "erase")
    for name in tsumugin.__all__:
        assert not any(word in name.lower() for word in forbidden), name


# ---------------------------------------------------------------------------
# 7. (@nested / @mem) 実サンプラ/実バイナリ smoke (未導入 auto-skip)
# ---------------------------------------------------------------------------


@pytest.mark.nested
def test_m5_nested_real_sampler_smoke():
    # 【テスト目的】: 実サンプラでの nested smoke (未導入は auto-skip) [TC-515-02]
    hyps = (_hyp("h1", chi2=100.0), _hyp("h2", chi2=103.0))
    problems = {h.id: _problem(h.id) for h in hyps}
    result = arbitrate(hyps, problems=problems, nested=NestedBackend())
    assert result.nested_ids == ("h1", "h2")


@pytest.mark.mem
def test_m5_mem_real_binary_smoke():
    # 【テスト目的】: 実 Dysnomia バイナリでの MEM smoke (未導入は auto-skip) [TC-515-04]
    _, _, joint_result = _joint_result_single()
    mem_input = build_mem_input(joint_result, "xray", grid_shape=(16, 16, 16))
    result = DysnomiaBackend().run(mem_input)
    assert isinstance(result, MEMResult)


def _unused_symbols_touch():
    # __all__ 昇格対象で本 E2E が直接使わないシンボルの import 到達性を担保する。
    return (
        ArbitratedHypothesis,
        ArbitrationConfig,
        NestedConfig,
        NestedOutcome,
        ProblemAwareEvidenceBackend,
        ReliabilityBin,
        RestraintSpec,
        build_prior_from_restraints,
        reliability_diagram,
        run_mem_spot,
        RankedHypothesis,
        EvidenceResult,
        SynthesisContext,
    )
