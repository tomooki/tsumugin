"""② list_review_queue / resolve_review_item (Review Queue 露出) の MCP テスト (Issue #125)。

背景: ``ReviewQueue`` (``src/tsumugin/selection/review_queue.py``) はエスカレーションを人間の
後追い確認のため蓄積する追記型キューで、① には実装済みだった。しかし ② にも ③ にも露出しておらず、
積まれた内容を人間が見る手段が存在しなかった。加えて queue を埋めるのは従来 ``FinalSelectionEngine.
decide()`` だけで、② ``accept_hypothesis`` は ``selection.accept()`` を直接呼び ``decide()`` を
迂回するため、②`list_review_queue` を足すだけでは常に空を返す DOA ツールになる (これは
``FinalSelectionEngine.accept()`` 側の修正 [tests/test_selection.py] で塞ぐ)。

本ファイルは ② 層の縮退契約 (例外を送出しない・空/不正入力を「正常」と答えない) を検証する。
"""

from __future__ import annotations

from tsumugin.backends.simulated import SimulatedBackend
from tsumugin.evidence.ic import BICBackend
from tsumugin.model.project import Project
from tsumugin.selection import FinalSelectionEngine, ReviewQueue
from tsumugin.store.ledger import Ledger
from tsumugin.store.snapshot import SnapshotStore

from tsumugin.mcp.tools import MCP_TOOLS, AnalysisSession, list_review_queue, resolve_review_item


def _session(selection: FinalSelectionEngine) -> AnalysisSession:
    ledger = Ledger()
    return AnalysisSession(
        project=Project(id="proj-0"),
        backend=SimulatedBackend(),
        selection=selection,
        ledger=ledger,
        snapshots=SnapshotStore(ledger=ledger),
        evidence=BICBackend(),
    )


# ---------------------------------------------------------------------------
# list_review_queue
# ---------------------------------------------------------------------------


def test_list_review_queue_errors_when_queue_not_injected():
    # 【テスト目的】: queue 未注入は「0 件」でなく error dict へ縮退する (最悪の失敗形を避ける)
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger())  # queue 未注入
    session = _session(selection)

    result = list_review_queue(session)

    assert result["status"] == "error"
    assert "error_type" in result  # 【確認内容】: 例外でなく型付き error dict 🔵


def test_list_review_queue_returns_unresolved_by_default():
    # 【テスト目的】: 既定は未解決のみを返す
    queue = ReviewQueue()
    queue.add("close_competitor", hypothesis_id="h1", frame_index=None, detail="a")
    queue.add("unknown_phase", hypothesis_id="h2", frame_index=3, detail="b")
    queue.resolve("rq-0000", note="ok")  # h1 を解決済みにする
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    result = list_review_queue(session)

    assert result["status"] == "ok"
    ids = [it["item_id"] for it in result["items"]]
    assert ids == ["rq-0001"]  # 【確認内容】: 未解決のみ (rq-0000 は除外) 🔵
    assert result["unresolved_count"] == 1
    assert result["total_count"] == 2


def test_list_review_queue_include_resolved_returns_all():
    # 【テスト目的】: include_resolved=True で解決済みも含めた全件が返る
    queue = ReviewQueue()
    queue.add("close_competitor", hypothesis_id="h1")
    queue.add("unknown_phase", hypothesis_id="h2")
    queue.resolve("rq-0000")
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    result = list_review_queue(session, include_resolved=True)

    ids = [it["item_id"] for it in result["items"]]
    assert ids == ["rq-0000", "rq-0001"]
    resolved_flags = {it["item_id"]: it["resolved"] for it in result["items"]}
    assert resolved_flags["rq-0000"] is True
    assert resolved_flags["rq-0001"] is False
    assert result["unresolved_count"] == 1
    assert result["total_count"] == 2


def test_list_review_queue_items_carry_all_fields():
    # 【テスト目的】: 各 item が仕様通りの全フィールドを持つ
    queue = ReviewQueue()
    queue.add("guard_escalated", hypothesis_id="h9", frame_index=2, detail="note")
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    result = list_review_queue(session)

    item = result["items"][0]
    assert item == {
        "item_id": "rq-0000",
        "reason": "guard_escalated",
        "hypothesis_id": "h9",
        "frame_index": 2,
        "detail": "note",
        "resolved": False,
    }


def test_list_review_queue_empty_queue_is_ok_not_error():
    # 【テスト目的】: 注入済みだが空の queue は正常 (0 件) であり error にしない
    queue = ReviewQueue()
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    result = list_review_queue(session)

    assert result["status"] == "ok"
    assert result["items"] == []
    assert result["unresolved_count"] == 0
    assert result["total_count"] == 0


def test_list_review_queue_is_deterministic():
    # 【テスト目的】: 同一状態への複数回呼び出しがビット同一の結果を返す (NFR-102)
    queue = ReviewQueue()
    queue.add("close_competitor", hypothesis_id="h1", frame_index=1)
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    assert list_review_queue(session) == list_review_queue(session)


# ---------------------------------------------------------------------------
# resolve_review_item
# ---------------------------------------------------------------------------


def test_resolve_review_item_marks_resolved_and_updates_count():
    # 【テスト目的】: 正常系で resolved 化し unresolved_count が減る
    queue = ReviewQueue()
    queue.add("close_competitor", hypothesis_id="h1")
    queue.add("unknown_phase", hypothesis_id="h2")
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    result = resolve_review_item(session, "rq-0000", note="human confirmed")

    assert result == {"status": "resolved", "item_id": "rq-0000", "unresolved_count": 1}
    assert queue.items[0].resolved is True
    assert len(queue.items) == 2  # 【確認内容】: 削除でなく状態遷移 (P2) 🔵


def test_resolve_review_item_unknown_id_returns_error_dict_not_exception():
    # 【テスト目的】: ① の KeyError を捕捉し error dict へ縮退する (② は例外を送出しない契約)
    queue = ReviewQueue()
    queue.add("close_competitor", hypothesis_id="h1")
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    result = resolve_review_item(session, "rq-9999")

    assert result["status"] == "error"
    assert "error_type" in result
    # 【非破壊】: 既存 item に影響しない
    assert queue.items[0].resolved is False


def test_resolve_review_item_errors_when_queue_not_injected():
    # 【テスト目的】: queue 未注入は error dict へ縮退する (例外を投げない)
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger())
    session = _session(selection)

    result = resolve_review_item(session, "rq-0000")

    assert result["status"] == "error"
    assert "error_type" in result


def test_resolve_review_item_is_deterministic():
    # 【テスト目的】: 同一操作の繰り返し呼び出しは(未知id経路で)ビット同一の error を返す
    queue = ReviewQueue()
    selection = FinalSelectionEngine(mode="agent", ledger=Ledger(), queue=queue)
    session = _session(selection)

    r1 = resolve_review_item(session, "rq-not-exist")
    r2 = resolve_review_item(session, "rq-not-exist")
    assert r1 == r2


# ---------------------------------------------------------------------------
# レジストリ登録 (② 到達可能性)
# ---------------------------------------------------------------------------


def test_review_tools_registered_in_mcp_tools():
    # 【テスト目的】: 両ツールが MCP_TOOLS に登録され ③ から名前で呼べる (§4.5 到達可能性)
    assert MCP_TOOLS["list_review_queue"] is list_review_queue
    assert MCP_TOOLS["resolve_review_item"] is resolve_review_item
