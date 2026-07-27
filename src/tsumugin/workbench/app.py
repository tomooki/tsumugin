"""操作系 FastAPI アプリ (`create_workbench_app` / `serve`) — `tsumugin.workbench` (設計 §バックエンド)。

`docs/design/gui-workbench/api-contract.md` の API 表面を実装する。ハンドラは例外を送出させず、
既知の失敗は ``{"error": ..., "error_type": ...}`` + 4xx へ縮退する (② と同じ流儀,
`src/tsumugin/mcp/tools.py` 冒頭)。**DELETE/PUT ルートは定義しない** (P2 / NFR-GUI-001) —
`tests/workbench/test_app.py` がルート表を構造的に走査してこれを担保する。

コア import 非汚染 (NFR-GUI-005): fastapi/uvicorn は関数内で遅延 import する。
``import tsumugin.workbench.app`` 自体は fastapi 未導入でも成功し、``create_workbench_app``/
``serve`` の呼び出し時点でのみ ``WebUIUnavailableError`` を送出する
(`src/tsumugin/webui/app.py` の ``_require_fastapi`` と同じ契約)。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from ..errors import ConflictError, LedgerIntegrityError, SnapshotIntegrityError, WebUIUnavailableError
from . import fsbrowse, lifecycle
from .session import WorkbenchSession

if TYPE_CHECKING:  # 【型のみ参照】: 実行時 import を避けコア依存を汚染しない 🔵
    from fastapi import FastAPI

_WEB_EXTRA_HINT = (
    "GUI ワークベンチには optional extra 'web' (fastapi/uvicorn) が必要です。"
    "`pip install 'tsumugin[web]'` または `uv sync --extra web` で導入してください。"
)

# 【エラー種別 → HTTP ステータス】: 不明 id は 404、値検証は 422、二重解決は 409 に縮退する。
_ERROR_STATUS: dict[str, int] = {
    "NotFoundError": 404,
    "KeyError": 404,
    "ConflictError": 409,
    "ValueError": 422,
    "LedgerIntegrityError": 422,
    "SnapshotIntegrityError": 422,
    # Tier1 sidecar (GSAS-II 抜き同梱) で GSAS 必須ジョブが起動されたときの縮退 (session.py
    # `_guard_gsas_available`)。
    "GSASUnavailableError": 422,
    # V3b (FR-601): POST /api/mem で Dysnomia バイナリが未解決のときの縮退 (session.py
    # `request_mem`)。
    "MEMUnavailableError": 422,
}

#: POST /api/project 系の「現在のセッションが refine 実行中」ガード共通メッセージ (api-contract.md)。
_REFINING_CONFLICT = {"error": "refinement is running", "error_type": "ConflictError"}

#: project ライフサイクルルート (create/open/close/demo) の「AUTO エージェントが実行中」ガード
#: 共通メッセージ (V3a レビュー指摘 #2)。実行中に swap すると、バックグラウンドスレッドが
#: 差し替え前後どちらのセッションに書き込むべきかが不定になる (`WorkbenchSession.agent_running`)。
_AGENT_RUNNING_CONFLICT = {"error": "agent is running", "error_type": "ConflictError"}


class _SessionHolder:
    """「現在のセッション」の差し替え口 (create_workbench_app が保持する可変ホルダ)。

    project の create/open/close/demo が ``.session`` を新しい ``WorkbenchSession`` へ差し替える。
    既存の全ルートハンドラはこのホルダ経由で最新セッションを読む (`create_workbench_app` の
    シグネチャ自体は互換維持 — 渡された ``session`` が初期値になる)。

    ``lock`` は project ライフサイクルルート (create/open/close/demo, セッション差し替え) の
    「ガード再確認 + I/O + swap」と、POST /api/refine の起動 (``request_refine`` 呼び出し) を
    **同一ロックで直列化**する (セルフレビュー指摘 #2, TOCTOU レース修正)。両者ともこのロックを
    保持している間は互いを待つため、「refine 実行中でないことを確認した直後にセッションが
    差し替わり、旧セッションの ledger へ独立した書き込み経路が生まれる」隙間が無くなる
    (`_guarded_swap`/`post_refine` 参照)。
    """

    def __init__(self, session: WorkbenchSession) -> None:
        self.session = session
        self.lock = threading.Lock()


def _require_fastapi() -> Any:
    """fastapi モジュールを遅延 import し、未導入なら誘導エラーへ変換する (`webui/app.py` と対称)。"""
    try:
        import fastapi
    except ImportError as exc:  # 【未導入捕捉】: extra web 案内へ変換 🔵
        raise WebUIUnavailableError(_WEB_EXTRA_HINT) from exc
    return fastapi


def _status_for(error_type: str) -> int:
    return _ERROR_STATUS.get(error_type, 400)


def create_workbench_app(
    session: WorkbenchSession, *, static_dir: "str | Path | None" = None
) -> "FastAPI":
    """操作系ワークベンチ FastAPI アプリを構築する。

    Args:
        session: 束ねる ``WorkbenchSession`` (呼び出し側が ``WorkbenchSession.create_demo()`` 等で用意)。
        static_dir: ビルド済み frontend の静的ファイルディレクトリ。存在すれば ``/`` で配信し、
            無ければ ``/`` は簡易な案内 JSON を返す (frontend 未ビルド環境でも起動できる)。

    Returns:
        ``fastapi.FastAPI`` インスタンス。

    Raises:
        WebUIUnavailableError: optional extra ``web`` (fastapi) 未導入のとき。
    """
    _require_fastapi()
    from fastapi import Body, FastAPI, File, Form, UploadFile
    from fastapi.responses import JSONResponse

    # 【from __future__ import annotations との相互作用】: 本モジュールは PEP 563 (遅延評価) が
    #   有効なため、ルートハンドラの型注釈は文字列として保持され、FastAPI が
    #   ``handler.__globals__`` (= このモジュールのグローバル名前空間) を使って解決する。
    #   ``UploadFile``/``File``/``Form`` はここ (関数ローカル) でしか import していないため、
    #   何もしないと ``post_project_upload`` の注釈解決が失敗する (`UploadFile` が未定義)。
    #   ``globals()`` はこの関数内で呼んでもモジュールの globals を指す (クロージャの
    #   ``__globals__`` は常にモジュール辞書) ので、ここへ差し込んで解決可能にする。
    globals().setdefault("UploadFile", UploadFile)
    globals().setdefault("File", File)
    globals().setdefault("Form", Form)

    app = FastAPI(title="tsumugin Workbench", description="操作系 GUI バックエンド (v1)")
    holder = _SessionHolder(session)

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(_request: Any, _exc: Exception) -> JSONResponse:
        """未知の例外を JSON error dict へ縮退させる恒久ガード (PR #120 系統欠陥の再発防止)。

        ハンドラ内で個別に捕捉していない例外 (実装漏れ・想定外のバグ) がここに落ちる。
        ③ は LLM であり、生の HTML/traceback は境界を貫通した時点でハード失敗になる —
        既知の失敗経路 (``_to_response``/``_invalid``) と同じ ``{"error", "error_type"}`` 形状を
        必ず維持する。
        """
        return JSONResponse(
            status_code=500,
            content={"error": "internal server error", "error_type": "internal_error"},
        )

    def _to_response(result: dict[str, Any], *, success_status: int = 200) -> Any:
        """session の返す純 dict をそのまま、または error dict なら 4xx JSONResponse へ変換する。"""
        if "error" in result and "error_type" in result:
            return JSONResponse(
                status_code=_status_for(str(result["error_type"])), content=result
            )
        if success_status == 200:
            return result
        return JSONResponse(status_code=success_status, content=result)

    def _invalid(field: str, value: Any) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": f"invalid {field}: {value!r}", "error_type": "ValueError"},
        )

    def _guard_not_refining() -> "JSONResponse | None":
        """project の spec 変更系ルート (upload/histograms/phases/settings) 共通ガード:

        現在のセッションで refine が実行中なら 409 (api-contract.md §プロジェクトライフサイクル
        「refine 実行中のプロジェクト変更系は 409」)。これらのルートはセッションを差し替えない
        (`_guarded_swap` 対象外) ため、`holder.lock` を取らない従来どおりの素通しチェックでよい —
        二重の防御として `WorkbenchSession._guard_project_editable` も同じ状態を確認する。
        """
        if holder.session.refine_status()["status"] == "running":
            return JSONResponse(status_code=409, content=dict(_REFINING_CONFLICT))
        return None

    def _guarded_swap(build_new_session: "Callable[[], WorkbenchSession]") -> Any:
        """project ライフサイクルルート (create/open/close/demo) 共通の直列化ヘルパ。

        「refine 実行中でないことの再確認」→「旧セッションの pending 承認カードを
        ``approval_abandoned`` として記録」→「新セッション構築 (I/O)」→「swap」を
        ``holder.lock`` 保持下で一括して行う (レビュー指摘 #1)。POST /api/refine (``post_refine``) も同じロックを
        取るため、この関数の実行中は refine の起動が待たされ (逆もまた然り)、guard 確認から
        swap までの間隙に別スレッドが旧セッションで refine を起動する TOCTOU が起きない
        (セルフレビュー指摘 #2)。

        同様に AUTO エージェント (`AgentBridge`) が実行中の swap も拒否する (V3a レビュー指摘 #2):
        ``AgentBridge`` は construction 時に束縛したクロージャ (``on_event``/``get_state_summary``)
        で旧セッションを指し続けるため、実行中に swap すると完了時のバックグラウンドスレッドが
        差し替え後のセッションから見えない旧セッションへ書き込む (更新が消える) か、新旧セッションの
        状態が混線する。

        ``build_new_session`` が送出する例外はロック解放後にそのまま呼び出し元 (route ハンドラ) へ
        伝播する — ``with`` 文がロック解放を保証するため、呼び出し元は例外の型ごとに 4xx へ
        変換すればよい。
        """
        with holder.lock:
            if holder.session.refine_status()["status"] == "running":
                return JSONResponse(status_code=409, content=dict(_REFINING_CONFLICT))
            if holder.session.agent_running():
                return JSONResponse(status_code=409, content=dict(_AGENT_RUNNING_CONFLICT))
            # 【レビュー指摘 #1: pending 承認カードの無記録消滅】: 旧セッションに未決
            #   (np-/sr-/rv-/pc-/st-) の承認カードが残っていれば、破棄する前に 1 件ごと
            #   ``approval_abandoned`` を旧セッションの ledger へ追記する — 何も記録せず消えると
            #   「agent_proposal はあるのに対応する決定が永久に現れない」状態になり、bypass では
            #   エージェント自身が自分の起票をこの経路で無記録に消せてしまう (P2 違反)。
            #   **人間の操作はブロックしない** (閉じられないと不便) — 記録した上で swap を進める。
            holder.session.abandon_pending_approvals()
            holder.session = build_new_session()
            return holder.session.state()

    # ------------------------------------------------------------------
    # GET /api/state, POST /api/mode
    # ------------------------------------------------------------------

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return holder.session.state()

    @app.post("/api/mode")
    def post_mode(body: dict[str, Any] = Body(...)) -> Any:
        mode = body.get("mode")
        if mode not in ("manual", "auto"):
            return _invalid("mode", mode)
        try:
            holder.session.set_mode(mode)
        except ConflictError as exc:
            return JSONResponse(
                status_code=409, content={"error": str(exc), "error_type": "ConflictError"}
            )
        return holder.session.state()

    # ------------------------------------------------------------------
    # GET /api/viewmodel
    # ------------------------------------------------------------------

    @app.get("/api/viewmodel")
    def get_viewmodel() -> dict[str, Any]:
        return holder.session.viewmodel()

    # ------------------------------------------------------------------
    # プロジェクトライフサイクル (V2a P1/P2, api-contract.md §プロジェクトライフサイクル)
    # ------------------------------------------------------------------

    @app.post("/api/project")
    def post_project_create(body: dict[str, Any] = Body(...)) -> Any:
        name = body.get("name")
        directory = body.get("directory")
        if not isinstance(name, str) or not name.strip():
            return _invalid("name", name)
        if not isinstance(directory, str) or not directory.strip():
            return _invalid("directory", directory)

        def _build() -> WorkbenchSession:
            return WorkbenchSession.open_persistent(lifecycle.create_project(name, directory))

        try:
            return _guarded_swap(_build)
        except ValueError as exc:
            return JSONResponse(
                status_code=409, content={"error": str(exc), "error_type": "ConflictError"}
            )
        except OSError as exc:
            return JSONResponse(
                status_code=422, content={"error": str(exc), "error_type": "ValueError"}
            )

    @app.post("/api/project/open")
    def post_project_open(body: dict[str, Any] = Body(...)) -> Any:
        path = body.get("path")
        if not isinstance(path, str) or not path.strip():
            return _invalid("path", path)

        def _build() -> WorkbenchSession:
            project = lifecycle.open_project(path)
            return WorkbenchSession.open_persistent(project)

        try:
            return _guarded_swap(_build)
        except FileNotFoundError as exc:
            # 【パス不存在 (セルフレビュー指摘 #3)】: `lifecycle.open_project` がプロジェクト
            #   ディレクトリ/project.json 自体の不在を型で示す (ValueError と区別)。
            return JSONResponse(
                status_code=404, content={"error": str(exc), "error_type": "NotFoundError"}
            )
        except LedgerIntegrityError as exc:
            return JSONResponse(
                status_code=422,
                content={"error": str(exc), "error_type": "LedgerIntegrityError"},
            )
        except SnapshotIntegrityError as exc:
            return JSONResponse(
                status_code=422,
                content={"error": str(exc), "error_type": "SnapshotIntegrityError"},
            )
        except ValueError as exc:
            # 【spec 不正 (セルフレビュー指摘 #3)】: JSON 壊れ/必須キー欠落/不正 enum/参照データ
            #   ファイル欠落 (`load_project_spec` が OSError から正規化, セルフレビュー指摘 #1) 等。
            #   パスは見つかっている (found) が内容が不正、という意味で 404 でなく 422。
            return JSONResponse(
                status_code=422, content={"error": str(exc), "error_type": "ValueError"}
            )

    @app.post("/api/project/close")
    def post_project_close() -> Any:
        return _guarded_swap(lambda: WorkbenchSession.create_empty())

    @app.post("/api/project/demo")
    def post_project_demo() -> Any:
        return _guarded_swap(lambda: WorkbenchSession.create_demo())

    @app.get("/api/project/recent")
    def get_project_recent() -> dict[str, Any]:
        return {"projects": lifecycle.load_recent()}

    # ------------------------------------------------------------------
    # GET /api/fs/roots, GET /api/fs/list (Welcome のアプリ内ファイル選択ウィンドウ,
    # api-contract.md §ファイル選択)
    # ------------------------------------------------------------------

    @app.get("/api/fs/roots")
    def get_fs_roots() -> dict[str, Any]:
        return {"roots": fsbrowse.list_roots()}

    @app.get("/api/fs/list")
    def get_fs_list(path: "str | None" = None) -> Any:
        if not isinstance(path, str) or not path.strip():
            return _invalid("path", path)
        try:
            return fsbrowse.list_dir(path)
        except FileNotFoundError as exc:
            return JSONResponse(
                status_code=404, content={"error": str(exc), "error_type": "NotFoundError"}
            )
        except (NotADirectoryError, PermissionError, ValueError) as exc:
            return JSONResponse(
                status_code=422, content={"error": str(exc), "error_type": "ValueError"}
            )

    @app.post("/api/project/upload")
    async def post_project_upload(
        file: UploadFile = File(...), kind: str = Form(...)
    ) -> Any:
        if kind not in ("data", "instrument", "structure", "echem"):
            return _invalid("kind", kind)
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        content = await file.read()
        result = holder.session.store_upload(file.filename or "upload.bin", content)
        return _to_response(result)

    @app.post("/api/project/histograms")
    def post_project_histograms(body: dict[str, Any] = Body(...)) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        result = holder.session.add_histogram(
            data_path=body.get("data_path"),
            instrument_path=body.get("instrument_path"),
            radiation=body.get("radiation"),
            geometry=body.get("geometry"),
            data_format=body.get("data_format", "GSAS"),
            two_theta_limits=body.get("two_theta_limits"),
            bank=body.get("bank"),
        )
        return _to_response(result)

    @app.post("/api/project/histograms/{hist_id}/remove")
    def post_project_histograms_remove(hist_id: str, body: dict[str, Any] = Body(default={})) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        result = holder.session.remove_histogram(hist_id)
        return _to_response(result)

    @app.post("/api/project/phases")
    def post_project_phases(body: dict[str, Any] = Body(...)) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        result = holder.session.add_phase(
            structure_path=body.get("structure_path"), phase_name=body.get("phase_name")
        )
        return _to_response(result)

    @app.post("/api/project/phases/{phase_name}/remove")
    def post_project_phases_remove(phase_name: str, body: dict[str, Any] = Body(default={})) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        result = holder.session.remove_phase(phase_name)
        return _to_response(result)

    @app.post("/api/project/phases/{phase_name}/settings")
    def post_project_phase_settings(phase_name: str, body: dict[str, Any] = Body(...)) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        # 型検証は `set_phase_settings` に一元化する (ここで先回りしない)。
        result = holder.session.set_phase_settings(
            phase_name, refine_cell=body.get("refine_cell")
        )
        return _to_response(result)

    @app.post("/api/project/settings")
    def post_project_settings(body: dict[str, Any] = Body(...)) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        result = holder.session.update_settings(
            two_theta_limits=body.get("two_theta_limits"),
            background_coeffs=body.get("background_coeffs"),
            max_cyc=body.get("max_cyc"),
        )
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/project/frames (V2b B1)
    # ------------------------------------------------------------------

    @app.post("/api/project/frames")
    def post_project_frames(body: dict[str, Any] = Body(...)) -> Any:
        guard = _guard_not_refining()
        if guard is not None:
            return guard
        frames = body.get("frames")
        if not isinstance(frames, list):
            return _invalid("frames", frames)
        result = holder.session.set_frames(frames, frame_axis=body.get("frame_axis"))
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/sequential, GET /api/sequential/status (V2b B2/B3)
    # ------------------------------------------------------------------

    @app.post("/api/sequential")
    def post_sequential(body: dict[str, Any] = Body(default={})) -> Any:
        mode = body.get("mode", "forward")
        if mode not in ("forward", "anchored"):
            return _invalid("mode", mode)
        result = holder.session.request_sequential(
            mode=mode,
            anchor_table=body.get("anchor_table"),
            use_charge_constraint=bool(body.get("use_charge_constraint", False)),
        )
        return _to_response(result, success_status=202)

    @app.get("/api/sequential/status")
    def get_sequential_status() -> dict[str, Any]:
        return holder.session.refine_status()

    # ------------------------------------------------------------------
    # POST /api/echem (V2b B4)
    # ------------------------------------------------------------------

    @app.post("/api/echem")
    def post_echem(body: dict[str, Any] = Body(...)) -> Any:
        mpr_path = body.get("mpr_path")
        if not isinstance(mpr_path, str) or not mpr_path.strip():
            return _invalid("mpr_path", mpr_path)
        sign = body.get("sign", 1)
        if sign not in (1, -1):
            return _invalid("sign", sign)
        result = holder.session.request_echem(
            mpr_path=mpr_path,
            offset_s=body.get("offset_s"),
            interval_s=body.get("interval_s"),
            n_frames=body.get("n_frames"),
            frame_epoch_s=body.get("frame_epoch_s"),
            sign=sign,
            x0=body.get("x0"),
            active_mass_mg=body.get("active_mass_mg"),
            formula_weight=body.get("formula_weight"),
            z=body.get("z", 1),
            x0_source=body.get("x0_source", "given"),
            clamp=bool(body.get("clamp", False)),
        )
        return _to_response(result)

    # ------------------------------------------------------------------
    # GET /api/hypotheses, POST /api/hypotheses/{id}/accept, POST /api/revert
    # ------------------------------------------------------------------

    @app.get("/api/hypotheses")
    def get_hypotheses() -> dict[str, Any]:
        return holder.session.hypotheses_view()

    @app.post("/api/hypotheses/{hypothesis_id}/accept")
    def post_accept(hypothesis_id: str, body: dict[str, Any] = Body(default={})) -> Any:
        by = body.get("by", "human")
        if by not in ("human", "agent"):
            return _invalid("by", by)
        result = holder.session.accept_hypothesis(
            hypothesis_id, by=by, reason=body.get("reason", "")
        )
        return _to_response(result)

    @app.post("/api/revert")
    def post_revert(body: dict[str, Any] = Body(...)) -> Any:
        hypothesis_id = body.get("hypothesis_id")
        if not hypothesis_id:
            return _invalid("hypothesis_id", hypothesis_id)
        result = holder.session.revert_hypothesis(hypothesis_id, note=body.get("note", ""))
        return _to_response(result)

    # ------------------------------------------------------------------
    # GET /api/review-queue, POST /api/review-queue/{id}/resolve
    # ------------------------------------------------------------------

    @app.get("/api/review-queue")
    def get_review_queue() -> dict[str, Any]:
        return {"items": holder.session.review_view()}

    @app.post("/api/review-queue/{item_id}/resolve")
    def post_review_resolve(item_id: str, body: dict[str, Any] = Body(...)) -> Any:
        action = body.get("action")
        if action not in ("accept", "send_back"):
            return _invalid("action", action)
        result = holder.session.resolve_review_item(
            item_id, action=action, note=body.get("note", "")
        )
        return _to_response(result)

    # ------------------------------------------------------------------
    # GET /api/ledger
    # ------------------------------------------------------------------

    @app.get("/api/ledger")
    def get_ledger() -> dict[str, Any]:
        return holder.session.ledger_view()

    # ------------------------------------------------------------------
    # POST /api/structure/apply
    # ------------------------------------------------------------------

    @app.post("/api/structure/apply")
    def post_structure_apply(body: dict[str, Any] = Body(...)) -> Any:
        sites = body.get("sites")
        if not isinstance(sites, list):
            return _invalid("sites", sites)
        if not all(isinstance(site, dict) for site in sites):
            return _invalid("sites", sites)
        result = holder.session.apply_structure(sites, note=body.get("note", ""))
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/approval/{action_id}
    # ------------------------------------------------------------------

    @app.post("/api/approval/{action_id}")
    def post_approval(action_id: str, body: dict[str, Any] = Body(...)) -> Any:
        decision = body.get("decision")
        if decision not in ("approve", "reject"):
            return _invalid("decision", decision)
        result = holder.session.resolve_approval(action_id, decision=decision)
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/proposals, GET /api/proposals (ModelAction 起票, V3a 権限境界改訂)
    # ------------------------------------------------------------------

    @app.post("/api/proposals")
    def post_proposal(body: dict[str, Any] = Body(...)) -> Any:
        kind = body.get("kind")
        payload = body.get("payload")
        if not isinstance(kind, str):
            return _invalid("kind", kind)
        if not isinstance(payload, dict):
            return _invalid("payload", payload)
        result = holder.session.create_proposal(kind, payload, rationale=body.get("rationale", ""))
        return _to_response(result)

    @app.get("/api/proposals")
    def get_proposals() -> dict[str, Any]:
        return {"pending": holder.session.pending_approvals()}

    # ------------------------------------------------------------------
    # POST /api/stages/{nn}
    # ------------------------------------------------------------------

    @app.post("/api/stages/{nn}")
    def post_stage(nn: str, body: dict[str, Any] = Body(...)) -> Any:
        action = body.get("action")
        if action not in ("release", "revert"):
            return _invalid("action", action)
        result = holder.session.stage_action(nn, action=action)
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/refine (202 / 409), GET /api/refine/status
    # ------------------------------------------------------------------

    @app.post("/api/refine")
    def post_refine(body: dict[str, Any] = Body(default={})) -> Any:
        # 【holder.lock で直列化 (セルフレビュー指摘 #2)】: `_guarded_swap` (project
        #   create/open/close/demo) と同一ロックを取ることで、「refine 起動」と「セッション
        #   差し替え」が互いを待つ。ロック自体は起動判定のみを覆う (`request_refine` は project
        #   モードでもバックグラウンドスレッドを起動するだけで即座に返る — 精密化本体の実行中は
        #   ロックを保持しない)。
        stages_on = body.get("stages_on")
        if stages_on is not None:
            if not isinstance(stages_on, dict) or not all(
                isinstance(k, str) and isinstance(v, bool) for k, v in stages_on.items()
            ):
                return _invalid("stages_on", stages_on)
        with holder.lock:
            result = holder.session.request_refine(stages_on=stages_on)
        return _to_response(result, success_status=202)

    @app.get("/api/refine/status")
    def get_refine_status() -> dict[str, Any]:
        return holder.session.refine_status()

    # ------------------------------------------------------------------
    # POST /api/phaseid, GET /api/phaseid/status, POST /api/phaseid/add (A4)
    # ------------------------------------------------------------------

    @app.post("/api/phaseid")
    def post_phaseid(body: dict[str, Any] = Body(default={})) -> Any:
        mode = body.get("mode", "pattern")
        if mode not in ("pattern", "residual"):
            return _invalid("mode", mode)
        top_k = body.get("top_k", 5)
        try:
            top_k = int(top_k)
        except (TypeError, ValueError):
            return _invalid("top_k", top_k)
        # elements 省略 (None) = 現相集合の CIF から導出 (従来動作)。値の検証は
        # `request_phaseid` (`_normalise_elements`) に一元化する — ここで先回りしない。
        result = holder.session.request_phaseid(
            mode=mode, top_k=top_k, elements=body.get("elements")
        )
        return _to_response(result, success_status=202)

    @app.get("/api/phaseid/status")
    def get_phaseid_status() -> dict[str, Any]:
        return holder.session.refine_status()

    @app.post("/api/phaseid/add")
    def post_phaseid_add(body: dict[str, Any] = Body(...)) -> Any:
        formula = body.get("formula")
        mp_id = body.get("mp_id")
        if not formula or not mp_id:
            return _invalid("formula/mp_id", body)
        result = holder.session.phaseid_add(formula=formula, mp_id=mp_id)
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/multistart, GET /api/multistart/status (A5)
    # ------------------------------------------------------------------

    @app.post("/api/multistart")
    def post_multistart(body: dict[str, Any] = Body(default={})) -> Any:
        n_starts, scale = body.get("n_starts", 3), body.get("scale", 0.007)
        try:
            n_starts = int(n_starts)
            scale = float(scale)
        except (TypeError, ValueError):
            return _invalid("n_starts/scale", body)
        result = holder.session.request_multistart(n_starts=n_starts, scale=scale)
        return _to_response(result, success_status=202)

    @app.get("/api/multistart/status")
    def get_multistart_status() -> dict[str, Any]:
        return holder.session.refine_status()

    # ------------------------------------------------------------------
    # POST /api/mem, GET /api/mem/status (V3b, FR-601)
    # ------------------------------------------------------------------

    @app.post("/api/mem")
    def post_mem(body: dict[str, Any] = Body(default={})) -> Any:
        map_type = body.get("map_type", "Fobs")
        if map_type not in ("Fobs", "delt-F"):
            return _invalid("map_type", map_type)
        dmin, grid_step = body.get("dmin", 0.9), body.get("grid_step", 0.25)
        try:
            dmin = float(dmin)
            grid_step = float(grid_step)
        except (TypeError, ValueError):
            return _invalid("dmin/grid_step", body)
        result = holder.session.request_mem(
            phase=body.get("phase"), hist=body.get("hist"),
            map_type=map_type, dmin=dmin, grid_step=grid_step,
        )
        return _to_response(result, success_status=202)

    @app.get("/api/mem/status")
    def get_mem_status() -> dict[str, Any]:
        return holder.session.refine_status()

    # ------------------------------------------------------------------
    # GET /api/export/gpx (A6)
    # ------------------------------------------------------------------

    @app.get("/api/export/gpx")
    def get_export_gpx() -> Any:
        from fastapi.responses import FileResponse

        info = holder.session.export_gpx_info()
        if "error" in info:
            return _to_response(info)
        return FileResponse(
            info["path"], filename=info["filename"], media_type="application/octet-stream"
        )

    # ------------------------------------------------------------------
    # POST /api/transcript/message
    # ------------------------------------------------------------------

    @app.post("/api/transcript/message")
    def post_transcript_message(body: dict[str, Any] = Body(...)) -> Any:
        result = holder.session.post_message(body.get("text", ""))
        success_status = 202 if result.get("status") == "agent_started" else 200
        return _to_response(result, success_status=success_status)

    # ------------------------------------------------------------------
    # アプリ設定 (資格情報) — Materials Project トークン (api-contract.md §アプリ設定)
    # ------------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return holder.session.get_settings()

    @app.post("/api/settings")
    def post_settings(body: dict[str, Any] = Body(...)) -> Any:
        result = holder.session.save_settings(mp_api_key=body.get("mp_api_key"))
        return _to_response(result)

    @app.post("/api/settings/clear")
    def post_settings_clear(body: dict[str, Any] = Body(...)) -> Any:
        result = holder.session.clear_settings(body.get("key"))
        return _to_response(result)

    # ------------------------------------------------------------------
    # GET /api/agent/status (V3a)
    # ------------------------------------------------------------------

    @app.get("/api/agent/status")
    def get_agent_status() -> dict[str, Any]:
        return holder.session.agent_status()

    # ------------------------------------------------------------------
    # POST /api/agent/policy (エージェント権限モード, 2026-07-26 権限境界改訂)
    # ------------------------------------------------------------------

    @app.post("/api/agent/policy")
    def post_agent_policy(body: dict[str, Any] = Body(...)) -> Any:
        policy = body.get("policy")
        if policy not in ("approve", "auto", "bypass"):
            return _invalid("policy", policy)
        try:
            holder.session.set_agent_policy(policy)
        except ConflictError as exc:
            return JSONResponse(
                status_code=409, content={"error": str(exc), "error_type": "ConflictError"}
            )
        return holder.session.state()

    # ------------------------------------------------------------------
    # 静的配信 (ビルド済み frontend があれば / で配信、無ければ案内 JSON)
    # ------------------------------------------------------------------

    resolved_static = Path(static_dir) if static_dir is not None else None
    if resolved_static is not None and resolved_static.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(resolved_static), html=True), name="frontend")
    else:

        @app.get("/")
        def index() -> dict[str, Any]:
            return {
                "app": "tsumugin workbench",
                "hint": "frontend not built; use /api/* endpoints (see /docs)",
            }

    return app


def serve(
    session: WorkbenchSession,
    *,
    host: str = "127.0.0.1",
    port: int = 8770,
    static_dir: "str | Path | None" = None,
) -> None:
    """``create_workbench_app(session)`` を uvicorn でローカル配信する (ブロッキング)。

    .. warning::
        認証は無い。``host`` を ``127.0.0.1`` 以外に変更すると解析データ全量が同一ネットワークへ
        無認証で公開される (NFR-GUI-003)。
    """
    app = create_workbench_app(session, static_dir=static_dir)
    try:
        import uvicorn
    except ImportError as exc:  # 【未導入捕捉】: extra web 案内へ変換 🔵
        raise WebUIUnavailableError(_WEB_EXTRA_HINT) from exc
    uvicorn.run(app, host=host, port=port)
