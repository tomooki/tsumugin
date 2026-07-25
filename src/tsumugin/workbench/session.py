"""`WorkbenchSession` — Ledger / SnapshotStore / ReviewQueue / FinalSelectionEngine を束ねる
操作系 GUI の可変セッション (`docs/design/gui-workbench/architecture.md` §バックエンド)。

内部の各ストアは既存 API (``Ledger.append``/``SnapshotStore.save``/``ReviewQueue.add``/``resolve``/
``FinalSelectionEngine.accept``/``revert``/``set_mode``) のみを使い、削除・上書き API を一切
実装しない (P2 / NFR-GUI-001)。GUI 語彙 (manual/auto) ↔ エンジン語彙 (human/agent) の写像は
本モジュールが一手に引き受ける (FR-402)。

モード制御 (FR-402): ``final_selection_mode`` の実行時単一情報源は
``FinalSelectionEngine.mode``。``FinalSelectionEngine.set_mode`` は呼ぶたびに無条件で
``ledger.append("selection_set_mode", ...)`` する (エンジン側の既存契約, `selection/engine.py`
L142-153)。同一モードへの切替を no-op (ledger 追記なし) にするため、``WorkbenchSession.set_mode``
は engine を呼ぶ前に現在の GUI モードと比較し、変更が無ければ engine を一切呼ばない
(二重追記を避ける — engine 側が追記するならそれに任せ、session 側では追記しない)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from ..selection.engine import FinalSelectionEngine
from ..selection.review_queue import ReviewQueue
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from . import seed as _seed

if TYPE_CHECKING:  # 【型のみ参照】: 実行時 import は不要 (numpy 汚染回避と同じ流儀) 🔵
    from ..model import PhaseInstance
    from ..search.tree import SearchResult

GuiMode = Literal["manual", "auto"]
EngineMode = Literal["human", "agent"]

_GUI_TO_ENGINE: dict[str, EngineMode] = {"manual": "human", "auto": "agent"}
_ENGINE_TO_GUI: dict[str, GuiMode] = {"human": "manual", "agent": "auto"}

# 【actor 色分けキー】: ledger.kind → LEDGER タブの actor 列 (api-contract.md 末尾) 🔵
_ACTOR_BY_KIND: dict[str, str] = {
    "selection_set_mode": "HUMAN",
    "selection_accept": "CORE ①",
    "selection_revert": "CORE ①",
    "snapshot_save": "CORE ①",
    "snapshot_revert": "CORE ①",
    "review_add": "GUARD",
    "review_resolve": "HUMAN",
    "stage_action": "HUMAN",
    "refine_request": "HUMAN",
    "transcript_message": "HUMAN",
    "approval_decision": "AGENT ③",
    "accept_reason": "HUMAN",
}


def _actor_for_kind(kind: str) -> str:
    return _ACTOR_BY_KIND.get(kind, "CORE ①")


def _text_for_kind(kind: str, payload: dict[str, Any], *, mode_from: str = "") -> str:
    """ledger エントリ 1 件の人間可読テキストを kind ごとに組み立てる (LEDGER タブ表示用)。"""
    if kind == "selection_set_mode":
        mode_to = _ENGINE_TO_GUI.get(str(payload.get("mode")), str(payload.get("mode")))
        prefix = f"{mode_from} → " if mode_from else ""
        return f"mode switch {prefix}{mode_to}"
    if kind == "selection_accept":
        return f"accept {payload.get('hypothesis_id')} by {payload.get('by')}"
    if kind == "selection_revert":
        return f"revert {payload.get('hypothesis_id')}"
    if kind == "snapshot_save":
        return f"snapshot {payload.get('snapshot_id')} saved ({payload.get('label')})"
    if kind == "snapshot_revert":
        return f"snapshot revert → {payload.get('snapshot_id')}"
    if kind == "review_add":
        return f"review add {payload.get('item_id')} ({payload.get('reason')})"
    if kind == "review_resolve":
        return f"review resolve {payload.get('item_id')}"
    if kind == "stage_action":
        return f"stage {payload.get('nn')} {payload.get('action')}"
    if kind == "refine_request":
        return "refine requested"
    if kind == "transcript_message":
        return "transcript message posted"
    if kind == "approval_decision":
        return f"approval {payload.get('action_id')} {payload.get('decision')}"
    if kind == "accept_reason":
        return f"accept reason: {payload.get('reason')}"
    return kind


class WorkbenchSession:
    """操作系ワークベンチ 1 セッション分の可変状態を束ねる (frozen でない)。

    Ledger/SnapshotStore/ReviewQueue/FinalSelectionEngine の実体を保持し、GUI からの各操作を
    対応するストア API へ委譲しつつ、必要な箇所のみ ledger に理由付きで追記する。structure apply /
    approval approve は ``SnapshotStore.save`` で子スナップショットも作る (REQ-GUI-008/009)。
    """

    def __init__(self, *, mode: GuiMode = "manual") -> None:
        if mode not in _GUI_TO_ENGINE:
            raise ValueError(f"unknown mode: {mode!r}")
        self.ledger = Ledger()
        self.snapshots = SnapshotStore(ledger=self.ledger)
        self.review_queue = ReviewQueue(ledger=self.ledger)
        self.engine = FinalSelectionEngine(
            mode=_GUI_TO_ENGINE[mode], ledger=self.ledger, queue=self.review_queue
        )
        self._initial_gui_mode: GuiMode = mode
        self.project: dict[str, Any] = _seed.seed_project()
        self._agent_base: dict[str, Any] = _seed.seed_agent_status()
        self._status: dict[str, Any] = _seed.seed_status()

        self._search_result: "SearchResult | None" = None
        self._hyp_rows: list[dict[str, Any]] = []
        self._stages: list[dict[str, Any]] = _seed.seed_stages()
        self._transcript: list[dict[str, Any]] = []
        self._approvals: dict[str, dict[str, Any]] = {}
        self._review_meta: dict[str, dict[str, str]] = {}
        self._review_state: dict[str, str] = {}
        self._structure_sites: list[dict[str, Any]] = []
        self._structure_phases: "tuple[PhaseInstance, ...]" = ()

    # ------------------------------------------------------------------
    # デモシード構築
    # ------------------------------------------------------------------

    @classmethod
    def create_demo(cls) -> "WorkbenchSession":
        """決定論シード状態で構築する (UI ハンドオフのプロトタイプ同値)。

        Review Queue にハンドオフ 4 項目 (close competitor / unindexed peaks / guard fired 3× /
        coulometric feasibility infeasible) を追加し、stages 8 段・transcript・structure sites 等
        をシードする。
        """
        session = cls(mode="manual")
        session._search_result = _seed.build_seed_search_result()
        session._hyp_rows = _seed.seed_hypotheses_rows()
        session._transcript = _seed.seed_transcript()
        session._structure_sites = _seed.seed_structure_sites()
        session._structure_phases = (_seed.seed_structure_base_phase(),)

        for entry in _seed.seed_review_items():
            item = session.review_queue.add(
                entry["reason"],
                hypothesis_id=entry["hypothesis_id"],
                frame_index=entry["frame_index"],
                detail=entry["detail"],
            )
            session._review_meta[item.item_id] = {
                "severity": entry["severity"], "title": entry["title"], "ref": entry["ref"],
            }
        return session

    # ------------------------------------------------------------------
    # モード (FR-402)
    # ------------------------------------------------------------------

    @property
    def mode(self) -> GuiMode:
        """現在の GUI モード (``final_selection_mode`` の GUI 語彙写像)。"""
        return _ENGINE_TO_GUI[self.engine.mode]

    def set_mode(self, gui_mode: str) -> bool:
        """GUI モードを切替える。同一モードへの切替は no-op (ledger 追記なし) で ``False`` を返す。

        変更時は ``FinalSelectionEngine.set_mode`` を呼ぶ (エンジン側が ``selection_set_mode`` を
        ledger に追記する契約なので session 側では二重追記しない)。不正値は ``ValueError``。
        """
        if gui_mode not in _GUI_TO_ENGINE:
            raise ValueError(f"unknown mode: {gui_mode!r}")
        if gui_mode == self.mode:
            return False
        self.engine.set_mode(_GUI_TO_ENGINE[gui_mode])
        return True

    # ------------------------------------------------------------------
    # GET /api/state
    # ------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        agent = dict(self._agent_base)
        agent["idle"] = self.mode == "manual"
        return {
            "project": dict(self.project),
            "mode": self.mode,
            "final_selection_mode": self.engine.mode,
            "ledger": {"count": len(self.ledger.entries), "verified": self.ledger.verify()},
            "status": dict(self._status),
            "agent": agent,
        }

    # ------------------------------------------------------------------
    # GET /api/viewmodel
    # ------------------------------------------------------------------

    def viewmodel(self) -> dict[str, Any]:
        seeded_snapshots = _seed.seed_snapshots()
        live_snapshots = [{"id": s.id, "note": s.label} for s in self.snapshots.snapshots]
        return {
            "datasets": _seed.seed_datasets(),
            "phases": _seed.seed_phases(),
            "channels": _seed.seed_channels(),
            "snapshots": seeded_snapshots + live_snapshots,
            "fit": _seed.seed_fit(),
            "parameters": _seed.seed_parameters(),
            "hypotheses": self.hypotheses_view(),
            "phase_id": _seed.seed_phase_id(),
            "sequence": _seed.seed_sequence(),
            "structure": self._structure_view(),
            "stages": [dict(s) for s in self._stages],
            "review": self.review_view(),
            "transcript": self._transcript_view(),
        }

    def _structure_view(self) -> dict[str, Any]:
        return {
            "sites": [dict(s) for s in self._structure_sites],
            "constraints": _seed.seed_structure_constraints(),
            "mem_peaks": _seed.seed_mem_peaks(),
        }

    def _transcript_view(self) -> list[dict[str, Any]]:
        rows = []
        for msg in self._transcript:
            row = dict(msg)
            if row.get("kind") == "approval":
                info = self._approvals.get(row.get("action_id"))
                if info is not None:
                    row["state"] = info["state"]
            rows.append(row)
        return rows

    # ------------------------------------------------------------------
    # GET /api/hypotheses, POST /api/hypotheses/{id}/accept, POST /api/revert
    # ------------------------------------------------------------------

    def hypotheses_view(self) -> dict[str, Any]:
        return {
            "rows": [dict(r) for r in self._hyp_rows],
            "diff": _seed.seed_hypotheses_diff(),
            "evidence": _seed.seed_hypotheses_evidence(),
        }

    def accept_hypothesis(
        self, hypothesis_id: str, *, by: Literal["human", "agent"], reason: str = ""
    ) -> dict[str, Any]:
        """指定仮説を accept する。human モードで by="agent" は書き込まず recommend_only。

        MANUAL (human) モードでは③=人間が最終判断者であるため、エージェント発の accept 要求は
        提案 (recommend_only) に留め、実際の accept 化 (ledger 追記) は行わない
        (proposal ≠ application, REQ-GUI-009 と同じ原則)。
        """
        if self.engine.mode == "human" and by == "agent":
            return {"status": "recommend_only", "hypothesis_id": hypothesis_id}
        if self._search_result is None or hypothesis_id not in self._search_result.hypotheses:
            return {"error": f"unknown hypothesis id: {hypothesis_id}", "error_type": "NotFoundError"}
        if reason:
            self.ledger.append("accept_reason", {"hypothesis_id": hypothesis_id, "reason": reason})
        self.engine.accept(self._search_result, hypothesis_id, by=by)
        for row in self._hyp_rows:
            row["selected"] = row["id"] == hypothesis_id
            if row["id"] == hypothesis_id:
                row["status"] = "accepted"
        return {"status": "accepted", "hypothesis_id": hypothesis_id}

    def revert_hypothesis(self, hypothesis_id: str, *, note: str = "") -> dict[str, Any]:
        try:
            self.engine.revert(hypothesis_id, note=note)
        except KeyError:
            return {"error": f"hypothesis not accepted: {hypothesis_id}", "error_type": "NotFoundError"}
        for row in self._hyp_rows:
            if row["id"] == hypothesis_id:
                row["status"] = "reverted"
                row["selected"] = False
        return {"status": "reverted"}

    # ------------------------------------------------------------------
    # GET /api/review-queue, POST /api/review-queue/{id}/resolve
    # ------------------------------------------------------------------

    def review_view(self) -> list[dict[str, Any]]:
        rows = []
        for item in self.review_queue.items:
            meta = self._review_meta.get(item.item_id, {})
            state = self._review_state.get(item.item_id, "pending")
            rows.append(
                {
                    "id": item.item_id,
                    "severity": meta.get("severity", "info"),
                    "title": meta.get("title", item.reason),
                    "ref": meta.get("ref", ""),
                    "detail": item.detail,
                    "state": state,
                }
            )
        return rows

    def resolve_review_item(
        self, item_id: str, *, action: Literal["accept", "send_back"], note: str = ""
    ) -> dict[str, Any]:
        existing = next((it for it in self.review_queue.items if it.item_id == item_id), None)
        if existing is None:
            return {"error": f"unknown review item: {item_id}", "error_type": "NotFoundError"}
        if existing.resolved:
            return {"error": f"review item already resolved: {item_id}", "error_type": "ConflictError"}
        note_text = f"{action}: {note}" if note else action
        resolved = self.review_queue.resolve(item_id, note=note_text)
        state = "accepted" if action == "accept" else "sent_back"
        self._review_state[item_id] = state
        meta = self._review_meta.get(item_id, {})
        return {
            "item": {
                "id": resolved.item_id,
                "severity": meta.get("severity", "info"),
                "title": meta.get("title", resolved.reason),
                "ref": meta.get("ref", ""),
                "detail": resolved.detail,
                "state": state,
            }
        }

    # ------------------------------------------------------------------
    # GET /api/ledger
    # ------------------------------------------------------------------

    def ledger_view(self) -> dict[str, Any]:
        entries: list[dict[str, Any]] = []
        current_gui_mode: GuiMode = self._initial_gui_mode
        for entry in self.ledger.entries:
            mode_from = current_gui_mode if entry.kind == "selection_set_mode" else ""
            text = _text_for_kind(entry.kind, dict(entry.payload), mode_from=mode_from)
            if entry.kind == "selection_set_mode":
                current_gui_mode = _ENGINE_TO_GUI.get(str(entry.payload.get("mode")), current_gui_mode)
            revert_to = None
            if entry.kind == "snapshot_revert":
                revert_to = entry.payload.get("snapshot_id")
            entries.append(
                {
                    "index": entry.index,
                    "time": f"t+{entry.index:04d}",
                    "actor": _actor_for_kind(entry.kind),
                    "text": text,
                    "hash": entry.hash,
                    "revert_to": revert_to,
                }
            )
        return {"entries": entries, "verified": self.ledger.verify()}

    # ------------------------------------------------------------------
    # POST /api/structure/apply
    # ------------------------------------------------------------------

    def apply_structure(self, sites: list[dict[str, Any]], *, note: str = "") -> dict[str, Any]:
        """working model (sites) を ``ReviseStructure`` として適用する (子スナップショット + ledger)。

        提案 ≠ 適用: STRUCTURE タブでの編集は working model のみを変え、本メソッド呼び出しが
        明示的な適用操作 (REQ-GUI-008)。占有率は site の ``label`` をキーに ``occupancies`` へ写す。
        """
        occupancies: dict[str, float] = {}
        for site in sites:
            label = site.get("label") or site.get("id")
            occ = site.get("occ")
            if label is None or occ is None:
                continue
            try:
                occupancies[str(label)] = float(occ)
            except (TypeError, ValueError):
                continue
        base = self._structure_phases[0] if self._structure_phases else _seed.seed_structure_base_phase()
        new_phase = base.with_updates(occupancies=occupancies)
        self._structure_phases = (new_phase,) + tuple(self._structure_phases[1:])
        self._structure_sites = [dict(s) for s in sites]
        snap = self.snapshots.save(self._structure_phases, label=note or "ReviseStructure apply")
        return {"snapshot_id": snap.id, "ledger_index": self.ledger.entries[-1].index}

    # ------------------------------------------------------------------
    # POST /api/approval/{action_id}
    # ------------------------------------------------------------------

    def resolve_approval(self, action_id: str, *, decision: Literal["approve", "reject"]) -> dict[str, Any]:
        """AUTO transcript の ModelAction 承認カードを解決する (両経路 ledger、approve のみ snapshot)。"""
        if action_id in self._approvals:
            return {"error": f"approval already resolved: {action_id}", "error_type": "ConflictError"}
        known = any(
            msg.get("kind") == "approval" and msg.get("action_id") == action_id
            for msg in self._transcript
        )
        if not known:
            return {"error": f"unknown approval action: {action_id}", "error_type": "NotFoundError"}

        if decision == "approve":
            # 【単一 ledger 効果】: SnapshotStore.save 自体が ledger.append("snapshot_save", ...) するため、
            #   ここで追加の ledger.append は行わない (二重記録を避け、reject 経路と対称に 1 効果 = 1 追記)。
            #   action_id/decision は label に埋め込み LEDGER タブのテキストから追跡できるようにする。
            phases = self._structure_phases or (_seed.seed_structure_base_phase(),)
            snap = self.snapshots.save(phases, label=f"approval {action_id} approve")
            self._approvals[action_id] = {"state": "approved", "snapshot_id": snap.id}
            return {
                "state": "approved", "snapshot_id": snap.id, "ledger_index": self.ledger.entries[-1].index,
            }

        self.ledger.append("approval_decision", {"action_id": action_id, "decision": "reject"})
        self._approvals[action_id] = {"state": "rejected", "snapshot_id": None}
        return {"state": "rejected", "snapshot_id": None, "ledger_index": self.ledger.entries[-1].index}

    # ------------------------------------------------------------------
    # POST /api/stages/{nn}
    # ------------------------------------------------------------------

    def stage_action(self, nn: str, *, action: Literal["release", "revert"]) -> dict[str, Any]:
        stage = next((s for s in self._stages if s["nn"] == nn), None)
        if stage is None:
            return {"error": f"unknown stage: {nn}", "error_type": "NotFoundError"}
        stage["released"] = action == "release"
        self.ledger.append("stage_action", {"nn": nn, "action": action})
        return {"stage": dict(stage)}

    # ------------------------------------------------------------------
    # POST /api/refine
    # ------------------------------------------------------------------

    def request_refine(self) -> dict[str, Any]:
        """精密化要求を ledger 追記のみで受理する (v1: 実 GSAS runner は M-later)。"""
        self.ledger.append("refine_request", {})
        return {"status": "recorded"}

    # ------------------------------------------------------------------
    # POST /api/transcript/message
    # ------------------------------------------------------------------

    def post_message(self, text: str) -> dict[str, Any]:
        msg = {"id": f"t{len(self._transcript) + 1}", "kind": "user", "text": text}
        self._transcript.append(msg)
        self.ledger.append("transcript_message", {"text": text})
        return {"message": dict(msg)}
