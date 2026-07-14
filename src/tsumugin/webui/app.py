"""Web UI 最小版 (read-only 結果閲覧) — FastAPI アプリと配信層 (REQ-007 / 設計 D6)。

木探索の出力 ``SearchResult`` を、ローカルブラウザから**読み取り専用**で閲覧できる最小構成の
Web UI を提供する。ロジックは持たず ``SearchResult.to_summary()`` / ``result.hypotheses`` を
JSON 化して返すだけの、探索コア下流の薄い配信層 (architecture.md D6 / dataflow.md L90-123)。

公開 API (interfaces.py L221-233 契約):
    create_app(result) -> fastapi.FastAPI  … GET / (静的 HTML), GET /api/result,
        GET /api/hypotheses/{id} の 3 本のみを定義する read-only アプリ。
    serve(result, *, host="127.0.0.1", port=8765) -> None … uvicorn でローカル配信
        (ブロッキング)。既定は localhost バインド (NFR-101)。

read-only 保証 (REQ-007): GET 以外のルートを一切定義しない。POST/PUT/DELETE/PATCH や
未定義パスは FastAPI が自然に 405/404 を返す。書き込み口を構造的に作らない。

コア依存非汚染 (CLAUDE.md / D6): コアは numpy のみ。fastapi/uvicorn は optional extra
``web``。**fastapi/uvicorn の import は関数内へ遅延**させ、``import tsumugin.webui.app`` 自体は
web 未導入でも成功させる。未導入時は呼び出し時点で ``WebUIUnavailableError`` を送出する。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from .._json import finite_or_none
from ..errors import WebUIUnavailableError

if TYPE_CHECKING:  # 【型のみ参照】: 実行時 import を避けコア依存を汚染しない 🔵 D6
    from fastapi import FastAPI

    from ..model import Hypothesis, PhaseInstance, RefinementMetrics
    from ..search.tree import SearchResult

# 【静的 HTML パス】: wheel 同梱の single page。editable install でも確実な絶対解決 🟡 §3
_INDEX_HTML = Path(__file__).parent / "static" / "index.html"

# 【未導入誘導メッセージ】: extra web の導入手順 (pip / uv 両方) を明示する 🟡 §3
_WEB_EXTRA_HINT = (
    "Web UI には optional extra 'web' (fastapi/uvicorn) が必要です。"
    "`pip install 'tsumugin[web]'` または `uv sync --extra web` で導入してください。"
)


def _require_fastapi() -> Any:
    """fastapi モジュールを遅延 import し、未導入なら誘導エラーへ変換する。

    【機能概要】: ``import fastapi`` を関数内で行い、未導入 (ImportError) を
      ``WebUIUnavailableError`` (extra web 案内) へ変換する遅延 import ゲート。
    【実装方針】: モジュール読込時ではなく ``create_app`` / ``serve`` 呼び出し時に評価することで、
      web 未導入環境でも ``import tsumugin.webui.app`` を成功させる (D6 遅延 import 契約)。
    【テスト対応】: test_create_app_without_fastapi_raises_web_unavailable
      (sys.modules["fastapi"]=None 注入で ImportError を誘発)。
    🟡 信頼性レベル: 遅延 import 契約は §3 / CLAUDE.md 由来、例外変換は実装時確定。
    """
    try:
        # 【遅延 import】: 呼び出し時にのみ fastapi を要求する 🔵 D6
        import fastapi
    except ImportError as exc:  # 【未導入捕捉】: extra web 案内へ変換 🟡 §3
        raise WebUIUnavailableError(_WEB_EXTRA_HINT) from exc
    return fastapi


def _serialize_metrics(metrics: "RefinementMetrics | None") -> dict[str, Any] | None:
    """``RefinementMetrics`` を純 Python 型の dict へ写像する (metrics 全量)。

    【機能概要】: rwp/gof/chi2/n_obs/n_params/evidence を素の型へ明示変換する。
    【実装方針】: numpy スカラーを露出させないため ``float()``/``int()`` で純型化 (§2.4)。
      metrics=None ノード (境界値) は ``AttributeError`` を避け ``None`` を返す。
    【テスト対応】: test_hypothesis_detail_returns_full_json /
      _is_json_serializable_pure_types / _with_none_metrics。
    🟡 信頼性レベル: キー集合は api-endpoints.md 🔵、純型化方針は to_summary と同流儀 🟡。
    """
    # 【None 分岐】: metrics 未付与ノードは 500 化させず null で返す 🟡 §4
    if metrics is None:
        return None
    # 非有限 (chi2=inf は EDGE-004 の正常経路) は JSON に存在しないため None で配信する。
    # FastAPI の暗黙 inf→null 変換に依存せず、契約としてここで保証する (to_summary と同一規則)。
    return {
        "rwp": finite_or_none(metrics.rwp),
        "gof": finite_or_none(metrics.gof),
        "chi2": finite_or_none(metrics.chi2),
        "n_obs": int(metrics.n_obs),
        "n_params": int(metrics.n_params),
        # 【evidence 全量】: backend 名 -> 値を純型化して残らず配信する 🟡 §2.4
        # 【センチネル非関与】: 詳細 API が読む metrics.evidence は生 backend 値 (失敗ノードは inf)
        #   のため素の finite_or_none で足りる。センチネル純化は to_summary 経由 (tree) が担う 🔵
        "evidence": {str(k): finite_or_none(v) for k, v in metrics.evidence.items()},
        # 【Issue #64 / FR-123 σ の由来明示 (NFR-107)】: EM 推定していれば noise_scale を配信し、
        #   未推定 (既定 None) はそのまま null (finite_or_none は None 透過) 🔵
        "noise_scale": finite_or_none(metrics.noise_scale),
    }


def _serialize_phase(phase: "PhaseInstance") -> dict[str, Any]:
    """``PhaseInstance`` を詳細 JSON (格子は角度・sigma まで) へ写像する。

    【機能概要】: phase_ref/scale/wt_frac/occupancies/lattice を純型化する。格子は
      to_summary の a/b/c に加え alpha/beta/gamma/sigma まで含めてよい (§2.4)。
    【テスト対応】: test_hypothesis_detail_returns_full_json (相・格子キー網羅)。
    🟡 信頼性レベル: 含める内容は api-endpoints.md L54-58 に依拠。
    """
    lattice = phase.lattice
    return {
        "phase_ref": phase.phase_ref,
        "scale": float(phase.scale),
        # 【任意フィールド】: wt_frac は None 許容のため分岐して純型化 🟡
        "wt_frac": (float(phase.wt_frac) if phase.wt_frac is not None else None),
        "occupancies": {str(k): float(v) for k, v in phase.occupancies.items()},
        "lattice": {
            "a": float(lattice.a),
            "b": float(lattice.b),
            "c": float(lattice.c),
            "alpha": float(lattice.alpha),
            "beta": float(lattice.beta),
            "gamma": float(lattice.gamma),
            # 【sigma 全量】: 格子誤差 (±σ) も純型化して含める 🟡 §2.4
            "sigma": {str(k): float(v) for k, v in lattice.sigma.items()},
            # 【σ 由来明示】: "covariance"/"proxy"/"" を純型化して配信 (Issue #66 / NFR-107) 🔵
            "sigma_source": str(lattice.sigma_source),
        },
    }


def _serialize_hypothesis(hyp: "Hypothesis") -> dict[str, Any]:
    """``Hypothesis`` 1 件を詳細 JSON (相・格子・metrics 全量・系譜) へ写像する。

    【機能概要】: id/parent_id/status/phases/metrics を純 Python 型で組み立てる。
      ``to_summary()`` は per-id 詳細を提供しないため hypotheses から独自シリアライズする。
    【テスト対応】: test_hypothesis_detail_returns_full_json ほか詳細系。
    🟡 信頼性レベル: 構造は api-endpoints.md / interfaces.py に依拠。
    """
    return {
        "id": hyp.id,
        "parent_id": hyp.parent_id,
        "status": str(hyp.status),
        "phases": [_serialize_phase(p) for p in hyp.phases],
        "metrics": _serialize_metrics(hyp.metrics),
    }


def create_app(result: "SearchResult") -> "FastAPI":
    """read-only な Web UI アプリを構築して返す (interfaces.py L221-233)。

    【機能概要】: GET / (静的 index.html), GET /api/result (to_summary 配信),
      GET /api/hypotheses/{id} (詳細 or 404) の 3 本のみを持つ FastAPI アプリを返す。
    【実装方針】: fastapi は遅延 import し、未導入なら ``WebUIUnavailableError`` を送出する。
      変更系ルートを一切定義しないことで read-only を構造的に担保する (REQ-007)。app 側では
      ソート・加工を行わず ``to_summary()`` の決定論的順序をそのまま配信する (REQ-403)。
    【テスト対応】: tests/test_webui.py の正常系 N1-N7 / 異常系 E1-E5 / 境界値 B1-B5。
    🔵 信頼性レベル: シグネチャ・3 エンドポイント・エラー形状は要件/設計に確定。

    Args:
        result: 木探索の出力 ``SearchResult`` (``ranked`` / ``hypotheses`` / ``to_summary()``)。

    Returns:
        ``fastapi.FastAPI`` インスタンス (テストは TestClient で叩く)。

    Raises:
        WebUIUnavailableError: optional extra ``web`` (fastapi) 未導入のとき。
    """
    # 【遅延 import ゲート】: 未導入なら extra web 案内で早期に送出する 🔵 D6
    _require_fastapi()
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse

    # 【最小アプリ】: docs 等は既定のまま。read-only ゆえ変更系ルータは追加しない 🔵 REQ-007
    app = FastAPI(title="tsumugin Web UI", description="read-only 結果閲覧 (M1 最小版)")

    @app.get("/", response_class=FileResponse)
    def index() -> FileResponse:
        # 【トップページ】: 同梱の静的 index.html を text/html で配信する 🟡 TC-007-02
        return FileResponse(_INDEX_HTML, media_type="text/html")

    @app.get("/api/result")
    def api_result() -> dict[str, Any]:
        # 【結果配信】: to_summary() の純 dict を無改変で返す (numpy 混入なし) 🔵 TC-007-01
        return result.to_summary()

    @app.get("/api/hypotheses/{hypothesis_id}")
    def api_hypothesis(hypothesis_id: str) -> dict[str, Any]:
        # 【詳細ルックアップ】: ranked ではなく hypotheses 全体から引く (ranked ⊆ hypotheses) 🔵
        hyp = result.hypotheses.get(hypothesis_id)
        if hyp is None:
            # 【不明 id】: スタックトレースを露出せず 404 JSON へ整形する 🟡 TC-007-04
            raise HTTPException(status_code=404, detail="hypothesis not found")
        return _serialize_hypothesis(hyp)

    return app


def serve(
    result: "SearchResult", *, host: str = "127.0.0.1", port: int = 8765
) -> None:
    """``create_app(result)`` を uvicorn でローカル配信する (ブロッキング)。

    【機能概要】: 既定 ``127.0.0.1:8765`` (localhost バインド, NFR-101) で ASGI アプリを起動する。
    【実装方針】: fastapi/uvicorn を遅延 import し、未導入なら ``WebUIUnavailableError`` を送出する。
      呼び出しは ``uvicorn.run`` に委譲するブロッキング処理 (戻り値 None)。

    .. warning::
        本 UI に認証は無い。``host`` を ``127.0.0.1`` 以外 (例 ``0.0.0.0``) に変更すると、
        解析データ全量が同一ネットワークへ無認証で公開される。M1 はローカル閲覧専用であり、
        外部公開はサポートしない (NFR-101)。
    🟡 信頼性レベル: シグネチャ・既定値は interfaces.py L221-233 / NFR-101 に依拠、起動委譲は実装時確定。

    Args:
        result: 配信対象の ``SearchResult``。
        host: バインドホスト (kw-only)。既定 ``127.0.0.1`` (localhost)。
        port: バインドポート (kw-only)。既定 ``8765``。
    """
    # 【遅延 import ゲート】: fastapi 未導入なら create_app 内で extra web 案内が上がる 🔵 D6
    app = create_app(result)
    try:
        # 【uvicorn 遅延 import】: 起動時にのみ要求する (uvicorn も extra web) 🔵
        import uvicorn
    except ImportError as exc:  # 【未導入捕捉】: extra web 案内へ変換 🟡 §3
        raise WebUIUnavailableError(_WEB_EXTRA_HINT) from exc
    # 【ブロッキング配信】: localhost 既定でローカルサーバを起動する 🟡 NFR-101
    uvicorn.run(app, host=host, port=port)
