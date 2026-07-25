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

import dataclasses
import math
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from .._json import finite_or_none
from ..autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from ..autorietveld.recipe import build_recipe
from ..model import LatticeParams, PhaseInstance
from ..selection.engine import FinalSelectionEngine
from ..selection.review_queue import ReviewQueue
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from . import lifecycle
from . import seed as _seed
from .jobs import RefinementJobManager, build_default_runner
from .project import WorkbenchProject, preview_pattern

if TYPE_CHECKING:  # 【型のみ参照】: 実行時 import は不要 (numpy 汚染回避と同じ流儀) 🔵
    from ..autorietveld.model import AutoRietveldResult
    from ..search.tree import SearchResult
    from ..store.persistent import PersistentLedger, PersistentSnapshotStore

GuiMode = Literal["manual", "auto"]
EngineMode = Literal["human", "agent"]
#: "none" = プロジェクト未読込 (Welcome 画面, V2a P1)。
GuiSource = Literal["demo", "project", "none"]

#: POST /api/project/histograms が受け付ける data_format (`reference.io._LOADERS` の語彙と同一)。
_VALID_DATA_FORMATS = frozenset({"XRDML", "FXYE", "GSAS", "XYE", "XY", "INT", "IGOR"})

#: POST /api/project/upload のファイルサイズ上限 (50MB, api-contract.md)。
_MAX_UPLOAD_BYTES = 50 * 1024 * 1024

#: source="none" (Welcome 画面) の project meta (api-contract.md GET /api/state)。
_EMPTY_PROJECT_META: dict[str, Any] = {"name": None, "dataset": None, "frame": None, "echem": None}

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
    "refine_finished": "CORE ①",
    "refine_failed": "CORE ①",
    "m7_stage": "CORE ①",
    "m7_stage_error": "GUARD",
    "transcript_message": "HUMAN",
    "approval_decision": "HUMAN",
    "accept_reason": "HUMAN",
    "project_edit": "HUMAN",
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
    if kind == "refine_finished":
        return f"refine finished (rwp={payload.get('rwp')})"
    if kind == "refine_failed":
        return f"refine failed: {payload.get('error')}"
    if kind == "m7_stage":
        return f"stage {payload.get('stage')} rwp={payload.get('rwp')}"
    if kind == "m7_stage_error":
        return f"stage {payload.get('stage')} error"
    if kind == "transcript_message":
        return "transcript message posted"
    if kind == "approval_decision":
        return f"approval {payload.get('action_id')} {payload.get('decision')}"
    if kind == "accept_reason":
        return f"accept reason: {payload.get('reason')}"
    if kind == "project_edit":
        return f"project edit: {payload.get('op')}"
    return kind


