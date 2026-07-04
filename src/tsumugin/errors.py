"""ドメイン例外階層。"""

from __future__ import annotations


class TsumuginError(Exception):
    """Tsumugin 由来の例外の基底。"""


class GuardrailError(TsumuginError):
    """ガードレール(FR-210)が回復不能な状態を検知したときに送出。"""


class EscalationRequired(TsumuginError):
    """自動リトライ上限(FR-212, 既定3回)に達し人間/Triage へのエスカレーションが必要。"""


class GSASUnavailableError(TsumuginError):
    """GSAS-II (GSASIIscriptable) が未導入の環境で GSASIIBackend を要求したとき。"""


class LedgerIntegrityError(TsumuginError):
    """永続 ledger (JSONL) の破損を検出したときに送出 (EDGE-003 / NFR-105)。

    ハッシュ不整合・prev_hash 断裂・index 不連続・不正 JSON 行を再オープン時に検出する。
    検出時にファイルの修復・上書き・切り詰めは一切行わない（無修復 / P2）。
    """


class SnapshotIntegrityError(TsumuginError):
    """永続 snapshot (JSONL) の破損 (不正 JSON 行・必須キー欠落) を検出したときに送出。

    ``LedgerIntegrityError`` と対称の fail-loud。検出時にファイルの修復・上書き・
    切り詰めは一切行わない (無修復 / P2)。
    """


class WebUIUnavailableError(TsumuginError):
    """optional extra ``web`` (fastapi/uvicorn) 未導入の環境で Web UI を要求したとき。

    ``GSASUnavailableError`` と対称の「available + 専用例外」パターン。``create_app`` /
    ``serve`` の遅延 import 契約 (D6): ``import tsumugin.webui.app`` 自体は web 未導入でも成功し、
    ``create_app`` / ``serve`` の呼び出し時点でのみ本例外を送出して extra 導入手順を案内する。
    """


class MCPUnavailableError(TsumuginError):
    """optional extra ``mcp`` (mcp SDK) 未導入環境で MCP サーバ起動 API を要求したとき。🔵 REQ-102

    ``WebUIUnavailableError`` と対称。``import tsumugin.mcp.server`` 自体は成功し、
    ``create_mcp_server`` / ``serve_stdio`` 呼び出し時にのみ本例外を送出して extra 導入を案内する。
    ツール実処理関数 (``mcp.tools``) は SDK 非依存で本例外に依存せず動作する。
    """


class MEMUnavailableError(TsumuginError):
    """MEM バックエンド (M5 / FR-601〜606) 未実装のまま ``run_mem`` を要求したとき。🔵 REQ-101

    破壊的操作を伴わず「M5 で提供予定」を明示する。既定は本例外送出だが、呼び出し側スキーマ互換の
    プレースホルダ dict 応答へ切替可能 (D9)。
    """


class NestedUnavailableError(TsumuginError):
    """optional extra ``nested`` (dynesty / ultranest) 未導入で nested 実行 API を要求したとき。🔵 REQ-005/EDGE-001

    ``MCPUnavailableError`` 系と対称の「available + 専用例外」パターン。``import tsumugin.nested`` /
    ``import tsumugin.nested.sampler`` 自体はコア (numpy) のみで成功し、``NestedBackend.score_problem``
    (実サンプラを起動する経路) の呼び出し時にのみ本例外を送出して extra 導入手順を案内する。
    laplace evidence・階層的裁定・較正はコア (numpy) のみで動作する。
    """


class OEDUnavailableError(TsumuginError):
    """optional extra ``oed`` (pyboed) 未導入で獲得関数接続 API を要求したとき。🔵 REQ-036/EDGE-011

    ``NestedUnavailableError`` と対称。PyBOED 獲得関数を用いた高度な情報利得評価 (``acquire`` 接続境界)
    の呼び出し時にのみ本例外を送出して extra 導入手順を案内する。v1 の提案生成 (``propose_measurements``)
    は本例外に依存せず外部依存なしで動作する。
    """
