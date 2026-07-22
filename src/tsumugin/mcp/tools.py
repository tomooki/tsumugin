"""MCP ツール実処理層 (M4 8 ツール + M6 相同定 2 ツール = 10 / REQ-021〜025/101/106/201)。

**SDK 非依存**: 本モジュールは MCP SDK を一切 import しない。各ツールはプレーンな関数として
M0〜M6 資産へ委譲し、応答は素の型 dict (str/int/float/bool/None/list/dict) のみを返す。MCP
プロトコル (JSON-RPC) との配線は SDK 依存の薄いアダプタ層 (``mcp.server``, TASK-0045) が担う
2 層分離 (D7)。M6 で相同定ツール (``identify_phases`` / ``identify_phase_mixtures``) を追加。

``AnalysisSession`` は各ツールが委譲先へアクセスするための不変 facade。interfaces.py の契約
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
from ..errors import GSASUnavailableError, MEMUnavailableError
from ..evidence.base import EvidenceBackend
from ..evidence.ic import BICBackend
from ..evidence.ranking import rank
from ..export.gpx import export_gpx as _export_gpx
from ..joint.model import JointHistogram
from ..joint.verification import JointVerificationResult, verify_survivors
from ..model import PhaseInstance
from ..model.project import Project
from ..pipeline import analyze_single_pattern
from ..reference.engine import identify_phases as _identify_phases
from ..reference.mixture import identify_phase_mixtures as _identify_phase_mixtures
from ..reference.provider import ReferenceProvider
from ._kalpha_spec import kalpha2_from_spec
from ..search.tree import HypothesisTreeSearch, SearchResult
from ..selection.engine import FinalSelectionEngine, detect_escalations
from ..sequential.trajectory import Trajectory
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from . import mem as _mem
from .anchor_tools import ANCHOR_TOOLS as _ANCHOR_TOOLS
from .compare_tools import COMPARE_TOOLS as _COMPARE_TOOLS
from .echem_tools import ECHEM_TOOLS as _ECHEM_TOOLS
from .insitu_tools import INSITU_TOOLS as _INSITU_TOOLS
from .interop_tools import INTEROP_TOOLS as _INTEROP_TOOLS
from .mem_tools import MEM_MODEL_TOOLS as _MEM_MODEL_TOOLS
from .operando_diag_tools import OPERANDO_DIAG_TOOLS as _OPERANDO_DIAG_TOOLS
from .rietveld_tools import RIETVELD_TOOLS as _RIETVELD_TOOLS

__all__ = [
    "MCP_TOOLS",
    "AnalysisSession",
    "accept_hypothesis",
    "compare_hypotheses",
    "export_gpx",
    "get_trajectory",
    "identify_pattern",
    "identify_phase_mixtures",
    "identify_phases",
    "list_hypotheses",
    "list_review_queue",
    "propose_discriminating_measurements",
    "resolve_review_item",
    "revert",
    "run_mem",
    "submit_analysis",
]


@dataclass(frozen=True)
class AnalysisSession:
    """MCP ツール群が委譲先へアクセスするための facade (SDK 非依存)。🔵 REQ-022

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
    # 【非破壊拡張 (M6)】: 相同定ツール (identify_phases / identify_phase_mixtures) が使う相ライブラリ
    #   供給元。末尾・既定 None の後方互換追加で、未設定時は当該ツールが error dict を返す (FR-101/110)。
    reference_provider: ReferenceProvider | None = None


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
    【空フォールバック (F4)】: search_result 不在時も to_summary と同じ 6 キー + ``escalations``
      (ranked/unknown_phase_flag/unmatched_observed/extra_calculated/warnings/n_hypotheses/escalations)
      を揃えた縮退 dict を返す (スキーマ整合・下流の KeyError 防止)。
    【Issue #125】: ``escalations`` は ``selection.detect_escalations`` (FR-403 の 4 条件) を
      ``session.search_result`` に対して都度計算した tuple → list。**accept する前にここを見る**の
      が ③ の手順 (SKILL.md「エスカレーションを確認する」)。空でなければ自動 accept せず
      ``list_review_queue`` で未解決の確認事項も併せて読む。
    【テスト対応】: test_list_hypotheses_delegates_to_search_result_summary /
      test_list_hypotheses_includes_escalations_when_detected /
      test_list_hypotheses_escalations_empty_when_none_detected /
      test_list_hypotheses_empty_fallback_has_six_keys (7 キー化)。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / tree.py to_summary に依拠 / Issue #125。
    """
    if session.search_result is None:
        return {
            "ranked": [],
            "unknown_phase_flag": False,
            "unmatched_observed": [],
            "extra_calculated": [],
            "warnings": [],
            "n_hypotheses": 0,
            "escalations": [],
        }
    summary = session.search_result.to_summary()
    # 【Issue #125】: accept 前に③がエスカレーションを確認できる唯一の場所。空でなければ
    # 自動 accept せず review queue を確認すべき、というシグナルを ③ に渡す (SKILL.md 手順)。
    summary["escalations"] = list(detect_escalations(session.search_result))
    return summary


def compare_hypotheses(
    session: AnalysisSession,
    hypothesis_ids: Sequence[str],
    *,
    chem_context: Mapping[str, object] | None = None,
) -> dict:
    """指定仮説を evidence/確率で比較する。rank へ委譲。🔵 REQ-021/022/FR-412

    【委譲】: ``session.search_result.hypotheses`` から指定 ID の仮説を取り出し、
      ``evidence.ranking.rank`` で evidence/確率を再計算した比較 dict を返す。
    【決定論】: 未知 ID はスキップ (誤操作防御)。evidence backend は session の注入 (既定 BIC)。
    【化学的妥当性の降格 (FR-412, chem_context 指定時)】: ``chem_context`` (合成条件) を渡すと、
      ``chem.rank_with_plausibility`` で **ChemPlausibility 降格**を配線する (例: 酸化雰囲気での
      単体アルカリ金属は非妥当として確率を下げる)。**降格のみ・候補除外はしない** (Dara 教訓):
      低スコア仮説も compared に残り件数は不変。``chem_context`` のキー:

      - ``atmosphere``: 合成雰囲気 ("air"/"O2"/"Ar"/"N2" 等)。酸化性判定に使う
      - ``element_system`` / ``precursors``: 合成の元素系/前駆体 (任意)
      - ``phase_compositions``: ``{phase_ref: {"formula": str, "element_system": [str]}}``。**相の
        組成メタ**。Hypothesis の相 (PhaseInstance) は phase_ref 文字列しか持たず組成を運ばないため、
        降格を効かせるには ③ が同定結果 (``identify_phases``/``identify_pattern`` の formula) から
        供給する。未供給の相は phase_ref から組成を導出できず降格対象外になる (静かに効かない)
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
    if chem_context is not None:
        from ..chem import AlkaliMetalInAirRule, SynthesisContext, rank_with_plausibility
        from ..model.phase import PhaseRef

        ctx = SynthesisContext(
            element_system=tuple(str(e) for e in chem_context.get("element_system", ())),
            precursors=tuple(str(p) for p in chem_context.get("precursors", ())),
            atmosphere=(
                str(chem_context["atmosphere"])
                if chem_context.get("atmosphere") is not None
                else None
            ),
        )
        # 相の組成メタを ③ 供給の phase_compositions から PhaseRef へ (phase_ref 文字列は組成を
        # 運ばないため; 未供給なら None で from_phase_ref フォールバック = 降格は効かない)。
        # 【頑健化】: ③ 供給 JSON なので不正形 (comps が dict でない・値が dict でない) を許容し、
        #   例外を境界に貫かせない (② は例外を送出しない契約)。不正な相はスキップ = 降格対象外。
        raw_comps = chem_context.get("phase_compositions")
        comps = raw_comps if isinstance(raw_comps, Mapping) else {}
        phase_refs = {
            str(pid): PhaseRef(
                id=str(pid),
                formula=(str(c["formula"]) if c.get("formula") is not None else None),
                element_system=tuple(str(e) for e in c.get("element_system", ())),
            )
            for pid, c in comps.items()
            if isinstance(c, Mapping)
        } or None
        ranked = rank_with_plausibility(
            hypotheses, backend, modules=(AlkaliMetalInAirRule(),), context=ctx,
            phase_refs=phase_refs, ledger=session.ledger,
        )
    else:
        ranked = rank(hypotheses, backend)
    return {
        # ChemPlausibility を配線したかを ③ に明示 (降格の有無で数字の解釈が変わる)
        "chem_demotion_applied": chem_context is not None,
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
        ],
    }


