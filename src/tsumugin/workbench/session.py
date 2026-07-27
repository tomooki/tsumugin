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
import json
import math
import os
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Mapping, Sequence

import numpy as np

from .._json import finite_or_none
from ..autorietveld.model import Geometry, HistogramSpec, PhaseSpec, Radiation
from ..autorietveld.recipe import build_recipe
from ..backends.gsasii import gsasii_available
from ..errors import ConflictError
from ..insitu.model import FrameSpec
from ..model import LatticeParams, PhaseInstance
from ..selection.engine import FinalSelectionEngine
from ..selection.review_queue import ReviewQueue
from ..store.ledger import Ledger
from ..store.snapshot import SnapshotStore
from . import density as _density
from . import lifecycle
from . import seed as _seed
from . import settings as _settings
from .agent_bridge import AgentBridge
from .jobs import RefinementJobManager, build_default_runner
from .project import (
    WorkbenchProject,
    convert_frame_for_runner,
    convert_histogram_for_runner,
    preview_pattern,
)

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

#: `request_sequential` のハートビート間隔 (秒, api-contract.md「進捗 = ledger」の可視化)。
#: モジュールレベルにして単体テストが monkeypatch で短縮できるようにする。
_SEQUENTIAL_HEARTBEAT_INTERVAL_S = 15.0

#: source="none" (Welcome 画面) の project meta (api-contract.md GET /api/state)。
_EMPTY_PROJECT_META: dict[str, Any] = {"name": None, "dataset": None, "frame": None, "echem": None}

_GUI_TO_ENGINE: dict[str, EngineMode] = {"manual": "human", "auto": "agent"}
_ENGINE_TO_GUI: dict[str, GuiMode] = {"human": "manual", "agent": "auto"}

#: エージェント権限モード (`agent_policy`, api-contract.md §エージェント権限モード, FR-402 拡張)。
#: 人間が `POST /api/agent/policy` で切り替える — エージェント自身がこれを変更するツールは
#: shim (`agent_mcp`) に存在しない (自己昇格の禁止)。
AgentPolicy = Literal["approve", "auto", "bypass"]
_VALID_AGENT_POLICIES: "tuple[AgentPolicy, ...]" = ("approve", "auto", "bypass")

#: GSAS-II 必須ジョブ (refine/multistart/sequential) が不在環境で起動された場合の error dict
#: (Tier1 sidecar, api-contract.md GET /api/state `status.gsas_available`)。呼び出し側 (app.py)
#: が 422 へ縮退する。
_GSAS_UNAVAILABLE_ERROR: dict[str, Any] = {
    "error": "GSAS-II が見つかりません — 導入ガイド (desktop/README.md) を参照してください",
    "error_type": "GSASUnavailableError",
}

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
    "agent_proposal": "AGENT ③",
    "approval_decision": "HUMAN",
    "accept_reason": "HUMAN",
    "project_edit": "HUMAN",
    "phaseid_request": "HUMAN",
    "phaseid_finished": "CORE ①",
    "phaseid_failed": "GUARD",
    "multistart_request": "HUMAN",
    "multistart_finished": "CORE ①",
    "multistart_failed": "GUARD",
    "sequential_request": "HUMAN",
    "sequential_progress": "CORE ①",
    "sequential_finished": "CORE ①",
    "sequential_failed": "GUARD",
    "echem_finished": "CORE ①",
    "echem_failed": "GUARD",
    "agent_policy_change": "HUMAN",
    "approval_abandoned": "GUARD",
    "mem_request": "HUMAN",
    "mem_finished": "CORE ①",
    "mem_failed": "GUARD",
    "settings_change": "HUMAN",
}

#: 承認カード action_id 接頭辞 → kind (``abandon_pending_approvals`` が ledger payload に積む
#: 表示用ラベル)。np- (B5 新相提案) は ``create_proposal`` を経由しない固定 kind なので
#: `_PROPOSAL_KIND_PREFIX` の逆引きだけでは賄えない — 別途明示する。
_PREFIX_TO_PROPOSAL_KIND: dict[str, str] = {
    "np": "new_phase",
    "sr": "structure_revision",
    "rv": "review_resolution",
    "pc": "phase_change",
    "st": "settings_change",
}


#: 【ModelAction 起票, 2026-07-26 権限境界改訂】: `create_proposal` の kind → 承認カード
#: action_id 接頭辞 (api-contract.md §propose_* ツールと承認カード の表と同一)。
_PROPOSAL_KIND_PREFIX: dict[str, str] = {
    "structure_revision": "sr",
    "review_resolution": "rv",
    "phase_change": "pc",
    "settings_change": "st",
}

