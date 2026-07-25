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

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..errors import WebUIUnavailableError
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
}


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
    from fastapi import Body, FastAPI
    from fastapi.responses import JSONResponse

    app = FastAPI(title="tsumugin Workbench", description="操作系 GUI バックエンド (v1)")

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

    # ------------------------------------------------------------------
    # GET /api/state, POST /api/mode
    # ------------------------------------------------------------------

    @app.get("/api/state")
    def get_state() -> dict[str, Any]:
        return session.state()

    @app.post("/api/mode")
    def post_mode(body: dict[str, Any] = Body(...)) -> Any:
        mode = body.get("mode")
        if mode not in ("manual", "auto"):
            return _invalid("mode", mode)
        session.set_mode(mode)
        return session.state()

    # ------------------------------------------------------------------
    # GET /api/viewmodel
    # ------------------------------------------------------------------

    @app.get("/api/viewmodel")
    def get_viewmodel() -> dict[str, Any]:
        return session.viewmodel()

    # ------------------------------------------------------------------
    # GET /api/hypotheses, POST /api/hypotheses/{id}/accept, POST /api/revert
    # ------------------------------------------------------------------

    @app.get("/api/hypotheses")
    def get_hypotheses() -> dict[str, Any]:
        return session.hypotheses_view()

    @app.post("/api/hypotheses/{hypothesis_id}/accept")
    def post_accept(hypothesis_id: str, body: dict[str, Any] = Body(default={})) -> Any:
        by = body.get("by", "human")
        if by not in ("human", "agent"):
            return _invalid("by", by)
        result = session.accept_hypothesis(hypothesis_id, by=by, reason=body.get("reason", ""))
        return _to_response(result)

    @app.post("/api/revert")
    def post_revert(body: dict[str, Any] = Body(...)) -> Any:
        hypothesis_id = body.get("hypothesis_id")
        if not hypothesis_id:
            return _invalid("hypothesis_id", hypothesis_id)
        result = session.revert_hypothesis(hypothesis_id, note=body.get("note", ""))
        return _to_response(result)

    # ------------------------------------------------------------------
    # GET /api/review-queue, POST /api/review-queue/{id}/resolve
    # ------------------------------------------------------------------

    @app.get("/api/review-queue")
    def get_review_queue() -> dict[str, Any]:
        return {"items": session.review_view()}

    @app.post("/api/review-queue/{item_id}/resolve")
    def post_review_resolve(item_id: str, body: dict[str, Any] = Body(...)) -> Any:
        action = body.get("action")
        if action not in ("accept", "send_back"):
            return _invalid("action", action)
        result = session.resolve_review_item(item_id, action=action, note=body.get("note", ""))
        return _to_response(result)

    # ------------------------------------------------------------------
    # GET /api/ledger
    # ------------------------------------------------------------------

    @app.get("/api/ledger")
    def get_ledger() -> dict[str, Any]:
        return session.ledger_view()

    # ------------------------------------------------------------------
    # POST /api/structure/apply
    # ------------------------------------------------------------------

    @app.post("/api/structure/apply")
    def post_structure_apply(body: dict[str, Any] = Body(...)) -> Any:
        sites = body.get("sites")
        if not isinstance(sites, list):
            return _invalid("sites", sites)
        result = session.apply_structure(sites, note=body.get("note", ""))
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/approval/{action_id}
    # ------------------------------------------------------------------

    @app.post("/api/approval/{action_id}")
    def post_approval(action_id: str, body: dict[str, Any] = Body(...)) -> Any:
        decision = body.get("decision")
        if decision not in ("approve", "reject"):
            return _invalid("decision", decision)
        result = session.resolve_approval(action_id, decision=decision)
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/stages/{nn}
    # ------------------------------------------------------------------

    @app.post("/api/stages/{nn}")
    def post_stage(nn: str, body: dict[str, Any] = Body(...)) -> Any:
        action = body.get("action")
        if action not in ("release", "revert"):
            return _invalid("action", action)
        result = session.stage_action(nn, action=action)
        return _to_response(result)

    # ------------------------------------------------------------------
    # POST /api/refine (202)
    # ------------------------------------------------------------------

    @app.post("/api/refine", status_code=202)
    def post_refine() -> dict[str, Any]:
        return session.request_refine()

    # ------------------------------------------------------------------
    # POST /api/transcript/message
    # ------------------------------------------------------------------

    @app.post("/api/transcript/message")
    def post_transcript_message(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return session.post_message(body.get("text", ""))

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