def accept_hypothesis(
    session: AnalysisSession, hypothesis_id: str, *, by: Literal["agent", "human"], reason: str = ""
) -> dict:
    """仮説を accept する。FinalSelectionEngine.accept へ委譲し mode を同一適用。🔵 REQ-023/106/201

    【human モード拒否】: ``session.selection.mode == "human"`` かつ ``by == "agent"`` のとき
      accepted 化を拒否し ``{"status": "recommend_only", "recommended_id": ...}`` を返す
      (REQ-106/EDGE-010)。それ以外は ``FinalSelectionEngine.accept(result, id, by=by)`` へ委譲。
    【記録】: accept 成立時のみ ``mcp_accept`` を ledger 記録する (accept 自体も selection 経由で
      ``selection_accept`` を記録)。``FinalSelectionEngine.accept`` は同時にエスカレーション成立時
      queue へも通知する (Issue #125)。
    【Issue #125】: 応答に ``escalations`` を含める。``selection.accept`` を直接呼ぶこの経路は
      ``decide()`` を迂回するため、accept 成立時点のエスカレーション状況を③へ明示的に返す
      (accept 後でも「実は僅差競合だった」等を確認できるようにする)。
    【テスト対応】: test_accept_agent_mode_accepts / test_accept_human_by_human_accepts_in_human_mode /
      test_human_mode_rejects_agent_accept / test_accept_records_and_verifies /
      test_accept_hypothesis_includes_escalations_key /
      test_accept_hypothesis_escalations_empty_when_none_detected。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / selection/engine.accept に依拠 / Issue #125。
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
    #   (Issue #125: accept 内部でエスカレーション成立時 queue へも通知される)
    accepted = session.selection.accept(session.search_result, hypothesis_id, by=by)
    # 【理由付き記録】: MCP 経由の accept を追記する (selection 側 selection_accept と二重記録) 🔵 REQ-025
    session.ledger.append(
        "mcp_accept", {"hypothesis_id": hypothesis_id, "by": by, "reason": reason}
    )
    return {
        "status": "accepted",
        "hypothesis_id": accepted.id,
        "accepted_by": accepted.accepted_by,
        # 【Issue #125】: accept 対象の SearchResult に対するエスカレーション再計算 (detect_escalations
        #   は純粋関数・副作用ゼロなので同じ result に対し何度呼んでも同じ tuple を返す, NFR-102) 🔵
        "escalations": list(detect_escalations(session.search_result)),
    }


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
      時は ``Trajectory.to_csv`` で CSV を書き出しパスを添える。
    【Issue #116: 偽成功の是正】: ``session.trajectory`` を設定する ② ツールは存在しない
      (``sequential/engine.py`` の M2 simulate 系の出力アクセサであり、実データ経路である M9
      ``sequential_rietveld``/M10 ``anchored_sequential`` とは別サブシステム)。従来は
      ``{"header": [], "rows": {}, "path": None}`` という**成功に見える空応答**を返しており、
      ③ はこれを「時系列データが無い」と読んでしまう (実際は「このツールへ入力を渡す経路が無い」)。
      CLAUDE.md ②不変条件 (空/不正入力を「正常」と答えない) に抵触するため、明示的な error dict
      (``error_type`` 付き) へ縮退する。実データの時系列は ``sequential_rietveld`` /
      ``anchored_sequential`` の結果 dict をそのまま使うこと。
    【テスト対応】: test_get_trajectory_delegates_to_trajectory_csv /
      test_get_trajectory_without_trajectory_returns_error_dict_not_empty_success /
      test_get_trajectory_without_trajectory_ignores_path_and_does_not_write_file。
    🔵 信頼性レベル: interfaces.py mcp/tools 節 / sequential/trajectory に依拠。
    """
    if session.trajectory is None:
        return {
            "error": (
                "session.trajectory が未設定です。get_trajectory は M2 逐次 simulate 系 "
                "(sequential/engine.py) の Trajectory 出力アクセサですが、これを設定する ② ツールは "
                "存在しないため実運用では到達不能です (dead on arrival)。実データの時系列は "
                "sequential_rietveld または anchored_sequential が返す結果 dict をそのまま使って"
                "ください (frames[].rwp/refined_cells/phase_fractions 等)。"
            ),
            "error_type": "TrajectoryUnavailableError",
        }
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
    【後方互換】: ``placeholder=True`` は M4 プレースホルダ dict (D9・状態変更なし)。破壊的操作なし
      (NFR-101)。
    【Issue #117: 例外リークの是正】: ``mem_backend`` は ``MEMBackend`` Protocol の**オブジェクト**
      であり JSON からは渡せない。したがって JSON しか送れない ③ が呼ぶと ``mem_backend`` は
      常に未供給になり、① ``run_mem_boundary`` は ``MEMUnavailableError`` を送出する。この例外が
      ② 境界を越えるのは CLAUDE.md ②不変条件 (② ツールは例外を送出しない) への抵触なので、ここで
      捕捉して error dict へ縮退する。① 直叩き経路 (``mem.run_mem_boundary`` を直接呼ぶ場合) は
      本関数を経由しないため従来通り送出される (後方互換, TC-511 系不変)。
    【テスト対応】: test_run_mem_default_returns_error_dict_not_raises (旧
      test_run_mem_default_raises_mem_unavailable を改称) / test_run_mem_tool_passes_backend_through_params。
    🔵 信頼性レベル: interfaces.py mcp/tools・mcp/mem 節 / REQ-033/034/101/104 に依拠。
    """
    try:
        # 【委譲】: M5 実体化境界へ params 透過 (mem_backend 供給時のみ実処理・破壊的追記なし) 🔵 REQ-034
        return _mem.run_mem_boundary(session, **params)
    except MEMUnavailableError as exc:
        # 【② 契約 (例外を送出しない)】: mem_backend は Protocol オブジェクトで JSON 境界を越えられ
        #   ないため、③ から呼ぶ限り本例外は避けられない。error dict へ縮退し、実データ MEM の代替
        #   経路 (JSON-only・callable 不要) を明示する 🔵 Issue #117
        return {
            "status": "error",
            "error": "mem_backend_unavailable",
            "error_type": type(exc).__name__,
            "message": (
                "run_mem は mem_backend (MEMBackend Protocol オブジェクト) を要求しますが、JSON から"
                "はオブジェクトを渡せないため実運用では到達不能です (dead on arrival)。実データ MEM は "
                "mem_density (単発 MEM 密度解析) または mem_rietveld_iterate (MEM-Rietveld 反復) を"
                "使ってください (mem-model-fix skill)。"
            ),
        }


def propose_discriminating_measurements(
    session: AnalysisSession, *, close_threshold: float = 10.0, reason: str = ""
) -> dict:
    """僅差競合の仮説を判別する追加測定を情報利得順に提案する (OED, FR-700)。🔵

    【なぜ session 経由か】: OED は木探索/裁定の中間生成物 ``RankedHypothesis`` を入力に取る。
      これを JSON で受け渡すのは §4.5 的に不自然なので、``compare_hypotheses`` と同じく **session 内の
      探索結果を入力に取る** (RankedHypothesis を境界に晒さない)。
    【委譲】: session の直近探索結果を ``evidence.ranking.rank`` で順位付け → ``oed.propose_measurements``
      で僅差競合 (最良との BIC 差 < close_threshold) の判別測定を情報利得順に提案する。
    【非破壊・提案のみ (FR-700)】: 測定の実行・データ変更はしない。提案を ledger に追記するのみ。
      僅差競合が無ければ空提案 (措置不要のシグナル)。

    :param close_threshold: 僅差競合とみなす最良仮説との evidence (BIC) 差の上限
    :returns: ``proposals[]`` (kind/target_hypothesis_ids/rationale/estimated_information_gain/
      parameters) + ``n_proposals``。探索結果が無ければ空提案
    """
    if session.search_result is None:
        return {"proposals": [], "n_proposals": 0}
    from ..oed import propose_measurements, proposals_to_json

    hypotheses = list(session.search_result.hypotheses.values())
    if not hypotheses:
        return {"proposals": [], "n_proposals": 0}
    backend = session.evidence or BICBackend()
    ranked = rank(hypotheses, backend, close_threshold=close_threshold)
    proposals = propose_measurements(
        ranked, close_threshold=close_threshold, ledger=session.ledger
    )
    return {"proposals": proposals_to_json(proposals), "n_proposals": len(proposals)}


def identify_phases(
    session: AnalysisSession,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    elements: Sequence[str],
    *,
    hull_cutoff_ev: float | None = 0.1,
    max_results: int | None = None,
    subtract_bg: bool = False,
    scoring: Literal["dara", "coverage"] = "dara",
    refine_lattice: bool = False,
    max_strain: float = 0.01,
    strain_penalty: float = 0.0,
    rerank_top_k: int = 5,
    kalpha2: Mapping[str, object] | None = None,
    reason: str = "",
) -> dict:
    """未知パターン + 元素一覧から単相候補をランキング同定する (M6 委譲境界)。🔵 FR-110/117

    【委譲】: ``session.reference_provider`` を供給元に ``reference.identify_phases`` へ委譲する。
      供給元未設定なら破壊的操作なしで ``{"error": ...}`` を返す。応答は素の型 dict
      (json.dumps(allow_nan=False) 安全, スコアは finite_or_none で None 化)。
    【記録】: ``ledger.append("mcp_identify", {..., "reason": reason})``。破壊的操作なし (NFR-101)。

    :param subtract_bg: 同定前に SNIP 背景減算をオプトイン適用する (① と同じ既定 False)。
      観測パターンが**既に背景減算済み**の場合に True を渡すと二重減算になるため注意。
    :param scoring: マッチスコア方式。``"dara"`` (既定, ① と同じ) は Fei et al. 2026 式1
      (実測強度正規化 + extra 罰。peak-rich 相を希釈しない)。``"coverage"`` は旧方式 (一致率+被覆率)。
      peak-rich 相の希釈が疑わしいときの比較用。
    :param refine_lattice: True で各候補の計算ピークを等方格子歪み+ゼロシフトで観測へ整合してから
      スコアする (Dara フロー)。MP(DFT) 構造は格子が実測とずれるため、DFT 由来の候補を使うときに使う。
    :param max_strain: ``refine_lattice`` 時の等方歪み上限 (① と同じ既定 0.01 = 1%)。
    :param strain_penalty: ランキングで格子シフトを罰する係数。実効スコア = score − strain_penalty·|strain|
      (① と同じ既定 0 = 無効)。
    :param rerank_top_k: >0 で上位 K 候補のみ異方格子整合で再スコアする (① と同じ既定 5 でオン)。
      0 で無効化。DFT の軸別格子誤差 (Issue #20) を吸収し識別マージンを上げる。
    :param kalpha2: Kα2 サテライト設定の JSON dict
      (``{"intensity_ratio": float, "wavelength_ratio": float}``、両フィールドとも省略可・省略時は
      Cu Kα1/Kα2 既定)。**Kα2 未除去の実験室 X 線データ**にのみ使う — 除去済みデータに指定すると
      二重補正になるため使わないこと。不正なキー/型 (dict でない・未知キー・非数値) は例外を送出せず
      ``{"error", "error_type":"ValueError"}`` へ縮退する (静かに無視すると指定した補正が効かない
      「呼べるが黙って間違う」を再導入するため)。
    Raises:
        なし (供給元未設定・不正な kalpha2 spec は error dict へ縮退)。
    """
    provider = session.reference_provider
    if provider is None:
        return {"error": "reference_provider が AnalysisSession に設定されていません (相同定不可)。"}
    try:
        kalpha2_cfg = kalpha2_from_spec(kalpha2)
    except ValueError as exc:
        return {"error": str(exc), "error_type": "ValueError"}
    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    result = _identify_phases(
        two_theta,
        intensity,
        provider,
        elements=elements,
        hull_cutoff_ev=hull_cutoff_ev,
        max_results=max_results,
        subtract_bg=subtract_bg,
        scoring=scoring,
        refine_lattice=refine_lattice,
        max_strain=max_strain,
        strain_penalty=strain_penalty,
        rerank_top_k=rerank_top_k,
        kalpha2=kalpha2_cfg,
    )
    session.ledger.append(
        "mcp_identify", {"mode": "single", "n_elements": len(elements), "reason": reason}
    )
    return {
        "mode": "single",
        "matches": [
            {
                "phase_id": m.reference.phase_id,
                "formula": m.reference.formula,
                "element_system": list(m.reference.element_system),
                "score": finite_or_none(m.score),
                "energy_above_hull": finite_or_none(m.reference.energy_above_hull)
                if m.reference.energy_above_hull is not None
                else None,
                "strain": finite_or_none(m.strain),
            }
            for m in result.matches
        ],
        "unmatched": {
            "unknown_phase_flag": bool(result.unmatched.unknown_phase_flag),
            "unmatched_observed": [float(p.position) for p in result.unmatched.unmatched_observed],
            "extra_calculated": [float(x) for x in result.unmatched.extra_calculated],
        },
        "n_observed_peaks": len(result.observed_peaks),
    }


def identify_phase_mixtures(
    session: AnalysisSession,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    elements: Sequence[str],
    *,
    hull_cutoff_ev: float | None = 0.1,
    subtract_bg: bool = False,
    refine_lattice: bool = False,
    kalpha2: Mapping[str, object] | None = None,
    prefilter_top_k: int | None = None,
    prefilter_dynamic: bool = False,
    reason: str = "",
) -> dict:
    """未知パターン + 元素一覧から多相混合を同定する (M6 委譲境界)。🔵 FR-110/115

    【委譲】: ``session.reference_provider`` を供給元に ``reference.identify_phase_mixtures`` へ
      委譲し、既存木探索の ``SearchResult`` を ``/api/result`` スキーマ準拠 dict
      (``to_summary()``) で返す。供給元未設定なら error dict。破壊的操作なし (NFR-101)。

    :param subtract_bg: 同定前に SNIP 背景減算をオプトイン適用する (① と同じ既定 False)。
      観測パターンが**既に背景減算済み**の場合に True を渡すと二重減算になるため注意。
    :param refine_lattice: True で各候補の計算ピークを観測へ格子整合してから絞り込み/木探索に使う
      (DFT 緩和格子のピーク位置ずれを吸収, Dara フロー)。MP(DFT) 由来の候補を使うときに使う。
    :param kalpha2: Kα2 サテライト設定の JSON dict (``identify_phases`` と同じ変換規約:
      ``{"intensity_ratio": float, "wavelength_ratio": float}``、両フィールドとも省略可)。
      Kα2 未除去の実験室 X 線データにのみ使う (除去済みなら二重補正になるため None のまま)。
      不正なキー/型は ``{"error", "error_type":"ValueError"}`` へ縮退する (静かに無視しない)。
    :param prefilter_top_k: 絞り込みの安全上限。実効スコア上位 k 相のみ木探索へ渡す
      (多相で候補が多すぎるときに使う)。``prefilter_dynamic`` と併用可。
    :param prefilter_dynamic: True で動的閾値 (スコア分布の変曲点, Dara 準拠) を適用し、良い相を
      件数に依らず残す (固定 top-k より正解を落としにくい)。
    Raises:
        なし (供給元未設定・不正な kalpha2 spec は error dict へ縮退)。
    """
    provider = session.reference_provider
    if provider is None:
        return {"error": "reference_provider が AnalysisSession に設定されていません (相同定不可)。"}
    try:
        kalpha2_cfg = kalpha2_from_spec(kalpha2)
    except ValueError as exc:
        return {"error": str(exc), "error_type": "ValueError"}
    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    result = _identify_phase_mixtures(
        two_theta,
        intensity,
        provider,
        elements=elements,
        hull_cutoff_ev=hull_cutoff_ev,
        subtract_bg=subtract_bg,
        refine_lattice=refine_lattice,
        kalpha2=kalpha2_cfg,
        prefilter_top_k=prefilter_top_k,
        prefilter_dynamic=prefilter_dynamic,
    )
    session.ledger.append(
        "mcp_identify", {"mode": "mixture", "n_elements": len(elements), "reason": reason}
    )
    response = result.to_summary()
    response["mode"] = "mixture"
    return response


def identify_pattern(
    session: AnalysisSession,
    two_theta: np.ndarray,
    intensity: np.ndarray,
    elements: Sequence[str],
    *,
    max_phases: int = 5,
    snr_stop: float = 5.0,
    subtract_bg: bool = True,
    refine_lattice: bool = True,
    hull_cutoff_ev: float | None = 0.1,
    reason: str = "",
) -> dict:
    """未知パターン + 元素から相集合を**逐次減算で統一同定**する (M11, FR-118)。🔵

    【単相/多相統一】: ``identify_phases`` (単相ランキング) と ``identify_phase_mixtures`` (木探索) を
      統合したエントリ。1 相受理するごとに残差からその寄与を減算し、**残差 S/N が閾値 (snr_stop σ)
      未満**になるまで反復する。単相なら 1 相で停止、多相なら複数相を積み上げる (相数を事前に
      指定しない)。過剰適合は受理ゲート (未説明強度の相対減少 ∧ 最小スケール) が抑える。
    【委譲】: ``session.reference_provider`` を供給元に ``reference.iterative.identify_pattern`` へ。
      供給元未設定は error dict。深段 Rietveld 裁定 (``refiner``) は本経路では省略 (提案のみ)。
    【残差配列非跨ぎ】: ``residual_two_theta``/``residual_intensity`` は境界を越えさせず、受理相の
      要約のみ返す (§4.5)。

    :param max_phases: 反復上限 (安全網; 実際は snr_stop が停止を決める)
    :param snr_stop: 残差 S/N がこの未満で停止 (5σ = 結晶学の標準検出閾値)
    :param subtract_bg: 同定前の SNIP 背景減算
    :param refine_lattice: 提案時の等方格子整合 (DFT 格子ズレ吸収)
    :returns: ``accepted[]`` (受理相: phase_id/formula/element_system/scale/score/strain) +
      ``n_accepted``。破壊的操作なし (提案のみ)
    """
    provider = session.reference_provider
    if provider is None:
        return {"error": "reference_provider が AnalysisSession に設定されていません (相同定不可)。"}
    from ..reference.iterative import IdentifyConfig
    from ..reference.iterative import identify_pattern as _identify_pattern

    two_theta = np.asarray(two_theta, dtype=float)
    intensity = np.asarray(intensity, dtype=float)
    cfg = IdentifyConfig(
        max_phases=int(max_phases),
        snr_stop=float(snr_stop),
        subtract_bg=bool(subtract_bg),
        refine_lattice=bool(refine_lattice),
        hull_cutoff_ev=hull_cutoff_ev,
    )
    result = _identify_pattern(
        two_theta, intensity, provider, elements=list(elements), cfg=cfg, ledger=session.ledger
    )
    session.ledger.append(
        "mcp_identify", {"mode": "iterative", "n_elements": len(elements), "reason": reason}
    )
    return {
        "mode": "iterative",
        "accepted": [
            {
                "phase_id": a.reference.phase_id,
                "formula": a.reference.formula,
                "element_system": list(a.reference.element_system),
                "scale": finite_or_none(a.scale),
                "score": finite_or_none(a.score),
                "strain": finite_or_none(a.strain),
                "source": a.source,
            }
            for a in result.accepted
        ],
        "n_accepted": len(result.accepted),
    }


def list_review_queue(session: AnalysisSession, *, include_resolved: bool = False) -> dict:
    """Review Queue の内容を返す (Issue #125)。② から ReviewQueue を読む唯一の経路。

    【背景】: ``ReviewQueue`` は ``FinalSelectionEngine.decide()``/``accept()`` がエスカレーション
      成立時に通知する追記型キューで、① には実装済みだったが ② に露出しておらず積まれた内容を
      人間が確認する手段が無かった (DOA)。``accept_hypothesis`` は ``selection.accept`` を直接呼ぶ
      経路だが、``FinalSelectionEngine.accept`` 自体がエスカレーション検出時に queue へ通知する
      よう修正済みなので、本ツールは常に空を返す DOA にはならない。
    【委譲】: ``session.selection.review_queue`` (``FinalSelectionEngine.review_queue`` プロパティ)
      から ``ReviewQueue`` を取得し、``items``/``unresolved`` を素の型 list[dict] に変換して返す。
    【queue 未注入 (error 縮退)】: ``review_queue`` が ``None`` (未注入) のときは **「0 件」と
      答えず** error dict へ縮退する (② の空/不正入力契約 — 0 件は「注入されていて中身が空」と
      「そもそも注入されていない」を区別しないと危険な誤情報になる)。
    【既定は未解決のみ】: ``include_resolved=False`` (既定) は ``unresolved`` のみを返す。
      ``include_resolved=True`` で解決済みも含めた全件 (``items``) を返す。
    【テスト対応】: tests/mcp/test_review_tools.py の list_review_queue 系。

    :param include_resolved: True で解決済みも含めた全件を返す (既定は未解決のみ)
    :returns: 成功時 ``{"status":"ok","items":[...],"unresolved_count":N,"total_count":M}``。
      queue 未注入時は ``{"status":"error","error":...,"error_type":"no_review_queue"}``
    """
    queue = session.selection.review_queue
    if queue is None:
        return {
            "status": "error",
            "error": "review_queue が FinalSelectionEngine に注入されていません (確認事項の蓄積が"
            "行われていない可能性)。",
            "error_type": "no_review_queue",
        }
    source = queue.items if include_resolved else queue.unresolved
    return {
        "status": "ok",
        "items": [
            {
                "item_id": it.item_id,
                "reason": it.reason,
                "hypothesis_id": it.hypothesis_id,
                "frame_index": it.frame_index,
                "detail": it.detail,
                "resolved": it.resolved,
            }
            for it in source
        ],
        "unresolved_count": len(queue.unresolved),
        "total_count": len(queue.items),
    }


def resolve_review_item(session: AnalysisSession, item_id: str, *, note: str = "") -> dict:
    """Review Queue の 1 件を解決済みにする (Issue #125)。**人間の裁定を記録する操作**。

    【権限境界】: これは人間がエスカレーション事項を確認・裁定したことを記録する操作であり、
      ③ (agent) が独断で呼んではならない (SKILL.md の権限境界節に準拠)。ユーザーの確認を経てから
      呼ぶこと。
    【委譲】: ``session.selection.review_queue.resolve(item_id, note=note)`` へ委譲する
      (``ReviewQueue.resolve`` は削除でなく resolved=True への状態遷移, P2)。
    【未知 item_id (② は例外を送出しない)】: ``ReviewQueue.resolve`` は未知 item_id で ``KeyError``
      を送出する (① の誤操作防御)。② はこれを捕捉して error dict へ縮退する (③ は LLM なので
      例外は回復不能なハード失敗になるため)。
    【queue 未注入】: ``list_review_queue`` と同様 error dict へ縮退する。
    【テスト対応】: tests/mcp/test_review_tools.py の resolve_review_item 系。

    :param item_id: 解決する ReviewItem の item_id ("rq-0000" 形式)
    :param note: 解決理由の自然言語メモ (任意)
    :returns: 成功時 ``{"status":"resolved","item_id":...,"unresolved_count":N}``。
      queue 未注入/未知 item_id は ``{"status":"error","error":...,"error_type":...}``
    """
    queue = session.selection.review_queue
    if queue is None:
        return {
            "status": "error",
            "error": "review_queue が FinalSelectionEngine に注入されていません。",
            "error_type": "no_review_queue",
        }
    try:
        queue.resolve(item_id, note=note)
    except KeyError:
        return {
            "status": "error",
            "error": f"未知の item_id です: {item_id}",
            "error_type": "unknown_item_id",
        }
    return {
        "status": "resolved",
        "item_id": item_id,
        "unresolved_count": len(queue.unresolved),
    }


# 【ツールレジストリ】: 10 ツール (M4 8 + M6 相同定 2) + M8 実構造 Rietveld 3 + M9 in situ 逐次 3
#   + M8-③ MEM model-fix 3 + operando 診断 4 + M10 anchor 1 = 24 ツール名 → 実処理関数。アダプタ層
#   (server.py) が配線に使う単一情報源 🔵 REQ-021。M8 の 3 ツール (auto_rietveld/propose_next_actions/
#   refine_with_revisions)・M9 の 3 ツール (sequential_rietveld/identify_and_add_phase/
#   parametric_fit)・M8-③ の 3 ツール (mem_density/propose_structure_revisions/edit_cif)・operando
#   診断の 4 ツール (assess_data_quality/residual_report/check_phase_set/repair_frames)・M10 anchor の
#   1 ツール (anchored_sequential, Issue #97) は session を取らない計器+アクチュエータ
#   (rietveld_tools.py / insitu_tools.py / mem_tools.py / operando_diag_tools.py / anchor_tools.py,
#   閉ループ丸ごとは出さない = ③ が回す, architecture.md §2/§6)。
MCP_TOOLS: Mapping[str, object] = {
    "submit_analysis": submit_analysis,
    "list_hypotheses": list_hypotheses,
    "compare_hypotheses": compare_hypotheses,
    "accept_hypothesis": accept_hypothesis,
    "revert": revert,
    "get_trajectory": get_trajectory,
    "export_gpx": export_gpx,
    "run_mem": run_mem,
    "identify_phases": identify_phases,
    "identify_phase_mixtures": identify_phase_mixtures,
    "identify_pattern": identify_pattern,
    "propose_discriminating_measurements": propose_discriminating_measurements,
    "list_review_queue": list_review_queue,
    "resolve_review_item": resolve_review_item,
    **_RIETVELD_TOOLS,
    **_INSITU_TOOLS,
    **_MEM_MODEL_TOOLS,
    **_OPERANDO_DIAG_TOOLS,
    **_ANCHOR_TOOLS,
    **_COMPARE_TOOLS,
    **_ECHEM_TOOLS,
    **_INTEROP_TOOLS,
}