#: 承認カード (transcript kind=approval) の title (kind ごと)。
_PROPOSAL_TITLES: dict[str, str] = {
    "structure_revision": "エージェント提案: 構造改訂 (ReviseStructure)",
    "review_resolution": "エージェント提案: レビュー項目の解決",
    "phase_change": "エージェント提案: 相の追加/除去",
    "settings_change": "エージェント提案: 精密化設定の変更",
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
    if kind == "agent_proposal":
        return f"agent proposal {payload.get('action_id')} ({payload.get('kind')})"
    if kind == "approval_decision":
        return f"approval {payload.get('action_id')} {payload.get('decision')}"
    if kind == "accept_reason":
        return f"accept reason: {payload.get('reason')}"
    if kind == "project_edit":
        return f"project edit: {payload.get('op')}"
    if kind == "phaseid_request":
        return f"phase id requested ({payload.get('mode')})"
    if kind == "phaseid_finished":
        return f"phase id finished (n={payload.get('n_candidates')})"
    if kind == "phaseid_failed":
        return f"phase id failed: {payload.get('error')}"
    if kind == "multistart_request":
        return f"multistart requested (n_starts={payload.get('n_starts')})"
    if kind == "multistart_finished":
        return f"multistart finished (basins={payload.get('n_basins')})"
    if kind == "multistart_failed":
        return f"multistart failed: {payload.get('error')}"
    if kind == "sequential_request":
        return f"sequential requested (mode={payload.get('mode')})"
    if kind == "sequential_progress":
        return (
            f"sequential running (mode={payload.get('mode')}, "
            f"n_frames={payload.get('n_frames')}, elapsed={payload.get('elapsed_s')}s)"
        )
    if kind == "sequential_finished":
        return f"sequential finished (n_frames={payload.get('n_frames')})"
    if kind == "sequential_failed":
        return f"sequential failed: {payload.get('error')}"
    if kind == "echem_finished":
        return f"echem aligned (n_frames={payload.get('n_frames')})"
    if kind == "echem_failed":
        return f"echem failed: {payload.get('error')}"
    if kind == "agent_policy_change":
        return f"agent policy → {payload.get('policy')}"
    if kind == "approval_abandoned":
        return f"approval {payload.get('action_id')} ({payload.get('kind')}) abandoned: {payload.get('reason')}"
    if kind == "mem_request":
        return f"mem requested (map_type={payload.get('map_type')})"
    if kind == "mem_finished":
        return f"mem finished (n_peaks={payload.get('n_peaks')})"
    if kind == "mem_failed":
        return f"mem failed: {payload.get('error')}"
    if kind == "settings_change":
        # 【値を出さない】: payload は {"key","action"} のみ (契約の絶対規則) — テキストにも値は出ない。
        return f"settings {payload.get('key')} {payload.get('action')}"
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
        # 【ModelAction 起票, 2026-07-26 権限境界改訂】: `create_proposal` (POST /api/proposals) が
        #   起票した sr-/rv-/pc-/st- カードの kind/payload/rationale。resolve_approval の approve
        #   分岐 (`_resolve_generic_proposal`) が approve 時にここを引いて実操作を呼ぶ
        #   (`_np_approval_info` と同じ役割の一般化)。state (pending/approved/rejected) は
        #   従来どおり `self._approvals` が単一情報源 (`_transcript_view` 参照)。
        self._proposals: dict[str, dict[str, Any]] = {}
        self._proposal_seq: int = 0
        self._review_meta: dict[str, dict[str, str]] = {}
        self._review_state: dict[str, str] = {}
        self._structure_sites: list[dict[str, Any]] = []
        self._structure_phases: "tuple[PhaseInstance, ...]" = ()
        # 【A2/A3: 実サイト抽出と id→相ルーティング】: 直近 refine が gpx から抽出した実サイトの
        #   一意 id→相名 (占有率 revision (A3) を正しい相へ配線するための session 内部専用マップ、
        #   契約 Site スキーマには現れない)。**label でなく id をキーにする**
        #   (セルフレビュー指摘 #3): label (原子ラベル, 例 "O1") は相ごとに独立して付与されるため
        #   多相では衝突しうるが、`atoms.extract_sites` が振る `id` は全相を跨いで一意。
        self._site_phase_map: dict[str, str] = {}
        # 【A3: pending occ revisions】: apply_structure が適用した occ 編集のうち、次回 refine の
        #   runner 構築時に initial_occupancies として渡す分 (相名→{ラベル→occ})。refine 開始時に
        #   消費 (クリア) される。uiso は run_auto_rietveld に直接注入する API が無いため対象外。
        self._pending_occupancies: dict[str, dict[str, float]] = {}
        # 【A4: 相同定候補】: viewmodel.phase_id.candidates (project モード) + mp_id→AcceptedPhase
        #   (ADD AS PHASE 時の再物質化用、strain を引き継ぐ)。
        self._phaseid_candidates: list[dict[str, Any]] = []
        self._phaseid_accepted_by_id: dict[str, Any] = {}
        # 【A5: basin 散布 + corroborated evidence】: run_multistart_rietveld 完了で供給。
        #   None は「データなし (empty-state)」(api-contract.md)。
        self._basin: "dict[str, Any] | None" = None
        self._hyp_evidence: list[list[str]] = []

        # 【V2b B2/B3: 逐次/operando】: 直近 sequential ジョブの生結果 (② 出力そのまま) + 構築済み
        #   viewmodel.sequence (契約形)。None は「未実行 (empty-state)」。
        self._sequential_result: "dict[str, Any] | None" = None
        self._sequence: "dict[str, Any] | None" = None
        # 【B4: echem】: 直近 POST /api/echem の結果 (align_echem + alkali_budget 合成)。
        self._echem_result: "dict[str, Any] | None" = None
        self._channels: list[dict[str, Any]] = []
        # 【B5: 新相承認カードの内部索引】: action_id → {frame_index, data_path, data_format}
        #   (approve 時に identify_and_add_phase へ渡す生パターンの出所)。
        self._np_approval_info: dict[str, dict[str, Any]] = {}

        # 【V3b: MEM 密度マップ】: 直近 POST /api/mem 完了の viewmodel.structure.mem 契約形
        #   (map+peaks+note)。None は「未実行 (empty-state)」(api-contract.md)。mem_peaks は
        #   既存キー (`structure.mem_peaks`) との二重供給用に別途保持する。
        self._mem_view: "dict[str, Any] | None" = None
        self._mem_peaks: list[dict[str, Any]] = []

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
        # 【レビュー指摘 #2: RLock 化 (再入可能)】: ``create_proposal``/``_resolve_generic_proposal``
        #   の auto/bypass 即時適用経路は、このロックを保持したまま ``_execute_proposal`` →
        #   ``apply_structure``/``add_phase``/``remove_phase``/``update_settings`` (各々が自前で
        #   ``self._lock`` を取る read-modify-write) を呼ぶ。通常の ``threading.Lock`` だと同一
        #   スレッドの再取得でデッドロックするため ``RLock`` にする — 別スレッドからの取得は
        #   従来どおり排他される (再入可能なのは「取得したスレッド自身」のみ)。
        self._lock = threading.RLock()
        # 【2026-07-26 権限境界改訂: agent_policy】: 既定 "approve"。人間が `set_agent_policy` で
        #   切り替える (エージェント自身が変更するツールは shim に存在しない — 自己昇格の禁止)。
        #   `AgentBridge` に `get_policy` として束ねることで、ターン開始時点の policy に応じて
        #   shim のツール表 (bypass のみ project ライフサイクル 4 本を追加) とシステムプロンプトの
        #   説明文を切り替える (`agent_mcp.build_server(policy)`/`allowed_tool_ids(policy)`)。
        self._agent_policy: AgentPolicy = "approve"
        # 【V3a AUTO 実 LLM ブリッジ】: `_agent_append` はこの `self._lock` 下で transcript へ
        #   append する (bridge のバックグラウンドスレッドと GET /api/viewmodel の並走に対して安全)。
        #   `get_state_summary=self.state` はシステムプロンプトに埋め込む現況要約。
        self._agent_bridge = AgentBridge(
            on_event=self._agent_append,
            get_state_summary=self.state,
            get_policy=lambda: self._agent_policy,
        )

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

    def agent_running(self) -> bool:
        """AUTO 実 LLM ブリッジ (`AgentBridge`) が現在ターンを実行中か (V3a レビュー指摘 #2)。

        実行中に mode 切替/project swap が起きると、バックグラウンドスレッドが古いセッション
        (transcript/ledger) へ書き込み続けたり、切替直後の新セッションへ誤って書き込んだりする
        (``on_event``/``get_state_summary`` は construction 時に束縛したクロージャのため)。
        呼び出し側 (`set_mode`/`app.py _guarded_swap`) がこれを見て 409 へ縮退させる。
        """
        return self._agent_bridge.status()["status"] == "running"

    def set_mode(self, gui_mode: str) -> bool:
        """GUI モードを切替える。同一モードへの切替は no-op (ledger 追記なし) で ``False`` を返す。

        変更時は ``FinalSelectionEngine.set_mode`` を呼ぶ (エンジン側が ``selection_set_mode`` を
        ledger に追記する契約なので session 側では二重追記しない)。不正値は ``ValueError``。
        エージェントが実行中 (`agent_running()`) の切替要求は ``ConflictError`` (呼び出し側
        [`app.py`] が 409 へ縮退, V3a レビュー指摘 #2) — 実行中のターンは "auto" モードの
        ``AgentBridge`` を握ったままなので、その最中に "manual" へ落とす/別モードへ動かすと
        実行中スレッドの transcript 書き込み前提が壊れる。
        """
        if gui_mode not in _GUI_TO_ENGINE:
            raise ValueError(f"unknown mode: {gui_mode!r}")
        if gui_mode == self.mode:
            return False
        if self.agent_running():
            raise ConflictError("agent is running — cannot switch mode while a turn is in progress")
        self.engine.set_mode(_GUI_TO_ENGINE[gui_mode])
        return True

    # ------------------------------------------------------------------
    # エージェント権限モード (`agent_policy`, POST /api/agent/policy, 2026-07-26 権限境界改訂)
    # ------------------------------------------------------------------

    @property
    def agent_policy(self) -> AgentPolicy:
        """現在のエージェント権限モード (``"approve"|"auto"|"bypass"``, 既定 ``"approve"``)。"""
        return self._agent_policy

    def set_agent_policy(self, policy: str) -> bool:
        """エージェント権限モードを切替える (人間専用 — shim にこれを呼ぶツールは存在しない)。

        ``set_mode`` (FR-402) と同じ規律: 不正値は ``ValueError``、同一値への切替は no-op
        (ledger 追記なし) で ``False``、エージェントのターン実行中の切替は ``ConflictError``
        (呼び出し側 [`app.py`] が 409 へ縮退) — 実行中のターンが束縛している shim のツール表
        (`agent_mcp.allowed_tool_ids(policy)`) を実行中に差し替えると、そのターン内のツール呼び出し
        前提が壊れる。変更時のみ ``ledger.append("agent_policy_change", ...)`` する
        (api-contract.md 「切替 + ledger 追記」)。
        """
        if policy not in _VALID_AGENT_POLICIES:
            raise ValueError(f"unknown agent_policy: {policy!r}")
        if policy == self._agent_policy:
            return False
        if self.agent_running():
            raise ConflictError(
                "agent is running — cannot switch agent_policy while a turn is in progress"
            )
        self._agent_policy = policy  # type: ignore[assignment]
        self.ledger.append("agent_policy_change", {"policy": policy})
        return True

    # ------------------------------------------------------------------
    # アプリ設定 (資格情報) — Materials Project トークン
    # (GET/POST /api/settings, POST /api/settings/clear, api-contract.md §アプリ設定)
    # ------------------------------------------------------------------

    #: 現状扱う設定キーは MP トークンのみ (未知 key は 422, `clear_settings`)。
    _VALID_SETTINGS_KEYS: "tuple[str, ...]" = ("mp_api_key",)

    def get_settings(self) -> dict[str, Any]:
        """GET /api/settings: マスク済み状態 (キー本体は絶対に返さない)。"""
        status = _settings.mp_api_key_status()
        return {
            "mp_api_key_set": status["set"],
            "mp_api_key_hint": status["hint"],
            "mp_api_key_source": status["source"],
        }

    def save_settings(self, *, mp_api_key: Any) -> dict[str, Any]:
        """POST /api/settings ``{"mp_api_key": str}``: 保存 + プロセス env 反映 + ledger。

        空文字/非文字列は ``ValueError`` (呼び出し側 [`app.py`] が 422 へ縮退)。**ledger に値は
        書かない** — 記録するのは ``settings_change`` (``{"key": "mp_api_key", "action": "set"}``)
        のみ (契約の絶対規則)。保存直後に ``apply_mp_api_key_to_env`` でプロセス env へ反映し、
        既存の ``MPRestClient()`` 遅延構築経路 (env → .env の順) がそのまま新しいキーを拾えるよう
        にする (設定 > env の優先順位)。
        """
        if not isinstance(mp_api_key, str) or not mp_api_key:
            return {"error": "mp_api_key must be a non-empty string", "error_type": "ValueError"}
        _settings.save_setting("mp_api_key", mp_api_key)
        _settings.apply_mp_api_key_to_env()
        self.ledger.append("settings_change", {"key": "mp_api_key", "action": "set"})
        return self.get_settings()

    def clear_settings(self, key: Any) -> dict[str, Any]:
        """POST /api/settings/clear ``{"key": "mp_api_key"}``: 削除 + env から除去 + ledger。

        未知 key は ``ValueError`` (422)。値を含まない ``settings_change`` (action="clear") のみを
        ledger に記す。
        """
        if key not in self._VALID_SETTINGS_KEYS:
            return {"error": f"unknown settings key: {key!r}", "error_type": "ValueError"}
        _settings.clear_setting(str(key))
        self.ledger.append("settings_change", {"key": key, "action": "clear"})
        return self.get_settings()

    # ------------------------------------------------------------------
    # GET /api/state
    # ------------------------------------------------------------------

    def state(self) -> dict[str, Any]:
        agent = dict(self._agent_base)
        # 【V3a: 実測値へ差し替え】: tokens/wall_time_s/available は AgentBridge の実測値
        #   (api-contract.md 「state.agent | tokens/wall_time_s が実測値に。available 追加」)。
        #   `get_state_summary=self.state` (bridge 構築時に注入) と本メソッドが相互参照する形に
        #   なるため、ここで `self._agent_bridge.status()` を呼んでも無限再帰しない
        #   (bridge は `state()` を「システムプロンプト構築時」にのみ呼び、`status()` はこの
        #   フィールドを読むだけで `state()` を呼び返さない)。
        bridge_status = self._agent_bridge.status()
        agent["available"] = bridge_status["available"]
        agent["tokens"] = bridge_status["tokens"]
        agent["wall_time_s"] = bridge_status["wall_time_s"]
        # 【idle = ターンが走っていないこと】: 旧実装は `mode == "manual"` を idle として
        #   いたため、AUTO でターン完了後も idle=false のまま固着し「エージェントが動き続けて
        #   いる」ように見えた (実走スモークで発見)。実測ステータスを単一情報源にする。
        agent["idle"] = bridge_status["status"] != "running"
        # 【エージェント権限モード】: 人間が切り替える単一情報源 (`self._agent_policy`)。
        agent["policy"] = self._agent_policy
        # 【gsas_available は毎回動的判定】: Tier1 sidecar は GSAS-II 抜きで同梱され得るため、
        #   status は起動時固定シードでなく現在の import 可否 (`gsasii_available`, lru_cache 済み
        #   なので実質定数コスト) を都度反映する (api-contract.md GET /api/state)。
        status = dict(self._status)
        status["gsas_available"] = gsasii_available()
        # 【mp_available は毎回動的判定】: gsas_available と同じ流儀 — 設定ファイル/env の現況を
        #   都度反映する (相同定ボタンの事前 disabled に使う, api-contract.md §アプリ設定)。
        status["mp_available"] = _settings.mp_available()
        return {
            "project": dict(self.project),
            "mode": self.mode,
            "final_selection_mode": self.engine.mode,
            "source": self._source,
            "refine": self.refine_status(),
            "project_path": self._project_path,
            "ledger": {"count": len(self.ledger.entries), "verified": self.ledger.verify()},
            "status": status,
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
        with self._lock:
            channels = list(self._channels)
            sequence = dict(self._sequence) if self._sequence is not None else None
        vm: dict[str, Any] = {
            "datasets": self._datasets_view(),
            "phases": phases,
            "channels": _seed.seed_channels() if use_seed else channels,
            "snapshots": seeded_snapshots + live_snapshots,
            "fit": fit,
            "parameters": parameters,
            "hypotheses": self.hypotheses_view(),
            "phase_id": self._phase_id_view(use_seed),
            "sequence": _seed.seed_sequence() if use_seed else (sequence or _EMPTY_SEQUENCE),
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
        frames = [
            {
                "id": f"f{i}",
                "data_path": f.data_path,
                "axis_value": f.axis_value,
                "label": f.label,
            }
            for i, f in enumerate(project.frames)
        ]
        return {
            "histograms": histograms,
            "phases": phases,
            "settings": settings,
            "frames": frames,
            "frame_axis": project.frame_axis,
        }

    def _phase_id_view(self, use_seed: bool) -> dict[str, Any]:
        """viewmodel.phase_id (A4): demo はシード、project は実 ``identify_pattern`` 候補。"""
        if use_seed:
            return _seed.seed_phase_id()
        if self._source != "project":
            return dict(_EMPTY_PHASE_ID)
        with self._lock:
            candidates = [dict(c) for c in self._phaseid_candidates]
        return {
            "candidates": candidates,
            "unexplained": [],
            "completeness": {"is_complete": None, "notes": [], "flagged_frames": ""},
        }

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
        # 【V3b: MEM は demo/project 共通】: 実 MEM が完了していれば mem_peaks を実ピークへ差し替え、
        #   viewmodel.structure.mem (map+peaks+note) を供給する。未実行は None (empty-state)。
        with self._lock:
            mem = dict(self._mem_view) if self._mem_view is not None else None
            mem_peaks_override = [dict(p) for p in self._mem_peaks] if self._mem_peaks else None
        if self._source != "demo":
            return {
                "sites": [dict(s) for s in self._structure_sites],
                "constraints": [],
                "mem_peaks": mem_peaks_override or [],
                "mem": mem,
            }
        return {
            "sites": [dict(s) for s in self._structure_sites],
            "constraints": _seed.seed_structure_constraints(),
            "mem_peaks": mem_peaks_override or _seed.seed_mem_peaks(),
            "mem": mem,
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
        if self._source == "demo":
            diff = _seed.seed_hypotheses_diff()
            evidence = _seed.seed_hypotheses_evidence()
        else:
            # 【empty-state (REQ-GUI-014)】: project/none はシードで実データ不在を偽装しない。
            #   evidence は A5 (multistart) の corroborated 行のみ蓄積する。
            diff = {"vs": None, "rows": []}
            with self._lock:
                evidence = [list(e) for e in self._hyp_evidence]
        with self._lock:
            basin = dict(self._basin) if self._basin is not None else None
        return {
            "rows": [dict(r) for r in self._hyp_rows],
            "diff": diff,
            "evidence": evidence,
            "basin": basin,
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
        明示的な適用操作 (REQ-GUI-008)。占有率は site の ``label`` をキーに ``occupancies`` へ写す
        (単相 demo 表示用の ``PhaseInstance.occupancies`` — 契約上 1 相分のみ)。

        project モード (A3, api-contract.md POST /api/structure/apply) では、適用した occ 編集を
        次回 ``request_refine`` の ``initial_occupancies`` へ配線するため ``self._pending_occupancies``
        (相名→{ラベル→occ}) を更新する。相名は直近 refine の実サイト抽出が残した
        ``self._site_phase_map`` (site の一意 ``id``→相名, `atoms.extract_sites` が全相を跨いで
        一意に採番) を引く — **label ではなく id でルーティングする** (セルフレビュー指摘 #3):
        多相では相を跨いで同じ label (例 "O1") が衝突しうるため、label をキーにした中間辞書を経由
        すると衝突した相の一方の occ 編集が消える。id で 1 サイトずつルーティングすれば、相ごとに
        独立した ``revisions[phase_name][label]`` へ正しく振り分けられる。未精密化 (map 未構築) の
        site は revision にできないため無視する。**uiso は対象外**: ``run_auto_rietveld`` に uiso を
        直接シードする API が無いため (occ の ``initial_occupancies`` のような注入点が存在しない)、
        occ のみを配線する。
        """
        occupancies: dict[str, float] = {}
        revisions: dict[str, dict[str, float]] = {}
        for site in sites:
            label = site.get("label") or site.get("id")
            occ = site.get("occ")
            if label is None or occ is None:
                continue
            try:
                occ_val = float(occ)
            except (TypeError, ValueError):
                continue
            occupancies[str(label)] = occ_val
            if self._source == "project":
                site_id = site.get("id")
                phase_name = self._site_phase_map.get(str(site_id)) if site_id is not None else None
                if phase_name is not None:
                    revisions.setdefault(phase_name, {})[str(label)] = occ_val
        # 【レビュー指摘 #2: read-modify-write を丸ごとロック下に】: ``self._structure_phases``
        #   の読取 (``base = ...``) から書込み (``self._structure_phases = ...``) までを 1 つの
        #   クリティカルセクションにする — 複数の ``apply_structure`` (例: auto/bypass の
        #   ``propose_structure_revision`` が同一ターンで 2 件並走) が同時に走ると、片方の
        #   ``base``/``occupancies`` 計算がもう片方の書込み前の古い値を読み、後勝ちの代入で
        #   一方の編集が消える (lost update)。``self._lock`` は ``RLock`` なので、この呼び出しが
        #   ``create_proposal``/``_resolve_generic_proposal`` の ``_execute_proposal`` (既にロック
        #   保持) 経由でも再入で安全に動く。
        with self._lock:
            base = (
                self._structure_phases[0] if self._structure_phases else _seed.seed_structure_base_phase()
            )
            new_phase = base.with_updates(occupancies=occupancies)
            self._structure_phases = (new_phase,) + tuple(self._structure_phases[1:])
            self._structure_sites = [dict(s) for s in sites]
            if self._source == "project":
                # 【セルフレビュー指摘 #2 (元 M-earlier): ロック外競合】: この書込みと
                #   ``request_refine`` の snapshot+clear (下記) を同一 ``self._lock`` に揃える。
                #   ``request_refine`` は「snapshot 読取 → job 起動 → 起動確定後のみ clear」を
                #   単一クリティカルセクションで行うため、この書込みはその間には割り込めず、必ず
                #   「snapshot に含まれてから clear される」か「clear の後に残る (次回 refine
                #   用)」のどちらかになる — snapshot 済みの古い値を読んだ直後に本メソッドが
                #   新しい revision で上書きし、それを ``request_refine`` が無条件 clear で
                #   消してしまう (revision 消失) 隙間を無くす。
                self._pending_occupancies = revisions
            snap = self.snapshots.save(self._structure_phases, label=note or "ReviseStructure apply")
            return {"snapshot_id": snap.id, "ledger_index": self.ledger.entries[-1].index}

    # ------------------------------------------------------------------
    # POST /api/approval/{action_id}
    # ------------------------------------------------------------------

    #: sr-/rv-/pc-/st- (`create_proposal` 起票) の action_id 接頭辞。np- (B5 新相承認) と同じく
    #: `_resolve_with_in_progress_guard` 経由で二重承認を防ぐ (2026-07-26 一般化)。
    _GENERIC_PROPOSAL_PREFIXES: "tuple[str, ...]" = ("sr-", "rv-", "pc-", "st-")

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

        if action_id.startswith("np-"):
            # 【B5: 新相承認カード】: structure ReviseStructure 承認とは別経路 (add_phase まで進む)。
            return self._resolve_with_in_progress_guard(
                action_id, lambda: self._resolve_new_phase_approval(action_id, decision=decision)
            )

        if action_id.startswith(self._GENERIC_PROPOSAL_PREFIXES):
            # 【ModelAction 起票の一般化, 2026-07-26】: `create_proposal` (POST /api/proposals) が
            #   作った sr-/rv-/pc-/st- カードの approve/reject。実操作は `_execute_proposal` へ
            #   委譲する (§propose_* ツールと承認カード の「approve 時に実行される操作」列)。
            return self._resolve_with_in_progress_guard(
                action_id, lambda: self._resolve_generic_proposal(action_id, decision=decision)
            )

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

    def _resolve_with_in_progress_guard(
        self, action_id: str, work: "Callable[[], dict[str, Any]]"
    ) -> dict[str, Any]:
        """二重承認防止の check-and-set マーカー (np-/sr-/rv-/pc-/st- 共通, 2026-07-26 一般化)。

        ``work`` (例: MP 問い合わせを含む ``_resolve_new_phase_approval``) が長時間ブロックしうる
        間、``self._approvals`` には何も書かれない (完了時に初めて確定状態を書く旧実装の弱点) ため、
        呼び出し前に ``self._lock`` 下で ``state="in_progress"`` マーカーを置き、以降の重複呼び出しを
        このマーカーで 409 (呼び出し元の事前チェック) にする。エラー経路 (例外/error dict) は
        マーカーを pop して pending に戻す (再試行可能, 既存の error 経路契約を維持)。
        """
        with self._lock:
            if action_id in self._approvals:
                return {
                    "error": f"approval already resolved: {action_id}",
                    "error_type": "ConflictError",
                }
            self._approvals[action_id] = {"state": "in_progress", "snapshot_id": None}
        try:
            result = work()
        except Exception:
            with self._lock:
                self._approvals.pop(action_id, None)
            raise
        if "error" in result:
            with self._lock:
                self._approvals.pop(action_id, None)
        return result

    # ------------------------------------------------------------------
    # POST /api/proposals, GET /api/proposals (ModelAction 起票, §propose_* ツールと承認カード)
    # ------------------------------------------------------------------

    def create_proposal(self, kind: Any, payload: Any, *, rationale: str = "") -> dict[str, Any]:
        """POST /api/proposals: ModelAction を起票する。

        kind ごとに payload を検証し (不正な kind/必須キー欠落/不明 item_id・phase_name は
        起票時に error dict へ縮退させる — 承認時まで持ち越さない, api-contract.md
        「payload の各引数は他ツールの出力から作れること」)。妥当なら transcript へ
        approval カード (state=pending) を追加し、ledger ``agent_proposal`` を追記する。

        **エージェント権限モード分岐 (§エージェント権限モード, 2026-07-26 改訂)**: ``approve``
        (既定) はカードを作って終わり — 実行 (add_phase/resolve_review_item 等) は
        ``resolve_approval`` の人間 approve でのみ起きる (提案 ≠ 適用)。``auto``/``bypass`` は
        カード作成に続けて ``_execute_proposal`` を**即時**呼び、成功すればカード state を
        ``"auto_applied"`` にする。実行が失敗すれば (error dict) カードは pending へ戻し
        (人間が後で承認/却下できる)、返り値にも同じ error を載せる。
        """
        if not isinstance(kind, str) or kind not in _PROPOSAL_KIND_PREFIX:
            return {"error": f"unknown proposal kind: {kind!r}", "error_type": "ValueError"}
        if not isinstance(payload, dict):
            return {"error": "payload must be an object", "error_type": "ValueError"}
        guard = self._validate_proposal_payload(kind, payload)
        if guard is not None:
            return guard
        with self._lock:
            self._proposal_seq += 1
            action_id = f"{_PROPOSAL_KIND_PREFIX[kind]}-{self._proposal_seq}"
            self._proposals[action_id] = {
                "kind": kind, "payload": dict(payload), "rationale": rationale,
            }
            self.ledger.append(
                "agent_proposal",
                {"action_id": action_id, "kind": kind, "payload": payload, "rationale": rationale},
            )
            msg = {
                "id": f"t{len(self._transcript) + 1}",
                "kind": "approval",
                "action_id": action_id,
                "title": _PROPOSAL_TITLES[kind],
                "rationale": rationale,
                "action_json": json.dumps(payload, ensure_ascii=False, default=str),
                "state": "pending",
            }
            self._transcript.append(msg)
            policy = self._agent_policy
            if policy != "approve":
                # 【即時自動適用の in_progress マーカー】: ``_resolve_with_in_progress_guard`` と
                #   同じ check-and-set を、ここでは「起票直後」に同一ロック内で置く。この
                #   action_id は今このロック内で採番されたばかりなので既存エントリとの競合は
                #   起きない (二重解決防止と同じ考え方を先取りして塞ぐ)。
                self._approvals[action_id] = {"state": "in_progress", "snapshot_id": None}
        if policy == "approve":
            return {"action_id": action_id, "state": "pending"}
        # 【auto/bypass: 即時自動適用 (レビュー指摘 #2 で ``with self._lock:`` に変更)】:
        #   ``_execute_proposal`` は ``apply_structure``/``add_phase``/``remove_phase``/
        #   ``update_settings`` 等 ``self._lock`` を自前で取るメソッドを呼ぶ。``self._lock`` は
        #   ``RLock`` (再入可能) にしたため、ここでロックを保持したまま呼んでもデッドロックしない
        #   — むしろ保持したまま呼ぶことで、``_execute_proposal`` 全体 (read-modify-write) が
        #   他スレッドの並行 ``create_proposal``/``_resolve_generic_proposal`` に割り込まれず、
        #   1 ターンに複数の propose_* が発行されても互いの変更を消し合わない (lost update 修正)。
        with self._lock:
            exec_result = self._execute_proposal(kind, payload)
        if "error" in exec_result:
            with self._lock:
                self._approvals.pop(action_id, None)  # pending へ復帰 (再試行可能)
            return {**exec_result, "action_id": action_id, "state": "pending"}
        self.ledger.append(
            "approval_decision", {"action_id": action_id, "decision": "auto", "kind": kind}
        )
        with self._lock:
            self._approvals[action_id] = {
                "state": "auto_applied", "snapshot_id": exec_result.get("snapshot_id"),
            }
        return {"action_id": action_id, "state": "auto_applied", "result": exec_result}

    def _validate_proposal_payload(self, kind: str, payload: dict[str, Any]) -> "dict[str, Any] | None":
        """``create_proposal`` の起票時 payload 検証 (kind ごと)。問題なければ ``None``。"""
        if kind == "structure_revision":
            sites = payload.get("sites")
            if not isinstance(sites, list) or not sites or not all(isinstance(s, dict) for s in sites):
                return {"error": "sites must be a non-empty list of objects", "error_type": "ValueError"}
            return None
        if kind == "review_resolution":
            item_id = payload.get("item_id")
            action = payload.get("action")
            if not isinstance(item_id, str) or not item_id:
                return {"error": "item_id is required", "error_type": "ValueError"}
            if action not in ("accept", "send_back"):
                return {"error": f"invalid action: {action!r}", "error_type": "ValueError"}
            if not any(it.item_id == item_id for it in self.review_queue.items):
                return {"error": f"unknown review item: {item_id}", "error_type": "NotFoundError"}
            return None
        if kind == "phase_change":
            op = payload.get("op")
            phase_name = payload.get("phase_name")
            if op not in ("add", "remove"):
                return {"error": f"invalid op: {op!r}", "error_type": "ValueError"}
            if not isinstance(phase_name, str) or not phase_name:
                return {"error": "phase_name is required", "error_type": "ValueError"}
            if self._source != "project" or self._project is None:
                return {"error": "no project loaded", "error_type": "ValueError"}
            exists = any(p.phase_name == phase_name for p in self._project.phases)
            if op == "add":
                if not payload.get("structure_path"):
                    return {
                        "error": "structure_path is required for op=add", "error_type": "ValueError",
                    }
                if exists:
                    return {"error": f"phase already exists: {phase_name}", "error_type": "ValueError"}
            else:
                if not exists:
                    return {"error": f"unknown phase: {phase_name}", "error_type": "NotFoundError"}
            return None
        if kind == "settings_change":
            if self._source != "project" or self._project is None:
                return {"error": "no project loaded", "error_type": "ValueError"}
            keys = ("two_theta_limits", "background_coeffs", "max_cyc")
            if not any(payload.get(k) is not None for k in keys):
                return {
                    "error": "at least one of two_theta_limits/background_coeffs/max_cyc is required",
                    "error_type": "ValueError",
                }
            ttl = payload.get("two_theta_limits")
            if ttl is not None:
                try:
                    float(ttl[0])
                    float(ttl[1])
                except (TypeError, ValueError, IndexError, KeyError):
                    return {
                        "error": f"invalid two_theta_limits: {ttl!r}", "error_type": "ValueError",
                    }
            bg = payload.get("background_coeffs")
            if bg is not None:
                try:
                    int(bg)
                except (TypeError, ValueError):
                    return {
                        "error": f"invalid background_coeffs: {bg!r}", "error_type": "ValueError",
                    }
            mc = payload.get("max_cyc")
            if mc is not None:
                try:
                    int(mc)
                except (TypeError, ValueError):
                    return {"error": f"invalid max_cyc: {mc!r}", "error_type": "ValueError"}
            return None
        return {"error": f"unknown proposal kind: {kind!r}", "error_type": "ValueError"}

    def _execute_proposal(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        """approve 時に kind ごとの実操作を呼ぶ (§propose_* ツールと承認カード の対応表)。"""
        if kind == "structure_revision":
            return self.apply_structure(payload.get("sites") or [], note="agent proposal: ReviseStructure")
        if kind == "review_resolution":
            return self.resolve_review_item(
                str(payload.get("item_id")), action=payload.get("action"), note="agent proposal"
            )
        if kind == "phase_change":
            op = payload.get("op")
            if op == "add":
                return self.add_phase(
                    structure_path=payload.get("structure_path"), phase_name=payload.get("phase_name")
                )
            if op == "remove":
                return self.remove_phase(str(payload.get("phase_name")))
            return {"error": f"unknown phase_change op: {op!r}", "error_type": "ValueError"}
        if kind == "settings_change":
            return self.update_settings(
                two_theta_limits=payload.get("two_theta_limits"),
                background_coeffs=payload.get("background_coeffs"),
                max_cyc=payload.get("max_cyc"),
            )
        return {"error": f"unknown proposal kind: {kind!r}", "error_type": "ValueError"}

    def _resolve_generic_proposal(
        self, action_id: str, *, decision: Literal["approve", "reject"]
    ) -> dict[str, Any]:
        """sr-/rv-/pc-/st- 承認カードの解決 (``create_proposal`` が起票した ModelAction)。"""
        if decision == "reject":
            self.ledger.append("approval_decision", {"action_id": action_id, "decision": "reject"})
            self._approvals[action_id] = {"state": "rejected", "snapshot_id": None}
            return {
                "state": "rejected", "snapshot_id": None,
                "ledger_index": self.ledger.entries[-1].index,
            }
        info = self._proposals.get(action_id)
        if info is None:
            return {"error": f"unknown approval action: {action_id}", "error_type": "NotFoundError"}
        # 【レビュー指摘 #2: RLock 下で実行】: create_proposal の auto/bypass 即時適用と同じ理由
        #   (上記コメント参照) — このロックの下で ``_execute_proposal`` を丸ごと実行することで、
        #   人間の approve と別スレッドの auto/bypass 即時適用が同一ターンで重なっても
        #   read-modify-write が直列化される。
        with self._lock:
            exec_result = self._execute_proposal(info["kind"], info["payload"])
        if "error" in exec_result:
            # 【実行失敗はカード pending 復帰】: `_resolve_with_in_progress_guard` が "error" キーを
            #   見て in_progress マーカーを pop する (再試行可能, api-contract.md 「approve 時の
            #   実行失敗は error dict + カードは pending 復帰」)。
            return exec_result
        self.ledger.append(
            "approval_decision", {"action_id": action_id, "decision": "approve", "kind": info["kind"]}
        )
        snapshot_id = exec_result.get("snapshot_id")
        self._approvals[action_id] = {"state": "approved", "snapshot_id": snapshot_id}
        return {
            "state": "approved", "snapshot_id": snapshot_id,
            "ledger_index": self.ledger.entries[-1].index,
        }

    def pending_approvals(self) -> list[dict[str, Any]]:
        """GET /api/proposals: transcript 上の pending 承認カード一覧 (起票機構問わず np-/sr-/rv-/pc-/st- 含む)。"""
        return [
            row for row in self._transcript_view()
            if row.get("kind") == "approval" and row.get("state") == "pending"
        ]

    def abandon_pending_approvals(self, *, reason: str = "session swap") -> int:
        """未決の承認カードすべてを ``approval_abandoned`` として ledger に記録する (レビュー指摘 #1)。

        project ライフサイクル (create/open/close/demo) がセッションを差し替える直前に、旧
        セッション (呼び出し先の ``self``) に対して呼ぶ想定 (``app.py`` ``_guarded_swap``)。np-/
        sr-/rv-/pc-/st- の pending カードは、swap 後は二度と approve/reject されない (旧セッション
        ごと参照を失う) — 何も記録しないまま消えると、対応する ``agent_proposal`` だけが ledger に
        残り「未決のまま永久に消えた」事実が追えなくなる (P2 違反。bypass ではエージェント自身が
        自分の起票をこの経路で無記録に消せてしまう)。1 件ごとに
        ``ledger.append("approval_abandoned", {"action_id", "kind", "reason"})`` を追記し、カード
        state を ``"abandoned"`` にする (以後 pending 一覧・``resolve_approval`` の対象から外れる)。

        **人間の操作はブロックしない** — このメソッド自体は失敗しない (呼び出し元は常に swap を
        進めてよい)。0 件なら ledger への追記は一切行わない (空振りで無駄な監査ノイズを生まない)。

        Returns:
            記録した件数。
        """
        pending = self.pending_approvals()
        count = 0
        with self._lock:
            for row in pending:
                action_id = row.get("action_id")
                if action_id is None or action_id in self._approvals:
                    continue  # 二重解決防止 (別スレッドが先に approve/reject/abandon 済み)
                prefix = str(action_id).split("-", 1)[0]
                kind = _PREFIX_TO_PROPOSAL_KIND.get(prefix, prefix)
                self.ledger.append(
                    "approval_abandoned", {"action_id": action_id, "kind": kind, "reason": reason}
                )
                self._approvals[action_id] = {"state": "abandoned", "snapshot_id": None}
                count += 1
        return count

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

    def _validate_stages_on(self, stages_on: "Mapping[str, bool] | None") -> "dict[str, Any] | None":
        """``stages_on`` の nn キーが ``viewmodel.stages`` に存在するか検証する (A1)。

        不明なキーがあれば ``ValueError`` error dict (呼び出し側が 422 へ縮退)、問題なければ
        ``None``。独立メソッドに切り出すことで、ガード自体の変異実証 (「検証を外すと不明キーが
        通ってしまう」) を `_guard_project_editable` と同じ流儀で書けるようにする。
        """
        if stages_on is None:
            return None
        known_nn = {s["nn"] for s in self._stages}
        unknown = sorted(set(stages_on) - known_nn)
        if unknown:
            return {"error": f"unknown stage nn: {unknown}", "error_type": "ValueError"}
        # 全段 OFF は「空 recipe の縮退 run」(履歴空で "done" に見える無意味な実行) に
        # なるため明示拒否する — 成功に見える無意味な実行は最悪の失敗形。
        if known_nn and all(not stages_on.get(nn, True) for nn in known_nn):
            return {
                "error": "all stages are disabled — nothing to refine",
                "error_type": "ValueError",
            }
        return None

    def request_refine(self, stages_on: "Mapping[str, bool] | None" = None) -> dict[str, Any]:
        """精密化要求を受理する (REQ-GUI-013)。

        demo モード (source="demo") は従来どおり ledger 追記のみで即時受理する (後方互換)。
        project モードは実 ``run_auto_rietveld`` をバックグラウンドスレッドで起動する。実行中の
        二重起動は ``ConflictError`` (呼び出し側 [`app.py`] が 409 へ縮退) を返す — refine/phaseid/
        multistart は同一ジョブ枠 (``self._job``) を共有するため、いずれかの実行中も 409 になる。

        :param stages_on: 段階 nn → 解放するか (A1)。不明な nn キー (``viewmodel.stages`` に無い)
            は ``ValueError`` error dict (呼び出し側が 422 へ縮退)。``None``/省略は全段既定。
        """
        guard = self._validate_stages_on(stages_on)
        if guard is not None:
            return guard
        payload = {"stages_on": dict(stages_on) if stages_on else None}
        if self._source == "demo":
            self.ledger.append("refine_request", payload)
            return {"status": "recorded"}
        if self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        gsas_guard = self._guard_gsas_available()
        if gsas_guard is not None:
            return gsas_guard
        # 【A3: pending occ revisions のスナップショット】: ``self._pending_occupancies`` はジョブが
        #   実際に起動できた場合のみ消費 (クリア) する — 起動が 409 で断られた場合に revision を
        #   取りこぼさないため、クリアは ``started`` 確定後に行う (下記)。
        #
        # 【セルフレビュー指摘 #2: ロック外競合】: 「スナップショット読取 → job 起動 →
        #   起動確定後のみ clear」を単一の ``with self._lock:`` に収める (``apply_structure`` と
        #   同一ロック)。以前はここが無ロックだったため、read 直後・clear 前に別スレッドの
        #   ``apply_structure`` が新しい revision を書き込むと、その revision はこの refine の
        #   ``initial_occupancies`` に一度も含まれないまま直後の無条件 clear で消えていた
        #   (取りこぼし)。ロックを揃えることで ``apply_structure`` はこの区間には割り込めなくなり、
        #   「snapshot に含まれてから clear される」か「clear の後に残る (次回 refine 用)」のいずれか
        #   に一本化される。
        with self._lock:
            initial_occupancies = (
                dict(self._pending_occupancies) if self._pending_occupancies else None
            )
            runner = build_default_runner(
                self._project, ledger=self.ledger, stages_on=stages_on,
                initial_occupancies=initial_occupancies,
            )
            started = self._job.start(
                runner,
                on_success=self._on_refine_success,
                on_failure=self._on_refine_failure,
                # 【ledger 順序保証】: on_started はロック保持下・スレッド起動前に同期実行されるため、
                #   即座に失敗する runner との競合でも "refine_request" は必ず終了系エントリより先に
                #   現れる (RefinementJobManager.start docstring 参照)。
                on_started=lambda: self.ledger.append("refine_request", payload),
                kind="refine",
            )
            if started:
                self._pending_occupancies = {}  # A3: この refine で消費済みにする (起動確定後のみ)
        if not started:
            return {"error": "refinement already running", "error_type": "ConflictError"}
        return {"status": "started"}

    def refine_status(self) -> dict[str, Any]:
        """GET /api/refine/status 契約形を返す (refine/phaseid/multistart 共有ジョブ枠)。"""
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
        # 【A2: 実サイト抽出】: gpx から label/el/x/y/z/occ/uiso + 特殊位置 lock を読む。
        #   `curves.extract_curves` (直上) と同じ流儀で例外は握らない — gpx_path が非空なのは
        #   実 run_auto_rietveld が成功裏に書き出した後のみなので GSAS 未導入は実運用では
        #   到達しない (防御的コードのみ)。失敗時は RefinementJobManager が failed へ縮退する。
        #   "phase" は session 内部専用ルーティングキー (A3) — viewmodel 契約の Site スキーマには
        #   存在しないため、格納前に取り除く。**キーは label でなく site の一意 id**
        #   (セルフレビュー指摘 #3): `atoms.extract_sites` は全相を跨いで一意な `id` (``"s{idx}"``,
        #   相をまたぐ通し番号) を振っているが、`label` (原子ラベル, 例 "O1") は相ごとに独立して
        #   付与されるため多相では衝突しうる。label をキーにすると、後勝ちで別の相の site を
        #   上書きし、`apply_structure` の occ 編集が誤った相 (または存在しない相) へ配線される。
        sites_view: list[dict[str, Any]] = []
        site_phase_map: dict[str, str] = {}
        if result.gpx_path and project is not None:
            from . import atoms

            raw_sites = atoms.extract_sites(result.gpx_path, occupancy_esd=result.atom_occupancy_esd)
            for site in raw_sites:
                site = dict(site)
                site_phase_map[site["id"]] = site.pop("phase", "")
                sites_view.append(site)

        with self._lock:
            self._fit["metrics"] = metrics
            self._fit["history"] = history
            self._fit["validity"] = validity_rows
            if plot:
                self._fit["plot"] = plot
            if phases_view:
                self._phases_view = phases_view
            if sites_view:
                self._structure_sites = sites_view
                self._site_phase_map = site_phase_map
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

    def _guard_gsas_available(self) -> "dict[str, Any] | None":
        """GSAS-II 必須ジョブ (refine/multistart/sequential) 共通ガード (Tier1 sidecar)。

        Tier1 配布はコア + web extra のみを同梱し GSAS-II はローカル導入前提とする
        (desktop/README.md)。未導入環境でジョブを起動するとバックグラウンドスレッド内で
        ``GSASUnavailableError`` が起き ``job.status()`` が "failed" になるまで気付けない —
        起動前に明示チェックして 422 error dict へ縮退させる (呼び出し側 [app.py] が変換)。
        """
        if not gsasii_available():
            return dict(_GSAS_UNAVAILABLE_ERROR)
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
            dataset = f"{len(project.histograms)} histogram(s)"
            if project.frames:
                dataset += f" · {len(project.frames)} frame(s)"
            # 【B1: 既存値の保持】: frame/echem は project spec 編集 (histogram/phase/settings/frames)
            #   の都度リセットしていた旧実装から変更 — frames 設定後に echem を取得済みの状態で
            #   別の spec 編集 (例 相追加) を行っても echem 表示が消えないようにする。
            self.project = {
                "name": project.name,
                "dataset": dataset,
                "frame": self.project.get("frame"),
                "echem": self.project.get("echem"),
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
        # 【runner-ready 不変条件】: WorkbenchProject.histograms は「そのまま
        # run_auto_rietveld に渡せる」こと。ロード時 (load_project_spec) と同じ変換を
        # 実行時追加でも通す (未変換 XRDML が refine 失敗を起こした回帰の恒久修正)。
        try:
            hist = convert_histogram_for_runner(
                hist, Path(self._project.spec_dir), len(self._project.histograms)
            )
        except (ValueError, OSError) as exc:
            return {"error": f"could not read data file: {exc}", "error_type": "ValueError"}
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
        # 【レビュー指摘 #2: self._project の read-modify-write をロック下に】: 既存重複チェック
        #   (``self._project.phases`` 読取) から代入 (``self._project = ...``) までを 1 つの
        #   クリティカルセクションにする。無ロックだと、``propose_phase_change`` が同一ターンで
        #   2 件 (auto/bypass 即時適用、または直接 HTTP 経由) 並走したとき、両方が同じ古い
        #   ``self._project.phases`` を読んでからそれぞれ ``dataclasses.replace`` で新タプルを
        #   作り、後勝ちの代入がもう片方の追加相を丸ごと消す (lost update)。
        with self._lock:
            assert self._project is not None
            name = str(phase_name)
            if any(p.phase_name == name for p in self._project.phases):
                return {"error": f"phase already exists: {name}", "error_type": "ValueError"}
            phase = PhaseSpec(structure_path=str(structure_path), phase_name=name)
            self._project = dataclasses.replace(
                self._project, phases=self._project.phases + (phase,)
            )
            self._save_and_refresh("add_phase", {"phase_name": name})
            return self.state()

    def remove_phase(self, phase_name: str) -> dict[str, Any]:
        """POST /api/project/phases/{phase_name}/remove: spec から相を除去する。"""
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        # 【レビュー指摘 #2: 同上】: add_phase と同じ read-modify-write レース (2 件の
        #   propose_phase_change(op=remove) 並走で片方の除去が復活する) をロックで塞ぐ。
        with self._lock:
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
        # 【レビュー指摘 #2: self._project の read-modify-write をロック下に】: この関数は
        #   ``self._project`` を一度だけ読み (``project = self._project``)、ローカル変数へ複数回
        #   ``dataclasses.replace`` を重ねてから最後に ``self._project = project`` で一括代入する
        #   — 読取から代入までの全区間が「他スレッドの並行書込みを巻き込むと消える」レース窓
        #   になる。add_phase/remove_phase と同じ理由でロックする。
        with self._lock:
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
    # POST /api/project/frames (V2b B1)
    # ------------------------------------------------------------------

    def set_frames(self, frames: Any, *, frame_axis: Any = None) -> dict[str, Any]:
        """POST /api/project/frames: フレーム列を**全置換**する (B1, api-contract.md §逐次/operando)。

        パスは spec ディレクトリ基準で絶対化・実在検証する。XRDML は ``load_project_spec`` と同じ
        流儀で XYE へ自己変換する (``convert_frame_for_runner``, ロード時/実行時追加の単一情報源)。
        不正な 1 要素があれば全体を受理しない (部分適用を避ける — set は冪等な全置換)。
        """
        guard = self._guard_project_editable()
        if guard is not None:
            return guard
        if not isinstance(frames, list):
            return {"error": "frames must be a list", "error_type": "ValueError"}
        assert self._project is not None
        project = self._project
        try:
            specs: list[FrameSpec] = []
            for i, fr in enumerate(frames):
                if not isinstance(fr, Mapping):
                    raise ValueError(f"frames[{i}] must be an object")
                fs = FrameSpec.from_dict(fr)
                fs = dataclasses.replace(
                    fs, data_path=_resolve_frame_path(project.spec_dir, fs.data_path)
                )
                if not Path(fs.data_path).exists():
                    raise ValueError(f"frames[{i}] data file not found: {fs.data_path}")
                fs = convert_frame_for_runner(fs, Path(project.spec_dir), i)
                specs.append(fs)
        except (ValueError, TypeError, KeyError, IndexError, AttributeError) as exc:
            return {"error": str(exc), "error_type": "ValueError"}
        axis = str(frame_axis) if frame_axis is not None else project.frame_axis
        self._project = dataclasses.replace(project, frames=tuple(specs), frame_axis=axis)
        self._clear_stale_sequence_and_np_approvals()
        self._save_and_refresh("set_frames", {"n_frames": len(specs)})
        return self.state()

    def _clear_stale_sequence_and_np_approvals(self) -> None:
        """frames 全置換で無効化される逐次結果 + B5 新相承認カードを一括整理する (B1 残骸対策)。

        旧フレーム列に対して求めた ``_sequential_result``/``_sequence`` (viewmodel の
        ``sequence``) と、旧フレームの changepoint に基づく新相承認カード (``np-*``) は、
        フレームが置換された時点で意味を失う — カードが指す ``frame_index`` は新しい
        フレーム列では別のデータを指しうる。P2 (非破壊性) は解析 ledger (Ledger/Snapshot) の
        話であり、置換はここで既に ``project_edit`` (op="set_frames") として記録されるため、
        無効化された「提案」(transcript の approval メッセージ・未解決状態マーカー) 自体の
        整理は P2 に抵触しない。同じ ``frame_index`` が次回逐次実行で再び changepoint と
        判定されれば、``_create_new_phase_approvals`` が新しい承認カードを生成する。
        """
        with self._lock:
            self._sequential_result = None
            self._sequence = None
            self._np_approval_info = {}
            stale_ids = [aid for aid in self._approvals if aid.startswith("np-")]
            for aid in stale_ids:
                del self._approvals[aid]
            self._transcript = [
                msg
                for msg in self._transcript
                if not (
                    msg.get("kind") == "approval"
                    and str(msg.get("action_id", "")).startswith("np-")
                )
            ]

    # ------------------------------------------------------------------
    # POST /api/transcript/message
    # ------------------------------------------------------------------

    def post_message(self, text: str) -> dict[str, Any]:
        """POST /api/transcript/message (V3a)。

        ``source != "none"`` かつ ``mode == "auto"`` かつ ``AgentBridge.available`` のときのみ
        エージェントへ非同期送信する (``bridge.send``)。実行中は ``ConflictError`` (呼び出し側が
        409 へ縮退)。それ以外は従来どおり記録のみ (demo/manual/エージェント不可用時のフォールバック,
        後方互換)。ユーザーメッセージ自体はどちらの経路でも transcript/ledger へ記録する。

        transcript への append は ``self._lock`` 下で行う (V3a レビュー指摘 #3, ``_agent_append`` と
        同じ流儀) — エージェントのバックグラウンドスレッド (``_agent_append``) や
        ``GET /api/viewmodel`` の transcript 読み取りと並走しても、``len(self._transcript)`` に基づく
        id 採番がレースして重複/欠番を起こさない。
        """
        with self._lock:
            msg = {"id": f"t{len(self._transcript) + 1}", "kind": "user", "text": text}
            self._transcript.append(msg)
        self.ledger.append("transcript_message", {"text": text})
        if self._source != "none" and self.mode == "auto" and self._agent_bridge.available:
            started = self._agent_bridge.send(text)
            if not started:
                return {"error": "agent is already running", "error_type": "ConflictError"}
            return {"status": "agent_started"}
        return {"message": dict(msg)}

    def _agent_append(self, kind: str, **fields: Any) -> dict[str, Any]:
        """``AgentBridge.on_event``: transcript へ 1 行 append し、append 済み行 (可変 dict) を返す。

        エージェントのバックグラウンドスレッドから呼ばれるため ``self._lock`` 下で行う
        (`GET /api/viewmodel` の transcript 読み取りとの並走に対して安全)。返す dict は
        ``self._transcript`` に格納された同一オブジェクトなので、呼び出し側 (`AgentBridge`) が
        後から ``row["ret"] = ...`` のように直接書き込めば transcript にも反映される
        (ToolUseBlock → 対応する ToolResultBlock の遅延反映に使う)。
        """
        with self._lock:
            row: dict[str, Any] = {"id": f"t{len(self._transcript) + 1}", "kind": kind, **fields}
            self._transcript.append(row)
            return row

    # ------------------------------------------------------------------
    # GET /api/agent/status (V3a)
    # ------------------------------------------------------------------

    def agent_status(self) -> dict[str, Any]:
        return self._agent_bridge.status()

    # ------------------------------------------------------------------
    # POST /api/phaseid, GET /api/phaseid/status, POST /api/phaseid/add (A4)
    # ------------------------------------------------------------------

    def request_phaseid(
        self, *, mode: Literal["pattern", "residual"], top_k: int = 5, _provider: object = None
    ) -> dict[str, Any]:
        """相同定ジョブを起動する (A4, api-contract.md POST /api/phaseid)。

        refine/phaseid/multistart は同一ジョブ枠 (``self._job``) を共有する — いずれかの実行中は
        ``ConflictError`` (呼び出し側が 409 へ縮退)。``mode="residual"`` は直近 refine の残差
        (``self._fit.plot.h0.residual``) が無ければ ``ConflictError`` (409) を返す。元素系は
        現相集合の CIF から導出する (``_elements_from_project``, pymatgen 遅延 import)。
        Materials Project API キー (環境変数 ``MATERIALS_PROJECT_API``) 未設定は ``ValueError``
        (422)。

        :param _provider: **テスト専用**の供給元注入シーム (§4.5)。実運用は常に ``None`` で
            ``MPReferenceProvider(MPRestClient())`` を使う — callable/オブジェクト注入を実運用経路
            にしない (`docs/design/operando-diagnosis/architecture.md` §4.5)。
        """
        if mode not in ("pattern", "residual"):
            return {"error": f"invalid mode: {mode!r}", "error_type": "ValueError"}
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        # 【共有ジョブ枠の優先確認】: refine/multistart 実行中はここで即 409 にする — 入力
        #   (plot/elements/key) の検証より先に確認することで、実行中はどんな入力であれ一貫して
        #   409 を返す (`add_histogram` 等 `_guard_project_editable` と同じ順序規律)。
        if self._job.status()["status"] == "running":
            return {"error": "a job is already running", "error_type": "ConflictError"}
        project = self._project
        plot = (self._fit.get("plot") or {}).get("h0") or {}
        if mode == "residual":
            residual = plot.get("residual")
            if not residual:
                return {
                    "error": "no refine residual available (run refine first)",
                    "error_type": "ConflictError",
                }
            x, y = plot.get("x"), residual
        else:
            x, y = plot.get("x"), plot.get("yobs")
            if not x or not y:
                return {"error": "no pattern available", "error_type": "ValueError"}
        try:
            elements = _elements_from_project(project)
        except ImportError as exc:
            return {"error": str(exc), "error_type": "ValueError"}
        if not elements:
            return {
                "error": "no elements derivable from current phase CIFs",
                "error_type": "ValueError",
            }
        if _provider is None:
            try:
                from ..mp.client import MPRestClient

                MPRestClient()  # 事前キー検証のみ (ネットワークアクセスなし)
            except ValueError as exc:
                return {"error": str(exc), "error_type": "ValueError"}

        def runner():
            from ..reference.iterative import IdentifyConfig
            from ..reference.iterative import identify_pattern as _identify_pattern

            provider = _provider
            if provider is None:
                from ..mp.client import MPRestClient
                from ..mp.provider import MPReferenceProvider

                provider = MPReferenceProvider(MPRestClient())
            cfg = IdentifyConfig(max_phases=max(1, int(top_k)))
            return _identify_pattern(
                np.asarray(x, dtype=float), np.asarray(y, dtype=float), provider,
                elements=elements, cfg=cfg, ledger=self.ledger,
            )

        started = self._job.start(
            runner,
            on_success=self._on_phaseid_success,
            on_failure=self._on_phaseid_failure,
            on_started=lambda: self.ledger.append("phaseid_request", {"mode": mode, "top_k": top_k}),
            kind="phaseid",
        )
        if not started:
            return {"error": "a job is already running", "error_type": "ConflictError"}
        return {"status": "started"}

    def _on_phaseid_success(self, result: Any) -> None:
        """相同定成功時のコールバック (`reference.iterative.IterativeIdentification`)。"""
        candidates: list[dict[str, Any]] = []
        accepted_by_id: dict[str, Any] = {}
        for i, accepted in enumerate(result.accepted):
            ref = accepted.reference
            candidates.append(
                {
                    "rank": i + 1,
                    "formula": ref.formula,
                    "source": accepted.source,
                    "sg": ref.spacegroup or "",
                    "dara": finite_or_none(accepted.score),
                    "mwmsx": "",
                    "strain": f"{accepted.strain * 100:.1f}%",
                    "chem_guard": "ok",
                    "guard_fail": False,
                    "mp_id": ref.phase_id,
                }
            )
            accepted_by_id[ref.phase_id] = accepted
        with self._lock:
            self._phaseid_candidates = candidates
            self._phaseid_accepted_by_id = accepted_by_id
            self.ledger.append("phaseid_finished", {"n_candidates": len(candidates)})

    def _on_phaseid_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.ledger.append("phaseid_failed", {"error": str(exc)})

    def phaseid_add(self, *, formula: Any, mp_id: Any) -> dict[str, Any]:
        """ADD AS PHASE: 相同定候補を CIF 物質化して project の相集合へ追加する (A4)。

        再精密化は行わない (ユーザーが RUN で明示する, api-contract.md)。候補の等方 strain
        (``request_phaseid`` で求めたもの) が判れば再物質化に引き継ぐ — 直近相同定に無い
        ``mp_id`` (候補一覧更新後の古い呼び出し等) は strain=0.0 にフォールバックする。
        """
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        if not formula or not mp_id:
            return {"error": "formula/mp_id is required", "error_type": "ValueError"}
        if self._job.status()["status"] == "running":
            return {"error": "a job is already running", "error_type": "ConflictError"}
        project = self._project
        try:
            elements = _elements_from_project(project)
        except ImportError as exc:
            return {"error": str(exc), "error_type": "ValueError"}
        if not elements:
            return {
                "error": "no elements derivable from current phase CIFs",
                "error_type": "ValueError",
            }
        accepted = self._phaseid_accepted_by_id.get(str(mp_id))
        strain = float(accepted.strain) if accepted is not None else 0.0
        try:
            from ..insitu.phaseid import MPMaterializer
            from ..mp.client import MPRestClient

            materializer = MPMaterializer(MPRestClient())
            data_dir = Path(project.spec_dir) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            safe_name = lifecycle.sanitize_filename(f"{formula}_{mp_id}.cif")
            cif_path = str(data_dir / safe_name)
            materializer.materialize(str(mp_id), elements, cif_path, strain=strain)
        except Exception as exc:  # noqa: BLE001 — MP/pymatgen 由来の失敗を error dict へ縮退
            return {"error": f"could not materialize phase: {exc}", "error_type": "ValueError"}
        phase_name = _unique_phase_name(project, str(formula))
        return self.add_phase(structure_path=cif_path, phase_name=phase_name)

    # ------------------------------------------------------------------
    # POST /api/multistart, GET /api/multistart/status (A5)
    # ------------------------------------------------------------------

    def request_multistart(self, *, n_starts: int = 3, scale: float = 0.007) -> dict[str, Any]:
        """マルチスタート大域最適確認ジョブを起動する (A5, api-contract.md POST /api/multistart)。

        refine/phaseid と同一ジョブ枠を共有する (実行中は 409)。完了で ``hypotheses.basin`` +
        evidence の corroborated 行を供給する (``_on_multistart_success``)。
        """
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        gsas_guard = self._guard_gsas_available()
        if gsas_guard is not None:
            return gsas_guard
        project = self._project

        def runner():
            from ..autorietveld.multistart import run_multistart_rietveld
            from ..autorietveld.recipe import build_recipe
            from ..multistart.perturb import MultistartConfig, PerturbationSpec

            recipe = build_recipe(
                project.histograms, project.phases, background_coeffs=project.background_coeffs
            )
            config = MultistartConfig(
                n_starts=int(n_starts), spec=PerturbationSpec(lattice_frac=float(scale))
            )
            return run_multistart_rietveld(
                project.histograms, project.phases, config=config, ledger=self.ledger,
                recipe=recipe, max_cyc=project.max_cyc,
            )

        started = self._job.start(
            runner,
            on_success=self._on_multistart_success,
            on_failure=self._on_multistart_failure,
            on_started=lambda: self.ledger.append(
                "multistart_request", {"n_starts": n_starts, "scale": scale}
            ),
            kind="multistart",
        )
        if not started:
            return {"error": "a job is already running", "error_type": "ConflictError"}
        return {"status": "started"}

    def _on_multistart_success(self, result: Any) -> None:
        """マルチスタート成功時のコールバック (`autorietveld.multistart.RietveldMultistartResult`)。"""
        project = self._project
        first_phase = project.phases[0].phase_name if project and project.phases else None
        points: list[dict[str, Any]] = []
        for start in result.starts:
            if start.result is None:
                continue
            cells = start.result.refined_cells
            a_val = cells.get(first_phase, (None,))[0] if first_phase else None
            points.append(
                {
                    "x": finite_or_none(a_val),
                    "y": finite_or_none(start.result.final_rwp),
                    "label": f"start {start.index + 1}",
                }
            )
        corroborated = bool(result.is_global_corroborated)
        note = (
            f"n={result.n_starts} · basins={result.n_basins} · "
            f"corroborated={'yes' if corroborated else 'no'}"
        )
        with self._lock:
            self._basin = {"points": points}
            self._hyp_evidence.append(["corroborated", note])
            self.ledger.append(
                "multistart_finished",
                {"n_basins": result.n_basins, "corroborated": corroborated},
            )

    def _on_multistart_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.ledger.append("multistart_failed", {"error": str(exc)})

    # ------------------------------------------------------------------
    # POST /api/mem, GET /api/mem/status (V3b, FR-601)
    # ------------------------------------------------------------------

    def request_mem(
        self,
        *,
        phase: "str | None" = None,
        hist: "str | None" = None,
        map_type: str = "Fobs",
        dmin: float = 0.9,
        grid_step: float = 0.25,
    ) -> dict[str, Any]:
        """MEM 密度マップジョブを起動する (api-contract.md POST /api/mem)。

        refine/phaseid/multistart/sequential と同一ジョブ枠 (``self._job``) を共有する
        (kind="mem" — GSAS/Dysnomia の直列実行の前提を保つ, api-contract.md §MEM 密度マップ)。

        未精密化 (project の gpx が無い/未存在) と Dysnomia バイナリ未解決は、いずれもジョブ
        起動前にここで検出し 422 error dict へ縮退させる (``_guard_gsas_available`` と同じ
        「起動前検出」の流儀 — バックグラウンド失敗 [job.status()="failed"] まで持ち越すと
        ③/人間が気付くまでポーリングを要する)。Dysnomia 未解決は ``MEMUnavailableError``
        (api-contract.md「Dysnomia バイナリ不在は 422」)。
        """
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        if map_type not in ("Fobs", "delt-F"):
            return {"error": f"invalid map_type: {map_type!r}", "error_type": "ValueError"}
        # 【共有ジョブ枠の優先確認】: request_phaseid と同じ順序規律 — gpx/Dysnomia の実体チェックより
        #   先に確認することで、実行中はどんな入力であれ一貫して 409 を返す。
        if self._job.status()["status"] == "running":
            return {"error": "a job is already running", "error_type": "ConflictError"}
        gpx_path = self._project.gpx_path
        if not gpx_path or not Path(gpx_path).exists():
            return {
                "error": "no refined gpx available (run refine first)",
                "error_type": "ValueError",
            }
        if map_type == "Fobs":
            # 【delt-F は Dysnomia 不要】: `mem.gsas.run_dysnomia_mem` は map_type="Fobs" のときのみ
            #   Dysnomia バイナリを要求する (差フーリエは GSAS ネイティブ FourierMap のみ)。
            from ..mem.gsas import resolve_dysnomia_binary

            if resolve_dysnomia_binary() is None:
                return {
                    "error": (
                        "Dysnomia binary not found "
                        "(see tsumugin.mem.gsas.resolve_dysnomia_binary search order)"
                    ),
                    "error_type": "MEMUnavailableError",
                }

        def runner() -> dict[str, Any]:
            from ..mcp.mem_tools import mem_density

            result = mem_density(
                gpx_path, phase=phase, hist=hist, map_type=map_type,
                dmin=dmin, grid_step=grid_step,
            )
            if "error" in result:
                # ② mem_density は例外を送出せず error dict へ縮退する契約 (`_degrade.degrade_oserror`
                #   + `MEMUnavailableError` 捕捉) — ジョブ枠の failed 経路 (on_failure/ledger
                #   "mem_failed") へ載せ直す。
                raise RuntimeError(str(result.get("error")))
            return result

        started = self._job.start(
            runner,
            on_success=self._on_mem_success,
            on_failure=self._on_mem_failure,
            on_started=lambda: self.ledger.append(
                "mem_request", {"map_type": map_type, "phase": phase, "hist": hist}
            ),
            kind="mem",
        )
        if not started:
            return {"error": "a job is already running", "error_type": "ConflictError"}
        return {"status": "started"}

    def _on_mem_success(self, result: dict[str, Any]) -> None:
        """MEM 密度ジョブ成功時のコールバック (``mcp.mem_tools.mem_density`` の戻り値そのまま)。"""
        kind = str(result.get("density_kind") or "")
        unit = _density.UNIT_BY_DENSITY_KIND.get(kind, "")
        peaks_view: list[dict[str, Any]] = []
        for p in result.get("peaks") or []:
            frac = p.get("frac") or (None, None, None)
            fx, fy, fz = (finite_or_none(x) for x in frac)
            mag = finite_or_none(p.get("magnitude"))
            dist = p.get("distance")
            peaks_view.append(
                {
                    "position": f"({fx}, {fy}, {fz})",
                    "density": f"{mag} {unit}".strip() if mag is not None else f"n/a {unit}".strip(),
                    "assign": (p.get("nearest_atom") or "")
                    + ("" if dist is not None and dist < 1.0 else "?"),
                }
            )
        grd_path = result.get("grd_path")
        map_view: "dict[str, Any] | None" = None
        if grd_path:
            try:
                map_view = _density.extract_mem_map(
                    grd_path,
                    density_kind=kind,
                    vmin=result.get("density_min") or 0.0,
                    vmax=result.get("density_max") or 0.0,
                )
            except (OSError, ValueError):
                # .grd が読めない (テスト注入 fake 等) 場合は map なし・peaks のみ供給する。
                map_view = None
        note = (
            f"{result.get('density_kind', '')} · converged="
            f"{'yes' if result.get('converged') else 'no'} · "
            f"n_reflections={result.get('n_reflections')}"
        )
        with self._lock:
            self._mem_peaks = peaks_view
            self._mem_view = {"map": map_view, "peaks": list(peaks_view), "note": note}
            self.ledger.append(
                "mem_finished",
                {"n_peaks": len(peaks_view), "converged": bool(result.get("converged"))},
            )

    def _on_mem_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.ledger.append("mem_failed", {"error": str(exc)})

    # ------------------------------------------------------------------
    # GET /api/export/gpx (A6)
    # ------------------------------------------------------------------

    def export_gpx_info(self) -> dict[str, Any]:
        """keep_gpx 生成物のダウンロード情報を返す (A6, FR-424)。未精密化/project 未読込は 404。"""
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "NotFoundError"}
        path = self._project.gpx_path
        if not path or not Path(path).exists():
            return {"error": "no refined gpx available yet", "error_type": "NotFoundError"}
        return {"path": path, "filename": f"{self._project.name}.gpx"}

    # ------------------------------------------------------------------
    # POST /api/sequential, GET /api/sequential/status (V2b B2/B3)
    # ------------------------------------------------------------------

    def _guard_frames_configured(
        self, project: "WorkbenchProject"
    ) -> "dict[str, Any] | None":
        """frames が 1 件以上設定されているかのガード (B2/B3, 独立メソッドに切り出し変異実証可能に)。"""
        if not project.frames:
            return {
                "error": "no frames configured (POST /api/project/frames first)",
                "error_type": "ValueError",
            }
        return None

    def request_sequential(
        self,
        *,
        mode: str,
        anchor_table: "Mapping[str, Any] | None" = None,
        use_charge_constraint: bool = False,
    ) -> dict[str, Any]:
        """逐次/operando 解析ジョブを起動する (B2/B3, api-contract.md §逐次/operando)。

        ``mode="forward"`` は ② ``sequential_rietveld``、``mode="anchored"`` は ②
        ``anchored_sequential`` をジョブ化する。**runner はどちらも instrument spec 経由で
        サーバ側が組む** (``_build_instrument_spec`` — histograms[0] から radiation/geometry/
        instprm/背景項数/max_cyc を写す。M9 の系列 = 単一装置の前提)。**エンジン内自動受理
        (``phase_finder``) は渡さない** — 新相採否は B5 の承認カード経由 (提案≠適用)。

        refine/phaseid/multistart と同一ジョブ枠 (``self._job``) を共有する (実行中は 409)。
        frames 未設定は 422。``mode="anchored"`` で ``anchor_table`` 省略も 422。
        """
        if mode not in ("forward", "anchored"):
            return {"error": f"invalid mode: {mode!r}", "error_type": "ValueError"}
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        gsas_guard = self._guard_gsas_available()
        if gsas_guard is not None:
            return gsas_guard
        project = self._project
        guard = self._guard_frames_configured(project)
        if guard is not None:
            return guard
        if not project.histograms:
            return {"error": "no histograms configured", "error_type": "ValueError"}
        if mode == "anchored" and not anchor_table:
            return {
                "error": "anchor_table is required for mode='anchored'",
                "error_type": "ValueError",
            }
        if self._job.status()["status"] == "running":
            return {"error": "a job is already running", "error_type": "ConflictError"}

        cc_spec: "dict[str, Any] | None" = None
        if use_charge_constraint:
            with self._lock:
                echem = self._echem_result
            if echem is None or not echem.get("targets"):
                return {
                    "error": "no echem targets available (POST /api/echem first)",
                    "error_type": "ValueError",
                }
            cc_config = project.charge_constraint_config
            if not cc_config:
                return {
                    "error": (
                        "project.json missing charge_constraint_config "
                        "(required for use_charge_constraint)"
                    ),
                    "error_type": "ValueError",
                }
            cc_spec = {
                "config": dict(cc_config),
                "targets": echem["targets"],
                "per_phase_content": {},
            }

        frames_payload = [f.to_dict() for f in project.frames]
        phases_payload = [p.to_dict() for p in project.phases]
        instrument = _build_instrument_spec(project)
        anchor_table_payload = (
            {str(k): list(v) for k, v in anchor_table.items()} if anchor_table else None
        )

        n_frames = len(project.frames)

        def runner() -> dict[str, Any]:
            # 【進捗可視化】: api-contract.md は「進捗 = ledger (frame k/N)」を約束するが、
            #   ① sequential_rietveld/anchored_sequential は同期呼び出しで完了までフレーム単位の
            #   進捗を返さない (engine 内部 Ledger は結果に畳まれるだけで実行中は見えない)。
            #   ①②の呼び出し契約 (runner/instrument spec) を変えずに実行中も session ledger が
            #   動いていることを示すため、一定間隔でハートビートを追記する (elapsed_s のみ; 厳密な
            #   frame k/N は ①②側の ledger 注入が必要で本セッション層の変更では届かない — 既知の
            #   残課題)。GSAS 実行は数十分かかりうるため、無音の 202→ポーリングだけでは「動いて
            #   いるのか固まっているのか」を LEDGER タブから判別できなかった (実走で確認した欠陥)。
            stop_heartbeat = threading.Event()
            start_t = time.monotonic()

            def _heartbeat() -> None:
                while not stop_heartbeat.wait(_SEQUENTIAL_HEARTBEAT_INTERVAL_S):
                    self.ledger.append(
                        "sequential_progress",
                        {
                            "mode": mode,
                            "n_frames": n_frames,
                            "elapsed_s": round(time.monotonic() - start_t, 1),
                        },
                    )

            hb_thread = threading.Thread(target=_heartbeat, daemon=True)
            hb_thread.start()
            try:
                if mode == "forward":
                    from ..mcp.insitu_tools import sequential_rietveld

                    result = sequential_rietveld(
                        frames_payload, phases_payload,
                        instrument=instrument, charge_constraint=cc_spec,
                    )
                else:
                    from ..mcp.anchor_tools import anchored_sequential

                    result = anchored_sequential(
                        frames_payload, phases_payload,
                        anchor_table=anchor_table_payload,
                        instrument=instrument, charge_constraint=cc_spec,
                    )
            finally:
                stop_heartbeat.set()
                hb_thread.join(timeout=2.0)
            if "error" in result and "error_type" in result:
                raise RuntimeError(f"{result['error_type']}: {result['error']}")
            return result

        started = self._job.start(
            runner,
            on_success=self._on_sequential_success,
            on_failure=self._on_sequential_failure,
            on_started=lambda: self.ledger.append(
                "sequential_request", {"mode": mode, "n_frames": len(project.frames)}
            ),
            kind="sequential",
        )
        if not started:
            return {"error": "a job is already running", "error_type": "ConflictError"}
        return {"status": "started"}

    def _on_sequential_success(self, result: "dict[str, Any]") -> None:
        """逐次ジョブ成功時のコールバック (B2/B3)。sequence viewmodel を構築し、FR-403 の
        infeasible フレームを ReviewQueue へ自動追加、B5 の新相承認カードを生成する。
        """
        project = self._project
        view = _build_sequence_view(result, project)
        frames = list(result.get("frames", []))
        infeasible = [f for f in frames if f.get("alkali_feasibility") == "infeasible"]
        with self._lock:
            self._sequential_result = result
            self._sequence = view
            self.ledger.append("sequential_finished", {"n_frames": len(frames)})
            for f in infeasible:
                item = self.review_queue.add(
                    "incomparable_evidence",
                    hypothesis_id=None,
                    frame_index=f.get("frame_index"),
                    detail=(
                        f"frame {f.get('frame_index')}: coulometric feasibility infeasible "
                        f"(x_echem={f.get('alkali_x_echem')}, x_xrd={f.get('alkali_x_xrd')})"
                    ),
                )
                self._review_meta[item.item_id] = {
                    "severity": "echem",
                    "title": f"frame {f.get('frame_index')}: coulometric feasibility infeasible",
                    "ref": "FR-403",
                }
            self._create_new_phase_approvals(frames, project)

    def _on_sequential_failure(self, exc: BaseException) -> None:
        with self._lock:
            self.ledger.append("sequential_failed", {"error": str(exc)})

    # ------------------------------------------------------------------
    # B5: 新相承認カード (transcript approval)
    # ------------------------------------------------------------------

    def _create_new_phase_approvals(
        self, frames: "list[dict[str, Any]]", project: "WorkbenchProject | None"
    ) -> None:
        """changepoint/未説明残差のあるフレームについて承認カードを生成する (B5, 呼び出し元がロック保持)。

        提案≠適用: カードは transcript に積むだけで、相追加は ``resolve_approval`` の approve
        でのみ起きる (エンジン内自動受理 [``phase_finder``] は使わない, api-contract.md)。
        """
        for f in frames:
            frame_idx = f.get("frame_index")
            if frame_idx is None:
                continue
            rationale = _new_phase_rationale(f)
            if rationale is None:
                continue
            action_id = f"np-{frame_idx}"
            if action_id in self._np_approval_info or action_id in self._approvals:
                continue  # 既に提案済み/解決済み (同一フレームへの重複カード生成を避ける)
            if project is not None and project.frames and 0 <= frame_idx < len(project.frames):
                fs = project.frames[frame_idx]
                self._np_approval_info[action_id] = {
                    "frame_index": frame_idx,
                    "data_path": fs.data_path,
                    "data_format": fs.data_format,
                }
            msg = {
                "id": f"t{len(self._transcript) + 1}",
                "kind": "approval",
                "action_id": action_id,
                "title": f"frame {frame_idx}: 新相の可能性",
                "rationale": rationale,
                "action_json": json.dumps(
                    {"frame_index": frame_idx, "mode": "pattern"}, ensure_ascii=False
                ),
                "state": "pending",
            }
            self._transcript.append(msg)

    def _resolve_new_phase_approval(
        self, action_id: str, *, decision: Literal["approve", "reject"]
    ) -> dict[str, Any]:
        """B5 新相承認カードの解決 (``resolve_approval`` から action_id prefix "np-" で分岐)。"""
        if decision == "reject":
            self.ledger.append("approval_decision", {"action_id": action_id, "decision": "reject"})
            self._approvals[action_id] = {"state": "rejected", "snapshot_id": None}
            return {
                "state": "rejected", "snapshot_id": None,
                "ledger_index": self.ledger.entries[-1].index,
            }

        info = self._np_approval_info.get(action_id)
        if info is None or self._project is None:
            return {"error": f"unknown approval action: {action_id}", "error_type": "NotFoundError"}
        try:
            elements = _elements_from_project(self._project)
        except ImportError as exc:
            return {"error": str(exc), "error_type": "ValueError"}
        if not elements:
            self.ledger.append(
                "approval_decision", {"action_id": action_id, "decision": "approve", "n_candidates": 0}
            )
            self._approvals[action_id] = {"state": "approved", "snapshot_id": None}
            return {
                "state": "approved", "snapshot_id": None,
                "ledger_index": self.ledger.entries[-1].index,
            }
        from ..mcp.insitu_tools import identify_and_add_phase
        from ..reference.io import load_pattern

        try:
            two_theta, intensity = load_pattern(info["data_path"], info["data_format"])
        except (OSError, ValueError) as exc:
            return {"error": f"could not read frame pattern: {exc}", "error_type": "ValueError"}
        workdir = str(Path(self._project.spec_dir) / "data")
        try:
            found = identify_and_add_phase(
                two_theta.tolist(), intensity.tolist(), elements, workdir, top_k=1
            )
        except Exception as exc:  # noqa: BLE001 — 境界縮退 (MP キー欠落/ネットワーク等)
            return {"error": f"phase identification failed: {exc}", "error_type": "ValueError"}
        if "error" in found:
            # ② の error dict を「承認済み・候補 0」と誤読しない — 失敗は失敗として返し、
            # 承認カードは pending のまま (ユーザーが再試行できる)。
            return {
                "error": f"phase identification failed: {found['error']}",
                "error_type": str(found.get("error_type", "ValueError")),
            }
        candidates = found.get("candidates") or []
        self.ledger.append(
            "approval_decision",
            {"action_id": action_id, "decision": "approve", "n_candidates": len(candidates)},
        )
        if not candidates:
            self._approvals[action_id] = {"state": "approved", "snapshot_id": None}
            return {
                "state": "approved", "snapshot_id": None,
                "ledger_index": self.ledger.entries[-1].index,
            }
        top = candidates[0]
        phase_name = _unique_phase_name(self._project, str(top.get("formula", "new_phase")))
        add_result = self.add_phase(
            structure_path=top["phase_spec"]["structure_path"], phase_name=phase_name
        )
        if "error" in add_result:
            self._approvals[action_id] = {"state": "approved", "snapshot_id": None}
            return {
                "state": "approved", "snapshot_id": None,
                "ledger_index": self.ledger.entries[-1].index,
            }
        self._approvals[action_id] = {"state": "approved", "snapshot_id": None}
        return {
            "state": "approved", "snapshot_id": None,
            "ledger_index": self.ledger.entries[-1].index,
        }

    # ------------------------------------------------------------------
    # POST /api/echem (V2b B4)
    # ------------------------------------------------------------------

    def request_echem(
        self,
        *,
        mpr_path: Any,
        offset_s: "float | None" = None,
        interval_s: "float | None" = None,
        n_frames: "int | None" = None,
        frame_epoch_s: "Sequence[float] | None" = None,
        sign: int = 1,
        x0: "float | None" = None,
        active_mass_mg: "float | None" = None,
        formula_weight: "float | None" = None,
        z: int = 1,
        x0_source: str = "given",
        clamp: bool = False,
    ) -> dict[str, Any]:
        """電気化学同期を実行する (B4, 同期実行)。② ``align_echem``/``alkali_budget`` を委譲。

        ``x0`` が与えられれば ``alkali_budget`` も実行し ``targets`` を供給する (省略時は
        ``align_echem`` のみで ``targets=None``)。``n_frames``/``offset_s``/``interval_s`` 省略時、
        ``frame_epoch_s`` も無ければ project の frames 数を既定にする。
        """
        if self._source != "project" or self._project is None:
            return {"error": "no project loaded", "error_type": "ValueError"}
        if not isinstance(mpr_path, str) or not mpr_path.strip():
            return {"error": "mpr_path is required", "error_type": "ValueError"}
        n = n_frames
        if n is None and frame_epoch_s is None and self._project.frames:
            n = len(self._project.frames)
        if n is None and frame_epoch_s is None:
            return {
                "error": "n_frames (or frame_epoch_s) is required (no frames configured to default from)",
                "error_type": "ValueError",
            }

        from ..mcp.echem_tools import align_echem, alkali_budget

        cadence_kwargs: dict[str, Any] = {}
        if frame_epoch_s is not None:
            cadence_kwargs["frame_epoch_s"] = list(frame_epoch_s)
        else:
            cadence_kwargs.update(offset_s=offset_s, interval_s=interval_s, n_frames=n)

        result = align_echem(mpr_path, clamp=clamp, **cadence_kwargs)
        if "error" in result:
            self.ledger.append("echem_failed", {"error": result["error"]})
            return {"error": result["error"], "error_type": "ValueError"}

        out = dict(result)
        out["targets"] = None
        if x0 is not None:
            if active_mass_mg is None or formula_weight is None:
                return {
                    "error": "active_mass_mg/formula_weight are required when x0 is given",
                    "error_type": "ValueError",
                }
            budget = alkali_budget(
                mpr_path, float(active_mass_mg), float(formula_weight),
                x0=float(x0), z=int(z), sign=int(sign), x0_source=str(x0_source),
                clamp=clamp, **cadence_kwargs,
            )
            if "error" in budget:
                self.ledger.append("echem_failed", {"error": budget["error"]})
                return {"error": budget["error"], "error_type": "ValueError"}
            out["targets"] = budget["targets"]
            out["x0"] = budget["x0"]
            out["x0_source"] = budget["x0_source"]
            out["sign"] = budget["sign"]
            out["budget_warnings"] = budget["warnings"]

        with self._lock:
            self._echem_result = out
            self._channels = _build_echem_channels(out)
            self.project["echem"] = _echem_state_summary(out)
            self.ledger.append(
                "echem_finished",
                {"n_frames": len(out.get("frames", [])), "has_targets": out["targets"] is not None},
            )
        return out


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


def _elements_from_project(project: WorkbenchProject) -> list[str]:
    """現相集合の CIF から構成元素を導出する (A4, `insitu.phaseid` の先例に倣い pymatgen 遅延 import)。

    個別 CIF の読込失敗 (壊れた 1 相・非対応形式) は無視して次の相へ進む — 1 相の欠陥で相同定要求
    全体を失敗させない。pymatgen 自体が未導入なら ``ImportError`` を送出する (呼び出し側が
    ``ValueError`` error dict へ変換する)。

    :returns: 元素記号の昇順ソート列 (重複排除)。相 0 件/全相読込失敗なら空リスト
    """
    from pymatgen.core import Structure

    elements: set[str] = set()
    for p in project.phases:
        try:
            structure = Structure.from_file(p.structure_path)
        except Exception:  # noqa: BLE001 — 壊れた 1 相で全体を失敗させない (安全側)
            continue
        elements.update(str(e) for e in structure.composition.elements)
    return sorted(elements)


def _unique_phase_name(project: WorkbenchProject, base: str) -> str:
    """``base`` が既存相名と衝突しないよう連番を付けた相名を返す (A4 ADD AS PHASE)。"""
    existing = {p.phase_name for p in project.phases}
    if base not in existing:
        return base
    i = 2
    while f"{base}_{i}" in existing:
        i += 1
    return f"{base}_{i}"


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
    """実 project から段階解放レシピを組み STAGES viewmodel の初期状態を作る。

    recipe 由来のステージは「次の RUN で実行される予定」の段であり released=True を既定と
    する (OFF はユーザーの明示的除外)。released=False 既定だとフロントの stageOn 同期 →
    stages_on 全 false → 空 recipe の縮退 run (履歴空で "done") が起きる (GUI 通し実証で
    実際に発生した回帰)。
    """
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
                "released": True,
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


# ---------------------------------------------------------------------------
# V2b 逐次/operando 接続 (B1-B5) ヘルパ
# ---------------------------------------------------------------------------


def _resolve_frame_path(spec_dir: str, raw: str) -> str:
    """``raw`` を ``spec_dir`` 基準で絶対化する (``project._abspath`` と同じ流儀の公開版)。"""
    p = Path(raw)
    if p.is_absolute():
        return str(p)
    return str((Path(spec_dir) / p).resolve())


def _build_instrument_spec(project: WorkbenchProject) -> dict[str, Any]:
    """② ``sequential_rietveld``/``anchored_sequential`` の ``instrument`` spec を
    ``histograms[0]`` から組む (B2/B3, api-contract.md: 「フレーム列の装置条件は histograms[0]
    [...] を共有する」)。
    """
    h0 = project.histograms[0]
    return {
        "path": h0.instrument_path,
        "radiation": h0.radiation.value,
        "geometry": h0.geometry.value,
        "background_coeffs": project.background_coeffs,
        "max_cyc": project.max_cyc,
    }


def _new_phase_rationale(f: "Mapping[str, Any]") -> "str | None":
    """フレームが B5 新相承認カードの対象か判定し、対象なら根拠テキストを返す (対象外は None)。

    トリガ: changepoint (①エンジンの変化点検出) か、残差レポートの ``peak_numerator_fraction``
    (背景でなくピーク域が Rwp 分子の主因) が高く未説明特徴を持つフレーム。
    """
    if f.get("changepoint"):
        reasons = ", ".join(str(r) for r in (f.get("changepoint_reasons") or ()))
        return "changepoint detected" + (f" ({reasons})" if reasons else "")
    rep = f.get("residual_report")
    if not rep:
        return None
    features = rep.get("top_features") or []
    pnf = rep.get("peak_numerator_fraction")
    if features and pnf is not None and pnf > 0.5:
        return (
            f"{len(features)} unexplained residual feature(s), "
            f"peak_numerator_fraction={pnf:.2f}"
        )
    return None


def _cell_component(cell: "list[Any] | None", index: int) -> "float | None":
    if not cell or len(cell) <= index:
        return None
    return cell[index]


def _frame_is_crossover(frame_idx: int, crossovers: "list[dict[str, Any]]") -> bool:
    for c in crossovers:
        if c.get("crossover_frame") == frame_idx or c.get("onset_frame") == frame_idx:
            return True
    return False


def _build_segments_view(
    crossovers: "list[dict[str, Any]]",
    anchors_raw: "list[dict[str, Any]]",
    frames: "list[dict[str, Any]]",
) -> list[dict[str, Any]]:
    """crossovers (② ``anchored_sequential`` 出力) を契約 ``sequence.segments`` 形へ写す。

    ⚠ ① M10 エンジンは採用経路の ``total_bic`` を 1 つしか持たない (前方/後方それぞれの bic は
    ledger に残らない) — 契約例の "41 208 / 39 402" のような両側表記はできないため、単一値を
    そのまま出す (判断点、report 参照)。"forward"/"backward" の相集合は区間左右のアンカーの相集合を
    充てる (crossover 前後で相集合が変わる区間の意味と整合)。
    """
    anchors_by_frame = {a.get("frame"): a for a in anchors_raw}
    frames_by_index = {f.get("frame_index"): f for f in frames}
    rows: list[dict[str, Any]] = []
    for c in crossovers:
        left, right = c.get("left"), c.get("right")
        forward_phases = "+".join(anchors_by_frame.get(left, {}).get("phases", []) or ())
        backward_phases = "+".join(anchors_by_frame.get(right, {}).get("phases", []) or ())
        cf, onf = c.get("crossover_frame"), c.get("onset_frame")
        fwd_rwp = frames_by_index.get(cf, {}).get("rwp") if cf is not None else None
        bwd_rwp = frames_by_index.get(onf, {}).get("rwp") if onf is not None else None
        if cf is None:
            selected = "backward"
        elif onf is None:
            selected = "forward"
        else:
            selected = "mixed"
        total_bic = c.get("total_bic")
        rows.append(
            {
                "segment": (
                    f"fr{left:03d}–fr{right:03d}"
                    if left is not None and right is not None
                    else ""
                ),
                "forward": forward_phases,
                "backward": backward_phases,
                "rwp": (
                    f"{fwd_rwp:.2f} / {bwd_rwp:.2f}"
                    if fwd_rwp is not None and bwd_rwp is not None
                    else ""
                ),
                "total_bic": f"{total_bic:.0f}" if total_bic is not None else "",
                "selected": selected,
            }
        )
    return rows


def _build_sequence_note(result: "Mapping[str, Any]") -> str:
    n = len(result.get("frames") or ())
    warnings = list(result.get("warnings") or ())
    note = f"{n} frame(s)"
    if warnings:
        note += " · " + "; ".join(str(w) for w in warnings[:2])
    return note


def _frame_row(f: "Mapping[str, Any]", project: "WorkbenchProject | None") -> dict[str, Any]:
    idx = f.get("frame_index")
    label = ""
    if project is not None and project.frames and idx is not None and 0 <= idx < len(project.frames):
        fs = project.frames[idx]
        label = fs.label or os.path.basename(fs.data_path)
    cells = {
        name: [finite_or_none(v) for v in cell]
        for name, cell in (f.get("refined_cells") or {}).items()
    }
    fractions = {k: finite_or_none(v) for k, v in (f.get("phase_weight_fractions") or {}).items()}
    return {
        "frame": idx,
        "label": label,
        "axis_value": finite_or_none(f.get("axis_value")) if f.get("axis_value") is not None else None,
        "rwp": finite_or_none(f.get("rwp")),
        "cells": cells,
        "fractions": fractions,
        "changepoint": bool(f.get("changepoint")),
    }


def _build_sequence_view(
    result: "Mapping[str, Any]", project: "WorkbenchProject | None"
) -> dict[str, Any]:
    """② 逐次/operando 結果 dict を契約 ``viewmodel.sequence`` 形へ写す (B2/B3)。

    charts 3 本 (rwp / lattice a,c per 相 / phase_weight_fractions+x_echem overlay) +
    anchors (anchored 時のみ) + segments (crossovers 写像) + per-frame 表。
    """
    frames = list(result.get("frames", []))
    phase_names = list(result.get("phase_names", []))
    xs = [f.get("frame_index") for f in frames]

    rwp_series = [finite_or_none(f.get("rwp")) for f in frames]
    charts: list[dict[str, Any]] = [
        {
            "id": "rwp", "title": "Rwp vs frame",
            "series": {"x": xs, "ys": [rwp_series], "labels": ["Rwp"]},
        }
    ]

    lat_ys: list[list[Any]] = []
    lat_labels: list[str] = []
    for name in phase_names:
        a_series, c_series = [], []
        for f in frames:
            cell = (f.get("refined_cells") or {}).get(name)
            a_series.append(_cell_component(cell, 0))
            c_series.append(_cell_component(cell, 2))
        lat_ys.append(a_series)
        lat_labels.append(f"{name} a")
        lat_ys.append(c_series)
        lat_labels.append(f"{name} c")
    charts.append(
        {
            "id": "lattice", "title": "lattice a/c vs frame",
            "series": {"x": xs, "ys": lat_ys, "labels": lat_labels} if lat_labels else None,
        }
    )

    frac_ys: list[list[Any]] = []
    frac_labels: list[str] = []
    for name in phase_names:
        series = [(f.get("phase_weight_fractions") or {}).get(name) for f in frames]
        frac_ys.append(series)
        frac_labels.append(name)
    echem_series = [f.get("alkali_x_echem") for f in frames]
    if any(v is not None for v in echem_series):
        frac_ys.append(echem_series)
        frac_labels.append("x_echem")
    charts.append(
        {
            "id": "phase_fraction", "title": "phase fraction vs frame (x_echem overlay)",
            "series": {"x": xs, "ys": frac_ys, "labels": frac_labels} if frac_labels else None,
        }
    )

    crossovers = list(result.get("crossovers") or [])
    anchors_raw = list(result.get("anchors") or [])
    anchors = [
        {"id": f"fr{a.get('frame'):03d}", "crossover": _frame_is_crossover(a.get("frame"), crossovers)}
        for a in anchors_raw
    ]
    segments = _build_segments_view(crossovers, anchors_raw, frames)

    return {
        "charts": charts,
        "anchors": anchors,
        "note": _build_sequence_note(result),
        "segments": segments,
        "frames": [_frame_row(f, project) for f in frames],
    }


def _build_echem_channels(echem: "Mapping[str, Any]") -> list[dict[str, Any]]:
    """B4: echem 結果から viewmodel.channels の echem チャンネルを構築する (直近 in_span フレーム)。"""
    frames = list(echem.get("frames") or [])
    last = next((f for f in reversed(frames) if f.get("in_span")), None)
    if last is None:
        return []
    v = last.get("voltage_v")
    charge = last.get("charge_mah")
    parts = []
    if v is not None:
        parts.append(f"V {v:.3f}")
    if charge is not None:
        parts.append(f"Q {charge:.1f} mAh")
    value = " · ".join(parts) if parts else "no in-span frames"
    channels = [{"id": "echem", "label": "echem", "value": value}]
    targets = echem.get("targets")
    if targets:
        last_target = next((t for t in reversed(targets) if t.get("x_total") is not None), None)
        if last_target is not None:
            channels.append(
                {
                    "id": "alkali",
                    "label": "alkali budget x(t)",
                    "value": f"x_total {last_target['x_total']:.3f}",
                }
            )
    return channels


def _echem_state_summary(echem: "Mapping[str, Any]") -> "dict[str, Any] | None":
    """GET /api/state の ``project.echem`` (直近 in_span フレームの要約)。"""
    frames = list(echem.get("frames") or [])
    last = next((f for f in reversed(frames) if f.get("in_span")), None)
    if last is None:
        return None
    out: dict[str, Any] = {"v": last.get("voltage_v"), "q_mah_g": last.get("charge_mah")}
    targets = echem.get("targets")
    if targets:
        last_target = next((t for t in reversed(targets) if t.get("x_total") is not None), None)
        if last_target is not None:
            out["x_echem"] = last_target.get("x_total")
    return out