class WorkbenchSession:
    """操作系ワークベンチ 1 セッション分の可変状態を束ねる (frozen でない)。

    Ledger/SnapshotStore/ReviewQueue/FinalSelectionEngine の実体を保持し、GUI からの各操作を
    対応するストア API へ委譲しつつ、必要な箇所のみ ledger に理由付きで追記する。structure apply /
    approval approve は ``SnapshotStore.save`` で子スナップショットも作る (REQ-GUI-008/009)。
    """

    def __init__(
        self,
        *,
        mode: GuiMode = "manual",
        ledger: "Ledger | PersistentLedger | None" = None,
        snapshots: "SnapshotStore | PersistentSnapshotStore | None" = None,
    ) -> None:
        """
        :param mode: 初期 GUI モード。
        :param ledger: 注入する ledger 実体 (既定 ``None`` は in-memory ``Ledger()``, demo 用)。
            project モードでは ``open_persistent`` が ``PersistentLedger`` を注入する (P1)。
        :param snapshots: 注入する snapshot ストア (既定 ``None`` は ``ledger`` を束ねる
            in-memory ``SnapshotStore``)。``ledger`` を注入しても ``snapshots`` を省略すると
            in-memory のままになる点に注意 (``open_persistent`` は両方を揃えて渡す)。
        """
        if mode not in _GUI_TO_ENGINE:
            raise ValueError(f"unknown mode: {mode!r}")
        self.ledger = ledger if ledger is not None else Ledger()
        self.snapshots = snapshots if snapshots is not None else SnapshotStore(ledger=self.ledger)
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

        # 【実プロジェクト接続 (REQ-GUI-012/013)】: 既定は demo。``from_project`` が "project" へ切替える。
        self._source: GuiSource = "demo"
        self._project: "WorkbenchProject | None" = None
        self._project_path: "str | None" = None
        self._phases_view: list[dict[str, Any]] = []
        self._parameters_view: dict[str, Any] = {}
        self._fit: dict[str, Any] = {}
        self._job = RefinementJobManager(last_event=self._last_ledger_text)
        # 【viewmodel 更新系の直列化】: FastAPI sync ハンドラは threadpool 実行 + refine ジョブ
        #   スレッドが並走するため、project モードの完了コールバックはこのロック下で状態を更新する。
        self._lock = threading.Lock()

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

    @classmethod
    def from_project(
        cls,
        project: WorkbenchProject,
        *,
        ledger: "Ledger | PersistentLedger | None" = None,
        snapshots: "SnapshotStore | PersistentSnapshotStore | None" = None,
    ) -> "WorkbenchSession":
        """実プロジェクト spec (`project.load_project_spec`) からセッションを構築する (REQ-GUI-012)。

        demo のシード (hypotheses/phase_id/sequence/transcript/review) は持たない — 実データが無い
        領域は empty-state (空リスト/None) として正直に表示する (REQ-GUI-014 精神、シード値で
        実データを偽装しない)。datasets/phases/fit(プレビュー)/stages は実 project から構築する
        (ヒストグラム/相 0 件の作成直後プロジェクトでも空リストとして安全に構築できる)。

        :param ledger: 注入する ledger (既定 ``None`` は in-memory, テスト/`--project` CLI 用)。
            プロジェクトディレクトリへの永続配線は ``open_persistent`` を使う (P1)。
        :param snapshots: 注入する snapshot ストア (既定は ``ledger`` を束ねる in-memory)。
        """
        session = cls(mode="manual", ledger=ledger, snapshots=snapshots)
        session._source = "project"
        session._project = project
        session._project_path = _project_json_path(project)
        session.project = {
            "name": project.name,
            "dataset": f"{len(project.histograms)} histogram(s)",
            "frame": None,
            "echem": None,
        }
        session._phases_view = _initial_phases_view(project)
        session._parameters_view = _initial_parameters_view(project)
        session._fit = _initial_fit_view(project)
        session._stages = _stages_from_recipe(project)
        return session

    @classmethod
    def open_persistent(cls, project: WorkbenchProject) -> "WorkbenchSession":
        """``project.spec_dir`` に永続 ledger/snapshot を配線してプロジェクトセッションを開く (P1)。

        ``<spec_dir>/ledger.jsonl``/``<spec_dir>/snapshots.jsonl`` を ``PersistentLedger``/
        ``PersistentSnapshotStore`` で (再) オープンする。再起動を跨いでも監査履歴が続く
        (REQ-GUI-015)。既存ファイルが破損していれば ``LedgerIntegrityError``/
        ``SnapshotIntegrityError`` を送出する (呼び出し側 [`app.py`] が 4xx error dict へ縮退する、
        無修復 / P2)。
        """
        from ..store.persistent import PersistentLedger, PersistentSnapshotStore

        spec_dir = Path(project.spec_dir).resolve()
        ledger = PersistentLedger(spec_dir / "ledger.jsonl")
        snapshots = PersistentSnapshotStore(spec_dir / "snapshots.jsonl", ledger=ledger)
        return cls.from_project(project, ledger=ledger, snapshots=snapshots)

    @classmethod
    def create_empty(cls) -> "WorkbenchSession":
        """プロジェクト未読込の空セッション (``source="none"``, Welcome 画面用, REQ-GUI-017)。

        demo のシード表示を一切持たない — シードで実データ不在を偽装しない (REQ-GUI-014 精神)。
        """
        session = cls(mode="manual")
        session._source = "none"
        session.project = dict(_EMPTY_PROJECT_META)
        session._stages = []
        return session

    # ------------------------------------------------------------------
    # モード (FR-402)
    # ------------------------------------------------------------------

    @property
    def mode(self) -> GuiMode:
        """現在の GUI モード (``final_selection_mode`` の GUI 語彙写像)。"""
        return _ENGINE_TO_GUI[self.engine.mode]

    @property
    def source(self) -> GuiSource:
        """接続元 ("demo"|"project", REQ-GUI-012)。``from_project`` で "project" になる。"""
        return self._source

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
            "source": self._source,
            "refine": self.refine_status(),
            "project_path": self._project_path,
            "ledger": {"count": len(self.ledger.entries), "verified": self.ledger.verify()},
            "status": dict(self._status),
            "agent": agent,
        }

    # ------------------------------------------------------------------
    # GET /api/viewmodel
    # ------------------------------------------------------------------

    def viewmodel(self) -> dict[str, Any]:
        # 【シード使用は demo のみ】: "project"/"none" (V2a P1) はどちらも実データ不在を
        #   empty-state で正直に表示する (REQ-GUI-014 精神、シード値で実データを偽装しない)。
        use_seed = self._source == "demo"
        seeded_snapshots = _seed.seed_snapshots() if use_seed else []
        live_snapshots = [{"id": s.id, "note": s.label} for s in self.snapshots.snapshots]
        with self._lock:
            fit = _seed.seed_fit() if use_seed else dict(self._fit)
            phases = _seed.seed_phases() if use_seed else [dict(p) for p in self._phases_view]
            parameters = (
                _seed.seed_parameters()
                if use_seed
                else {k: dict(v) for k, v in self._parameters_view.items()}
            )
        vm: dict[str, Any] = {
            "datasets": self._datasets_view(),
            "phases": phases,
            "channels": _seed.seed_channels() if use_seed else [],
            "snapshots": seeded_snapshots + live_snapshots,
            "fit": fit,
            "parameters": parameters,
            "hypotheses": self.hypotheses_view(),
            "phase_id": _seed.seed_phase_id() if use_seed else _EMPTY_PHASE_ID,
            "sequence": _seed.seed_sequence() if use_seed else _EMPTY_SEQUENCE,
            "structure": self._structure_view(),
            "stages": [dict(s) for s in self._stages],
            "review": self.review_view(),
            "transcript": self._transcript_view(),
        }
        project_config = self._project_config_view()
        if project_config is not None:
            vm["project"] = project_config
        return vm

    def _project_config_view(self) -> "dict[str, Any] | None":
        """PROJECT タブ用の入力設定 echo (V2a, api-contract.md ``viewmodel.project``)。

        ``HistogramSpec``/``PhaseSpec``/精密化設定を 1:1 で映す (PROJECT タブのフォーム初期値・
        一覧表示用)。project モードでのみ供給し、demo/none は ``None`` (呼び出し元がキー自体を
        省略する — 契約注記どおり「省略 = 空表示。行を偽装しない」)。
        """
        if self._source != "project" or self._project is None:
            return None
        project = self._project
        histograms = [
            {
                "id": f"h{i}",
                "data_path": h.data_path,
                "instrument_path": h.instrument_path,
                "radiation": h.radiation.value,
                "geometry": h.geometry.value,
                "data_format": h.data_format,
                "two_theta_limits": list(h.two_theta_limits) if h.two_theta_limits else None,
                "bank": h.bank,
            }
            for i, h in enumerate(project.histograms)
        ]
        phases = [
            {"name": p.phase_name, "structure_path": p.structure_path} for p in project.phases
        ]
        limits = project.histograms[0].two_theta_limits if project.histograms else None
        settings = {
            "two_theta_limits": list(limits) if limits else None,
            "background_coeffs": project.background_coeffs,
            "max_cyc": project.max_cyc,
        }
        return {"histograms": histograms, "phases": phases, "settings": settings}

    def _datasets_view(self) -> list[dict[str, Any]]:
        if self._source == "demo":
            return _seed.seed_datasets()
        if self._source != "project" or self._project is None:
            return []
        rows = []
        for i, h in enumerate(self._project.histograms):
            rows.append(
                {
                    "id": f"h{i}",
                    "name": os.path.basename(h.data_path),
                    "meta": h.radiation.value,
                    "probe": "N" if h.radiation.is_neutron else "X",
                    "active": i == 0,
                }
            )
        return rows

    def _structure_view(self) -> dict[str, Any]:
        if self._source != "demo":
            return {
                "sites": [dict(s) for s in self._structure_sites],
                "constraints": [],
                "mem_peaks": [],
            }
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
        """精密化要求を受理する (REQ-GUI-013)。

        demo モード (source="demo") は従来どおり ledger 追記のみで即時受理する (後方互換)。
        project モードは実 ``run_auto_rietveld`` をバックグラウンドスレッドで起動する。実行中の
        二重起動は ``ConflictError`` (呼び出し側 [`app.py`] が 409 へ縮退) を返す。
        """
        if self._source == "demo":
            self.ledger.append("refine_request", {})
            return {"status": "recorded"}
        if self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        runner = build_default_runner(self._project, ledger=self.ledger)
        started = self._job.start(
            runner,
            on_success=self._on_refine_success,
            on_failure=self._on_refine_failure,
            # 【ledger 順序保証】: on_started はロック保持下・スレッド起動前に同期実行されるため、
            #   即座に失敗する runner との競合でも "refine_request" は必ず終了系エントリより先に
            #   現れる (RefinementJobManager.start docstring 参照)。
            on_started=lambda: self.ledger.append("refine_request", {}),
        )
        if not started:
            return {"error": "refinement already running", "error_type": "ConflictError"}
        return {"status": "started"}

    def refine_status(self) -> dict[str, Any]:
        """GET /api/refine/status 契約形を返す。"""
        return self._job.status()

    def _last_ledger_text(self) -> "str | None":
        """job manager の ``last_event`` に注入する callable: 直近 ledger エントリの表示テキスト。"""
        entries = self.ledger.entries
        if not entries:
            return None
        last = entries[-1]
        return _text_for_kind(last.kind, dict(last.payload))

    def _on_refine_success(self, result: "AutoRietveldResult") -> None:
        """精密化成功時のコールバック (RefinementJobManager が背景スレッドから呼ぶ)。

        純粋な整形処理 (metrics/history/validity/plot/phases) をロック外で計算し、副作用
        (viewmodel 更新・SnapshotStore.save・ledger 追記) のみをロック下で行う (部分適用を避ける)。
        整形処理が例外を送出した場合、ここでの副作用は一切実行されないまま `RefinementJobManager`
        側へ伝播し ``failed`` へ縮退する (例外貫通禁止は境界である job manager が担保する)。
        """
        project = self._project
        metrics = _build_fit_metrics(result)
        history = _build_fit_history(result.stage_results)
        validity_rows = _build_validity_rows(result.validity)
        plot: dict[str, Any] = {}
        if result.gpx_path and project is not None:
            from . import curves

            limits = [h.two_theta_limits for h in project.histograms]
            plot = curves.extract_curves(result.gpx_path, two_theta_limits=limits)
        phases_view = _build_phases_view(project, result) if project is not None else []
        snapshot_phases = (
            _phase_instances_from_result(project, result) if project is not None else ()
        )

        with self._lock:
            self._fit["metrics"] = metrics
            self._fit["history"] = history
            self._fit["validity"] = validity_rows
            if plot:
                self._fit["plot"] = plot
            if phases_view:
                self._phases_view = phases_view
            self._apply_hist_profile(result.hist_profile)
            self.snapshots.save(snapshot_phases, label="refine finished")
            self.ledger.append(
                "refine_finished",
                {"rwp": finite_or_none(result.final_rwp), "gof": finite_or_none(result.final_gof)},
            )

    def _on_refine_failure(self, exc: BaseException) -> None:
        """精密化失敗時のコールバック (RefinementJobManager が背景スレッドから呼ぶ)。"""
        with self._lock:
            self.ledger.append("refine_failed", {"error": str(exc)})

    def _apply_hist_profile(self, hist_profile: "tuple[Any, ...]") -> None:
        """精密化後の ``hist_profile`` で PARAMETERS の PROFILE カードを更新する (可能な範囲で)。

        呼び出し元 (`_on_refine_success`) がロックを保持している前提 (自前ロックしない)。
        """
        for i, prof in enumerate(hist_profile):
            hist_id = f"h{i}"
            view = self._parameters_view.get(hist_id)
            if view is None or not prof:
                continue
            for card in view.get("cards", []):
                if card.get("id") != "profile":
                    continue
                card["rows"] = [
                    _row(str(k), f"{v:.6g}", released=True) for k, v in sorted(dict(prof).items())
                ]
                card["note"] = "refined"
            view["released_count"] = len(prof)

    # ------------------------------------------------------------------
    # POST /api/project/upload, /histograms(/remove), /phases(/remove), /settings (P2)
    # ------------------------------------------------------------------

    def _guard_project_editable(self) -> "dict[str, Any] | None":
        """spec 変更系メソッドの共通ガード: project 未読込 (422) / refine 実行中 (409)。"""
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        if self._job.status()["status"] == "running":
            return {"error": "refinement is running", "error_type": "ConflictError"}
        return None

    def _save_and_refresh(self, op: str, payload: dict[str, Any]) -> None:
        """project.json へ自動保存 + ledger 追記 + PHASES/PARAMETERS/FIT/STAGES viewmodel 再構築。"""
        assert self._project is not None
        lifecycle.save_project_spec(self._project)
        self.ledger.append("project_edit", {"op": op, **payload})
        self._refresh_project_views()

    def _refresh_project_views(self) -> None:
        project = self._project
        assert project is not None
        with self._lock:
            self._phases_view = _initial_phases_view(project)
            self._parameters_view = _initial_parameters_view(project)
            self._fit = _initial_fit_view(project)
            self._stages = _stages_from_recipe(project)
            self.project = {
                "name": project.name,
                "dataset": f"{len(project.histograms)} histogram(s)",
                "frame": None,
                "echem": None,
            }

    def store_upload(self, filename: str, content: bytes) -> dict[str, Any]:
        """アップロードされたファイルをプロジェクト ``data/`` へコピーする (自己完結方式, REQ-GUI-016)。

        ファイル名は `lifecycle.sanitize_filename` でパス区切り等を除去し、同名衝突は連番で回避する。
        """
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        if len(content) > _MAX_UPLOAD_BYTES:
            return {"error": "file too large (max 50MB)", "error_type": "ValueError"}
        assert self._project is not None
        data_dir = Path(self._project.spec_dir) / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        safe_name = lifecycle.sanitize_filename(filename)
        target = data_dir / safe_name
        stem, suffix = target.stem, target.suffix
        i = 1
        while target.exists():
            target = data_dir / f"{stem}_{i}{suffix}"
            i += 1
        target.write_bytes(content)
        return {"stored_path": str(target)}

    def add_histogram(
        self,
        *,
        data_path: Any,
        instrument_path: Any,
        radiation: Any,
        geometry: Any,
        data_format: Any = "GSAS",
        two_theta_limits: Any = None,
        bank: Any = None,
    ) -> dict[str, Any]:
        """POST /api/project/histograms: spec へ 1 ヒストグラムを追記する (REQ-GUI-016)。"""
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        if not data_path or not instrument_path:
            return {"error": "data_path/instrument_path is required", "error_type": "ValueError"}
        try:
            rad = Radiation(radiation)
        except ValueError:
            return {"error": f"invalid radiation: {radiation!r}", "error_type": "ValueError"}
        try:
            geo = Geometry(geometry)
        except ValueError:
            return {"error": f"invalid geometry: {geometry!r}", "error_type": "ValueError"}
        fmt = str(data_format).upper()
        if fmt not in _VALID_DATA_FORMATS:
            return {"error": f"invalid data_format: {data_format!r}", "error_type": "ValueError"}
        limits: "tuple[float, float] | None" = None
        if two_theta_limits is not None:
            try:
                limits = (float(two_theta_limits[0]), float(two_theta_limits[1]))
            except (TypeError, ValueError, IndexError, KeyError):
                return {
                    "error": f"invalid two_theta_limits: {two_theta_limits!r}",
                    "error_type": "ValueError",
                }
        try:
            bank_val = int(bank) if bank is not None else None
        except (TypeError, ValueError):
            return {"error": f"invalid bank: {bank!r}", "error_type": "ValueError"}
        hist = HistogramSpec(
            data_path=str(data_path),
            instrument_path=str(instrument_path),
            radiation=rad,
            geometry=geo,
            data_format=fmt,
            two_theta_limits=limits,
            bank=bank_val,
        )
        assert self._project is not None
        self._project = dataclasses.replace(
            self._project, histograms=self._project.histograms + (hist,)
        )
        self._save_and_refresh("add_histogram", {"data_path": hist.data_path})
        return self.state()

    def remove_histogram(self, hist_id: str) -> dict[str, Any]:
        """POST /api/project/histograms/{hist_id}/remove: spec からヒストグラムを除去する。"""
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        assert self._project is not None
        idx = _hist_index(hist_id, len(self._project.histograms))
        if idx is None:
            return {"error": f"unknown histogram: {hist_id}", "error_type": "NotFoundError"}
        histograms = self._project.histograms[:idx] + self._project.histograms[idx + 1 :]
        self._project = dataclasses.replace(self._project, histograms=histograms)
        self._save_and_refresh("remove_histogram", {"hist_id": hist_id})
        return self.state()

    def add_phase(self, *, structure_path: Any, phase_name: Any) -> dict[str, Any]:
        """POST /api/project/phases: spec へ 1 相を追記する (REQ-GUI-016)。"""
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        if not structure_path or not phase_name:
            return {"error": "structure_path/phase_name is required", "error_type": "ValueError"}
        assert self._project is not None
        name = str(phase_name)
        if any(p.phase_name == name for p in self._project.phases):
            return {"error": f"phase already exists: {name}", "error_type": "ValueError"}
        phase = PhaseSpec(structure_path=str(structure_path), phase_name=name)
        self._project = dataclasses.replace(self._project, phases=self._project.phases + (phase,))
        self._save_and_refresh("add_phase", {"phase_name": name})
        return self.state()

    def remove_phase(self, phase_name: str) -> dict[str, Any]:
        """POST /api/project/phases/{phase_name}/remove: spec から相を除去する。"""
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        assert self._project is not None
        phases = tuple(p for p in self._project.phases if p.phase_name != phase_name)
        if len(phases) == len(self._project.phases):
            return {"error": f"unknown phase: {phase_name}", "error_type": "NotFoundError"}
        self._project = dataclasses.replace(self._project, phases=phases)
        self._save_and_refresh("remove_phase", {"phase_name": phase_name})
        return self.state()

    def update_settings(
        self,
        *,
        two_theta_limits: Any = None,
        background_coeffs: Any = None,
        max_cyc: Any = None,
    ) -> dict[str, Any]:
        """POST /api/project/settings: 精密化設定 (2θ範囲/背景項数/max_cyc) を更新する。"""
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        assert self._project is not None
        project = self._project
        if two_theta_limits is not None:
            try:
                lo, hi = float(two_theta_limits[0]), float(two_theta_limits[1])
            except (TypeError, ValueError, IndexError, KeyError):
                return {
                    "error": f"invalid two_theta_limits: {two_theta_limits!r}",
                    "error_type": "ValueError",
                }
            project = dataclasses.replace(
                project,
                histograms=tuple(
                    dataclasses.replace(h, two_theta_limits=(lo, hi)) for h in project.histograms
                ),
            )
        if background_coeffs is not None:
            try:
                project = dataclasses.replace(project, background_coeffs=int(background_coeffs))
            except (TypeError, ValueError):
                return {
                    "error": f"invalid background_coeffs: {background_coeffs!r}",
                    "error_type": "ValueError",
                }
        if max_cyc is not None:
            try:
                project = dataclasses.replace(project, max_cyc=int(max_cyc))
            except (TypeError, ValueError):
                return {"error": f"invalid max_cyc: {max_cyc!r}", "error_type": "ValueError"}
        self._project = project
        self._save_and_refresh("settings", {})
        return self.state()

    # ------------------------------------------------------------------
    # POST /api/transcript/message
    # ------------------------------------------------------------------

    def post_message(self, text: str) -> dict[str, Any]:
        msg = {"id": f"t{len(self._transcript) + 1}", "kind": "user", "text": text}
        self._transcript.append(msg)
        self.ledger.append("transcript_message", {"text": text})
        return {"message": dict(msg)}


