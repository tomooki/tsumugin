"""ドメイン例外階層。"""

from __future__ import annotations


class TsumuginError(Exception):
    """Tsumugin 由来の例外の基底。"""


class GuardrailError(TsumuginError):
    """ガードレール(FR-210)が回復不能な状態を検知したときに送出。"""


class EscalationRequired(TsumuginError):
    """自動リトライ上限(FR-212, 既定3回)に達し人間/Triage へのエスカレーションが必要。"""


class InvalidPhaseSpecError(TsumuginError, ValueError):
    """相仕様 (`PhaseSpec`) がそのエンジンで実行できないとき。

    例 (TOPAS 経路): 相に無い原子ラベルを凍結・拘束に書いた / 3 原子以上の混合占有 /
    1 変数に束ねた組の一部だけを凍結した / TOPAS が実装していない指定を渡した
    (`topas.structure.PHASE_SPEC_FIELDS` の ``refused``)。精密化の**前**に送出されるので、
    ② はこれを ``{"error","error_type"}`` へ縮退させる (③ は LLM なので例外は回復不能)。
    ``ValueError`` も継ぐので、入力検証を ``ValueError`` で捕まえる既存の呼び手と互換。
    """


class GSASUnavailableError(TsumuginError):
    """GSAS-II (GSASIIscriptable) が未導入の環境で GSASIIBackend を要求したとき。"""


class TopasUnavailableError(TsumuginError):
    """Bruker TOPAS (コンソール実行体 ``tc.exe``) が未導入の環境で TOPAS 経路を要求したとき。

    ``GSASUnavailableError`` と同型の「available + 専用例外」パターン。``import tsumugin.topas``
    自体はコア (numpy/stdlib) のみで成功し、``tc.exe`` の実行を伴う経路 (``run_topas_rietveld`` /
    ``TopasBackend.__init__``) の呼び出し時にのみ本例外を送出して導入手順を案内する。
    TOPAS は PyPI に存在しない商用ソフトのため optional extra ではなく**外部バイナリ**として
    解決する (Dysnomia と同じ扱い)。
    """


class TopasRunError(TsumuginError):
    """``tc.exe`` の実行が失敗したとき (異常終了・タイムアウト・出力欠落)。

    **⚠ tc.exe は INP の構文エラーで異常終了しても終了コード 0 を返す** (実測)。したがって
    「終了コードが 0 だから成功」と読んではならず、driver は stdout の異常終了マーカーと
    出力ファイルの生成有無で判定する。GSAS-II の ``G2Project.refine`` が ``Refine`` の失敗戻り値を
    捨てる問題 (CLAUDE.md) と同じクラスの罠であり、同じ轍を踏まないための専用例外。

    精密化エンジン層はこの例外を捕まえて **chi2=inf / rwp=inf** へ縮退させ、ガードレールに
    処理させる (不変条件「バックエンドの失敗は例外でなく chi2=inf に変換」)。
    """


class TopasSymmetryError(TsumuginError):
    """CIF に対称操作が無く、TOPAS の ``Sg/`` からも補完できなかったとき (#219)。

    **空の対称操作で続行しない**ための専用例外。続行すると全サイトの自由軸が空になり
    座標段が何も解放しないまま完走する (ledger には「無言 no-op」としか残らない)。加えて
    特殊位置の吸着 (#172) も効かず、TOPAS が特殊位置を一般位置へ展開して**単位胞に存在
    しない原子が増える**ことがある。どちらも Rwp からは原因に辿り着けない。

    以前は補完の失敗を握りつぶして空タプルを返していたため、**同じ CIF でも「その空間群を
    過去に TOPAS で回した機械か」で結果が変わっていた** (NFR-102 違反)。対処は CIF に
    対称操作ループ (``_symmetry_equiv_pos_as_xyz`` / ``_space_group_symop_operation_xyz``) を
    足すか、空間群記号が TOPAS の受け付ける形かを確かめること。
    """


class TopasInputError(TsumuginError, ValueError):
    """TOPAS 経路の入力 (CIF・装置ファイル・観測データ) から INP を組めないとき。

    例: 装置ファイルから波長を読めない / CIF に空間群・セル・原子ループのいずれかが無い /
    対称操作の書式が読めない。組み立て側は ``ValueError`` で知らせるが、② の縮退
    (`mcp.rietveld_tools._run_degrading_domain_errors`) は**ドメインエラーだけ**を捕まえる
    (論理バグを「入力の誤り」に見せないため) ので、そのままでは例外が ② の境界を越える。
    `topas.engine.run_topas_rietveld` が INP を組む区間で入力の誤りをこれに包む。
    ``ValueError`` も継ぐので、従来の捕まえ方とも互換。
    """


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


class ConflictError(TsumuginError):
    """操作が現在の状態と両立しないため拒否されたとき (HTTP 409 相当)。🔵 V3a レビュー指摘 #2

    workbench 層 (`tsumugin.workbench.session`/`app`) が使う: 実行中の AUTO エージェントの
    1 ターン (`AgentBridge`) やジョブと衝突するモード切替/プロジェクト swap を拒否する際に送出する。
    多くの workbench メソッドは同種の衝突を ``{"error", "error_type": "ConflictError"}`` dict へ
    縮退させて返す規約だが (`request_refine` 等)、``set_mode`` は成功時に ``bool`` を返す既存契約
    (呼び出し側が真偽で分岐) のため、衝突時のみ本例外を送出し呼び出し側 (`app.py`) が 409 へ変換する。
    """


class MPUnavailableError(TsumuginError):
    """optional extra ``mp`` (pymatgen / mp-api) 未導入で Materials Project 供給元を要求したとき。🔵 FR-101

    ``NestedUnavailableError`` / ``OEDUnavailableError`` と対称の「available + 専用例外」パターン。
    ``import tsumugin.mp`` 自体はコア (numpy) のみで成功し、pymatgen / mp_api を引き込まない。
    実構造の XRD 生成 (``simulate_reference_peaks``) や MP クエリ (``MPRestClient.search``) の
    呼び出し時にのみ本例外を送出して extra 導入手順を案内する。相同定コア (``identify_phases``) と
    ``ReferenceProvider`` Protocol はコア (numpy) のみで動作する。
    """
