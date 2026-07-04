"""MCP 8 ツールの実処理層 (M4 / REQ-021〜025/101/106/201 / interfaces.py mcp/tools 節)。

**SDK 非依存**: 本モジュールは MCP SDK を一切 import しない。8 ツールはプレーンな関数として
M0〜M3 資産へ委譲し、応答は素の型 dict (str/int/float/bool/None/list/dict) のみを返す。MCP
プロトコル (JSON-RPC) との配線は SDK 依存の薄いアダプタ層 (``mcp.server``, TASK-0045) が担う
2 層分離 (D7)。

``AnalysisSession`` は 8 ツールが委譲先へアクセスするための不変 facade。interfaces.py の契約
(project/backend/selection/ledger/snapshots/evidence/search_result/trajectory) に加え、観測
パターン (``two_theta``/``intensity``) を末尾・既定 None で保持する。これは ``export_gpx`` /
``submit_analysis`` が単一の観測パターンを facade 経由でスレッドするための非破壊拡張であり、
MCP フロー (dataflow.md submit → … → export_gpx) の E2E 成立に必要な最小追加である。

**非破壊 (P2 / NFR-101)**: 削除・上書き API を一切実装しない。``revert`` は
``FinalSelectionEngine.revert`` (superseded 化・追記型) のみに委譲し、accept 履歴の件数は減らない。
全状態変更 (submit/accept/revert) は理由付きで ledger に追記し、``ledger.verify()`` は True を保つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..backends.base import RefinementBackend
from ..errors import GSASUnavailableError
from ..evidence.base import EvidenceBackend
from ..evidence.ic import BICBackend
from ..evidence.ranking import rank
from ..export.gpx import export_gpx as _export_gpx
from ..joint.model import JointHistogram
from ..joint.verification import JointVerificationResult, verify_survivors
from ..model import PhaseInstance
from ..model.project import Project
from ..pipeline import analyze_single_pattern
from ..search.tree import HypothesisTreeSearch, SearchResult
from ..selection.engine import FinalSelectionEngine
from ..sequential.trajectory import Trajectory
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from . import mem as _mem

__all__ = [
    "MCP_TOOLS",
    "AnalysisSession",
    "accept_hypothesis",
    "compare_hypotheses",
    "export_gpx",
    "get_trajectory",
    "list_hypotheses",
    "revert",
    "run_mem",
    "submit_analysis",
]


@dataclass(frozen=True)
class AnalysisSession:
    """8 ツールが委譲先へアクセスするための facade (SDK 非依存)。🔵 REQ-022

    【束ね】: project/backend/evidence/ledger/snapshots/selection と直近の SearchResult・
      Trajectory・観測パターンを保持する不変 facade。MCP プロトコルを一切知らない (2 層分離の
      実処理側, D7)。
    【非破壊拡張】: ``two_theta``/``intensity`` は interfaces.py の契約末尾へ既定 None で追加した
      観測パターン保持フィールド。``export_gpx`` / joint ``submit_analysis`` が facade 経由で
      パターンをスレッドするための最小追加 (後方互換・P2)。
    【非破壊拡張 (M5 / TASK-0057)】: ``verification`` は直近の joint 検証結果 (``run_mem`` が対象
      仮説の ``JointRefinementResult`` を引き当てる元) を保持する末尾・既定 None フィールド。
      ``two_theta``/``intensity`` と同型の後方互換追加で、既存フィールドは不変 (P2)。
    """

    project: Project
    backend: RefinementBackend
    selection: FinalSelectionEngine  # 【final_selection_mode 適用の単一経路】 🔵 REQ-023
    ledger: Ledger
    snapshots: SnapshotStore
    evidence: EvidenceBackend | None = None
    search_result: SearchResult | None = None  # 【直近の探索/検証結果】 🔵
    trajectory: Trajectory | None = None  # 【get_trajectory 委譲用】 🔵
    two_theta: np.ndarray | None = None  # 【直近観測 2θ 軸 (export_gpx 用)】 🟡
    intensity: np.ndarray | None = None  # 【直近観測強度 (export_gpx 用)】 🟡
    verification: JointVerificationResult | None = None  # 【run_mem 用 joint 検証結果】 🔵 REQ-034


def submit_analysis(
    session: AnalysisSession,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    candidate_phase_sets: Sequence[Sequence[PhaseInstance]],
    *,
    histograms: tuple[JointHistogram, ...] = (),
    reason: str = "",
) -> dict:
    """解析を投入する。pipeline / joint オーケストレーションへ委譲。🔵 REQ-021/022/025

    【委譲】: histograms 空 → ``analyze_single_pattern`` (単一パターン)。histograms 非空 →
      ``HypothesisTreeSearch.search`` で探索した上で ``verify_survivors`` (joint 検証精密化)。
    【記録】: ``ledger.append("mcp_submit", {..., "reason": reason})`` (REQ-025)。応答は素の型 dict。
    【テスト対応】: test_submit_single_pattern_delegates_to_analyze_single_pattern /
      test_submit_joint_delegates_to_verify_survivors / test_submit_records_reason_in_ledger。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / dataflow.md MCP フローに依拠。
    """
    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)

    if histograms:
        # 【joint 経路】: プライマリパターンで探索 → 生存仮説のみ joint 検証精密化 (FR-245) 🔵
        # 【候補平坦化 (F3)】: search() はフラットな候補相列を取る。多相セットを ps[0] で
        #   捨てず全セットの全相を順序保存で平坦化し、phase_ref 重複を除去して渡す。空セットは
        #   自然に寄与ゼロで skip され IndexError を起こさない (多相 joint 探索の候補欠落を防ぐ) 🔵
        flat_candidates: list[PhaseInstance] = []
        seen_refs: set[str] = set()
        for ps in candidate_phase_sets:
            for phase in ps:
                ref = phase.phase_ref
                if ref in seen_refs:
                    continue
                seen_refs.add(ref)
                flat_candidates.append(phase)
        search = HypothesisTreeSearch(session.backend, evidence=session.evidence)
        search_result = search.search(two_theta, intensity, flat_candidates)
        verification = verify_survivors(
            session.backend, search_result, histograms, evidence=session.evidence
        )
        response = {
            "mode": "joint",
            "n_survivors": len(verification.verified),
            "verified_ids": [h.id for h in verification.verified],
            "warnings": list(verification.warnings),
        }
        n_candidates = len(candidate_phase_sets)
    else:
        # 【単一経路】: 段階精密化 → evidence → ランキング (M0 pipeline へ委譲) 🔵
        analysis = analyze_single_pattern(
            two_theta,
            intensity,
            candidate_phase_sets,
            backend=session.backend,
            evidence=session.evidence,
        )
        response = {
            "mode": "single",
            "ranked": [
                {
                    "id": rk.hypothesis.id,
                    # 【有限化 (F1)】: 全候補失敗時 softmax は NaN 確率を返す。rwp(inf) 同様に
                    #   finite_or_none で None 化し json.dumps(allow_nan=False) クラッシュを防ぐ 🔵
                    "probability": finite_or_none(rk.probability),
                    # 【有限化 (F1)】: 失敗仮説の rwp は inf。json.dumps(allow_nan=False) が
                    #   クラッシュしないよう to_summary と同じ finite_or_none で None 化する 🔵
                    "rwp": (
                        finite_or_none(rk.hypothesis.metrics.rwp)
                        if rk.hypothesis.metrics is not None
                        else None
                    ),
                }
                for rk in analysis.ranked
            ],
        }
        n_candidates = len(candidate_phase_sets)

    # 【理由付き記録】: 投入自体を mcp_submit で追記する (REQ-025) 🔵
    session.ledger.append(
        "mcp_submit",
        {
            "mode": response["mode"],
            "n_candidates": n_candidates,
            "n_histograms": len(histograms),
            "reason": reason,
        },
    )
    return response


def list_hypotheses(session: AnalysisSession) -> dict:
    """仮説一覧を返す。SearchResult.to_summary へ委譲。🔵 REQ-021/022

    【委譲】: ``session.search_result.to_summary()`` の /api/result スキーマ準拠 dict を返す。
      直近の探索結果が無い場合は空一覧 dict を返す (縮退・例外化しない)。
    【空フォールバック (F4)】: search_result 不在時も to_summary と同じ 6 キー
      (ranked/unknown_phase_flag/unmatched_observed/extra_calculated/warnings/n_hypotheses)
      を揃えた縮退 dict を返す (スキーマ整合・下流の KeyError 防止)。
    【テスト対応】: test_list_hypotheses_delegates_to_search_result_summary。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / tree.py to_summary に依拠。
    """
    if session.search_result is None:
        return {
            "ranked": [],
            "unknown_phase_flag": False,
            "unmatched_observed": [],
            "extra_calculated": [],
            "warnings": [],
            "n_hypotheses": 0,
        }
    return session.search_result.to_summary()


def compare_hypotheses(session: AnalysisSession, hypothesis_ids: Sequence[str]) -> dict:
    """指定仮説を evidence/確率で比較する。rank へ委譲。🔵 REQ-021/022

    【委譲】: ``session.search_result.hypotheses`` から指定 ID の仮説を取り出し、
      ``evidence.ranking.rank`` で evidence/確率を再計算した比較 dict を返す。
    【決定論】: 未知 ID はスキップ (誤操作防御)。evidence backend は session の注入 (既定 BIC)。
    【テスト対応】: test_compare_hypotheses_delegates_to_rank。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / evidence/ranking.rank に依拠。
    """
    if session.search_result is None:
        return {"compared": []}
    hypotheses = [
        session.search_result.hypotheses[hid]
        for hid in hypothesis_ids
        if hid in session.search_result.hypotheses
    ]
    if not hypotheses:
        return {"compared": []}
    # 【evidence 再ランク (F5)】: session 注入 evidence を単一情報源で既定 BIC へフォールバック
    #   (既存パターン ``session.evidence or BICBackend()`` に統一・関数内 import を除去) 🔵
    backend = session.evidence or BICBackend()
    ranked = rank(hypotheses, backend)
    return {
        "compared": [
            {
                "id": rk.hypothesis.id,
                # 【有限化 (F1)】: 失敗仮説では probability/evidence.value が非有限になりうる。
                #   json.dumps(allow_nan=False) クラッシュを防ぐため finite_or_none で None 化 🔵
                "probability": finite_or_none(rk.probability),
                "evidence": {
                    "backend": str(rk.evidence.backend),
                    "value": finite_or_none(rk.evidence.value),
                },
                "close_competitor": bool(rk.close_competitor),
            }
            for rk in ranked
        ]
    }


def accept_hypothesis(
    session: AnalysisSession, hypothesis_id: str, *, by: Literal["agent", "human"], reason: str = ""
) -> dict:
    """仮説を accept する。FinalSelectionEngine.accept へ委譲し mode を同一適用。🔵 REQ-023/106/201

    【human モード拒否】: ``session.selection.mode == "human"`` かつ ``by == "agent"`` のとき
      accepted 化を拒否し ``{"status": "recommend_only", "recommended_id": ...}`` を返す
      (REQ-106/EDGE-010)。それ以外は ``FinalSelectionEngine.accept(result, id, by=by)`` へ委譲。
    【記録】: accept 成立時のみ ``mcp_accept`` を ledger 記録する (accept 自体も selection 経由で
      ``selection_accept`` を記録)。
    【テスト対応】: test_accept_agent_mode_accepts / test_accept_human_by_human_accepts_in_human_mode /
      test_human_mode_rejects_agent_accept / test_accept_records_and_verifies。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / selection/engine.accept に依拠。
    """
    # 【human モード拒否】: agent 主導の accepted 化を拒み推奨提示に留める (EDGE-010) 🔵 REQ-106
    if session.selection.mode == "human" and by == "agent":
        return {"status": "recommend_only", "recommended_id": hypothesis_id}

    if session.search_result is None:
        return {"status": "error", "error": "no_search_result"}

    # 【未知 id 防御 (F2)】: 未知 id は engine.accept が KeyError を送出し MCP をクラッシュさせる。
    #   委譲前に探索結果メンバか確認し、未知なら error dict へ変換する (export_gpx/compare と対称) 🔵
    if hypothesis_id not in session.search_result.hypotheses:
        return {"status": "error", "error": "unknown_hypothesis"}

    # 【委譲】: FinalSelectionEngine.accept が mode を同一適用し accepted 化を記録する 🔵 REQ-023
    accepted = session.selection.accept(session.search_result, hypothesis_id, by=by)
    # 【理由付き記録】: MCP 経由の accept を追記する (selection 側 selection_accept と二重記録) 🔵 REQ-025
    session.ledger.append(
        "mcp_accept", {"hypothesis_id": hypothesis_id, "by": by, "reason": reason}
    )
    return {"status": "accepted", "hypothesis_id": accepted.id, "accepted_by": accepted.accepted_by}


def revert(session: AnalysisSession, hypothesis_id: str, *, note: str = "") -> dict:
    """accept を superseded 化する (追記型・破壊的削除でない)。🔵 REQ-024/TC-407-04

    【委譲】: ``FinalSelectionEngine.revert`` (superseded 化) のみ。破壊的操作は新設しない
      (REQ-024/NFR-101)。accept 履歴の件数は減らない。
    【記録】: ``mcp_revert`` を ledger 記録する (selection 側 ``selection_revert`` と二重記録)。
    【テスト対応】: test_revert_supersedes_and_keeps_registry_count / test_revert_records_and_verifies。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / selection/engine.revert に依拠。
    """
    # 【未 accept id 防御 (F2)】: engine.revert は未 accept id で KeyError を送出し MCP を
    #   クラッシュさせる。accept 済みレジストリを確認し、未登録なら error dict へ変換する 🔵
    if hypothesis_id not in session.selection.accepted:
        return {"status": "error", "error": "not_accepted"}
    # 【委譲】: superseded 化のみ (追記型・件数不減, P2) 🔵 REQ-024
    superseded = session.selection.revert(hypothesis_id, note=note)
    # 【理由付き記録】: MCP 経由の revert を追記する (追記のみ・削除しない) 🔵 REQ-025
    session.ledger.append("mcp_revert", {"hypothesis_id": hypothesis_id, "note": note})
    return {"status": "superseded", "hypothesis_id": superseded.id}


def get_trajectory(session: AnalysisSession, *, path: str | None = None) -> dict:
    """時系列トラジェクトリを返す/CSV 書き出す。Trajectory へ委譲。🔵 REQ-021/022

    【委譲】: ``session.trajectory`` のヘッダ + frame_index 行を素の型 dict で返す。``path`` 指定
      時は ``Trajectory.to_csv`` で CSV を書き出しパスを添える。trajectory 不在は空応答 (縮退)。
    【テスト対応】: test_get_trajectory_delegates_to_trajectory_csv。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / sequential/trajectory に依拠。
    """
    if session.trajectory is None:
        return {"header": [], "rows": {}, "path": None}
    trajectory = session.trajectory
    # 【委譲】: 決定論ヘッダ + frame_index → セル列 (Trajectory 私有を触らず公開 API 経由) 🔵
    response: dict = {
        "header": list(trajectory.header()),
        "rows": {str(k): v for k, v in trajectory.rows_by_frame().items()},
        "path": None,
    }
    if path is not None:
        # 【CSV 委譲】: 決定論 CSV を書き出しパスを添える (外部委譲出口) 🔵
        response["path"] = trajectory.to_csv(path)
    return response


def export_gpx(
    session: AnalysisSession, path: str, hypothesis_id: str, *, wavelength: float | None = None
) -> dict:
    """指定仮説の相を .gpx へ書き出す。export.gpx.export_gpx へ委譲。🔵 REQ-021/022/EDGE-011

    【委譲】: ``session.search_result.hypotheses[hypothesis_id]`` の phases と session の観測
      パターンで ``export.gpx.export_gpx`` を呼ぶ。wavelength 指定時のみ渡す (既定は export 側)。
    【GSAS 未導入】: ``GSASUnavailableError`` を捕捉し ``{"status": "error", "error":
      "gsas_unavailable"}`` へ変換する (クラッシュしない, TC-407-10/EDGE-011)。
    【テスト対応】: test_export_gpx_delegates_to_export_module /
      test_export_gpx_converts_gsas_unavailable_to_error_dict。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / export/gpx.export_gpx に依拠。
    """
    # 【仮説引き当て】: 直近探索結果から対象仮説の相を取り出す (未知 ID はエラー dict) 🔵
    if session.search_result is None or hypothesis_id not in session.search_result.hypotheses:
        return {"status": "error", "error": "unknown_hypothesis"}
    if session.two_theta is None or session.intensity is None:
        return {"status": "error", "error": "no_pattern"}

    phases = session.search_result.hypotheses[hypothesis_id].phases
    kwargs: dict = {}
    if wavelength is not None:
        kwargs["wavelength"] = wavelength
    try:
        # 【委譲】: 実書き出しは export.gpx へ (GSAS 導入時のみ成功) 🔵
        out_path = _export_gpx(
            path, phases, session.two_theta, session.intensity, **kwargs
        )
    except GSASUnavailableError:
        # 【EDGE-011】: GSAS 未導入例外を MCP エラー dict へ変換 (クラッシュしない) 🔵
        return {"status": "error", "error": "gsas_unavailable"}
    return {"status": "ok", "path": out_path, "hypothesis_id": hypothesis_id}


def run_mem(session: AnalysisSession, **params: object) -> dict:
    """MEM 実行の M5 委譲境界。破壊的操作なし。🔵 REQ-033/034/101/104/EDGE-006/008/013

    【委譲】: ``mcp.mem.run_mem_boundary`` へ **params 透過で委譲する。``mem_backend`` /
      ``hypothesis_id`` / ``frame_index`` を含む params はそのまま境界へ渡り、``mem_backend``
      供給時のみ ``build_mem_input``→``mem_backend.run`` の実処理へ入る (M5 実体化)。
    【後方互換】: ``mem_backend`` 未供給かつ ``placeholder=False`` は従来通り ``MEMUnavailableError``
      送出、``placeholder=True`` は M4 プレースホルダ dict (D9)。破壊的操作なし (NFR-101)。
    【テスト対応】: test_run_mem_default_raises_mem_unavailable / test_run_mem_tool_passes_backend_through_params。
    🔵 信頼性レベル: interfaces.py mcp/tools・mcp/mem 節 / REQ-033/034/101/104 に依拠。
    """
    # 【委譲】: M5 実体化境界へ params 透過 (mem_backend 供給時のみ実処理・破壊的追記なし) 🔵 REQ-034
    return _mem.run_mem_boundary(session, **params)


# 【ツールレジストリ】: 8 ツール名 → 実処理関数。アダプタ層 (server.py) が配線に使う単一情報源 🔵 REQ-021
MCP_TOOLS: Mapping[str, object] = {
    "submit_analysis": submit_analysis,
    "list_hypotheses": list_hypotheses,
    "compare_hypotheses": compare_hypotheses,
    "accept_hypothesis": accept_hypothesis,
    "revert": revert,
    "get_trajectory": get_trajectory,
    "export_gpx": export_gpx,
    "run_mem": run_mem,
}