# ---------------------------------------------------------------------------
# project モード viewmodel 構築ヘルパ (empty-state 契約, REQ-GUI-014)
# ---------------------------------------------------------------------------

#: project モードは実相同定/逐次解析が未接続 (v1 残存制約) — シード値で偽装せず空を返す。
_EMPTY_PHASE_ID: dict[str, Any] = {
    "candidates": [],
    "unexplained": [],
    "completeness": {"is_complete": None, "notes": [], "flagged_frames": ""},
}
_EMPTY_SEQUENCE: dict[str, Any] = {"charts": [], "anchors": [], "note": "", "segments": []}


def _project_json_path(project: WorkbenchProject) -> "str | None":
    """``GET /api/state`` の ``project_path`` (project.json の絶対パス)。

    テスト fixture 由来の ``WorkbenchProject`` (``spec_dir`` 既定 "." / 未設定) は ``None`` を返す
    (実プロジェクトディレクトリと結び付いていないため)。
    """
    if not project.spec_dir or project.spec_dir == ".":
        return None
    return str(Path(project.spec_dir).resolve() / lifecycle.PROJECT_JSON_NAME)


def _hist_index(hist_id: str, n_histograms: int) -> "int | None":
    """``"h{i}"`` 形式のヒストグラム id を index へ変換する (範囲外/不正形式は ``None``)。"""
    if not hist_id.startswith("h"):
        return None
    try:
        idx = int(hist_id[1:])
    except ValueError:
        return None
    if not (0 <= idx < n_histograms):
        return None
    return idx


