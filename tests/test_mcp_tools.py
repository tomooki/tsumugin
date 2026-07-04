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
    list_hypotheses,
    revert,
    run_mem,
    submit_analysis,
)


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
    )


# ===========================================================================
# (1) TC-407-01: 8 ツール実処理関数が存在し MCP_TOOLS に登録される
# ===========================================================================


def test_eight_tools_registered_in_mcp_tools():
    # 【テスト目的】: 8 ツール名が MCP_TOOLS に単一情報源として登録される
    expected = {
        "submit_analysis",
        "list_hypotheses",
        "compare_hypotheses",
        "accept_hypothesis",
        "revert",
        "get_trajectory",
        "export_gpx",
        "run_mem",
    }
    assert set(MCP_TOOLS.keys()) == expected


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


def test_run_mem_default_raises_mem_unavailable():
    # 【テスト目的】: 既定 run_mem は MEMUnavailableError を送出する (EDGE-008)
    session = _session()
    with pytest.raises(MEMUnavailableError):
        run_mem(session)


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
    # 【テスト目的】: run_mem 例外送出でも ledger 追記・破壊操作がない
    session = _session()
    n_before = len(session.ledger.entries)
    with pytest.raises(MEMUnavailableError):
        run_mem(session)
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
