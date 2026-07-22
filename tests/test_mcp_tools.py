"""TASK-0044 mcp/tools + mcp/mem (8 ツール実処理層・SDK 非依存) の TDD テスト。

対象実装 (本タスクで新設):
- ``src/tsumugin/mcp/__init__.py``: サブパッケージ (tools/mem の re-export・SDK 非依存)
- ``src/tsumugin/mcp/tools.py``: ``AnalysisSession`` facade + 8 ツール実処理関数 + ``MCP_TOOLS``
- ``src/tsumugin/mcp/mem.py``: ``run_mem_boundary`` (M5 委譲境界)

完了条件 9 項目 (TASK-0044) に 1:1 対応する:
  (1) 8 ツール実処理関数が存在し MCP_TOOLS に登録         [TC-407-01]
  (2) 各ツールが M0〜M3 資産へ委譲                        [TC-407-02]
  (3) accept/revert が final_selection_mode 同一適用       [TC-407-03]
  (4) revert が superseded 化・accept 履歴件数不変          [TC-407-04/P2]
  (5) human モードで by=agent の accept 拒否→recommend_only [TC-407-05/EDGE-010]
  (6) submit/accept/revert/mode 切替が理由付き ledger 記録  [TC-407-06]
  (7) run_mem が MEMUnavailableError or プレースホルダ      [TC-407-07/EDGE-008]
  (8) MCP ツールに破壊的操作が存在しない                    [TC-407-09]
  (9) export_gpx が GSASUnavailableError→dict 変換・非クラッシュ [TC-407-10/EDGE-011]

本層は MCP SDK を一切 import しない。テストも SDK 非依存で通常 pytest として動く。
"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.errors import GSASUnavailableError, MEMUnavailableError
from tsumugin.evidence.base import EvidenceResult
from tsumugin.evidence.ic import BICBackend
from tsumugin.evidence.ranking import RankedHypothesis
from tsumugin.model import Hypothesis, LatticeParams, PhaseInstance, Project, RefinementMetrics
from tsumugin.search.matcher import UnmatchedPeakReport
from tsumugin.search.tree import SearchResult
from tsumugin.selection import FinalSelectionEngine
from tsumugin.sequential import FrameRecord, Trajectory
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

# 【未実装 import】: mcp パッケージは本タスクで新設。collection 時にここで失敗する (Red) 🔵
from tsumugin.mcp import mem as mem_module
from tsumugin.mcp import tools as tools_module
from tsumugin.mcp.tools import (
    MCP_TOOLS,
    AnalysisSession,
    accept_hypothesis,
    compare_hypotheses,
    export_gpx,
    get_trajectory,
    identify_pattern,
    identify_phase_mixtures,
    identify_phases,
    list_hypotheses,
    propose_discriminating_measurements,
    revert,
    run_mem,
    submit_analysis,
)
from tsumugin.reference.engine import identify_phases as _layer1_identify_phases
from tsumugin.reference.mixture import identify_phase_mixtures as _layer1_identify_phase_mixtures
from tsumugin.reference.model import ReferencePhase
from tsumugin.search.peaks import Peak


# ---------------------------------------------------------------------------
# テストダブルヘルパ (test_selection.py / test_gpx_export.py の慣習を踏襲)
# ---------------------------------------------------------------------------


def _phase(a: float = 4.0, ref: str = "P") -> PhaseInstance:
    return PhaseInstance(phase_ref=ref, lattice=LatticeParams(a, a, a), scale=1.0)


def _metrics(rwp: float = 5.0) -> RefinementMetrics:
    return RefinementMetrics(
        rwp=rwp, gof=1.0, chi2=1.0, n_obs=100, n_params=5, evidence={"bic": rwp}
    )


def _ranked(hyp_id: str, evidence_value: float, *, close: bool = False) -> RankedHypothesis:
    h = Hypothesis(id=hyp_id, phases=(_phase(ref=hyp_id),), metrics=_metrics(), status="refined")
    ev = EvidenceResult(backend="bic", value=evidence_value)
    return RankedHypothesis(hypothesis=h, evidence=ev, probability=0.5, close_competitor=close)


def _search_result(ranked: list[RankedHypothesis]) -> SearchResult:
    led = Ledger()
    return SearchResult(
        ranked=tuple(ranked),
        hypotheses={r.hypothesis.id: r.hypothesis for r in ranked},
        good_cluster_ids=tuple(sorted(r.hypothesis.id for r in ranked)),
        alternatives={},
        unmatched=UnmatchedPeakReport(
            unmatched_observed=(), extra_calculated=(), unknown_phase_flag=False
        ),
        final_reports={},
        ledger=led,
        snapshots=SnapshotStore(ledger=led),
        warnings=(),
    )


def _grid() -> tuple[np.ndarray, np.ndarray]:
    tt = np.arange(20.0, 60.0, 0.1)
    backend = SimulatedBackend()
    intensity = backend.simulate([_phase()], tt)
    return tt, intensity


def _session(
    *,
    mode: str = "agent",
    ranked: list[RankedHypothesis] | None = None,
    with_pattern: bool = False,
    trajectory: Trajectory | None = None,
    reference_provider=None,
) -> AnalysisSession:
    ledger = Ledger()
    selection = FinalSelectionEngine(mode=mode, ledger=ledger)
    search_result = _search_result(ranked) if ranked is not None else None
    tt, intensity = _grid() if with_pattern else (None, None)
    return AnalysisSession(
        project=Project(id="proj-0"),
        backend=SimulatedBackend(),
        selection=selection,
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        evidence=BICBackend(),
        search_result=search_result,
        trajectory=trajectory,
        two_theta=tt,
        intensity=intensity,
        reference_provider=reference_provider,
    )


class _FakeRefProvider:
    """相同定ツール用の in-memory ``ReferenceProvider`` テストダブル。"""

    def __init__(self, phases):
        self._phases = tuple(phases)

    def fetch(self, elements):
        return self._phases


def _ref_phase(phase_id, positions):
    return ReferencePhase(
        phase_id=phase_id,
        formula="X",
        element_system=("Fe", "O"),
        peaks=tuple(Peak(position=p, height=1.0) for p in positions),
        energy_above_hull=0.0,
    )


def _synthetic_pattern(centers, *, fwhm=0.15):
    tt = np.arange(15.0, 60.0, 0.02)
    y = np.zeros_like(tt)
    sigma = fwhm / 2.3548
    for c in centers:
        y += np.exp(-0.5 * ((tt - c) / sigma) ** 2)
    return tt, y


# ===========================================================================
# (1) TC-407-01: 8 ツール実処理関数が存在し MCP_TOOLS に登録される
# ===========================================================================


def test_eight_tools_registered_in_mcp_tools():
    # 【テスト目的】: M4 8 + M6 相同定 2 + M11 identify_pattern 1 (#100) + M8 実構造 Rietveld 3
    #   + M11 identify_pattern 1 + M5 oed 1 (propose_discriminating_measurements #104)
    #   + M9 in situ 逐次 3 + M8-③ MEM 4 (mem_rietveld_iterate #100 含む) + operando 診断 4
    #   + M10 anchor 1 (anchored_sequential, #97) + 構造モデル比較 1 (compare_structure_models, #100)
    #   + 電気化学同期 1 (align_echem, #103)
    #   + interop 変換 2 (convert_pattern/write_instrument_params, #108)
    #   + alkali_budget 1 (FR-318) + review queue 露出 2 (list_review_queue/resolve_review_item,
    #   Issue #125) + write_sequential_csv 1 (FR-504 トラジェクトリ CSV, Issue #116/#117 調査) = 35 ツール登録
    expected = {
        "submit_analysis",
        "list_hypotheses",
        "compare_hypotheses",
        "accept_hypothesis",
        "revert",
        "get_trajectory",
        "export_gpx",
        "run_mem",
        "identify_phases",
        "identify_phase_mixtures",
        "identify_pattern",
        "propose_discriminating_measurements",
        "auto_rietveld",
        "propose_next_actions",
        "refine_with_revisions",
        "sequential_rietveld",
        "identify_and_add_phase",
        "parametric_fit",
        "mem_density",
        "propose_structure_revisions",
        "edit_cif",
        "assess_data_quality",
        "residual_report",
        "check_phase_set",
        "repair_frames",
        "anchored_sequential",
        "compare_structure_models",
        "mem_rietveld_iterate",
        "align_echem",
        "alkali_budget",
        "convert_pattern",
        "write_instrument_params",
        "list_review_queue",
        "resolve_review_item",
        "write_sequential_csv",
    }
    assert set(MCP_TOOLS.keys()) == expected


# ===========================================================================
# M6: 相同定ツール (identify_phases / identify_phase_mixtures)
# ===========================================================================


def test_identify_phases_tool_ranks_and_returns_plain_dict():
    import json

    prov = _FakeRefProvider([
        _ref_phase("mp-good", [20.0, 30.0, 40.0]),
        _ref_phase("mp-poor", [25.0, 55.0]),
    ])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 30.0, 40.0])
    out = identify_phases(session, tt, y, ["Fe", "O"])
    assert out["mode"] == "single"
    assert out["matches"][0]["phase_id"] == "mp-good"
    json.dumps(out, allow_nan=False)  # 素の型 dict (JSON 安全)


def test_identify_phases_tool_without_provider_returns_error():
    session = _session()  # reference_provider 未設定
    tt, y = _synthetic_pattern([20.0])
    out = identify_phases(session, tt, y, ["Fe", "O"])
    assert "error" in out


def test_identify_phases_tool_records_ledger_reason():
    prov = _FakeRefProvider([_ref_phase("mp-1", [20.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0])
    identify_phases(session, tt, y, ["Fe", "O"], reason="agent-run")
    kinds = [e.kind for e in session.ledger.entries]
    assert "mcp_identify" in kinds


def test_identify_phase_mixtures_tool_returns_summary():
    import json

    prov = _FakeRefProvider([
        _ref_phase("mp-A", [20.0, 40.0]),
        _ref_phase("mp-B", [30.0, 50.0]),
    ])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 40.0, 30.0, 50.0])
    out = identify_phase_mixtures(session, tt, y, ["Fe", "O"])
    assert out["mode"] == "mixture"
    assert "ranked" in out
    json.dumps(out, allow_nan=False)


def test_identify_phase_mixtures_tool_without_provider_returns_error():
    session = _session()
    tt, y = _synthetic_pattern([20.0])
    out = identify_phase_mixtures(session, tt, y, ["Fe", "O"])
    assert "error" in out


# ===========================================================================
# subtract_bg 配線 (① reference.engine.identify_phases / reference.mixture.identify_phase_mixtures
# の subtract_bg を ② へ透過する。① 既定は subtract_bg=False — ② もこれに合わせる)
# ===========================================================================


def test_identify_phases_signature_has_subtract_bg_default_false():
    # 【テスト目的】: ② identify_phases に subtract_bg が実在し、① と同じ既定 False であることを
    #   シグネチャで固定する 🔵
    sig = inspect.signature(identify_phases)
    assert "subtract_bg" in sig.parameters
    assert sig.parameters["subtract_bg"].default is False


def test_identify_phase_mixtures_signature_has_subtract_bg_default_false():
    sig = inspect.signature(identify_phase_mixtures)
    assert "subtract_bg" in sig.parameters
    assert sig.parameters["subtract_bg"].default is False


def test_identify_phases_tool_accepts_subtract_bg_true_without_error():
    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0, 30.0, 40.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 30.0, 40.0])
    out = identify_phases(session, tt, y, ["Fe", "O"], subtract_bg=True)
    assert "error" not in out
    assert out["mode"] == "single"


def test_identify_phases_tool_accepts_subtract_bg_false_without_error():
    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0, 30.0, 40.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 30.0, 40.0])
    out = identify_phases(session, tt, y, ["Fe", "O"], subtract_bg=False)
    assert "error" not in out
    assert out["mode"] == "single"


def test_identify_phase_mixtures_tool_accepts_subtract_bg_true_without_error():
    prov = _FakeRefProvider([
        _ref_phase("mp-A", [20.0, 40.0]),
        _ref_phase("mp-B", [30.0, 50.0]),
    ])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 40.0, 30.0, 50.0])
    out = identify_phase_mixtures(session, tt, y, ["Fe", "O"], subtract_bg=True)
    assert "error" not in out
    assert out["mode"] == "mixture"


# ===========================================================================
# Issue #118: ① identify_phases/identify_phase_mixtures の主要パラメータ配線
# (refine_lattice/max_strain/strain_penalty/rerank_top_k/scoring/kalpha2 —
#  reference.engine.identify_phases; refine_lattice/kalpha2/prefilter_top_k/prefilter_dynamic —
#  reference.mixture.identify_phase_mixtures)。② に無いパラメータは ③ から到達不能 (§4.5)。
# ===========================================================================


def test_identify_phases_threads_new_kwargs_to_layer1(monkeypatch):
    """② の新パラメータが①へ実際に渡ること (kwargs をスパイで検証, デフォルトと異なる値で確認)。"""
    from tsumugin.mcp import tools as t

    captured = {}
    real = t._identify_phases

    def spy(two_theta, intensity, provider, **kwargs):
        captured.update(kwargs)
        return real(two_theta, intensity, provider, **kwargs)

    monkeypatch.setattr(t, "_identify_phases", spy)

    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0, 30.0, 40.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 30.0, 40.0])
    out = identify_phases(
        session, tt, y, ["Fe", "O"],
        scoring="coverage",
        refine_lattice=True,
        max_strain=0.02,
        strain_penalty=0.5,
        rerank_top_k=2,
        kalpha2={"intensity_ratio": 0.3, "wavelength_ratio": 1.01},
    )
    assert "error" not in out
    assert captured["scoring"] == "coverage"
    assert captured["refine_lattice"] is True
    assert captured["max_strain"] == 0.02
    assert captured["strain_penalty"] == 0.5
    assert captured["rerank_top_k"] == 2
    from tsumugin.reference.kalpha import KAlpha2

    assert captured["kalpha2"] == KAlpha2(intensity_ratio=0.3, wavelength_ratio=1.01)


def test_identify_phases_default_kwargs_match_layer1_defaults(monkeypatch):
    """省略時は①既定値と同一の呼び出しになること (後方互換)。"""
    from tsumugin.mcp import tools as t

    captured = {}
    real = t._identify_phases

    def spy(two_theta, intensity, provider, **kwargs):
        captured.update(kwargs)
        return real(two_theta, intensity, provider, **kwargs)

    monkeypatch.setattr(t, "_identify_phases", spy)

    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0, 30.0, 40.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 30.0, 40.0])
    identify_phases(session, tt, y, ["Fe", "O"])

    sig = inspect.signature(_layer1_identify_phases)
    assert captured["scoring"] == sig.parameters["scoring"].default
    assert captured["refine_lattice"] == sig.parameters["refine_lattice"].default
    assert captured["max_strain"] == sig.parameters["max_strain"].default
    assert captured["strain_penalty"] == sig.parameters["strain_penalty"].default
    assert captured["rerank_top_k"] == sig.parameters["rerank_top_k"].default
    assert captured["kalpha2"] is None


def test_identify_phases_kalpha2_none_stays_none(monkeypatch):
    from tsumugin.mcp import tools as t

    captured = {}
    real = t._identify_phases

    def spy(two_theta, intensity, provider, **kwargs):
        captured.update(kwargs)
        return real(two_theta, intensity, provider, **kwargs)

    monkeypatch.setattr(t, "_identify_phases", spy)

    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0])
    identify_phases(session, tt, y, ["Fe", "O"], kalpha2=None)
    assert captured["kalpha2"] is None


def test_identify_phases_invalid_kalpha2_spec_degrades_to_error_dict():
    """不正な kalpha2 spec は例外を送出せず error dict へ縮退する (② 不変条件)。"""
    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0])
    out = identify_phases(session, tt, y, ["Fe", "O"], kalpha2={"unknown_key": 1})
    assert out.get("error_type") == "ValueError"
    assert "unknown_key" in out["error"]


def test_identify_phases_invalid_kalpha2_spec_does_not_mutate_ledger():
    """入力不正時は破壊的操作 (ledger 追記含む) をしない。"""
    prov = _FakeRefProvider([_ref_phase("mp-good", [20.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0])
    identify_phases(session, tt, y, ["Fe", "O"], kalpha2={"bad": 1})
    assert "mcp_identify" not in [e.kind for e in session.ledger.entries]


def test_identify_phase_mixtures_threads_new_kwargs_to_layer1(monkeypatch):
    from tsumugin.mcp import tools as t

    captured = {}
    real = t._identify_phase_mixtures

    def spy(two_theta, intensity, provider, **kwargs):
        captured.update(kwargs)
        return real(two_theta, intensity, provider, **kwargs)

    monkeypatch.setattr(t, "_identify_phase_mixtures", spy)

    prov = _FakeRefProvider([
        _ref_phase("mp-A", [20.0, 40.0]),
        _ref_phase("mp-B", [30.0, 50.0]),
    ])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 40.0, 30.0, 50.0])
    out = identify_phase_mixtures(
        session, tt, y, ["Fe", "O"],
        refine_lattice=True,
        kalpha2={"intensity_ratio": 0.4},
        prefilter_top_k=1,
        prefilter_dynamic=True,
    )
    assert "error" not in out
    assert captured["refine_lattice"] is True
    from tsumugin.reference.kalpha import KAlpha2

    assert captured["kalpha2"] == KAlpha2(intensity_ratio=0.4)
    assert captured["prefilter_top_k"] == 1
    assert captured["prefilter_dynamic"] is True


def test_identify_phase_mixtures_default_kwargs_match_layer1_defaults(monkeypatch):
    from tsumugin.mcp import tools as t

    captured = {}
    real = t._identify_phase_mixtures

    def spy(two_theta, intensity, provider, **kwargs):
        captured.update(kwargs)
        return real(two_theta, intensity, provider, **kwargs)

    monkeypatch.setattr(t, "_identify_phase_mixtures", spy)

    prov = _FakeRefProvider([
        _ref_phase("mp-A", [20.0, 40.0]),
        _ref_phase("mp-B", [30.0, 50.0]),
    ])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 40.0, 30.0, 50.0])
    identify_phase_mixtures(session, tt, y, ["Fe", "O"])

    sig = inspect.signature(_layer1_identify_phase_mixtures)
    assert captured["refine_lattice"] == sig.parameters["refine_lattice"].default
    assert captured["kalpha2"] is None
    assert captured["prefilter_top_k"] == sig.parameters["prefilter_top_k"].default
    assert captured["prefilter_dynamic"] == sig.parameters["prefilter_dynamic"].default


def test_identify_phase_mixtures_invalid_kalpha2_spec_degrades_to_error_dict():
    prov = _FakeRefProvider([_ref_phase("mp-A", [20.0, 40.0])])
    session = _session(reference_provider=prov)
    tt, y = _synthetic_pattern([20.0, 40.0])
    out = identify_phase_mixtures(session, tt, y, ["Fe", "O"], kalpha2={"bad": 1})
    assert out.get("error_type") == "ValueError"
    assert "bad" in out["error"]


# ===========================================================================
# M11: identify_pattern (単相/多相統一の逐次減算同定, Issue #100)
# ===========================================================================


def test_identify_pattern_tool_accepts_phases_and_returns_plain_dict():
    import json

    prov = _FakeRefProvider([
        _ref_phase("mp-A", [20.0, 40.0]),
        _ref_phase("mp-B", [30.0, 50.0]),
    ])
    session = _session(reference_provider=prov)
    # 逐次減算同定は残差 S/N ≥ 5σ を受理条件にするため、計数統計に耐える高カウントパターンにする
    # (振幅 1 の合成では sigma=√counts≈1 で S/N が閾値に届かず 0 相で停止する)。
    tt, y = _synthetic_pattern([20.0, 40.0, 30.0, 50.0])
    y = y * 5000.0 + 50.0
    out = identify_pattern(session, tt, y, ["Fe", "O"], snr_stop=5.0)
    assert out["mode"] == "iterative"
    assert out["n_accepted"] == len(out["accepted"])
    assert out["n_accepted"] >= 1  # 少なくとも 1 相受理
    for a in out["accepted"]:
        assert {"phase_id", "formula", "scale", "score", "strain"} <= set(a)
    json.dumps(out, allow_nan=False)


def test_identify_pattern_tool_without_provider_returns_error():
    session = _session()
    tt, y = _synthetic_pattern([20.0])
    out = identify_pattern(session, tt, y, ["Fe", "O"])
    assert "error" in out


def test_identify_pattern_registered_in_mcp_tools():
    assert MCP_TOOLS["identify_pattern"] is identify_pattern


# ===========================================================================
# FR-412: chem 降格 (compare_hypotheses chem_context) / FR-700: oed
# ===========================================================================


def test_compare_hypotheses_chem_context_demotes_alkali_metal_in_air():
    """chem_context 指定で単体アルカリ金属仮説が酸化雰囲気下で降格される (除外はしない)。"""
    session = _session(ranked=[_ranked("Na", 10.0), _ranked("NaCl", 10.0)])
    plain = compare_hypotheses(session, ["Na", "NaCl"])
    # 相の組成は phase_ref 文字列に無いので ③ が同定結果から供給する
    chem_ctx = {
        "atmosphere": "air",
        "phase_compositions": {
            "Na": {"formula": "Na", "element_system": ["Na"]},
            "NaCl": {"formula": "NaCl", "element_system": ["Na", "Cl"]},
        },
    }
    demoted = compare_hypotheses(session, ["Na", "NaCl"], chem_context=chem_ctx)

    assert plain["chem_demotion_applied"] is False
    assert demoted["chem_demotion_applied"] is True
    na_plain = next(c["probability"] for c in plain["compared"] if c["id"] == "Na")
    na_demoted = next(c["probability"] for c in demoted["compared"] if c["id"] == "Na")
    assert na_demoted < na_plain  # 単体 Na は air で降格
    # 降格のみ・除外しない: 件数は不変で Na も残る (Dara 教訓)
    assert len(demoted["compared"]) == len(plain["compared"]) == 2
    assert {c["id"] for c in demoted["compared"]} == {"Na", "NaCl"}


def test_compare_hypotheses_chem_context_tolerates_malformed_compositions():
    """★不正形 phase_compositions (dict でない値) を例外でなく縮退で扱う (② 契約: 例外を送出しない)。

    ③ 供給 JSON なので値が dict でない等の不正形がありうる。素朴な c.get(...) は AttributeError を
    MCP 境界に貫かせるため、不正な相はスキップして降格対象外にする (self-review 指摘)。
    """
    session = _session(ranked=[_ranked("Na", 10.0), _ranked("NaCl", 10.0)])
    out = compare_hypotheses(
        session, ["Na", "NaCl"],
        chem_context={"atmosphere": "air", "phase_compositions": {"Na": "NOT_A_DICT"}},
    )
    assert out["chem_demotion_applied"] is True
    assert len(out["compared"]) == 2  # 例外にならず件数不変


def test_propose_discriminating_measurements_for_close_competitors():
    """僅差競合に判別測定を情報利得順に提案する (非破壊・提案のみ)。"""
    import json

    session = _session(ranked=[_ranked("h1", 10.0), _ranked("h2", 10.0)])
    out = propose_discriminating_measurements(session, close_threshold=10.0)
    assert out["n_proposals"] == len(out["proposals"])
    assert out["n_proposals"] >= 1  # 同一 evidence = 僅差 → 提案あり
    for p in out["proposals"]:
        assert {"kind", "target_hypothesis_ids", "estimated_information_gain"} <= set(p)
    json.dumps(out, allow_nan=False)


def test_propose_discriminating_measurements_without_search_result():
    session = _session()  # 探索結果なし
    out = propose_discriminating_measurements(session)
    assert out == {"proposals": [], "n_proposals": 0}


def test_propose_discriminating_measurements_registered_in_mcp_tools():
    assert MCP_TOOLS["propose_discriminating_measurements"] is propose_discriminating_measurements


def test_mcp_tools_values_are_the_actual_functions():
    # 【テスト目的】: レジストリ値が実処理関数そのもの (別実装でない)
    assert MCP_TOOLS["submit_analysis"] is submit_analysis
    assert MCP_TOOLS["list_hypotheses"] is list_hypotheses
    assert MCP_TOOLS["compare_hypotheses"] is compare_hypotheses
    assert MCP_TOOLS["accept_hypothesis"] is accept_hypothesis
    assert MCP_TOOLS["revert"] is revert
    assert MCP_TOOLS["get_trajectory"] is get_trajectory
    assert MCP_TOOLS["export_gpx"] is export_gpx
    assert MCP_TOOLS["run_mem"] is run_mem


def test_all_tools_return_plain_dict():
    # 【テスト目的】: 各ツールが素の型 dict を返す (SDK 型を露出しない)
    ranked = [_ranked("hyp-0000", 10.0), _ranked("hyp-0001", 20.0)]
    session = _session(ranked=ranked)
    assert isinstance(list_hypotheses(session), dict)
    assert isinstance(compare_hypotheses(session, ["hyp-0000", "hyp-0001"]), dict)


def test_mcp_module_does_not_import_sdk():
    # 【テスト目的】: 実処理層 (tools/mem) が mcp SDK に依存しない (import 表面走査)
    import tsumugin.mcp as mcp_pkg

    for module in (mcp_pkg, tools_module, mem_module):
        source = inspect.getsource(module)
        assert "import mcp" not in source
        assert "from mcp" not in source


# ===========================================================================
# (2) TC-407-02: 各ツールが M0〜M3 資産へ委譲する
# ===========================================================================


def test_submit_single_pattern_delegates_to_analyze_single_pattern(monkeypatch):
    # 【テスト目的】: histograms 空 → pipeline.analyze_single_pattern へ委譲
    calls = {}
    from tsumugin.mcp import tools as t

    real = t.analyze_single_pattern

    def spy(two_theta, intensity, candidate_phase_sets, **kwargs):
        calls["hit"] = True
        return real(two_theta, intensity, candidate_phase_sets, **kwargs)

    monkeypatch.setattr(t, "analyze_single_pattern", spy)

    session = _session()
    tt, intensity = _grid()
    result = submit_analysis(session, tt, intensity, [[_phase()]], reason="unit-test")
    assert calls.get("hit") is True
    assert isinstance(result, dict)


def test_submit_joint_delegates_to_verify_survivors(monkeypatch):
    # 【テスト目的】: histograms 非空 → 探索 → verify_survivors へ委譲
    from tsumugin.joint.model import JointHistogram
    from tsumugin.mcp import tools as t

    calls = {}
    real = t.verify_survivors

    def spy(backend, search_result, histograms, **kwargs):
        calls["hit"] = True
        return real(backend, search_result, histograms, **kwargs)

    monkeypatch.setattr(t, "verify_survivors", spy)

    session = _session()
    tt, intensity = _grid()
    hists = (JointHistogram(two_theta=tt, intensity=intensity, probe="xray"),)
    result = submit_analysis(
        session, tt, intensity, [[_phase()]], histograms=hists, reason="joint"
    )
    assert calls.get("hit") is True
    assert isinstance(result, dict)


def test_list_hypotheses_delegates_to_search_result_summary():
    # 【テスト目的】: list_hypotheses は SearchResult.to_summary の内容を返す
    ranked = [_ranked("hyp-0000", 10.0), _ranked("hyp-0001", 20.0)]
    session = _session(ranked=ranked)
    result = list_hypotheses(session)
    ids = [row["id"] for row in result["ranked"]]
    assert ids == ["hyp-0000", "hyp-0001"]


def test_list_hypotheses_includes_escalations_when_detected():
    # 【テスト目的】: list_hypotheses が escalations (Issue #125) を含み、accept 前に③が確認できる
    # 【背景】: 2 位 close_competitor=True で detect_escalations が "close_competitor" を検出する
    ranked = [_ranked("hyp-0000", 10.0), _ranked("hyp-0001", 10.0, close=True)]
    session = _session(ranked=ranked)
    result = list_hypotheses(session)
    assert "close_competitor" in result["escalations"]


def test_list_hypotheses_escalations_empty_when_none_detected():
    # 【テスト目的】: エスカレーション不成立時は escalations が空リストで返る
    ranked = [_ranked("hyp-0000", 10.0), _ranked("hyp-0001", 20.0)]
    session = _session(ranked=ranked)
    result = list_hypotheses(session)
    assert result["escalations"] == []


def test_compare_hypotheses_delegates_to_rank(monkeypatch):
    # 【テスト目的】: compare_hypotheses が evidence.ranking.rank へ委譲する
    from tsumugin.mcp import tools as t

    calls = {}
    real = t.rank

    def spy(hypotheses, backend, **kwargs):
        calls["hit"] = True
        return real(hypotheses, backend, **kwargs)

    monkeypatch.setattr(t, "rank", spy)

    ranked = [_ranked("hyp-0000", 10.0), _ranked("hyp-0001", 20.0)]
    session = _session(ranked=ranked)
    result = compare_hypotheses(session, ["hyp-0000", "hyp-0001"])
    assert calls.get("hit") is True
    assert isinstance(result, dict)


def test_accept_delegates_to_final_selection_engine(monkeypatch):
    # 【テスト目的】: accept_hypothesis が FinalSelectionEngine.accept へ委譲する
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(ranked=ranked)
    calls = {}
    real = session.selection.accept

    def spy(result, hypothesis_id, *, by):
        calls["by"] = by
        return real(result, hypothesis_id, by=by)

    monkeypatch.setattr(session.selection, "accept", spy)
    result = accept_hypothesis(session, "hyp-0000", by="agent", reason="ok")
    assert calls.get("by") == "agent"
    assert result["status"] == "accepted"


def test_get_trajectory_delegates_to_trajectory_csv(tmp_path):
    # 【テスト目的】: get_trajectory が Trajectory へ委譲し path 指定で CSV 書き出す
    traj = Trajectory(records=(FrameRecord(frame_index=0, rwp=5.0),))
    session = _session(trajectory=traj)
    out = tmp_path / "traj.csv"
    result = get_trajectory(session, path=str(out))
    assert out.exists()
    assert result["path"] == str(out)


def test_get_trajectory_without_trajectory_returns_error_dict_not_empty_success():
    # 【テスト目的】: Issue #116 — session.trajectory 未設定は偽の成功空応答でなく error dict を返す。
    #   旧実装は {"header": [], "rows": {}, "path": None} という「成功に見える空応答」を返しており、
    #   ③ はこれを「時系列データが無い」と誤読していた (実際は入力経路が存在しない)。
    session = _session()  # trajectory 既定 None
    result = get_trajectory(session)
    assert "header" not in result  # 【確認内容】: 偽成功の旧スキーマが残っていない
    assert "rows" not in result
    assert result["error_type"] == "TrajectoryUnavailableError"
    assert "sequential_rietveld" in result["error"]
    assert "anchored_sequential" in result["error"]


def test_get_trajectory_without_trajectory_ignores_path_and_does_not_write_file(tmp_path):
    # 【テスト目的】: trajectory 未設定時は path 指定があってもファイルを書き出さない (副作用なし)
    session = _session()
    out = tmp_path / "traj.csv"
    result = get_trajectory(session, path=str(out))
    assert result["error_type"] == "TrajectoryUnavailableError"
    assert not out.exists()


def test_export_gpx_delegates_to_export_module(monkeypatch, tmp_path):
    # 【テスト目的】: export_gpx が export.gpx.export_gpx へ委譲する (GSAS 非依存に強制成功)
    from tsumugin.mcp import tools as t

    calls = {}

    def fake_export(path, phases, two_theta, intensity, **kwargs):
        calls["path"] = path
        calls["n_phases"] = len(phases)
        return str(path)

    monkeypatch.setattr(t, "_export_gpx", fake_export)

    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(ranked=ranked, with_pattern=True)
    out = tmp_path / "out.gpx"
    result = export_gpx(session, str(out), "hyp-0000")
    assert calls["path"] == str(out)
    assert calls["n_phases"] == 1
    assert result["status"] == "ok"


# ===========================================================================
# (3) TC-407-03: accept/revert が final_selection_mode を同一適用する
# ===========================================================================


def test_accept_agent_mode_accepts():
    # 【テスト目的】: agent モードでは agent による accept が accepted 化する
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    result = accept_hypothesis(session, "hyp-0000", by="agent", reason="agent-accept")
    assert result["status"] == "accepted"
    assert session.selection.accepted["hyp-0000"].status == "accepted"


def test_accept_human_by_human_accepts_in_human_mode():
    # 【テスト目的】: human モードでも by=human の明示 accept は成立する (REQ-103)
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="human", ranked=ranked)
    result = accept_hypothesis(session, "hyp-0000", by="human", reason="human-accept")
    assert result["status"] == "accepted"


def test_accept_hypothesis_includes_escalations_key():
    # 【テスト目的】: accept_hypothesis の応答にも escalations (Issue #125) が含まれる
    ranked = [_ranked("hyp-0000", 10.0), _ranked("hyp-0001", 10.0, close=True)]
    session = _session(mode="agent", ranked=ranked)
    result = accept_hypothesis(session, "hyp-0000", by="agent")
    assert result["status"] == "accepted"
    assert "close_competitor" in result["escalations"]


def test_accept_hypothesis_escalations_empty_when_none_detected():
    # 【テスト目的】: エスカレーション不成立時は accept_hypothesis の escalations が空リスト
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    result = accept_hypothesis(session, "hyp-0000", by="agent")
    assert result["status"] == "accepted"
    assert result["escalations"] == []


def test_revert_uses_same_engine_registry():
    # 【テスト目的】: revert は accept と同一エンジンレジストリを操作する
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    accept_hypothesis(session, "hyp-0000", by="agent")
    revert(session, "hyp-0000", note="rollback")
    assert session.selection.accepted["hyp-0000"].status == "superseded"


# ===========================================================================
# (4) TC-407-04: revert が superseded 化 (追記型) で accept 履歴件数不変
# ===========================================================================


def test_revert_supersedes_and_keeps_registry_count():
    # 【テスト目的】: revert 後もレジストリ件数は減らず superseded 化する (P2)
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    accept_hypothesis(session, "hyp-0000", by="agent")
    count_before = len(session.selection.accepted)
    result = revert(session, "hyp-0000", note="rollback")
    assert result["status"] == "superseded"
    assert len(session.selection.accepted) == count_before
    assert session.selection.accepted["hyp-0000"].status == "superseded"


# ===========================================================================
# (5) TC-407-05: human モードで by=agent の accept 拒否 → recommend_only
# ===========================================================================


def test_human_mode_rejects_agent_accept():
    # 【テスト目的】: human モード + by=agent は accepted 化せず recommend_only を返す (EDGE-010)
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="human", ranked=ranked)
    result = accept_hypothesis(session, "hyp-0000", by="agent", reason="agent-try")
    assert result["status"] == "recommend_only"
    assert result["recommended_id"] == "hyp-0000"
    # 【拒否の担保】: accepted 化されていない (レジストリに accepted が生じない)
    assert "hyp-0000" not in session.selection.accepted


# ===========================================================================
# (6) TC-407-06: submit/accept/revert/mode 切替が理由付き ledger 記録・verify True
# ===========================================================================


def test_submit_records_reason_in_ledger():
    # 【テスト目的】: submit が mcp_submit を理由付きで ledger 記録する
    session = _session()
    tt, intensity = _grid()
    submit_analysis(session, tt, intensity, [[_phase()]], reason="my-reason")
    kinds = [e.kind for e in session.ledger.entries]
    assert "mcp_submit" in kinds
    entry = next(e for e in session.ledger.entries if e.kind == "mcp_submit")
    assert entry.payload["reason"] == "my-reason"
    assert session.ledger.verify() is True


def test_accept_records_and_verifies():
    # 【テスト目的】: accept が ledger 記録され verify() True を維持する
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    accept_hypothesis(session, "hyp-0000", by="agent", reason="acc")
    kinds = [e.kind for e in session.ledger.entries]
    assert "mcp_accept" in kinds
    assert session.ledger.verify() is True


def test_revert_records_and_verifies():
    # 【テスト目的】: revert が ledger 記録され verify() True を維持する
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    accept_hypothesis(session, "hyp-0000", by="agent")
    revert(session, "hyp-0000", note="rb")
    kinds = [e.kind for e in session.ledger.entries]
    assert "mcp_revert" in kinds
    assert session.ledger.verify() is True


def test_mode_switch_records_and_verifies():
    # 【テスト目的】: mode 切替 (set_mode) が ledger 記録され verify() True を維持する
    session = _session(mode="agent")
    session.selection.set_mode("human")
    kinds = [e.kind for e in session.ledger.entries]
    assert "selection_set_mode" in kinds
    assert session.ledger.verify() is True


# ===========================================================================
# (7) TC-407-07: run_mem が MEMUnavailableError or プレースホルダ・破壊操作なし
# ===========================================================================


def test_run_mem_default_returns_error_dict_not_raises():
    # 【テスト目的】: Issue #117 — ② run_mem は MEMUnavailableError を送出せず error dict へ縮退する
    #   (mem_backend は JSON から渡せない Protocol オブジェクトなので ③ からは常にこの経路を通る)。
    #   ① run_mem_boundary の直叩きは従来通り送出する (test_mcp_mem.py 側で不変を確認)。
    session = _session()
    result = run_mem(session)
    assert isinstance(result, dict)
    assert result["status"] == "error"
    assert result["error_type"] == "MEMUnavailableError"
    # 【代替経路の明示】: ③ が実データ MEM への正しい導線を得られること
    assert "mem_density" in result["message"]
    assert "mem_rietveld_iterate" in result["message"]


def test_run_mem_boundary_direct_call_still_raises_mem_unavailable():
    # 【テスト目的】: ① 直叩き経路 (mem_module.run_mem_boundary) は従来どおり例外を送出する
    #   (② run_mem のみが error dict へ縮退する境界であることの対比; test_mcp_mem.py の
    #   test_default_without_backend_raises_mem_unavailable と同一契約)
    session = _session()
    with pytest.raises(MEMUnavailableError):
        mem_module.run_mem_boundary(session)


def test_run_mem_placeholder_returns_dict_without_state_change():
    # 【テスト目的】: placeholder=True は M5 プレースホルダ dict を返し状態変更しない
    session = _session()
    n_before = len(session.ledger.entries)
    result = mem_module.run_mem_boundary(session, placeholder=True)
    assert result["status"] == "not_implemented"
    assert result["milestone"] == "M5"
    # 【破壊操作なし】: ledger は追記されない (境界のみ)
    assert len(session.ledger.entries) == n_before


def test_run_mem_default_does_not_mutate_ledger():
    # 【テスト目的】: run_mem が error dict へ縮退しても ledger 追記・破壊操作がない
    session = _session()
    n_before = len(session.ledger.entries)
    result = run_mem(session)
    assert result["status"] == "error"
    assert len(session.ledger.entries) == n_before


# ===========================================================================
# (8) TC-407-09: MCP ツールに破壊的操作 (削除/上書き) が存在しない (API 表面走査)
# ===========================================================================


def test_no_destructive_operation_names_in_registry():
    # 【テスト目的】: MCP_TOOLS の関数名に破壊的動詞が現れない
    forbidden = ("delete", "remove", "drop", "overwrite", "truncate", "purge", "erase")
    for name in MCP_TOOLS:
        assert not any(word in name for word in forbidden), name


def test_no_destructive_calls_in_tools_source():
    # 【テスト目的】: tools.py 実装が ledger/snapshot の破壊系メソッドを呼ばない (走査)
    source = inspect.getsource(tools_module)
    # 【メソッド呼び出し走査】: 破壊系メソッドの呼び出しが実装に現れない
    for pattern in (".delete(", ".remove(", ".overwrite(", ".pop(", ".truncate(", ".clear("):
        assert pattern not in source, pattern
    # 【del 文走査】: `del ` 文が (import の "model" 等に誤ヒットしないよう) 行頭トークンで現れない
    for line in source.splitlines():
        stripped = line.strip()
        assert not stripped.startswith("del "), stripped


# ===========================================================================
# (9) TC-407-10: export_gpx が GSASUnavailableError → dict 変換・非クラッシュ
# ===========================================================================


def test_export_gpx_converts_gsas_unavailable_to_error_dict(monkeypatch):
    # 【テスト目的】: GSAS 未導入で GSASUnavailableError → {"status":"error"} 変換 (EDGE-011)
    from tsumugin.mcp import tools as t

    def raising_export(*args, **kwargs):
        raise GSASUnavailableError("gsas not installed")

    monkeypatch.setattr(t, "_export_gpx", raising_export)

    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(ranked=ranked, with_pattern=True)
    # 【非クラッシュ】: 例外が dict へ変換され送出されない
    result = export_gpx(session, "unused.gpx", "hyp-0000")
    assert result["status"] == "error"
    assert result["error"] == "gsas_unavailable"


# ===========================================================================
# セルフレビュー修正の回帰テスト (F1〜F4)
# ===========================================================================


def _failed_ranked(hyp_id: str) -> RankedHypothesis:
    """chi2=inf の失敗仮説 (evidence.value=inf / metrics.rwp=inf) を作る。"""
    metrics = RefinementMetrics(
        rwp=float("inf"),
        gof=float("inf"),
        chi2=float("inf"),
        n_obs=100,
        n_params=5,
        evidence={"bic": float("inf")},
    )
    h = Hypothesis(id=hyp_id, phases=(_phase(ref=hyp_id),), metrics=metrics, status="refined")
    ev = EvidenceResult(backend="bic", value=float("inf"))
    return RankedHypothesis(hypothesis=h, evidence=ev, probability=0.0, close_competitor=False)


def test_compare_hypotheses_finite_or_none_serializable_with_failed_hypothesis():
    # 【F1】: 失敗仮説 (evidence.value=inf) で compare_hypotheses の応答が
    #   json.dumps(allow_nan=False) で例外なく直列化でき、該当数値が None であること。
    import json

    ranked = [_failed_ranked("hyp-0000"), _ranked("hyp-0001", 20.0)]
    session = _session(ranked=ranked)
    resp = compare_hypotheses(session, ["hyp-0000", "hyp-0001"])
    # 直列化がクラッシュしない (allow_nan=False)
    json.dumps(resp, allow_nan=False)
    failed_row = next(r for r in resp["compared"] if r["id"] == "hyp-0000")
    assert failed_row["evidence"]["value"] is None


def test_submit_single_finite_or_none_serializable_with_failed_rwp(monkeypatch):
    # 【F1】: submit(single) が失敗 rwp=inf を None 化し allow_nan=False で直列化できること。
    import json

    from tsumugin.mcp import tools as t

    class _Analysis:
        ranked = (_failed_ranked("hyp-0000"),)

    def fake_analyze(two_theta, intensity, candidate_phase_sets, **kwargs):
        return _Analysis()

    monkeypatch.setattr(t, "analyze_single_pattern", fake_analyze)

    session = _session()
    tt, intensity = _grid()
    resp = submit_analysis(session, tt, intensity, [[_phase()]], reason="fail")
    json.dumps(resp, allow_nan=False)
    assert resp["mode"] == "single"
    assert resp["ranked"][0]["rwp"] is None


def test_submit_single_finite_or_none_serializable_with_nan_probability(monkeypatch):
    # 【F1 追補】: 全候補失敗時 softmax は NaN 確率を返す。submit(single) の probability も
    #   finite_or_none で None 化され allow_nan=False で直列化できること (rwp だけでなく)。
    import json

    from tsumugin.mcp import tools as t

    nan_ranked = RankedHypothesis(
        hypothesis=Hypothesis(
            id="hyp-0000",
            phases=(_phase(ref="hyp-0000"),),
            metrics=RefinementMetrics(
                rwp=float("inf"),
                gof=float("inf"),
                chi2=float("inf"),
                n_obs=100,
                n_params=5,
                evidence={"bic": float("inf")},
            ),
            status="refined",
        ),
        evidence=EvidenceResult(backend="bic", value=float("inf")),
        probability=float("nan"),
        close_competitor=False,
    )

    class _Analysis:
        ranked = (nan_ranked,)

    monkeypatch.setattr(t, "analyze_single_pattern", lambda *a, **k: _Analysis())

    session = _session()
    tt, intensity = _grid()
    resp = submit_analysis(session, tt, intensity, [[_phase()]], reason="fail")
    json.dumps(resp, allow_nan=False)
    assert resp["ranked"][0]["probability"] is None


def test_accept_unknown_id_returns_error_dict():
    # 【F2】: 未知 id で accept が error dict を返しクラッシュしないこと。
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    result = accept_hypothesis(session, "hyp-unknown", by="agent")
    assert result["status"] == "error"
    assert result["error"] == "unknown_hypothesis"


def test_revert_unknown_id_returns_error_dict():
    # 【F2】: 未 accept id で revert が error dict を返しクラッシュしないこと。
    ranked = [_ranked("hyp-0000", 10.0)]
    session = _session(mode="agent", ranked=ranked)
    result = revert(session, "hyp-0000", note="never accepted")
    assert result["status"] == "error"
    assert result["error"] == "not_accepted"


def test_submit_joint_flattens_multiphase_candidate_sets(monkeypatch):
    # 【F3】: 多相セット ([[A,B],[C]]) の全相が探索候補へ平坦化されて渡ること。
    from tsumugin.joint.model import JointHistogram
    from tsumugin.mcp import tools as t

    captured = {}
    real_search = t.HypothesisTreeSearch

    class _SpySearch(real_search):  # type: ignore[valid-type,misc]
        def search(self, two_theta, intensity, candidates, **kwargs):
            captured["refs"] = [c.phase_ref for c in candidates]
            return super().search(two_theta, intensity, candidates, **kwargs)

    monkeypatch.setattr(t, "HypothesisTreeSearch", _SpySearch)

    session = _session()
    tt, intensity = _grid()
    hists = (JointHistogram(two_theta=tt, intensity=intensity, probe="xray"),)
    phase_sets = [[_phase(ref="A"), _phase(ref="B")], [_phase(ref="C")]]
    submit_analysis(session, tt, intensity, phase_sets, histograms=hists, reason="joint")
    assert captured["refs"] == ["A", "B", "C"]


def test_submit_joint_skips_empty_candidate_set_without_indexerror(monkeypatch):
    # 【F3】: 空セットを含んでもクラッシュ (IndexError) せず、非空相のみ渡ること。
    from tsumugin.joint.model import JointHistogram
    from tsumugin.mcp import tools as t

    captured = {}
    real_search = t.HypothesisTreeSearch

    class _SpySearch(real_search):  # type: ignore[valid-type,misc]
        def search(self, two_theta, intensity, candidates, **kwargs):
            captured["refs"] = [c.phase_ref for c in candidates]
            return super().search(two_theta, intensity, candidates, **kwargs)

    monkeypatch.setattr(t, "HypothesisTreeSearch", _SpySearch)

    session = _session()
    tt, intensity = _grid()
    hists = (JointHistogram(two_theta=tt, intensity=intensity, probe="xray"),)
    phase_sets = [[], [_phase(ref="A")]]
    # 空セット先頭でも IndexError にならない
    submit_analysis(session, tt, intensity, phase_sets, histograms=hists, reason="joint")
    assert captured["refs"] == ["A"]


def test_list_hypotheses_empty_fallback_has_seven_keys():
    # 【F4】: search_result None 時も to_summary と同じ 6 キー + escalations (Issue #125) が揃うこと。
    session = _session()  # ranked=None → search_result None
    result = list_hypotheses(session)
    assert set(result.keys()) == {
        "ranked",
        "unknown_phase_flag",
        "unmatched_observed",
        "extra_calculated",
        "warnings",
        "n_hypotheses",
        "escalations",
    }
    assert result["ranked"] == []
    assert result["unknown_phase_flag"] is False
    assert result["n_hypotheses"] == 0
    assert result["escalations"] == []