def _row(field: str, value: str, esd: str = "", *, released: bool = False, locked: bool = False) -> dict[str, Any]:
    """PARAMETERS カードの 1 行 (`seed._row` と同一形; project モードは実値を渡す)。"""
    return {"field": field, "value": value, "esd": esd, "released": released, "locked": locked}


def _initial_phases_view(project: WorkbenchProject) -> list[dict[str, Any]]:
    """左レール PHASES の初期状態 (精密化前, wt_frac は未定なので "―")。"""
    rows: list[dict[str, Any]] = []
    for i, p in enumerate(project.phases):
        display = project.phase_display.get(p.phase_name, {})
        rows.append(
            {
                "id": f"p{i + 1}",
                "name": p.phase_name,
                "swatch": "accent" if i == 0 else "neutral",
                "space_group": str(display.get("space_group", "")),
                "mp_id": str(display.get("mp_id", "")),
                "wt_frac": "―",
            }
        )
    return rows


def _fmt_wt_frac(value: "float | None", esd: "float | None") -> str:
    if value is None:
        return "―"
    pct = value * 100.0
    if esd:
        return f"{pct:.1f}({esd * 100:.1f}) %"
    return f"{pct:.1f} %"


def _build_phases_view(
    project: "WorkbenchProject | None", result: "AutoRietveldResult"
) -> list[dict[str, Any]]:
    """精密化後の左レール PHASES (wt%±esd を `phase_weight_fractions`/`_esd` から反映)。"""
    if project is None:
        return []
    rows = _initial_phases_view(project)
    for row in rows:
        name = row["name"]
        wt = result.phase_weight_fractions.get(name)
        esd = result.phase_weight_fraction_esd.get(name)
        row["wt_frac"] = _fmt_wt_frac(wt, esd)
    return rows


def _initial_parameters_view(project: WorkbenchProject) -> dict[str, Any]:
    """PARAMETERS の初期状態: RADIATION は spec 由来の実値、PROFILE は精密化後に埋まる空カード。"""
    out: dict[str, Any] = {}
    for i, h in enumerate(project.histograms):
        hist_id = f"h{i}"
        cards = [
            {
                "id": "radiation",
                "title": "RADIATION / WAVELENGTH",
                "note": "spec",
                "rows": [
                    _row("radiation", h.radiation.value, locked=True),
                    _row("geometry", h.geometry.value, locked=True),
                ],
                "footer": "",
            },
            {
                "id": "profile",
                "title": "PROFILE",
                "note": "精密化前",
                "rows": [],
                "footer": "精密化後に hist_profile から実値を反映する。",
            },
        ]
        out[hist_id] = {"released_count": 0, "cards": cards}
    return out


def _initial_fit_view(project: WorkbenchProject) -> dict[str, Any]:
    """FIT の初期状態: metrics/history/validity は空 (精密化前)、plot は yobs のみのプレビュー。"""
    histograms_meta = [
        {"id": f"h{i}", "label": os.path.basename(h.data_path), "active": i == 0}
        for i, h in enumerate(project.histograms)
    ]
    plot: dict[str, Any] = {}
    for i, h in enumerate(project.histograms):
        try:
            plot[f"h{i}"] = preview_pattern(h)
        except (OSError, ValueError):
            plot[f"h{i}"] = None
    limits = project.histograms[0].two_theta_limits if project.histograms else None
    return {
        "metrics": [],
        "histograms": histograms_meta,
        "limits_note": f"background {project.background_coeffs} terms",
        "phase_ticks": [p.phase_name for p in project.phases],
        "two_theta": {"min": limits[0], "max": limits[1]} if limits else {"min": None, "max": None},
        "history": [],
        "validity": [],
        "plot": plot,
    }


def _stages_from_recipe(project: WorkbenchProject) -> list[dict[str, Any]]:
    """実 project から段階解放レシピを組み STAGES viewmodel の初期状態 (全未 release) を作る。"""
    try:
        recipe = build_recipe(
            project.histograms, project.phases, background_coeffs=project.background_coeffs
        )
    except ValueError:
        return []
    stages: list[dict[str, Any]] = []
    for i, stage in enumerate(recipe, start=1):
        flags = ", ".join(sorted(str(k) for k in stage.flags.keys())) if stage.flags else ""
        stages.append(
            {
                "nn": f"{i:02d}",
                "name": stage.label,
                "flags": flags,
                "delta_rwp": "",
                "released": False,
                "gate": None,
            }
        )
    return stages


def _build_fit_metrics(result: "AutoRietveldResult") -> list[dict[str, Any]]:
    """FIT メトリクス (Rwp/GOF/χ²/n_params/n_obs)。χ² = GOF²·(n_obs−n_params)。"""
    rwp = result.final_rwp
    gof = result.final_gof
    n_obs = result.n_obs
    n_params = result.stage_results[-1].n_params if result.stage_results else 0
    chi2 = None
    if gof is not None and n_obs and n_obs > n_params and math.isfinite(gof):
        chi2 = gof * gof * (n_obs - n_params)
    rwp_val = finite_or_none(rwp)
    gof_val = finite_or_none(gof)
    return [
        {"key": "rwp", "label": "Rwp", "value": f"{rwp_val:.2f}%" if rwp_val is not None else "―", "note": ""},
        {"key": "gof", "label": "GOF", "value": f"{gof_val:.2f}" if gof_val is not None else "―", "note": ""},
        {
            "key": "chi2", "label": "χ²",
            "value": f"{chi2:.0f}" if chi2 is not None else "―", "note": "",
        },
        {"key": "n_params", "label": "n_params", "value": str(n_params), "note": ""},
        {"key": "n_obs", "label": "n_obs", "value": str(n_obs), "note": ""},
    ]


def _build_fit_history(stage_results: "tuple[Any, ...]") -> list[dict[str, Any]]:
    """FIT history: 段階ごとの (stage, rwp, delta_rwp[隣接差分], guard, reverted)。"""
    rows: list[dict[str, Any]] = []
    prev_rwp: "float | None" = None
    for i, s in enumerate(stage_results, start=1):
        rwp_val = finite_or_none(s.rwp)
        delta = None if prev_rwp is None or rwp_val is None else rwp_val - prev_rwp
        rows.append(
            {
                "stage": f"{i:02d} {s.label}",
                "rwp": rwp_val,
                "delta_rwp": finite_or_none(delta),
                "guard": s.note if s.reverted else "",
                "reverted": bool(s.reverted),
            }
        )
        if rwp_val is not None:
            prev_rwp = rwp_val
    return rows


def _build_validity_rows(validity: "Any") -> list[dict[str, Any]]:
    """FIT validity: `ValidityReport.checks`→ pass/fail 行 + `warnings`→ warn 行。"""
    rows = [
        {"check": name, "status": "pass" if ok else "fail", "detail": detail}
        for name, ok, detail in validity.checks
    ]
    rows.extend({"check": "warning", "status": "warn", "detail": w} for w in validity.warnings)
    return rows


def _phase_instances_from_result(
    project: "WorkbenchProject | None", result: "AutoRietveldResult"
) -> "tuple[PhaseInstance, ...]":
    """精密化結果から STRUCTURE 適用/スナップショット用の `PhaseInstance` を組み立てる。

    座標は `AutoRietveldResult` に含まれないため (v1 残存制約)、占有率/格子/重量分率のみを反映する。
    """
    if project is None:
        return ()
    out: list[PhaseInstance] = []
    for p in project.phases:
        cell = result.refined_cells.get(p.phase_name)
        if cell is not None and len(cell) == 6:
            a, b, c, alpha, beta, gamma = (float(x) for x in cell)
            lattice = LatticeParams(a=a, b=b, c=c, alpha=alpha, beta=beta, gamma=gamma)
        else:
            lattice = LatticeParams(a=1.0, b=1.0, c=1.0)
        wt = result.phase_weight_fractions.get(p.phase_name)
        occ = {k: float(v) for k, v in dict(result.atom_occupancy.get(p.phase_name, {})).items()}
        out.append(PhaseInstance(phase_ref=p.phase_name, lattice=lattice, wt_frac=wt, occupancies=occ))
    return tuple(out)
